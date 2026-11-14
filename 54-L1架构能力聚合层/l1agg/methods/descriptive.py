# -*- coding: utf-8 -*-
"""描述统计（S）与分布形态/稳健统计（D）。

覆盖 METHOD_LIBRARY：
  §2 S01–S10、S12–S24、S27、S28（S11/S25/S26 已在 conditional.py）
  §3 D01–D24（全量）

约束：默认纯 stdlib（复用 `_helpers`），D14/D15 懒加载 scipy，缺失时回退确定性
矩估计/近似（结果中 `method` 标注，简化口径）；无网络、无写库；
所有方法同输入同输出，参数通过函数参数传入而非 data 字段（避免污染 `_sample_n`）。
"""

from __future__ import annotations

import bisect
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import _helpers as H
from .registry import MethodChecks, register

_S = H.series

# 描述统计最小样本量（D1 类）
_N_MIN = 1


def _synth(values: Sequence[float], **params: Any) -> Dict[str, Any]:
    return {"data": {"series": list(values)}, "params": dict(params)}


def _expect(values: Sequence[float], expects: Mapping[str, Any], **params: Any) -> Dict[str, Any]:
    case = _synth(values, **params)
    case["expect"] = dict(expects)
    return case


# ======================================================================
# S 组：单维描述统计
# ======================================================================


