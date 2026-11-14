# -*- coding: utf-8 -*-
"""S2 相关性批（自举批次）：M01–M07、M11–M12、M24–M25 + R05 表达。

另含多变量补齐批：M08–M10（偏相关/距离相关/互信息）、M13–M16（协整/回归）、
M18–M22（跟踪误差/降维/聚类）、M26（简化因子暴露）。

门禁（SPEC §17.1.3 S2）：n≥60 才出同期相关；n≥120 才出 CCF；
所有 p 值走 t 分布（非正态近似），多重比较走 BH-FDR；
CCF 符号约定：`ccf(k)=corr(x[t], y[t+k])`，k>0 表示 **x 领先 y** k 期。

所有方法只接收已对齐等长序列（`l1agg.align` 产物），不做取数、不写库。
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from l1agg.persistence._stats import pearson, spearman

from ._helpers import r4, r6
from .registry import MethodChecks, register
from .stats_core import bh_fdr, corr_p, kendall_p, kendall_tau_b, t_two_sided_p

PAIRS_MIN_N = 60
CCF_MIN_N = 120
_EPS = 1e-12


def _pairs(data: Mapping[str, Any]) -> tuple[List[float], List[float]]:
    x = [float(v) for v in data["x"]]
    y = [float(v) for v in data["y"]]
    n = min(len(x), len(y))
    if n < 3:
        raise ValueError("need at least 3 paired points")
    return x[:n], y[:n]


def _panel(data: Mapping[str, Any], min_n: int) -> Dict[str, List[float]]:
    series = data["series"]
    n = min(len(v) for v in series.values())
    if n < min_n:
        raise ValueError(f"panel needs n>={min_n}, got {n}")
    return {k: [float(v) for v in vals[:n]] for k, vals in series.items()}


def _ci_like(r: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Fisher z 变换的近似 95% 置信区间（仅作诊断量，不作显著性判断）。"""
    if n <= 3 or abs(r) >= 1.0:
        return r, r
    zr, se = math.atanh(r), 1.0 / math.sqrt(n - 3)
    lo, hi = math.tanh(zr - z * se), math.tanh(zr + z * se)
    return round(lo, 6), round(hi, 6)


# ============================================================
# M01–M03 同期相关
# ============================================================


@register(
    "M01",
    name="Pearson 相关",
    group="M",
    layer="D2",
    input_kind="pairs",
    min_n=PAIRS_MIN_N,
    output_schema=("r", "p", "n", "ci95"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "x": [float(i) for i in range(PAIRS_MIN_N)],
                "y": [2.0 * i + 3.0 for i in range(PAIRS_MIN_N)],
            },
            "params": {},
            "expect": {"result.r": 1.0, "result.n": PAIRS_MIN_N, "gate": "ok"},
        },
        null="no_correlation",
        reference=lambda data: {
            "result.r": float(
                __import__("scipy.stats", fromlist=["stats"]).pearsonr(data["x"], data["y"])[0]
            )
        },
    ),
)
def m01_pearson(data, **_: Any) -> Dict[str, Any]:
    x, y = _pairs(data)
    r = pearson(x, y)
    n = len(x)
    return {"r": round(r, 6), "p": corr_p(r, n), "n": n, "ci95": _ci_like(r, n)}


@register(
    "M02",
    name="Spearman 秩相关",
    group="M",
    layer="D2",
    input_kind="pairs",
    min_n=PAIRS_MIN_N,
    output_schema=("r", "p", "n"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "x": [float(i) for i in range(PAIRS_MIN_N)],
                "y": [float(i**2) for i in range(PAIRS_MIN_N)],
            },
            "params": {},
            "expect": {"result.r": 1.0, "result.n": PAIRS_MIN_N},
        },
        null="no_correlation",
    ),
)
def m02_spearman(data, **_: Any) -> Dict[str, Any]:
    x, y = _pairs(data)
    r = spearman(x, y)
    n = len(x)
    return {"r": round(r, 6), "p": corr_p(r, n), "n": n}


@register(
    "M03",
    name="Kendall τ-b",
    group="M",
    layer="D2",
    input_kind="pairs",
    min_n=PAIRS_MIN_N,
    output_schema=("tau", "p", "n"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "x": [float(i) for i in range(PAIRS_MIN_N)],
                "y": [3.0 * i + 1.0 for i in range(PAIRS_MIN_N)],
            },
            "params": {},
            "expect": {"result.tau": 1.0, "result.n": PAIRS_MIN_N},
        },
        null="no_correlation",
    ),
)
def m03_kendall(data, **_: Any) -> Dict[str, Any]:
    x, y = _pairs(data)
    tau = kendall_tau_b(x, y)
    n = len(x)
    return {"tau": round(tau, 6), "p": kendall_p(tau, n), "n": n}


# ============================================================
# M04–M07 滚动 / 矩阵 / 排序
# ============================================================


@register(
    "M04",
    name="滚动相关",
    group="M",
    layer="D2",
    input_kind="pairs",
    min_n=PAIRS_MIN_N,
    output_schema=("r", "window", "n_windows"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "x": [float(i) for i in range(PAIRS_MIN_N)],
                "y": [float(i) for i in range(PAIRS_MIN_N)],
            },
            "params": {"window": 30},
            "expect": {"result.n_windows": PAIRS_MIN_N - 30 + 1, "result.mean_r": 1.0},
        },
    ),
)
def m04_rolling(data, window: int = 30, **_: Any) -> Dict[str, Any]:
    x, y = _pairs(data)
    if window < 2 or window > len(x):
        raise ValueError(f"invalid window={window} for n={len(x)}")
    rs: List[float] = []
    for i in range(len(x) - window + 1):
        rs.append(_safe_pearson(x[i : i + window], y[i : i + window]))
    valid = [r for r in rs if r is not None]
    return {
        "r": [None if r is None else round(r, 6) for r in rs],
        "window": window,
        "n_windows": len(rs),
        "mean_r": round(sum(valid) / len(valid), 6) if valid else None,
        "sample_n": len(x),
    }


