"""波动率指标计算（纯函数 + talib.abstract）。"""
from __future__ import annotations

import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """平均真实波幅 (Average True Range)。

    衡量市场波动率，非负值，用于止损和仓位管理。
    """
    from talib.abstract import ATR
    return ATR(df, timeperiod=period)


def boll(
    df: pd.DataFrame,
    period: int = 20,
    nbdev: float = 2.0,
) -> pd.DataFrame:
    """布林带 (Bollinger Bands)。

    Returns:
        DataFrame with columns: upper, middle, lower
    """
    from talib.abstract import BBANDS
    result = BBANDS(df, timeperiod=period, nbdevup=nbdev, nbdevdn=nbdev)
    return pd.DataFrame({
        "upper": result["upperband"],
        "middle": result["middleband"],
        "lower": result["lowerband"],
    }, index=df.index)
