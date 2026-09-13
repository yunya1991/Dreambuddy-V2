"""GridTradingEngine — 网格交易策略（震荡市波动套利层）

策略原理（参考 SPEC Phase C + 调研报告）：
  - 间距 Δ = ATR × k（k=1.0~2.0，币种自适应）
  - 网格数 N = (P_high - P_low) / Δ，最多 20 格
  - 单格金额 = 仓位预算 × 递减比例（5%）
  - 硬止损 8%（HC-TF-05）
  - 趋势市暂停（HC-TF-05）

与 V15 倒金字塔叠加：
  - 网格处理小波动（ATR 间距）
  - V15 处理大波动（8% 间距）
  - 不同波动尺度互补

FAIL-OPEN 原则（HC-TF-07）：
  任何异常 → 返回中性兜底 {"action": "WAIT"}，不抛异常
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ====================================================================
# 常量（硬约束对齐）
# ====================================================================
GRID_ATR_MULTIPLIER = 1.0        # Δ = 1×ATR（可调 1.0~2.0）
GRID_MAX_COUNT = 20              # 最多 20 格
GRID_SINGLE_BUDGET_RATIO = 0.05  # 单格 = 5% 仓位预算（递减式）

GRID_STOP_LOSS_PCT = 0.08         # 跌破下界 8% 停止加仓（HC-TF-05）
GRID_REGIME_FILTER = True         # 趋势市暂停网格（HC-TF-05）


class GridParameterCalculator:
    """网格参数计算器"""

    @staticmethod
    def calc_params(kline_data: dict, budget: float) -> dict:
        """计算网格参数

        Args:
            kline_data: {"close": [...], "high": [...], "low": [...]}
            budget: 仓位预算（USDT）

        Returns:
            {
                "spacing": float,      # 间距 Δ
                "grid_count": int,     # 网格数 N
                "single_budget": float, # 单格金额
                "grid_upper": float,   # 上界
                "grid_lower": float,   # 下界
            }
        """
        try:
            highs = list(kline_data.get("high") or [])
            lows = list(kline_data.get("low") or [])
            closes = list(kline_data.get("close") or [])

            if not highs or not lows or not closes:
                return {"spacing": 0.0, "grid_count": 0, "single_budget": 0.0,
                        "grid_upper": 0.0, "grid_lower": 0.0}

            # 计算 ATR（复用 V15 signal 模块）
            try:
                import sys
                from pathlib import Path
                v15_core = Path(__file__).resolve().parents[3] / "14-V15经典马丁策略" / "core"
                if str(v15_core) not in sys.path:
                    sys.path.insert(0, str(v15_core))
                from v15_signal import calc_atr  # type: ignore
            except ImportError:
                def calc_atr(highs, lows, closes, period=14):
                    if len(closes) < period + 1:
                        return 0.0
                    tr_list = []
                    for i in range(1, len(closes)):
                        tr = max(highs[i] - lows[i],
                                 abs(highs[i] - closes[i - 1]),
                                 abs(lows[i] - closes[i - 1]))
                        tr_list.append(tr)
                    return sum(tr_list[-period:]) / min(period, len(tr_list)) if tr_list else 0.0

            atr = calc_atr(highs, lows, closes, period=14)

            # 间距 Δ = ATR × k
            spacing = atr * GRID_ATR_MULTIPLIER
            if spacing <= 0:
                # 兜底：用价格 1%
                current_price = float(closes[-1])
                spacing = current_price * 0.01

            # 上界/下界：当前价 ± N×spacing
            current_price = float(closes[-1])
            grid_upper = current_price + GRID_MAX_COUNT * spacing / 2
            grid_lower = current_price - GRID_MAX_COUNT * spacing / 2

            # 网格数 N = (P_high - P_low) / Δ
            grid_count = int((grid_upper - grid_lower) / spacing)
            grid_count = min(grid_count, GRID_MAX_COUNT)

            # 单格金额 = 仓位预算 × 5%（递减式）
            single_budget = budget * GRID_SINGLE_BUDGET_RATIO

            return {
                "spacing": round(spacing, 6),
                "grid_count": grid_count,
                "single_budget": round(single_budget, 6),
                "grid_upper": round(grid_upper, 6),
                "grid_lower": round(grid_lower, 6),
                "atr": round(atr, 6),
            }
        except Exception as e:
            logger.warning("[FO] GridParameterCalculator.calc_params: %s", e)
            return {"spacing": 0.0, "grid_count": 0, "single_budget": 0.0,
                    "grid_upper": 0.0, "grid_lower": 0.0}


class GridRiskGate:
    """网格风险闸门（HC-TF-05：硬止损 8%，趋势市暂停）"""

    @staticmethod
    def check_stop(position: dict, kline_data: dict) -> bool:
        """检查是否触发硬止损

        跌破下界 8% → 停止加仓（HC-TF-05）

        Args:
            position: {"grid_lower": float}
            kline_data: {"close": [...]}

        Returns:
            True=应停止加仓，False=可继续
        """
        try:
            grid_lower = float(position.get("grid_lower", 0))
            closes = list(kline_data.get("close") or [])
            if not closes or grid_lower <= 0:
                return False

            current_price = float(closes[-1])
            # 跌破下界 8% → 停止
            stop_line = grid_lower * (1 - GRID_STOP_LOSS_PCT)
            return current_price < stop_line
        except Exception as e:
            logger.warning("[FO] GridRiskGate.check_stop: %s", e)
            return True  # 异常时保守停止

    @staticmethod
    def should_pause(regime: str = "RANGE") -> bool:
        """趋势市是否应暂停网格（HC-TF-05）

        Args:
            regime: "TREND" / "RANGE" / "CRISIS"

        Returns:
            True=应暂停，False=可运行
        """
        try:
            if not GRID_REGIME_FILTER:
                return False
            return regime.upper() in ("TREND", "CRISIS")
        except Exception:
            return True  # 异常时保守暂停


class GridTradingEngine:
    """网格交易主引擎

    与 V15 倒金字塔在不同波动尺度叠加：
      网格：ATR 间距，处理小波动
      V15：8% 间距，处理大波动

    由 RegimeGateSwitch 在 regime=RANGE 时调用。
    """

    @staticmethod
    def evaluate(kline_data: dict, account_state: dict) -> dict:
        """评估网格交易信号

        Args:
            kline_data: {"close": [...], "high": [...], "low": [...]}
            account_state: {"equity": float, "regime": str}

        Returns:
            {
                "action": "GRID_PLACE"/"WAIT",
                "params": dict,
                "reason": str,
            }
        """
        try:
            if not kline_data or not account_state:
                return {"action": "WAIT", "reason": "empty input"}

            regime = str(account_state.get("regime", "RANGE"))

            # 趋势市暂停（HC-TF-05）
            if GridRiskGate.should_pause(regime):
                return {"action": "WAIT", "reason": f"regime={regime} pause grid"}

            equity = float(account_state.get("equity", 0))
            if equity <= 0:
                return {"action": "WAIT", "reason": "no equity"}

            # 计算网格参数
            params = GridParameterCalculator.calc_params(kline_data, equity)

            if params["grid_count"] <= 0:
                return {"action": "WAIT", "reason": "grid_count=0"}

            return {
                "action": "GRID_PLACE",
                "params": params,
                "regime": regime,
                "reason": f"grid_place_{params['grid_count']}_levels",
            }
        except Exception as e:
            logger.warning("[FO] GridTradingEngine.evaluate crash: %s", e)
            return {"action": "WAIT", "reason": f"FO crash: {type(e).__name__}"}
