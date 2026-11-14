# -*- coding: utf-8 -*-
"""A1–A7 延续性统计指标。

方法映射（METHOD_LIBRARY）：
  A1 Hurst R/S      → T13
  A2 方差比 VR      → T14
  A3 AR(1)/半衰期    → T20/T21
  A4 连胜/连败       → F18
  A5 状态转移矩阵    → B07/B08/T24
  A6 趋势斜率 t      → T08/T09
  A7 IC 衰减        → B13/B14/B15
"""

from __future__ import annotations

import math

from ._stats import clean, mean, ols_slope, pearson, spearman, two_sided_p, var
from .constants import EPS, HURST_CONFIDENT_N, HURST_MAX_CHUNK, PersistenceError


def hurst_rs(
    values, *, min_chunk: int = 8, max_chunk: int = HURST_MAX_CHUNK, corrected: bool = True
) -> dict:
    """A1 Hurst 指数（R/S，简化 Anis-Lloyd 修正：仅 (k-0.5)/k，不含 k>340 长段修正）。

    H>0.5 持续、H≈0.5 随机、H<0.5 反持续。
    输入应为**收益序列**（价格上直接算会得到 H≈1.5，无意义）。
    `max_chunk` 固定块上限，保证不同样本长度的 H 跨期可比（B3）。
    """
    x = clean(values)
    n = len(x)
    if n < 64:
        raise PersistenceError(f"hurst needs n>=64, got {n}")

    chunks, k = [], max(min_chunk, 4)
    upper = min(n // 2, max_chunk)
    while k <= upper:
        chunks.append(k)
        k *= 2
    if len(chunks) < 2:
        raise PersistenceError("hurst needs >=2 chunk sizes")

    xs, ys = [], []
    for k in chunks:
        m = n // k
        ratios = []
        for i in range(m):
            seg = x[i * k : (i + 1) * k]
            seg_mean = mean(seg)
            cum, dev = [], 0.0
            for v in seg:
                dev += v - seg_mean
                cum.append(dev)
            r = max(cum) - min(cum)
            s = math.sqrt(var(seg))
            if s > EPS:
                ratios.append(r / s)
        if not ratios:
            continue
        rs = mean(ratios)
        if corrected and k > 2:
            rs *= (k - 0.5) / k
        xs.append(math.log(k))
        ys.append(math.log(rs))

    if len(xs) < 2:
        raise PersistenceError("hurst: not enough usable chunks")
    h, _, _, _, r2 = ols_slope(xs, ys)
    return {
        "h": round(h, 4),
        "chunks": chunks,
        "max_chunk": max_chunk,
        "loglog_r2": round(r2, 4),
        "corrected": corrected,
        "n": n,
        "confidence": "high" if n >= HURST_CONFIDENT_N else "low",
        # confidence=low 时 regime 仅供内部调试，文本层禁止展示（评审 §6 反对 2）
        "regime": "persistent" if h > 0.55 else ("anti_persistent" if h < 0.45 else "random_walk"),
        "regime_displayable": n >= HURST_CONFIDENT_N,
    }


def variance_ratio(returns, q: int) -> dict:
    """A2 方差比 VR(q)（Lo-MacKinlay，同方差 z 统计量）。

    VR>1 趋势、VR<1 均值回复、VR≈1 随机游走。
    """
    x = clean(returns)
    n = len(x)
    if q < 2:
        raise PersistenceError(f"q must be >=2, got {q}")
    if n < max(30, 3 * q):
        raise PersistenceError(f"variance_ratio needs n>={max(30, 3 * q)}, got {n}")

    mu = mean(x)
    var1 = var(x)
    if var1 <= EPS:
        raise PersistenceError("constant returns")
    agg = [sum(x[i : i + q]) for i in range(n - q + 1)]
    varq = sum((a - q * mu) ** 2 for a in agg) / (len(agg) * q)
    vr = varq / var1
    z = (vr - 1.0) / math.sqrt(2.0 * (2 * q - 1) * (q - 1) / (3.0 * q * n))
    return {
        "q": q,
        "vr": round(vr, 4),
        "z": round(z, 3),
        "p": two_sided_p(z),  # 不 round，避免 1e-12 被抹成 0.0
        "n": n,
        "interpretation": "trend" if vr > 1.0 else ("mean_revert" if vr < 1.0 else "random_walk"),
    }


def ar1_halflife(returns) -> dict:
    """A3 AR(1) 系数与均值回复半衰期（T20/T21）。"""
    x = clean(returns)
    if len(x) < 30:
        raise PersistenceError(f"ar1 needs n>=30, got {len(x)}")
    phi = pearson(x[:-1], x[1:])
    halflife = None
    if 0.0 < abs(phi) < 1.0:
        halflife = math.log(0.5) / math.log(abs(phi))
    return {
        "phi": round(phi, 4),
        "halflife_days": None if halflife is None else round(halflife, 2),
        "n": len(x) - 1,
    }


def run_length_stats(returns) -> dict:
    """A4 连胜/连败分布（F18）。"""
    x = clean(returns)
    signs = [1 if v > 0 else (-1 if v < 0 else 0) for v in x]
    seq = [s for s in signs if s != 0]
    n_zero = len(signs) - len(seq)
    if len(seq) < 10:
        raise PersistenceError(f"run_length needs n>=10, got {len(seq)}")

    runs, cur, sign = [], 1, seq[0]
    for s in seq[1:]:
        if s == sign:
            cur += 1
        else:
            runs.append((sign, cur))
            sign, cur = s, 1
    runs.append((sign, cur))

    up = [n for s, n in runs if s > 0]
    down = [n for s, n in runs if s < 0]
    return {
        "n_runs": len(runs),
        "max_run": max(n for _, n in runs),
        "mean_run": round(mean([n for _, n in runs]), 3),
        "max_up": max(up) if up else 0,
        "max_down": max(down) if down else 0,
        "n": len(seq),
        "n_zero": n_zero,
    }


def transition_matrix(returns) -> dict:
    """A5 涨跌状态转移矩阵 + 稳态 + 期望停留期（B07/B08/T24）。

    零收益在两个状态口径中一律跳过（与 A4 对齐，评审 I1）：只统计涨/跌明确的方向。
    """
    x = clean(returns)
    if len(x) < 30:
        raise PersistenceError(f"transition needs n>=30, got {len(x)}")
    state = [1 if v > 0 else 0 for v in x if v != 0.0]
    n_zero = len(x) - len(state)
    if len(state) < 30:
        raise PersistenceError(f"transition needs >=30 non-zero returns, got {len(state)}")
    tm = [[0, 0], [0, 0]]
    for a, b in zip(state[:-1], state[1:], strict=False):
        tm[a][b] += 1

    def prob(row, col):
        total = tm[row][0] + tm[row][1]
        return None if total == 0 else tm[row][col] / total

    p_uu, p_ud = prob(1, 1), prob(1, 0)
    p_du, p_dd = prob(0, 1), prob(0, 0)
    steady_up = None
    if None not in (p_ud, p_du) and (p_ud + p_du) > 0:
        steady_up = p_du / (p_ud + p_du)
    return {
        "p_up_up": None if p_uu is None else round(p_uu, 4),
        "p_up_down": None if p_ud is None else round(p_ud, 4),
        "p_down_up": None if p_du is None else round(p_du, 4),
        "p_down_down": None if p_dd is None else round(p_dd, 4),
        "steady_up": None if steady_up is None else round(steady_up, 4),
        "dwell_up_days": None if not p_ud else round(1.0 / p_ud, 2),
        "dwell_down_days": None if not p_du else round(1.0 / p_du, 2),
        "n": len(state) - 1,
        "n_zero": n_zero,
    }


def trend_slope(prices) -> dict:
    """A6 对数价格趋势斜率 + t 值 + R²（T08/T09）。

    ⚠️ t 值未做 Newey-West/HAC 修正（评审 B1）：对数价格 OLS 残差强自相关，
    名义 t 会被显著放大。**仅用于同一资产跨期相对比较，不得作为显著性结论**。
    """
    p = clean(prices)
    if any(v <= 0 for v in p):
        raise PersistenceError("trend_slope requires strictly positive prices")
    if len(p) < 30:
        raise PersistenceError(f"trend_slope needs n>=30, got {len(p)}")
    y = [math.log(v) for v in p]
    x = list(range(len(y)))
    slope, _, se, t, r2 = ols_slope(x, y)
    return {
        "slope_per_day": round(slope, 8),
        "annualized_log": round(slope * 365, 4),
        "se": round(se, 8) if se == se else None,
        "t": round(t, 3) if t == t else None,
        "p": two_sided_p(t) if t == t else None,
        "r2": round(r2, 4),
        "n": len(y),
        "hac_corrected": False,
        "note": "t 未做 HAC 修正，仅作相对比较，不作显著性结论",
    }


def ic_decay(prices, *, lookback: int = 20, horizons=(1, 5, 20)) -> dict:
    """A7 动量因子 IC 衰减（B13/B14/B15）。

    factor_t = 过去 lookback 期收益；target = 未来 h 期收益。
    同时给重叠样本与非重叠样本的 Spearman IC：
    重叠样本 n 大但 t 虚高，非重叠样本更保守（n 会很小）。
    """
    p = clean(prices)
    n = len(p)
    if lookback < 1:
        raise PersistenceError("lookback must be >=1")
    if n < lookback + max(horizons) + 30:
        raise PersistenceError("ic_decay: insufficient history")

    mom = [None] * n
    for i in range(lookback, n):
        if p[i - lookback] > 0:
            mom[i] = p[i] / p[i - lookback] - 1.0

    items = []
    for h in horizons:
        xs, ys, idx = [], [], []
        for i in range(lookback, n - h):
            if mom[i] is None:
                continue
            xs.append(mom[i])
            ys.append(p[i + h] / p[i] - 1.0)
            idx.append(i)
        if len(xs) < 10:
            items.append(
                {
                    "h": h,
                    "ric": None,
                    "n": len(xs),
                    "ric_nonoverlap": None,
                    "ric_nonoverlap_min": None,
                    "ric_nonoverlap_max": None,
                    "n_phases": 0,
                    "n_nonoverlap": 0,
                }
            )
            continue
        ric = spearman(xs, ys)
        # B2：非重叠采样不固定单一相位，遍历 h 个相位取均值与极差
        phase_rics, phase_counts = [], []
        for p0 in range(h):
            keep = [j for j, i in enumerate(idx) if i % h == p0]
            phase_counts.append(len(keep))
            if len(keep) >= 8:
                phase_rics.append(spearman([xs[j] for j in keep], [ys[j] for j in keep]))
        items.append(
            {
                "h": h,
                "ric": round(ric, 4),
                "n": len(xs),
                "ric_nonoverlap": round(mean(phase_rics), 4) if phase_rics else None,
                "ric_nonoverlap_min": round(min(phase_rics), 4) if phase_rics else None,
                "ric_nonoverlap_max": round(max(phase_rics), 4) if phase_rics else None,
                "n_phases": len(phase_rics),
                "n_nonoverlap": int(round(mean(phase_counts))) if phase_counts else 0,
            }
        )
    return {"lookback": lookback, "items": items, "n": n}
