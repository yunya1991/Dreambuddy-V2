# -*- coding: utf-8 -*-
"""S3 批（条件收益 / IC / 分组）：S11/S25/S26、F01–F06、B01–B03/B05/B11–B16、H01、R01/R02。

口径纪律（METHOD_LIBRARY §14 S3 + §16）：
  - **门禁分层**：分布/收益类 `min_n=30`，条件收益/IC/分组类 `min_n=250`
    （与 §14「S3 需 ≥250 对齐点」一致，不足即 `insufficient_samples`）；
  - **前瞻收益唯一实现** = `l1agg.align.forward_returns`：B13/B14/B16/R02 只消费
    已对齐的 target，不自行位移、不重复实现；
  - **B15 复用冻结实现** `persistence.metrics.ic_decay`（重叠 + h 个相位非重叠），
    禁止在本批另写一份口径；
  - p 值统一走 t 分布（`stats_core.t_two_sided_p`），`p<0.05` 只表述为显著，不表述为因果；
  - 只接收已对齐等长序列（`l1agg.align.align` 产物），不取数、不写库、无随机数。
"""

from __future__ import annotations

import bisect
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

from l1agg.align import forward_returns, simple_returns
from l1agg.persistence._stats import pearson, spearman
from l1agg.persistence.metrics import ic_decay

from .registry import MethodChecks, register
from .stats_core import corr_p, t_two_sided_p

DIST_MIN_N = 30  # 单维分布/收益描述
COND_MIN_N = 250  # 条件收益 / IC / 分组（§14 S3 门禁）
EPS = 1e-12


# ============================================================
# 输入契约（只接受已对齐等长序列）
# ============================================================


def _floats(seq: Sequence[Any]) -> List[float]:
    return [float(v) for v in seq]


def _series(data: Any) -> List[float]:
    """单序列：list 或 {"series"/"values"/"price"/"prices"/"indicator"}。"""
    if isinstance(data, Mapping):
        for key in ("series", "values", "price", "prices", "indicator", "x"):
            if key in data:
                return _floats(data[key])
        raise ValueError("series data must contain one of series/values/price/prices/indicator")
    return _floats(data)


def _two(data: Mapping[str, Any]) -> tuple[List[float], List[float]]:
    """等长双序列：x/y 或 factor/target 或 factor/price 或 indicator/price。"""
    for a, b in (
        ("x", "y"),
        ("factor", "target"),
        ("factor", "price"),
        ("indicator", "price"),
    ):
        if a in data and b in data:
            xs, ys = _floats(data[a]), _floats(data[b])
            n = min(len(xs), len(ys))
            if n < 3:
                raise ValueError("need at least 3 paired points")
            return xs[:n], ys[:n]
    raise ValueError("paired data must contain x/y, factor/target or factor/price")


def _quantile_sorted(sorted_vals: Sequence[float], q: float) -> float:
    """线性插值分位（与 numpy.percentile(method="linear") 同口径）。"""
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
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def _median(sorted_vals: Sequence[float]) -> float:
    return _quantile_sorted(sorted_vals, 0.5)


def _std(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mu = _mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))


def _group_stats(values: Sequence[float]) -> Dict[str, Any]:
    """组内描述统计（R01/B05 共用）：均值/中位/胜率/t。"""
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "win_rate": None, "t": None, "p": None}
    mu = _mean(values)
    sd = _std(values)
    t = None if (n < 2 or sd <= EPS) else mu / (sd / math.sqrt(n))
    return {
        "n": n,
        "mean": round(mu, 6),
        "median": round(_median(sorted(values)), 6),
        "win_rate": round(sum(1 for v in values if v > 0) / n, 6),
        "t": None if t is None else round(t, 3),
        "p": t_two_sided_p(t, n - 1) if t is not None else None,
    }


# ============================================================
# S11 / S25 / S26 单维分布
# ============================================================


@register(
    "S11",
    name="分位（线性插值）",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=DIST_MIN_N,
    output_schema=("p1", "p5", "p10", "p25", "p50", "p75", "p90", "p95", "p99", "n"),
    notes="与 numpy.percentile(method='linear') 同口径",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [float(i) for i in range(30)],
            "params": {},
            "expect": {"result.p50": 14.5, "result.p1": 0.29, "result.n": 30},
        },
        reference=lambda data: {
            "result.p50": float(__import__("numpy").percentile(data, 50)),
            "result.p99": float(__import__("numpy").percentile(data, 99)),
        },
    ),
)
def s11_percentiles(data, **_: Any) -> Dict[str, Any]:
    values = sorted(_series(data))
    qs = (1, 5, 10, 25, 50, 75, 90, 95, 99)
    out: Dict[str, Any] = {f"p{q}": round(_quantile_sorted(values, q / 100.0), 6) for q in qs}
    out["n"] = len(values)
    return out


