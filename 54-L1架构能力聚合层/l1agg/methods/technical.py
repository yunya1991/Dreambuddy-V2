# -*- coding: utf-8 -*-
"""I 组技术指标（D-B01–B07 的方法内核）：I 组 34 个方法全量实现。

口径冻结（METHOD_LIBRARY §6）：
  - 全部纯 stdlib、只吃等长序列、不取数、不写库；
  - EMA/MACD 以「前 period 个值的 SMA」为种子（adjust=False 口径）；
  - RSI/ATR 用 Wilder 平滑；布林用总体标准差（ddof=0，与 pandas 一致）；
  - 依赖 high/low 的方法（I12、I20–I23）缺腿时抛 `ValueError`，
    由编排层转成 `insufficient_history`——**禁止**用 close 伪造高低点。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence

from l1agg.persistence._stats import mean

from ._helpers import EPS, ols_slope, r4, r6
from .registry import register

SUPPORT_EPS_PCT = 0.015  # 支撑/压力聚簇容差（同簇价差 ≤1.5%）


def _series(data: Mapping[str, Any], key: str) -> List[float]:
    values = data.get(key)
    if values is None or isinstance(values, str):
        raise ValueError(f"missing '{key}' series")
    out = [float(v) for v in values]
    if not out:
        raise ValueError(f"empty '{key}' series")
    return out


def _ohlc(data: Mapping[str, Any]) -> tuple[List[float], List[float]]:
    return _series(data, "high"), _series(data, "low")


def _sma(values: Sequence[float], period: int) -> float:
    if period < 1 or len(values) < period:
        raise ValueError(f"sma needs n>={period}")
    return mean(list(values[-period:]))


def _ema_series(values: Sequence[float], period: int) -> List[float]:
    """种子 = 前 period 个值 SMA；返回与输入等长的 EMA 序列。"""
    if period < 1 or len(values) < period:
        raise ValueError(f"ema needs n>={period}")
    alpha = 2.0 / (period + 1.0)
    seed = mean(list(values[:period]))
    out = [seed] * period
    for v in values[period:]:
        out.append(out[-1] + alpha * (v - out[-1]))
    return out


def _touch_count(
    highs: Sequence[float], lows: Sequence[float], level: float, eps_pct: float
) -> int:
    lo, hi = level * (1.0 - eps_pct), level * (1.0 + eps_pct)
    return sum(1 for h, low in zip(highs, lows, strict=True) if low <= hi and h >= lo)


def _pivot_levels(
    values: Sequence[float],
    *,
    side: str,
    window: int,
    eps_pct: float,
    k: int = 2,
    highs: Sequence[float],
    lows: Sequence[float],
) -> List[Dict[str, float]]:
    """分形枢轴极值 → 邻近聚簇（同簇价差 ≤ eps_pct），输出价格 + 触碰次数。"""
    if window < 2 * k + 1:
        raise ValueError(f"window needs >={2 * k + 1}")
    seq = list(values[-window:])
    picks: List[float] = []
    for i in range(k, len(seq) - k):
        neighbors = seq[i - k : i + k + 1]
        if side == "high" and seq[i] >= max(neighbors):
            picks.append(seq[i])
        elif side == "low" and seq[i] <= min(neighbors):
            picks.append(seq[i])
    clusters: List[Dict[str, float]] = []
    for price in sorted(picks, reverse=(side == "high")):
        if clusters and abs(price - clusters[-1]["price"]) / clusters[-1]["price"] <= eps_pct:
            c = clusters[-1]
            c["price"] = (c["price"] * c["hits"] + price) / (c["hits"] + 1)
            c["hits"] += 1
        else:
            clusters.append({"price": price, "hits": 1})
    for c in clusters:
        c["touches"] = _touch_count(highs, lows, c["price"], eps_pct)
        c.pop("hits", None)
    return clusters


# ============================================================
# D-B01：MA / EMA
# ============================================================


@register(
    "I01",
    name="SMA 简单移动平均",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=20,
    output_schema=("ma",),
)
def i01_sma(data, periods: Sequence[int] = (5, 10, 20, 60, 120), **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    ma: Dict[str, float] = {}
    for p in periods:
        if len(close) >= p:
            ma[str(p)] = round(_sma(close, p), 6)
    return {"ma": ma}


@register(
    "I02",
    name="EMA 指数移动平均",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=26,
    output_schema=("ema",),
)
def i02_ema(data, periods: Sequence[int] = (12, 26, 50), **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    ema: Dict[str, float] = {}
    for p in periods:
        if len(close) >= p:
            ema[str(p)] = round(_ema_series(close, p)[-1], 6)
    return {"ema": ema}


# ============================================================
# D-B02：RSI（Wilder 14）
# ============================================================


@register(
    "I07",
    name="RSI 相对强弱",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=15,
    output_schema=("rsi", "zone"),
)
def i07_rsi(data, period: int = 14, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    if len(close) < period + 1:
        raise ValueError(f"rsi needs n>={period + 1}")
    diffs = [close[i] - close[i - 1] for i in range(1, len(close))]
    gains = [max(d, 0.0) for d in diffs]
    losses = [max(-d, 0.0) for d in diffs]
    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])
    for g, loss in zip(gains[period:], losses[period:], strict=True):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_gain == 0.0 and avg_loss == 0.0:
        rsi = 50.0
    elif avg_loss == 0.0:
        rsi = 100.0
    elif avg_gain == 0.0:
        rsi = 0.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - 100.0 / (1.0 + rs)
    zone = "超买" if rsi >= 70 else ("超卖" if rsi <= 30 else "中性")
    return {"rsi": round(rsi, 6), "zone": zone}


# ============================================================
# D-B03：MACD（12/26/9）
# ============================================================


@register(
    "I09",
    name="MACD",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=35,
    output_schema=("dif", "dea", "hist", "cross"),
)
def i09_macd(data, fast: int = 12, slow: int = 26, signal: int = 9, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    if len(close) < slow + signal:
        raise ValueError(f"macd needs n>={slow + signal}")
    ema_fast = _ema_series(close, fast)
    ema_slow = _ema_series(close, slow)
    dif_series = [f - s for f, s in zip(ema_fast, ema_slow, strict=True)]
    dea_series = _ema_series(dif_series, signal)
    dif, dea = dif_series[-1], dea_series[-1]
    cross = "none"
    if len(dif_series) >= 2:
        prev_dif, prev_dea = dif_series[-2], dea_series[-2]
        if prev_dif <= prev_dea and dif > dea:
            cross = "golden"
        elif prev_dif >= prev_dea and dif < dea:
            cross = "death"
    return {
        "dif": round(dif, 6),
        "dea": round(dea, 6),
        "hist": round(dif - dea, 6),
        "cross": cross,
    }


# ============================================================
# D-B04：ATR（Wilder 14，需 HLC）
# ============================================================


@register(
    "I12",
    name="ATR 平均真实波幅",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=15,
    output_schema=("atr", "atr_pct"),
)
def i12_atr(data, period: int = 14, **_: Any) -> Dict[str, Any]:
    high, low = _ohlc(data)
    close = _series(data, "close")
    n = min(len(high), len(low), len(close))
    if n < period + 1:
        raise ValueError(f"atr needs n>={period + 1}")
    tr = [high[0] - low[0]]
    for i in range(1, n):
        tr.append(
            max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
        )
    atr = mean(tr[1 : period + 1])
    for value in tr[period + 1 :]:
        atr = (atr * (period - 1) + value) / period
    return {"atr": round(atr, 6), "atr_pct": round(atr / close[n - 1], 6)}


# ============================================================
# D-B05：布林带 / %B
# ============================================================


def _boll(close: Sequence[float], period: int, k: float) -> tuple[float, float, float]:
    if len(close) < period:
        raise ValueError(f"boll needs n>={period}")
    window = list(close[-period:])
    mid = mean(window)
    var = sum((v - mid) ** 2 for v in window) / period
    sd = math.sqrt(var)
    return mid + k * sd, mid, mid - k * sd


@register(
    "I14",
    name="布林带",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=20,
    output_schema=("upper", "mid", "lower"),
)
def i14_boll(data, period: int = 20, k: float = 2.0, **_: Any) -> Dict[str, Any]:
    upper, mid, lower = _boll(_series(data, "close"), period, k)
    return {"upper": round(upper, 6), "mid": round(mid, 6), "lower": round(lower, 6)}


@register(
    "I15",
    name="布林带位置 %B",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=20,
    output_schema=("pctb",),
)
def i15_pctb(data, period: int = 20, k: float = 2.0, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    upper, _, lower = _boll(close, period, k)
    width = upper - lower
    pctb = 0.5 if width == 0 else (close[-1] - lower) / width
    return {"pctb": round(pctb, 6)}


# ============================================================
# D-B06：量能比
# ============================================================


@register(
    "I17",
    name="量能比",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=21,
    output_schema=("vol_ratio", "base_vol"),
)
def i17_vol_ratio(data, period: int = 20, **_: Any) -> Dict[str, Any]:
    volume = _series(data, "volume")
    if len(volume) < period + 1:
        raise ValueError(f"vol_ratio needs n>={period + 1}")
    base = mean(volume[-period - 1 : -1])
    if base == 0:
        raise ValueError("base volume is zero")
    return {"vol_ratio": round(volume[-1] / base, 6), "base_vol": round(base, 6)}


# ============================================================
# D-B07：支撑 / 压力 / 触碰 / 距离
# ============================================================


@register(
    "I20",
    name="支撑位（低点聚类）",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=20,
    output_schema=("levels",),
)
def i20_support(
    data, window: int = 60, eps_pct: float = SUPPORT_EPS_PCT, **_: Any
) -> Dict[str, Any]:
    high, low = _ohlc(data)
    levels = _pivot_levels(
        low[-window:],
        side="low",
        window=min(window, len(low)),
        eps_pct=eps_pct,
        highs=high,
        lows=low,
    )
    return {"levels": [{"price": round(c["price"], 6), "touches": c["touches"]} for c in levels]}


@register(
    "I21",
    name="压力位（高点聚类）",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=20,
    output_schema=("levels",),
)
def i21_resistance(
    data, window: int = 60, eps_pct: float = SUPPORT_EPS_PCT, **_: Any
) -> Dict[str, Any]:
    high, low = _ohlc(data)
    levels = _pivot_levels(
        high[-window:],
        side="high",
        window=min(window, len(high)),
        eps_pct=eps_pct,
        highs=high,
        lows=low,
    )
    return {"levels": [{"price": round(c["price"], 6), "touches": c["touches"]} for c in levels]}


@register(
    "I22",
    name="触碰次数",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("touches",),
)
def i22_touches(data, level: float, eps_pct: float = 0.01, **_: Any) -> Dict[str, Any]:
    high, low = _ohlc(data)
    return {"touches": _touch_count(high, low, float(level), float(eps_pct))}


@register(
    "I23",
    name="距支撑/压力距离",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("support_dist", "resistance_dist"),
)
def i23_level_distance(data, support: float, resistance: float, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")[-1]
    if close == 0:
        raise ValueError("close is zero")
    return {
        "support_dist": round((close - float(support)) / close, 6),
        "resistance_dist": round((float(resistance) - close) / close, 6),
    }


# ============================================================
# 通用滚动算子（I 组第二批共用）
# ============================================================


def _rolling_mean(values: Sequence[float], period: int) -> List[Any]:
    """滚动均值，前 period−1 位为 None；长度与输入一致。"""
    n = len(values)
    if period < 1 or n < period:
        return [None] * n
    out: List[Any] = [None] * (period - 1)
    running = sum(values[:period])
    out.append(running / period)
    for i in range(period, n):
        running += values[i] - values[i - period]
        out.append(running / period)
    return out


def _rolling_max(values: Sequence[float], period: int) -> List[Any]:
    n = len(values)
    if period < 1 or n < period:
        return [None] * n
    return [None] * (period - 1) + [
        max(values[i - period + 1 : i + 1]) for i in range(period - 1, n)
    ]


def _rolling_min(values: Sequence[float], period: int) -> List[Any]:
    n = len(values)
    if period < 1 or n < period:
        return [None] * n
    return [None] * (period - 1) + [
        min(values[i - period + 1 : i + 1]) for i in range(period - 1, n)
    ]


def _wma(values: Sequence[float], period: int) -> float:
    """线性加权移动平均：权重 1..period（最新价权重最大）。"""
    if period < 1 or len(values) < period:
        raise ValueError(f"wma needs n>={period}")
    window = list(values[-period:])
    denom = period * (period + 1) / 2.0
    return sum(w * v for w, v in zip(range(1, period + 1), window, strict=True)) / denom


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _rsi_series(close: Sequence[float], period: int) -> List[Any]:
    """Wilder RSI 序列，前 period 位为 None（与 close 等长）。"""
    if len(close) < period + 1:
        raise ValueError(f"rsi needs n>={period + 1}")
    out: List[Any] = [None] * period
    diffs = [close[i] - close[i - 1] for i in range(1, len(close))]
    gains = [max(d, 0.0) for d in diffs]
    losses = [max(-d, 0.0) for d in diffs]
    avg_gain, avg_loss = mean(gains[:period]), mean(losses[:period])
    out.append(_rsi_value(avg_gain, avg_loss))
    for g, loss in zip(gains[period:], losses[period:], strict=True):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out.append(_rsi_value(avg_gain, avg_loss))
    return out


def _macd_lines(
    close: Sequence[float], fast: int, slow: int, signal: int
) -> tuple[List[float], List[float]]:
    if len(close) < slow + signal:
        raise ValueError(f"macd needs n>={slow + signal}")
    ema_fast = _ema_series(close, fast)
    ema_slow = _ema_series(close, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow, strict=True)]
    return dif, _ema_series(dif, signal)


# ============================================================
# D-B08：均线族扩展（I03 WMA / I04 位置 / I05 排列 / I06 交叉）
# ============================================================


@register(
    "I03",
    name="WMA 线性加权移动平均",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=20,
    output_schema=("wma",),
    notes="权重 1..period 线性递增（最新价权重 period），分母 period(period+1)/2；默认 20 周期",
)
def i03_wma(data, period: int = 20, **_: Any) -> Dict[str, Any]:
    return {"wma": r6(_wma(_series(data, "close"), period))}


@register(
    "I04",
    name="价格相对均线位置",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=20,
    output_schema=("pos",),
    notes="pos[period]=close/MA(period)−1，仅输出样本足够的历史窗口；>0 表示价在均线上方",
)
def i04_ma_position(
    data, periods: Sequence[int] = (5, 10, 20, 60, 120), **_: Any
) -> Dict[str, Any]:
    close = _series(data, "close")
    last = close[-1]
    if last == 0:
        raise ValueError("close is zero")
    pos: Dict[str, float] = {}
    for p in periods:
        if len(close) >= p:
            pos[str(p)] = r6(last / _sma(close, p) - 1.0)
    return {"pos": pos}


@register(
    "I05",
    name="均线排列",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=60,
    output_schema=("ma5", "ma20", "ma60", "stack"),
    notes="固定 5/20/60 三线：ma5>ma20>ma60 为多头排列，反向为空头排列，其余为非单调",
)
def i05_ma_stack(data, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    ma5, ma20, ma60 = (_sma(close, p) for p in (5, 20, 60))
    if ma5 > ma20 > ma60:
        stack = "多头排列"
    elif ma5 < ma20 < ma60:
        stack = "空头排列"
    else:
        stack = "非单调"
    return {"ma5": r6(ma5), "ma20": r6(ma20), "ma60": r6(ma60), "stack": stack}


@register(
    "I06",
    name="金叉/死叉",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("cross", "bars_since", "ma_fast", "ma_slow"),
    notes="快线(默认 5)上穿慢线(默认 20)记 golden、下穿记 death；bars_since 为距最近交叉的 K 线数，无交叉为 null",
)
def i06_ma_cross(data, fast: int = 5, slow: int = 20, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    if fast < 1 or slow < 1 or fast >= slow:
        raise ValueError("need 1 <= fast < slow")
    if len(close) < slow + 1:
        raise ValueError(f"ma cross needs n>={slow + 1}")
    ma_fast = _rolling_mean(close, fast)
    ma_slow = _rolling_mean(close, slow)
    prev_diff = None
    last_cross = "none"
    last_idx = None
    for i, (f, s) in enumerate(zip(ma_fast, ma_slow, strict=True)):
        if f is None or s is None:
            continue
        diff = f - s
        if prev_diff is not None:
            if prev_diff <= 0.0 < diff:
                last_cross, last_idx = "golden", i
            elif prev_diff >= 0.0 > diff:
                last_cross, last_idx = "death", i
        prev_diff = diff
    return {
        "cross": last_cross,
        "bars_since": None if last_idx is None else len(close) - 1 - last_idx,
        "ma_fast": r6(ma_fast[-1]),
        "ma_slow": r6(ma_slow[-1]),
    }


# ============================================================
# D-B09：RSI 背离 / MACD 柱变化（I08、I10）
# ============================================================


@register(
    "I08",
    name="RSI 背离",
    group="I",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=("divergence", "price_delta", "rsi_delta", "window"),
    notes="取最近 window 与前一 window 段比较：价新高但 RSI 峰值走低=bearish；价新低但 RSI 谷值抬高=bullish；delta 为对应峰/谷差",
)
def i08_rsi_divergence(data, period: int = 14, window: int = 20, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    if len(close) < 2 * window + period:
        raise ValueError(f"divergence needs n>={2 * window + period}")
    rsi = _rsi_series(close, period)
    recent_px, prior_px = close[-window:], close[-2 * window : -window]
    recent_rsi = [v for v in rsi[-window:] if v is not None]
    prior_rsi = [v for v in rsi[-2 * window : -window] if v is not None]
    if not recent_rsi or not prior_rsi:
        raise ValueError("insufficient rsi history for divergence")
    if max(recent_px) > max(prior_px) and max(recent_rsi) < max(prior_rsi):
        return {
            "divergence": "bearish",
            "price_delta": r6(max(recent_px) - max(prior_px)),
            "rsi_delta": r6(max(recent_rsi) - max(prior_rsi)),
            "window": window,
        }
    if min(recent_px) < min(prior_px) and min(recent_rsi) > min(prior_rsi):
        return {
            "divergence": "bullish",
            "price_delta": r6(min(recent_px) - min(prior_px)),
            "rsi_delta": r6(min(recent_rsi) - min(prior_rsi)),
            "window": window,
        }
    return {
        "divergence": "none",
        "price_delta": r6(max(recent_px) - max(prior_px)),
        "rsi_delta": r6(max(recent_rsi) - max(prior_rsi)),
        "window": window,
    }


@register(
    "I10",
    name="MACD 柱变化",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=36,
    output_schema=("hist", "prev_hist", "delta", "expanding"),
    notes="hist=dif−dea；delta=hist(t)−hist(t−1)；expanding=True 表示红柱/绿柱幅度扩大（|delta| 上的方向性由 delta 符号给出）",
)
def i10_macd_hist_delta(
    data, fast: int = 12, slow: int = 26, signal: int = 9, **_: Any
) -> Dict[str, Any]:
    close = _series(data, "close")
    dif, dea = _macd_lines(close, fast, slow, signal)
    hist = dif[-1] - dea[-1]
    prev_hist = dif[-2] - dea[-2]
    delta = hist - prev_hist
    return {
        "hist": r6(hist),
        "prev_hist": r6(prev_hist),
        "delta": r6(delta),
        "expanding": abs(hist) > abs(prev_hist),
    }


# ============================================================
# D-B10：KDJ / 真实波幅 / 布林带宽（I11、I13、I16）
# ============================================================


@register(
    "I11",
    name="KDJ",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=20,
    output_schema=("k", "d", "j"),
    notes="RSV=(C−LLV(L,9))/(HHV(H,9)−LLV(L,9))×100；K=2/3·K₋₁+1/3·RSV、D=2/3·D₋₁+1/3·K，种子 50；J=3K−2D；需 HLC",
)
def i11_kdj(
    data, period: int = 9, k_period: int = 3, d_period: int = 3, **_: Any
) -> Dict[str, Any]:
    high, low = _ohlc(data)
    close = _series(data, "close")
    n = min(len(high), len(low), len(close))
    if n < period:
        raise ValueError(f"kdj needs n>={period}")
    a_k, a_d = 1.0 / k_period, 1.0 / d_period
    k_val = d_val = 50.0
    for i in range(period - 1, n):
        hhv = max(high[i - period + 1 : i + 1])
        llv = min(low[i - period + 1 : i + 1])
        rsv = 50.0 if hhv == llv else (close[i] - llv) / (hhv - llv) * 100.0
        k_val = (1.0 - a_k) * k_val + a_k * rsv
        d_val = (1.0 - a_d) * d_val + a_d * k_val
    return {"k": r6(k_val), "d": r6(d_val), "j": r6(3.0 * k_val - 2.0 * d_val)}


@register(
    "I13",
    name="真实波幅 TR",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=15,
    output_schema=("tr", "tr_pct", "max_tr"),
    notes="TR=max(H−L,|H−C₋₁|,|L−C₋₁|) 取当根；tr_pct=TR/close；max_tr 为最近 period 根 TR 最大值；需 HLC",
)
def i13_true_range(data, period: int = 14, **_: Any) -> Dict[str, Any]:
    high, low = _ohlc(data)
    close = _series(data, "close")
    n = min(len(high), len(low), len(close))
    if n < 2:
        raise ValueError("true range needs n>=2")
    trs = [high[0] - low[0]]
    for i in range(1, n):
        trs.append(
            max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
        )
    last = trs[-1]
    if close[n - 1] == 0:
        raise ValueError("close is zero")
    return {
        "tr": r6(last),
        "tr_pct": r6(last / close[n - 1]),
        "max_tr": r6(max(trs[-period:])),
    }


@register(
    "I16",
    name="布林带宽",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=20,
    output_schema=("width", "mid", "upper", "lower"),
    notes="width=(upper−lower)/mid，与 I14 同参数（20, 2σ，总体标准差 ddof=0）",
)
def i16_boll_width(data, period: int = 20, k: float = 2.0, **_: Any) -> Dict[str, Any]:
    upper, mid, lower = _boll(_series(data, "close"), period, k)
    width = 0.0 if mid == 0 else (upper - lower) / mid
    return {
        "width": r6(width),
        "mid": r6(mid),
        "upper": r6(upper),
        "lower": r6(lower),
    }


# ============================================================
# D-B11：量能族（I18 OBV / I19 成交量 z-score / I34 成交额比）
# ============================================================


@register(
    "I18",
    name="OBV 能量潮",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("obv", "obv_change", "n"),
    notes="首根 OBV=0；收涨加当日量、收跌减当日量、持平不变；obv_change=当前 OBV 与 period 根之前的差",
)
def i18_obv(data, period: int = 20, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    volume = _series(data, "volume")
    n = min(len(close), len(volume))
    if n < 2:
        raise ValueError("obv needs n>=2")
    obv = [0.0]
    for i in range(1, n):
        if close[i] > close[i - 1]:
            obv.append(obv[-1] + volume[i])
        elif close[i] < close[i - 1]:
            obv.append(obv[-1] - volume[i])
        else:
            obv.append(obv[-1])
    ref = obv[-min(period + 1, n)]
    return {"obv": r6(obv[-1]), "obv_change": r6(obv[-1] - ref), "n": n}


@register(
    "I19",
    name="成交量 z-score",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=21,
    output_schema=("z", "mean", "std", "volume"),
    notes="z=(v−μ)/σ，μ/σ 取最近 period 根（σ 为样本标准差 ddof=1）；σ≈0 时 z=0",
)
def i19_volume_zscore(data, period: int = 20, **_: Any) -> Dict[str, Any]:
    volume = _series(data, "volume")
    if len(volume) < period:
        raise ValueError(f"volume z-score needs n>={period}")
    seg = volume[-period:]
    mu = mean(seg)
    sd = math.sqrt(sum((v - mu) ** 2 for v in seg) / (period - 1)) if period > 1 else 0.0
    z = 0.0 if sd <= EPS else (volume[-1] - mu) / sd
    return {
        "z": r6(z),
        "mean": r6(mu),
        "std": r6(sd),
        "volume": r6(volume[-1]),
    }


@register(
    "I34",
    name="换手/成交额比",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("ratio", "vwap", "volume"),
    notes="ratio=(Σ成交额/Σ成交量)/close，即均价相对收盘价的偏离；无 turnover 字段时以 close×volume 作成交额代理",
)
def i34_turnover_ratio(data, period: int = 20, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    volume = _series(data, "volume")
    turnover = data.get("turnover") if isinstance(data, Mapping) else None
    if turnover is not None:
        amount = [float(v) for v in turnover]
    else:
        amount = [c * v for c, v in zip(close, volume, strict=False)]
    n = min(len(close), len(volume), len(amount))
    if n < period:
        raise ValueError(f"turnover ratio needs n>={period}")
    vol_sum = sum(volume[-period:])
    if vol_sum == 0:
        raise ValueError("volume sum is zero")
    if close[n - 1] == 0:
        raise ValueError("close is zero")
    vwap = sum(amount[-period:]) / vol_sum
    return {
        "ratio": r6(vwap / close[n - 1]),
        "vwap": r6(vwap),
        "volume": r6(vol_sum),
    }


# ============================================================
# D-B12：突破 / 极值 / 回撤 / 通道 / 动量（I24–I29）
# ============================================================


@register(
    "I24",
    name="突破事件",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=60,
    output_schema=("breakout", "close", "prior_high_20", "prior_high_60"),
    notes="突破=close 高于前高（前高不含当日）：先判 20 日、再判 60 日，均未破为 none",
)
def i24_breakout(data, short: int = 20, long: int = 60, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    if len(close) < short + 1:
        raise ValueError(f"breakout needs n>={short + 1}")
    prior_short = max(close[-short - 1 : -1])
    prior_long = max(close[-long - 1 : -1])
    last = close[-1]
    flag = "20" if last > prior_short else ("60" if last > prior_long else "none")
    return {
        "breakout": flag,
        "close": r6(last),
        "prior_high_20": r6(prior_short),
        "prior_high_60": r6(prior_long),
    }


@register(
    "I25",
    name="新高/新低天数",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=60,
    output_schema=("new_high_days", "new_low_days", "window"),
    notes="在最近 window 根内统计收盘价等于其 trailing window 最高/最低的根数（rolling max/min 口径）",
)
def i25_extreme_days(data, window: int = 20, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    if len(close) < 2 * window:
        raise ValueError(f"extreme days needs n>={2 * window}")
    rmax = _rolling_max(close, window)
    rmin = _rolling_min(close, window)
    highs = lows = 0
    for i in range(len(close) - window, len(close)):
        if rmax[i] is not None and close[i] >= rmax[i]:
            highs += 1
        if rmin[i] is not None and close[i] <= rmin[i]:
            lows += 1
    return {"new_high_days": highs, "new_low_days": lows, "window": window}


@register(
    "I26",
    name="距 ATH 回撤",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("dd", "ath", "close"),
    notes="dd=close/max(全样本收盘)−1（≤0）；ath 为样本内历史最高收盘",
)
def i26_from_ath(data, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    ath = max(close)
    if ath == 0:
        raise ValueError("ath is zero")
    return {"dd": r6(close[-1] / ath - 1.0), "ath": r6(ath), "close": r6(close[-1])}


@register(
    "I27",
    name="唐奇安通道",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=20,
    output_schema=("upper", "mid", "lower", "width_pct"),
    notes="upper=max(H,period)、lower=min(L,period)、mid 为中轨、width_pct=(upper−lower)/mid；需 high/low",
)
def i27_donchian(data, period: int = 20, **_: Any) -> Dict[str, Any]:
    high, low = _ohlc(data)
    n = min(len(high), len(low))
    if n < period:
        raise ValueError(f"donchian needs n>={period}")
    upper, lower = max(high[-period:]), min(low[-period:])
    mid = (upper + lower) / 2.0
    width_pct = 0.0 if mid == 0 else (upper - lower) / mid
    return {
        "upper": r6(upper),
        "mid": r6(mid),
        "lower": r6(lower),
        "width_pct": r6(width_pct),
    }


@register(
    "I28",
    name="价格动量",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("mom", "mom_pct"),
    notes="绝对动量 mom[k]=C−C₋ₖ（方法库公式与 I29 ROC 同为比值口径，此处取价差口径以区分）；mom_pct[k]=C/C₋ₖ−1",
)
def i28_momentum(data, ks: Sequence[int] = (1, 5, 20), **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    mom: Dict[str, float] = {}
    mom_pct: Dict[str, float] = {}
    for k in ks:
        if k < 1 or len(close) <= k:
            continue
        base = close[-1 - k]
        mom[str(k)] = r6(close[-1] - base)
        mom_pct[str(k)] = None if base == 0 else r6(close[-1] / base - 1.0)
    if not mom:
        raise ValueError("momentum needs n>max(k)")
    return {"mom": mom, "mom_pct": mom_pct}


@register(
    "I29",
    name="变化率 ROC",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("roc",),
    notes="roc[k]=C/C₋ₖ−1，默认 k∈{1,5,20}，仅输出样本足够的 k",
)
def i29_roc(data, ks: Sequence[int] = (1, 5, 20), **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    roc: Dict[str, float] = {}
    for k in ks:
        if k < 1 or len(close) <= k:
            continue
        base = close[-1 - k]
        if base == 0:
            raise ValueError("base close is zero")
        roc[str(k)] = r6(close[-1] / base - 1.0)
    if not roc:
        raise ValueError("roc needs n>max(k)")
    return {"roc": roc}


# ============================================================
# D-B13：波动率分位 / 回归通道（I30、I31）
# ============================================================


def rolling_volatility(close: Sequence[float], window: int = 20) -> List[float]:
    """I30 的滚动波动率序列；首个值对齐 close[window]。"""
    if window < 2:
        raise ValueError("vol window must be >= 2")
    values = [float(v) for v in close]
    rets: List[float] = []
    for i in range(1, len(values)):
        if values[i - 1] == 0:
            raise ValueError("close is zero at previous bar")
        rets.append(values[i] / values[i - 1] - 1.0)
    vols: List[float] = []
    for i in range(window - 1, len(rets)):
        seg = rets[i - window + 1 : i + 1]
        mu = mean(seg)
        vols.append(math.sqrt(sum((x - mu) ** 2 for x in seg) / (window - 1)))
    return vols


@register(
    "I30",
    name="波动率分位",
    group="I",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=("percentile", "current_vol", "window", "lookback"),
    notes="滚动 window 根日收益率样本标准差(ddof=1)序列，当前值在最近 lookback 个历史值中的百分位（0–100，含自身）",
)
def i30_vol_percentile(data, window: int = 20, lookback: int = 60, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    if len(close) < window + 2:
        raise ValueError(f"vol percentile needs n>={window + 2}")
    vols = rolling_volatility(close, window)
    hist = vols[-lookback:]
    current = vols[-1] if vols else None
    if current is None or not hist:
        raise ValueError("insufficient return history for vol percentile")
    pct = 100.0 * sum(1 for v in hist if v <= current) / len(hist)
    return {
        "percentile": r4(pct),
        "current_vol": r6(current),
        "window": window,
        "lookback": lookback,
    }


@register(
    "I31",
    name="回归通道",
    group="I",
    layer="D3",
    input_kind="series",
    min_n=60,
    output_schema=("slope", "intercept", "mid", "upper", "lower", "r2"),
    notes="最近 window 根收盘价对时间 OLS（t=0..window−1），通道=拟合值±k·残差标准差(ddof=2)，k 默认 2；mid 为末端拟合值",
)
def i31_regression_channel(data, window: int = 60, k: float = 2.0, **_: Any) -> Dict[str, Any]:
    close = _series(data, "close")
    if len(close) < window or window < 3:
        raise ValueError(f"regression channel needs n>={window}")
    y = list(close[-window:])
    xs = [float(i) for i in range(window)]
    fit = ols_slope(y)
    slope = fit["slope"]
    if slope is None:
        raise ValueError("degenerate series: zero variance")
    intercept = mean(y) - slope * mean(xs)
    resid = [y[i] - (intercept + slope * xs[i]) for i in range(window)]
    sigma = math.sqrt(sum(e * e for e in resid) / (window - 2))
    mid = intercept + slope * xs[-1]
    return {
        "slope": r6(slope),
        "intercept": r6(intercept),
        "mid": r6(mid),
        "upper": r6(mid + k * sigma),
        "lower": r6(mid - k * sigma),
        "r2": r6(fit["r2"]),
    }


# ============================================================
# D-B14：ADX 趋势强度 / MFI 资金流（I32、I33）
# ============================================================


@register(
    "I32",
    name="趋势强度 ADX",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("adx", "plus_di", "minus_di", "atr_smoothed"),
    notes="Wilder 平滑：±DM 与 TR 首值为前 period 根求和，之后 S=S−S/period+x；DX=100|+DI−−DI|/(+DI+−DI)，ADX 为 DX 的 Wilder 均值；需 HLC",
)
def i32_adx(data, period: int = 14, **_: Any) -> Dict[str, Any]:
    high, low = _ohlc(data)
    close = _series(data, "close")
    n = min(len(high), len(low), len(close))
    if n < 2 * period + 1:
        raise ValueError(f"adx needs n>={2 * period + 1}")
    tr: List[float] = []
    plus_dm: List[float] = []
    minus_dm: List[float] = []
    for i in range(1, n):
        up, down = high[i] - high[i - 1], low[i - 1] - low[i]
        plus_dm.append(up if (up > down and up > 0.0) else 0.0)
        minus_dm.append(down if (down > up and down > 0.0) else 0.0)
        tr.append(
            max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
        )
    atr_s = sum(tr[:period])
    p_s = sum(plus_dm[:period])
    m_s = sum(minus_dm[:period])
    dxs: List[float] = []
    pdi = mdi = 0.0
    for i in range(period - 1, len(tr)):
        if i >= period:
            atr_s = atr_s - atr_s / period + tr[i]
            p_s = p_s - p_s / period + plus_dm[i]
            m_s = m_s - m_s / period + minus_dm[i]
        pdi = 100.0 * p_s / atr_s if atr_s > EPS else 0.0
        mdi = 100.0 * m_s / atr_s if atr_s > EPS else 0.0
        denom = pdi + mdi
        dxs.append(100.0 * abs(pdi - mdi) / denom if denom > EPS else 0.0)
    adx = mean(dxs[:period])
    for dx in dxs[period:]:
        adx = (adx * (period - 1) + dx) / period
    return {
        "adx": r6(adx),
        "plus_di": r6(pdi),
        "minus_di": r6(mdi),
        "atr_smoothed": r6(atr_s),
    }


@register(
    "I33",
    name="资金流 MFI",
    group="I",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("mfi", "positive_flow", "negative_flow"),
    notes="典型价 TP=(H+L+C)/3，资金流=TP×V；最近 period 根按 TP 涨跌归入正/负流；MFI=100−100/(1+正/负)，负流为 0 时记 100；需 HLCV",
)
def i33_mfi(data, period: int = 14, **_: Any) -> Dict[str, Any]:
    high, low = _ohlc(data)
    close = _series(data, "close")
    volume = _series(data, "volume")
    n = min(len(high), len(low), len(close), len(volume))
    if n < period + 1:
        raise ValueError(f"mfi needs n>={period + 1}")
    tp = [(high[i] + low[i] + close[i]) / 3.0 for i in range(n)]
    pos = neg = 0.0
    for i in range(n - period, n):
        flow = tp[i] * volume[i]
        if tp[i] > tp[i - 1]:
            pos += flow
        elif tp[i] < tp[i - 1]:
            neg += flow
    if neg <= EPS:
        mfi = 100.0
    elif pos <= EPS:
        mfi = 0.0
    else:
        mfi = 100.0 - 100.0 / (1.0 + pos / neg)
    return {"mfi": r6(mfi), "positive_flow": r6(pos), "negative_flow": r6(neg)}
