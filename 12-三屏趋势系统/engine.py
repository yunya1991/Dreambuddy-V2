"""三屏趋势系统 — 主引擎

核心入口：compute_full_trading_signal()

主力策略：V4 + 波浪互斥融合（V4定方向，波浪择时加仓）

策略层级：
1. 三屏趋势系统：五大算法（静态投票+动态融合+权重调整+贝叶斯+基本面撮合）
   → 作为信号源和置信度评估层
2. V4 减半周期策略：主策略，定方向（多/空/空仓），覆盖三屏决策
   → 9年回测：年化 53.34%，夏普 1.37，回撤 -44.37%
3. 波浪策略：择时加仓（同向叠加，反向以V4为主，V4空仓时波浪轻仓抄底）
   → V4+波浪互斥融合：年化 56.43%，夏普 1.41，回撤 -43.31%
4. 物理置信度调节：弱趋势状态（η<0.10）下仓位微调

设计理念：V4定方向，波浪择时加仓，物理引擎评估风险。

系统边界：
- 三屏趋势系统 = 「V4主策略方向 + 波浪择时加仓 + 置信度评估 + 仓位计算」
- 入场信号精选 → 委托给 10-经典指标系统 的 Freqtrade 策略
- 离场决策 → 委托给 10-经典指标系统 的 ClassicExitSystem
"""

from datetime import datetime, timezone
from typing import Optional, Dict

try:
    from .core import (
        calc_trend_consistency,
        calc_bayesian_confidence,
        fuse_technical_fundamental,
        calc_classic_indicator_confidence,
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        calc_elder_ray,
        calc_30d_volatility,
        get_vol_adjusted_params,
        calc_risk_reward_ratio,
        evaluate_addon_opportunity,
        calc_position_sizing,
        MAX_LEVERAGE,
        MAX_POSITION_PCT,
        MAX_ADDON_POSITION_PCT,
        BASE_TAKE_PROFIT_PCT,
        BASE_STOP_LOSS_PCT,
        BTC_DIVERGENCE_ADDON_PCT,
        BTC_WIND_VANE_DAILY_MA,
        BTC_WIND_VANE_WEEKLY_MA,
        BTC_WIND_VANE_BREAK_DAYS,
        BTC_WIND_VANE_ENABLED,
    )
    from .core.config import (
        OPEN_CONFIDENCE_THRESHOLD,
        TRIAL_CONFIDENCE_THRESHOLD,
        POSITION_TIERS,
        CONFIDENCE_JUMP_THRESHOLD,
        DEFAULT_INST_SPOT,
    )
except ImportError:
    from core import (
        calc_trend_consistency,
        calc_bayesian_confidence,
        fuse_technical_fundamental,
        calc_classic_indicator_confidence,
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        calc_elder_ray,
        calc_30d_volatility,
        get_vol_adjusted_params,
        calc_risk_reward_ratio,
        evaluate_addon_opportunity,
        calc_position_sizing,
        MAX_LEVERAGE,
        MAX_POSITION_PCT,
        MAX_ADDON_POSITION_PCT,
        BASE_TAKE_PROFIT_PCT,
        BASE_STOP_LOSS_PCT,
        BTC_DIVERGENCE_ADDON_PCT,
        BTC_WIND_VANE_DAILY_MA,
        BTC_WIND_VANE_WEEKLY_MA,
        BTC_WIND_VANE_BREAK_DAYS,
        BTC_WIND_VANE_ENABLED,
    )
    from core.config import (
        OPEN_CONFIDENCE_THRESHOLD,
        TRIAL_CONFIDENCE_THRESHOLD,
        POSITION_TIERS,
        CONFIDENCE_JUMP_THRESHOLD,
        DEFAULT_INST_SPOT,
    )


def evaluate_btc_wind_vane(btc_daily_df=None, btc_weekly_df=None, reversal_context: Optional[Dict] = None) -> Dict:
    """BTC风向标评估 — 全系统做多/做空闸门

    大原则（宏观方向过滤器，优先级高于一切币种级信号）：
    1. BTC有效跌破日线MA128（连续N日收盘价低于MA128）→ 全系统做空闸门打开
    2. BTC有效站上周线MA200（周收盘价站上）→ 全系统做多闸门打开
    3. 站上周线MA200 → 强制做多，禁止做空

    "有效跌破"定义：连续 BTC_WIND_VANE_BREAK_DAYS 日收盘价低于日线MA128

    P0 改进：动态逆转软闸门
    - 静态强制 + 动态强逆转 → 降级为"软拦截"，允许轻仓试探反向（不硬性禁止）
    - 通过 reversal_context 传入动态逆转信息，返回 soft_block 标志
    - 硬拦截（hard_block=True）保持原有禁止行为
    - 软拦截（soft_block=True）允许下游决策器用轻仓试探

    参数:
        btc_daily_df: BTC日线DataFrame（需含close列，至少MA128+BREAK_DAYS根）
        btc_weekly_df: BTC周线DataFrame（需含close列，至少MA200根）
        reversal_context: 动态逆转上下文（可选），结构：
            {
                "consistency_level": str,    # STRONG/REVERSAL/NEUTRAL/INCONSISTENT
                "reversal_alignment": str,   # NONE/WEEKLY_REVERSAL/DAILY_REVERSAL/BOTH_REVERSAL
                "reversal_confidence": float,  # 0-100
                "overall_direction": str,    # 逆转后的方向 BULL/BEAR/NEUTRAL
            }

    返回:
        {
            "enabled": bool,
            "long_gate_open": bool,      # 做多闸门是否打开
            "short_gate_open": bool,     # 做空闸门是否打开
            "force_long": bool,          # 强制做多（站上周线MA200）
            "prohibit_short": bool,      # 禁止做空（硬拦截）
            "prohibit_long": bool,       # 禁止做多（未站上MA200且未跌破MA128）
            "btc_daily_ma128": float/None,
            "btc_weekly_ma200": float/None,
            "btc_last_daily_close": float/None,
            "btc_last_weekly_close": float/None,
            "consecutive_below_ma128": int,
            "weekly_above_ma200": bool,
            "daily_below_ma128_confirmed": bool,
            "reason": str,
            # ── P0 新增字段 ──
            "hard_block": bool,          # 硬拦截：严格禁止反向信号
            "soft_block": bool,          # 软拦截：动态逆转中，允许轻仓试探反向
            "reversal_downgrade": bool,   # 是否触发了动态降级
            "reversal_direction": str,   # 逆转方向（软拦截时有效）：BULL/BEAR/NEUTRAL
        }
    """
    result = {
        "enabled": BTC_WIND_VANE_ENABLED,
        "long_gate_open": True,
        "short_gate_open": True,
        "force_long": False,
        "prohibit_short": False,
        "prohibit_long": False,
        "btc_daily_ma128": None,
        "btc_weekly_ma200": None,
        "btc_last_daily_close": None,
        "btc_last_weekly_close": None,
        "consecutive_below_ma128": 0,
        "weekly_above_ma200": False,
        "daily_below_ma128_confirmed": False,
        "reason": "风向标未启用或数据不足，默认全开",
        "hard_block": False,
        "soft_block": False,
        "reversal_downgrade": False,
        "reversal_direction": "NEUTRAL",
    }

    if not BTC_WIND_VANE_ENABLED:
        return result

    # ── 日线MA128 跌破检测 ──
    daily_ma128 = None
    consecutive_below = 0
    last_daily_close = None
    daily_below_confirmed = False

    if btc_daily_df is not None and len(btc_daily_df) >= BTC_WIND_VANE_DAILY_MA + BTC_WIND_VANE_BREAK_DAYS:
        closes = list(btc_daily_df["close"])
        daily_ma128 = sum(closes[-BTC_WIND_VANE_DAILY_MA:]) / BTC_WIND_VANE_DAILY_MA
        last_daily_close = closes[-1]

        recent_closes = closes[-(BTC_WIND_VANE_BREAK_DAYS):]
        consecutive_below = sum(1 for c in recent_closes if c < daily_ma128)
        daily_below_confirmed = consecutive_below >= BTC_WIND_VANE_BREAK_DAYS

    # ── 周线MA200 站上检测 ──
    weekly_ma200 = None
    last_weekly_close = None
    weekly_above = False

    if btc_weekly_df is not None and len(btc_weekly_df) >= BTC_WIND_VANE_WEEKLY_MA:
        w_closes = list(btc_weekly_df["close"])
        weekly_ma200 = sum(w_closes[-BTC_WIND_VANE_WEEKLY_MA:]) / BTC_WIND_VANE_WEEKLY_MA
        last_weekly_close = w_closes[-1]
        weekly_above = last_weekly_close > weekly_ma200

    result["btc_daily_ma128"] = round(daily_ma128, 2) if daily_ma128 else None
    result["btc_weekly_ma200"] = round(weekly_ma200, 2) if weekly_ma200 else None
    result["btc_last_daily_close"] = round(last_daily_close, 2) if last_daily_close else None
    result["btc_last_weekly_close"] = round(last_weekly_close, 2) if last_weekly_close else None
    result["consecutive_below_ma128"] = consecutive_below
    result["weekly_above_ma200"] = weekly_above
    result["daily_below_ma128_confirmed"] = daily_below_confirmed

    # ── P0 改进：解析逆转上下文 ──
    has_reversal = False
    reversal_confidence = 0.0
    reversal_dir = "NEUTRAL"
    if reversal_context:
        level = reversal_context.get("consistency_level", "")
        if level == "REVERSAL_CONSISTENT":
            alignment = reversal_context.get("reversal_alignment", "NONE")
            if alignment != "NONE":
                has_reversal = True
                reversal_confidence = float(reversal_context.get("reversal_confidence", 0))
                reversal_dir = reversal_context.get("overall_direction", "NEUTRAL")

    # 逆转软拦截阈值：逆转置信度 ≥ 50 才允许软拦截
    REVERSAL_SOFT_BLOCK_THRESHOLD = 50.0

    # ── 闸门逻辑（P0：硬拦截 + 软拦截）──
    # 规则3优先级最高：站上周线MA200 → 强制做多，禁止做空
    if weekly_above:
        result["force_long"] = True
        result["prohibit_short"] = True
        result["long_gate_open"] = True
        result["short_gate_open"] = False

        # P0 软拦截判定：静态强制做多 + 动态强逆转看空 → 软拦截（允许轻仓做空试探）
        if has_reversal and reversal_dir == "BEAR" and reversal_confidence >= REVERSAL_SOFT_BLOCK_THRESHOLD:
            result["hard_block"] = False
            result["soft_block"] = True
            result["reversal_downgrade"] = True
            result["reversal_direction"] = "BEAR"
            result["reason"] = (
                f"BTC周收盘({last_weekly_close:.2f})站上周线MA200({weekly_ma200:.2f})，"
                f"但动态逆转置信度{reversal_confidence:.1f}%≥{REVERSAL_SOFT_BLOCK_THRESHOLD}%，"
                f"软拦截：允许轻仓做空试探（不超过trial仓位）"
            )
        else:
            result["hard_block"] = True
            result["reason"] = (
                f"BTC周收盘({last_weekly_close:.2f})站上周线MA200({weekly_ma200:.2f})，"
                f"强制做多，禁止做空（硬拦截）"
            )
        return result

    # 规则1：BTC有效跌破日线MA128 → 做空闸门打开
    if daily_below_confirmed:
        result["short_gate_open"] = True
        result["long_gate_open"] = False
        result["prohibit_long"] = True

        # P0 软拦截判定：静态强制做空 + 动态强逆转看多 → 软拦截（允许轻仓做多试探）
        if has_reversal and reversal_dir == "BULL" and reversal_confidence >= REVERSAL_SOFT_BLOCK_THRESHOLD:
            result["hard_block"] = False
            result["soft_block"] = True
            result["reversal_downgrade"] = True
            result["reversal_direction"] = "BULL"
            result["reason"] = (
                f"BTC连续{consecutive_below}日收盘低于日线MA128({daily_ma128:.2f})，"
                f"但动态逆转置信度{reversal_confidence:.1f}%≥{REVERSAL_SOFT_BLOCK_THRESHOLD}%，"
                f"软拦截：允许轻仓做多试探（不超过trial仓位）"
            )
        else:
            result["hard_block"] = True
            result["reason"] = (
                f"BTC连续{consecutive_below}日收盘低于日线MA128({daily_ma128:.2f})，"
                f"做空闸门打开，做多关闭（硬拦截）"
            )
        return result

    # 中间状态：未跌破MA128且未站上MA200 → 双向开放（等待明确信号）
    parts = []
    if daily_ma128 and last_daily_close:
        if last_daily_close < daily_ma128:
            parts.append(f"日线收盘{last_daily_close:.2f}<MA128({daily_ma128:.2f})但未连续{BTC_WIND_VANE_BREAK_DAYS}日确认")
        else:
            parts.append(f"日线收盘{last_daily_close:.2f}≥MA128({daily_ma128:.2f})")
    if weekly_ma200 and last_weekly_close:
        if last_weekly_close < weekly_ma200:
            parts.append(f"周收盘{last_weekly_close:.2f}<MA200({weekly_ma200:.2f})，未站上")
        else:
            parts.append(f"周收盘{last_weekly_close:.2f}≥MA200({weekly_ma200:.2f})")
    result["reason"] = "；".join(parts) if parts else "数据不足，默认双向开放"
    return result