@register(
    "S25",
    name="历史分位",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=DIST_MIN_N,
    output_schema=("value", "percentile", "n"),
    notes="percentile = 100 × count(X ≤ x_last) / n（PIT 无未来函数）",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [float(i) for i in range(30)],
            "params": {},
            "expect": {"result.percentile": 100.0, "result.value": 29.0},
        },
    ),
)
def s25_percentile(data, **_: Any) -> Dict[str, Any]:
    values = _series(data)
    last = values[-1]
    return {
        "value": round(last, 6),
        "percentile": round(100.0 * sum(1 for v in values if v <= last) / len(values), 4),
        "n": len(values),
    }


@register(
    "S26",
    name="z-score（winsorize p1/p99）",
    group="S",
    layer="D1",
    input_kind="series",
    min_n=DIST_MIN_N,
    output_schema=("z", "mean", "std", "n", "winsorized"),
    notes="先按 p1/p99 截断再算 μ/σ，z 取末点（D-A05 口径）",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [float(i) for i in range(30)],
            "params": {},
            "expect": {"result.mean": 14.5, "result.n": 30},
        },
    ),
)
def s26_zscore(data, **_: Any) -> Dict[str, Any]:
    values = _series(data)
    s = sorted(values)
    lo, hi = _quantile_sorted(s, 0.01), _quantile_sorted(s, 0.99)
    wins = [min(max(v, lo), hi) for v in values]
    mu, sd = _mean(wins), _std(wins)
    return {
        "z": None if sd <= EPS else round((values[-1] - mu) / sd, 6),
        "mean": round(mu, 6),
        "std": round(sd, 6),
        "n": len(values),
        "winsorized": True,
    }


# ============================================================
# F01–F06 收益与风险
# ============================================================


@register(
    "F01",
    name="简单收益",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=DIST_MIN_N,
    output_schema=("r", "mean", "std", "n"),
    notes="复用 align.simple_returns（r_t=P_t/P_{t-1}−1，首点丢弃）",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [100.0 * (1.1**i) for i in range(30)],
            "params": {},
            "expect": {"result.mean": 0.1, "result.n": 30},
        },
    ),
)
def f01_simple_return(data, **_: Any) -> Dict[str, Any]:
    values = _series(data)
    rs = simple_returns(values)
    return {
        "r": [round(r, 6) for r in rs],
        "mean": round(_mean(rs), 6),
        "std": round(_std(rs), 6),
        "n": len(values),
    }


@register(
    "F02",
    name="对数收益",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=DIST_MIN_N,
    output_schema=("lr", "mean", "std", "n"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [100.0 * (1.1**i) for i in range(30)],
            "params": {},
            "expect": {"result.mean": 0.0953102, "result.n": 30},
        },
    ),
)
def f02_log_return(data, **_: Any) -> Dict[str, Any]:
    values = _series(data)
    lrs = [
        0.0 if (a <= 0 or b <= 0) else math.log(b / a)
        for a, b in zip(values, values[1:], strict=False)
    ]
    return {
        "lr": [round(v, 6) for v in lrs],
        "mean": round(_mean(lrs), 6),
        "std": round(_std(lrs), 6),
        "n": len(values),
    }


@register(
    "F03",
    name="区间收益",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("ret", "start", "end", "n"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [100.0] * 15 + [200.0] * 15,
            "params": {},
            "expect": {"result.ret": 1.0, "result.n": 30},
        },
    ),
)
def f03_interval_return(data, **_: Any) -> Dict[str, Any]:
    values = _series(data)
    first, last = values[0], values[-1]
    return {
        "ret": None if first == 0 else round(last / first - 1.0, 6),
        "start": round(first, 6),
        "end": round(last, 6),
        "n": len(values),
    }


@register(
    "F04",
    name="年化收益",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=DIST_MIN_N,
    output_schema=("ann", "mean_daily", "n"),
    notes="(1+日均收益)^365 − 1；仅描述历史，不外推",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [100.0 * (1.001**i) for i in range(30)],
            "params": {},
            "expect": {"result.mean_daily": 0.001, "result.n": 30},
        },
    ),
)
def f04_annualized_return(data, **_: Any) -> Dict[str, Any]:
    values = _series(data)
    mu = _mean(simple_returns(values))
    return {
        "ann": round((1.0 + mu) ** 365 - 1.0, 6),
        "mean_daily": round(mu, 6),
        "n": len(values),
    }


