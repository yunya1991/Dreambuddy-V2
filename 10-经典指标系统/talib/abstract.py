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


def SUPERTREND(v: Any, period: int = 10, multiplier: float = 3.0):
    """超级趋势指标 (SuperTrend)。返回 dict: {"upperband", "lowerband", "direction"}
    direction: 1=多头趋势, -1=空头趋势
    """
    high, low, close, _ = _ohlcv(v)
    n = len(close)
    if n == 0:
        return {"upperband": pd.Series(dtype=float), "lowerband": pd.Series(dtype=float), "direction": pd.Series(dtype=float)}
    atr = ATR(v, timeperiod=period)
    hl2 = (high + low) / 2.0
    basic_ub = hl2 + float(multiplier) * atr
    basic_lb = hl2 - float(multiplier) * atr
    ub = basic_ub.values
    lb = basic_lb.values
    c = close.values
    final_ub = np.zeros(n, dtype=float)
    final_lb = np.zeros(n, dtype=float)
    trend = np.ones(n, dtype=int)
    final_ub[0] = ub[0]
    final_lb[0] = lb[0]
    for i in range(1, n):
        final_ub[i] = ub[i] if (ub[i] < final_ub[i - 1] or c[i - 1] > final_ub[i - 1]) else final_ub[i - 1]
        final_lb[i] = lb[i] if (lb[i] > final_lb[i - 1] or c[i - 1] < final_lb[i - 1]) else final_lb[i - 1]
        if trend[i - 1] == 1:
            trend[i] = -1 if c[i] <= final_lb[i] else 1
        else:
            trend[i] = 1 if c[i] >= final_ub[i] else -1
    idx = close.index
    return {
        "upperband": pd.Series(final_ub, index=idx, dtype=float),
        "lowerband": pd.Series(final_lb, index=idx, dtype=float),
        "direction": pd.Series(trend, index=idx, dtype=int),
    }


def ICHIMOKU(v: Any, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52, displacement: int = 26):
    """一目均衡表 (Ichimoku Cloud)。返回 dict:
    {"tenkan_sen", "kijun_sen", "span_a", "span_b", "cloud_top", "cloud_bottom"}
    """
    high, low, close, _ = _ohlcv(v)
    n = len(close)
    if n == 0:
        return {"tenkan_sen": pd.Series(dtype=float), "kijun_sen": pd.Series(dtype=float),
                "span_a": pd.Series(dtype=float), "span_b": pd.Series(dtype=float),
                "cloud_top": pd.Series(dtype=float), "cloud_bottom": pd.Series(dtype=float)}
    t = max(1, int(tenkan))
    k = max(1, int(kijun))
    sb = max(1, int(senkou_b))
    tenkan_sen = (high.rolling(t, min_periods=1).max() + low.rolling(t, min_periods=1).min()) / 2.0
    kijun_sen = (high.rolling(k, min_periods=1).max() + low.rolling(k, min_periods=1).min()) / 2.0
    span_a = (tenkan_sen + kijun_sen) / 2.0
    span_b = (high.rolling(sb, min_periods=1).max() + low.rolling(sb, min_periods=1).min()) / 2.0
    cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    cloud_bottom = pd.concat([span_a, span_b], axis=1).min(axis=1)
    return {
        "tenkan_sen": tenkan_sen,
        "kijun_sen": kijun_sen,
        "span_a": span_a,
        "span_b": span_b,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
    }


def KELTNER(v: Any, ema_period: int = 20, atr_period: int = 10, mult: float = 2.0):
    """Keltner通道。返回 dict: {"upper", "middle", "lower"}
    """
    high, low, close, _ = _ohlcv(v)
    n = len(close)
    if n == 0:
        return {"upper": pd.Series(dtype=float), "middle": pd.Series(dtype=float), "lower": pd.Series(dtype=float)}
    middle = EMA(v, timeperiod=ema_period)
    atr = ATR(v, timeperiod=atr_period)
    upper = middle + float(mult) * atr
    lower = middle - float(mult) * atr
    return {"upper": upper, "middle": middle, "lower": lower}


