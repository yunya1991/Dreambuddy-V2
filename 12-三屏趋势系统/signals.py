"""三屏趋势系统 — 入场信号服务

从信号池（pool.json）读取 Freqtrade 多策略入场信号。

信号池由 signal_pool/scanner.py 定时扫描全币种生成，包含
1h 和 4h 两个时间周期的多策略投票结果。

三屏趋势系统的定位：
- Screen1/Screen2：大周期趋势方向 + 置信度（本模块计算）
- Screen3：执行层入场时机 → 从信号池读取 Freqtrade 策略信号
"""

import os
import json
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


# 信号池文件路径
_POOL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_pool", "pool.json")

# 信号池缓存（避免每次读文件）
_pool_cache = None
_pool_cache_mtime = 0


def _load_pool() -> dict:
    """加载信号池（带文件修改时间缓存）"""
    global _pool_cache, _pool_cache_mtime
    try:
        mtime = os.path.getmtime(_POOL_FILE)
        if _pool_cache is not None and mtime == _pool_cache_mtime:
            return _pool_cache
        with open(_POOL_FILE, "r") as f:
            _pool_cache = json.load(f)
            _pool_cache_mtime = mtime
            return _pool_cache
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def fetch_freqtrade_signals(
    symbol: str,
    timeframes: Optional[List[str]] = None,
) -> Dict[str, MultiStrategySignal]:
    """
    从信号池读取 Freqtrade 多策略信号

    参数:
        symbol: 币种符号，如 "BTC"
        timeframes: 时间周期列表，如 ["1h", "4h"]，默认 ["1h", "4h"]

    返回:
        {timeframe: MultiStrategySignal}

    说明:
        信号池由 signal_pool/scanner.py 定时生成（默认每5分钟）。
        如果信号池不存在或币种未在池中，返回中性信号。
    """
    timeframes = timeframes or ["1h", "4h"]
    pool = _load_pool()

    if not pool or not pool.get("signals"):
        # 信号池不存在或为空，返回中性信号
        return {tf: _neutral_signal(symbol, tf) for tf in timeframes}

    pool_signals = pool["signals"]
    coin_data = pool_signals.get(symbol, {})

    result = {}
    for tf in timeframes:
        tf_data = coin_data.get(tf, {})
        if tf_data:
            result[tf] = _dict_to_multi_signal(symbol, tf, tf_data)
        else:
            result[tf] = _neutral_signal(symbol, tf)

    return result


def _dict_to_multi_signal(symbol: str, timeframe: str, data: dict) -> MultiStrategySignal:
    """将信号池中的字典转换为 MultiStrategySignal"""
    signal_str = (data.get("signal") or "hold").lower()
    conf = float(data.get("confidence", 0) or 0)
    strategy_name = data.get("strategy", f"freqtrade_{timeframe}")

    direction = _parse_direction(signal_str)
    details = data.get("details", [])

    strategies = []
    for d in details:
        strategies.append(StrategySignal(
            strategy_name=d.get("strategy", ""),
            signal=_parse_direction(d.get("signal", "hold")),
            confidence=float(d.get("weight", 0)) * 100,
        ))

    if not strategies:
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
        strategy_count=len(strategies),
        long_votes=sum(1 for s in strategies if s.signal == SignalDirection.LONG),
        short_votes=sum(1 for s in strategies if s.signal == SignalDirection.SHORT),
        strategies=strategies,
    )


def _parse_direction(signal_str: str) -> SignalDirection:
    """解析信号方向字符串"""
    s = signal_str.lower().strip()
    if s in ("long", "buy", "bull", "enter_long"):
        return SignalDirection.LONG
    if s in ("short", "sell", "bear", "enter_short"):
        return SignalDirection.SHORT
    return SignalDirection.HOLD


def _neutral_signal(symbol: str, timeframe: str) -> MultiStrategySignal:
    """返回中性/空信号（信号池不可用时的降级）"""
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