@register(
    "F05",
    name="年化波动率",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=DIST_MIN_N,
    output_schema=("vol", "mean_ret", "n"),
    notes="σ(日简单收益) × √365",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [100.0 * (1.1**i) for i in range(30)],
            "params": {},
            "expect": {"result.vol": 0.0, "result.n": 30},
        },
    ),
)
def f05_annualized_vol(data, **_: Any) -> Dict[str, Any]:
    values = _series(data)
    rs = simple_returns(values)
    return {
        "vol": round(_std(rs) * math.sqrt(365.0), 6),
        "mean_ret": round(_mean(rs), 6),
        "n": len(values),
    }


@register(
    "F06",
    name="夏普比率",
    group="F",
    layer="D2",
    input_kind="series",
    min_n=DIST_MIN_N,
    output_schema=("sharpe", "ann_ret", "ann_vol", "rf", "n"),
    notes="(年化收益 − rf) / 年化波动；波动为 0 时返回 null",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [100.0 * (1.1**i) for i in range(30)],
            "params": {},
            "expect": {"result.sharpe": None, "result.n": 30},
        },
    ),
)
def f06_sharpe(data, rf: float = 0.0, **_: Any) -> Dict[str, Any]:
    values = _series(data)
    rs = simple_returns(values)
    mu = _mean(rs)
    vol = _std(rs) * math.sqrt(365.0)
    ann = (1.0 + mu) ** 365 - 1.0
    return {
        "sharpe": None if vol <= EPS else round((ann - float(rf)) / vol, 6),
        "ann_ret": round(ann, 6),
        "ann_vol": round(vol, 6),
        "rf": float(rf),
        "n": len(values),
    }


# ============================================================
# B01–B03 分箱
# ============================================================


@register(
    "B01",
    name="等宽分箱",
    group="B",
    layer="D1",
    input_kind="series",
    min_n=DIST_MIN_N,
    output_schema=("edges", "counts", "bin", "k", "n"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [float(i) for i in range(30)],
            "params": {"k": 10},
            "expect": {"result.counts.0": 3, "result.counts.9": 3, "result.k": 10},
        },
    ),
)
def b01_width_bins(data, k: int = 10, **_: Any) -> Dict[str, Any]:
    values = _series(data)
    if k < 2:
        raise ValueError("k must be >= 2")
    lo, hi = min(values), max(values)
    width = (hi - lo) / k if hi > lo else 1.0
    edges = [lo + width * i for i in range(k + 1)]
    counts = [0] * k
    for v in values:
        counts[min(int((v - lo) / width), k - 1)] += 1
    return {
        "edges": [round(e, 6) for e in edges],
        "counts": counts,
        "bin": min(int((values[-1] - lo) / width), k - 1),
        "k": k,
        "n": len(values),
    }


@register(
    "B02",
    name="等频分箱（分位）",
    group="B",
    layer="D1",
    input_kind="series",
    min_n=DIST_MIN_N,
    output_schema=("edges", "counts", "bucket", "k", "n"),
    notes="edges 用线性插值分位；左闭右开，末桶闭合",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [float(i) for i in range(30)],
            "params": {"k": 5},
            "expect": {"result.counts.0": 6, "result.k": 5, "result.bucket": 4},
        },
    ),
)
def b02_quantile_bins(data, k: int = 5, **_: Any) -> Dict[str, Any]:
    values = _series(data)
    if k < 2:
        raise ValueError("k must be >= 2")
    s = sorted(values)
    edges = [_quantile_sorted(s, i / k) for i in range(k + 1)]
    inner = edges[1:-1]
    counts = [0] * k
    for v in values:
        counts[min(bisect.bisect_right(inner, v), k - 1)] += 1
    return {
        "edges": [round(e, 6) for e in edges],
        "counts": counts,
        "bucket": min(bisect.bisect_right(inner, values[-1]), k - 1),
        "k": k,
        "n": len(values),
    }