def confidence_to_position(confidence: float) -> dict:
    for threshold, pos in POSITION_TIERS:
        if confidence >= threshold:
            tier_map = {
                0.60: "heavy",
                0.45: "medium",
                0.30: "moderate",
                0.15: "light",
                0.05: "trial",
                0.02: "micro",
            }
            return {
                "position_pct": pos,
                "tier": tier_map.get(pos, "micro"),
            }
    return {
        "position_pct": 0.0,
        "tier": "none",
    }


def calc_take_profit_stop_loss(
    direction: str,
    entry_price: float,
    vol_params: Dict,
    base_tp_pct: float = None,
    base_sl_pct: float = None,
) -> Dict:
    if base_tp_pct is None:
        base_tp_pct = BASE_TAKE_PROFIT_PCT
    if base_sl_pct is None:
        base_sl_pct = BASE_STOP_LOSS_PCT

    vol_ratio = vol_params.get("vol_ratio", 1.0)
    tp_pct = base_tp_pct * vol_ratio
    sl_pct = base_sl_pct * vol_ratio

    if direction == "LONG":
        tp_price = entry_price * (1 + tp_pct)
        sl_price = entry_price * (1 - sl_pct)
    else:
        tp_price = entry_price * (1 - tp_pct)
        sl_price = entry_price * (1 + sl_pct)

    rr = calc_risk_reward_ratio(direction, entry_price, entry_price, sl_price, tp_price)

    return {
        "take_profit_price": round(tp_price, 4),
        "stop_loss_price": round(sl_price, 4),
        "take_profit_pct": round(tp_pct * 100, 2),
        "stop_loss_pct": round(sl_pct * 100, 2),
        "vol_ratio": vol_ratio,
        "risk_reward": rr,
    }


def compute_value_risk_assessment(
    symbol: str,
    direction: str,
    current_price: float,
    daily_df,
    is_btc: bool = False,
    btc_daily_df=None,
) -> Dict:
    if daily_df is None or len(daily_df) < 31:
        return {"error": "日线数据不足"}

    klines = []
    for i in range(len(daily_df)):
        klines.append({
            "high": float(daily_df["high"].iloc[i]),
            "low": float(daily_df["low"].iloc[i]),
            "close": float(daily_df["close"].iloc[i]),
        })

    elder_ray = calc_elder_ray(klines, period=13)

    closes = [float(c) for c in daily_df["close"]]
    coin_vol = calc_30d_volatility(closes)

    btc_vol = coin_vol
    if btc_daily_df is not None and len(btc_daily_df) >= 31:
        btc_closes = [float(c) for c in btc_daily_df["close"]]
        btc_vol = calc_30d_volatility(btc_closes)

    vol_params = get_vol_adjusted_params(coin_vol, btc_vol)

    long_dir = "LONG" if direction == "BULL" else "SHORT"
    tp_sl = calc_take_profit_stop_loss(long_dir, current_price, vol_params)

    return {
        "symbol": symbol,
        "is_btc": is_btc,
        "direction": direction,
        "current_price": current_price,
        "elder_ray": elder_ray,
        "volatility": vol_params,
        "take_profit_stop_loss": tp_sl,
        "value_gt_risk": tp_sl["risk_reward"]["value_gt_risk"],
    }


def evaluate_addon_decision(
    symbol: str,
    direction: str,
    current_price: float,
    entry_price: float,
    is_btc: bool,
    daily_df,
    btc_daily_df=None,
    unrealized_pnl_pct: float = 0.0,
    current_position_pct: float = 0.0,
    max_position_cap: float = None,
) -> Dict:
    if max_position_cap is None:
        max_position_cap = MAX_ADDON_POSITION_PCT

    if daily_df is None or len(daily_df) < 31:
        return {"can_add": False, "reason": "日线数据不足"}

    klines = []
    for i in range(len(daily_df)):
        klines.append({
            "high": float(daily_df["high"].iloc[i]),
            "low": float(daily_df["low"].iloc[i]),
            "close": float(daily_df["close"].iloc[i]),
        })

    elder_ray = calc_elder_ray(klines, period=13)

    closes = [float(c) for c in daily_df["close"]]
    coin_vol = calc_30d_volatility(closes)

    btc_vol = coin_vol
    if btc_daily_df is not None and len(btc_daily_df) >= 31:
        btc_closes = [float(c) for c in btc_daily_df["close"]]
        btc_vol = calc_30d_volatility(btc_closes)

    vol_params = get_vol_adjusted_params(coin_vol, btc_vol)

    long_dir = "LONG" if direction == "BULL" else "SHORT"

    addon_result = evaluate_addon_opportunity(
        symbol=symbol,
        direction=long_dir,
        current_price=current_price,
        entry_price=entry_price,
        is_btc=is_btc,
        elder_ray=elder_ray if elder_ray else {},
        vol_params=vol_params,
        unrealized_pnl_pct=unrealized_pnl_pct,
        current_position_pct=current_position_pct,
        max_position_cap=max_position_cap,
    )

    addon_result["elder_ray"] = elder_ray
    addon_result["volatility"] = vol_params
    return addon_result