@register(
    "M05",
    name="相关矩阵",
    group="M",
    layer="D2",
    input_kind="panel",
    min_n=PAIRS_MIN_N,
    output_schema=("matrix", "names", "n"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "series": {
                    "A": [float(i) for i in range(PAIRS_MIN_N)],
                    "B": [2.0 * i for i in range(PAIRS_MIN_N)],
                    "C": [-1.0 * i for i in range(PAIRS_MIN_N)],
                }
            },
            "params": {},
            "expect": {
                "result.matrix.A.B": 1.0,
                "result.matrix.A.C": -1.0,
                "result.n": PAIRS_MIN_N,
            },
        },
    ),
)
def m05_matrix(data, **_: Any) -> Dict[str, Any]:
    panel = _panel(data, PAIRS_MIN_N)
    names = list(panel)
    n = len(next(iter(panel.values())))
    matrix: Dict[str, Dict[str, float]] = {}
    for a in names:
        matrix[a] = {}
        for b in names:
            matrix[a][b] = 1.0 if a == b else round(_safe_pearson(panel[a], panel[b]) or 0.0, 6)
    return {"matrix": matrix, "names": names, "n": n}


@register(
    "M06",
    name="相关矩阵 TopK（R05 表达）",
    group="M",
    layer="D2",
    input_kind="panel",
    min_n=PAIRS_MIN_N,
    output_schema=("pairs", "topk", "phrase", "n"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "series": {
                    "A": [float(i) for i in range(PAIRS_MIN_N)],
                    "B": [2.0 * i for i in range(PAIRS_MIN_N)],
                    "C": [float((i * 37) % 11) for i in range(PAIRS_MIN_N)],
                }
            },
            "params": {"k": 2},
            "expect": {"result.topk.0.r": 1.0},
        },
    ),
)
def m06_topk(data, k: int = 5, base: str = "", **_: Any) -> Dict[str, Any]:
    panel = _panel(data, PAIRS_MIN_N)
    names = list(panel)
    n = len(next(iter(panel.values())))
    pairs: List[Dict[str, Any]] = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            r = _safe_pearson(panel[a], panel[b])
            if r is None:
                continue
            pairs.append({"a": a, "b": b, "r": round(r, 6), "p": corr_p(r, n), "n": n})
    if base:
        pairs = [p for p in pairs if base in (p["a"], p["b"])]
        pairs.sort(key=lambda p: -abs(p["r"]))
        subject = base
    else:
        pairs.sort(key=lambda p: -abs(p["r"]))
        subject = "全市场"
    if not pairs:
        raise ValueError("no valid pair")
    pvals = [p["p"] for p in pairs]
    fdr = bh_fdr(pvals)
    for p, q, rej in zip(pairs, fdr["q"], fdr["reject"], strict=False):
        p["q"] = round(q, 6)
        p["significant"] = bool(rej)
    top = pairs[: max(1, int(k))]
    listed = "、".join(f"{p['a']}–{p['b']}({p['r']:+.3f})" for p in top)
    return {
        "pairs": pairs,
        "topk": top,
        "phrase": f"与{subject}相关性最高：{listed}（n={n}，BH-FDR q≤{fdr['alpha']}）。",
        "n": n,
        "fdr": {"alpha": fdr["alpha"], "m": fdr["m"]},
    }


@register(
    "M07",
    name="平均相关度",
    group="M",
    layer="D2",
    input_kind="panel",
    min_n=PAIRS_MIN_N,
    output_schema=("avg_abs_r", "avg_r", "n_assets", "n"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "series": {
                    "A": [float(i) for i in range(PAIRS_MIN_N)],
                    "B": [2.0 * i for i in range(PAIRS_MIN_N)],
                    "C": [3.0 * i for i in range(PAIRS_MIN_N)],
                }
            },
            "params": {},
            "expect": {"result.avg_abs_r": 1.0, "result.n_assets": 3},
        },
    ),
)
def m07_avg(data, **_: Any) -> Dict[str, Any]:
    panel = _panel(data, PAIRS_MIN_N)
    names = list(panel)
    rs = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            r = _safe_pearson(panel[a], panel[b])
            if r is not None:
                rs.append(r)
    if not rs:
        raise ValueError("no valid pair")
    return {
        "avg_abs_r": round(sum(abs(r) for r in rs) / len(rs), 6),
        "avg_r": round(sum(rs) / len(rs), 6),
        "n_assets": len(names),
        "n": len(next(iter(panel.values()))),
    }


# ============================================================
# M11–M12 领先滞后
# ============================================================


def _ccf_core(x: Sequence[float], y: Sequence[float], max_lag: int) -> Dict[str, Any]:
    lags = list(range(-max_lag, max_lag + 1))
    rs: List[float] = []
    ns: List[int] = []
    for k in lags:
        if k >= 0:
            xs, ys = x[: len(x) - k], y[k:]
        else:
            xs, ys = x[-k:], y[: len(y) + k]
        n = min(len(xs), len(ys))
        ns.append(n)
        rs.append(_safe_pearson(xs, ys) or 0.0)
    ps = []
    for r, n in zip(rs, ns, strict=False):
        p = corr_p(r, n)
        ps.append(1.0 if p is None else p)
    fdr = bh_fdr(ps)
    return {
        "lags": lags,
        "r": [round(r, 6) for r in rs],
        "p": ps,
        "q": [round(q, 6) for q in fdr["q"]],
        "significant": fdr["reject"],
        "n_by_lag": ns,
        "sample_n": len(x),
    }


@register(
    "M11",
    name="领先滞后 CCF",
    group="M",
    layer="D2",
    input_kind="pairs",
    min_n=CCF_MIN_N,
    output_schema=("lags", "r", "p", "q", "n_by_lag"),
    notes="ccf(k)=corr(x[t],y[t+k])；k>0 表示 x 领先 y",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": _ccf_synthetic()["data"],
            "params": {"max_lag": 10},
            # lags 索引 11 对应 lag=+1（x 领先 y 1 期）
            "expect": {"result.r.11": 1.0, "gate": "ok"},
        },
    ),
)
def m11_ccf(data, max_lag: int = 10, **_: Any) -> Dict[str, Any]:
    x, y = _pairs(data)
    if max_lag < 1:
        raise ValueError("max_lag must be >= 1")
    return _ccf_core(x, y, max_lag)