@register(
    "B03",
    name="固定阈值分档",
    group="B",
    layer="D1",
    input_kind="series",
    min_n=1,
    output_schema=("level", "label", "counts", "thresholds", "n"),
    notes="如恐惧贪婪 0–25/26–50/…；阈值由参数给出，不写死在数据里",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [float(i) for i in range(101)],
            "params": {"thresholds": (25, 50, 75)},
            "expect": {"result.level": 3, "result.n": 101},
        },
    ),
)
def b03_threshold_levels(
    data, thresholds: Sequence[float] = (25, 50, 75), **_: Any
) -> Dict[str, Any]:
    values = _series(data)
    th = sorted(float(t) for t in thresholds)
    if not th:
        raise ValueError("thresholds must not be empty")
    counts = [0] * (len(th) + 1)
    for v in values:
        counts[min(bisect.bisect_right(th, v), len(th))] += 1
    level = min(bisect.bisect_right(th, values[-1]), len(th))
    if level == 0:
        label = f"<{th[0]:g}"
    elif level == len(th):
        label = f">={th[-1]:g}"
    else:
        label = f"{th[level - 1]:g}~{th[level]:g}"
    return {
        "level": level,
        "label": label,
        "counts": counts,
        "thresholds": th,
        "n": len(values),
    }


# ============================================================
# B05 / B11–B16 条件分组与 IC
# ============================================================


@register(
    "B05",
    name="条件分组统计",
    group="B",
    layer="D2",
    input_kind="pairs",
    min_n=COND_MIN_N,
    output_schema=("table", "n"),
    notes="state × target → 每组 均值/中位/胜率/次数/t（配 R01 表达）",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "state": [str(i % 2) for i in range(300)],
                "target": [0.01 if i % 2 else -0.01 for i in range(300)],
            },
            "params": {},
            "expect": {"result.table.1.mean": 0.01, "result.table.0.mean": -0.01},
        },
    ),
)
def b05_conditional(data, **_: Any) -> Dict[str, Any]:
    if "state" not in data or "target" not in data:
        raise ValueError("B05 needs data.state and data.target")
    states = list(data["state"])[: len(data["target"])]
    targets = _floats(data["target"])[: len(states)]
    groups: Dict[str, List[float]] = {}
    for s, t in zip(states, targets, strict=False):
        groups.setdefault(str(s), []).append(t)
    table = [dict(state=k, **_group_stats(v)) for k, v in groups.items()]
    return {"table": table, "n": len(targets)}


def _bucket_by_quantile(
    factor: Sequence[float], target: Sequence[float], k: int
) -> List[Dict[str, Any]]:
    edges = [_quantile_sorted(sorted(factor), i / k) for i in range(k + 1)]
    inner = edges[1:-1]
    buckets: List[List[float]] = [[] for _ in range(k)]
    for f, t in zip(factor, target, strict=False):
        buckets[min(bisect.bisect_right(inner, f), k - 1)].append(t)
    return [
        dict(bucket=i, lo=round(edges[i], 6), hi=round(edges[i + 1], 6), **_group_stats(vals))
        for i, vals in enumerate(buckets)
    ]


@register(
    "B16",
    name="分组回测统计",
    group="B",
    layer="D2",
    input_kind="pairs",
    min_n=COND_MIN_N,
    output_schema=("table", "spread", "k", "n"),
    notes="factor 分位分组 → target 组内均值/胜率；spread = 最高组 − 最低组（描述性，非策略收益）",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "factor": [float(i) for i in range(300)],
                "target": [0.001 * i for i in range(300)],
            },
            "params": {"k": 5},
            "expect": {"result.spread": 0.24, "result.k": 5},
        },
    ),
)
def b16_group_stats(data, k: int = 5, **_: Any) -> Dict[str, Any]:
    factor, target = _two(data)
    if k < 2:
        raise ValueError("k must be >= 2")
    table = _bucket_by_quantile(factor, target, k)
    top, bottom = table[-1]["mean"], table[0]["mean"]
    spread = None if (top is None or bottom is None) else round(top - bottom, 6)
    return {"table": table, "spread": spread, "k": k, "n": len(target)}


@register(
    "B12",
    name="分箱收益梯度",
    group="B",
    layer="D2",
    input_kind="pairs",
    min_n=COND_MIN_N,
    output_schema=("spread", "spread_pp", "k", "n"),
    notes="同 B16 的价差，额外给百分点写法",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "factor": [float(i) for i in range(300)],
                "target": [0.001 * i for i in range(300)],
            },
            "params": {"k": 5},
            "expect": {"result.spread": 0.24, "result.spread_pp": 24.0},
        },
    ),
)
def b12_gradient(data, k: int = 5, **_: Any) -> Dict[str, Any]:
    out = b16_group_stats(data, k=k)
    return {
        "spread": out["spread"],
        "spread_pp": None if out["spread"] is None else round(out["spread"] * 100.0, 4),
        "k": out["k"],
        "n": out["n"],
    }