def _integrate_freqtrade_signals(
    final_direction: str,
    base_confidence: float,
    freqtrade_signals: Dict,
) -> dict:
    """
    集成 Freqtrade 信号（来自经典指标系统）

    信号校准规则：
    - 同向时 +置信度×权重（1h×10%, 4h×15%）
    - 反向时 -10%
    - 1h或4h任一同向即为 freqtrade_consistent = true

    参数:
        final_direction: "BULL"/"BEAR"/"NEUTRAL"
        base_confidence: 基础置信度（0-100）
        freqtrade_signals: {"1h": MultiStrategySignal, "4h": MultiStrategySignal}
                          或 {"1h": {"signal": ..., "confidence": ...}, ...}

    返回:
        {"consistent": bool, "adjusted_confidence": float, "details": {...}}
    """
    try:
        from .signals import align_freqtrade_with_trend
    except ImportError:
        from signals import align_freqtrade_with_trend

    adjusted_confidence = base_confidence
    consistent = False
    details = {}

    if final_direction == "NEUTRAL":
        return {"consistent": False, "adjusted_confidence": base_confidence, "details": {}}

    for tf in ["1h", "4h"]:
        sig = freqtrade_signals.get(tf)
        if sig is None:
            continue

        if hasattr(sig, 'direction'):
            sig_obj = sig
        else:
            sig_obj = _dict_to_signal(sig, tf)

        alignment = align_freqtrade_with_trend(final_direction, sig_obj)
        adjusted_confidence += alignment["confidence_adjustment"]
        if alignment["consistent"]:
            consistent = True
        details[tf] = {
            "consistent": alignment["consistent"],
            "adjustment": round(float(alignment["confidence_adjustment"]), 2),
        }

    adjusted_confidence = max(0, min(100, adjusted_confidence))

    return {
        "consistent": consistent,
        "adjusted_confidence": round(adjusted_confidence, 1),
        "details": details,
    }


def _dict_to_signal(sig_dict: Dict, timeframe: str):
    """将字典格式的信号转换为 MultiStrategySignal"""
    try:
        from .signals import MultiStrategySignal, SignalDirection, StrategySignal
    except ImportError:
        from signals import MultiStrategySignal, SignalDirection, StrategySignal

    signal_str = sig_dict.get("signal", "HOLD")
    direction = SignalDirection.HOLD
    if signal_str in ("BUY", "LONG", "long", "buy"):
        direction = SignalDirection.LONG
    elif signal_str in ("SELL", "SHORT", "short", "sell"):
        direction = SignalDirection.SHORT

    return MultiStrategySignal(
        symbol=sig_dict.get("symbol", ""),
        timeframe=timeframe,
        direction=direction,
        confidence=float(sig_dict.get("confidence", 0) or 0),
        strategy_count=1,
        long_votes=1 if direction == SignalDirection.LONG else 0,
        short_votes=1 if direction == SignalDirection.SHORT else 0,
        strategies=[StrategySignal(
            strategy_name=sig_dict.get("strategy", f"freqtrade_{timeframe}"),
            signal=direction,
            confidence=float(sig_dict.get("confidence", 0) or 0),
        )],
    )


def fetch_entry_signals_from_classic(
    symbol: str,
    timeframes: Optional[list] = None,
) -> Dict:
    """
    从经典指标系统获取入场信号（Freqtrade 多策略）

    这是 Screen3 执行层的入场信号来源，
    三屏趋势系统只负责大方向判断，具体入场时机由经典系统负责。

    参数:
        symbol: 币种符号
        timeframes: 时间周期列表，默认 ["1h", "4h"]

    返回:
        {timeframe: MultiStrategySignal}
    """
    try:
        from .signals import fetch_freqtrade_signals
        return fetch_freqtrade_signals(symbol, timeframes)
    except ImportError:
        from signals import fetch_freqtrade_signals
        return fetch_freqtrade_signals(symbol, timeframes)
    except Exception:
        return {}


def evaluate_exit_from_classic(
    position_info: Dict,
    candles_1h: Optional[list] = None,
    regime: str = "trend",
) -> Dict:
    """
    从经典指标系统获取离场决策（ClassicExitSystem）

    三屏趋势系统不直接实现离场逻辑，
    离场策略全部委托给经典系统的 ClassicExitSystem。

    参数:
        position_info: 持仓信息字典
            {"symbol", "side", "entry_price", "current_price", "quantity", ...}
        candles_1h: 1小时K线列表
        regime: 市场状态 trend/choppy/neutral

    返回:
        {"action": "close/reduce/hold", "confidence": float, "reason": str, ...}
    """
    try:
        try:
            from .exit_integration import PositionInfo, evaluate_exit
        except ImportError:
            from exit_integration import PositionInfo, evaluate_exit
        pos = PositionInfo(
            symbol=position_info.get("symbol", ""),
            side=position_info.get("side", "long"),
            entry_price=float(position_info.get("entry_price", 0) or 0),
            current_price=float(position_info.get("current_price", 0) or 0),
            quantity=float(position_info.get("quantity", 0) or 0),
            entry_time=float(position_info.get("entry_time", 0) or 0),
            notional_usd=float(position_info.get("notional_usd", 0) or 0),
        )
        result = evaluate_exit(pos, candles_1h, regime)
        return {
            "action": result.action.value,
            "confidence": result.confidence,
            "reason": result.reason,
            "priority": result.priority,
            "reduce_fraction": result.reduce_fraction,
            "suggested_price": result.suggested_price,
            "new_tp_price": result.new_tp_price,
            "new_tp_pct": result.new_tp_pct,
        }
    except Exception as e:
        return {
            "action": "hold",
            "confidence": 0,
            "reason": f"离场系统调用失败: {str(e)[:100]}",
            "priority": "error",
        }


