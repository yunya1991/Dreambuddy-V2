# -*- coding: utf-8 -*-
"""方法层共享工具：输入契约、描述统计、分布函数、回撤/自相关。

只依赖 stdlib（math/bisect），供 `descriptive.py` / `timeseries.py` / `inference.py` 复用；
禁止在此做取数或写库。
"""

from __future__ import annotations

import bisect
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

EPS = 1e-12


# ---------------- 输入契约 ----------------

_SERIES_KEYS = ("series", "values", "price", "prices", "returns", "x", "indicator")


def floats(seq: Sequence[Any]) -> List[float]:
    return [float(v) for v in seq]


def clean(seq: Sequence[Any]) -> List[float]:
    return [float(v) for v in seq if v is not None]


def series(data: Any, *keys: str) -> List[float]:
    """单序列：list 或 mapping（默认按 _SERIES_KEYS 顺序取）。"""
    if isinstance(data, Mapping):
        for key in keys or _SERIES_KEYS:
            if key in data:
                return clean(data[key])
        raise ValueError(f"series data must contain one of {keys or _SERIES_KEYS}")
    return clean(data)


def two(data: Mapping[str, Any]) -> Tuple[List[float], List[float]]:
    """等长双序列：x/y 或 factor/target 或 actual/expected。"""
    for a, b in (("x", "y"), ("factor", "target"), ("actual", "expected")):
        if a in data and b in data:
            xs, ys = clean(data[a]), clean(data[b])
            n = min(len(xs), len(ys))
            if n < 3:
                raise ValueError("need at least 3 paired points")
            return xs[:n], ys[:n]
    raise ValueError("paired data must contain x/y, factor/target or actual/expected")


def group_pair(data: Mapping[str, Any]) -> Tuple[List[str], List[float]]:
    """分组双序列：state/group × target/value。"""
    if "state" in data and "target" in data:
        g, y = data["state"], data["target"]
    elif "group" in data and "value" in data:
        g, y = data["group"], data["value"]
    else:
        raise ValueError("grouped data must contain state/target or group/value")
    yv = floats(y)[: len(g)]
    return [str(v) for v in g[: len(yv)]], yv