@register(
    "B11",
    name="分箱单调性",
    group="B",
    layer="D2",
    input_kind="pairs",
    min_n=COND_MIN_N,
    output_schema=("monotonic", "bin_means", "rho_bin", "k", "n"),
    notes="组均值随桶序严格递增/递减才算 monotonic，否则 non_monotonic",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "factor": [float(i) for i in range(300)],
                "target": [0.001 * i for i in range(300)],
            },
            "params": {"k": 5},
            "expect": {"result.monotonic": "increasing"},
        },
    ),
)
def b11_monotonic(data, k: int = 5, prebinned: bool = False, **_: Any) -> Dict[str, Any]:
    if prebinned:
        table = [
            row
            for row in b05_conditional(data)["table"]
            if row["n"] > 0 and row["mean"] is not None
        ]
        try:
            table = sorted(table, key=lambda row: int(row["state"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("prebinned states must be integer ordinals") from exc
        if len(table) < 2:
            raise ValueError("prebinned requires at least two nonempty states")
    else:
        # 真实数据下分位边界可能塌缩（大量并列值 → 空桶），空桶 mean=None 不参与单调性判断。
        table = [
            row
            for row in b16_group_stats(data, k=k)["table"]
            if row["n"] > 0 and row["mean"] is not None
        ]
        if len(table) < 2:
            raise ValueError(f"factor 在 k={k} 下非空分箱不足 2 个")
    means = [float(x["mean"]) for x in table]
    diffs = [b - a for a, b in zip(means, means[1:], strict=False)]
    if all(d > 0 for d in diffs):
        mono = "increasing"
    elif all(d < 0 for d in diffs):
        mono = "decreasing"
    else:
        mono = "non_monotonic"
    rho = None
    try:
        rho = spearman([float(i) for i in range(len(means))], means)
    except Exception:
        pass
    return {
        "monotonic": mono,
        "bin_means": [round(m, 6) for m in means],
        "rho_bin": None if rho is None else round(rho, 6),
        "k": len(table) if prebinned else k,
        "n": sum(x["n"] for x in table),
    }


@register(
    "B13",
    name="信息系数 IC",
    group="B",
    layer="D2",
    input_kind="pairs",
    min_n=COND_MIN_N,
    output_schema=("ic", "p", "n"),
    notes="factor 与 target（已由 align.forward_returns 生成）的 Pearson 相关；不做位移",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "factor": [float(i) for i in range(300)],
                "target": [float(i) for i in range(300)],
            },
            "params": {},
            "expect": {"result.ic": 1.0, "result.n": 300},
        },
        null="no_correlation",
        reference=lambda data: {
            "result.ic": float(
                __import__("scipy.stats", fromlist=["stats"]).pearsonr(
                    data["factor"], data["target"]
                )[0]
            )
        },
    ),
)
def b13_ic(data, **_: Any) -> Dict[str, Any]:
    factor, target = _two(data)
    ic = pearson(factor, target)
    return {"ic": round(ic, 6), "p": corr_p(ic, len(factor)), "n": len(factor)}


@register(
    "B14",
    name="Rank IC",
    group="B",
    layer="D2",
    input_kind="pairs",
    min_n=COND_MIN_N,
    output_schema=("rank_ic", "p", "n"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "factor": [float(i) for i in range(300)],
                "target": [float(i) ** 3 for i in range(300)],
            },
            "params": {},
            "expect": {"result.rank_ic": 1.0},
        },
        null="no_correlation",
        reference=lambda data: {
            "result.rank_ic": float(
                __import__("scipy.stats", fromlist=["stats"]).spearmanr(
                    data["factor"], data["target"]
                )[0]
            )
        },
    ),
)
def b14_rank_ic(data, **_: Any) -> Dict[str, Any]:
    factor, target = _two(data)
    ric = spearman(factor, target)
    return {"rank_ic": round(ric, 6), "p": corr_p(ric, len(factor)), "n": len(factor)}


@register(
    "B15",
    name="IC 衰减",
    group="B",
    layer="D3",
    input_kind="series",
    min_n=COND_MIN_N,
    output_schema=("lookback", "items", "n"),
    notes="复用 §16 冻结实现 persistence.metrics.ic_decay（重叠 + h 相位非重叠）",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [100.0 * math.exp(0.001 * i + 0.05 * math.sin(i / 5.0)) for i in range(400)],
            "params": {"lookback": 20, "horizons": (1, 5, 20)},
            "expect": {"result.items.0.h": 1, "result.n": 400},
        },
    ),
)
def b15_ic_decay(
    data, lookback: int = 20, horizons: Sequence[int] = (1, 5, 20), **_: Any
) -> Dict[str, Any]:
    out = ic_decay(_series(data), lookback=lookback, horizons=tuple(horizons))
    # 统一输出：把非重叠口径标成 gate 语言，避免下游误用重叠 n
    for item in out["items"]:
        item["nonoverlap_gate"] = (
            "ok" if item.get("ric_nonoverlap") is not None else "insufficient_samples"
        )
    return out


