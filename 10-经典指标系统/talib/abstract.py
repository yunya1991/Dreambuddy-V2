from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd


def _as_series(v: Any) -> pd.Series:
    if isinstance(v, pd.Series):
        return v.astype(float)
    if isinstance(v, pd.DataFrame):
        if "close" in v.columns:
            return pd.to_numeric(v["close"], errors="coerce").astype(float)
        return pd.Series(dtype=float)
    return pd.Series(v, dtype=float)


def _ohlcv(v: Any) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    if isinstance(v, pd.DataFrame):
        high = pd.to_numeric(v.get("high"), errors="coerce")
        low = pd.to_numeric(v.get("low"), errors="coerce")
        close = pd.to_numeric(v.get("close"), errors="coerce")
        vol = pd.to_numeric(v.get("volume"), errors="coerce")
        return high.astype(float), low.astype(float), close.astype(float), vol.astype(float)
    s = _as_series(v)
    return s, s, s, pd.Series(np.zeros(len(s)), index=s.index, dtype=float)


def EMA(v: Any, timeperiod: int = 30) -> pd.Series:
    s = _as_series(v if not isinstance(v, pd.DataFrame) else v.get("close"))
    return s.ewm(span=max(1, int(timeperiod)), adjust=False).mean()


def RSI(v: Any, timeperiod: int = 14) -> pd.Series:
    s = _as_series(v if not isinstance(v, pd.DataFrame) else v.get("close"))
    d = s.diff()
    up = d.clip(lower=0.0)
    dn = -d.clip(upper=0.0)
    au = up.ewm(alpha=1 / max(1, int(timeperiod)), adjust=False).mean()
    ad = dn.ewm(alpha=1 / max(1, int(timeperiod)), adjust=False).mean()
    rs = au / ad.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def TRANGE(v: Any) -> pd.Series:
    high, low, close, _ = _ohlcv(v)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.fillna(0.0)


def ATR(*args: Any, timeperiod: int = 14) -> pd.Series:
    if len(args) >= 3 and isinstance(args[0], pd.Series):
        high = pd.to_numeric(args[0], errors="coerce")
        low = pd.to_numeric(args[1], errors="coerce")
        close = pd.to_numeric(args[2], errors="coerce")
        tr = pd.concat([(high - low).abs(), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / max(1, int(timeperiod)), adjust=False).mean().fillna(0.0)
    tr = TRANGE(args[0] if args else pd.Series(dtype=float))
    return tr.ewm(alpha=1 / max(1, int(timeperiod)), adjust=False).mean().fillna(0.0)


def _di_pair(v: Any, timeperiod: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
    high, low, close, _ = _ohlcv(v)
    up = high.diff()
    dn = -low.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=high.index)
    atr = ATR(v, timeperiod=timeperiod).replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / max(1, int(timeperiod)), adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / max(1, int(timeperiod)), adjust=False).mean() / atr
    return plus_di.fillna(0.0), minus_di.fillna(0.0), close


def PLUS_DI(v: Any, timeperiod: int = 14) -> pd.Series:
    plus_di, _, _ = _di_pair(v, timeperiod=timeperiod)
    return plus_di


def MINUS_DI(v: Any, timeperiod: int = 14) -> pd.Series:
    _, minus_di, _ = _di_pair(v, timeperiod=timeperiod)
    return minus_di


def ADX(v: Any, timeperiod: int = 14) -> pd.Series:
    plus_di, minus_di, _ = _di_pair(v, timeperiod=timeperiod)
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.ewm(alpha=1 / max(1, int(timeperiod)), adjust=False).mean().fillna(0.0)


def MACD(v: Any, fastperiod: int = 12, slowperiod: int = 26, signalperiod: int = 9):
    s = _as_series(v if not isinstance(v, pd.DataFrame) else v.get("close"))
    fast = s.ewm(span=max(1, int(fastperiod)), adjust=False).mean()
    slow = s.ewm(span=max(1, int(slowperiod)), adjust=False).mean()
    macd = fast - slow
    signal = macd.ewm(span=max(1, int(signalperiod)), adjust=False).mean()
    hist = macd - signal
    if isinstance(v, pd.DataFrame):
        return {"macd": macd, "macdsignal": signal, "macdhist": hist}
    return macd, signal, hist


