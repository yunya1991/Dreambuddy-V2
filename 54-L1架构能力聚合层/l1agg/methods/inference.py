# -*- coding: utf-8 -*-
"""假设检验（H）、分箱状态（B）补充、多变量（M）补充与关系表达（R）。

覆盖 METHOD_LIBRARY：
  §10 H02–H08、H09–H12、H13–H18（H01 已在 conditional.py；
      H09 复用 T07 的 Ljung-Box 口径，H10/H11 走 ADF / Engle-Granger，H12 走 D'Agostino 正态性）
  §8  B04、B06–B10、B17、B18（B01–B03/B05/B11–B16 已在 conditional.py）
  §7  M17、M23
  §11 R03–R18（R01/R02 已在 conditional.py）

约束：以 stdlib 为主（复用 `_helpers` / `stats_core` / 已冻结的 T07/M06/M11/M12/M04/C14 口径）；
H10/H11/H12 在使用点延迟导入 statsmodels/scipy；置换与 Bootstrap 固定 seed 保证确定性。
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import _helpers as H
from .conditional import b11_monotonic
from .correlation import m04_rolling, m06_topk, m11_ccf, m12_best_lag
from .registry import MethodChecks, register
from .seasonal import _parse_one, _rets_dates, c14_month_consistency
from .stats_core import bh_fdr, t_two_sided_p
from .timeseries import t07_ljung_box

_EPS = H.EPS
COND_MIN_N = 250  # 与 conditional.py 的条件/分组门禁一致
_WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# ---------------------------------------------------------------- 通用工具


def _raw(data: Any, *keys: str) -> List[Any]:
    if isinstance(data, Mapping):
        for key in keys:
            if key in data:
                return list(data[key])
        raise ValueError(f"raw data must contain one of {keys}")
    return list(data)


def _two_groups(data: Mapping[str, Any], need: int = 2) -> Tuple[List[str], List[List[float]]]:
    """按 state/group 分组，返回 (组名, 各组数值)，保留出现顺序。"""
    labels, values = H.group_pair(data)
    order: List[str] = []
    bucket: Dict[str, List[float]] = {}
    for g, v in zip(labels, values, strict=False):
        if g not in bucket:
            bucket[g] = []
            order.append(g)
        bucket[g].append(v)
    return order[:need], [bucket[g] for g in order[:need]]


def _two_cats(data: Mapping[str, Any]) -> Tuple[List[str], List[str]]:
    for a, b in (("row", "col"), ("group", "state"), ("x", "y")):
        if a in data and b in data:
            n = min(len(data[a]), len(data[b]))
            return [str(v) for v in data[a][:n]], [str(v) for v in data[b][:n]]
    raise ValueError("categorical pair must contain row/col or group/state or x/y")


def _ranks(vals: Sequence[float]) -> List[float]:
    """平均秩（并列取均值）。"""
    idx = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and vals[idx[j + 1]] == vals[idx[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[idx[k]] = avg
        i = j + 1
    return ranks


def _group_synth() -> Dict[str, Any]:
    a = [round(0.005 + 0.001 * i, 6) for i in range(12)]
    b = [round(0.020 + 0.001 * i, 6) for i in range(12)]
    return {"data": {"state": ["a"] * 12 + ["b"] * 12, "target": a + b}, "params": {}, "expect": {}}


# ======================================================================
# H 组：假设检验
# ======================================================================


@register(
    "H02",
    name="双样本 t 检验",
    group="H",
    layer="D2",
    input_kind="pairs",
    min_n=10,
    output_schema=("t", "p", "df", "diff", "n"),
    notes="Student t（合并方差）；组来自 state/target",
    checks=MethodChecks(synthetic=_group_synth),
)
def h02_two_sample_t(data: Any) -> Dict[str, Any]:
    _, groups = _two_groups(data)
    if len(groups) < 2:
        return {"t": None, "p": None, "df": None, "diff": None, "n": 0}
    a, b = groups[0], groups[1]
    n1, n2 = len(a), len(b)
    df = n1 + n2 - 2
    if df <= 0:
        return {"t": None, "p": None, "df": df, "diff": None, "n": n1 + n2}
    sp2 = ((n1 - 1) * H.var(a) + (n2 - 1) * H.var(b)) / df
    se = math.sqrt(sp2 * (1.0 / n1 + 1.0 / n2))
    diff = H.mean(a) - H.mean(b)
    t = diff / se if se > _EPS else None
    return {
        "t": H.r4(t),
        "p": t_two_sided_p(t, df) if t is not None else None,
        "df": df,
        "diff": H.r6(diff),
        "n": n1 + n2,
    }


@register(
    "H03",
    name="Welch t 检验",
    group="H",
    layer="D2",
    input_kind="pairs",
    min_n=10,
    output_schema=("t", "p", "df", "diff", "n"),
    notes="方差不等，Welch-Satterthwaite 自由度",
    checks=MethodChecks(synthetic=_group_synth),
)
def h03_welch_t(data: Any) -> Dict[str, Any]:
    _, groups = _two_groups(data)
    if len(groups) < 2:
        return {"t": None, "p": None, "df": None, "diff": None, "n": 0}
    a, b = groups[0], groups[1]
    n1, n2 = len(a), len(b)
    v1, v2 = H.var(a) / n1, H.var(b) / n2
    diff = H.mean(a) - H.mean(b)
    se = math.sqrt(v1 + v2)
    t = diff / se if se > _EPS else None
    df = (v1 + v2) ** 2 / ((v1**2) / (n1 - 1) + (v2**2) / (n2 - 1)) if (n1 > 1 and n2 > 1) else None
    p = t_two_sided_p(t, df) if (t is not None and df) else None
    return {
        "t": H.r4(t),
        "p": p,
        "df": None if df is None else H.r4(df),
        "diff": H.r6(diff),
        "n": n1 + n2,
    }


@register(
    "H04",
    name="Mann-Whitney U",
    group="H",
    layer="D2",
    input_kind="pairs",
    min_n=10,
    output_schema=("u", "z", "p", "n"),
    notes="正态近似 + 并列秩修正",
    checks=MethodChecks(synthetic=_group_synth),
)
def h04_mann_whitney(data: Any) -> Dict[str, Any]:
    _, groups = _two_groups(data)
    if len(groups) < 2:
        return {"u": None, "z": None, "p": None, "n": 0}
    a, b = groups[0], groups[1]
    n1, n2 = len(a), len(b)
    merged = list(a) + list(b)
    ranks = _ranks(merged)
    r1 = sum(ranks[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2.0
    n = n1 + n2
    # 并列修正
    tie = 0.0
    counts: Dict[float, int] = {}
    for v in merged:
        counts[v] = counts.get(v, 0) + 1
    for t in counts.values():
        if t > 1:
            tie += t**3 - t
    var = n1 * n2 / 12.0 * ((n + 1) - tie / (n * (n - 1))) if n > 1 else 0.0
    mu = n1 * n2 / 2.0
    z = (u1 - mu) / math.sqrt(var) if var > _EPS else None
    p = None if z is None else H.r6(2.0 * (1.0 - H.norm_cdf(abs(z))))
    return {"u": H.r4(u1), "z": H.r4(z), "p": p, "n": n}


@register(
    "H05",
    name="Wilcoxon 符号秩",
    group="H",
    layer="D2",
    input_kind="pairs",
    min_n=10,
    output_schema=("w", "z", "p", "n"),
    notes="配对差；输入 actual/expected",
)
def h05_wilcoxon(data: Mapping[str, Any]) -> Dict[str, Any]:
    a, b = H.two(data)
    diffs = [x - y for x, y in zip(a, b, strict=False) if abs(x - y) > _EPS]
    n = len(diffs)
    if n < 2:
        return {"w": None, "z": None, "p": None, "n": n}
    ranks = _ranks([abs(d) for d in diffs])
    w = sum(r for r, d in zip(ranks, diffs, strict=False) if d > 0)
    mu = n * (n + 1) / 4.0
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
    z = (w - mu) / sd if sd > _EPS else None
    p = None if z is None else H.r6(2.0 * (1.0 - H.norm_cdf(abs(z))))
    return {"w": H.r4(w), "z": H.r4(z), "p": p, "n": n}


@register(
    "H06",
    name="卡方独立性",
    group="H",
    layer="D3",
    input_kind="pairs",
    min_n=10,
    output_schema=("chi2", "p", "df", "n"),
    notes="二维列联表 row×col",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "row": ["a"] * 10 + ["b"] * 10,
                "col": ["x"] * 7 + ["y"] * 3 + ["x"] * 4 + ["y"] * 6,
            },
            "params": {},
            "expect": {"result.p": "non_empty"},
        }
    ),
)
def h06_chi2(data: Mapping[str, Any]) -> Dict[str, Any]:
    rows, cols = _two_cats(data)
    n = len(rows)
    rkeys = sorted(set(rows))
    ckeys = sorted(set(cols))
    table = {r: dict.fromkeys(ckeys, 0) for r in rkeys}
    for r, c in zip(rows, cols, strict=False):
        table[r][c] += 1
    rt = {r: sum(table[r].values()) for r in rkeys}
    ct = {c: sum(table[r][c] for r in rkeys) for c in ckeys}
    chi2 = 0.0
    for r in rkeys:
        for c in ckeys:
            e = rt[r] * ct[c] / n
            if e > 0:
                chi2 += (table[r][c] - e) ** 2 / e
    df = (len(rkeys) - 1) * (len(ckeys) - 1)
    return {
        "chi2": H.r4(chi2),
        "p": H.r6(H.chi2_sf(chi2, df)) if df > 0 else None,
        "df": df,
        "n": n,
    }


@register(
    "H07",
    name="方差分析 ANOVA",
    group="H",
    layer="D3",
    input_kind="pairs",
    min_n=10,
    output_schema=("f", "p", "df1", "df2", "n"),
    notes="单因素组间/组内均方比",
    checks=MethodChecks(synthetic=_group_synth),
)
def h07_anova(data: Any) -> Dict[str, Any]:
    order, groups = _two_groups(data, need=99)
    k = len(groups)
    if k < 2:
        return {"f": None, "p": None, "df1": k - 1, "df2": 0, "n": 0}
    all_vals = [v for g in groups for v in g]
    n = len(all_vals)
    gm = H.mean(all_vals)
    ssb = sum(len(g) * (H.mean(g) - gm) ** 2 for g in groups)
    ssw = sum(sum((v - H.mean(g)) ** 2 for v in g) for g in groups)
    df1, df2 = k - 1, n - k
    if df2 <= 0 or ssw <= _EPS:
        return {"f": None, "p": None, "df1": df1, "df2": df2, "n": n}
    f = (ssb / df1) / (ssw / df2)
    return {"f": H.r4(f), "p": H.r6(H.f_sf(f, df1, df2)), "df1": df1, "df2": df2, "n": n}


@register(
    "H08",
    name="Kruskal-Wallis",
    group="H",
    layer="D3",
    input_kind="pairs",
    min_n=10,
    output_schema=("h", "p", "df", "n"),
    notes="秩和检验 + 并列修正",
    checks=MethodChecks(synthetic=_group_synth),
)
def h08_kruskal(data: Any) -> Dict[str, Any]:
    order, groups = _two_groups(data, need=99)
    k = len(groups)
    all_vals = [v for g in groups for v in g]
    n = len(all_vals)
    if k < 2 or n < 3:
        return {"h": None, "p": None, "df": k - 1, "n": n}
    ranks = _ranks(all_vals)
    pos = 0
    total = 0.0
    for g in groups:
        rsum = sum(ranks[pos : pos + len(g)])
        pos += len(g)
        total += rsum**2 / len(g)
    hstat = 12.0 / (n * (n + 1)) * total - 3 * (n + 1)
    counts: Dict[float, int] = {}
    for v in all_vals:
        counts[v] = counts.get(v, 0) + 1
    tie = sum(t**3 - t for t in counts.values() if t > 1)
    corr = 1.0 - tie / (n**3 - n) if n > 1 else 1.0
    if corr > _EPS:
        hstat /= corr
    df = k - 1
    return {"h": H.r4(hstat), "p": H.r6(H.chi2_sf(hstat, df)), "df": df, "n": n}


@register(
    "H09",
    name="自相关检验（Ljung-Box）",
    group="H",
    layer="D3",
    input_kind="series",
    min_n=30,
    output_schema=("q", "p", "df", "n", "is_significant"),
    notes="§10 别名：复用 T07 的 Ljung-Box 口径（Q=n(n+2)Σ r_k²/(n−k)，χ²(m) 上尾）",
)
def h09_autocorr_test(data: Any, max_lag: int = 10) -> Dict[str, Any]:
    out = t07_ljung_box(data, max_lag=max_lag)
    p = out["p"]
    return {
        "q": out["q"],
        "p": p,
        "df": out["df"],
        "n": out["n"],
        "is_significant": None if p is None else bool(p < 0.05),
    }


@register(
    "H10",
    name="单位根检验（ADF）",
    group="H",
    layer="D3",
    input_kind="series",
    min_n=30,
    output_schema=("stat", "p", "lags", "n", "is_significant", "stationary", "critical"),
    notes="H0=存在单位根；p<alpha → 拒绝单位根（stationary=True）；statsmodels.adfuller，AIC 选阶",
)
def h10_unit_root(
    data: Any, regression: str = "c", maxlag: Optional[int] = None, alpha: float = 0.05
) -> Dict[str, Any]:
    xs = H.series(data)
    if len(xs) < 8 or len({round(v, 12) for v in xs}) < 3:
        return {
            "stat": None,
            "p": None,
            "lags": None,
            "n": len(xs),
            "is_significant": None,
            "stationary": None,
            "critical": None,
        }
    from statsmodels.tsa.stattools import adfuller  # 延迟导入：包导入保持 stdlib

    stat, p, usedlag, nobs, crit, _icbest = adfuller(
        xs, maxlag=maxlag, regression=regression, autolag="AIC", result_object=False
    )
    p = float(p)
    return {
        "stat": H.r4(float(stat)),
        "p": H.r6(p),
        "lags": int(usedlag),
        "n": int(nobs),
        "is_significant": bool(p < alpha),
        "stationary": bool(p < alpha),
        "critical": {k: H.r4(float(v)) for k, v in crit.items()},
    }


@register(
    "H11",
    name="协整检验（Engle-Granger）",
    group="H",
    layer="D3",
    input_kind="pairs",
    min_n=60,
    output_schema=("stat", "p", "n", "is_significant", "cointegrated", "critical"),
    notes="x/y 为两条价格（对数）序列；statsmodels.coint（H0=无协整），AIC 选阶",
)
def h11_cointegration(
    data: Mapping[str, Any], trend: str = "c", alpha: float = 0.05
) -> Dict[str, Any]:
    xs, ys = H.two(data)
    if len(ys) < 8 or len({round(v, 12) for v in xs}) < 3 or len({round(v, 12) for v in ys}) < 3:
        return {
            "stat": None,
            "p": None,
            "n": len(ys),
            "is_significant": None,
            "cointegrated": None,
            "critical": None,
        }
    from statsmodels.tsa.stattools import coint  # 延迟导入

    stat, p, crit = coint(ys, xs, trend=trend, autolag="aic")
    p = float(p)
    crit_map = (
        {str(k): float(v) for k, v in crit.items()}
        if isinstance(crit, Mapping)
        else dict(zip(("1%", "5%", "10%"), (float(v) for v in crit), strict=False))
    )
    return {
        "stat": H.r4(float(stat)),
        "p": H.r6(p),
        "n": len(ys),
        "is_significant": bool(p < alpha),
        "cointegrated": bool(p < alpha),
        "critical": {k: H.r4(v) for k, v in crit_map.items()},
    }


@register(
    "H12",
    name="正态性检验（D'Agostino-Pearson）",
    group="H",
    layer="D3",
    input_kind="series",
    min_n=30,
    output_schema=("stat", "p", "n", "is_significant", "normal"),
    notes="§10 别名：见 D13/D14；scipy.stats.normaltest，H0=样本来自正态分布",
)
def h12_normality(data: Any, alpha: float = 0.05) -> Dict[str, Any]:
    xs = H.series(data)
    if len(xs) < 8 or H.std(xs) <= _EPS:
        return {"stat": None, "p": None, "n": len(xs), "is_significant": None, "normal": None}
    from scipy import stats as sps  # 延迟导入

    res = sps.normaltest(xs)
    stat, p = float(res.statistic), float(res.pvalue)
    return {
        "stat": H.r4(stat),
        "p": H.r6(p),
        "n": len(xs),
        "is_significant": bool(p < alpha),
        "normal": bool(p >= alpha),
    }


def _pvals(data: Any) -> List[float]:
    if isinstance(data, Mapping):
        for key in ("p", "pvalues", "values"):
            if key in data:
                return [float(v) for v in data[key]]
    return [float(v) for v in data]


@register(
    "H13",
    name="多重比较校正（Bonferroni）",
    group="H",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("p_adj", "m", "significant"),
    notes="p_adj=min(1, p·m)",
)
def h13_bonferroni(data: Any, alpha: float = 0.05) -> Dict[str, Any]:
    ps = _pvals(data)
    m = len(ps)
    adj = [H.r6(min(1.0, p * m)) for p in ps]
    return {"p_adj": adj, "m": m, "significant": [a <= alpha for a in adj]}


@register(
    "H14",
    name="多重比较校正（BH-FDR）",
    group="H",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("q", "m", "significant", "alpha"),
    notes="Benjamini-Hochberg，q 单调",
)
def h14_bh_fdr(data: Any, alpha: float = 0.05) -> Dict[str, Any]:
    ps = _pvals(data)
    out = bh_fdr(ps, alpha)
    return {
        "q": [H.r6(v) for v in out["q"]],
        "m": out["m"],
        "significant": out["reject"],
        "alpha": alpha,
    }


@register(
    "H15",
    name="置换检验",
    group="H",
    layer="D3",
    input_kind="pairs",
    min_n=10,
    output_schema=("p_perm", "observed", "trials", "n"),
    notes="打乱组标签重算均值差；seed 固定保证确定性",
    checks=MethodChecks(synthetic=_group_synth),
)
def h15_permutation(data: Any, trials: int = 200, seed: int = 42) -> Dict[str, Any]:
    _, groups = _two_groups(data)
    if len(groups) < 2:
        return {"p_perm": None, "observed": None, "trials": trials, "n": 0}
    a, b = groups[0], groups[1]
    pooled = list(a) + list(b)
    n1 = len(a)
    obs = H.mean(a) - H.mean(b)
    rng = random.Random(seed)
    hits = 0
    for _ in range(trials):
        rng.shuffle(pooled)
        d = H.mean(pooled[:n1]) - H.mean(pooled[n1:])
        if abs(d) >= abs(obs):
            hits += 1
    return {
        "p_perm": H.r4((hits + 1) / (trials + 1)),
        "observed": H.r6(obs),
        "trials": trials,
        "n": len(pooled),
    }


@register(
    "H16",
    name="Bootstrap 置信区间",
    group="H",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("ci_low", "ci_high", "mean", "trials", "n"),
    notes="均值的百分位 Bootstrap；seed 固定",
)
def h16_bootstrap(
    data: Any, trials: int = 500, seed: int = 42, level: float = 0.95
) -> Dict[str, Any]:
    xs = H.series(data)
    rng = random.Random(seed)
    n = len(xs)
    means = []
    for _ in range(trials):
        means.append(H.mean([xs[rng.randrange(n)] for _ in range(n)]))
    means.sort()
    lo = H.quantile(means, (1.0 - level) / 2.0)
    hi = H.quantile(means, 1.0 - (1.0 - level) / 2.0)
    return {
        "ci_low": H.r6(lo),
        "ci_high": H.r6(hi),
        "mean": H.r6(H.mean(xs)),
        "trials": trials,
        "n": n,
    }


@register(
    "H17",
    name="效应量（Cohen d）",
    group="H",
    layer="D2",
    input_kind="pairs",
    min_n=10,
    output_schema=("d", "diff", "pooled_std", "n"),
    checks=MethodChecks(synthetic=_group_synth),
)
def h17_cohen_d(data: Any) -> Dict[str, Any]:
    _, groups = _two_groups(data)
    if len(groups) < 2:
        return {"d": None, "diff": None, "pooled_std": None, "n": 0}
    a, b = groups[0], groups[1]
    n1, n2 = len(a), len(b)
    df = n1 + n2 - 2
    if df <= 0:
        return {"d": None, "diff": None, "pooled_std": None, "n": n1 + n2}
    sp = math.sqrt(((n1 - 1) * H.var(a) + (n2 - 1) * H.var(b)) / df)
    diff = H.mean(a) - H.mean(b)
    return {
        "d": H.r4(diff / sp) if sp > _EPS else None,
        "diff": H.r6(diff),
        "pooled_std": H.r6(sp),
        "n": n1 + n2,
    }


@register(
    "H18",
    name="统计功效（近似）",
    group="H",
    layer="D2",
    input_kind="series",
    min_n=1,
    output_schema=("power", "n", "d", "alpha"),
    notes="双样本 t 近似：Φ(|d|√(n/2) − z_{1−α/2})",
)
def h18_power(data: Any, d: float = 0.5, alpha: float = 0.05) -> Dict[str, Any]:
    n = max(1, len(H.series(data)))
    z_alpha = H.norm_ppf(1.0 - alpha / 2.0)
    power = H.norm_cdf(abs(d) * math.sqrt(n / 2.0) - z_alpha)
    return {"power": H.r4(power), "n": n, "d": d, "alpha": alpha}


# ======================================================================
# B 组补充：分箱 / 状态 / 聚合
# ======================================================================


@register(
    "B04",
    name="状态离散化",
    group="B",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("states", "counts", "threshold", "n"),
    notes="规则映射：>threshold 为 high，否则 low",
)
def b04_discretize(data: Any, threshold: float = 0.5) -> Dict[str, Any]:
    xs = H.series(data)
    states = ["high" if v > threshold else "low" for v in xs]
    counts = {"high": states.count("high"), "low": states.count("low")}
    return {"states": states, "counts": counts, "threshold": threshold, "n": len(xs)}


@register(
    "B06",
    name="二维交叉表",
    group="B",
    layer="D1",
    input_kind="pairs",
    min_n=3,
    output_schema=("rows", "cols", "table", "n"),
    notes="状态 × 结果的联合计数；输入为两条类别序列",
)
def b06_crosstab(data: Mapping[str, Any]) -> Dict[str, Any]:
    rows, cols = _two_cats(data)
    rkeys = sorted(set(rows))
    ckeys = sorted(set(cols))
    table = {r: dict.fromkeys(ckeys, 0) for r in rkeys}
    for r, c in zip(rows, cols, strict=False):
        table[r][c] += 1
    return {"rows": rkeys, "cols": ckeys, "table": table, "n": len(rows)}


def _transition(labels: Sequence[str]) -> Dict[str, Any]:
    order: List[str] = []
    for v in labels:
        if v not in order:
            order.append(v)
    counts = {a: dict.fromkeys(order, 0) for a in order}
    for a, b in zip(labels, labels[1:], strict=False):
        counts[a][b] += 1
    matrix = []
    for a in order:
        tot = sum(counts[a].values())
        matrix.append([None if tot == 0 else round(counts[a][b] / tot, 6) for b in order])
    return {"states": order, "matrix": matrix, "counts": counts, "n": len(labels)}


@register(
    "B07",
    name="状态转移矩阵",
    group="B",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("states", "matrix", "n"),
    notes="P(s_{t+1}|s_t)，行随机；输入为离散状态序列",
)
def b07_transition(data: Any) -> Dict[str, Any]:
    out = _transition(_raw(data, "state", "states", "labels"))
    return {"states": out["states"], "matrix": out["matrix"], "n": out["n"]}


@register(
    "B08",
    name="马尔可夫稳态分布",
    group="B",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("states", "stationary", "n"),
    notes="幂迭代求行随机矩阵左特征向量",
)
def b08_stationary(data: Any) -> Dict[str, Any]:
    out = _transition(_raw(data, "state", "states", "labels"))
    order, matrix = out["states"], out["matrix"]
    k = len(order)
    if k == 0:
        return {"states": [], "stationary": [], "n": out["n"]}
    dist = [1.0 / k] * k
    for _ in range(500):
        nxt = [0.0] * k
        for i, p in enumerate(dist):
            row = matrix[i]
            for j in range(k):
                if row[j] is not None:
                    nxt[j] += p * row[j]
        total = sum(nxt)
        nxt = [v / total for v in nxt] if total > _EPS else dist
        if max(abs(a - b) for a, b in zip(nxt, dist, strict=False)) < 1e-12:
            dist = nxt
            break
        dist = nxt
    return {"states": order, "stationary": [H.r6(v) for v in dist], "n": out["n"]}


@register(
    "B09",
    name="同状态持续性",
    group="B",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("states", "dwell", "n"),
    notes="期望停留期 = 1/(1−p_ii)",
)
def b09_dwell(data: Any) -> Dict[str, Any]:
    out = _transition(_raw(data, "state", "states", "labels"))
    order, matrix = out["states"], out["matrix"]
    dwell = []
    for i, row in enumerate(matrix):
        p = row[i]
        dwell.append(None if (p is None or p >= 1.0) else round(1.0 / (1.0 - p), 4))
    return {"states": order, "dwell": dwell, "n": out["n"]}


@register(
    "B10",
    name="条件分位",
    group="B",
    layer="D2",
    input_kind="pairs",
    min_n=COND_MIN_N,
    output_schema=("percentiles", "states", "n"),
    notes="P(X|state) 的 p10/p25/p50/p75/p90",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "state": ["s"] * 130 + ["t"] * 130,
                "target": [float(i) for i in range(130)] + [float(i) * 2 for i in range(130)],
            },
            "params": {},
            "expect": {"result.states.0": "s"},
        }
    ),
)
def b10_conditional_quantile(data: Any) -> Dict[str, Any]:
    labels, values = H.group_pair(data)
    order: List[str] = []
    bucket: Dict[str, List[float]] = {}
    for g, v in zip(labels, values, strict=False):
        bucket.setdefault(g, [])
        if g not in order:
            order.append(g)
        bucket[g].append(v)
    qs = (10, 25, 50, 75, 90)
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for g in order:
        s = sorted(bucket[g])
        out[g] = {f"p{q}": H.r6(H.quantile(s, q / 100.0)) for q in qs}
    return {"percentiles": out, "states": order, "n": len(values)}


@register(
    "B17",
    name="共现计数",
    group="B",
    layer="D1",
    input_kind="pairs",
    min_n=3,
    output_schema=("count", "total", "ratio", "n"),
    notes="两个布尔条件的交集计数",
)
def b17_cooccurrence(data: Mapping[str, Any]) -> Dict[str, Any]:
    a, b = _two_cats(data)
    n = len(a)
    both = sum(1 for x, y in zip(a, b, strict=False) if _truthy(x) and _truthy(y))
    return {"count": both, "total": n, "ratio": H.r4(both / n) if n else None, "n": n}


def _truthy(v: Any) -> bool:
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "t", "up", "high", "positive")


@register(
    "B18",
    name="频率表",
    group="B",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("freq", "total", "n"),
    notes="类别频次分布",
)
def b18_frequency(data: Any) -> Dict[str, Any]:
    vals = [str(v) for v in _raw(data, "state", "states", "labels", "values", "series")]
    freq: Dict[str, int] = {}
    for v in vals:
        freq[v] = freq.get(v, 0) + 1
    return {"freq": freq, "total": len(vals), "n": len(vals)}


# ======================================================================
# M 组补充
# ======================================================================


@register(
    "M17",
    name="Beta（对基准）",
    group="M",
    layer="D2",
    input_kind="pairs",
    min_n=30,
    output_schema=("beta", "alpha", "r2", "n"),
    notes="x=基准收益、y=资产收益；β=cov(x,y)/var(x)",
)
def m17_beta(data: Mapping[str, Any]) -> Dict[str, Any]:
    xs, ys = H.two(data)
    n = len(xs)
    vx = H.var(xs)
    if vx <= _EPS:
        return {"beta": None, "alpha": None, "r2": None, "n": n}
    mx, my = H.mean(xs), H.mean(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=False)) / (n - 1)
    beta = cov / vx
    r = cov / math.sqrt(vx * H.var(ys)) if H.var(ys) > _EPS else 0.0
    return {"beta": H.r4(beta), "alpha": H.r6(my - beta * mx), "r2": H.r4(r * r), "n": n}


@register(
    "M23",
    name="资产同向率",
    group="M",
    layer="D1",
    input_kind="pairs",
    min_n=10,
    output_schema=("ratio", "up_up", "down_down", "n"),
    notes="同涨同跌（零收益不计）占比",
)
def m23_co_movement(data: Mapping[str, Any]) -> Dict[str, Any]:
    xs, ys = H.two(data)
    pairs = [(a, b) for a, b in zip(xs, ys, strict=False) if a != 0 and b != 0]
    n = len(pairs)
    if not n:
        return {"ratio": None, "up_up": 0, "down_down": 0, "n": 0}
    up = sum(1 for a, b in pairs if a > 0 and b > 0)
    down = sum(1 for a, b in pairs if a < 0 and b < 0)
    return {"ratio": H.r4((up + down) / n), "up_up": up, "down_down": down, "n": n}


# ======================================================================
# R 组：关系表达
# ======================================================================


@register(
    "R08",
    name="分箱单调性（表达）",
    group="R",
    layer="D2",
    input_kind="pairs",
    min_n=COND_MIN_N,
    output_schema=("monotonic", "bins", "rho_bin", "phrase", "n"),
    notes="复用 B11（conditional.b11_monotonic），只补固定句式",
)
def r08_monotonic_phrase(data: Any, k: int = 5, label: str = "该指标") -> Dict[str, Any]:
    out = b11_monotonic(data, k=k)
    mono = out["monotonic"]
    if mono == "increasing":
        phrase = f"{label}越高，后续表现越好（{out['k']} 组严格递增）。"
    elif mono == "decreasing":
        phrase = f"{label}越高，后续表现越差（{out['k']} 组严格递减）。"
    else:
        phrase = f"{label}与后续表现没有单调关系（{out['k']} 组非单调）。"
    return {
        "monotonic": mono,
        "bins": out["bin_means"],
        "rho_bin": out["rho_bin"],
        "phrase": phrase,
        "n": out["n"],
    }


@register(
    "R09",
    name="计数表达",
    group="R",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("up_n", "down_n", "total", "phrase", "n"),
    notes="「历史上 {事件} 后上涨 u 次、下跌 d 次，共 n 次。」",
)
def r09_counts(data: Any, label: str = "该事件") -> Dict[str, Any]:
    xs = H.series(data)
    up = sum(1 for v in xs if v > 0)
    down = sum(1 for v in xs if v < 0)
    total = len(xs)
    phrase = f"历史上「{label}」后上涨 {up} 次、下跌 {down} 次，共 {total} 次。"
    return {"up_n": up, "down_n": down, "total": total, "phrase": phrase, "n": total}


@register(
    "R10",
    name="共现频次（表达）",
    group="R",
    layer="D1",
    input_kind="pairs",
    min_n=3,
    output_schema=("count", "ratio", "phrase", "n"),
    notes="两条件同时发生的次数与占比",
)
def r10_cooccurrence_phrase(data: Mapping[str, Any], label: str = "两条件") -> Dict[str, Any]:
    out = b17_cooccurrence(data)
    ratio_pct = None if out["ratio"] is None else round(out["ratio"] * 100.0, 2)
    phrase = f"「{label}」同时出现 {out['count']} 次，占比 {ratio_pct}%。"
    return {"count": out["count"], "ratio": out["ratio"], "phrase": phrase, "n": out["n"]}


@register(
    "R11",
    name="回撤画像",
    group="R",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("mdd", "duration", "recoveries", "phrase", "n"),
    notes="最大回撤 + 回撤阶段数 + 恢复情况",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [100, 120, 90, 110, 100, 121, 95, 125],
            "params": {},
            "expect": {"result.recoveries": 2},
        }
    ),
)
def r11_drawdown_profile(data: Any, min_dd: float = 0.05) -> Dict[str, Any]:
    xs = H.series(data)
    prof = H.drawdown_profile(xs)
    recoveries = 0
    peak = xs[0]
    in_dd = False
    for p in xs[1:]:
        if p >= peak:
            if in_dd:
                recoveries += 1
                in_dd = False
            peak = p
        elif peak > 0 and 1.0 - p / peak >= min_dd:
            in_dd = True
    mdd_pct = round((prof["mdd"] or 0.0) * 100.0, 2)
    if prof["recovered"]:
        phrase = (
            f"历史最大回撤 {mdd_pct}%，回撤持续 {prof['duration_days']} 天，"
            f"{prof['recovery_days']} 天后收复。"
        )
    else:
        phrase = f"历史最大回撤 {mdd_pct}%，回撤持续 {prof['duration_days']} 天，尚未收复。"
    return {
        "mdd": prof["mdd"],
        "duration": prof["duration_days"],
        "recoveries": recoveries,
        "phrase": phrase,
        "n": prof["n"],
    }


@register(
    "R16",
    name="跨资产同向率（表达）",
    group="R",
    layer="D1",
    input_kind="pairs",
    min_n=10,
    output_schema=("ratio", "phrase", "n"),
)
def r16_comovement_phrase(data: Mapping[str, Any], label: str = "两资产") -> Dict[str, Any]:
    out = m23_co_movement(data)
    pct = None if out["ratio"] is None else round(out["ratio"] * 100.0, 2)
    phrase = f"{label}同涨同跌概率 {pct}%（n={out['n']}）。"
    return {"ratio": out["ratio"], "phrase": phrase, "n": out["n"]}


@register(
    "R17",
    name="水平对比",
    group="R",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("current", "base", "diff", "pct", "percentile", "phrase", "n"),
    notes="当前值 vs 基期（默认首值）与历史分位",
)
def r17_level_compare(
    data: Any, base: Optional[float] = None, label: str = "该指标"
) -> Dict[str, Any]:
    xs = H.series(data)
    cur = xs[-1]
    b = xs[0] if base is None else float(base)
    diff = cur - b
    pct = (cur / b - 1.0) if b != 0 else None
    pctl = 100.0 * sum(1 for v in xs if v <= cur) / len(xs)
    pct_txt = "—" if pct is None else f"{pct * 100:+.2f}%"
    phrase = (
        f"当前 {label} {cur:.4g}，较基准 {b:.4g} {pct_txt}，"
        f"处于近 {len(xs)} 期 {pctl:.0f}% 分位。"
    )
    return {
        "current": H.r6(cur),
        "base": H.r6(b),
        "diff": H.r6(diff),
        "pct": H.r6(pct),
        "percentile": H.r4(pctl),
        "phrase": phrase,
        "n": len(xs),
    }


@register(
    "R03",
    name="日历效应表",
    group="R",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("table", "best", "worst", "counts", "by", "phrase", "n"),
    notes="收益 × 月份/星期（by=month|weekday）；只描述历史分组统计，不含预测措辞",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "returns": [0.001 if i % 7 < 5 else 0.002 for i in range(60)],
                "dates": [f"2024-01-{i % 28 + 1:02d}" for i in range(60)],
            },
            "params": {"by": "weekday"},
            "expect": {"result.by": "weekday"},
        }
    ),
)
def r03_calendar_table(
    data: Any, by: str = "month", dates: Optional[Sequence[Any]] = None, label: str = "该资产"
) -> Dict[str, Any]:
    if by not in ("month", "weekday"):
        raise ValueError("by must be 'month' or 'weekday'")
    ys, ds = _rets_dates(data, dates)
    groups: Dict[int, List[float]] = {}
    for v, d in zip(ys, ds, strict=False):
        key = d.month if by == "month" else d.weekday()
        groups.setdefault(int(key), []).append(v)
    table: List[Dict[str, Any]] = []
    for key in sorted(groups):
        vals = groups[key]
        table.append(
            {
                "key": key,
                "label": f"{key} 月" if by == "month" else _WEEKDAY_LABELS[key],
                "mean": H.r6(H.mean(vals)),
                "median": H.r6(H.median(vals)),
                "win_rate": H.r4(sum(1 for v in vals if v > 0) / len(vals)),
                "up": sum(1 for v in vals if v > 0),
                "down": sum(1 for v in vals if v < 0),
                "n": len(vals),
            }
        )
    best = max(table, key=lambda row: row["mean"])
    worst = min(table, key=lambda row: row["mean"])
    counts = {str(row["key"]): row["n"] for row in table}
    unit = "月" if by == "month" else "星期"
    phrase = (
        f"{label} 近 {len(ys)} 个观测按{unit}统计：{best['label']}平均 "
        f"{best['mean'] * 100:+.2f}%、上涨 {best['up']}/{best['n']} 次（最高），"
        f"最低为 {worst['label']}（{worst['mean'] * 100:+.2f}%）。"
    )
    return {
        "table": table,
        "best": best["key"],
        "worst": worst["key"],
        "counts": counts,
        "by": by,
        "phrase": phrase,
        "n": len(ys),
    }


@register(
    "R04",
    name="事件研究窗",
    group="R",
    layer="D1",
    input_kind="pairs",
    min_n=10,
    output_schema=("ar", "offsets", "car", "n", "events", "pre", "post", "phrase"),
    notes="事件日 × [−pre,+post]；AR=事件窗收益−全样本均值，CAR=ΣAR；门禁按事件数（≥10）",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {"prices": [100.0 + i for i in range(40)], "events": [15, 20, 25] * 4},
            "params": {"pre": 2, "post": 3},
            "expect": {"result.pre": 2, "result.post": 3},
        }
    ),
)
def r04_event_window(
    data: Mapping[str, Any], pre: int = 5, post: int = 10, dates: Optional[Sequence[Any]] = None
) -> Dict[str, Any]:
    if pre < 0 or post < 0:
        raise ValueError("pre/post must be >= 0")
    prices = H.series(data, "prices", "price", "series", "values")
    idx = _event_indices(data, dates)
    n = len(prices)
    rets = [0.0] + [
        (prices[i] / prices[i - 1] - 1.0) if prices[i - 1] else 0.0 for i in range(1, n)
    ]
    baseline = H.mean(rets[1:]) if n > 1 else 0.0
    offsets = list(range(-pre, post + 1))
    ar: List[Optional[float]] = []
    for k in offsets:
        vals = [rets[i + k] - baseline for i in idx if 0 <= i + k < n]
        ar.append(H.r6(H.mean(vals)) if vals else None)
    car = H.r6(sum(v for v in ar if v is not None))
    used = sum(1 for i in idx if i - pre >= 0 and i + post <= n - 1)
    phrase = (
        f"「事件」共 {len(idx)} 次，其中 {used} 次窗口完整；"
        f"窗口 [−{pre},+{post}] 累计异常收益 CAR={car * 100:+.2f}%（n={used}）。"
    )
    return {
        "ar": ar,
        "offsets": offsets,
        "car": car,
        "n": used,
        "events": len(idx),
        "pre": pre,
        "post": post,
        "phrase": phrase,
    }


def _event_indices(data: Mapping[str, Any], dates: Optional[Sequence[Any]] = None) -> List[int]:
    """事件定位：直接给下标，或给事件日期（配合 dates 轴）。"""
    raw = data.get("events", data.get("event_index"))
    if raw is not None:
        return sorted({int(v) for v in raw})
    ev_dates = data.get("event_dates")
    axis = dates if dates is not None else data.get("dates")
    if ev_dates is None or axis is None:
        raise ValueError("event study needs data.events (index) or event_dates + dates")
    pos = {_parse_one(d).strftime("%Y-%m-%d"): i for i, d in enumerate(axis)}
    out = []
    for d in ev_dates:
        key = _parse_one(d).strftime("%Y-%m-%d")
        if key in pos:
            out.append(pos[key])
    return sorted(set(out))


@register(
    "R05",
    name="相关矩阵 TopK",
    group="R",
    layer="D2",
    input_kind="panel",
    min_n=60,
    output_schema=("pairs", "rho", "top", "phrase", "n"),
    notes="复用 M06（冻结口径）：面板收益 → 全对相关，按 |ρ| 降序；rho 为 Top1",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "series": {
                    "A": [float(i) for i in range(60)],
                    "B": [2.0 * i for i in range(60)],
                    "C": [float((i * 37) % 11) for i in range(60)],
                }
            },
            "params": {"k": 2},
            "expect": {"result.rho": 1.0},
        }
    ),
)
def r05_corr_topk(data: Mapping[str, Any], k: int = 3, base: str = "") -> Dict[str, Any]:
    panel = data.get("series") if isinstance(data, Mapping) else None
    if not isinstance(panel, Mapping) or len(panel) < 2:
        return {
            "pairs": [],
            "rho": None,
            "top": [],
            "phrase": "资产不足 2 个，无法计算相关性。",
            "n": 0,
        }
    out = m06_topk(data, k=k, base=base)
    pairs = [
        {
            "a": p["a"],
            "b": p["b"],
            "rho": p["r"],
            "p": p["p"],
            "q": p.get("q"),
            "significant": p.get("significant"),
            "n": p["n"],
        }
        for p in out["pairs"]
    ]
    top = pairs[: max(1, int(k))]
    return {
        "pairs": pairs,
        "rho": top[0]["rho"],
        "top": top,
        "phrase": out["phrase"],
        "n": out["n"],
    }


@register(
    "R06",
    name="领先滞后",
    group="R",
    layer="D2",
    input_kind="pairs",
    min_n=60,
    output_schema=("best_lag", "best_rho", "ccf", "lags", "n", "phrase"),
    notes="复用 M11/M12：ccf(k)=corr(x[t],y[t+k])，k>0 表示 x 领先 y；最大滞后默认 ±10",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "x": [math.sin(i * 0.7) for i in range(80)],
                "y": [0.0] + [math.sin(i * 0.7) for i in range(79)],
            },
            "params": {"max_lag": 5},
            "expect": {"result.best_lag": 1},
        }
    ),
)
def r06_lead_lag(
    data: Mapping[str, Any], max_lag: int = 10, label_x: str = "序列X", label_y: str = "序列Y"
) -> Dict[str, Any]:
    if "x" not in data or "y" not in data:
        xs, ys = H.two(data)
        data = {"x": xs, "y": ys}
    ccf = m11_ccf(data, max_lag=max_lag)
    best = m12_best_lag(data, max_lag=max_lag)
    lag = int(best["lag"])
    if lag > 0:
        direction = f"{label_x} 领先 {label_y} {lag} 期"
    elif lag < 0:
        direction = f"{label_y} 领先 {label_x} {-lag} 期"
    else:
        direction = f"{label_x} 与 {label_y} 同期"
    phrase = (
        f"交叉相关峰值 lag={lag}（ρ={best['r']:+.3f}），{direction}"
        f"（滞后范围 ±{max_lag}，n={ccf['sample_n']}）。"
    )
    return {
        "best_lag": lag,
        "best_rho": best["r"],
        "ccf": ccf["r"],
        "lags": ccf["lags"],
        "n": ccf["sample_n"],
        "phrase": phrase,
    }


@register(
    "R07",
    name="状态转移",
    group="R",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("states", "matrix", "next_dist", "next_state", "phrase", "n"),
    notes="P(s_{t+1}|s_t) 行随机；next_dist 取最近状态那一行",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": ["a", "a", "b", "a", "a", "b"] * 10,
            "params": {},
            "expect": {"result.states.0": "a"},
        }
    ),
)
def r07_state_transition(data: Any) -> Dict[str, Any]:
    labels = [str(v) for v in _raw(data, "state", "states", "labels", "series", "values")]
    out = _transition(labels)
    order, matrix = out["states"], out["matrix"]
    last = labels[-1] if labels else None
    next_dist: Dict[str, Optional[float]] = {}
    next_state = None
    if last is not None and last in order:
        row = matrix[order.index(last)]
        next_dist = {order[j]: row[j] for j in range(len(order)) if row[j] is not None}
        if next_dist:
            next_state = max(next_dist, key=lambda key_: next_dist[key_])
    desc = "、".join(f"{k}({v:.2f})" for k, v in sorted(next_dist.items(), key=lambda kv: -kv[1]))
    phrase = (
        f"最近状态「{last}」之后，历史分布为：{desc}（共 {out['n']} 个状态点）。"
        if last is not None
        else "状态序列为空。"
    )
    return {
        "states": order,
        "matrix": matrix,
        "next_dist": next_dist,
        "next_state": next_state,
        "phrase": phrase,
        "n": out["n"],
    }


@register(
    "R12",
    name="极值后表现",
    group="R",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("fwd_dist", "n", "events", "horizon", "lookback", "phrase"),
    notes="极值事件=创历史新高（lookback>0 时改判窗口内新高）；fwd 为事件后 h 日收益分布",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [100.0 * (1.0 + 0.01) ** i for i in range(40)],
            "params": {"horizon": 5},
            "expect": {"result.fwd_dist.win_rate": 1.0},
        }
    ),
)
def r12_extreme_forward(data: Any, horizon: int = 10, lookback: int = 0) -> Dict[str, Any]:
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    prices = H.series(data)
    n = len(prices)
    events = [
        i
        for i in range(1, n)
        if prices[i] > max(prices[max(0, i - lookback) if lookback > 0 else 0 : i])
    ]
    fwd = [
        prices[i + horizon] / prices[i] - 1.0 for i in events if i + horizon < n and prices[i] != 0
    ]
    if fwd:
        s = sorted(fwd)
        dist: Dict[str, Optional[float]] = {
            "mean": H.r6(H.mean(fwd)),
            "median": H.r6(H.median(s)),
            "win_rate": H.r4(sum(1 for v in fwd if v > 0) / len(fwd)),
            "p10": H.r6(H.quantile(s, 0.10)),
            "p90": H.r6(H.quantile(s, 0.90)),
            "std": H.r6(H.std(fwd)),
        }
    else:
        dist = dict.fromkeys(("mean", "median", "win_rate", "p10", "p90", "std"))
    win = None if dist["win_rate"] is None else dist["win_rate"] * 100.0
    mean = None if dist["mean"] is None else dist["mean"] * 100.0
    phrase = (
        f"历史「新高」事件 {len(events)} 次，其后 {horizon} 日上涨 {win:.1f}%、"
        f"均值 {mean:+.2f}%（有效 n={len(fwd)}）。"
        if fwd
        else f"历史「新高」事件 {len(events)} 次，无完整 {horizon} 日后验数据。"
    )
    return {
        "fwd_dist": dist,
        "n": len(fwd),
        "events": len(events),
        "horizon": horizon,
        "lookback": lookback,
        "phrase": phrase,
    }


@register(
    "R13",
    name="波动率状态→收益",
    group="R",
    layer="D2",
    input_kind="pairs",
    min_n=COND_MIN_N,
    output_schema=("buckets", "spread", "k", "phrase", "n"),
    notes="波动率分位等频分桶 × 前瞻收益（fwd 由 align.forward_returns 生成）；spread=最高组−最低组",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "vol": [float(i) for i in range(300)],
                "target": [0.001 * i for i in range(300)],
            },
            "params": {"k": 5},
            "expect": {"result.k": 5},
        }
    ),
)
def r13_vol_regime(data: Mapping[str, Any], k: int = 5) -> Dict[str, Any]:
    if k < 2:
        raise ValueError("k must be >= 2")
    vol, target = _vol_target(data)
    edges, ids = H.bucket(vol, k)
    buckets: List[Dict[str, Any]] = []
    for b in range(k):
        vals = [t for t, i in zip(target, ids, strict=False) if i == b]
        buckets.append(
            {
                "bucket": b,
                "lo": H.r6(edges[b]),
                "hi": H.r6(edges[b + 1]),
                "mean": H.r6(H.mean(vals)) if vals else None,
                "median": H.r6(H.median(vals)) if vals else None,
                "win_rate": H.r4(sum(1 for v in vals if v > 0) / len(vals)) if vals else None,
                "n": len(vals),
            }
        )
    top, bottom = buckets[-1]["mean"], buckets[0]["mean"]
    spread = None if (top is None or bottom is None) else H.r6(top - bottom)
    phrase = (
        f"波动率分 {k} 组：最高波动组均值 {top * 100:+.2f}%、最低组 {bottom * 100:+.2f}%，"
        f"价差 {spread * 100:+.2f} 个百分点（n={len(target)}）。"
        if spread is not None
        else f"波动率分 {k} 组，样本不足无法比较。"
    )
    return {"buckets": buckets, "spread": spread, "k": k, "phrase": phrase, "n": len(target)}


def _vol_target(data: Mapping[str, Any]) -> Tuple[List[float], List[float]]:
    for a, b in (("vol", "target"), ("volatility", "target"), ("vol", "fwd")):
        if a in data and b in data:
            xs, ys = H.floats(data[a]), H.floats(data[b])
            n = min(len(xs), len(ys))
            if n < 3:
                raise ValueError("need at least 3 paired points")
            return xs[:n], ys[:n]
    return H.two(data)


@register(
    "R14",
    name="相关性突变",
    group="R",
    layer="D2",
    input_kind="pairs",
    min_n=60,
    output_schema=(
        "z",
        "current",
        "history_avg",
        "history_std",
        "window",
        "is_anomaly",
        "phrase",
        "n",
    ),
    notes="当前滚动相关对前期窗口的 z-score（复用 M04 滚动口径）；|z|≥threshold 记为异常",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "x": [math.sin(i * 0.7) for i in range(120)],
                "y": [math.sin(i * 0.7) if i < 60 else -math.sin(i * 0.7) for i in range(120)],
            },
            "params": {"window": 20, "threshold": 2.0},
            "expect": {"result.window": 20},
        }
    ),
)
def r14_corr_jump(
    data: Mapping[str, Any], window: int = 30, threshold: float = 2.0
) -> Dict[str, Any]:
    roll = m04_rolling(data, window=window)
    rs = [r for r in roll["r"] if r is not None]
    if len(rs) < 6:
        return {
            "z": None,
            "current": None,
            "history_avg": None,
            "history_std": None,
            "window": window,
            "is_anomaly": None,
            "phrase": "滚动窗口不足，无法判断。",
            "n": roll["sample_n"],
        }
    current, hist = rs[-1], rs[:-1]
    mu, sd = H.mean(hist), H.std(hist)
    z = 0.0 if sd <= _EPS else (current - mu) / sd
    anomaly = abs(z) >= threshold
    phrase = (
        f"当前滚动相关 {current:+.3f}，历史均值 {mu:+.3f}（σ={sd:.3f}），"
        f"z={z:+.2f}，{'触发' if anomaly else '未触发'}突变阈值 {threshold}（窗口 {window}）。"
    )
    return {
        "z": H.r4(z),
        "current": H.r6(current),
        "history_avg": H.r6(mu),
        "history_std": H.r6(sd),
        "window": window,
        "is_anomaly": bool(anomaly),
        "phrase": phrase,
        "n": roll["sample_n"],
    }


@register(
    "R15",
    name="季节性一致率",
    group="R",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=("consistency", "table", "years", "phrase", "n"),
    notes="复用 C14 冻结口径：按年×月聚合成月收益后，统计同月跨年同向比例（consistency[12]）",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "returns": [0.01] * 120,
                "dates": [
                    f"{2023 + i // 60}-{m:02d}-{15 if i % 2 else 20}"
                    for i, m in enumerate(list(range(1, 13)) * 10)
                ],
            },
            "params": {},
            "expect": {"result.years": 2, "result.consistency.0": 1.0},
        }
    ),
)
def r15_season_consistency(
    data: Any, dates: Optional[Sequence[Any]] = None, label: str = "该资产"
) -> Dict[str, Any]:
    out = c14_month_consistency(data, dates=dates)
    table = out["table"]
    by_month = {int(row["month"]): row for row in table}
    consistency = [by_month[m]["consistency"] if m in by_month else None for m in range(1, 13)]
    years = max((row["years"] for row in table), default=0)
    valid = [(row["month"], row["consistency"]) for row in table]
    if valid:
        best = max(valid, key=lambda t: t[1])
        worst = min(valid, key=lambda t: t[1])
        phrase = (
            f"{label} 同月跨年一致率：最高 {best[0]} 月 {best[1] * 100:.0f}%，"
            f"最低 {worst[0]} 月 {worst[1] * 100:.0f}%（覆盖 {years} 年）。"
        )
    else:
        phrase = f"{label} 无足够月度样本计算一致率。"
    return {
        "consistency": consistency,
        "table": table,
        "years": years,
        "phrase": phrase,
        "n": out["n"],
    }


def _utc_day(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%d")
    return _parse_one(value).strftime("%Y-%m-%d")


def _r18_daily(entries: Any, shared_dates: Optional[Sequence[Any]]) -> Dict[str, float]:
    """单资产 → {UTC 日: 收盘}：同日取最后观测，跨源重复按 source 字典序保留最小者。"""
    rows: List[Tuple[str, str, float]] = []
    if isinstance(entries, Mapping):
        for key, val in entries.items():
            rows.append((_utc_day(key), "", float(val)))
    else:
        seq = list(entries)
        if shared_dates is not None and seq and not isinstance(seq[0], (tuple, list, Mapping)):
            for day, val in zip(shared_dates, seq, strict=False):
                rows.append((_utc_day(day), "", float(val)))
        else:
            for item in seq:
                if isinstance(item, Mapping):
                    rows.append(
                        (
                            _utc_day(item.get("ts", item.get("timestamp"))),
                            str(item.get("source", "")),
                            float(item.get("value")),
                        )
                    )
                elif isinstance(item, (int, float)):
                    raise ValueError("R18 裸数值序列需要配套 data.dates 时间轴")
                elif len(item) == 2:
                    rows.append((_utc_day(item[0]), "", float(item[1])))
                else:
                    rows.append((_utc_day(item[1]), str(item[0]), float(item[2])))
    best_src: Dict[str, str] = {}
    for day, src, _val in rows:
        if day not in best_src or src < best_src[day]:
            best_src[day] = src
    out: Dict[str, float] = {}
    for day, src, val in rows:  # 输入按时间升序 → 后写覆盖 = 当日收盘
        if src == best_src[day]:
            out[day] = val
    return dict(sorted(out.items()))


@register(
    "R18",
    name="时空对齐切片",
    group="R",
    layer="D1",
    input_kind="panel",
    min_n=30,
    output_schema=(
        "window_rows",
        "window",
        "assets",
        "align_method",
        "timezone",
        "max_stale_days",
        "n",
    ),
    notes="对齐原语：UTC 日收盘（同日取最后）+ 跨源去重（source 字典序最小）+ ffill（超 stale 上限即缺失）",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "series": {
                    "A": [("binance", 1700000000 + i * 86400, 100.0 + i) for i in range(40)],
                    "B": [("coinbase", 1700000000 + i * 86400, 50.0 + i) for i in range(40)],
                }
            },
            "params": {},
            "expect": {"result.align_method": "daily_last+ffill"},
        }
    ),
)
def r18_alignment_slice(
    data: Mapping[str, Any],
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    window: Optional[int] = None,
    max_stale_days: int = 3,
) -> Dict[str, Any]:
    panel = data.get("series") if "series" in data else data.get("panel")
    if not isinstance(panel, Mapping) or not panel:
        raise ValueError("R18 需要 data.series / data.panel（资产 → 带时间戳的序列）")
    shared = data.get("dates")
    daily = {str(asset): _r18_daily(vals, shared) for asset, vals in panel.items()}
    all_days = sorted({day for s in daily.values() for day in s})
    if not all_days:
        raise ValueError("R18 输入无有效日期")
    first = datetime.strptime(all_days[0], "%Y-%m-%d").toordinal()
    last = datetime.strptime(all_days[-1], "%Y-%m-%d").toordinal()
    if start is not None:
        first = max(first, datetime.strptime(_utc_day(start), "%Y-%m-%d").toordinal())
    if end is not None:
        last = min(last, datetime.strptime(_utc_day(end), "%Y-%m-%d").toordinal())
    if window is not None:
        first = max(first, last - int(window) + 1)
    if last < first:
        raise ValueError("R18 时间窗为空（start/end/window 与序列无交集）")
    axis = [datetime.fromordinal(o).strftime("%Y-%m-%d") for o in range(first, last + 1)]
    cap = int(max_stale_days)

    window_rows: List[Dict[str, Any]] = []
    for asset, series in daily.items():
        pts: List[Tuple[str, Optional[float], bool]] = []
        last_val: Optional[float] = None
        last_ord: Optional[int] = None
        for day in axis:
            ord_day = datetime.strptime(day, "%Y-%m-%d").toordinal()
            if day in series:
                last_val, last_ord = series[day], ord_day
                pts.append((day, last_val, True))
            elif last_ord is None or (ord_day - last_ord) > cap:
                continue
            else:
                pts.append((day, last_val, False))
        if not pts:
            window_rows.append(
                {
                    "asset": asset,
                    "start_value": None,
                    "end_value": None,
                    "ret": None,
                    "n_obs": 0,
                    "stale_ratio": None,
                    "first_date": None,
                    "last_date": None,
                }
            )
            continue
        start_v, end_v = pts[0][1], pts[-1][1]
        ret = (end_v / start_v - 1.0) if start_v else None
        n_obs = sum(1 for p in pts if p[2])
        window_rows.append(
            {
                "asset": asset,
                "start_value": H.r6(start_v),
                "end_value": H.r6(end_v),
                "ret": H.r6(ret),
                "n_obs": n_obs,
                "stale_ratio": H.r4(1.0 - n_obs / len(pts)),
                "first_date": pts[0][0],
                "last_date": pts[-1][0],
            }
        )
    window_rows.sort(key=lambda row: row["asset"])
    return {
        "window_rows": window_rows,
        "window": f"{axis[0]}~{axis[-1]}",
        "assets": sorted(daily),
        "align_method": "daily_last+ffill",
        "timezone": "UTC",
        "max_stale_days": cap,
        "n": len(axis),
    }