# ============================================================
# H01 单样本 t
# ============================================================


@register(
    "H01",
    name="单样本 t 检验",
    group="H",
    layer="D2",
    input_kind="series",
    min_n=DIST_MIN_N,
    output_schema=("mean", "se", "t", "p", "n", "is_significant"),
    notes="H0: 均值=0；p 走 t 分布（df=n−1）",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [0.01, 0.02] * 15,
            "params": {},
            "expect": {"result.mean": 0.015, "result.is_significant": True},
        },
        reference=lambda data: {
            "result.t": float(
                __import__("scipy.stats", fromlist=["stats"]).ttest_1samp(data, 0.0)[0]
            )
        },
    ),
)
def h01_one_sample_t(data, **_: Any) -> Dict[str, Any]:
    values = _series(data)
    n = len(values)
    mu, sd = _mean(values), _std(values)
    se = None if sd <= EPS else sd / math.sqrt(n)
    t = None if (se is None or se <= EPS) else mu / se
    p = None if t is None else t_two_sided_p(t, n - 1)
    return {
        "mean": round(mu, 6),
        "se": None if se is None else round(se, 8),
        "t": None if t is None else round(t, 3),
        "p": p,
        "n": n,
        "is_significant": bool(p is not None and p < 0.05),
    }


# ============================================================
# R01 / R02 关系表达
# ============================================================


@register(
    "R01",
    name="条件收益统计（表达）",
    group="R",
    layer="D2",
    input_kind="pairs",
    min_n=COND_MIN_N,
    output_schema=("table", "phrase", "state", "h", "n"),
    notes="固定句式（§13 R01）；只描述历史统计，不含因果与预测措辞",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "state": [str(i % 2) for i in range(300)],
                "target": [0.01 if i % 2 else -0.01 for i in range(300)],
            },
            "params": {"h": 1},
            "expect": {"result.table.1.mean": 0.01, "result.n": 300},
        },
    ),
)
def r01_conditional_phrase(
    data, h: int = 1, state: Optional[str] = None, **_: Any
) -> Dict[str, Any]:
    out = b05_conditional(data)
    table = out["table"]
    if not table:
        raise ValueError("no state group")
    pick = next((row for row in table if str(row["state"]) == str(state)), None) if state else None
    if pick is None:
        pick = max(table, key=lambda row: row["n"])
    mean_pct = None if pick["mean"] is None else pick["mean"] * 100.0
    med_pct = None if pick["median"] is None else pick["median"] * 100.0
    win = None if pick["win_rate"] is None else pick["win_rate"] * 100.0
    phrase = (
        f"历史 {pick['n']} 次「{pick['state']}」后 {h} 日："
        f"均值 {mean_pct:+.2f}%、中位 {med_pct:+.2f}%、上涨 {win:.1f}%"
        f"（n={pick['n']}，t={pick['t']}）。"
    )
    return {"table": table, "phrase": phrase, "state": pick["state"], "h": h, "n": out["n"]}


def _r02_time_key(value: Any) -> float:
    """把 ISO 日期/时间或数值时间戳转成可比较的 UTC 秒。"""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text)
        except ValueError:
            pass
        from datetime import datetime, timezone

        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    raise ValueError(f"unsupported timestamp: {value!r}")


def _r02_nonoverlap_n(indices: Sequence[int], horizon: int) -> int:
    """按时间顺序贪心保留前瞻窗口不重叠的样本数。"""
    count = 0
    next_available = None
    for i in indices:
        if next_available is None or i >= next_available:
            count += 1
            next_available = i + horizon
    return count


def _r02_rolling_state(
    values: Sequence[float],
    buckets: int,
    window: int,
    release_keys: Sequence[float],
    time_keys: Sequence[float],
    has_release: bool,
):
    """PIT 逐时点滚动分位分桶闭包：`(last_index, visible_until) -> (percentile, bucket)`。

    `has_release=false` 时可见窗口等价于「截至 last_index 的最近 window 个观测」，
    用切片直接取，避免 O(n²) 的逐点过滤（与过滤口径结果完全一致）。
    """

    def state_at(last_index: int, visible_until: float):
        if has_release:
            visible = [j for j in range(last_index + 1) if release_keys[j] <= visible_until]
            if len(visible) < window:
                return None
            sample = [values[j] for j in visible[-window:]]
        else:
            if last_index + 1 < window:
                return None
            sample = list(values[last_index + 1 - window : last_index + 1])
        current = sample[-1]
        ordered = sorted(sample)
        inner = [_quantile_sorted(ordered, i / buckets) for i in range(1, buckets)]
        percentile = 100.0 * sum(1 for v in sample if v <= current) / len(sample)
        bucket = min(bisect.bisect_right(inner, current), buckets - 1)
        return percentile, bucket

    return state_at