# ---------------- 描述统计 ----------------


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def var(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mu = mean(xs)
    return sum((x - mu) ** 2 for x in xs) / (n - 1)


def std(xs: Sequence[float]) -> float:
    return math.sqrt(var(xs))


def median(sorted_or_not: Sequence[float]) -> float:
    return quantile(sorted(sorted_or_not), 0.5)


def quantile(sorted_vals: Sequence[float], q: float) -> float:
    """线性插值分位（numpy.percentile(method="linear") 同口径）。"""
    n = len(sorted_vals)
    if n == 0:
        raise ValueError("empty series")
    if q <= 0:
        return sorted_vals[0]
    if q >= 1:
        return sorted_vals[-1]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def skewness(xs: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mu, s = mean(xs), std(xs)
    if s <= EPS:
        return None
    return sum((x - mu) ** 3 for x in xs) / n / (s**3)


def kurtosis_excess(xs: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 4:
        return None
    mu, s = mean(xs), std(xs)
    if s <= EPS:
        return None
    return sum((x - mu) ** 4 for x in xs) / n / (s**4) - 3.0


def r6(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(float(x), 6)


def r4(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(float(x), 4)


# ---------------- 线性/自相关 ----------------


def ols_slope(ys: Sequence[float]) -> Dict[str, Optional[float]]:
    """y ~ t（t=0..n−1）OLS：slope/se/t/r2。"""
    n = len(ys)
    if n < 3:
        return {"slope": None, "se": None, "t": None, "r2": None}
    xs = [float(i) for i in range(n)]
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    slope = sxy / sxx if sxx > EPS else None
    intercept = my - slope * mx if slope is not None else None
    resid = (
        [y - (intercept + slope * x) for x, y in zip(xs, ys, strict=False)]
        if slope is not None
        else []
    )
    sse = sum(e * e for e in resid)
    sst = sum((y - my) ** 2 for y in ys)
    dof = n - 2
    se = math.sqrt(sse / dof / sxx) if (dof > 0 and sxx > EPS) else None
    t = slope / se if (slope is not None and se and se > EPS) else None
    r2 = 1.0 - sse / sst if sst > EPS else 0.0
    return {"slope": slope, "se": se, "t": t, "r2": r2}


def acf(xs: Sequence[float], max_lag: int) -> List[Optional[float]]:
    """自相关 ACF(k)=corr(x_t, x_{t−k})，k=1..max_lag。"""
    n = len(xs)
    mu = mean(xs)
    denom = sum((x - mu) ** 2 for x in xs)
    out: List[Optional[float]] = []
    for k in range(1, max_lag + 1):
        if n - k < 3 or denom <= EPS:
            out.append(None)
            continue
        num = sum((xs[i] - mu) * (xs[i - k] - mu) for i in range(k, n))
        out.append(num / denom)
    return out


# ---------------- 分布函数（无 scipy 依赖） ----------------


def norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """标准正态分位（Acklam 有理近似，|误差|<1.2e-9）。"""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def _betacf(a: float, b: float, x: float) -> float:
    """不完全 beta 连分式（Numerical Recipes）。"""
    maxit, eps, fpmin = 200, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """正则化不完全 beta I_x(a,b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _gser(a: float, x: float) -> float:
    """下不完全 gamma P(a,x) 级数。"""
    if x <= 0.0:
        return 0.0
    gln = math.lgamma(a)
    ap, s, delta = a, 1.0 / a, 1.0 / a
    for _ in range(1000):
        ap += 1.0
        delta *= x / ap
        s += delta
        if abs(delta) < abs(s) * 3e-12:
            break
    return s * math.exp(-x + a * math.log(x) - gln)


def _gcf(a: float, x: float) -> float:
    """上不完全 gamma Q(a,x) 连分式。"""
    fpmin, eps = 1e-300, 3e-12
    gln = math.lgamma(a)
    b = x + 1.0 - a
    c = 1.0 / fpmin
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < fpmin:
            d = fpmin
        c = b + an / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def gammaq(a: float, x: float) -> float:
    """正则化上不完全 gamma Q(a,x)。"""
    if x < 0 or a <= 0:
        return float("nan")
    if x == 0:
        return 1.0
    return 1.0 - _gser(a, x) if x < a + 1.0 else _gcf(a, x)


def chi2_sf(x: float, df: int) -> float:
    return gammaq(df / 2.0, x / 2.0)


def f_sf(f: float, df1: int, df2: int) -> float:
    if f <= 0:
        return 1.0
    return betainc(df2 / 2.0, df1 / 2.0, df2 / (df2 + df1 * f))


# ---------------- 回撤 ----------------


def drawdown_profile(prices: Sequence[float]) -> Dict[str, Any]:
    """最大回撤 / 峰谷索引 / 回撤持续与恢复天数（D20/D21/F09/F10/R11 共用）。"""
    n = len(prices)
    peak = prices[0]
    mdd = 0.0
    mdd_peak = mdd_trough = 0
    cur_peak_i = 0
    for i, p in enumerate(prices):
        if p > peak:
            peak, cur_peak_i = p, i
        dd = 1.0 - p / peak if peak else 0.0
        if dd > mdd:
            mdd, mdd_peak, mdd_trough = dd, cur_peak_i, i
    recovery = None
    for j in range(mdd_trough, n):
        if prices[j] >= prices[mdd_peak]:
            recovery = j - mdd_trough
            break
    return {
        "mdd": r6(mdd),
        "peak_index": mdd_peak,
        "trough_index": mdd_trough,
        "duration_days": mdd_trough - mdd_peak,
        "recovery_days": recovery,
        "recovered": recovery is not None,
        "n": n,
    }


# ---------------- 分组 ----------------


def bucket(values: Sequence[float], k: int) -> Tuple[List[float], List[int]]:
    """等频分桶（线性插值分位）：返回 (edges, 每条样本的桶号)。"""
    sorted_vals = sorted(values)
    edges = [quantile(sorted_vals, i / k) for i in range(k + 1)]
    inner = edges[1:-1]
    ids = [min(bisect.bisect_right(inner, v), k - 1) for v in values]
    return edges, ids


def quantile_bins(values: Sequence[float], k: int, qs: Sequence[float]) -> Dict[str, List[float]]:
    """分桶后再取各桶内分位（B10 用）。"""
    _, ids = bucket(values, k)
    out: Dict[str, List[float]] = {}
    for b in range(k):
        sub = sorted(v for v, i in zip(values, ids, strict=False) if i == b)
        out[str(b)] = [r6(quantile(sub, q / 100.0)) if sub else None for q in qs]
    return out
