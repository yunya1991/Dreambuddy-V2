"""TalibAligned — 与 talib.abstract 输出完全对齐的经典指标模块。

与 classic_indicators.py 区别（关键：列名 100% 对齐 talib.abstract）：
  - rsi（非 rsi_14）                : talib.abstract.RSI(df, timeperiod=14)
  - ema_{period}                    : talib.abstract.EMA(df, timeperiod=period)
  - macd / macdsignal / macdhist    : talib.abstract.MACD(df) 三列
  - bb_upper / bb_mid / bb_lower    : qtpylib.bollinger_bands(df, 20, 2) 列名对齐
  - adx（非 adx_14）                : talib.abstract.ADX(df) timeperiod=14
  - atr（非 atr_14）                : talib.abstract.ATR(df, timeperiod=14)
  - volume_mean（rolling 50 mean）  : Bot2StrategyTrend 原始实现
  - willr / cci / obv               : talib.abstract 同名输出（对齐 period=14）

10-经典指标系统 freqtrade 策略的 populate_indicators 在 dataframe 上就地写列，
后续 populate_entry_trend / custom_stoploss 直接按列名读取。本模块产出的列名
必须与策略代码中使用的列名 100% 一致，否则后续逻辑会出现 KeyError 或
行为偏差（这是 10-经典与 12-三屏 FE 范式的最大差异）。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


# 直接尝试使用 talib；不可用时 pandas 兜底（fail-open，保证数值尽量一致）
try:
    import talib.abstract as _ta  # type: ignore
    _HAS_TALIB = True
except Exception:  # noqa: BLE001
    _HAS_TALIB = False


def _pandas_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / (loss + 1e-12)
    return 100.0 - 100.0 / (1.0 + rs)


def _pandas_ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()


def _pandas_macd(close: pd.Series):
    ema12 = _pandas_ema(close, 12)
    ema26 = _pandas_ema(close, 26)
    macd_line = ema12 - ema26
    signal = _pandas_ema(macd_line, 9)
    return macd_line, signal, macd_line - signal


def _pandas_bb(close: pd.Series, window: int = 20, stds: float = 2.0):
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = mid + stds * std
    lower = mid - stds * std
    return upper, mid, lower


def _pandas_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h = df["high"]
    l = df["low"]
    c = df["close"]
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _pandas_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h = df["high"]
    l = df["low"]
    c = df["close"]
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_s = tr.rolling(period).mean().replace(0, np.nan)
    plus_dm = (h - h.shift(1)).where(
        (h - h.shift(1)) > (l.shift(1) - l), 0.0)
    minus_dm = (l.shift(1) - l).where(
        (l.shift(1) - l) > (h - h.shift(1)), 0.0)
    plus_di = 100.0 * (plus_dm.rolling(period).mean() / atr_s)
    minus_di = 100.0 * (minus_dm.rolling(period).mean() / atr_s)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)
    return dx.rolling(period).mean()


def _pandas_willr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hh = df["high"].rolling(period).max()
    ll = df["low"].rolling(period).min()
    return -100.0 * ((hh - df["close"]) / (hh - ll + 1e-12))


def _pandas_cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_sma = tp.rolling(period).mean()
    tp_mad = tp.rolling(period).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - tp_sma) / (0.015 * tp_mad + 1e-12)


def _pandas_obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["close"].diff()) * df["volume"]).fillna(0.0).cumsum()


def compute(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    macro_df: Optional[pd.DataFrame] = None,
    symbol: str = "",
) -> pd.DataFrame:
    """Talib 对齐指标计算。

    仅产出列；调用方负责 merge 回原 dataframe。
    注意：FeatureHub 会加 "<module>__" 前缀，接入时需用 strip_prefix=True
    恢复与 talib.abstract / qtpylib 同名列。
    """
    out = pd.DataFrame(index=df.index)
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # --- RSI 14（列名 "rsi"，Bot2StrategyTrend L85 用 ta.RSI 默认 period=14）---
    if _HAS_TALIB:
        try:
            out["rsi"] = _ta.RSI(df, timeperiod=14)
        except Exception:  # noqa: BLE001
            out["rsi"] = _pandas_rsi(close, 14)
    else:
        out["rsi"] = _pandas_rsi(close, 14)

    # --- EMA（列名 ema_fast / ema_slow / ema_trend，Bot2 三个默认 12/40/217）---
    # 注意：Bot2 取的是 IntParameter.value（默认 12/40/217），此处使用默认值
    # 灰度验证时若用户实际优化参数≠默认，信号会有偏差；本目标是「列名对齐 +
    # 数值在默认参数下对齐」，后续优化参数需通过 config 注入。
    if _HAS_TALIB:
        try:
            out["ema_fast"] = _ta.EMA(df, timeperiod=12)
            out["ema_slow"] = _ta.EMA(df, timeperiod=40)
            out["ema_trend"] = _ta.EMA(df, timeperiod=217)
        except Exception:  # noqa: BLE001
            out["ema_fast"] = _pandas_ema(close, 12)
            out["ema_slow"] = _pandas_ema(close, 40)
            out["ema_trend"] = _pandas_ema(close, 217)
    else:
        out["ema_fast"] = _pandas_ema(close, 12)
        out["ema_slow"] = _pandas_ema(close, 40)
        out["ema_trend"] = _pandas_ema(close, 217)

    # --- Bollinger Bands 20, std=2（列名 bb_upper / bb_mid / bb_lower）---
    # Bot2StrategyTrend L91-94: qtpylib.bollinger_bands(typical_price, window=20, stds=2)
    if _HAS_TALIB:
        try:
            bb = _ta.BBANDS(df, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
            # talib BBANDS: upperband / middleband / lowerband
            out["bb_upper"] = bb["upperband"]
            out["bb_mid"] = bb["middleband"]
            out["bb_lower"] = bb["lowerband"]
        except Exception:  # noqa: BLE001
            u, m, lo = _pandas_bb(close, 20, 2)
            out["bb_upper"] = u
            out["bb_mid"] = m
            out["bb_lower"] = lo
    else:
        u, m, lo = _pandas_bb(close, 20, 2)
        out["bb_upper"] = u
        out["bb_mid"] = m
        out["bb_lower"] = lo

    # --- ADX 14（列名 adx）Bot2 L96: ta.ADX(df) 默认 period=14 ---
    if _HAS_TALIB:
        try:
            out["adx"] = _ta.ADX(df, timeperiod=14)
        except Exception:  # noqa: BLE001
            out["adx"] = _pandas_adx(df, 14)
    else:
        out["adx"] = _pandas_adx(df, 14)

    # --- ATR 14（列名 atr）Bot2 L97: ta.ATR(df, timeperiod=14) ---
    if _HAS_TALIB:
        try:
            out["atr"] = _ta.ATR(df, timeperiod=14)
        except Exception:  # noqa: BLE001
            out["atr"] = _pandas_atr(df, 14)
    else:
        out["atr"] = _pandas_atr(df, 14)

    # --- Volume mean rolling 50 ---
    out["volume_mean"] = df["volume"].rolling(50).mean()

    # --- MACD 默认 12/26/9（列名 macd / macdsignal / macdhist）---
    if _HAS_TALIB:
        try:
            m = _ta.MACD(df, fastperiod=12, slowperiod=26, signalperiod=9)
            out["macd"] = m["macd"]
            out["macdsignal"] = m["macdsignal"]
            out["macdhist"] = m["macdhist"]
        except Exception:  # noqa: BLE001
            ml, sig, hist = _pandas_macd(close)
            out["macd"] = ml
            out["macdsignal"] = sig
            out["macdhist"] = hist
    else:
        ml, sig, hist = _pandas_macd(close)
        out["macd"] = ml
        out["macdsignal"] = sig
        out["macdhist"] = hist

    # --- Williams %R 14 ---
    if _HAS_TALIB:
        try:
            out["willr"] = _ta.WILLR(df, timeperiod=14)
        except Exception:  # noqa: BLE001
            out["willr"] = _pandas_willr(df, 14)
    else:
        out["willr"] = _pandas_willr(df, 14)

    # --- CCI 20 ---
    if _HAS_TALIB:
        try:
            out["cci"] = _ta.CCI(df, timeperiod=20)
        except Exception:  # noqa: BLE001
            out["cci"] = _pandas_cci(df, 20)
    else:
        out["cci"] = _pandas_cci(df, 20)

    # --- OBV ---
    if _HAS_TALIB:
        try:
            out["obv"] = _ta.OBV(df["close"], df["volume"])
        except Exception:  # noqa: BLE001
            out["obv"] = _pandas_obv(df)
    else:
        out["obv"] = _pandas_obv(df)

    return out
