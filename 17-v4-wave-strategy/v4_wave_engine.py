"""V4+波浪趋势策略 — 主引擎

完全独立于三屏趋势系统的 V4+波浪策略引擎。

核心流程：
1. 获取日线K线数据
2. V4减半周期策略 → 定方向（多/空/空仓）
3. 价值风险评估 → 仓位约束
4. 物理置信度调节 → 弱趋势仓位微调
5. 波浪策略互斥融合 → 择时加仓
6. 输出 final_signal

与三屏系统的关系：完全独立。物理引擎模块从 12-三屏趋势系统 导入。

使用方式：
    from v4_wave_engine import compute_v4_wave_signal, V4WaveEngine
    signal = compute_v4_wave_signal("BTC-USDT", is_btc=True)
"""

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
SANPING_DIR = os.path.join(PROJECT_ROOT, "12-三屏趋势系统")
sys.path.insert(0, MODULE_DIR)
sys.path.insert(1, SANPING_DIR)

try:
    from .halving_top_exit_strategy import HalvingTopExitStrategy
    from .data.market_data import fetch_candles, resample_candles, candles_to_dataframe
    from .ewave_strategy_adapter import EWaveStrategyAdapter, WaveConfig
except ImportError:
    from halving_top_exit_strategy import HalvingTopExitStrategy
    from data.market_data import fetch_candles, resample_candles, candles_to_dataframe
    from ewave_strategy_adapter import EWaveStrategyAdapter, WaveConfig

MAX_LEVERAGE = 3
MAX_POSITION_PCT = 0.25


def _position_to_action(position_pct: float) -> tuple:
    """将仓位比例转换为 action 和 direction

    Returns:
        (action, direction)
    """
    if position_pct > 0.001:
        return "ENTER_LONG", "BULL"
    elif position_pct < -0.001:
        return "ENTER_SHORT", "BEAR"
    else:
        return "WAIT", "NEUTRAL"


def _compute_value_risk(
    daily_df: pd.DataFrame,
    position_pct: float,
    direction: str,
) -> Dict:
    """价值风险评估（精简版）

    基于价格位置评估仓位风险，对极端高位/低位进行仓位约束。

    评估维度：
    - ATH回撤距离：距历史高点的回撤百分比
    - MA200位置：价格相对MA200的位置
    - 波动率：近期波动率

    Returns:
        {
            "risk_level": "low" | "medium" | "high",
            "adjusted_position": float,
            "ath_drawdown_pct": float,
            "ma200_distance_pct": float,
            "reason": str,
        }
    """
    result = {
        "risk_level": "low",
        "adjusted_position": position_pct,
        "ath_drawdown_pct": 0.0,
        "ma200_distance_pct": 0.0,
        "reason": "value_risk_not_applied",
    }

    if daily_df is None or len(daily_df) < 200:
        return result

    close = daily_df["close"].values
    current_price = close[-1]

    ath = np.max(close)
    ath_drawdown_pct = (ath - current_price) / ath * 100
    result["ath_drawdown_pct"] = round(ath_drawdown_pct, 2)

    ma200 = pd.Series(close).rolling(window=200, min_periods=200).mean().values[-1]
    if not np.isnan(ma200) and ma200 > 0:
        ma200_distance_pct = (current_price - ma200) / ma200 * 100
        result["ma200_distance_pct"] = round(ma200_distance_pct, 2)
    else:
        ma200_distance_pct = 0.0

    is_long = direction == "BULL"
    is_short = direction == "BEAR"

    adjusted = position_pct
    reason = "normal"

    if is_long:
        if ath_drawdown_pct < 10 and ma200_distance_pct > 50:
            result["risk_level"] = "high"
            adjusted = position_pct * 0.7
            reason = "near_ath_high_extreme"
        elif ath_drawdown_pct < 20 and ma200_distance_pct > 30:
            result["risk_level"] = "medium"
            adjusted = position_pct * 0.85
            reason = "near_ath_medium"
    elif is_short:
        if ath_drawdown_pct > 70:
            result["risk_level"] = "high"
            adjusted = position_pct * 0.7
            reason = "deep_bear_short_risk"
        elif ath_drawdown_pct > 50:
            result["risk_level"] = "medium"
            adjusted = position_pct * 0.85
            reason = "moderate_bear_short_risk"

    result["adjusted_position"] = round(adjusted, 4)
    result["reason"] = reason

    return result