def TEMA(v: Any, timeperiod: int = 30) -> pd.Series:
    s = _as_series(v if not isinstance(v, pd.DataFrame) else v.get("close"))
    e1 = s.ewm(span=max(1, int(timeperiod)), adjust=False).mean()
    e2 = e1.ewm(span=max(1, int(timeperiod)), adjust=False).mean()
    e3 = e2.ewm(span=max(1, int(timeperiod)), adjust=False).mean()
    return 3 * e1 - 3 * e2 + e3


def SAR(v: Any, acceleration: float = 0.02, maximum: float = 0.2) -> pd.Series:
    high, low, close, _ = _ohlcv(v)
    n = len(close)
    if n == 0:
        return pd.Series(dtype=float)
    out = np.zeros(n, dtype=float)
    out[0] = float(low.iloc[0] if np.isfinite(low.iloc[0]) else close.iloc[0])
    long_pos = True
    ep = float(high.iloc[0] if np.isfinite(high.iloc[0]) else close.iloc[0])
    af = float(acceleration)
    for i in range(1, n):
        prev = out[i - 1]
        out[i] = prev + af * (ep - prev)
        hi = float(high.iloc[i]) if np.isfinite(high.iloc[i]) else float(close.iloc[i])
        lo = float(low.iloc[i]) if np.isfinite(low.iloc[i]) else float(close.iloc[i])
        if long_pos:
            if lo < out[i]:
                long_pos = False
                out[i] = ep
                ep = lo
                af = float(acceleration)
            else:
                if hi > ep:
                    ep = hi
                    af = min(float(maximum), af + float(acceleration))
        else:
            if hi > out[i]:
                long_pos = True
                out[i] = ep
                ep = hi
                af = float(acceleration)
            else:
                if lo < ep:
                    ep = lo
                    af = min(float(maximum), af + float(acceleration))
    return pd.Series(out, index=close.index, dtype=float)


def WILLR(v: Any, timeperiod: int = 14) -> pd.Series:
    high, low, close, _ = _ohlcv(v)
    hh = high.rolling(max(1, int(timeperiod)), min_periods=1).max()
    ll = low.rolling(max(1, int(timeperiod)), min_periods=1).min()
    den = (hh - ll).replace(0, np.nan)
    return (-100 * (hh - close) / den).fillna(0.0)


def BBANDS(v: Any, timeperiod: int = 5, nbdevup: float = 2.0, nbdevdn: float = 2.0, matype: int = 0):
    s = _as_series(v if not isinstance(v, pd.DataFrame) else v.get("close"))
    mid = s.rolling(max(1, int(timeperiod)), min_periods=1).mean()
    std = s.rolling(max(1, int(timeperiod)), min_periods=1).std(ddof=0).fillna(0.0)
    up = mid + float(nbdevup) * std
    dn = mid - float(nbdevdn) * std
    if isinstance(v, pd.DataFrame):
        return {"upperband": up, "middleband": mid, "lowerband": dn}
    return up, mid, dn


def STOCHRSI(v: Any, timeperiod: int = 14, fastk_period: int = 5, fastd_period: int = 3, fastd_matype: int = 0) -> Dict[str, pd.Series]:
    rsi = RSI(v, timeperiod=timeperiod)
    lo = rsi.rolling(max(1, int(fastk_period)), min_periods=1).min()
    hi = rsi.rolling(max(1, int(fastk_period)), min_periods=1).max()
    fastk = (100 * (rsi - lo) / (hi - lo).replace(0, np.nan)).fillna(0.0)
    fastd = fastk.rolling(max(1, int(fastd_period)), min_periods=1).mean()
    return {"fastk": fastk, "fastd": fastd}


def OBV(close: Any, volume: Any = None) -> pd.Series:
    c = _as_series(close if not isinstance(close, pd.DataFrame) else close.get("close"))
    if volume is None and isinstance(close, pd.DataFrame):
        volume = close.get("volume")
    v = _as_series(volume if volume is not None else pd.Series(np.zeros(len(c)), index=c.index))
    direction = np.sign(c.diff().fillna(0.0))
    return (direction * v).cumsum().fillna(0.0)