def five_algo_decision(
    trend_consistent: bool,
    direction: str,
    confidence: float,
    freqtrade_signals: Optional[Dict] = None,
    freqtrade_consistent: bool = False,
    btc_wind_vane: Optional[Dict] = None,
    consistency_level: str = "STRONG_CONSISTENT",
    reversal_confidence: float = 0.0,
    daily_dynamics: Optional[Dict] = None,
    trend_phase: str = "UNKNOWN",
    trend_phase_confidence: float = 0.0,
    elder_ray: Optional[Dict] = None,
) -> dict:
    """
    五大算法模式的执行决策（三屏趋势系统完整决策逻辑）

    决策优先级（从高到低）：
    0. BTC风向标闸门（宏观方向过滤，最高优先级）
       - 硬拦截（hard_block=True）：严格禁止反向信号 → WAIT
       - 软拦截（soft_block=True）：动态逆转中，允许轻仓试探反向
    1. Screen1 - 趋势一致性分级：
       - STRONG_CONSISTENT: 正常入场流程
       - REVERSAL_CONSISTENT: 仅允许轻仓试探入场（trial仓位上限）
       - NEUTRAL_CONSISTENT: 正常入场流程（周线中性，日线主导）
       - INCONSISTENT: → WAIT
    2. Screen2 - 置信度评估 + P2 趋势生命周期阶段：
       - EARLY（启动阶段）: 从轻仓开始，降低入场阈值
       - ACCELERATING（加速阶段）: 正常仓位，标准阈值
       - MATURING（成熟/衰竭阶段）: 减仓，不提高阈值（让利润奔跑）
       - REVERSING（逆转阶段）: 反向轻仓试探
       - UNKNOWN: 不调整
    3. Screen3 - 入场时机：
       - Freqtrade 信号：同向信号触发入场（最高优先级）
       - P2-v2 Elder-ray 背离信号（第二屏振荡器）：
         * 上升趋势 + 看涨背离 → 做多入场（回调结束，趋势恢复）
         * 下降趋势 + 看跌背离 → 做空入场（反弹结束，趋势恢复）
       - P1 动态时机评分（speed/accel）：动量充足时允许降级入场
       - 纯置信度降级入场：无任何时机信号时，高置信度也可入场

    核心原则：BTC风向标闸门 → 趋势一致 + 入场时机信号 → 入场

    参数:
        trend_consistent: 趋势是否一致（Screen1，向后兼容）
        direction: 最终方向（BULL/BEAR/NEUTRAL）
        confidence: 综合置信度（0-100）
        freqtrade_signals: Freqtrade信号 {"1h": {...}, "4h": {...}}（Screen3）
        freqtrade_consistent: Freqtrade信号是否与趋势同向
        btc_wind_vane: BTC风向标评估结果（由 evaluate_btc_wind_vane() 生成）
        consistency_level: 一致性级别 STRONG/REVERSAL/NEUTRAL/INCONSISTENT（P0 新增）
        reversal_confidence: 逆转置信度 0-100（P0 新增）
        daily_dynamics: 日线动态指标（P1 新增）
        trend_phase: 趋势生命周期阶段（P2 新增）
        trend_phase_confidence: 阶段判定置信度 0-100（P2 新增）
        elder_ray: Elder-ray 高级分析结果（P2-v2 新增，第二屏振荡器），结构：
            {
                "ema_trend": "BULL"/"BEAR"/"NEUTRAL",
                "bull_divergence": {"detected": bool, "strength": float},
                "bear_divergence": {"detected": bool, "strength": float},
                "bull_losing_control": bool,
                "bear_losing_control": bool,
                "setup_score": float,
            }

    返回:
        {
            "action": "ENTER_LONG"/"ENTER_SHORT"/"WAIT",
            "confidence": float,
            "position": dict,
            "reason": str,
            "wind_vane_blocked": bool,
            "wind_vane_soft_blocked": bool,
            "reversal_trial": bool,
            "dynamic_timing_entry": bool,
            "trend_phase": str,
            "phase_adjusted": bool,
            "elder_ray_divergence_entry": bool,  # P2-v2 新增
        }
    """
    # 默认返回标志
    result_flags = {
        "wind_vane_blocked": False,
        "wind_vane_soft_blocked": False,
        "reversal_trial": False,
        "dynamic_timing_entry": False,
        "trend_phase": trend_phase,
        "phase_adjusted": False,
        "elder_ray_divergence_entry": False,  # P2-v2 新增
    }

    # ── 优先级0：BTC风向标闸门（宏观方向过滤器）──
    if btc_wind_vane and btc_wind_vane.get("enabled"):
        wv_reason = btc_wind_vane.get("reason", "")

        # P0 软拦截处理：软拦截允许轻仓试探反向
        if btc_wind_vane.get("soft_block", False):
            # 软拦截：允许逆向轻仓试探，仓位上限为 trial(0.05)
            rev_dir = btc_wind_vane.get("reversal_direction", "NEUTRAL")
            if direction == rev_dir and direction != "NEUTRAL":
                # 方向匹配逆转方向 → 允许 trial 仓位入场（不走正常流程）
                trial_pos = {"position_pct": 0.05, "tier": "trial"}
                if not freqtrade_signals:
                    # 无 Freqtrade 信号：逆转置信度足够时降级入场
                    if confidence >= 60 or reversal_confidence >= 50:
                        action = "ENTER_LONG" if direction == "BULL" else "ENTER_SHORT"
                        result_flags["wind_vane_soft_blocked"] = True
                        result_flags["reversal_trial"] = True
                        return {
                            "action": action,
                            "confidence": confidence,
                            "position": trial_pos,
                            "reason": f"[风向标软拦截] 动态逆转置信度{reversal_confidence:.1f}%，{direction}轻仓试探入场(trial 5%)。{wv_reason}",
                            **result_flags,
                        }
                else:
                    # 有 Freqtrade 信号：要求 Freqtrade 同向
                    if freqtrade_consistent:
                        action = "ENTER_LONG" if direction == "BULL" else "ENTER_SHORT"
                        result_flags["wind_vane_soft_blocked"] = True
                        result_flags["reversal_trial"] = True
                        return {
                            "action": action,
                            "confidence": confidence,
                            "position": trial_pos,
                            "reason": f"[风向标软拦截] 动态逆转+Freqtrade同向，{direction}轻仓试探入场(trial 5%)。{wv_reason}",
                            **result_flags,
                        }
                # 软拦截下方向匹配但条件不足 → 观望
                return {
                    "action": "WAIT",
                    "confidence": confidence,
                    "position": confidence_to_position(0),
                    "reason": f"[风向标软拦截] 逆转方向匹配但入场条件不足（需Freqtrade同向或置信度≥60），观望。{wv_reason}",
                    **result_flags,
                }
            # 软拦截下方向不匹配逆转方向 → 不入场（继续后续流程会被硬拦截逻辑处理）
            # 这里让流程继续，但标记软拦截状态
            result_flags["wind_vane_soft_blocked"] = True

        # 硬拦截逻辑（原有逻辑保持）
        # 强制做多场景：站上MA200时，BEAR信号一律硬拦截
        if btc_wind_vane.get("force_long") and direction == "BEAR" and btc_wind_vane.get("hard_block", True):
            result_flags["wind_vane_blocked"] = True
            return {
                "action": "WAIT",
                "confidence": confidence,
                "position": confidence_to_position(0),
                "reason": f"[风向标硬拦截] BTC站上周线MA200强制做多，禁止做空信号。{wv_reason}",
                **result_flags,
            }

        # 做空闸门关闭：禁止ENTER_SHORT（硬拦截）
        if not btc_wind_vane.get("short_gate_open", True) and direction == "BEAR" and btc_wind_vane.get("hard_block", True):
            result_flags["wind_vane_blocked"] = True
            return {
                "action": "WAIT",
                "confidence": confidence,
                "position": confidence_to_position(0),
                "reason": f"[风向标硬拦截] 做空闸门关闭。{wv_reason}",
                **result_flags,
            }

        # 做多闸门关闭：禁止ENTER_LONG（硬拦截）
        if not btc_wind_vane.get("long_gate_open", True) and direction == "BULL" and btc_wind_vane.get("hard_block", True):
            result_flags["wind_vane_blocked"] = True
            return {
                "action": "WAIT",
                "confidence": confidence,
                "position": confidence_to_position(0),
                "reason": f"[风向标硬拦截] 做多闸门关闭。{wv_reason}",
                **result_flags,
            }

    # ── 优先级1：趋势一致性分级判定 ──
    if direction == "NEUTRAL":
        return {
            "action": "WAIT",
            "confidence": confidence,
            "position": confidence_to_position(0),
            "reason": "方向中性，等待",
            **result_flags,
        }

    if not trend_consistent:
        # INCONSISTENT：硬拦截
        return {
            "action": "WAIT",
            "confidence": confidence,
            "position": confidence_to_position(0),
            "reason": "趋势不一致，观望",
            **result_flags,
        }

    # REVERSAL_CONSISTENT：标记为逆转试探，仓位上限为 trial
    is_reversal_trial = (consistency_level == "REVERSAL_CONSISTENT")

    pos = confidence_to_position(confidence)

    # 逆转一致：强制仓位上限为 trial(0.05)
    if is_reversal_trial:
        if pos["position_pct"] > 0.05:
            pos = {"position_pct": 0.05, "tier": "trial"}
        result_flags["reversal_trial"] = True

    # ── P2-v2: 趋势生命周期阶段调整（基于Elder-ray理论）──
    # 三重滤网第二屏：用 Elder-ray 的多空力量 + 背离信号辅助第二屏决策
    # 阶段置信度阈值：只有阶段判定置信度≥30才调整
    PHASE_CONF_THRESHOLD = 30.0
    phase_applicable = trend_phase_confidence >= PHASE_CONF_THRESHOLD and not is_reversal_trial

    if phase_applicable:
        if trend_phase == "EARLY":
            # 启动阶段：EMA刚转向，力量开始积累 → 轻仓试探，降低阈值早入场
            if pos["position_pct"] > 0.10:
                pos = {"position_pct": 0.10, "tier": "light"}
            phase_threshold_offset = -10
            result_flags["phase_adjusted"] = True
        elif trend_phase == "ACCELERATING":
            # 加速阶段：EMA趋势明确 + 对手失控 → 正常仓位，正常阈值
            phase_threshold_offset = 0
        elif trend_phase == "MATURING":
            # 成熟/衰竭阶段：EMA趋势仍在但背离出现，双方力量减弱
            # 策略：不减仓（让利润奔跑），但提高止损敏感度（这里仅减仓30%）
            if pos["position_pct"] > 0.20:
                pos = {"position_pct": round(pos["position_pct"] * 0.7, 4), "tier": "moderate"}
            elif pos["position_pct"] > 0.10:
                pos = {"position_pct": round(pos["position_pct"] * 0.7, 4), "tier": "light"}
            phase_threshold_offset = 0
            result_flags["phase_adjusted"] = True
        elif trend_phase == "REVERSING":
            # 逆转阶段：EMA走平 + 背离 + 失控 → 反向轻仓试探
            if pos["position_pct"] > 0.05:
                pos = {"position_pct": 0.05, "tier": "trial"}
            phase_threshold_offset = -10
            result_flags["phase_adjusted"] = True
        else:
            phase_threshold_offset = 0
    else:
        phase_threshold_offset = 0

    ft_signals = freqtrade_signals or {}

    # Screen3: Freqtrade入场信号触发
    ft_bull = False
    ft_bear = False
    ft_trigger_tf = None
    for tf in ["4h", "1h"]:
        sig = ft_signals.get(tf, {})
        sig_dir = sig.get("signal", "HOLD")
        if sig_dir == "BUY" or sig_dir == "LONG":
            ft_bull = True
            ft_trigger_tf = tf
        elif sig_dir == "SELL" or sig_dir == "SHORT":
            ft_bear = True
            ft_trigger_tf = tf

    # 仓位档位描述（用于日志）
    if is_reversal_trial:
        pos_label = "逆转轻仓试探(trial 5%)"
    elif phase_applicable and trend_phase == "EARLY":
        pos_label = "启动阶段轻仓(light)"
    elif phase_applicable and trend_phase == "MATURING":
        pos_label = f"衰竭阶段减仓({pos['position_pct']*100:.0f}%)"
    elif phase_applicable and trend_phase == "REVERSING":
        pos_label = "逆转阶段试探(trial 5%)"
    elif confidence >= OPEN_CONFIDENCE_THRESHOLD:
        pos_label = "正常仓位"
    elif confidence >= TRIAL_CONFIDENCE_THRESHOLD:
        pos_label = "轻仓试探"
    else:
        pos_label = f"微仓({pos['position_pct']*100:.0f}%)"

    # 逆转状态下降级入场阈值：60%（vs 正常 70%）
    base_fallback = 60 if is_reversal_trial else 70
    fallback_threshold = base_fallback + phase_threshold_offset
    # 阈值边界限制：不低于 45，不高于 85
    fallback_threshold = max(45, min(85, fallback_threshold))

    # ── P1: 动态时机评分（无 Freqtrade 信号时，用 speed/accel 寻找入场时机）──
    # 评分逻辑：
    # - speed 高 + accel 正（加速） → 动量强劲，降低入场阈值
    # - speed 高 + accel 负（减速） → 动量衰竭，提高入场阈值
    # - speed 低 → 时机不佳，不降级入场
    DYNAMIC_SPEED_THRESHOLD = 30.0   # speed ≥ 30 视为动量充足
    DYNAMIC_ACCEL_THRESHOLD = 10.0   # accel ≥ 10 视为加速

    dynamic_timing_score = 0.0
    daily_speed = 0.0
    daily_accel = 0.0
    if daily_dynamics:
        daily_speed = float(daily_dynamics.get("avg_speed", 0))
        daily_accel = float(daily_dynamics.get("avg_acceleration", 0))

        # 动量充足 + 加速 → 时机评分高（可降低入场阈值 10 分）
        if daily_speed >= DYNAMIC_SPEED_THRESHOLD and daily_accel >= DYNAMIC_ACCEL_THRESHOLD:
            dynamic_timing_score = 1.0  # 强动量+加速
        elif daily_speed >= DYNAMIC_SPEED_THRESHOLD * 0.7 and daily_accel >= 0:
            dynamic_timing_score = 0.5  # 中等动量+非减速
        # speed 低 或 accel 负 → 时机评分 0（不降级入场）

    # 动态时机入场阈值：时机评分高时，降级入场阈值从 70 降到 60
    dynamic_fallback_threshold = fallback_threshold
    if dynamic_timing_score >= 1.0:
        dynamic_fallback_threshold = max(60, fallback_threshold - 10)
    elif dynamic_timing_score >= 0.5:
        dynamic_fallback_threshold = max(65, fallback_threshold - 5)

    # ── P2-v2: Elder-ray 第二屏振荡器（背离信号增强入场）──
    # 三重滤网第二屏核心逻辑（Alexander Elder）：
    # - 第一屏（周线）定主趋势方向
    # - 第二屏（日线）用 Elder-ray 找与主趋势相反的回撤/背离点
    #   * 主趋势向上 + 日线看涨背离 → 做多（回调结束，趋势恢复）
    #   * 主趋势向下 + 日线看跌背离 → 做空（反弹结束，趋势恢复）
    # - 第三屏（小时线/Freqtrade）精确入场
    #
    # 关键洞察：背离信号与趋势方向"相反"是正常的 — 背离出现在回调中
    # 因此背离方向应该是"与入场方向一致"（看涨背离=做多信号），而不是与direction相同
    # 当 direction=BULL 时，我们要找的是看涨背离（Bear Power 背离）— 回调买入
    # 当 direction=BEAR 时，我们要找的是看跌背离（Bull Power 背离）— 反弹卖出
    #
    # 但实际数据显示：看涨背离常出现在direction=BEAR时（下跌末端），
    # 看跌背离常出现在direction=BULL时（上涨末端）。
    # 这说明：背离更多是"逆转信号"而非"回调信号"。
    # 因此：背离可以作为逆转/反转的确认信号，在 REVERSAL_CONSISTENT 时增强入场信心。

    elder_divergence_bonus = 0.0  # 阈值降低值
    elder_divergence_type = None  # "bull" / "bear"

    if elder_ray and not ft_signals:  # 无 Freqtrade 信号时才启用 Elder-ray 背离
        er_bull_div = elder_ray.get("bull_divergence", {})
        er_bear_div = elder_ray.get("bear_divergence", {})
        er_ema_trend = elder_ray.get("ema_trend", "NEUTRAL")

        # 场景1: 趋势一致 + 同向背离（趋势内回调，顺势入场）
        # 例如：主趋势BULL，日线看涨背离（回调后继续向上）→ 做多
        # 例如：主趋势BEAR，日线看跌背离（反弹后继续向下）→ 做空
        # P2-v3: 降低阈值，提升权重（背离 = 动态趋势切换信号）
        if direction == "BULL" and er_bear_div.get("detected", False) and consistency_level in ("STRONG_CONSISTENT", "NEUTRAL_CONSISTENT"):
            div_strength = er_bear_div.get("strength", 0.0)
            if div_strength >= 40:
                elder_divergence_bonus = 25
            elif div_strength >= 25:
                elder_divergence_bonus = 20
            elif div_strength >= 10:
                elder_divergence_bonus = 15
            elder_divergence_type = "bull"

        elif direction == "BEAR" and er_bull_div.get("detected", False) and consistency_level in ("STRONG_CONSISTENT", "NEUTRAL_CONSISTENT"):
            div_strength = er_bull_div.get("strength", 0.0)
            if div_strength >= 40:
                elder_divergence_bonus = 25
            elif div_strength >= 25:
                elder_divergence_bonus = 20
            elif div_strength >= 10:
                elder_divergence_bonus = 15
            elder_divergence_type = "bear"

        # 场景2: 逆转一致 + 背离确认（Elder-ray 背离作为动态趋势切换的核心判据）
        # 背离本身就是趋势到另一种趋势的切换 → 给予最高权重
        elif consistency_level == "REVERSAL_CONSISTENT":
            if direction == "BULL" and er_bear_div.get("detected", False):
                div_strength = er_bear_div.get("strength", 0.0)
                if div_strength >= 25:
                    elder_divergence_bonus = 25
                elif div_strength >= 10:
                    elder_divergence_bonus = 20
                else:
                    elder_divergence_bonus = 15  # 有背离即给权重
                elder_divergence_type = "bull"
            elif direction == "BEAR" and er_bull_div.get("detected", False):
                div_strength = er_bull_div.get("strength", 0.0)
                if div_strength >= 25:
                    elder_divergence_bonus = 25
                elif div_strength >= 10:
                    elder_divergence_bonus = 20
                else:
                    elder_divergence_bonus = 15
                elder_divergence_type = "bear"

    # 最终入场阈值：取动态时机和 Elder-ray 背离中最激进的（最低的阈值）
    final_entry_threshold = dynamic_fallback_threshold
    if elder_divergence_bonus > 0:
        # P2-v3: 背离权重提升后，阈值下限从 45 降到 40
        elder_fallback_threshold = max(40, fallback_threshold - elder_divergence_bonus)
        final_entry_threshold = min(dynamic_fallback_threshold, elder_fallback_threshold)

    if direction == "BULL":
        if ft_bull and freqtrade_consistent:
            action = "ENTER_LONG"
            reason = f"趋势一致+Freqtrade {ft_trigger_tf}看多+置信{confidence:.1f}%，{pos_label}入场"
        elif not ft_signals:
            # P2-v2 Elder-ray 背离 + P1 动态时机 + 纯置信度 三级降级入场
            if confidence >= final_entry_threshold:
                action = "ENTER_LONG"
                if elder_divergence_type == "bull":
                    result_flags["elder_ray_divergence_entry"] = True
                    result_flags["dynamic_timing_entry"] = False
                    er_str = er_bear_div.get("strength", 0.0) if elder_ray else 0
                    reason = (f"经典系统不可用，趋势一致+看涨背离(强度{er_str:.0f})+置信{confidence:.1f}%"
                              f"≥{final_entry_threshold}%，Elder-ray背离入场({pos_label})")
                elif dynamic_timing_score >= 1.0:
                    result_flags["dynamic_timing_entry"] = True
                    reason = f"经典系统不可用，趋势一致+置信{confidence:.1f}%≥{final_entry_threshold}%，动态时机入场(speed={daily_speed:.1f}/accel={daily_accel:.1f}，{pos_label})"
                elif dynamic_timing_score >= 0.5:
                    result_flags["dynamic_timing_entry"] = True
                    reason = f"经典系统不可用，趋势一致+置信{confidence:.1f}%≥{final_entry_threshold}%，中等动态时机入场({pos_label})"
                else:
                    reason = f"经典系统不可用，趋势一致+置信{confidence:.1f}%≥{final_entry_threshold}%，降级入场({pos_label})"
            else:
                action = "WAIT"
                div_info = f"，Elder-ray背离阈值{final_entry_threshold}" if elder_divergence_bonus > 0 else f"，动态时机评分{dynamic_timing_score}"
                reason = f"Freqtrade信号缺失+置信{confidence:.1f}%<{final_entry_threshold}%，观望{div_info}"
        else:
            action = "WAIT"
            reason = f"Freqtrade无同向信号（1h={ft_signals.get('1h',{}).get('signal','HOLD')}, 4h={ft_signals.get('4h',{}).get('signal','HOLD')}），等待入场时机"
    elif direction == "BEAR":
        if ft_bear and freqtrade_consistent:
            action = "ENTER_SHORT"
            reason = f"趋势一致+Freqtrade {ft_trigger_tf}看空+置信{confidence:.1f}%，{pos_label}入场"
        elif not ft_signals:
            if confidence >= final_entry_threshold:
                action = "ENTER_SHORT"
                if elder_divergence_type == "bear":
                    result_flags["elder_ray_divergence_entry"] = True
                    result_flags["dynamic_timing_entry"] = False
                    er_str = er_bull_div.get("strength", 0.0) if elder_ray else 0
                    reason = (f"经典系统不可用，趋势一致+看跌背离(强度{er_str:.0f})+置信{confidence:.1f}%"
                              f"≥{final_entry_threshold}%，Elder-ray背离入场({pos_label})")
                elif dynamic_timing_score >= 1.0:
                    result_flags["dynamic_timing_entry"] = True
                    reason = f"经典系统不可用，趋势一致+置信{confidence:.1f}%≥{final_entry_threshold}%，动态时机入场(speed={daily_speed:.1f}/accel={daily_accel:.1f}，{pos_label})"
                elif dynamic_timing_score >= 0.5:
                    result_flags["dynamic_timing_entry"] = True
                    reason = f"经典系统不可用，趋势一致+置信{confidence:.1f}%≥{final_entry_threshold}%，中等动态时机入场({pos_label})"
                else:
                    reason = f"经典系统不可用，趋势一致+置信{confidence:.1f}%≥{final_entry_threshold}%，降级入场({pos_label})"
            else:
                action = "WAIT"
                div_info = f"，Elder-ray背离阈值{final_entry_threshold}" if elder_divergence_bonus > 0 else f"，动态时机评分{dynamic_timing_score}"
                reason = f"Freqtrade信号缺失+置信{confidence:.1f}%<{final_entry_threshold}%，观望{div_info}"
        else:
            action = "WAIT"
            reason = f"Freqtrade无同向信号（1h={ft_signals.get('1h',{}).get('signal','HOLD')}, 4h={ft_signals.get('4h',{}).get('signal','HOLD')}），等待入场时机"
    else:
        action = "WAIT"
        reason = "方向中性，等待"

    return {
        "action": action,
        "confidence": round(confidence, 1),
        "position": pos,
        "reason": reason,
        **result_flags,
    }