class V4WaveEngine:
    """V4+波浪趋势策略引擎（完全独立版）

    流程：
    1. V4减半周期策略定方向
    2. 价值风险评估（仓位约束）
    3. 物理置信度调节（弱趋势仓位微调）
    4. 波浪策略互斥融合（择时加仓）
    """

    def __init__(self, wave_config: WaveConfig = None):
        self.wave_config = wave_config or WaveConfig()
        self.wave_adapter = EWaveStrategyAdapter(self.wave_config)
        self._v4_strategy_cache = {}

    def compute_from_dataframes(
        self,
        daily_df: pd.DataFrame,
        symbol: str = "BTC",
        is_btc: bool = True,
    ) -> Dict:
        """从K线DataFrame计算策略信号

        参数:
            daily_df: 日线OHLCV DataFrame，索引为DatetimeIndex
            symbol: 币种符号
            is_btc: 是否为BTC

        返回:
            完整的 final_signal 结构（与三屏系统兼容）
        """
        if daily_df is None or len(daily_df) < 250:
            return {
                "error": "日线数据不足",
                "final_signal": {
                    "action": "WAIT",
                    "direction": "NEUTRAL",
                    "confidence": 0,
                    "position": {"position_pct": 0.0},
                    "wave_strategy": {"enabled": False},
                    "v4_strategy": {"enabled": False},
                    "leverage": MAX_LEVERAGE,
                },
            }

        price = float(daily_df["close"].iloc[-1])

        # ── Step 1: V4减半周期策略定方向 ──
        v4_strategy = HalvingTopExitStrategy(
            symbol=symbol,
            is_btc=is_btc,
            btc_prices=daily_df if not is_btc else None,
        )
        v4_positions = v4_strategy.generate_signals(daily_df)
        v4_position_pct = float(v4_positions.iloc[-1])
        v4_action, v4_direction = _position_to_action(v4_position_pct)

        v4_info = {
            "enabled": True,
            "v4_action": v4_action,
            "v4_direction": v4_direction,
            "v4_position_pct": round(v4_position_pct, 4),
            "strategy_version": "v4_halving_top_exit",
            "stats": v4_strategy.get_stats(),
        }

        base_position = abs(v4_position_pct)
        base_action = v4_action
        base_direction = v4_direction

        # ── Step 2: 价值风险评估 ──
        value_risk = _compute_value_risk(daily_df, base_position, base_direction)
        if value_risk["adjusted_position"] != base_position:
            if base_direction == "BULL":
                base_position = value_risk["adjusted_position"]
            elif base_direction == "BEAR":
                base_position = value_risk["adjusted_position"]

        # ── Step 3: 物理置信度调节（弱趋势条件） ──
        physics_adjustment = {
            "enabled": False,
            "eta": None,
            "phys_conf": None,
            "kinetic_score": None,
            "adjusted_position": base_position,
            "reason": "physics_not_applied",
        }
        adjusted_position = base_position

        if self.wave_config.enable_physics and self.wave_adapter.physics_enhancer is not None:
            try:
                phys = self.wave_adapter.physics_enhancer
                feats = phys.compute_features(daily_df)
                n = len(daily_df)
                last_idx = n - 1

                eta = float(feats["eta"][last_idx]) if not np.isnan(feats["eta"][last_idx]) else 0.0
                phys_conf = float(feats["phys_conf"][last_idx]) if not np.isnan(feats["phys_conf"][last_idx]) else 0.5
                kinetic_score = float(feats["kinetic_score"][last_idx]) if not np.isnan(feats["kinetic_score"][last_idx]) else 0.5

                physics_adjustment["enabled"] = True
                physics_adjustment["eta"] = round(eta, 4)
                physics_adjustment["phys_conf"] = round(phys_conf, 4)
                physics_adjustment["kinetic_score"] = round(kinetic_score, 4)

                if eta < self.wave_config.eta_weak:
                    phys_multiplier = self.wave_config.position_lower + self.wave_config.position_scale * phys_conf
                    adjusted_position = base_position * phys_multiplier
                    physics_adjustment["adjusted_position"] = round(adjusted_position, 4)
                    physics_adjustment["reason"] = "weak_trend_physics_adjusted"
                else:
                    physics_adjustment["reason"] = "strong_trend_no_adjustment"

            except Exception as e:
                physics_adjustment["reason"] = f"physics_error: {str(e)}"

        final_position = adjusted_position
        final_action, final_direction = _position_to_action(
            final_position if base_direction == "BULL" else -final_position
        )

        # 保持原始方向的正负号
        if base_direction == "BEAR":
            final_position = -abs(final_position)
            final_action = "ENTER_SHORT" if abs(final_position) > 0.001 else "WAIT"
            final_direction = "BEAR" if abs(final_position) > 0.001 else "NEUTRAL"
        elif base_direction == "BULL":
            final_position = abs(final_position)
            final_action = "ENTER_LONG" if final_position > 0.001 else "WAIT"
            final_direction = "BULL" if final_position > 0.001 else "NEUTRAL"
        else:
            final_position = 0.0
            final_action = "WAIT"
            final_direction = "NEUTRAL"

        # ── Step 4: 波浪策略互斥融合 ──
        try:
            wave_result = self.wave_adapter.evaluate(
                daily_df=daily_df,
                v4_action=final_action,
                v4_direction=final_direction,
                v4_position_pct=abs(final_position),
                symbol=symbol,
            )
        except Exception as e:
            wave_result = {
                "enabled": False,
                "error": str(e),
                "total_position_pct": abs(final_position),
                "final_action": final_action,
                "final_direction": final_direction,
                "fusion_rule": "wave_error_keep_v4",
            }

        # 融合波浪结果
        if wave_result.get("enabled"):
            wave_total_pos = wave_result["total_position_pct"]
            wave_action = wave_result["final_action"]
            wave_direction = wave_result["final_direction"]

            if wave_action == "ENTER_LONG":
                total_position = wave_total_pos
                total_action = "ENTER_LONG"
                total_direction = "BULL"
            elif wave_action == "ENTER_SHORT":
                total_position = -wave_total_pos
                total_action = "ENTER_SHORT"
                total_direction = "BEAR"
            else:
                total_position = 0.0
                total_action = "WAIT"
                total_direction = "NEUTRAL"
        else:
            total_position = final_position
            total_action = final_action
            total_direction = final_direction

        abs_position = abs(total_position)
        confidence = min(95.0, 50.0 + abs_position * 50)

        # ── 组装 final_signal ──
        final_signal = {
            "direction": total_direction,
            "confidence": round(confidence, 1),
            "action": total_action,
            "position": {
                "position_pct": round(abs_position, 4),
                "tier": "full" if abs_position > 0.5 else "partial",
                "original_position_pct": round(abs(v4_position_pct), 4),
            },
            "decision_reason": wave_result.get("fusion_rule", "v4_base"),
            "leverage": MAX_LEVERAGE,
            "margin_mode": "isolated",
            "max_position_pct": MAX_POSITION_PCT,
            "max_addon_position_pct": 0.1,
            "v4_strategy": v4_info,
            "physics_adjustment": physics_adjustment,
            "wave_strategy": wave_result,
            "value_risk_assessment": value_risk,
        }

        return {
            "symbol": symbol,
            "price": round(price, 2),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "timeframes": {
                "daily": len(daily_df),
            },
            "value_risk_assessment": value_risk,
            "final_signal": final_signal,
        }


_default_engine = None


def compute_v4_wave_signal(
    spot_inst: str = "BTC-USDT",
    is_btc: bool = True,
) -> dict:
    """V4+波浪策略完整信号计算（含数据获取）

    完全独立于三屏趋势系统。

    参数:
        spot_inst: 现货交易对，如 "BTC-USDT"
        is_btc: 是否为BTC币种

    返回:
        完整信号结构（与三屏系统compute_full_trading_signal兼容）
    """
    global _default_engine
    if _default_engine is None:
        _default_engine = V4WaveEngine()

    symbol = spot_inst.split("-")[0]

    daily = fetch_candles(spot_inst, "1D", 300)

    if not daily:
        return {"error": f"无法获取{spot_inst} K线数据"}

    price = daily[-1]["c"]

    daily_df = candles_to_dataframe(daily)

    result = _default_engine.compute_from_dataframes(
        daily_df=daily_df,
        symbol=symbol,
        is_btc=is_btc,
    )

    result["symbol"] = symbol
    result["price"] = round(price, 2)

    return result
