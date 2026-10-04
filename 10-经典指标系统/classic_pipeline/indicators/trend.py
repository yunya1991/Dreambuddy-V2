"""趋势指标计算（纯函数 + talib.abstract）。

所有函数输入 OHLCV DataFrame，输出 pd.Series 或 pd.DataFrame。
不依赖全局状态，可独立测试。
"""
from __future__ import annotations

import pandas as pd


def ema(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """指数移动平均线 (Exponential Moving Average)。"""
    from talib.abstract import EMA
    return EMA(df, timeperiod=period)


def sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """简单移动平均线 (Simple Moving Average)。"""
    from talib.abstract import SMA
    return SMA(df, timeperiod=period)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """平均趋向指数 (Average Directional Index)。

    衡量趋势强度，值域 [0, 100]，>25 表示有趋势。
    """
    from talib.abstract import ADX
    return ADX(df, timeperiod=period)


def macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD (Moving Average Convergence Divergence)。

    Returns:
        DataFrame with columns: macd, signal, histogram
    """
    from talib.abstract import MACD
    result = MACD(df, fastperiod=fast, slowperiod=slow, signalperiod=signal)
    return pd.DataFrame({
        "macd": result["macd"],
        "signal": result["macdsignal"],
        "histogram": result["macdhist"],
    }, index=df.index)