def compute_trend_signal_from_dataframes(
    weekly_df,
    daily_df,
    symbol: str = "BTC",
    price: Optional[float] = None,
    fundamental_data: Optional[Dict] = None,
    freqtrade_signals: Optional[Dict] = None,
    is_btc: bool = False,
    btc_daily_df=None,
    btc_weekly_df=None,
    btc_trend_direction: Optional[str] = None,
    use_fundamental: Optional[bool] = None,
) -> dict:
    """
    基于 DataFrame 计算完整三屏趋势信号（核心算法层）

    这是系统的纯计算入口，不依赖外部数据获取。
    数据获取由 data/ 层负责，计算层与数据层解耦。

    参数:
        weekly_df: 周线K线 DataFrame (open/high/low/close/volume)
        daily_df: 日线K线 DataFrame
        symbol: 币种符号
        price: 当前价格（可选，从 daily_df 推断）
        fundamental_data: 基本面数据 {"direction", "confidence"}（可选）
        freqtrade_signals: Freqtrade信号 {"1h": {...}, "4h": {...}}（可选）
        is_btc: 是否为BTC币种
        btc_daily_df: BTC日线DataFrame（用于波动率基准 + 风向标MA128检测）
        btc_weekly_df: BTC周线DataFrame（用于风向标MA200检测）
        btc_trend_direction: BTC 趋势方向 "BULL"/"BEAR"/"NEUTRAL"（可选）
            非BTC币种趋势跟随过滤：仅允许与BTC同向开单，禁止逆向开单
        use_fundamental: 是否启用基本面融合（None=从config读取，True/False=强制）
            基本面不可用时自动回退到纯技术分析

    返回:
        完整信号结构，详见技术文档第7节
    """
    if price is None and daily_df is not None and len(daily_df) > 0:
        price = float(daily_df["close"].iloc[-1])

    fundamental_data = fundamental_data or {"direction": "NEUTRAL", "confidence": 0}
    freqtrade_signals = freqtrade_signals or {}

    trend_consistency = calc_trend_consistency(weekly_df, daily_df, use_fundamental=use_fundamental)

    bayesian_confidence = calc_bayesian_confidence(weekly_df, daily_df)

    classic_confidence = calc_classic_indicator_confidence(weekly_df, daily_df)

    fusion_result = fuse_technical_fundamental(
        {"direction": bayesian_confidence["direction"], "confidence": bayesian_confidence["confidence"]},
        fundamental_data
    )

    # ── P3.4: 综合预测引擎（技术基线 + 基本面三维度调节）──
    # 核心公式: final_confidence = tech_confidence × (1 + fundamental_adjustment)
    # 基本面通过方向/速度/加速度/情绪四维因子调节技术面置信度
    composite_prediction = None
    try:
        from .core.composite_predictor import create_composite_predictor
        predictor = create_composite_predictor()
        tech_result_for_composite = {
            "direction": trend_consistency.get("overall_direction", "NEUTRAL"),
            "confidence": trend_consistency.get("consistency_confidence", 0.0),
        }
        composite_prediction = predictor.predict(
            tech_result=tech_result_for_composite,
            fundamental_data=fundamental_data,
        )
    except Exception:
        composite_prediction = None

    final_direction = fusion_result["final_direction"]
    final_confidence = fusion_result["final_confidence"]

    # 应用综合预测引擎的调节因子
    if composite_prediction and composite_prediction.get("fundamental", {}).get("adjustment", {}).get("adjustment") != 0:
        adjustment = composite_prediction["fundamental"]["adjustment"]
        adjustment_type = adjustment.get("adjustment_type", "none")
        if adjustment_type == "enhance":
            final_confidence = min(100, final_confidence * (1 + adjustment["adjustment"] * 0.3))
        elif adjustment_type == "weaken":
            final_confidence = max(0, final_confidence * (1 + adjustment["adjustment"] * 0.3))

    # ── P2-v3: Elder-ray 背离确认时，使用趋势一致性判定的方向 ──
    # 核心思想：Elder-ray 背离代表动态趋势切换，背离确认的方向应覆盖融合方向
    # 这使得背离不仅能降低入场阈值，还能直接决定交易方向
    if trend_consistency.get("elder_divergence_confirm", False):
        er_direction = trend_consistency.get("overall_direction", "NEUTRAL")
        if er_direction != "NEUTRAL" and er_direction != final_direction:
            final_direction = er_direction
            # 背离确认时提升置信度（背离是可靠的切换信号）
            final_confidence = max(final_confidence, 55.0)

    # ── BTC 趋势方向过滤（非 BTC 币种趋势跟随）──
    # 核心逻辑：BTC 方向确定后，小币遵循"多空不对称性"原则：
    # - BTC BULL  → 小币只能做多（ENTER_LONG），禁止做空 — 顺势而为
    # - BTC BEAR  → 小币只能做空（ENTER_SHORT），禁止做多 — 逆势做空需明确信号
    # - BTC NEUTRAL → 默认只允许做多（保守策略），禁止做空 — 市场多空不对称
    btc_direction_blocked = False
    btc_filter_reason = ""
    if not is_btc and btc_trend_direction:
        if btc_trend_direction == "BULL":
            # BTC 看多 → 禁止做空
            if final_direction == "BEAR":
                btc_direction_blocked = True
                btc_filter_reason = "BTC趋势BULL，禁止做空"
                final_direction = "NEUTRAL"
                final_confidence = 0.0
        elif btc_trend_direction == "BEAR":
            # BTC 看空 → 禁止做多
            if final_direction == "BULL":
                btc_direction_blocked = True
                btc_filter_reason = "BTC趋势BEAR，禁止做多"
                final_direction = "NEUTRAL"
                final_confidence = 0.0
        elif btc_trend_direction == "NEUTRAL":
            # BTC 中性 → 默认只做多（市场多空不对称性）
            if final_direction == "BEAR":
                btc_direction_blocked = True
                btc_filter_reason = "BTC趋势NEUTRAL，默认禁止做空（多空不对称）"
                final_direction = "NEUTRAL"
                final_confidence = 0.0

    ft_consistent = _integrate_freqtrade_signals(
        final_direction=final_direction,
        base_confidence=final_confidence,
        freqtrade_signals=freqtrade_signals,
    )
    final_confidence = ft_consistent["adjusted_confidence"]

    # ── BTC风向标评估（全系统做多/做空闸门）──
    # P0 改进：传入逆转上下文，启用软拦截机制
    # BTC自身使用自己的日线/周线数据；其他币种使用传入的BTC数据
    wv_daily_df = daily_df if is_btc else btc_daily_df
    wv_weekly_df = weekly_df if is_btc else btc_weekly_df

    # 构造逆转上下文（仅对 BTC 币种有效：非 BTC 币种使用自己的趋势一致性）
    reversal_context = {
        "consistency_level": trend_consistency.get("consistency_level", "STRONG_CONSISTENT"),
        "reversal_alignment": trend_consistency.get("reversal_alignment", "NONE"),
        "reversal_confidence": trend_consistency.get("reversal_confidence", 0.0),
        "overall_direction": trend_consistency.get("overall_direction", "NEUTRAL"),
    }
    btc_wind_vane = evaluate_btc_wind_vane(wv_daily_df, wv_weekly_df, reversal_context=reversal_context)

    # P1: 提取日线动态指标（speed/acceleration）传给 five_algo_decision 做时机评分
    daily_dynamics_for_timing = None
    daily_info = trend_consistency.get("daily", {})
    if daily_info:
        daily_dynamics_for_timing = {
            "avg_speed": daily_info.get("avg_speed", 0),
            "avg_acceleration": daily_info.get("avg_acceleration", 0),
            "signals": daily_info.get("signals", []),
        }

    # P2: 趋势生命周期阶段
    trend_phase_val = trend_consistency.get("trend_phase", "UNKNOWN")
    trend_phase_conf_val = trend_consistency.get("trend_phase_confidence", 0.0)

    # P2-v2: 计算 Elder-ray 高级分析（第二屏振荡器）
    elder_ray_result = None
    if daily_df is not None and len(daily_df) >= 33:
        try:
            from .core.indicators import calc_elder_ray_advanced
        except ImportError:
            from core.indicators import calc_elder_ray_advanced
        try:
            elder_ray_result = calc_elder_ray_advanced(daily_df, period=13, lookback=20)
        except Exception:
            elder_ray_result = None

    decision = five_algo_decision(
        trend_consistent=trend_consistency["consistent"],
        direction=final_direction,
        confidence=final_confidence,
        freqtrade_signals=freqtrade_signals,
        freqtrade_consistent=ft_consistent["consistent"],
        btc_wind_vane=btc_wind_vane,
        consistency_level=trend_consistency.get("consistency_level", "STRONG_CONSISTENT"),
        reversal_confidence=trend_consistency.get("reversal_confidence", 0.0),
        daily_dynamics=daily_dynamics_for_timing,
        trend_phase=trend_phase_val,
        trend_phase_confidence=trend_phase_conf_val,
        elder_ray=elder_ray_result,
    )

    # === 主策略：V4 减半周期策略（BTC）+ 非BTC趋势跟踪策略 ===
    # BTC: V4 减半周期逃顶策略（定方向）
    # 非BTC: AltcoinTrendStrategy（基于自身MA200+减半周期影子仓位）
    # 9年回测验证：V4年化 53.34%，V4+波浪互斥融合年化 56.43%
    v4_strategy_info = None
    try:
        import pandas as _pd_v4

        if daily_df is not None and len(daily_df) >= 250:
            if is_btc:
                try:
                    from .ml.halving_top_exit_strategy import HalvingTopExitStrategy
                except (ImportError, ValueError):
                    from ml.halving_top_exit_strategy import HalvingTopExitStrategy

                v4_strategy = HalvingTopExitStrategy(
                    symbol=symbol,
                    is_btc=True,
                    btc_prices=daily_df,
                )
                strategy_name = "HalvingTopExitStrategy_v4"
            else:
                try:
                    from .ml.altcoin_trend_strategy import AltcoinTrendStrategy
                except (ImportError, ValueError):
                    from ml.altcoin_trend_strategy import AltcoinTrendStrategy

                v4_strategy = AltcoinTrendStrategy(
                    symbol=symbol,
                    btc_prices=btc_daily_df,
                )
                strategy_name = "AltcoinTrendStrategy"

            v4_position_series = v4_strategy.generate_signals(daily_df)
            v4_position_arr = v4_position_series.values if hasattr(v4_position_series, 'values') else np.array(v4_position_series)
            v4_current_position = float(v4_position_arr[-1]) if len(v4_position_arr) > 0 else 0.0
            v4_abs_position = abs(v4_current_position)

            if v4_current_position > 0.01:
                v4_action = "ENTER_LONG"
                v4_direction = "BULL"
                v4_position_pct = v4_abs_position
            elif v4_current_position < -0.01:
                v4_action = "ENTER_SHORT"
                v4_direction = "BEAR"
                v4_position_pct = v4_abs_position
            else:
                v4_action = "WAIT"
                v4_direction = "NEUTRAL"
                v4_position_pct = 0.0

            v4_strategy_info = {
                "enabled": True,
                "v4_action": v4_action,
                "v4_direction": v4_direction,
                "v4_position_pct": round(v4_position_pct, 4),
                "v4_raw_position": round(v4_current_position, 4),
                "is_btc": is_btc,
                "strategy_name": strategy_name,
            }

            decision["action"] = v4_action
            decision["position"]["position_pct"] = v4_position_pct
            final_direction = v4_direction
            adjusted_position_pct = v4_position_pct
    except Exception as e:
        v4_strategy_info = {
            "enabled": False,
            "error": str(e),
            "reason": "主策略计算异常，回退到三屏趋势决策",
        }

    value_risk = None
    if final_direction != "NEUTRAL" and daily_df is not None and len(daily_df) >= 31:
        try:
            value_risk = compute_value_risk_assessment(
                symbol=symbol,
                direction=final_direction,
                current_price=price if price else 0,
                daily_df=daily_df,
                is_btc=is_btc,
                btc_daily_df=btc_daily_df,
            )
        except Exception:
            value_risk = None

    adjusted_position_pct = decision["position"]["position_pct"]
    if value_risk and value_risk.get("value_gt_risk") is False and decision["action"] in ("ENTER_LONG", "ENTER_SHORT"):
        adjusted_position_pct = min(adjusted_position_pct, 0.05)

    # === PITD 物理置信度调节（方向1条件策略）===
    # 物理引擎作为信号评估器调节仓位，不生成信号
    # 条件：仅在弱趋势状态（η<0.10）启用物理调节，强趋势保持原始仓位
    # 最优参数：网格搜索+Walk-Forward验证（年化7.19%→9.38%，夏普0.3772→0.4364）
    physics_adjustment = None
    if decision["action"] in ("ENTER_LONG", "ENTER_SHORT") and daily_df is not None and len(daily_df) >= 60:
        try:
            import numpy as _np
            import pandas as _pd
            try:
                from .ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights
                from .ml.pitd_kinematics_engineer import KinematicsEngineer
                from .ml.pitd_dynamics_engineer import DynamicsEngineer
            except (ImportError, ValueError):
                from ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights
                from ml.pitd_kinematics_engineer import KinematicsEngineer
                from ml.pitd_dynamics_engineer import DynamicsEngineer

            # 1) 计算 η 判断是否弱趋势
            _kin_fe = KinematicsEngineer()
            _dyn_fe = DynamicsEngineer()
            _kin_feats = _kin_fe.extract_series(daily_df)
            _dyn_feats = _dyn_fe.extract_series(daily_df, _kin_feats)
            _eta_series = _dyn_feats["dyn_coupling_eta"].values
            current_eta = float(_eta_series[-1]) if len(_eta_series) > 0 else 0.0

            # 2) 条件策略：仅在弱趋势时启用物理调节
            if current_eta < 0.10:
                # 3) 从决策方向+置信度推导 ML 信号（[-1,+1] 等价于 [0,1]）
                signal_strength = max(min(final_confidence / 100.0, 1.0), 0.0)
                if decision["action"] == "ENTER_LONG":
                    ml_signal_value = 0.5 + 0.5 * signal_strength  # [0.5, 1.0]
                else:  # ENTER_SHORT
                    ml_signal_value = 0.5 - 0.5 * signal_strength  # [0.0, 0.5]

                # 4) 调用物理置信度评估器（最优参数显式传入）
                optimal_weights = ConfidenceWeights(
                    w_eta=0.211, w_reversal=0.368,
                    w_support=0.211, w_kinetic=0.211,
                    position_lower=0.6, position_scale=1.0,
                )
                _scorer = PhysicsConfidenceScorer(optimal_weights)
                # 构造等长 ML 预测数组（最后一根为当前 bar）
                ml_predictions = _np.full(len(daily_df), 0.5)
                ml_predictions[-1] = ml_signal_value

                confidence_arr, components = _scorer.score_signals(
                    prices=daily_df, ml_predictions=ml_predictions
                )
                current_confidence = float(confidence_arr[-1])

                # 5) 调节仓位（取当前 bar）
                base_pos_arr = _np.array([adjusted_position_pct])
                conf_arr = _np.array([current_confidence])
                adjusted_arr = _scorer.adjust_position(base_pos_arr, conf_arr)
                physics_adjusted_pct = float(adjusted_arr[0])

                # 6) 记录调节信息（供实盘可观测）
                physics_adjustment = {
                    "enabled": True,
                    "weak_trend": True,
                    "current_eta": round(current_eta, 4),
                    "physics_confidence": round(current_confidence, 4),
                    "original_position_pct": round(adjusted_position_pct, 4),
                    "adjusted_position_pct": round(physics_adjusted_pct, 4),
                    "multiplier": round(
                        physics_adjusted_pct / max(adjusted_position_pct, 1e-6), 4
                    ),
                    "weights": {
                        "w_eta": 0.211, "w_reversal": 0.368,
                        "w_support": 0.211, "w_kinetic": 0.211,
                        "position_lower": 0.6, "position_scale": 1.0,
                    },
                    "components": {
                        "trend_score": round(float(components["trend_score"][-1]), 4),
                        "reversal_score": round(float(components["reversal_score"][-1]), 4),
                        "support_score": round(float(components["support_score"][-1]), 4),
                        "kinetic_score": round(float(components["kinetic_score"][-1]), 4),
                    },
                }
                adjusted_position_pct = physics_adjusted_pct
            else:
                physics_adjustment = {
                    "enabled": False,
                    "weak_trend": False,
                    "current_eta": round(current_eta, 4),
                    "reason": f"η={current_eta:.4f}≥0.10，强趋势保持原始仓位",
                }
        except Exception as e:
            physics_adjustment = {
                "enabled": False,
                "error": str(e),
                "reason": "物理置信度计算异常，保持原始仓位",
            }

    # === 波浪策略：择时加仓（互斥融合：V4定方向，波浪同向加仓）===
    # 波浪理论作为择时加仓信号，物理引擎作为评估器
    # V4主策略定方向 + 波浪择时加仓（3成基础仓位，上限5成）
    # 融合规则：同向叠加、异向以V4为主、V4空仓时波浪轻仓抄底
    wave_strategy = None
    try:
        try:
            from .ml.ewave_strategy_adapter import EWaveStrategyAdapter, WaveConfig
        except (ImportError, ValueError):
            from ml.ewave_strategy_adapter import EWaveStrategyAdapter, WaveConfig
        _wave_adapter = EWaveStrategyAdapter(WaveConfig(base_position=0.3, max_position=0.5))
        wave_strategy = _wave_adapter.evaluate(
            daily_df=daily_df,
            v4_action=decision["action"],
            v4_direction=final_direction,
            v4_position_pct=adjusted_position_pct,
            symbol=symbol,
        )
        # 融合后的总仓位作为最终仓位
        if wave_strategy and wave_strategy.get("enabled"):
            adjusted_position_pct = wave_strategy["total_position_pct"]
            # 如果波浪策略改变了action/direction，更新决策
            if wave_strategy["final_action"] != decision["action"]:
                decision["action"] = wave_strategy["final_action"]
                final_direction = wave_strategy["final_direction"]
    except Exception as e:
        wave_strategy = {
            "enabled": False,
            "error": str(e),
            "reason": "波浪策略计算异常，保持V4原始仓位",
        }

    final_signal = {
        "direction": final_direction,
        "confidence": round(final_confidence, 1),
        "trend_consistent": trend_consistency["consistent"],
        "consistency_level": trend_consistency.get("consistency_level", "STRONG_CONSISTENT"),  # P0 新增
        "reversal_alignment": trend_consistency.get("reversal_alignment", "NONE"),  # P0 新增
        "reversal_confidence": trend_consistency.get("reversal_confidence", 0.0),  # P0 新增
        "fusion_consistent": fusion_result["consistent"],
        "freqtrade_consistent": ft_consistent["consistent"],
        "action": decision["action"],
        "position": {
            "position_pct": adjusted_position_pct,
            "tier": decision["position"]["tier"],
            "original_position_pct": decision["position"]["position_pct"],
        },
        "decision_reason": decision["reason"],
        "wind_vane_blocked": decision.get("wind_vane_blocked", False),
        "wind_vane_soft_blocked": decision.get("wind_vane_soft_blocked", False),  # P0 新增
        "reversal_trial": decision.get("reversal_trial", False),  # P0 新增
        "dynamic_timing_entry": decision.get("dynamic_timing_entry", False),  # P1 新增
        "trend_phase": decision.get("trend_phase", "UNKNOWN"),  # P2 新增
        "phase_adjusted": decision.get("phase_adjusted", False),  # P2 新增
        "elder_ray_divergence_entry": decision.get("elder_ray_divergence_entry", False),  # P2-v2 新增
        "elder_ray": elder_ray_result,  # P2-v2 新增，完整 Elder-ray 结果
        "btc_direction_blocked": btc_direction_blocked,  # BTC趋势方向过滤
        "btc_filter_reason": btc_filter_reason,  # 过滤原因
        "fundamental_fusion": trend_consistency.get("fundamental_fusion"),  # 基本面融合结果
        "composite_prediction": composite_prediction,  # P3.4 综合预测引擎结果
        "leverage": MAX_LEVERAGE,
        "margin_mode": "isolated",
        "max_position_pct": MAX_POSITION_PCT,
        "max_addon_position_pct": MAX_ADDON_POSITION_PCT,
        "v4_strategy": v4_strategy_info,  # V4 主策略信息（定方向）
        "physics_adjustment": physics_adjustment,  # PITD 物理置信度调节信息
        "wave_strategy": wave_strategy,  # 波浪策略择时加仓信息
    }

    return {
        "symbol": symbol,
        "price": round(price, 2) if price else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframes": {
            "weekly": len(weekly_df) if weekly_df is not None else 0,
            "daily": len(daily_df) if daily_df is not None else 0,
        },
        "indicators": {
            "screen1_weekly": SCREEN1_INDICATORS,
            "screen2_daily": SCREEN2_INDICATORS,
        },
        "trend_consistency": trend_consistency,
        "bayesian_confidence": bayesian_confidence,
        "classic_indicator_confidence": classic_confidence,
        "fundamental_data": fundamental_data,
        "freqtrade_signals": freqtrade_signals,
        "technical_fundamental_fusion": fusion_result,
        "value_risk_assessment": value_risk,
        "btc_wind_vane": btc_wind_vane,
        "final_signal": final_signal,
    }


