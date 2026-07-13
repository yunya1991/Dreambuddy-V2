"""三屏趋势系统 — 主引擎

核心入口：compute_full_trading_signal()

整合五大算法：
1. 静态指标投票
2. 三维动态融合（方向+速度+加速度，动态优先）
3. 动态权重调整（回测排名 vs MA200基线）
4. 贝叶斯参数寻优（置信度计算）
5. 技术面+基本面撮合

设计理念：趋势一致性确定方向，置信度评估确定仓位。

系统边界：
- 三屏趋势系统 = 「趋势方向判定 + 置信度评估 + 仓位计算」
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
    )
    from core.config import (
        OPEN_CONFIDENCE_THRESHOLD,
        TRIAL_CONFIDENCE_THRESHOLD,
        POSITION_TIERS,
        CONFIDENCE_JUMP_THRESHOLD,
        DEFAULT_INST_SPOT,
    )


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
) -> dict:
    """
    五大算法模式的执行决策（三屏趋势系统完整决策逻辑）

    三屏决策规则：
    1. Screen1 - 趋势一致性：趋势不一致 → WAIT（入场前置条件）
    2. Screen2 - 置信度评估：决定仓位大小（置信度越高仓位越大，低置信度=低仓位）
    3. Screen3 - Freqtrade入场信号：具体入场时机触发（有同向信号才动手）

    核心原则：趋势一致 + Freqtrade同向信号 → 入场，置信度只决定仓位大小

    参数:
        trend_consistent: 趋势是否一致（Screen1）
        direction: 最终方向（BULL/BEAR/NEUTRAL）
        confidence: 综合置信度（0-100）
        freqtrade_signals: Freqtrade信号 {"1h": {...}, "4h": {...}}（Screen3）
        freqtrade_consistent: Freqtrade信号是否与趋势同向

    返回:
        {
            "action": "ENTER_LONG"/"ENTER_SHORT"/"WAIT",
            "confidence": float,
            "position": dict,
            "reason": str,
        }
    """
    if not trend_consistent or direction == "NEUTRAL":
        return {
            "action": "WAIT",
            "confidence": confidence,
            "position": confidence_to_position(0),
            "reason": "趋势不一致或方向中性",
        }

    pos = confidence_to_position(confidence)
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
    if confidence >= OPEN_CONFIDENCE_THRESHOLD:
        pos_label = "正常仓位"
    elif confidence >= TRIAL_CONFIDENCE_THRESHOLD:
        pos_label = "轻仓试探"
    else:
        pos_label = f"微仓({pos['position_pct']*100:.0f}%)"

    if direction == "BULL":
        if ft_bull and freqtrade_consistent:
            action = "ENTER_LONG"
            reason = f"趋势一致+Freqtrade {ft_trigger_tf}看多+置信{confidence:.1f}%，{pos_label}入场"
        elif not ft_signals:
            # Freqtrade信号缺失时降级：仅看置信度（保守）
            if confidence >= 70:
                action = "ENTER_LONG"
                reason = f"经典系统不可用，趋势一致+置信{confidence:.1f}%≥70%，降级入场"
            else:
                action = "WAIT"
                reason = f"Freqtrade信号缺失+置信{confidence:.1f}%<70%，观望"
        else:
            action = "WAIT"
            reason = f"Freqtrade无同向信号（1h={ft_signals.get('1h',{}).get('signal','HOLD')}, 4h={ft_signals.get('4h',{}).get('signal','HOLD')}），等待入场时机"
    elif direction == "BEAR":
        if ft_bear and freqtrade_consistent:
            action = "ENTER_SHORT"
            reason = f"趋势一致+Freqtrade {ft_trigger_tf}看空+置信{confidence:.1f}%，{pos_label}入场"
        elif not ft_signals:
            if confidence >= 70:
                action = "ENTER_SHORT"
                reason = f"经典系统不可用，趋势一致+置信{confidence:.1f}%≥70%，降级入场"
            else:
                action = "WAIT"
                reason = f"Freqtrade信号缺失+置信{confidence:.1f}%<70%，观望"
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
    }


def compute_trend_signal_from_dataframes(
    weekly_df,
    daily_df,
    symbol: str = "BTC",
    price: Optional[float] = None,
    fundamental_data: Optional[Dict] = None,
    freqtrade_signals: Optional[Dict] = None,
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

    返回:
        完整信号结构，详见技术文档第7节
    """
    if price is None and daily_df is not None and len(daily_df) > 0:
        price = float(daily_df["close"].iloc[-1])

    fundamental_data = fundamental_data or {"direction": "NEUTRAL", "confidence": 0}
    freqtrade_signals = freqtrade_signals or {}

    trend_consistency = calc_trend_consistency(weekly_df, daily_df)

    bayesian_confidence = calc_bayesian_confidence(weekly_df, daily_df)

    classic_confidence = calc_classic_indicator_confidence(weekly_df, daily_df)

    fusion_result = fuse_technical_fundamental(
        {"direction": bayesian_confidence["direction"], "confidence": bayesian_confidence["confidence"]},
        fundamental_data
    )

    final_direction = fusion_result["final_direction"]
    final_confidence = fusion_result["final_confidence"]

    ft_consistent = _integrate_freqtrade_signals(
        final_direction=final_direction,
        base_confidence=final_confidence,
        freqtrade_signals=freqtrade_signals,
    )
    final_confidence = ft_consistent["adjusted_confidence"]

    decision = five_algo_decision(
        trend_consistent=trend_consistency["consistent"],
        direction=final_direction,
        confidence=final_confidence,
        freqtrade_signals=freqtrade_signals,
        freqtrade_consistent=ft_consistent["consistent"],
    )

    final_signal = {
        "direction": final_direction,
        "confidence": round(final_confidence, 1),
        "trend_consistent": trend_consistency["consistent"],
        "fusion_consistent": fusion_result["consistent"],
        "freqtrade_consistent": ft_consistent["consistent"],
        "action": decision["action"],
        "position": decision["position"],
        "decision_reason": decision["reason"],
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

    result = compute_trend_signal_from_dataframes(
        weekly_df=weekly_df,
        daily_df=daily_df,
        symbol=symbol,
        price=price,
        fundamental_data=fundamental_data,
        freqtrade_signals=freqtrade_signals if freqtrade_signals else None,
    )

    result["spot_inst"] = spot_inst
    result["is_btc"] = is_btc
    result["fundamental_source"] = fundamental_source

    return result