def _r02_describe(selected: Sequence[tuple], horizon: int, pit: bool) -> Dict[str, Any]:
    """单桶/单格前瞻收益描述统计；h>1 的 PIT 样本不输出朴素 t/p。"""
    stats = _group_stats([float(v) for _, v in selected])
    ordered = sorted(float(v) for _, v in selected)
    stats["p10"] = round(_quantile_sorted(ordered, 0.1), 6) if ordered else None
    stats["p90"] = round(_quantile_sorted(ordered, 0.9), 6) if ordered else None
    if pit and horizon > 1:
        stats["t"] = None
        stats["p"] = None
    stats.update(
        {
            "effective_n": len(selected),
            "nonoverlap_n": _r02_nonoverlap_n([i for i, _ in selected], horizon),
        }
    )
    return stats


@register(
    "R02",
    name="分位→前瞻收益（表达）",
    group="R",
    layer="D2",
    input_kind="pairs",
    min_n=COND_MIN_N,
    output_schema=(
        "current_percentile",
        "bucket",
        "by_horizon",
        "phrase",
        "n",
        "pit",
        "as_of",
        "window",
        "align_method",
    ),
    notes=(
        "pit=true 逐时点滚动分位；pit=false 仅供含未来函数的样本内回顾；"
        "可选 indicator2 做两维分位笛卡尔积（cells=buckets²），每格独立统计并输出 by_cell"
    ),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "indicator": [float(i) for i in range(300)],
                "price": [100.0 * math.exp(0.0005 * i) for i in range(300)],
            },
            "params": {"buckets": 10, "horizons": (1, 5)},
            "expect": {"result.current_percentile": 100.0, "result.bucket": 9},
        },
    ),
)
def r02_percentile_forward(
    data,
    buckets: int = 10,
    horizons: Sequence[int] = (1, 3, 5, 10, 20),
    label: str = "该指标",
    label2: Optional[str] = None,
    pit: bool = False,
    window: int = COND_MIN_N,
    as_of: Any = None,
    include_states: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    indicator, price = _two(data)
    second_raw = next((data[key] for key in ("indicator2", "factor2", "x2") if key in data), None)
    two_axis = second_raw is not None
    n = len(indicator)
    if buckets < 2:
        raise ValueError("buckets must be >= 2")
    if window < 2:
        raise ValueError("window must be >= 2")
    second: List[float] = []
    if two_axis:
        second = _floats(second_raw)
        if len(second) != n:
            raise ValueError("indicator2 length must equal indicator/price length")
        if not pit:
            raise ValueError("two-axis percentile requires pit=True")

    raw_times = next(
        (data[key] for key in ("timestamps", "dates", "ts") if key in data),
        list(range(n)),
    )
    if len(raw_times) != n:
        raise ValueError("timestamps length must equal indicator/price length")
    time_keys = [_r02_time_key(v) for v in raw_times]
    if any(b < a for a, b in zip(time_keys, time_keys[1:], strict=False)):
        raise ValueError("timestamps must be sorted")

    as_of_value = raw_times[-1] if as_of is None else as_of
    as_of_key = _r02_time_key(as_of_value)
    end = bisect.bisect_right(time_keys, as_of_key)
    if end < 1:
        raise ValueError("as_of precedes the first observation")
    indicator = indicator[:end]
    price = price[:end]
    raw_times = raw_times[:end]
    time_keys = time_keys[:end]
    if two_axis:
        second = second[:end]

    release_keys = time_keys
    has_release = bool(pit and "release_ts" in data)
    if has_release:
        if len(data["release_ts"]) != n:
            raise ValueError("release_ts length must equal indicator/price length")
        release_keys = [_r02_time_key(v) for v in data["release_ts"][:end]]

    state_at = _r02_rolling_state(indicator, buckets, window, release_keys, time_keys, has_release)
    state_at2 = (
        _r02_rolling_state(second, buckets, window, release_keys, time_keys, has_release)
        if two_axis
        else None
    )

    if pit:
        current_state = state_at(end - 1, as_of_key)
        if current_state is None:
            raise ValueError(
                f"pit requires at least {window} visible observations as of {as_of_value}"
            )
        states = [state_at(i, time_keys[i]) for i in range(end)]
        pct, bucket = current_state
        cell = None
        pct2 = bucket2 = None
        if two_axis:
            current_state2 = state_at2(end - 1, as_of_key)
            if current_state2 is None:
                raise ValueError(
                    f"pit requires at least {window} visible observations as of {as_of_value}"
                )
            states2 = [state_at2(i, time_keys[i]) for i in range(end)]
            pct2, bucket2 = current_state2
            cell = int(bucket) * buckets + int(bucket2)
            labels = [
                None if (left is None or right is None) else int(left[1]) * buckets + int(right[1])
                for left, right in zip(states, states2, strict=False)
            ]
        else:
            labels = [None if state is None else int(state[1]) for state in states]
    else:
        last = indicator[-1]
        pct = 100.0 * sum(1 for v in indicator if v <= last) / end
        edges = [_quantile_sorted(sorted(indicator), i / buckets) for i in range(buckets + 1)]
        inner = edges[1:-1]
        bucket = min(bisect.bisect_right(inner, last), buckets - 1)
        labels = [min(bisect.bisect_right(inner, value), buckets - 1) for value in indicator]
        cell = None
        pct2 = bucket2 = None

    align_method = str(data.get("align_method") or "prealigned")
    disclosed_window = int(window) if pit else end
    grid = buckets * buckets if two_axis else buckets

    by_horizon: List[Dict[str, Any]] = []
    for h in horizons:
        horizon = int(h)
        fwd = forward_returns(price, horizon)
        entries: List[Dict[str, Any]] = []
        for condition in range(grid):
            selected = [
                (i, fwd[i]) for i in range(end) if fwd[i] is not None and labels[i] == condition
            ]
            row = dict(bucket=condition, **_r02_describe(selected, horizon, pit))
            if two_axis:
                row.update(cell=condition, axis1=condition // buckets, axis2=condition % buckets)
            entries.append(row)
        current_label = cell if two_axis else bucket
        stats = dict(entries[current_label])
        stats.pop("bucket")
        stats.update(
            {
                "pit": bool(pit),
                "as_of": as_of_value,
                "window": disclosed_window,
                "align_method": align_method,
            }
        )
        stats["by_cell" if two_axis else "by_bucket"] = entries
        by_horizon.append(dict(h=horizon, **stats))

    main = by_horizon[0] if by_horizon else None
    if main and main["effective_n"]:
        distribution = (
            f"历史同分位区间后 {main['h']} 日：均值 {(main['mean'] or 0.0) * 100.0:+.2f}%、"
            f"上涨 {(main['win_rate'] or 0.0) * 100.0:.1f}%"
            f"（有效 n={main['effective_n']}，非重叠 n={main['nonoverlap_n']}）。"
        )
    else:
        distribution = "历史同分位区间样本不足。"
    if two_axis:
        head = (
            f"截至 {as_of_value}，{label}处于 {pct:.1f}% 分位、"
            f"{label2 or '第二维状态'}处于 {pct2:.1f}% 分位"
            f"（{buckets}×{buckets} 网格第 {int(bucket) + 1} 行第 {int(bucket2) + 1} 列）；"
        )
        phrase = f"{head}按当时可见数据识别的同格{distribution}历史统计，不代表未来。"
    elif pit:
        phrase = (
            f"截至 {as_of_value}，当前 {label} 处于 {pct:.1f}% 分位；"
            f"按当时可见数据识别的{distribution}历史统计，不代表未来。"
        )
    else:
        phrase = (
            f"样本内回顾（全样本分位，含未来函数，不用于条件外推）：当前 {label} "
            f"处于 {pct:.1f}% 分位；{distribution}历史统计，不代表未来。"
        )
    out = {
        "current_percentile": round(pct, 4),
        "bucket": bucket,
        "by_horizon": by_horizon,
        "phrase": phrase,
        "n": end,
        "sample_n": end,
        "pit": bool(pit),
        "as_of": as_of_value,
        "window": disclosed_window,
        "align_method": align_method,
    }
    if two_axis:
        out.update(
            {
                "dim": 2,
                "buckets_per_axis": buckets,
                "cells": grid,
                "current_percentile_2": round(pct2, 4),
                "bucket_1": bucket,
                "bucket_2": bucket2,
                "cell": cell,
            }
        )
    if include_states:
        out["states"] = labels
    return out
