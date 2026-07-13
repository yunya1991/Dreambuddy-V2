"""三屏趋势系统 — 入场信号服务

通过经典指标系统（10-经典指标系统）获取 Freqtrade 多策略入场信号。

三屏趋势系统的定位：
- Screen1/Screen2：大周期趋势方向 + 置信度（本模块计算）
- Screen3：执行层入场时机 → 委托给经典系统的 Freqtrade 策略

这样职责分离：
- 三屏趋势系统 = 「判断做不做、做多空、做多少」
- 经典指标系统 = 「具体什么时候进场、什么时候离场」
"""

from typing import Dict, Optional, List
from dataclasses import dataclass
from enum import Enum


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    HOLD = "hold"


@dataclass
class StrategySignal:
    """单策略信号"""
    strategy_name: str
    signal: SignalDirection
    confidence: float = 0.0
    entry_price: Optional[float] = None


@dataclass
class MultiStrategySignal:
    """多策略投票信号"""
    symbol: str
    timeframe: str
    direction: SignalDirection
    confidence: float
    strategy_count: int
    long_votes: int
    short_votes: int
    strategies: List[StrategySignal]

    @property
    def is_long(self) -> bool:
        return self.direction == SignalDirection.LONG

    @property
    def is_short(self) -> bool:
        return self.direction == SignalDirection.SHORT

    @property
    def is_hold(self) -> bool:
        return self.direction == SignalDirection.HOLD


def fetch_freqtrade_signals(
    symbol: str,
    timeframes: Optional[List[str]] = None,
) -> Dict[str, MultiStrategySignal]:
    """
    从经典指标系统获取 Freqtrade 多策略信号

    参数:
        symbol: 币种符号，如 "BTC"
        timeframes: 时间周期列表，如 ["1h", "4h"]，默认 ["1h", "4h"]

    返回:
        {timeframe: MultiStrategySignal}

    说明：
        三屏趋势系统不直接运行 Freqtrade 策略，而是通过经典系统获取信号。
        经典系统负责策略运行、回测优化、参数调优等。
    """
    try:
        from .classic_bridge import _make_request
    except ImportError:
        from classic_bridge import _make_request

    timeframes = timeframes or ["1h", "4h"]
    result = {}

    for tf in timeframes:
        signal = _fetch_single_timeframe(symbol, tf)
        if signal:
            result[tf] = signal

    return result


def _fetch_single_timeframe(symbol: str, timeframe: str) -> Optional[MultiStrategySignal]:
    """获取单个时间周期的信号"""
    try:
        from .classic_bridge import _make_request
    except ImportError:
        from classic_bridge import _make_request

    endpoint_map = {
        "1h": f"/signals/hyperliquid/regime-hybrid?coin={symbol}",
        "4h": f"/signals/hyperliquid/multigroup?coin={symbol}",
    }

    endpoint = endpoint_map.get(timeframe)
    if not endpoint:
        return _neutral_signal(symbol, timeframe)

    resp = _make_request(endpoint, timeout=4.0)
    if not resp["ok"]:
        return _neutral_signal(symbol, timeframe)

    data = resp["data"]
    if isinstance(data, dict):
        signal_str = (data.get("signal") or data.get("direction") or "hold").lower()
        conf = float(data.get("confidence", 0) or 0)
        strategy_name = data.get("strategy", f"freqtrade_{timeframe}")

        direction = _parse_direction(signal_str)
        strategies = [StrategySignal(
            strategy_name=strategy_name,
            signal=direction,
            confidence=conf,
        )]

        return MultiStrategySignal(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=conf,
            strategy_count=1,
            long_votes=1 if direction == SignalDirection.LONG else 0,
            short_votes=1 if direction == SignalDirection.SHORT else 0,
            strategies=strategies,
        )

    return _neutral_signal(symbol, timeframe)


def _parse_direction(signal_str: str) -> SignalDirection:
    """解析信号方向字符串"""
    s = signal_str.lower().strip()
    if s in ("long", "buy", "bull", "enter_long"):
        return SignalDirection.LONG
    if s in ("short", "sell", "bear", "enter_short"):
        return SignalDirection.SHORT
    return SignalDirection.HOLD


def _neutral_signal(symbol: str, timeframe: str) -> MultiStrategySignal:
    """返回中性/空信号（经典系统不可用时的降级）"""
    return MultiStrategySignal(
        symbol=symbol,
        timeframe=timeframe,
        direction=SignalDirection.HOLD,
        confidence=0.0,
        strategy_count=0,
        long_votes=0,
        short_votes=0,
        strategies=[],
    )


def align_freqtrade_with_trend(
    trend_direction: str,
    freqtrade_signal: MultiStrategySignal,
) -> Dict[str, float]:
    """
    将 Freqtrade 信号与趋势方向对齐，校准置信度

    规则：
    - 同向时：增益（1h +10%, 4h +15%）
    - 反向时：扣减 -10%
    - 中性时：不影响

    参数:
        trend_direction: "BULL"/"BEAR"/"NEUTRAL"
        freqtrade_signal: 多策略信号

    返回:
        {"confidence_adjustment": float, "consistent": bool}
    """
    if trend_direction == "NEUTRAL":
        return {"confidence_adjustment": 0.0, "consistent": False}

    tf_weight = {
        "1h": 0.10,
        "4h": 0.15,
    }

    is_bull = trend_direction == "BULL"
    adjustment = 0.0
    consistent = False

    if freqtrade_signal.is_long and is_bull:
        adjustment = freqtrade_signal.confidence * tf_weight.get(freqtrade_signal.timeframe, 0.1)
        consistent = True
    elif freqtrade_signal.is_short and not is_bull:
        adjustment = freqtrade_signal.confidence * tf_weight.get(freqtrade_signal.timeframe, 0.1)
        consistent = True
    elif not freqtrade_signal.is_hold:
        adjustment = -10.0

    return {"confidence_adjustment": adjustment, "consistent": consistent}
