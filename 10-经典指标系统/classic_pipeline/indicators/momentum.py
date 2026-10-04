"""动量指标计算（纯函数 + talib.abstract）。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """相对强弱指数 (Relative Strength Index)。

    值域 [0, 100]，>70 超买，<30 超卖。
    """
    from talib.abstract import RSI
    return RSI(df, timeperiod=period)


def cci(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """顺势指标 (Commodity Channel Index)。"""
    from talib.abstract import CCI
    return CCI(df, timeperiod=period)


def stoch(
    df: pd.DataFrame,
    fastk: int = 14,
    slowk: int = 3,
    slowd: int = 3,
) -> pd.DataFrame:
    """随机指标 (Stochastic Oscillator)。

    注：talib.abstract 未提供 STOCH，此处用 pandas 实现。

    Returns:
        DataFrame with columns: slowk, slowd
    """
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")

    lowest_low = low.rolling(max(1, int(fastk)), min_periods=1).min()
    highest_high = high.rolling(max(1, int(fastk)), min_periods=1).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    fastk_line = (100 * (close - lowest_low) / denom).fillna(0.0)

    slowk_line = fastk_line.rolling(max(1, int(slowk)), min_periods=1).mean()
    slowd_line = slowk_line.rolling(max(1, int(slowd)), min_periods=1).mean()

    return pd.DataFrame({"slowk": slowk_line, "slowd": slowd_line}, index=df.index)
