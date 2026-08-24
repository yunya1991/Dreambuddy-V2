"""ClassicIndicators — 经典技术指标（M3.3 完善，从 M2 stub 升级）

基于 pandas 计算 15+ 常用技术指标，覆盖趋势/动量/波动/成交量四类。
后续 M3.5 可替换为 talib 30+ 指标的 SklearnStyleAdapter。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def compute(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    macro_df: Optional[pd.DataFrame] = None,
    symbol: str = "",
) -> pd.DataFrame:
    """经典技术指标计算（15+ 列）"""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    result = pd.DataFrame(index=df.index)

    # === 移动平均（4列）===
    result["sma_10"] = close.rolling(10).mean()
    result["sma_20"] = close.rolling(20).mean()
    result["sma_50"] = close.rolling(50).mean()
    result["ema_12"] = close.ewm(span=12, adjust=False).mean()

    # === RSI 14（1列）===
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    result["rsi_14"] = 100 - 100 / (1 + rs)

    # === MACD（2列）===
    ema_26 = close.ewm(span=26, adjust=False).mean()
    macd_line = result["ema_12"] - ema_26
    result["macd"] = macd_line
    result["macd_signal"] = macd_line.ewm(span=9, adjust=False).mean()

    # === Bollinger Bands（2列）===
    std = close.rolling(20).std()
    result["bb_upper"] = result["sma_20"] + 2 * std
    result["bb_lower"] = result["sma_20"] - 2 * std

    # === ATR（1列）===
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    result["atr_14"] = tr.rolling(14).mean()

    # === ADX 简化版（1列）===
    plus_dm = (high - high.shift(1)).where(
        (high - high.shift(1)) > (low.shift(1) - low), 0
    )
    minus_dm = (low.shift(1) - low).where(
        (low.shift(1) - low) > (high - high.shift(1)), 0
    )
    atr_sm = result["atr_14"].replace(0, np.nan)
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr_sm)
    minus_di = 100 * (minus_dm.rolling(14).mean() / atr_sm)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10))
    result["adx_14"] = dx.rolling(14).mean()

    # === OBV（1列）===
    obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    result["obv"] = obv

    # === Williams %R（1列）===
    hh = high.rolling(14).max()
    ll = low.rolling(14).min()
    result["willr_14"] = -100 * ((hh - close) / (hh - ll + 1e-10))

    # === CCI（1列）===
    tp = (high + low + close) / 3
    tp_sma = tp.rolling(20).mean()
    tp_mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    result["cci_20"] = (tp - tp_sma) / (0.015 * tp_mad + 1e-10)

    # === Donchian Channel（1列）===
    result["dc_width"] = hh - ll

    return result