@register(
    "M12",
    name="最优领先/滞后",
    group="M",
    layer="D2",
    input_kind="pairs",
    min_n=CCF_MIN_N,
    output_schema=("lag", "r", "p", "q", "n"),
    notes="argmax|CCF|；k>0 表示 x 领先 y",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": _ccf_synthetic()["data"],
            "params": {"max_lag": 10},
            "expect": {"result.lag": 1, "gate": "ok"},
        },
    ),
)
def m12_best_lag(data, max_lag: int = 10, **_: Any) -> Dict[str, Any]:
    x, y = _pairs(data)
    ccf = _ccf_core(x, y, max_lag)
    idx = max(range(len(ccf["r"])), key=lambda i: abs(ccf["r"][i]))
    return {
        "lag": ccf["lags"][idx],
        "r": ccf["r"][idx],
        "p": ccf["p"][idx],
        "q": ccf["q"][idx],
        "n": ccf["n_by_lag"][idx],
    }


def _ccf_synthetic() -> Dict[str, Any]:
    n = CCF_MIN_N + 20
    x = [math.sin(i * 0.7) + 0.3 * math.cos(i * 1.3) for i in range(n)]
    # y[t] = x[t-1] → x 领先 y 1 期（ccf 峰值应在 k=+1）
    y = [0.0] + x[:-1]
    return {"data": {"x": x, "y": y}, "params": {"max_lag": 10}, "expect": {"result.lag": 1}}


# ============================================================
# M24–M25 稳定性 / 突变
# ============================================================


@register(
    "M24",
    name="相关性稳定性",
    group="M",
    layer="D2",
    input_kind="pairs",
    min_n=PAIRS_MIN_N,
    output_schema=("mean_r", "std_r", "min_r", "max_r", "sign_consistency", "stability"),
    notes="stability=1/(1+std_r)，∈(0,1]，越接近 1 越稳定",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "x": [float(i) for i in range(PAIRS_MIN_N)],
                "y": [2.0 * i for i in range(PAIRS_MIN_N)],
            },
            "params": {"window": 30},
            "expect": {"result.stability": 1.0, "result.sign_consistency": 1.0},
        },
    ),
)
def m24_stability(data, window: int = 30, **_: Any) -> Dict[str, Any]:
    roll = m04_rolling(data, window=window)
    rs = [r for r in roll["r"] if r is not None]
    if not rs:
        raise ValueError("no valid rolling window")
    mean_r = sum(rs) / len(rs)
    var = sum((r - mean_r) ** 2 for r in rs) / max(1, len(rs) - 1)
    std_r = math.sqrt(var)
    signs = [1 if r > 0 else (-1 if r < 0 else 0) for r in rs]
    major = 1 if sum(1 for s in signs if s > 0) >= len(signs) / 2 else -1
    consistency = sum(1 for s in signs if s == major) / len(signs)
    return {
        "mean_r": round(mean_r, 6),
        "std_r": round(std_r, 6),
        "min_r": round(min(rs), 6),
        "max_r": round(max(rs), 6),
        "sign_consistency": round(consistency, 6),
        "stability": round(1.0 / (1.0 + std_r), 6),
        "sample_n": roll["sample_n"],
    }


@register(
    "M25",
    name="相关性突变",
    group="M",
    layer="D2",
    input_kind="pairs",
    min_n=PAIRS_MIN_N,
    output_schema=("z", "breakpoints", "threshold", "window"),
    notes="滚动相关 z-score（对前期窗口），|z|≥threshold 的局部极值记为突变点",
    checks=MethodChecks(
        synthetic=lambda: _break_synthetic(),
    ),
)
def m25_change(data, window: int = 30, threshold: float = 2.0, **_: Any) -> Dict[str, Any]:
    roll = m04_rolling(data, window=window)
    rs = roll["r"]
    z: List[float | None] = [None] * len(rs)
    for i in range(1, len(rs)):
        hist = [r for r in rs[:i] if r is not None]
        if len(hist) < 5 or rs[i] is None:
            continue
        mu = sum(hist) / len(hist)
        sd = math.sqrt(sum((r - mu) ** 2 for r in hist) / max(1, len(hist) - 1))
        z[i] = 0.0 if sd <= 1e-12 else (rs[i] - mu) / sd
    breaks: List[int] = []
    for i in range(1, len(z) - 1):
        if z[i] is None or z[i - 1] is None or z[i + 1] is None:
            continue
        if abs(z[i]) >= threshold and abs(z[i]) >= abs(z[i - 1]) and abs(z[i]) >= abs(z[i + 1]):
            breaks.append(i)
    return {
        "z": [None if v is None else round(v, 6) for v in z],
        "breakpoints": breaks,
        "threshold": threshold,
        "window": window,
        "sample_n": roll["sample_n"],
    }