def DONCHIAN(v: Any, period: int = 20):
    """Donchian通道。返回 dict: {"upper", "middle", "lower"}
    """
    high, low, close, _ = _ohlcv(v)
    n = len(close)
    if n == 0:
        return {"upper": pd.Series(dtype=float), "middle": pd.Series(dtype=float), "lower": pd.Series(dtype=float)}
    p = max(1, int(period))
    upper = high.rolling(p, min_periods=1).max()
    lower = low.rolling(p, min_periods=1).min()
    middle = (upper + lower) / 2.0
    return {"upper": upper, "middle": middle, "lower": lower}


def ROC(v: Any, period: int = 10) -> pd.Series:
    """变化率 Rate of Change。返回百分比变化序列。"""
    s = _as_series(v if not isinstance(v, pd.DataFrame) else v.get("close"))
    p = max(1, int(period))
    return ((s - s.shift(p)) / s.shift(p) * 100).fillna(0.0)


def AROON(v: Any, period: int = 25):
    """Aroon 指标。返回 dict: {"aroondown", "aroonup"}
    aroon_up 接近 100 表示近期创新高（多头强势）
    aroon_down 接近 100 表示近期创新低（空头强势）
    """
    high, low, close, _ = _ohlcv(v)
    n = len(close)
    if n == 0:
        return {"aroondown": pd.Series(dtype=float), "aroonup": pd.Series(dtype=float)}
    p = max(1, int(period))
    aroon_up = high.rolling(p, min_periods=1).apply(lambda x: (x.argmax()) / (len(x) - 1) * 100, raw=False).fillna(0.0)
    aroon_down = low.rolling(p, min_periods=1).apply(lambda x: (x.argmin()) / (len(x) - 1) * 100, raw=False).fillna(0.0)
    return {"aroondown": aroon_down, "aroonup": aroon_up}


def VORTEX(v: Any, period: int = 14):
    """Vortex 指标。返回 dict: {"plus_vi", "minus_vi"}
    +VI > -VI 多头趋势，-VI > +VI 空头趋势
    """
    high, low, close, _ = _ohlcv(v)
    n = len(close)
    if n == 0:
        return {"plus_vi": pd.Series(dtype=float), "minus_vi": pd.Series(dtype=float)}
    p = max(1, int(period))
    tr = TRANGE(v)
    vm_plus = (high - low.shift(1)).abs()
    vm_minus = (low - high.shift(1)).abs()
    tr_sum = tr.rolling(p, min_periods=1).sum()
    vi_plus = (vm_plus.rolling(p, min_periods=1).sum() / tr_sum * 100).fillna(0.0)
    vi_minus = (vm_minus.rolling(p, min_periods=1).sum() / tr_sum * 100).fillna(0.0)
    return {"plus_vi": vi_plus, "minus_vi": vi_minus}


def VWAP(v: Any) -> pd.Series:
    """成交量加权平均价 (Volume Weighted Average Price)"""
    high, low, close, vol = _ohlcv(v)
    if len(close) == 0:
        return pd.Series(dtype=float)
    typical = (high + low + close) / 3.0
    cum_vol = vol.cumsum().replace(0, np.nan)
    cum_pv = (typical * vol).cumsum()
    return (cum_pv / cum_vol).fillna(close)


def ELDER_RAY(v: Any, period: int = 13):
    """
    Elder-ray 指标（埃尔德原创指标）
    用于判断趋势力度的衰竭和逆转
    
    Bull Power = High - EMA(13)
    Bear Power = Low - EMA(13)
    
    返回 dict: {"bull_power", "bear_power", "ema"}
    
    解读：
    - Bull Power > 0 且上升：多头力量增强
    - Bull Power > 0 但下降：多头力量衰竭
    - Bear Power < 0 且下降：空头力量增强
    - Bear Power < 0 但上升：空头力量衰竭
    """
    high, low, close, _ = _ohlcv(v)
    p = max(1, int(period))
    ema = close.ewm(span=p, adjust=False).mean()
    bull_power = high - ema
    bear_power = low - ema
    return {"bull_power": bull_power, "bear_power": bear_power, "ema": ema}