def compute_full_trading_signal(
    spot_inst: str = DEFAULT_INST_SPOT,
    is_btc: bool = True,
) -> dict:
    """
    完整三屏交易信号计算（含数据获取）

    注意：此函数依赖外部数据服务。如需纯计算，请使用 compute_trend_signal_from_dataframes()。

    参数:
        spot_inst: 现货交易对，如 "BTC-USDT"
        is_btc: 是否为BTC币种

    返回:
        完整信号结构
    """
    try:
        from .data.market_data import fetch_candles, resample_candles
        from .data.fundamental_data import fetch_fundamental_data
    except ImportError:
        from data.market_data import fetch_candles, resample_candles
        from data.fundamental_data import fetch_fundamental_data
    import pandas as pd

    symbol = spot_inst.split("-")[0]

    daily = fetch_candles(spot_inst, "1D", 250)
    weekly = fetch_candles(spot_inst, "1W", 210)
    hourly = fetch_candles(spot_inst, "1H", 168)

    if not daily:
        return {"error": f"无法获取{spot_inst} K线数据"}

    price = daily[-1]["c"]

    daily_df = pd.DataFrame({
        "open": [c["o"] for c in daily],
        "high": [c["h"] for c in daily],
        "low": [c["l"] for c in daily],
        "close": [c["c"] for c in daily],
        "volume": [c["vol"] for c in daily],
    })
    weekly_df = pd.DataFrame({
        "open": [c["o"] for c in weekly],
        "high": [c["h"] for c in weekly],
        "low": [c["l"] for c in weekly],
        "close": [c["c"] for c in weekly],
        "volume": [c["vol"] for c in weekly],
    }) if weekly else pd.DataFrame()

    fundamental_data = fetch_fundamental_data(symbol)

    # 基本面数据缺失时回退到经典指标系统
    # A系列研报仅覆盖BTC，非BTC币种直接使用经典指标综合置信度作为基本面
    fundamental_source = "research_reports"
    if not is_btc or fundamental_data.get("total_reports", 0) == 0:
        try:
            try:
                from .core import calc_classic_indicator_confidence
            except ImportError:
                from core import calc_classic_indicator_confidence
            classic_conf = calc_classic_indicator_confidence(weekly_df, daily_df)
            fundamental_data = {
                "direction": classic_conf["overall_direction"],
                "confidence": classic_conf["overall_confidence"],
                "weekly": {
                    "direction": classic_conf["screen1_weekly"]["direction"],
                    "confidence": classic_conf["screen1_weekly"]["confidence"],
                    "regime": f"classic_{classic_conf['screen1_weekly']['direction'].lower()}",
                    "source": "classic_indicator",
                },
                "daily": {
                    "direction": classic_conf["screen2_daily"]["direction"],
                    "confidence": classic_conf["screen2_daily"]["confidence"],
                    "regime": f"classic_{classic_conf['screen2_daily']['direction'].lower()}",
                    "source": "classic_indicator",
                },
                "reports": [{"type": "classic_indicator_fallback", "direction": classic_conf["overall_direction"], "confidence": classic_conf["overall_confidence"]}],
                "bull_count": classic_conf["screen1_weekly"]["bull_count"] + classic_conf["screen2_daily"]["bull_count"],
                "bear_count": classic_conf["screen1_weekly"]["bear_count"] + classic_conf["screen2_daily"]["bear_count"],
                "total_reports": 0,
            }
            fundamental_source = "classic_indicator_fallback"
        except Exception:
            fundamental_source = "none"

    # 获取 Freqtrade 入场信号（1h/4h 多策略投票）
    freqtrade_signals = {}
    try:
        try:
            from .signals import SignalDirection
        except ImportError:
            from signals import SignalDirection
        ft_raw = fetch_entry_signals_from_classic(symbol, ["1h", "4h"])
        for tf, sig in ft_raw.items():
            if hasattr(sig, "direction"):
                sig_map = {SignalDirection.LONG: "BUY", SignalDirection.SHORT: "SELL"}
                freqtrade_signals[tf] = {
                    "signal": sig_map.get(sig.direction, "HOLD"),
                    "confidence": sig.confidence,
                    "strategy": sig.strategies[0].strategy_name if sig.strategies else "Freqtrade",
                }
            elif isinstance(sig, dict):
                freqtrade_signals[tf] = sig
    except Exception:
        pass

    # 获取BTC日线和周线数据（用于风向标评估和波动率基准）
    btc_daily_df = daily_df if is_btc else None
    btc_weekly_df = weekly_df if is_btc else None
    if not is_btc:
        try:
            btc_daily_raw = fetch_candles("BTC-USDT", "1D", 260)
            btc_weekly_raw = fetch_candles("BTC-USDT", "1W", 210)
            if btc_daily_raw:
                btc_daily_df = pd.DataFrame({
                    "open": [c["o"] for c in btc_daily_raw],
                    "high": [c["h"] for c in btc_daily_raw],
                    "low": [c["l"] for c in btc_daily_raw],
                    "close": [c["c"] for c in btc_daily_raw],
                    "volume": [c["vol"] for c in btc_daily_raw],
                })
            if btc_weekly_raw:
                btc_weekly_df = pd.DataFrame({
                    "open": [c["o"] for c in btc_weekly_raw],
                    "high": [c["h"] for c in btc_weekly_raw],
                    "low": [c["l"] for c in btc_weekly_raw],
                    "close": [c["c"] for c in btc_weekly_raw],
                    "volume": [c["vol"] for c in btc_weekly_raw],
                })
        except Exception:
            pass

    result = compute_trend_signal_from_dataframes(
        weekly_df=weekly_df,
        daily_df=daily_df,
        symbol=symbol,
        price=price,
        fundamental_data=fundamental_data,
        freqtrade_signals=freqtrade_signals if freqtrade_signals else None,
        is_btc=is_btc,
        btc_daily_df=btc_daily_df,
        btc_weekly_df=btc_weekly_df,
    )

    if not is_btc and btc_daily_df is not None:
        try:
            vr = compute_value_risk_assessment(
                symbol=symbol,
                direction=result["final_signal"]["direction"],
                current_price=price,
                daily_df=daily_df,
                is_btc=False,
                btc_daily_df=btc_daily_df,
            )
            result["value_risk_assessment"] = vr
            if vr and vr.get("value_gt_risk") is False and result["final_signal"]["action"] in ("ENTER_LONG", "ENTER_SHORT"):
                orig_pos = result["final_signal"]["position"]["position_pct"]
                result["final_signal"]["position"]["position_pct"] = min(orig_pos, 0.05)
                result["final_signal"]["position"]["original_position_pct"] = orig_pos
        except Exception:
            pass

    result["spot_inst"] = spot_inst
    result["is_btc"] = is_btc
    result["fundamental_source"] = fundamental_source

    return result