def _break_synthetic() -> Dict[str, Any]:
    n = PAIRS_MIN_N * 2
    x = [math.sin(i * 0.7) for i in range(n)]
    y = [x[i] if i < n // 2 else -x[i] for i in range(n)]
    return {
        "data": {"x": x, "y": y},
        "params": {"window": 20, "threshold": 2.0},
        "expect": {"result.breakpoints": "non_empty"},
    }


# ============================================================
# 批处理：多重比较修正（R05/R06 共用）
# ============================================================


def apply_fdr(results: Sequence[Mapping[str, Any]], alpha: float = 0.05) -> List[Dict[str, Any]]:
    """为一组方法输出统一补 `q/significant`（BH-FDR）。"""
    pvals = [float(r["p"]) for r in results]
    fdr = bh_fdr(pvals, alpha=alpha)
    out = []
    for r, q, rej in zip(results, fdr["q"], fdr["reject"], strict=False):
        item = dict(r)
        item["q"] = round(q, 6)
        item["significant"] = bool(rej)
        out.append(item)
    return out


def _safe_pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    try:
        return pearson(xs, ys)
    except Exception:
        return None


# ============================================================
# 多变量补齐批通用工具（M08–M10 / M13–M16 / M18–M22 / M26）
# ============================================================


def _np():
    """延迟导入 numpy（模块导入期不引入第三方依赖）。"""
    import numpy

    return numpy


def _columns(data: Any) -> Tuple[List[str], List[List[float]]]:
    """面板输入 → (names, columns)，列已按最短长度对齐。

    兼容：{"series": {name: [...]}}（标准）、{"matrix": [[...]]}（行=样本）、
    扁平 {name: [...]}（按插入顺序）。
    """
    if isinstance(data, Mapping):
        series = data.get("series")
        if isinstance(series, Mapping):
            names = [str(k) for k in series]
            raw = [list(series[k]) for k in series]
        elif "matrix" in data:
            rows = [list(r) for r in data["matrix"]]
            if not rows:
                raise ValueError("empty matrix")
            width = len(rows[0])
            if width < 2:
                raise ValueError("matrix needs >= 2 columns")
            if any(len(r) != width for r in rows):
                raise ValueError("ragged matrix")
            names = [f"f{i}" for i in range(width)]
            raw = [[r[i] for r in rows] for i in range(width)]
        else:
            names = [
                str(k)
                for k, v in data.items()
                if isinstance(v, Sequence) and not isinstance(v, (str, bytes))
            ]
            raw = [list(data[k]) for k in names]
    elif isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
        names, raw = ["f0"], [list(data)]
    else:
        raise ValueError("panel data must be a mapping or a sequence")
    if not raw:
        raise ValueError("no series in panel data")
    n = min(len(c) for c in raw)
    if n < 1:
        raise ValueError("empty series in panel data")
    return names, [[float(v) for v in c[:n]] for c in raw]


def _named_column(
    names: Sequence[str], cols: Sequence[List[float]], key: Any, default_idx: int
) -> Tuple[str, List[float]]:
    if key is None:
        return names[default_idx], cols[default_idx]
    if isinstance(key, int) and not isinstance(key, bool):
        return names[key], cols[key]
    name = str(key)
    if name not in names:
        raise ValueError(f"unknown column {name!r} in {list(names)}")
    return name, cols[names.index(name)]


def _target_and_factors(
    data: Any, target: Optional[str] = None, factors: Optional[Sequence[str]] = None
) -> Tuple[List[float], List[str], List[List[float]], int]:
    """拆出 (y, 因子名, 因子列, n)；支持 {"target","factors"} 与面板 series。"""
    if isinstance(data, Mapping) and isinstance(data.get("factors"), Mapping):
        fmap = data["factors"]
        y = [float(v) for v in data["target"]]
        names = [str(k) for k in fmap]
        cols = [[float(v) for v in fmap[k]] for k in names]
    else:
        names, cols = _columns(data)
        if target is None:
            target = "y" if "y" in names else names[-1]
        if target not in names:
            raise ValueError(f"target {target!r} not in {names}")
        i = names.index(target)
        y = cols[i]
        names = [n for j, n in enumerate(names) if j != i]
        cols = [c for j, c in enumerate(cols) if j != i]
    if factors:
        wanted = [str(f) for f in factors]
        missing = [f for f in wanted if f not in names]
        if missing:
            raise ValueError(f"unknown factors: {missing}")
        cols = [cols[names.index(f)] for f in wanted]
        names = wanted
    if not names:
        raise ValueError("need at least 1 factor")
    n = min([len(y)] + [len(c) for c in cols])
    if n < 3:
        raise ValueError("need at least 3 aligned observations")
    return y[:n], names, [c[:n] for c in cols], n


def _multi_ols(
    y: Sequence[float], cols: Sequence[Sequence[float]], names: Sequence[str]
) -> Dict[str, Any]:
    """y ~ 1 + X 多元 OLS；返回 beta/alpha/r2/t/p/残差（t、p 基于 (X'X)⁻¹σ²）。"""
    np = _np()
    yv = np.asarray(list(y), dtype=float)
    xm = np.column_stack([np.ones(len(yv))] + [np.asarray(list(c), dtype=float) for c in cols])
    n, p = xm.shape
    if n <= p:
        raise ValueError(f"need n>{p} observations for {p - 1} factors, got {n}")
    beta, *_ = np.linalg.lstsq(xm, yv, rcond=None)
    resid = yv - xm @ beta
    sse = float(resid @ resid)
    sst = float(((yv - yv.mean()) ** 2).sum())
    r2 = 0.0 if sst <= _EPS else 1.0 - sse / sst
    dof = n - p
    sigma2 = sse / dof if dof > 0 else 0.0
    se = np.sqrt(np.maximum(np.diag(np.linalg.pinv(xm.T @ xm)) * sigma2, 0.0))
    t_stats: Dict[str, Optional[float]] = {}
    p_vals: Dict[str, Optional[float]] = {}
    for i, name in enumerate(names):
        s = float(se[i + 1])
        if s <= _EPS:
            t_stats[name] = None
            p_vals[name] = None
        else:
            ti = float(beta[i + 1] / s)
            t_stats[name] = r4(ti)
            p_vals[name] = t_two_sided_p(ti, dof)
    return {
        "alpha": float(beta[0]),
        "betas": {name: float(beta[i + 1]) for i, name in enumerate(names)},
        "r2": float(r2),
        "t": t_stats,
        "p": p_vals,
        "n": n,
        "dof": dof,
        "resid": [float(v) for v in resid],
    }


def _adf_test(
    values: Sequence[float], regression: str = "c", maxlag: Optional[int] = None
) -> Dict[str, Any]:
    """ADF 单位根检验（statsmodels，AIC 选阶）；退化输入返回 p=1。"""
    from statsmodels.tsa.stattools import adfuller

    vals = [float(v) for v in values]
    autolag = "AIC" if maxlag is None else None
    try:
        try:
            res = adfuller(
                vals, maxlag=maxlag, regression=regression, autolag=autolag, result_object=False
            )
        except TypeError:  # statsmodels < 0.15 无 result_object 参数
            res = adfuller(vals, maxlag=maxlag, regression=regression, autolag=autolag)
    except (ValueError, ZeroDivisionError, IndexError):
        return {"stat": None, "p": 1.0, "lags": 0, "n": len(vals)}
    return {"stat": float(res[0]), "p": float(res[1]), "lags": int(res[2]), "n": int(res[3])}


def _equal_freq_ids(arr: Any, k: int) -> Any:
    """等频分箱编号（线性插值分位，最后一箱含最大值）。"""
    np = _np()
    edges = np.quantile(arr, np.linspace(0.0, 1.0, k + 1))
    inner = edges[1:-1]
    return np.searchsorted(inner, arr, side="right")


def _pca_core(data: Any, k: Optional[int] = None) -> Dict[str, Any]:
    """z-score 标准化后 SVD（相关阵口径）；载荷符号约定：最大绝对值取正。"""
    np = _np()
    names, cols = _columns(data)
    xm = np.asarray(cols, dtype=float).T
    n, m = xm.shape
    if m < 2:
        raise ValueError("PCA needs >= 2 variables")
    sd = xm.std(axis=0, ddof=1)
    if bool(np.any(sd <= _EPS)):
        raise ValueError("PCA needs non-constant series")
    z = (xm - xm.mean(axis=0)) / sd
    _, s, vt = np.linalg.svd(z, full_matrices=False)
    eig = (s**2) / max(1, n - 1)
    total = float(eig.sum())
    ratio = eig / total if total > _EPS else np.zeros_like(eig)
    for i in range(vt.shape[0]):
        j = int(np.argmax(np.abs(vt[i])))
        if vt[i, j] < 0:
            vt[i] = -vt[i]
    load = vt * np.sqrt(np.maximum(eig, 0.0))[:, None]
    kk = max(1, min(int(k) if k else min(3, m), int(vt.shape[0])))
    return {
        "names": names,
        "n": n,
        "m": m,
        "k": kk,
        "ratio": ratio[:kk],
        "cum": np.cumsum(ratio[:kk]),
        "load": load[:kk],
    }


# ---------------- 合成自检数据（供 eval harness 自动执行） ----------------


def _partial_synthetic() -> Dict[str, Any]:
    rng = random.Random(11)
    n = 140
    z = [rng.gauss(0, 1) for _ in range(n)]
    x = [v + rng.gauss(0, 1) for v in z]
    y = [v + rng.gauss(0, 1) for v in z]
    return {
        "data": {"series": {"x": x, "y": y, "z": z}},
        "params": {},
        "expect": {"result.n": n, "gate": "ok"},
    }


def _dcor_synthetic() -> Dict[str, Any]:
    n = 120
    x = [float(i) for i in range(n)]
    y = [2.0 * i + 3.0 for i in range(n)]
    return {"data": {"x": x, "y": y}, "params": {}, "expect": {"result.dcor": 1.0}}


def _mi_synthetic() -> Dict[str, Any]:
    n = 120
    x = [float(i) for i in range(n)]
    y = [4.0 * i - 7.0 for i in range(n)]
    return {"data": {"x": x, "y": y}, "params": {"bins": 8}, "expect": {"result.nmi": 1.0}}


def _coint_synthetic() -> Dict[str, Any]:
    rng = random.Random(5)
    n = 220
    x = [0.0]
    for _ in range(n - 1):
        x.append(x[-1] + rng.gauss(0, 1))
    y = [2.0 * v + rng.gauss(0, 0.5) for v in x]
    return {"data": {"x": x, "y": y}, "params": {}, "expect": {"result.n": n, "gate": "ok"}}


def _ols_synthetic() -> Dict[str, Any]:
    n = 120
    x = [float(i) for i in range(n)]
    y = [2.0 * v + 3.0 + 1e-3 * math.sin(i * 1.7) for i, v in enumerate(x)]
    return {
        "data": {"x": x, "y": y},
        "params": {},
        "expect": {"result.beta": 2.0, "result.r2": 1.0},
    }


def _multi_factor_synthetic() -> Dict[str, Any]:
    n = 120
    f1 = [float(i) for i in range(n)]
    f2 = [math.sin(i * 0.3) for i in range(n)]
    y = [
        2.0 * a + 3.0 * b + 1e-3 * math.cos(i * 0.7)
        for i, (a, b) in enumerate(zip(f1, f2, strict=False))
    ]
    return {
        "data": {"target": y, "factors": {"f1": f1, "f2": f2}},
        "params": {},
        "expect": {"result.betas.f1": 2.0, "result.betas.f2": 3.0, "result.r2": 1.0},
    }


def _resid_synthetic() -> Dict[str, Any]:
    rng = random.Random(9)
    n = 180
    x = [math.sin(i * 0.5) + 0.2 * math.cos(i * 1.1) for i in range(n)]
    y = [2.0 * v + rng.gauss(0, 0.3) for v in x]
    return {"data": {"series": {"y": y, "x": x}}, "params": {}, "expect": {"gate": "ok"}}


def _tracking_synthetic() -> Dict[str, Any]:
    n = 120
    y = [math.sin(i * 0.2) for i in range(n)]
    x = [v + 0.002 for v in y]
    return {"data": {"x": x, "y": y}, "params": {}, "expect": {"result.te": 0.0}}


def _collinear_panel() -> Dict[str, Any]:
    n = 120
    a = [float(i) for i in range(n)]
    return {"series": {"A": a, "B": [2.0 * v for v in a], "C": [-1.5 * v for v in a]}}


def _pca_synthetic() -> Dict[str, Any]:
    return {
        "data": _collinear_panel(),
        "params": {},
        "expect": {"result.ratio.0": 1.0, "result.k": 3},
    }


def _loadings_synthetic() -> Dict[str, Any]:
    return {
        "data": _collinear_panel(),
        "params": {},
        "expect": {"result.k": 3, "result.n_features": 3},
    }


def _cluster_synthetic() -> Dict[str, Any]:
    rng = random.Random(3)
    n = 120
    series: Dict[str, List[float]] = {}
    for gi in range(3):
        base = [rng.gauss(0, 1) for _ in range(n)]
        for j in range(2):
            series[f"g{gi}_{j}"] = [v + 0.02 * rng.gauss(0, 1) for v in base]
    return {"data": {"series": series}, "params": {"k": 3}, "expect": {"result.n_clusters": 3}}


def _exposure_synthetic() -> Dict[str, Any]:
    rng = random.Random(17)
    n = 160
    market = [rng.gauss(0, 1) for _ in range(n)]
    size = [rng.gauss(0, 1) for _ in range(n)]
    momentum = [rng.gauss(0, 1) for _ in range(n)]
    y = [
        1.5 * a - 0.5 * b + 0.8 * c + 1e-3 * rng.gauss(0, 1)
        for a, b, c in zip(market, size, momentum, strict=False)
    ]
    return {
        "data": {"target": y, "factors": {"market": market, "size": size, "momentum": momentum}},
        "params": {},
        "expect": {
            "result.exposures.market": 1.5,
            "result.exposures.size": -0.5,
            "result.exposures.momentum": 0.8,
        },
    }


# ============================================================
# M08–M10
# ============================================================


@register(
    "M08",
    name="偏相关",
    group="M",
    layer="D2",
    input_kind="panel",
    min_n=CCF_MIN_N,
    output_schema=("r", "r_xy", "p", "n", "control"),
    notes=(
        "一阶偏相关 r_xy·z=(r_xy−r_xz·r_yz)/√((1−r_xz²)(1−r_yz²))；"
        "三列默认按顺序取 x/y/z，可用 params x/y/z 指定名称或下标；"
        "p 的自由度 n−3；仅支持单个控制变量"
    ),
    checks=MethodChecks(synthetic=_partial_synthetic),
)
def m08_partial_corr(
    data: Any, x: Any = None, y: Any = None, z: Any = None, **_: Any
) -> Dict[str, Any]:
    names, cols = _columns(data)
    if len(names) < 3:
        raise ValueError(f"partial correlation needs 3 columns, got {len(names)}")
    _x_name, xv = _named_column(names, cols, x, 0)
    _y_name, yv = _named_column(names, cols, y, 1)
    z_name, zv = _named_column(names, cols, z, 2)
    n = min(len(xv), len(yv), len(zv))
    r_xy = pearson(xv[:n], yv[:n])
    r_xz = pearson(xv[:n], zv[:n])
    r_yz = pearson(yv[:n], zv[:n])
    denom = math.sqrt(max(0.0, (1.0 - r_xz**2) * (1.0 - r_yz**2)))
    r = None if denom <= _EPS else (r_xy - r_xz * r_yz) / denom
    r = None if r is None else max(-1.0, min(1.0, r))
    return {
        "r": r6(r),
        "r_xy": r6(r_xy),
        "p": corr_p(r, n - 1) if r is not None else None,
        "n": n,
        "control": z_name,
    }


@register(
    "M09",
    name="距离相关",
    group="M",
    layer="D2",
    input_kind="pairs",
    min_n=PAIRS_MIN_N,
    output_schema=("dcor", "dcor2", "n"),
    notes=(
        "Székely 距离相关 dCor=√(dCov²/√(dVar_x·dVar_y))，∈[0,1]，"
        "0 当且仅当独立；对平移/正缩放不变；O(n²)"
    ),
    checks=MethodChecks(synthetic=_dcor_synthetic),
)
def m09_distance_corr(data: Mapping[str, Any], **_: Any) -> Dict[str, Any]:
    np = _np()
    x, y = _pairs(data)
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    a = np.abs(xa[:, None] - xa[None, :])
    b = np.abs(ya[:, None] - ya[None, :])
    a = a - a.mean(axis=0, keepdims=True) - a.mean(axis=1, keepdims=True) + a.mean()
    b = b - b.mean(axis=0, keepdims=True) - b.mean(axis=1, keepdims=True) + b.mean()
    dcov2 = float((a * b).mean())
    dvar_x = float((a * a).mean())
    dvar_y = float((b * b).mean())
    denom = math.sqrt(max(dvar_x * dvar_y, 0.0))
    dcor = 0.0 if denom <= _EPS else math.sqrt(max(dcov2, 0.0) / denom)
    dcor = max(0.0, min(1.0, dcor))
    return {"dcor": r6(dcor), "dcor2": r6(dcor**2), "n": len(x)}


@register(
    "M10",
    name="互信息",
    group="M",
    layer="D2",
    input_kind="pairs",
    min_n=PAIRS_MIN_N,
    output_schema=("mi", "nmi", "bins", "n"),
    notes=(
        "等频分箱（默认 8 箱）离散互信息，单位 nats；"
        "nmi=MI/min(H_x,H_y)∈[0,1]，1 表示完全确定关系"
    ),
    checks=MethodChecks(synthetic=_mi_synthetic),
)
def m10_mutual_info(data: Mapping[str, Any], bins: int = 8, **_: Any) -> Dict[str, Any]:
    np = _np()
    x, y = _pairs(data)
    k = max(2, int(bins))
    bx = _equal_freq_ids(np.asarray(x, dtype=float), k)
    by = _equal_freq_ids(np.asarray(y, dtype=float), k)
    joint = np.zeros((k, k), dtype=float)
    np.add.at(joint, (bx, by), 1.0)
    joint /= joint.sum()
    px = joint.sum(axis=1)
    py = joint.sum(axis=0)
    outer = np.outer(px, py)
    mask = joint > 0
    mi = float(np.sum(joint[mask] * np.log(joint[mask] / outer[mask])))
    hx = float(-np.sum(px[px > 0] * np.log(px[px > 0])))
    hy = float(-np.sum(py[py > 0] * np.log(py[py > 0])))
    floor = min(hx, hy)
    nmi = 0.0 if floor <= _EPS else mi / floor
    return {
        "mi": r6(max(0.0, mi)),
        "nmi": r6(max(0.0, min(1.0, nmi))),
        "bins": k,
        "n": len(x),
    }


# ============================================================
# M13–M16 协整与回归
# ============================================================


@register(
    "M13",
    name="协整（Engle-Granger）",
    group="M",
    layer="D3",
    input_kind="pairs",
    min_n=CCF_MIN_N,
    output_schema=("p", "beta", "stat", "n", "crit_5pct"),
    notes=(
        "y~x 含常数 OLS 取残差，ADF 用 statsmodels.coint（MacKinnon p，AIC 选阶）；"
        "p<0.05 拒绝『无协整』；beta 为静态 OLS 斜率（未做 DOLS/FM 修正）"
    ),
    checks=MethodChecks(synthetic=_coint_synthetic),
)
def m13_cointegration(data: Mapping[str, Any], **_: Any) -> Dict[str, Any]:
    from statsmodels.tsa.stattools import coint

    x, y = _pairs(data)
    if len(x) < 30:
        raise ValueError("cointegration needs n>=30")
    stat, p, crit = coint(y, x, trend="c", autolag="aic")
    fit = _multi_ols(y, [x], ["x"])
    return {
        "p": float(p),
        "beta": r6(fit["betas"]["x"]),
        "stat": r6(float(stat)),
        "n": len(x),
        "crit_5pct": r6(float(crit[1])),
    }


@register(
    "M14",
    name="OLS 单因子回归",
    group="M",
    layer="D3",
    input_kind="pairs",
    min_n=PAIRS_MIN_N,
    output_schema=("beta", "alpha", "r2", "t", "p", "n"),
    notes=(
        "y~x 含截距 OLS（numpy.lstsq）；t/p 用 (X'X)⁻¹σ² 标准误与 t 分布；" "x 为自变量、y 为因变量"
    ),
    checks=MethodChecks(synthetic=_ols_synthetic),
)
def m14_ols(data: Mapping[str, Any], **_: Any) -> Dict[str, Any]:
    x, y = _pairs(data)
    fit = _multi_ols(y, [x], ["x"])
    return {
        "beta": r6(fit["betas"]["x"]),
        "alpha": r6(fit["alpha"]),
        "r2": r4(fit["r2"]),
        "t": fit["t"]["x"],
        "p": fit["p"]["x"],
        "n": fit["n"],
    }


@register(
    "M15",
    name="多因子回归",
    group="M",
    layer="D3",
    input_kind="panel",
    min_n=CCF_MIN_N,
    output_schema=("betas", "alpha", "r2", "t", "p", "n", "factor_names"),
    notes=(
        "y~1+X 多元 OLS；target 由 params.target 指定（默认 'y'，无则最后一列），"
        "其余列为因子；params.factors 可选子集；t/p 为双侧 t 检验"
    ),
    checks=MethodChecks(synthetic=_multi_factor_synthetic),
)
def m15_multi_factor(
    data: Any, target: Optional[str] = None, factors: Optional[Sequence[str]] = None, **_: Any
) -> Dict[str, Any]:
    y, names, cols, n = _target_and_factors(data, target, factors)
    fit = _multi_ols(y, cols, names)
    return {
        "betas": {k: r6(v) for k, v in fit["betas"].items()},
        "alpha": r6(fit["alpha"]),
        "r2": r4(fit["r2"]),
        "t": fit["t"],
        "p": fit["p"],
        "n": n,
        "factor_names": names,
    }


@register(
    "M16",
    name="回归残差平稳性",
    group="M",
    layer="D3",
    input_kind="panel",
    min_n=CCF_MIN_N,
    output_schema=("p", "adf", "n", "lags", "r2"),
    notes=(
        "先做多元 OLS（params.target/factors，缺省 y~x）取残差，再跑 ADF"
        "（含常数、AIC 选阶）；p<0.05 视为残差平稳；n 为 ADF 回归有效样本数"
    ),
    checks=MethodChecks(synthetic=_resid_synthetic),
)
def m16_resid_stationarity(
    data: Any, target: Optional[str] = None, factors: Optional[Sequence[str]] = None, **_: Any
) -> Dict[str, Any]:
    y, names, cols, _n = _target_and_factors(data, target, factors)
    fit = _multi_ols(y, cols, names)
    adf = _adf_test(fit["resid"])
    return {
        "p": adf["p"],
        "adf": r4(adf["stat"]) if adf["stat"] is not None else None,
        "n": adf["n"],
        "lags": adf["lags"],
        "r2": r4(fit["r2"]),
    }


# ============================================================
# M18–M22 跟踪误差 / 降维 / 聚类
# ============================================================


@register(
    "M18",
    name="跟踪误差",
    group="M",
    layer="D1",
    input_kind="pairs",
    min_n=PAIRS_MIN_N,
    output_schema=("te", "te_annual", "mean_excess", "n"),
    notes=(
        "x=组合收益、y=基准收益；te=std(x−y, ddof=1)，"
        "te_annual=te×√ann_factor（params.ann_factor，默认 252）"
    ),
    checks=MethodChecks(synthetic=_tracking_synthetic),
)
def m18_tracking_error(data: Mapping[str, Any], ann_factor: int = 252, **_: Any) -> Dict[str, Any]:
    np = _np()
    x, y = _pairs(data)
    diff = np.asarray(x, dtype=float) - np.asarray(y, dtype=float)
    te = float(diff.std(ddof=1))
    return {
        "te": r6(te),
        "te_annual": r6(te * math.sqrt(float(ann_factor))),
        "mean_excess": r6(float(diff.mean())),
        "n": len(x),
    }


@register(
    "M19",
    name="PCA 解释方差",
    group="M",
    layer="D3",
    input_kind="panel",
    min_n=PAIRS_MIN_N,
    output_schema=("ratio", "cum_ratio", "k", "n", "n_features"),
    notes=(
        "对列做 z-score 标准化后 SVD（相关阵口径）；ratio_i=λ_i/Σλ（降序）；"
        "k 默认 min(3, 变量数)；要求变量非常数"
    ),
    checks=MethodChecks(synthetic=_pca_synthetic),
)
def m19_pca_variance(data: Any, k: Optional[int] = None, **_: Any) -> Dict[str, Any]:
    core = _pca_core(data, k)
    return {
        "ratio": [r6(v) for v in core["ratio"]],
        "cum_ratio": [r6(v) for v in core["cum"]],
        "k": core["k"],
        "n": core["n"],
        "n_features": core["m"],
    }


@register(
    "M20",
    name="PCA 载荷",
    group="M",
    layer="D3",
    input_kind="panel",
    min_n=PAIRS_MIN_N,
    output_schema=("loadings", "names", "explained", "k", "n_features"),
    notes=(
        "载荷=√λ_i·v_ij（标准化口径下等同 corr(变量, PC_i)）；"
        "符号约定：每个主成分绝对值最大载荷为正"
    ),
    checks=MethodChecks(synthetic=_loadings_synthetic),
)
def m20_pca_loadings(data: Any, k: Optional[int] = None, **_: Any) -> Dict[str, Any]:
    core = _pca_core(data, k)
    loadings = [
        {name: r6(val) for name, val in zip(core["names"], row, strict=False)}
        for row in core["load"]
    ]
    return {
        "loadings": loadings,
        "names": core["names"],
        "explained": [r6(v) for v in core["ratio"]],
        "k": core["k"],
        "n_features": core["m"],
    }


@register(
    "M21",
    name="层次聚类",
    group="M",
    layer="D3",
    input_kind="panel",
    min_n=PAIRS_MIN_N,
    output_schema=("labels", "names", "k", "n_clusters", "n"),
    notes=(
        "距离 d=1−ρ（相关系数缺失记 1，截断到 [0,2]），average 链接 + "
        "fcluster(maxclust=k)；确定性，无随机数"
    ),
    checks=MethodChecks(synthetic=_cluster_synthetic),
)
def m21_hierarchical(data: Any, k: int = 3, method: str = "average", **_: Any) -> Dict[str, Any]:
    np = _np()
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    names, cols = _columns(data)
    m = len(cols)
    if m < 2:
        raise ValueError("clustering needs >= 2 variables")
    rmat = np.eye(m)
    for i in range(m):
        for j in range(i + 1, m):
            r = _safe_pearson(cols[i], cols[j])
            rmat[i, j] = rmat[j, i] = 0.0 if r is None else float(r)
    dist = np.clip(1.0 - rmat, 0.0, 2.0)
    np.fill_diagonal(dist, 0.0)
    tree = linkage(squareform(dist, checks=False), method=method)
    kk = max(1, min(int(k), m))
    raw = fcluster(tree, t=kk, criterion="maxclust")
    labels = {name: int(lab) for name, lab in zip(names, raw, strict=False)}
    return {
        "labels": labels,
        "names": names,
        "k": kk,
        "n_clusters": len(set(labels.values())),
        "n": len(cols[0]),
    }


@register(
    "M22",
    name="K-Means 分群",
    group="M",
    layer="D3",
    input_kind="panel",
    min_n=PAIRS_MIN_N,
    output_schema=("labels", "names", "k", "n_clusters", "n", "inertia"),
    notes=(
        "每个资产序列 z-score 后 KMeans（random_state=0，n_init=10）；"
        "标签仅表示分群、数值无顺序含义；确定性"
    ),
    checks=MethodChecks(synthetic=_cluster_synthetic),
)
def m22_kmeans(data: Any, k: int = 3, **_: Any) -> Dict[str, Any]:
    np = _np()
    from sklearn.cluster import KMeans

    names, cols = _columns(data)
    m = len(cols)
    if m < 2:
        raise ValueError("K-Means needs >= 2 variables")
    xm = np.asarray(cols, dtype=float)
    sd = xm.std(axis=1, ddof=1, keepdims=True)
    if bool(np.any(sd <= _EPS)):
        raise ValueError("K-Means needs non-constant series")
    z = (xm - xm.mean(axis=1, keepdims=True)) / sd
    kk = max(1, min(int(k), m))
    model = KMeans(n_clusters=kk, random_state=0, n_init=10).fit(z)
    labels = {name: int(lab) for name, lab in zip(names, model.labels_, strict=False)}
    return {
        "labels": labels,
        "names": names,
        "k": kk,
        "n_clusters": len(set(labels.values())),
        "n": len(cols[0]),
        "inertia": r6(float(model.inertia_)),
    }


# ============================================================
# M26 简化因子暴露
# ============================================================


@register(
    "M26",
    name="因子暴露（简化）",
    group="M",
    layer="D3",
    input_kind="panel",
    min_n=CCF_MIN_N,
    output_schema=("exposures", "alpha", "r2", "t", "n", "factor_names"),
    notes=(
        "简化 Fama 口径：优先取 market/size/momentum 三因子，缺失时退化为全部列；"
        "exposures 即回归 beta（未做行业中性化、去极值与标准化）"
    ),
    checks=MethodChecks(synthetic=_exposure_synthetic),
)
def m26_factor_exposure(
    data: Any,
    target: Optional[str] = None,
    factors: Sequence[str] = ("market", "size", "momentum"),
    **_: Any,
) -> Dict[str, Any]:
    y, names, all_cols, n = _target_and_factors(data, target, None)
    wanted = [f for f in factors if f in names] or names
    cols = [all_cols[names.index(f)] for f in wanted]
    fit = _multi_ols(y, cols, wanted)
    return {
        "exposures": {k: r6(v) for k, v in fit["betas"].items()},
        "alpha": r6(fit["alpha"]),
        "r2": r4(fit["r2"]),
        "t": fit["t"],
        "n": n,
        "factor_names": wanted,
    }
