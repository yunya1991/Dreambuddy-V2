"""TrendFollowingEngine — 趋势跟踪（海龟法则）+ 正金字塔加仓 + 2N 止损

策略原理（参考 SPEC Phase B + 调研报告）：
  - 入场：20 日 Donchian 突破（快系统）/ 55 日突破（慢系统）
  - 止损：2×ATR，下限 4%，上限 15%（HC-TF-01）
  - 加仓：每 0.5×ATR 加 1 Unit，最多 4 Unit（HC-TF-02）
  - 离场：跌破 10 日低点（快）/ 20 日低点（慢）

FAIL-OPEN 原则（HC-TF-07）：
  任何异常 → 返回中性兜底 {"action": "WAIT"}，不抛异常，不阻塞交易
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ====================================================================
# 常量（硬约束对齐）
# ====================================================================
RISK_PER_TRADE = 0.01          # 1% 账户风险（海龟标准）
MAX_UNITS = 4                   # 最多 4 个加仓 Unit（HC-TF-02）
ADDON_INTERVAL_ATR = 0.5        # 每 0.5×ATR 加仓 1 Unit（HC-TF-02）

ATR_STOP_MULTIPLIER = 2.0       # 2×ATR 止损（HC-TF-01）
SL_FLOOR_PCT = 0.04             # SL 下限 4%（HC-TF-01，对齐 CLAUDE.md）
SL_CAP_PCT = 0.15               # SL 上限 15%（HC-TF-01）

EXIT_FAST_PERIOD = 10           # 快系统离场：跌破 10 日低点
EXIT_SLOW_PERIOD = 20           # 慢系统离场：跌破 20 日低点

DONCHIAN_FAST = 20              # 海龟快系统
DONCHIAN_SLOW = 55              # 海龟慢系统


class DonchianChannel:
    """Donchian 通道突破信号 — 趋势跟踪入场触发器"""

    @staticmethod
    def breakout_signal(kline_data: dict, period: int = 20) -> str:
        """计算 Donchian 通道突破信号

        Args:
            kline_data: {"high": [...], "low": [...], "close": [...]}
            period: 通道周期（20=快，55=慢）

        Returns:
            "LONG" / "SHORT" / "NEUTRAL"
        """
        try:
            highs = list(kline_data.get("high") or [])
            lows = list(kline_data.get("low") or [])
            closes = list(kline_data.get("close") or [])
            if len(highs) < period or len(lows) < period or not closes:
                return "NEUTRAL"

            upper = max(float(h) for h in highs[-period:])
            lower = min(float(l) for l in lows[-period:])
            current_close = float(closes[-1])

            if current_close > upper:
                return "LONG"
            elif current_close < lower:
                return "SHORT"
            else:
                return "NEUTRAL"
        except Exception as e:
            logger.warning("[FO] DonchianChannel.breakout_signal: %s", e)
            return "NEUTRAL"


class ATRStopCalculator:
    """2×ATR 止损计算器（HC-TF-01：下限 4%，上限 15%）"""

    @staticmethod
    def calc_stop(entry_price: float, atr: float, direction: str = "LONG") -> float:
        """计算止损价

        Args:
            entry_price: 入场价
            atr: ATR 值
            direction: "LONG" 或 "SHORT"

        Returns:
            止损价（float）
        """
        try:
            if entry_price <= 0 or atr < 0:
                return entry_price * (1 - SL_FLOOR_PCT)  # 兜底 4%

            # 2×ATR 止损百分比
            sl_pct = (atr * ATR_STOP_MULTIPLIER) / entry_price

            # HC-TF-01：下限 4%，上限 15%
            sl_pct = max(sl_pct, SL_FLOOR_PCT)
            sl_pct = min(sl_pct, SL_CAP_PCT)

            if direction.upper() == "SHORT":
                # 做空：止损在上方
                return round(entry_price * (1 + sl_pct), 6)
            else:
                # 做多：止损在下方
                return round(entry_price * (1 - sl_pct), 6)
        except Exception as e:
            logger.warning("[FO] ATRStopCalculator.calc_stop: %s", e)
            return round(entry_price * (1 - SL_FLOOR_PCT), 6)


class PyramidingPositionSizer:
    """正金字塔仓位计算器（HC-TF-02：最多 4 Unit，每 0.5N 加仓）"""

    @staticmethod
    def calc_unit(account: float, atr: float, point_value: float = 1.0) -> float:
        """计算单个 Unit 仓位大小

        Unit = (Account × 1%) / (ATR × PointValue)
        海龟法则波动率标准化：使每笔风险恒定为账户的 1%

        Args:
            account: 账户净值（USDT）
            atr: ATR 值
            point_value: 每单位价值（USDT/单位）

        Returns:
            Unit 仓位大小（float）
        """
        try:
            if account <= 0 or atr <= 0 or point_value <= 0:
                return 0.0
            risk_amount = account * RISK_PER_TRADE
            unit = risk_amount / (atr * point_value)
            return round(unit, 6)
        except Exception as e:
            logger.warning("[FO] PyramidingPositionSizer.calc_unit: %s", e)
            return 0.0

    @staticmethod
    def calc_addon_tiers(
        entry_price: float,
        atr: float,
        direction: str = "LONG",
        max_units: int = MAX_UNITS,
    ) -> list:
        """计算正金字塔加仓阶梯价格

        多头：每上涨 0.5×ATR 加仓一次
        做空：每下跌 0.5×ATR 加仓一次
        最多 4 个加仓阶梯（HC-TF-02）

        Args:
            entry_price: 入场价
            atr: ATR 值
            direction: "LONG" 或 "SHORT"
            max_units: 最大加仓次数（默认 4）

        Returns:
            list[float]：加仓价格阶梯
        """
        try:
            if entry_price <= 0 or atr <= 0:
                return []

            tiers = []
            step = atr * ADDON_INTERVAL_ATR  # 0.5×ATR

            for i in range(1, max_units + 1):
                if direction.upper() == "SHORT":
                    # 做空：价格下跌才加仓（顺势）
                    price = entry_price - step * i
                else:
                    # 做多：价格上涨才加仓（顺势）
                    price = entry_price + step * i
                if price > 0:
                    tiers.append(round(price, 6))
            return tiers
        except Exception as e:
            logger.warning("[FO] PyramidingPositionSizer.calc_addon_tiers: %s", e)
            return []


class TrendExitRule:
    """趋势跟踪离场规则 — 跌破 N 日低点离场"""

    @staticmethod
    def check_exit(kline_data: dict, period: int = EXIT_FAST_PERIOD) -> bool:
        """检查是否触发离场

        跌破 period 日最低价 → 离场

        Args:
            kline_data: {"low": [...], "close": [...]}
            period: 离场周期（10=快系统，20=慢系统）

        Returns:
            True=应离场，False=继续持有
        """
        try:
            lows = list(kline_data.get("low") or [])
            closes = list(kline_data.get("close") or [])
            if len(lows) < period or not closes:
                return False

            low_bound = min(float(l) for l in lows[-period:])
            current_close = float(closes[-1])

            # 当前收盘价跌破 period 日最低价 → 离场
            return current_close < low_bound
        except Exception as e:
            logger.warning("[FO] TrendExitRule.check_exit: %s", e)
            return False


class TrendFollowingEngine:
    """趋势跟踪主引擎 — 海龟法则 + 正金字塔加仓 + 2N 止损

    对称镜像 V15 倒金字塔：
      V15 倒金字塔（震荡市）：逆势加仓，8% 间距，无止损
      TrendFollowingEngine 正金字塔（趋势市）：顺势加仓，0.5N 间距，2N 止损

    由 RegimeGateSwitch 在 regime=TREND 时调用。
    """

    @staticmethod
    def evaluate(kline_data: dict, account_state: dict) -> dict:
        """评估趋势跟踪信号

        Args:
            kline_data: {"high": [...], "low": [...], "close": [...], "volume": [...]}
            account_state: {"equity": float, "point_value": float}

        Returns:
            {
                "action": "LONG"/"SHORT"/"WAIT",
                "signal": str,
                "entry_price": float,
                "stop_price": float,
                "unit": float,
                "addon_tiers": list,
                "exit_period": int,
                "reason": str,
            }
        """
        try:
            if not kline_data or not account_state:
                return {"action": "WAIT", "reason": "empty input"}

            highs = list(kline_data.get("high") or [])
            lows = list(kline_data.get("low") or [])
            closes = list(kline_data.get("close") or [])

            if len(highs) < DONCHIAN_FAST or len(lows) < DONCHIAN_FAST or not closes:
                return {"action": "WAIT", "reason": "insufficient data"}

            # 1. Donchian 突破信号（快系统）
            signal = DonchianChannel.breakout_signal(kline_data, period=DONCHIAN_FAST)
            if signal == "NEUTRAL":
                return {"action": "WAIT", "reason": "no breakout"}

            # 2. 计算 ATR（复用 V15 signal 模块的 calc_atr）
            try:
                # 优先从 14-V15经典马丁策略 导入 calc_atr
                import sys
                from pathlib import Path

                v15_core = Path(__file__).resolve().parents[3] / "14-V15经典马丁策略" / "core"
                if str(v15_core) not in sys.path:
                    sys.path.insert(0, str(v15_core))
                from v15_signal import calc_atr  # type: ignore
            except ImportError:
                # 兜底：简化 ATR 计算
                def calc_atr(highs, lows, closes, period=14):
                    if len(closes) < period + 1:
                        return 0.0
                    tr_list = []
                    for i in range(1, len(closes)):
                        tr = max(
                            highs[i] - lows[i],
                            abs(highs[i] - closes[i - 1]),
                            abs(lows[i] - closes[i - 1]),
                        )
                        tr_list.append(tr)
                    return sum(tr_list[-period:]) / min(period, len(tr_list)) if tr_list else 0.0

            atr = calc_atr(highs, lows, closes, period=14)
            if atr <= 0:
                return {"action": "WAIT", "reason": "ATR=0"}

            # 3. 入场价 = 当前收盘价
            entry_price = float(closes[-1])

            # 4. 2×ATR 止损（HC-TF-01）
            stop_price = ATRStopCalculator.calc_stop(entry_price, atr, signal)

            # 5. Unit 仓位（HC-TF-02）
            equity = float(account_state.get("equity", 0))
            point_value = float(account_state.get("point_value", 1.0))
            unit = PyramidingPositionSizer.calc_unit(equity, atr, point_value)

            # 6. 加仓阶梯（HC-TF-02：最多 4）
            addon_tiers = PyramidingPositionSizer.calc_addon_tiers(entry_price, atr, signal)

            return {
                "action": signal,
                "signal": signal,
                "entry_price": round(entry_price, 6),
                "stop_price": stop_price,
                "atr": round(atr, 6),
                "unit": unit,
                "addon_tiers": addon_tiers,
                "exit_period": EXIT_FAST_PERIOD,
                "max_units": MAX_UNITS,
                "reason": f"donchian_{DONCHIAN_FAST}_breakout",
            }
        except Exception as e:
            logger.warning("[FO] TrendFollowingEngine.evaluate crash: %s", e)
            return {"action": "WAIT", "reason": f"FO crash: {type(e).__name__}"}
