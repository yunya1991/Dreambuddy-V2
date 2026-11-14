# -*- coding: utf-8 -*-
"""纯 stdlib 基础统计原语（不含业务口径）。

与 `l1agg.align` 同一纪律：无第三方依赖、无随机数、无全局状态。
"""

from __future__ import annotations

import math

from .constants import EPS, P_FLOOR, PersistenceError


def mean(xs):
    return sum(xs) / len(xs)


def var(xs):
    n = len(xs)
    if n < 2:
        raise PersistenceError("variance needs n>=2")
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        raise PersistenceError("pearson needs n>=3")
    mx, my = mean(xs), mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= EPS or syy <= EPS:
        raise PersistenceError("constant series")
    return sxy / math.sqrt(sxx * syy)


def rank(xs):
    """平均秩（处理并列），与 scipy.stats.rankdata 口径一致。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    return pearson(rank(xs), rank(ys))


def ols_slope(xs, ys):
    """返回 (slope, intercept, se_slope, t, r2)。"""
    n = len(xs)
    if n < 3:
        raise PersistenceError("ols needs n>=3")
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= EPS:
        raise PersistenceError("degenerate x")
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    slope = sxy / sxx
    intercept = my - slope * mx
    resid = [y - (intercept + slope * x) for x, y in zip(xs, ys, strict=False)]
    sse = sum(e * e for e in resid)
    sst = sum((y - my) ** 2 for y in ys)
    r2 = 0.0 if sst <= EPS else 1.0 - sse / sst
    if n <= 2:
        return slope, intercept, float("nan"), float("nan"), r2
    s2 = sse / (n - 2)
    se = math.sqrt(s2 / sxx) if sxx > EPS else float("nan")
    t = slope / se if se and se > 0 else float("nan")
    return slope, intercept, se, t, r2


def two_sided_p(z):
    """正态近似双侧 p（n>=30 时足够；纯 stdlib 无 t 分布 CDF）。

    下溢时截断到 P_FLOOR，避免输出 0 被读成"确定性"。
    """
    if z is None or math.isnan(z):
        return None
    p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))
    if p <= 0.0:
        return P_FLOOR
    return max(p, P_FLOOR)


def clean(values):
    out = [float(v) for v in values if v is not None]
    if len(out) < 3:
        raise PersistenceError(f"need n>=3, got {len(out)}")
    return out
