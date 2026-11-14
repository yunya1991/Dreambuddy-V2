# -*- coding: utf-8 -*-
"""统计原语补强（纯 stdlib）：t 分布 p 值、Kendall τ、BH-FDR。

为什么需要：`persistence/_stats.two_sided_p` 只有正态近似，n∈[60,120) 时
p 值偏乐观；相关性批门禁要求「p 值 + 多重比较修正」，故在此补精确 t 尾概率。

纪律：无第三方依赖、无随机数、无全局状态；与 scipy 口径交叉验证见 tests。
"""

from __future__ import annotations

import math
from typing import List, Sequence

EPS = 1e-12


def _betacf(a: float, b: float, x: float, max_iter: int = 200) -> float:
    """正则化不完全 Beta 的连分式（Lentz 法，Numerical Recipes §6.4）。"""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < EPS:
        d = EPS
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < EPS:
            d = EPS
        c = 1.0 + aa / c
        if abs(c) < EPS:
            c = EPS
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < EPS:
            d = EPS
        c = 1.0 + aa / c
        if abs(c) < EPS:
            c = EPS
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3.0e-12:
            break
    return h


def betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数 I_x(a,b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    """t 分布右尾概率 P(T > t)。"""
    if df <= 0:
        raise ValueError("df must be > 0")
    if t == 0:
        return 0.5
    x = df / (df + t * t)
    tail = 0.5 * betai(df / 2.0, 0.5, x)
    return tail if t > 0 else 1.0 - tail


def t_two_sided_p(t: float, df: float) -> float:
    """t 分布双侧 p 值（n<120 时优于正态近似）。"""
    if t is None or math.isnan(t):
        return None
    return min(1.0, max(0.0, 2.0 * t_sf(abs(t), df)))


def corr_p(r: float, n: int, *, exact_t: bool = True) -> float:
    """相关系数显著性 p（H0: ρ=0）；df=n−2，exact_t=False 时退化为正态近似。"""
    if n is None or n < 3:
        return None
    if abs(r) >= 1.0:
        return 0.0
    if not exact_t:
        z = r * math.sqrt(n - 1)
        return min(1.0, math.erfc(abs(z) / math.sqrt(2.0)))
    t = r * math.sqrt((n - 2) / max(EPS, 1.0 - r * r))
    return t_two_sided_p(t, n - 2)


def kendall_tau_b(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Kendall τ-b（处理并列）。"""
    n = len(xs)
    if n < 3 or n != len(ys):
        raise ValueError("kendall needs equal-length n>=3")
    concordant = discordant = ties_x = ties_y = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            dx = xs[i] - xs[j]
            dy = ys[i] - ys[j]
            if dx == 0 and dy == 0:
                ties_x += 1
                ties_y += 1
            elif dx == 0:
                ties_x += 1
            elif dy == 0:
                ties_y += 1
            elif dx * dy > 0:
                concordant += 1
            else:
                discordant += 1
    n0 = n * (n - 1) / 2.0
    denom = math.sqrt((n0 - ties_x) * (n0 - ties_y))
    return 0.0 if denom <= EPS else (concordant - discordant) / denom


def kendall_p(tau: float, n: int) -> float:
    """Kendall τ 的显著性（正态近似，n>=10 足够）。"""
    if n < 3:
        return None
    var = 2.0 * (2 * n + 5) / (9.0 * n * (n - 1))
    z = tau / math.sqrt(var) if var > 0 else 0.0
    return min(1.0, math.erfc(abs(z) / math.sqrt(2.0)))


def bh_fdr(pvals: Sequence[float], alpha: float = 0.05) -> dict:
    """Benjamini–Hochberg FDR 修正。

    Returns:
        {"q": [...], "reject": [...], "alpha": alpha, "m": len(pvals)}
        `q` 与输入同序；`reject[i]` 表示第 i 个假设在 FDR=alpha 下显著。
    """
    m = len(pvals)
    if m == 0:
        return {"q": [], "reject": [], "alpha": alpha, "m": 0}
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    # 从大到小回溯，保证 q 单调
    for rank in range(m, 0, -1):
        idx = order[rank - 1]
        val = min(prev, pvals[idx] * m / rank)
        q[idx] = min(1.0, val)
        prev = q[idx]
    reject = [q[i] <= alpha for i in range(m)]
    return {"q": q, "reject": reject, "alpha": alpha, "m": m}


def rolling(values: Sequence[float], window: int) -> List[List[float]]:
    """等长滚动窗口（不足 window 的尾部丢弃）。"""
    if window < 2:
        raise ValueError("window must be >= 2")
    return [list(values[i : i + window]) for i in range(0, len(values) - window + 1)]