@register(
    "S01",
    name="计数",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("n",),
    notes="有效值个数",
    checks=MethodChecks(synthetic=lambda: _expect([1, 2, 3], {"result.n": 3})),
)
def s01_count(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    return {"n": len(xs)}


@register(
    "S02",
    name="有效样本率",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("n_total", "n_valid", "ratio"),
    notes="None 视为缺失；ratio=n_valid/n_total",
)
def s02_valid_rate(data: Any) -> Dict[str, Any]:
    raw = data.get("series", data.get("values", data)) if isinstance(data, Mapping) else data
    total = len(raw)
    valid = sum(1 for v in raw if v is not None)
    return {"n_total": total, "n_valid": valid, "ratio": round(valid / total, 6) if total else None}


@register(
    "S03",
    name="算术均值",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("mean", "n"),
    checks=MethodChecks(synthetic=lambda: _expect([1, 2, 3, 4, 5], {"result.mean": 3.0})),
)
def s03_mean(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    return {"mean": H.r6(H.mean(xs)), "n": len(xs)}


@register(
    "S04",
    name="中位数",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("median", "n"),
    checks=MethodChecks(synthetic=lambda: _expect([1, 2, 3, 4, 5], {"result.median": 3.0})),
)
def s04_median(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    return {"median": H.r6(H.median(xs)), "n": len(xs)}


@register(
    "S05",
    name="众数（分箱）",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("mode", "count", "k"),
    notes="等宽分箱后取最高频箱中心（连续量无重复值）",
)
def s05_mode(data: Any, k: int = 10) -> Dict[str, Any]:
    xs = _S(data)
    lo, hi = min(xs), max(xs)
    if hi <= lo:
        return {"mode": H.r6(lo), "count": len(xs), "k": 1}
    width = (hi - lo) / k
    counts = [0] * k
    for v in xs:
        idx = min(int((v - lo) / width), k - 1)
        counts[idx] += 1
    best = max(range(k), key=lambda i: counts[i])
    center = lo + (best + 0.5) * width
    return {"mode": H.r6(center), "count": counts[best], "k": k}


@register(
    "S06",
    name="最小值/最大值",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("min", "max", "n"),
)
def s06_minmax(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    return {"min": H.r6(min(xs)), "max": H.r6(max(xs)), "n": len(xs)}


@register(
    "S07",
    name="极差",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("range", "n"),
    checks=MethodChecks(synthetic=lambda: _expect([1, 2, 3, 4, 5], {"result.range": 4.0})),
)
def s07_range(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    return {"range": H.r6(max(xs) - min(xs)), "n": len(xs)}


@register(
    "S08",
    name="方差（样本）",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("var", "n"),
    checks=MethodChecks(synthetic=lambda: _expect([1, 2, 3, 4, 5], {"result.var": 2.5})),
)
def s08_var(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    return {"var": H.r6(H.var(xs)), "n": len(xs)}


@register(
    "S09",
    name="标准差",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("std", "n"),
    checks=MethodChecks(synthetic=lambda: _expect([1, 2, 3, 4, 5], {"result.std": 1.581139})),
)
def s09_std(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    return {"std": H.r6(H.std(xs)), "n": len(xs)}


@register(
    "S10",
    name="变异系数",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("cv", "mean", "std", "n"),
    notes="σ/μ；μ≈0 时返回 None",
)
def s10_cv(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    mu, sd = H.mean(xs), H.std(xs)
    cv = sd / mu if abs(mu) > H.EPS else None
    return {"cv": H.r6(cv), "mean": H.r6(mu), "std": H.r6(sd), "n": len(xs)}


@register(
    "S12",
    name="四分位距",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=4,
    output_schema=("iqr", "q1", "q3", "n"),
    checks=MethodChecks(synthetic=lambda: _expect([1, 2, 3, 4, 5], {"result.iqr": 2.0})),
)
def s12_iqr(data: Any) -> Dict[str, Any]:
    xs = sorted(_S(data))
    q1, q3 = H.quantile(xs, 0.25), H.quantile(xs, 0.75)
    return {"iqr": H.r6(q3 - q1), "q1": H.r6(q1), "q3": H.r6(q3), "n": len(xs)}


@register(
    "S13",
    name="均值标准误",
    group="S",
    layer="D2",
    input_kind="series",
    min_n=2,
    output_schema=("se", "n"),
)
def s13_se(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    se = H.std(xs) / math.sqrt(n) if n else None
    return {"se": H.r6(se), "n": n}


@register(
    "S14",
    name="置信区间（正态近似）",
    group="S",
    layer="D2",
    input_kind="series",
    min_n=2,
    output_schema=("ci_low", "ci_high", "mean", "se", "n"),
    notes="μ ± 1.96·se（95%）",
)
def s14_ci(data: Any, level: float = 0.95) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    mu = H.mean(xs)
    se = H.std(xs) / math.sqrt(n) if n else 0.0
    z = H.norm_ppf(0.5 + level / 2.0)
    return {
        "ci_low": H.r6(mu - z * se),
        "ci_high": H.r6(mu + z * se),
        "mean": H.r6(mu),
        "se": H.r6(se),
        "n": n,
    }


@register(
    "S15",
    name="变化量",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("diff", "window", "n"),
)
def s15_diff(data: Any, k: int = 1) -> Dict[str, Any]:
    xs = _S(data)
    if k < 1 or len(xs) <= k:
        return {"diff": None, "window": k, "n": len(xs)}
    return {"diff": H.r6(xs[-1] - xs[-1 - k]), "window": k, "n": len(xs)}


@register(
    "S16",
    name="变化率",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("pct", "window", "n"),
)
def s16_pct(data: Any, k: int = 1) -> Dict[str, Any]:
    xs = _S(data)
    if k < 1 or len(xs) <= k or xs[-1 - k] == 0:
        return {"pct": None, "window": k, "n": len(xs)}
    return {"pct": H.r6(xs[-1] / xs[-1 - k] - 1.0), "window": k, "n": len(xs)}


@register(
    "S17",
    name="对数变化",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("logret", "window", "n"),
)
def s17_logret(data: Any, k: int = 1) -> Dict[str, Any]:
    xs = _S(data)
    if k < 1 or len(xs) <= k or xs[-1] <= 0 or xs[-1 - k] <= 0:
        return {"logret": None, "window": k, "n": len(xs)}
    return {"logret": H.r6(math.log(xs[-1] / xs[-1 - k])), "window": k, "n": len(xs)}


@register(
    "S18",
    name="累计变化率",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("cum", "n"),
    notes="returns=False 时按价格比 x_last/x_first−1；True 时按 ∏(1+r)−1",
)
def s18_cum(data: Any, is_returns: bool = False) -> Dict[str, Any]:
    xs = _S(data)
    if is_returns:
        prod = 1.0
        for v in xs:
            prod *= 1.0 + v
        return {"cum": H.r6(prod - 1.0), "n": len(xs)}
    if xs[0] == 0:
        return {"cum": None, "n": len(xs)}
    return {"cum": H.r6(xs[-1] / xs[0] - 1.0), "n": len(xs)}


@register(
    "S19",
    name="CAGR",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("cagr", "years", "n"),
    notes="(x_end/x_start)^(365/days)−1；days 默认 n−1",
)
def s19_cagr(data: Any, days: Optional[float] = None) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    span = float(days) if days else float(n - 1)
    if n < 2 or span <= 0 or xs[0] <= 0 or xs[-1] <= 0:
        return {"cagr": None, "years": None, "n": n}
    years = span / 365.0
    return {"cagr": H.r6((xs[-1] / xs[0]) ** (1.0 / years) - 1.0), "years": H.r6(years), "n": n}


def _rolling(xs: Sequence[float], k: int, fn) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(xs)):
        if i + 1 < k:
            out.append(None)
        else:
            out.append(H.r6(fn(xs[i + 1 - k : i + 1])))
    return out


@register(
    "S20",
    name="滚动均值",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("series", "k", "n"),
)
def s20_rolling_mean(data: Any, k: int = 5) -> Dict[str, Any]:
    xs = _S(data)
    if k < 1 or k > len(xs):
        return {"series": [], "k": k, "n": len(xs)}
    return {"series": _rolling(xs, k, H.mean), "k": k, "n": len(xs)}


@register(
    "S21",
    name="滚动中位数",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("series", "k", "n"),
)
def s21_rolling_median(data: Any, k: int = 5) -> Dict[str, Any]:
    xs = _S(data)
    if k < 1 or k > len(xs):
        return {"series": [], "k": k, "n": len(xs)}
    return {"series": _rolling(xs, k, H.median), "k": k, "n": len(xs)}


@register(
    "S22",
    name="滚动标准差",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("series", "k", "n"),
)
def s22_rolling_std(data: Any, k: int = 5) -> Dict[str, Any]:
    xs = _S(data)
    if k < 2 or k > len(xs):
        return {"series": [], "k": k, "n": len(xs)}
    return {"series": _rolling(xs, k, H.std), "k": k, "n": len(xs)}


@register(
    "S23",
    name="滚动极值",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("high", "low", "k", "n"),
)
def s23_rolling_extreme(data: Any, k: int = 5) -> Dict[str, Any]:
    xs = _S(data)
    if k < 1 or k > len(xs):
        return {"high": [], "low": [], "k": k, "n": len(xs)}
    return {"high": _rolling(xs, k, max), "low": _rolling(xs, k, min), "k": k, "n": len(xs)}


@register(
    "S24",
    name="排名/名次",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("rank", "n"),
    notes="末值在样本中的降序名次（1=最大）",
)
def s24_rank(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    last = xs[-1]
    rank = 1 + sum(1 for v in xs[:-1] if v > last)
    return {"rank": rank, "n": len(xs)}


@register(
    "S27",
    name="标准化 min-max",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("scaled", "min", "max", "n"),
    notes="全序列缩放；极差为 0 时返回全 0.5",
)
def s27_minmax(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    lo, hi = min(xs), max(xs)
    span = hi - lo
    scaled = [0.5 if span <= H.EPS else (v - lo) / span for v in xs]
    return {"scaled": [H.r6(v) for v in scaled], "min": H.r6(lo), "max": H.r6(hi), "n": len(xs)}


@register(
    "S28",
    name="趋势方向",
    group="S",
    layer="D2",
    input_kind="series",
    min_n=3,
    output_schema=("direction", "slope", "t", "n"),
    notes="末 k 点 OLS slope；|t|<2 或 slope≈0 记为 flat",
)
def s28_direction(data: Any, k: int = 20, t_threshold: float = 2.0) -> Dict[str, Any]:
    xs = _S(data)
    sub = xs[-min(k, len(xs)) :]
    fit = H.ols_slope(sub)
    slope, t = fit["slope"], fit["t"]
    if slope is None:
        return {"direction": "flat", "slope": None, "t": None, "n": len(xs)}
    if abs(slope) <= H.EPS or (t is not None and abs(t) < t_threshold):
        direction = "flat"
    else:
        direction = "up" if slope > 0 else "down"
    return {"direction": direction, "slope": H.r6(slope), "t": H.r4(t), "n": len(xs)}


# ======================================================================
# D 组：分布形态与稳健统计
# ======================================================================


@register(
    "D01",
    name="偏度",
    group="D",
    layer="D2",
    input_kind="series",
    min_n=3,
    output_schema=("skew", "n"),
    notes="总体三阶矩/σ³",
    checks=MethodChecks(synthetic=lambda: _expect([1, 2, 3, 4, 5], {"result.skew": 0.0})),
)
def d01_skew(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    return {"skew": H.r6(H.skewness(xs)), "n": len(xs)}


@register(
    "D02",
    name="峰度（超额）",
    group="D",
    layer="D2",
    input_kind="series",
    min_n=4,
    output_schema=("kurt", "n"),
    notes="总体四阶矩/σ⁴−3",
    checks=MethodChecks(synthetic=lambda: _expect([1, 2, 3, 4, 5], {"result.kurt": "non_empty"})),
)
def d02_kurtosis(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    return {"kurt": H.r6(H.kurtosis_excess(xs)), "n": len(xs)}


@register(
    "D03",
    name="中位数绝对偏差",
    group="D",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("mad", "median", "n"),
    checks=MethodChecks(synthetic=lambda: _expect([1, 2, 3, 4, 5], {"result.mad": 1.0})),
)
def d03_mad(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    med = H.median(xs)
    mad = H.median([abs(x - med) for x in xs])
    return {"mad": H.r6(mad), "median": H.r6(med), "n": len(xs)}


@register(
    "D04",
    name="稳健 z-score",
    group="D",
    layer="D2",
    input_kind="series",
    min_n=3,
    output_schema=("rz", "median", "mad", "n"),
    notes="0.6745(x−med)/MAD；MAD≈0 时返回 None 序列",
)
def d04_robust_z(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    med = H.median(xs)
    mad = H.median([abs(x - med) for x in xs])
    if mad <= H.EPS:
        return {"rz": [None] * len(xs), "median": H.r6(med), "mad": H.r6(mad), "n": len(xs)}
    rz = [0.6745 * (x - med) / mad for x in xs]
    return {"rz": [H.r4(v) for v in rz], "median": H.r6(med), "mad": H.r6(mad), "n": len(xs)}


@register(
    "D05",
    name="截尾均值",
    group="D",
    layer="D2",
    input_kind="series",
    min_n=3,
    output_schema=("trimmed_mean", "p", "n"),
)
def d05_trimmed_mean(data: Any, p: float = 5.0) -> Dict[str, Any]:
    xs = sorted(_S(data))
    cut = int(len(xs) * p / 100.0)
    sub = xs[cut : len(xs) - cut] if cut > 0 else xs
    if not sub:
        return {"trimmed_mean": None, "p": p, "n": len(xs)}
    return {"trimmed_mean": H.r6(H.mean(sub)), "p": p, "n": len(xs)}


@register(
    "D06",
    name="Winsorize",
    group="D",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("series", "p", "n"),
)
def d06_winsorize(data: Any, p: float = 1.0) -> Dict[str, Any]:
    xs = _S(data)
    s = sorted(xs)
    lo, hi = H.quantile(s, p / 100.0), H.quantile(s, 1.0 - p / 100.0)
    return {"series": [H.r6(min(max(v, lo), hi)) for v in xs], "p": p, "n": len(xs)}


@register(
    "D07",
    name="离群标记（IQR）",
    group="D",
    layer="D1",
    input_kind="series",
    min_n=4,
    output_schema=("flags", "n_outliers", "n"),
    notes="x<Q1−1.5IQR 或 x>Q3+1.5IQR",
)
def d07_outlier_iqr(data: Any, k: float = 1.5) -> Dict[str, Any]:
    xs = _S(data)
    s = sorted(xs)
    q1, q3 = H.quantile(s, 0.25), H.quantile(s, 0.75)
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    flags = [bool(v < lo or v > hi) for v in xs]
    return {"flags": flags, "n_outliers": sum(flags), "n": len(xs)}


@register(
    "D08",
    name="离群标记（MAD）",
    group="D",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("flags", "n_outliers", "n"),
    notes="|0.6745(x−med)/MAD| > 3.5",
)
def d08_outlier_mad(data: Any, z: float = 3.5) -> Dict[str, Any]:
    xs = _S(data)
    med = H.median(xs)
    mad = H.median([abs(x - med) for x in xs])
    if mad <= H.EPS:
        flags = [False] * len(xs)
    else:
        flags = [bool(abs(0.6745 * (v - med) / mad) > z) for v in xs]
    return {"flags": flags, "n_outliers": sum(flags), "n": len(xs)}


@register(
    "D09",
    name="经验 CDF",
    group="D",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("cdf", "n"),
    notes="F(x_i)=#{x≤x_i}/n",
)
def d09_ecdf(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    s = sorted(xs)
    n = len(s)
    cdf = [H.r6(bisect.bisect_right(s, v) / n) for v in xs]
    return {"cdf": cdf, "n": n}


@register(
    "D10",
    name="直方图分箱",
    group="D",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("edges", "counts", "k", "n"),
)
def d10_histogram(data: Any, k: int = 10) -> Dict[str, Any]:
    xs = _S(data)
    lo, hi = min(xs), max(xs)
    if hi <= lo or k < 1:
        return {"edges": [H.r6(lo), H.r6(hi)], "counts": [len(xs)], "k": 1, "n": len(xs)}
    width = (hi - lo) / k
    edges = [lo + i * width for i in range(k + 1)]
    counts = [0] * k
    for v in xs:
        idx = min(int((v - lo) / width), k - 1)
        counts[idx] += 1
    return {"edges": [H.r6(e) for e in edges], "counts": counts, "k": k, "n": len(xs)}


@register(
    "D11",
    name="核密度估计",
    group="D",
    layer="D2",
    input_kind="series",
    min_n=3,
    output_schema=("grid", "density", "bandwidth", "n"),
    notes="高斯核 + Silverman 带宽，固定 32 点网格",
)
def d11_kde(data: Any, points: int = 32) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    sd = H.std(xs)
    if sd <= H.EPS:
        return {"grid": [H.r6(xs[0])], "density": [None], "bandwidth": 0.0, "n": n}
    bw = 1.06 * sd * n ** (-0.2)
    lo, hi = min(xs) - 3 * bw, max(xs) + 3 * bw
    grid = [lo + (hi - lo) * i / (points - 1) for i in range(points)]
    density = []
    for g in grid:
        acc = sum(math.exp(-0.5 * ((g - x) / bw) ** 2) for x in xs)
        density.append(acc / (n * bw * math.sqrt(2 * math.pi)))
    return {
        "grid": [H.r6(g) for g in grid],
        "density": [H.r6(d) for d in density],
        "bandwidth": H.r6(bw),
        "n": n,
    }


@register(
    "D12",
    name="QQ 偏离度",
    group="D",
    layer="D3",
    input_kind="series",
    min_n=5,
    output_schema=("max_dev", "n"),
    notes="max|标准化值−正态理论分位|，越大越偏离正态",
)
def d12_qq_dev(data: Any) -> Dict[str, Any]:
    xs = sorted(_S(data))
    n = len(xs)
    mu, sd = H.mean(xs), H.std(xs)
    if sd <= H.EPS:
        return {"max_dev": None, "n": n}
    dev = 0.0
    for i, x in enumerate(xs):
        p = (i + 0.5) / n
        dev = max(dev, abs((x - mu) / sd - H.norm_ppf(p)))
    return {"max_dev": H.r4(dev), "n": n}


@register(
    "D13",
    name="正态性检验（Jarque-Bera）",
    group="D",
    layer="D3",
    input_kind="series",
    min_n=8,
    output_schema=("jb", "p", "n"),
    notes="JB=n/6·(S²+(K−3)²/4)，χ²(2) 上尾",
    checks=MethodChecks(
        synthetic=lambda: _expect(
            [((i * 37) % 23) - 11 + 0.1 * i for i in range(40)],
            {"result.jb": "non_empty", "result.p": "non_empty"},
        )
    ),
)
def d13_jarque_bera(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    sk, ku = H.skewness(xs), H.kurtosis_excess(xs)
    if sk is None or ku is None:
        return {"jb": None, "p": None, "n": n}
    jb = n / 6.0 * (sk**2 + ku**2 / 4.0)
    return {"jb": H.r4(jb), "p": H.r6(H.chi2_sf(jb, 2)), "n": n}


@register(
    "D14",
    name="正态性检验（Shapiro）",
    group="D",
    layer="D3",
    input_kind="series",
    min_n=30,
    output_schema=("w", "p", "normal", "n", "method"),
    notes="scipy.stats.shapiro；n>5000 时按等距固定步长取 5000 点（无随机）；"
    "scipy 缺失时回退 Jarque-Bera p（简化口径）",
)
def d14_shapiro(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    sample = xs if n <= 5000 else [xs[int(i * (n - 1) / 4999)] for i in range(5000)]
    w: Optional[float] = None
    p: Optional[float] = None
    method = "scipy_shapiro"
    try:
        from scipy import stats  # noqa: PLC0415

        wv, pv = stats.shapiro(sample)
        w, p = float(wv), float(pv)
    except Exception:  # noqa: BLE001 - 库缺失/数值失败回退 JB 近似
        method = "jarque_bera_fallback"
        sk, ku = H.skewness(xs), H.kurtosis_excess(xs)
        if sk is not None and ku is not None:
            jb = n / 6.0 * (sk**2 + ku**2 / 4.0)
            p = H.chi2_sf(jb, 2)
    normal = None if p is None else bool(p > 0.05)
    return {"w": H.r4(w), "p": H.r6(p), "normal": normal, "n": n, "method": method}


def _dist_fits(xs: Sequence[float]) -> Dict[str, Any]:
    """正态/对数正态/学生 t 的 (params, loglik, k)；scipy 缺失时用矩估计近似。"""
    n = len(xs)
    mu, sd = H.mean(xs), H.std(xs)
    fits: Dict[str, Any] = {
        "normal": {"params": {"mu": mu, "sigma": sd}, "k": 2, "loglik": None},
        "lognormal": {"params": None, "k": 2, "loglik": None},
        "t": {"params": None, "k": 3, "loglik": None},
    }
    if n > 0 and sd > H.EPS:
        sse = sum((v - mu) ** 2 for v in xs)
        fits["normal"]["loglik"] = -0.5 * n * math.log(2 * math.pi * sd * sd) - sse / (
            2.0 * sd * sd
        )
    if all(v > 0 for v in xs):
        logs = [math.log(v) for v in xs]
        lm, ls = H.mean(logs), H.std(logs)
        fits["lognormal"]["params"] = {"mu_log": lm, "sigma_log": ls}
        if ls > H.EPS:
            sse_l = sum((v - lm) ** 2 for v in logs)
            fits["lognormal"]["loglik"] = (
                -sum(logs) - 0.5 * n * math.log(2 * math.pi * ls * ls) - sse_l / (2.0 * ls * ls)
            )
    try:
        from scipy import stats  # noqa: PLC0415

        df, loc, scale = stats.t.fit(xs)
        if scale > 0 and df > 0:
            fits["t"]["params"] = {"df": float(df), "loc": float(loc), "scale": float(scale)}
            fits["t"]["loglik"] = float(sum(stats.t.logpdf(xs, df, loc, scale)))
    except Exception:  # noqa: BLE001 - 库缺失/拟合失败则 t 不参与 AIC 比较
        pass
    for fit in fits.values():
        ll = fit["loglik"]
        fit["aic"] = None if ll is None else 2.0 * fit["k"] - 2.0 * ll
    return fits


@register(
    "D15",
    name="分布拟合（正态/对数正态/学生 t）",
    group="D",
    layer="D3",
    input_kind="series",
    min_n=30,
    output_schema=("best", "params", "aic", "aic_normal", "aic_lognormal", "aic_t", "n", "method"),
    notes="MLE（scipy.stats）后按 AIC=2k−2lnL 选最优；对数正态要求全正；"
    "scipy 缺失时仅正态/对数正态矩估计（t 不参与，简化口径）",
)
def d15_dist_fit(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    fits = _dist_fits(xs)
    usable = [(f["aic"], name) for name, f in fits.items() if f["aic"] is not None]
    method = "scipy_mle" if fits["t"]["params"] is not None else "moments_fallback"
    if not usable:
        return {
            "best": None,
            "params": None,
            "aic": None,
            "aic_normal": None,
            "aic_lognormal": None,
            "aic_t": None,
            "n": len(xs),
            "method": method,
        }
    best_aic, best = min(usable)
    params = fits[best]["params"] or {}
    return {
        "best": best,
        "params": {k: H.r6(v) for k, v in params.items()},
        "aic": H.r4(best_aic),
        "aic_normal": H.r4(fits["normal"]["aic"]),
        "aic_lognormal": H.r4(fits["lognormal"]["aic"]),
        "aic_t": H.r4(fits["t"]["aic"]),
        "n": len(xs),
        "method": method,
    }


@register(
    "D16",
    name="尾部指数（Hill）",
    group="D",
    layer="D3",
    input_kind="series",
    min_n=10,
    output_schema=("alpha", "k", "n"),
    notes="仅对正值序列；k 默认 max(5, n//20)",
)
def d16_hill(data: Any, k: int = 0) -> Dict[str, Any]:
    xs = sorted((v for v in _S(data) if v > 0), reverse=True)
    n = len(xs)
    kk = k if k > 0 else max(5, n // 20)
    if n <= kk or kk < 2:
        return {"alpha": None, "k": kk, "n": n}
    ref = xs[kk]
    acc = sum(math.log(xs[i] / ref) for i in range(kk))
    alpha = kk / acc if acc > H.EPS else None
    return {"alpha": H.r4(alpha), "k": kk, "n": n}


@register(
    "D17",
    name="VaR（历史法）",
    group="D",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("var", "q", "n"),
    notes="返回正数形式的损失：−P_q(returns)",
    checks=MethodChecks(
        synthetic=lambda: _expect(
            [-0.02 + 0.0001 * i for i in range(100)], {"result.var": "non_empty"}
        )
    ),
)
def d17_var(data: Any, q: float = 5.0) -> Dict[str, Any]:
    xs = sorted(_S(data))
    v = -H.quantile(xs, q / 100.0)
    return {"var": H.r6(v), "q": q, "n": len(xs)}


@register(
    "D18",
    name="CVaR / ES",
    group="D",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("cvar", "q", "n"),
    notes="−E[r | r ≤ P_q]",
    checks=MethodChecks(
        synthetic=lambda: _expect(
            [-0.02 + 0.0001 * i for i in range(100)], {"result.cvar": "non_empty"}
        )
    ),
)
def d18_cvar(data: Any, q: float = 5.0) -> Dict[str, Any]:
    xs = sorted(_S(data))
    cut = H.quantile(xs, q / 100.0)
    tail = [v for v in xs if v <= cut]
    cvar = -H.mean(tail) if tail else None
    return {"cvar": H.r6(cvar), "q": q, "n": len(xs)}


@register(
    "D19",
    name="最大单期跌幅",
    group="D",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("worst", "n"),
)
def d19_worst(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    return {"worst": H.r6(min(xs)), "n": len(xs)}


@register(
    "D20",
    name="最大回撤",
    group="D",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("mdd", "peak_index", "trough_index", "n"),
    notes="输入为价格序列，非收益",
    checks=MethodChecks(synthetic=lambda: _expect([100, 120, 90, 110], {"result.mdd": 0.25})),
)
def d20_mdd(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    prof = H.drawdown_profile(xs)
    return {
        "mdd": prof["mdd"],
        "peak_index": prof["peak_index"],
        "trough_index": prof["trough_index"],
        "n": prof["n"],
    }


@register(
    "D21",
    name="回撤持续期",
    group="D",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("duration_days", "recovery_days", "recovered", "n"),
)
def d21_drawdown_duration(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    prof = H.drawdown_profile(xs)
    return {
        "duration_days": prof["duration_days"],
        "recovery_days": prof["recovery_days"],
        "recovered": prof["recovered"],
        "n": prof["n"],
    }


@register(
    "D22",
    name="上下行波动比",
    group="D",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("ratio", "up_vol", "down_vol", "n"),
    notes="σ(正收益)/σ(负收益)；任一侧不足 2 点返回 None",
)
def d22_updown_vol(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    up = [v for v in xs if v > 0]
    dn = [v for v in xs if v < 0]
    if len(up) < 2 or len(dn) < 2:
        return {"ratio": None, "up_vol": None, "down_vol": None, "n": len(xs)}
    su, sd = H.std(up), H.std(dn)
    ratio = su / sd if sd > H.EPS else None
    return {"ratio": H.r4(ratio), "up_vol": H.r6(su), "down_vol": H.r6(sd), "n": len(xs)}


@register(
    "D23",
    name="盈亏比",
    group="D",
    layer="D1",
    input_kind="series",
    min_n=5,
    output_schema=("pl_ratio", "avg_win", "avg_loss", "n"),
)
def d23_profit_loss(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    wins = [v for v in xs if v > 0]
    losses = [v for v in xs if v < 0]
    if not wins or not losses:
        return {"pl_ratio": None, "avg_win": None, "avg_loss": None, "n": len(xs)}
    aw, al = H.mean(wins), H.mean(losses)
    return {
        "pl_ratio": H.r4(aw / abs(al)) if abs(al) > H.EPS else None,
        "avg_win": H.r6(aw),
        "avg_loss": H.r6(al),
        "n": len(xs),
    }


@register(
    "D24",
    name="胜率",
    group="D",
    layer="D1",
    input_kind="series",
    min_n=5,
    output_schema=("win_rate", "wins", "n"),
    checks=MethodChecks(
        synthetic=lambda: _expect(
            [0.01, -0.01, 0.02, 0.0, 0.03, -0.02, 0.01, -0.01], {"result.win_rate": 0.5}
        )
    ),
)
def d24_win_rate(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    wins = sum(1 for v in xs if v > 0)
    return {"win_rate": H.r4(wins / len(xs)) if xs else None, "wins": wins, "n": len(xs)}
