# -*- coding: utf-8 -*-
"""科研方法族 SC47–SC92（变点/趋势、信息论、极值、空间网络、生存、meta、数据质量、季节调整）。

来源：docs/RESEARCH-SCIENTIFIC-METHODS.md §2.5–§2.13。
编号/名称/层级/最小样本取自 `research.spec_of`（SSoT），本模块只负责真实实现。

约束：
  - 无网络、无 DB、无 LLM；随机过程固定 seed（社区发现 seed=42，其余方法无随机）；
  - 输入契约在函数内兼容 series / x-y / matrix / coords+values / table；
  - 输出键与 `output_schema` 完全一致，浮点统一 6 位（比率类 4 位）；
  - 文档未给完整算法时给确定性标准简化版，并在 notes 标注“简化口径”。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import numpy as np
from scipy import stats as sps
from scipy.signal import coherence as _sp_coherence
from scipy.spatial.distance import cdist

from .registry import MethodChecks, register
from .research import spec_of

_EPS = 1e-12
_SEED = 42


# ---------------------------------------------------------------- 通用工具


def _f(v: Any, nd: int = 6) -> Any:
    """float 收敛：非有限返回 None，其余按 nd 位四舍五入。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


def _lst(v: Any, nd: int = 6) -> List[Any]:
    arr = np.asarray(v, dtype=float).ravel()
    return [_f(x, nd) for x in arr]


def _mtx(v: Any, nd: int = 6) -> List[List[Any]]:
    arr = np.asarray(v, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    return [[_f(x, nd) for x in row] for row in arr]


def _is_nested(seq: Any) -> bool:
    if isinstance(seq, (str, bytes)):
        return False
    try:
        first = list(seq)[0]
    except (TypeError, IndexError):
        return False
    return isinstance(first, (list, tuple, np.ndarray))


def _vals(seq: Any) -> np.ndarray:
    """一维数值数组（去 None / 非有限 / 不可转数值）。"""
    out: List[float] = []
    for v in list(seq):
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):
            out.append(x)
    return np.asarray(out, dtype=float)


def _series(data: Any) -> np.ndarray:
    if isinstance(data, Mapping):
        for key in ("x", "series", "values", "value", "y", "returns", "price", "indicator"):
            if key in data and not _is_nested(data[key]):
                return _vals(data[key])
        raise ValueError("series data must contain x/series/values/value/y")
    return _vals(data)


def _matrix(data: Any, *keys: str) -> np.ndarray:
    """数值矩阵：X/matrix/design/features/table/records 或 list-of-lists（保留 NaN）。"""
    names = keys or ("X", "matrix", "design", "features", "table", "records", "data")
    if isinstance(data, Mapping):
        for key in names:
            if key in data and _is_nested(data[key]):
                rows = list(data[key])
                return np.asarray(
                    [[np.nan if v is None else float(v) for v in row] for row in rows], dtype=float
                )
        cols = []
        for key, val in data.items():
            if key in (
                "y",
                "target",
                "value",
                "label",
                "group",
                "state",
                "time",
                "event",
                "season",
                "coords",
                "rules",
                "edges",
                "n_nodes",
                "available",
                "used",
                "keys",
                "n",
            ):
                continue
            if isinstance(val, (list, tuple, np.ndarray)) and not _is_nested(val):
                cols.append(_vals(val))
        if cols:
            m = min(len(c) for c in cols)
            return np.column_stack([c[:m] for c in cols])
        raise ValueError("matrix data must contain X/matrix/design or numeric columns")
    arr = np.asarray(data, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    return arr


def _pair(data: Any) -> Tuple[np.ndarray, np.ndarray]:
    if not isinstance(data, Mapping):
        raise ValueError("paired data must be a mapping")
    if "x" in data and "y" in data:
        a, b = _vals(data["x"]), _vals(data["y"])
    elif "factor" in data and "target" in data:
        a, b = _vals(data["factor"]), _vals(data["target"])
    else:
        raise ValueError("paired data must contain x/y or factor/target")
    n = min(len(a), len(b))
    return a[:n], b[:n]


def _meta(mid: str, **over: Any) -> Dict[str, Any]:
    """从 SSoT 取 name/group/layer/min_n（编号唯一口径）。"""
    _, name, group, layer, min_n = spec_of(mid)
    out = {"name": name, "group": group, "layer": layer, "min_n": min_n}
    out.update(over)
    return out


def _coords_values(data: Any) -> Tuple[np.ndarray, np.ndarray]:
    """空间输入：{coords|locs: [[x,y],...], values|z: [...]}。"""
    if not isinstance(data, Mapping):
        raise ValueError("spatial data must be a mapping with coords and values")
    coords = None
    for key in ("coords", "locs", "locations", "xy"):
        if key in data:
            coords = np.asarray(data[key], dtype=float)
            break
    if coords is None and "x" in data and "y" in data and not _is_nested(data["x"]):
        xs, ys = _vals(data["x"]), _vals(data["y"])
        n = min(len(xs), len(ys))
        coords = np.column_stack([xs[:n], ys[:n]])
    if coords is None:
        raise ValueError("spatial data needs coords/locs or x+y")
    if coords.ndim == 1:
        coords = coords.reshape(-1, 1)
    vals = None
    for key in ("values", "z", "value", "observed"):
        if key in data:
            vals = _vals(data[key])
            break
    if vals is None:
        raise ValueError("spatial data needs values/z")
    m = min(len(vals), len(coords))
    return coords[:m], vals[:m]


def _weights(coords: np.ndarray, k: int = 4) -> np.ndarray:
    """k 近邻二进制权重（对称化 + 行标准化，行列和=1）。"""
    n = len(coords)
    d = cdist(coords, coords)
    np.fill_diagonal(d, np.inf)
    kk = int(max(1, min(int(k), n - 1)))
    w = np.zeros((n, n), dtype=float)
    for i in range(n):
        idx = np.argsort(d[i], kind="stable")[:kk]
        w[i, idx] = 1.0
    w = np.maximum(w, w.T)
    np.fill_diagonal(w, 0.0)
    row = w.sum(axis=1)
    row[row <= 0] = 1.0
    return w / row[:, None]


def _time_event(data: Any) -> Tuple[np.ndarray, np.ndarray]:
    """生存输入：{time|duration|durations, event|status|failed}。"""
    if not isinstance(data, Mapping):
        raise ValueError("survival data must be a mapping with time and event")
    t = None
    for key in ("time", "duration", "durations", "t"):
        if key in data:
            t = _vals(data[key])
            break
    if t is None:
        raise ValueError("survival data needs time/duration")
    e = None
    for key in ("event", "status", "failed", "observed"):
        if key in data:
            e = _vals(data[key])
            break
    if e is None:
        e = np.ones_like(t)
    m = min(len(t), len(e))
    return t[:m], (e[:m] > 0).astype(float)


def _effect_se(data: Any) -> Tuple[np.ndarray, np.ndarray]:
    """meta 输入：{effect|effects|y, se|stderr|sigma}；同时兼容 {x, y} 别名（x=效应, y=标准误）。"""
    if not isinstance(data, Mapping):
        raise ValueError("meta data must be a mapping with effect and se")
    eff = None
    for key in ("effect", "effects", "estimate", "beta"):
        if key in data:
            eff = _vals(data[key])
            break
    se = None
    for key in ("se", "stderr", "sigma", "sd"):
        if key in data:
            se = _vals(data[key])
            break
    if (eff is None or se is None) and "x" in data and "y" in data:
        eff, se = _vals(data["x"]), _vals(data["y"])
    if eff is None:
        raise ValueError("meta data needs effect/effects")
    if se is None:
        raise ValueError("meta data needs se/stderr")
    m = min(len(eff), len(se))
    eff = eff[:m]
    se = se[:m]
    keep = se > 0
    return eff[keep], se[keep]


def _dl(eff: np.ndarray, se: np.ndarray) -> Dict[str, float]:
    """固定效应 + DerSimonian-Laird 随机效应共用口径。"""
    w = 1.0 / se**2
    pooled_fe = float(np.sum(w * eff) / np.sum(w))
    q = float(np.sum(w * (eff - pooled_fe) ** 2))
    df = len(eff) - 1
    c = float(np.sum(w) - np.sum(w**2) / np.sum(w))
    tau2 = max(0.0, (q - df) / c) if c > _EPS else 0.0
    ws = 1.0 / (se**2 + tau2)
    pooled = float(np.sum(ws * eff) / np.sum(ws))
    se_pooled = float(math.sqrt(1.0 / np.sum(ws)))
    i2 = max(0.0, min(1.0, (q - df) / q)) if q > _EPS else 0.0
    return {
        "fe": pooled_fe,
        "q": q,
        "df": float(df),
        "tau2": tau2,
        "re": pooled,
        "se_re": se_pooled,
        "i2": i2,
    }


# ---------------------------------------------------------------- SC47–SC54


@register(
    "SC47",
    **_meta("SC47"),
    input_kind="series",
    output_schema=("state", "gain", "loglik", "last_state", "n"),
    notes="局部水平状态空间（固定 Q/R），标量卡尔曼递推；gain 为逐期卡尔曼增益",
)
def sc47_kalman(data: Any, process_var: float = 0.01, obs_var: float = 1.0) -> Dict[str, Any]:
    y = _series(data)
    q, r = max(float(process_var), _EPS), max(float(obs_var), _EPS)
    x, p = float(y[0]), 1.0
    states: List[float] = []
    gains: List[float] = []
    ll = 0.0
    for v in y:
        p_pred = p + q
        k = p_pred / (p_pred + r)
        innov = float(v) - x
        x = x + k * innov
        p = (1.0 - k) * p_pred
        states.append(x)
        gains.append(k)
        ll += -0.5 * (math.log(2.0 * math.pi * (p_pred + r)) + innov**2 / (p_pred + r))
    return {
        "state": _lst(states),
        "gain": _lst(gains),
        "loglik": _f(ll),
        "last_state": _f(states[-1]),
        "n": len(y),
    }


@register(
    "SC48",
    **_meta("SC48"),
    input_kind="pairs",
    output_schema=("freqs", "coherence", "peak_coherence", "peak_freq", "nperseg", "n"),
    notes="scipy.signal.coherence（Welch 平均，fs=1，nperseg=min(32,n//2)，简化口径）",
)
def sc48_coherence(data: Any, nperseg: int = 0) -> Dict[str, Any]:
    xs, ys = _pair(data)
    n = len(xs)
    seg = int(nperseg) if nperseg else max(8, min(32, n // 2))
    seg = min(seg, n)
    f, cxy = _sp_coherence(xs, ys, fs=1.0, nperseg=seg, detrend="constant")
    cxy = np.nan_to_num(cxy, nan=0.0)
    i = int(np.argmax(cxy))
    return {
        "freqs": _lst(f),
        "coherence": _lst(cxy),
        "peak_coherence": _f(cxy[i], 4),
        "peak_freq": _f(f[i]),
        "nperseg": seg,
        "n": n,
    }


def _cusum_points(y: np.ndarray, threshold: float, min_size: int = 5) -> List[int]:
    """CUSUM 二元分割变点（标准化累计和 |CUSUM| 超阈值即切分，栈式迭代避免深递归）。"""
    points: List[int] = []
    stack: List[Tuple[int, int]] = [(0, len(y))]
    while stack:
        lo, hi = stack.pop()
        seg = y[lo:hi]
        m = len(seg)
        if m < 2 * min_size:
            continue
        mu, sd = float(np.mean(seg)), float(np.std(seg, ddof=1))
        if sd <= _EPS:
            continue
        z = np.cumsum(seg - mu) / (sd * math.sqrt(m))
        cand = np.abs(z[min_size : m - min_size])
        if cand.size == 0:
            continue
        cp = int(min_size + int(np.argmax(cand)))
        if float(abs(z[cp])) <= float(threshold):
            continue
        points.append(lo + cp)
        stack.append((lo, lo + cp))
        stack.append((lo + cp, hi))
    return sorted(points)


@register(
    "SC49",
    **_meta("SC49"),
    input_kind="series",
    output_schema=("breakpoints", "max_abs", "threshold", "n"),
    notes="CUSUM 二元分割：标准化累计和 |CUSUM| 超阈值即在该处切分并递归（简化口径）",
)
def sc49_cusum(data: Any, threshold: float = 1.5) -> Dict[str, Any]:
    x = _series(data)
    n = len(x)
    points = _cusum_points(x, float(threshold))
    mu, sd = float(np.mean(x)), float(np.std(x, ddof=1))
    if sd > _EPS:
        z = np.cumsum(x - mu) / (sd * math.sqrt(n))
        peak = float(np.max(np.abs(z[5 : n - 5]))) if n > 10 else float(np.max(np.abs(z)))
    else:
        peak = 0.0
    return {"breakpoints": points, "max_abs": _f(peak), "threshold": float(threshold), "n": n}


def _seg_cost(cs: np.ndarray, cs2: np.ndarray, i: int, j: int) -> float:
    m = j - i
    if m <= 0:
        return float("inf")
    s = cs[j] - cs[i]
    return float(cs2[j] - cs2[i] - s * s / m)


@register(
    "SC50",
    **_meta("SC50"),
    input_kind="series",
    output_schema=("breakpoints", "n_changepoints", "penalty", "n", "method"),
    notes="精确最小二乘分段（等价 PELT 全局最优，O(n²) DP），惩罚 = pen·σ²·ln n",
)
def sc50_pelt(data: Any, pen_factor: float = 3.0) -> Dict[str, Any]:
    y = _series(data)
    n = len(y)
    cs = np.concatenate([[0.0], np.cumsum(y)])
    cs2 = np.concatenate([[0.0], np.cumsum(y * y)])
    sigma2 = float(np.var(y, ddof=1)) if n > 1 else 1.0
    sigma2 = max(sigma2, _EPS)
    pen = float(pen_factor) * sigma2 * math.log(max(n, 2))
    best = np.full(n + 1, np.inf)
    prev = np.zeros(n + 1, dtype=int)
    best[0] = -pen
    for j in range(1, n + 1):
        costs = np.array([best[i] + _seg_cost(cs, cs2, i, j) for i in range(j)])
        i = int(np.argmin(costs))
        best[j] = costs[i] + pen
        prev[j] = i
    points: List[int] = []
    j = n
    while j > 0:
        i = int(prev[j])
        if i > 0:
            points.append(i)
        j = i
    points.reverse()
    return {
        "breakpoints": points,
        "n_changepoints": len(points),
        "penalty": _f(pen),
        "n": n,
        "method": "exact_dp_l2",
    }


@register(
    "SC51",
    **_meta("SC51"),
    input_kind="series",
    output_schema=("k", "point", "p", "n"),
    notes="Pettitt 非参数单变点：K=max|U_t|，p≈2exp(−6K²/(n³+n²))",
)
def sc51_pettitt(data: Any) -> Dict[str, Any]:
    x = _series(data)
    n = len(x)
    ranks = sps.rankdata(x)
    u = 2.0 * np.cumsum(ranks) - np.arange(1, n + 1) * (n + 1)
    k = float(np.max(np.abs(u)))
    point = int(np.argmax(np.abs(u)))
    p = float(min(1.0, 2.0 * math.exp(-6.0 * k * k / (n**3 + n**2))))
    return {"k": _f(k), "point": point, "p": _f(min(p, 1.0)), "n": n}


@register(
    "SC52",
    **_meta("SC52"),
    input_kind="series",
    output_schema=("s", "tau", "z", "p", "trend", "n"),
    notes="Mann-Kendall S 统计量 + 结值方差修正 + 连续性校正正态近似",
)
def sc52_mann_kendall(data: Any, alpha: float = 0.05) -> Dict[str, Any]:
    x = _series(data)
    n = len(x)
    s = 0.0
    for i in range(n - 1):
        s += float(np.sum(np.sign(x[i + 1 :] - x[i])))
    _, counts = np.unique(x, return_counts=True)
    ties = np.sum(counts * (counts - 1) * (2 * counts + 5))
    var_s = (n * (n - 1) * (2 * n + 5) - ties) / 18.0
    if var_s > _EPS:
        z = (s - math.copysign(1.0, s)) / math.sqrt(var_s) if s != 0 else 0.0
        p = float(2.0 * (1.0 - sps.norm.cdf(abs(z))))
    else:
        z, p = 0.0, 1.0
    tau = s / (0.5 * n * (n - 1)) if n > 1 else 0.0
    trend = "no trend"
    if p < alpha:
        trend = "increasing" if s > 0 else "decreasing"
    return {"s": _f(s), "tau": _f(tau, 4), "z": _f(z), "p": _f(p), "trend": trend, "n": n}


@register(
    "SC53",
    **_meta("SC53"),
    input_kind="series",
    output_schema=("slope", "ci_low", "ci_high", "intercept", "n"),
    notes="Sen 中位斜率；CI 用 MK 方差 + 斜率秩区间（简化口径）",
)
def sc53_sen(data: Any, alpha: float = 0.05) -> Dict[str, Any]:
    x = _series(data)
    n = len(x)
    parts: List[np.ndarray] = []
    for i in range(n - 1):
        parts.append((x[i + 1 :] - x[i]) / np.arange(1, n - i))
    slopes = np.concatenate(parts) if parts else np.array([0.0])
    slope = float(np.median(slopes))
    ss = np.sort(slopes)
    n_pairs = len(ss)
    _, counts = np.unique(x, return_counts=True)
    ties = np.sum(counts * (counts - 1) * (2 * counts + 5))
    var_s = max((n * (n - 1) * (2 * n + 5) - ties) / 18.0, 0.0)
    c_alpha = sps.norm.ppf(1.0 - alpha / 2.0) * math.sqrt(var_s)
    lo_idx = int(max(0, math.floor((n_pairs - c_alpha) / 2.0) - 1))
    hi_idx = int(min(n_pairs - 1, math.ceil((n_pairs + c_alpha) / 2.0) - 1))
    intercept = float(np.median(x - slope * np.arange(n)))
    return {
        "slope": _f(slope),
        "ci_low": _f(ss[lo_idx]),
        "ci_high": _f(ss[hi_idx]),
        "intercept": _f(intercept),
        "n": n,
    }


@register(
    "SC54",
    **_meta("SC54"),
    input_kind="series",
    output_schema=("s", "z", "p", "trend", "n_seasons", "n"),
    notes="季节 Mann-Kendall：各季 S 与方差相加后做正态近似（可给 season 分组或 period）",
)
def sc54_seasonal_mk(data: Any, period: int = 12, alpha: float = 0.05) -> Dict[str, Any]:
    x = _series(data)
    n = len(x)
    if isinstance(data, Mapping) and "season" in data:
        labels = [str(v) for v in data["season"]][:n]
        groups: Dict[str, List[float]] = {}
        for g, v in zip(labels, x, strict=False):
            groups.setdefault(g, []).append(v)
        blocks = list(groups.values())
    else:
        p = max(1, int(period))
        blocks = [x[i::p] for i in range(p)]
    s_tot, var_tot = 0.0, 0.0
    for blk in blocks:
        arr = np.asarray(blk, dtype=float)
        m = len(arr)
        if m < 3:
            continue
        s = 0.0
        for i in range(m - 1):
            s += float(np.sum(np.sign(arr[i + 1 :] - arr[i])))
        _, counts = np.unique(arr, return_counts=True)
        ties = np.sum(counts * (counts - 1) * (2 * counts + 5))
        s_tot += s
        var_tot += (m * (m - 1) * (2 * m + 5) - ties) / 18.0
    if var_tot > _EPS:
        z = (s_tot - math.copysign(1.0, s_tot)) / math.sqrt(var_tot) if s_tot != 0 else 0.0
        p = float(2.0 * (1.0 - sps.norm.cdf(abs(z))))
    else:
        z, p = 0.0, 1.0
    trend = "no trend"
    if p < alpha:
        trend = "increasing" if s_tot > 0 else "decreasing"
    return {
        "s": _f(s_tot),
        "z": _f(z),
        "p": _f(p),
        "trend": trend,
        "n_seasons": len(blocks),
        "n": n,
    }


# ---------------------------------------------------------------- SC55–SC62


def _entropy(counts: np.ndarray) -> float:
    p = np.asarray(counts, dtype=float).ravel()
    p = p[p > 0]
    if p.size == 0:
        return 0.0
    p = p / p.sum()
    return float(-np.sum(p * np.log(p)))


def _bin_labels(x: np.ndarray, bins: int) -> np.ndarray:
    """等频分箱（分位点去重），返回 0..k−1 整数标签。"""
    qs = np.linspace(0.0, 1.0, int(bins) + 1)[1:-1]
    edges = np.unique(np.quantile(x, qs))
    return np.searchsorted(edges, x, side="right")


@register(
    "SC55",
    **_meta("SC55"),
    input_kind="series",
    output_schema=("h", "h_norm", "bins", "n"),
    notes="等宽直方图概率质量（bins=10 固定），自然对数；h_norm=h/ln(bins)",
)
def sc55_shannon_entropy(data: Any, bins: int = 10) -> Dict[str, Any]:
    x = _series(data)
    hist, _ = np.histogram(x, bins=int(bins))
    h = _entropy(hist)
    return {
        "h": _f(h),
        "h_norm": _f(h / math.log(int(bins)) if bins > 1 else 0.0, 4),
        "bins": int(bins),
        "n": len(x),
    }


@register(
    "SC56",
    **_meta("SC56"),
    input_kind="pairs",
    output_schema=("mi", "mi_norm", "bins", "n"),
    notes="等频分箱（bins=10）离散互信息，单位 nats；mi_norm=mi/min(Hx,Hy)",
)
def sc56_mutual_info(data: Any, bins: int = 10) -> Dict[str, Any]:
    xs, ys = _pair(data)
    bx, by = _bin_labels(xs, bins), _bin_labels(ys, bins)
    kx, ky = int(bx.max()) + 1, int(by.max()) + 1
    joint = np.zeros((kx, ky))
    np.add.at(joint, (bx, by), 1.0)
    n = joint.sum()
    px, py = joint.sum(axis=1) / n, joint.sum(axis=0) / n
    nz = joint > 0
    mi = float(np.sum(joint[nz] / n * np.log(joint[nz] / n / np.outer(px, py)[nz])))
    denom = min(_entropy(px), _entropy(py))
    return {
        "mi": _f(mi),
        "mi_norm": _f(mi / denom, 4) if denom > _EPS else 0.0,
        "bins": int(bins),
        "n": len(xs),
    }


def _te(
    source_past: np.ndarray, target_past: np.ndarray, target_now: np.ndarray, bins: int
) -> float:
    """传递熵：Σp(a,b,c)·ln[p(y_t|y_{t−1},x_{t−1}) / p(y_t|y_{t−1})]（三数组按下标对齐）。"""
    cats = np.concatenate([target_past, target_now])
    labels = _bin_labels(cats, bins)
    tp, tn = labels[: len(target_past)], labels[len(target_past) :]
    sp = _bin_labels(source_past, bins)
    nt, ns = int(labels.max()) + 1, int(sp.max()) + 1
    c_tt = np.zeros((nt, nt))
    c_tts = np.zeros((nt, nt, ns))
    for a, b, c in zip(tn, tp, sp, strict=False):
        c_tt[a, b] += 1.0
        c_tts[a, b, c] += 1.0
    tot = c_tt.sum()
    if tot <= 0:
        return 0.0
    te = 0.0
    for b in range(nt):
        prev = c_tt[:, b].sum()
        if prev <= 0:
            continue
        for c in range(ns):
            cond_prev = c_tts[:, b, c].sum()
            if cond_prev <= 0:
                continue
            for a in range(nt):
                v = c_tts[a, b, c]
                if v <= 0:
                    continue
                te += (v / tot) * math.log((v / cond_prev) / (c_tt[a, b] / prev))
    return float(te)


@register(
    "SC57",
    **_meta("SC57"),
    input_kind="pairs",
    output_schema=("te", "te_reverse", "net", "bins", "lag", "n"),
    notes="传递熵（hist 等频分箱 bins=8, lag=1）：H(Yt|Yt−1)−H(Yt|Yt−1,Xt−1)",
)
def sc57_transfer_entropy(data: Any, bins: int = 8, lag: int = 1) -> Dict[str, Any]:
    xs, ys = _pair(data)
    k = max(1, int(lag))
    m = len(xs) - k
    te_xy = _te(xs[:m], ys[:m], ys[k:], int(bins))
    te_yx = _te(ys[:m], xs[:m], xs[k:], int(bins))
    return {
        "te": _f(te_xy),
        "te_reverse": _f(te_yx),
        "net": _f(te_xy - te_yx),
        "bins": int(bins),
        "lag": k,
        "n": m,
    }


@register(
    "SC58",
    **_meta("SC58"),
    input_kind="pairs",
    output_schema=("kl", "kl_reverse", "js", "bins", "n"),
    notes="两样本直方图（共享等宽分箱 bins=10，ε=1e−6 平滑）KL 散度与 JS 散度",
)
def sc58_kl_divergence(data: Any, bins: int = 10) -> Dict[str, Any]:
    xs, ys = _pair(data)
    lo, hi = float(min(xs.min(), ys.min())), float(max(xs.max(), ys.max()))
    if hi <= lo:
        hi = lo + 1.0
    edges = np.linspace(lo, hi, int(bins) + 1)
    p, _ = np.histogram(xs, bins=edges)
    q, _ = np.histogram(ys, bins=edges)
    p = p.astype(float) + 1e-6
    q = q.astype(float) + 1e-6
    p, q = p / p.sum(), q / q.sum()
    m = 0.5 * (p + q)
    kl = float(np.sum(p * np.log(p / q)))
    kl_rev = float(np.sum(q * np.log(q / p)))
    js = float(0.5 * np.sum(p * np.log(p / m)) + 0.5 * np.sum(q * np.log(q / m)))
    return {"kl": _f(kl), "kl_reverse": _f(kl_rev), "js": _f(js), "bins": int(bins), "n": len(xs)}


@register(
    "SC59",
    **_meta("SC59"),
    input_kind="series",
    output_schema=("c", "c_raw", "n"),
    notes="Lempel-Ziv 复杂度（LZ76 穷举解析，按中位数二值化，c=c_raw·log2(n)/n）",
)
def sc59_lempel_ziv(data: Any) -> Dict[str, Any]:
    x = _series(data)
    n = len(x)
    med = float(np.median(x))
    s = "".join("1" if v > med else "0" for v in x)
    i, k, c_raw = 0, 1, 0
    while True:
        if i + k > n:
            c_raw += 1
            break
        if s[i : i + k] in s[: i + k - 1]:
            k += 1
        else:
            c_raw += 1
            i += k
            k = 1
    c = c_raw * math.log2(n) / n if n > 1 else 0.0
    return {"c": _f(c), "c_raw": int(c_raw), "n": n}


@register(
    "SC60",
    **_meta("SC60"),
    input_kind="series",
    output_schema=("sampen", "m", "r", "n"),
    notes="样本熵（m=2, r=0.2·σ）：−ln(A/B)，模板匹配用 Chebyshev 距离",
)
def sc60_sample_entropy(data: Any, m: int = 2, r_factor: float = 0.2) -> Dict[str, Any]:
    x = _series(data)
    n = len(x)
    mm = int(m)
    r = float(r_factor) * float(np.std(x))
    if r <= _EPS:
        r = 1e-6

    def _count(size: int) -> int:
        k = n - size
        if k < 2:
            return 0
        tmpl = np.lib.stride_tricks.sliding_window_view(x, size)[:k]
        d = np.max(np.abs(tmpl[:, None, :] - tmpl[None, :, :]), axis=2)
        tri = d[np.triu_indices(k, k=1)]
        return int(np.sum(tri <= r))

    b_cnt, a_cnt = _count(mm), _count(mm + 1)
    sampen = -math.log(a_cnt / b_cnt) if (a_cnt > 0 and b_cnt > 0) else 0.0
    return {"sampen": _f(sampen), "m": mm, "r": _f(r), "n": n}


@register(
    "SC61",
    **_meta("SC61"),
    input_kind="series",
    output_schema=("pe", "pe_norm", "m", "n"),
    notes="排列熵（m=3, τ=1）：pe_norm=pe/ln(m!)",
)
def sc61_permutation_entropy(data: Any, m: int = 3, tau: int = 1) -> Dict[str, Any]:
    x = _series(data)
    mm, tt = int(m), int(tau)
    n = len(x)
    span = (mm - 1) * tt
    patterns: Dict[Tuple[int, ...], int] = {}
    for i in range(0, n - span):
        idx = tuple(np.argsort(x[i : i + span + 1 : tt], kind="stable"))
        patterns[idx] = patterns.get(idx, 0) + 1
    counts = np.asarray(list(patterns.values()), dtype=float)
    pe = _entropy(counts)
    norm = pe / math.log(math.factorial(mm))
    return {"pe": _f(pe), "pe_norm": _f(norm, 4), "m": mm, "n": n}


@register(
    "SC62",
    **_meta("SC62"),
    input_kind="series",
    output_schema=("alpha", "h", "scales", "n"),
    notes="DFA 去趋势波动分析：log F(s)~log s 斜率 α（Hurst 近似，10 个几何尺度）",
)
def sc62_dfa(data: Any, n_scales: int = 10) -> Dict[str, Any]:
    x = _series(data)
    n = len(x)
    y = np.cumsum(x - np.mean(x))
    max_s = max(4, n // 4)
    scales = np.unique(np.round(np.geomspace(4, max_s, int(n_scales))).astype(int))
    log_s, log_f = [], []
    for s in scales:
        if s < 4 or s > max_s:
            continue
        k = n // s
        if k < 2:
            continue
        seg = y[: k * s].reshape(k, s)
        tt = np.arange(s, dtype=float)
        tt_m = tt.mean()
        denom = np.sum((tt - tt_m) ** 2)
        beta = (seg - seg.mean(axis=1, keepdims=True)) @ (tt - tt_m) / denom
        fit = seg.mean(axis=1, keepdims=True) + beta[:, None] * (tt - tt_m)
        f = math.sqrt(float(np.mean((seg - fit) ** 2)))
        if f > 0:
            log_s.append(math.log(s))
            log_f.append(math.log(f))
    alpha = float(np.polyfit(log_s, log_f, 1)[0]) if len(log_s) >= 2 else 0.5
    return {"alpha": _f(alpha, 4), "h": _f(alpha, 4), "scales": [int(v) for v in scales], "n": n}


# ---------------------------------------------------------------- SC63–SC70


def _block_maxima(x: np.ndarray, block_size: int = 0) -> np.ndarray:
    n = len(x)
    size = int(block_size) if block_size else max(5, n // 10)
    size = max(2, min(size, n))
    k = n // size
    return x[: k * size].reshape(k, size).max(axis=1)


def _gev_fit(x: np.ndarray, block_size: int = 0) -> Tuple[float, float, float]:
    maxima = _block_maxima(x, block_size)
    if len(maxima) < 3:
        maxima = np.array([maxima.max(), float(np.median(maxima)), maxima.min()])
    try:
        c, loc, scale = sps.genextreme.fit(maxima)
    except Exception:  # 退化样本时的矩估计近似（简化口径）
        loc, scale = float(maxima.mean()), float(maxima.std(ddof=1) or 1e-6)
        c = 0.0
    return float(loc), float(abs(scale) or 1e-6), float(-c)


@register(
    "SC63",
    **_meta("SC63"),
    input_kind="series",
    output_schema=("mu", "sigma", "xi", "blocks", "n"),
    notes="块最大值 GEV（MLE，块长=max(5,n//10)）；xi 为形状参数（scipy 的 c=−xi）",
)
def sc63_gev_fit(data: Any, block_size: int = 0) -> Dict[str, Any]:
    x = _series(data)
    mu, sigma, xi = _gev_fit(x, block_size)
    return {
        "mu": _f(mu),
        "sigma": _f(sigma),
        "xi": _f(xi),
        "blocks": len(_block_maxima(x, block_size)),
        "n": len(x),
    }


@register(
    "SC64",
    **_meta("SC64"),
    input_kind="series",
    output_schema=("xi", "beta", "threshold", "n_exceed", "n"),
    notes="POT/GPD（MLE，阈值=P95，floc=0）；beta 为尺度参数",
)
def sc64_gpd_fit(data: Any, q: float = 0.95) -> Dict[str, Any]:
    x = _series(data)
    u = float(np.quantile(x, float(q)))
    exc = x[x > u] - u
    if len(exc) < 3:
        exc = np.concatenate([exc, np.array([1e-6, 1e-6, 1e-6])])
    try:
        c, _, scale = sps.genpareto.fit(exc, floc=0.0)
    except Exception:  # 指数尾退化（简化口径）
        c, scale = 0.0, float(np.mean(exc) or 1e-6)
    return {
        "xi": _f(c),
        "beta": _f(abs(scale) or 1e-6),
        "threshold": _f(u),
        "n_exceed": int(np.sum(x > u)),
        "n": len(x),
    }


@register(
    "SC65",
    **_meta("SC65"),
    input_kind="series",
    output_schema=("level", "return_period", "mu", "sigma", "xi", "n"),
    notes="GEV 重现水平：level=μ+σ/ξ·((−ln(1−1/T))^(−ξ)−1)，T 默认 10 个块",
)
def sc65_return_level(data: Any, return_period: float = 10.0) -> Dict[str, Any]:
    x = _series(data)
    mu, sigma, xi = _gev_fit(x)
    t = max(float(return_period), 1.01)
    y = -math.log(1.0 - 1.0 / t)
    if abs(xi) > _EPS:
        level = mu + sigma / xi * (y ** (-xi) - 1.0)
    else:
        level = mu - sigma * math.log(y)
    return {
        "level": _f(level),
        "return_period": _f(t),
        "mu": _f(mu),
        "sigma": _f(sigma),
        "xi": _f(xi),
        "n": len(x),
    }


@register(
    "SC66",
    **_meta("SC66"),
    input_kind="series",
    output_schema=("alpha", "k", "threshold", "n"),
    notes="Hill 尾指数：取顶部 k 个正值（k 默认 max(5,n//10)），alpha=k/Σln(x_i/u)",
)
def sc66_hill(data: Any, k: int = 0) -> Dict[str, Any]:
    x = _series(data)
    pos = np.sort(x[x > 0])[::-1]
    kk = int(k) if k else max(5, len(pos) // 10)
    kk = int(max(3, min(kk, len(pos))))
    top = pos[:kk]
    u = float(top[-1])
    logs = np.log(top / u) if u > 0 else np.zeros(kk)
    s = float(np.sum(logs))
    alpha = kk / s if s > _EPS else None
    return {"alpha": _f(alpha), "k": kk, "threshold": _f(u), "n": len(x)}


@register(
    "SC67",
    **_meta("SC67"),
    input_kind="panel",
    output_schema=("i", "e_i", "z", "p", "n"),
    notes="Moran's I：k=4 近邻二进制权重（对称化 + 行标准化），正态近似 p 值",
)
def sc67_moran(data: Any, k: int = 4) -> Dict[str, Any]:
    coords, vals = _coords_values(data)
    n = len(vals)
    w = _weights(coords, k)
    z = vals - vals.mean()
    s0 = float(w.sum())
    s1 = float(np.sum(w**2))
    s2 = float(np.sum((w + w.T) ** 2))
    i_stat = (n / s0) * float(z @ w @ z) / float(z @ z) if s0 > _EPS else 0.0
    e_i = -1.0 / (n - 1)
    var_i = (n * n * s1 - n * s2 + 3.0 * s0 * s0) / ((n * n - 1) * s0 * s0) - e_i**2
    if var_i > _EPS:
        zs = (i_stat - e_i) / math.sqrt(var_i)
        p = float(2.0 * (1.0 - sps.norm.cdf(abs(zs))))
    else:
        zs, p = 0.0, 1.0
    return {"i": _f(i_stat, 4), "e_i": _f(e_i, 4), "z": _f(zs), "p": _f(p), "n": n}


@register(
    "SC68",
    **_meta("SC68"),
    input_kind="panel",
    output_schema=("c", "e_c", "z", "p", "n"),
    notes="Geary's C：同 SC67 权重；显著性与 z 值用确定性循环移位零分布（199 次）",
)
def sc68_geary(data: Any, k: int = 4) -> Dict[str, Any]:
    coords, vals = _coords_values(data)
    n = len(vals)
    w = _weights(coords, k)
    s0 = float(w.sum())
    tot = float(np.sum((vals - vals.mean()) ** 2)) or _EPS

    def _c(v: np.ndarray) -> float:
        dd = cdist(v.reshape(-1, 1), v.reshape(-1, 1), metric="sqeuclidean")
        return (n - 1) * float(np.sum(w * dd)) / (2.0 * s0 * tot)

    c_stat = _c(vals)
    shifts = [float(_c(np.roll(vals, s))) for s in range(1, min(200, n))]
    if shifts:
        arr = np.asarray(shifts)
        p = float(
            (1 + np.sum(np.abs(arr - arr.mean()) >= abs(c_stat - arr.mean()))) / (len(arr) + 1)
        )
        zs = (c_stat - float(arr.mean())) / float(arr.std(ddof=1) or 1e-6)
    else:
        p, zs = 1.0, 0.0
    return {"c": _f(c_stat, 4), "e_c": 1.0, "z": _f(zs), "p": _f(min(p, 1.0)), "n": n}


@register(
    "SC69",
    **_meta("SC69"),
    input_kind="panel",
    output_schema=("lags", "gamma", "counts", "n"),
    notes="半变异函数：等宽滞后分箱（n_bins=8，最大距离/2），γ(h)=mean[(x_i−x_j)²]/2",
)
def sc69_semivariogram(data: Any, n_bins: int = 8) -> Dict[str, Any]:
    coords, vals = _coords_values(data)
    n = len(vals)
    dm = cdist(coords, coords)
    sq = cdist(vals.reshape(-1, 1), vals.reshape(-1, 1), metric="sqeuclidean")
    tri = np.triu_indices(n, k=1)
    dist = dm[tri]
    semi = 0.5 * sq[tri]
    hmax = float(dist.max())
    if hmax <= _EPS:
        return {"lags": [], "gamma": [], "counts": [], "n": n}
    edges = np.linspace(0.0, hmax, int(n_bins) + 1)
    lags, gamma, counts = [], [], []
    for b in range(int(n_bins)):
        mask = (dist > edges[b]) if b == 0 else (dist >= edges[b])
        mask &= dist <= edges[b + 1] if b == int(n_bins) - 1 else dist < edges[b + 1]
        cnt = int(np.sum(mask))
        counts.append(cnt)
        lags.append(float((edges[b] + edges[b + 1]) / 2.0))
        gamma.append(float(semi[mask].mean()) if cnt else 0.0)
    return {"lags": _lst(lags), "gamma": _lst(gamma), "counts": counts, "n": n}


@register(
    "SC70",
    **_meta("SC70"),
    input_kind="panel",
    output_schema=("pred", "var", "targets", "nugget", "sill", "range", "n"),
    notes="普通克里金：指数变异函数（γ=sill(1−exp(−3h/range))，块金=0，range 取经验γ达 95%sill 的距离），"
    "简化口径：默认预测点为样本坐标质心",
)
def sc70_kriging(data: Any, targets: Sequence[Sequence[float]] | None = None) -> Dict[str, Any]:
    coords, vals = _coords_values(data)
    n = len(vals)
    dm = cdist(coords, coords)
    tri = np.triu_indices(n, k=1)
    dist, semi = dm[tri], 0.5 * cdist(vals.reshape(-1, 1), vals.reshape(-1, 1), "sqeuclidean")[tri]
    sill = float(np.var(vals, ddof=1)) or _EPS
    order = np.argsort(dist, kind="stable")
    d_s, s_s = dist[order], semi[order]
    rng = float(d_s.max())
    cum = np.cumsum(s_s) / np.arange(1, len(s_s) + 1)
    hit = np.where(cum >= 0.95 * sill)[0]
    if len(hit):
        rng = float(max(d_s[hit[0]], _EPS))
    rng = max(rng, 1e-6)
    gamma = lambda h: sill * (1.0 - np.exp(-3.0 * np.asarray(h, dtype=float) / rng))  # noqa: E731
    gam = gamma(dm)
    a = np.ones((n + 1, n + 1))
    a[:n, :n] = gam + 1e-10 * np.eye(n)
    a[n, n] = 0.0
    if targets is None:
        tgt = coords.mean(axis=0).reshape(1, -1)
    else:
        tgt = np.asarray(targets, dtype=float).reshape(-1, coords.shape[1])
    preds, varis = [], []
    for t in tgt:
        h0 = np.linalg.norm(coords - t, axis=1)
        g0 = gamma(h0)
        rhs = np.concatenate([g0, [1.0]])
        try:
            sol = np.linalg.solve(a, rhs)
        except np.linalg.LinAlgError:
            sol = np.linalg.lstsq(a, rhs, rcond=None)[0]
        w = sol[:n]
        preds.append(float(w @ vals))
        varis.append(float(max(0.0, w @ g0 + sol[n])))
    return {
        "pred": _lst(preds),
        "var": _lst(varis),
        "targets": _mtx(tgt),
        "nugget": 0.0,
        "sill": _f(sill),
        "range": _f(rng),
        "n": n,
    }


# ---------------------------------------------------------------- SC71–SC78


def _graph(data: Any):
    """网络输入：邻接矩阵 / {adj|matrix} / {edges:[[i,j],...], n_nodes}。"""
    import networkx as nx  # noqa: PLC0415

    if isinstance(data, Mapping):
        for key in ("adj", "adjacency", "matrix", "A"):
            if key in data and _is_nested(data[key]):
                a = np.asarray(data[key], dtype=float)
                g = nx.from_numpy_array(a)
                g.remove_edges_from(nx.selfloop_edges(g))
                return g
        if "edges" in data:
            edges = data["edges"]
            n_nodes = int(data.get("n_nodes", 0) or 0)
            g = nx.Graph()
            pairs = []
            for e in edges:
                if isinstance(e, Mapping):
                    pairs.append((int(e["source"]), int(e["target"])))
                else:
                    pairs.append((int(e[0]), int(e[1])))
            if n_nodes:
                g.add_nodes_from(range(n_nodes))
            g.add_edges_from(pairs)
            return g
        raise ValueError("graph data needs adj/matrix or edges")
    a = np.asarray(data, dtype=float)
    g = nx.from_numpy_array(a)
    g.remove_edges_from(nx.selfloop_edges(g))
    return g


@register(
    "SC71",
    **_meta("SC71"),
    input_kind="panel",
    output_schema=("degree", "betweenness", "closeness", "top_node", "n_nodes", "n_edges"),
    notes="networkx 度/介数/接近中心性（度与介数按 n−1 归一，介数近似用精确算法）",
)
def sc71_centrality(data: Any) -> Dict[str, Any]:
    import networkx as nx  # noqa: PLC0415

    g = _graph(data)
    nodes = sorted(g.nodes())
    deg = nx.degree_centrality(g)
    btw = nx.betweenness_centrality(g, normalized=True)
    clo = nx.closeness_centrality(g)
    d = [float(deg[n]) for n in nodes]
    b = [float(btw[n]) for n in nodes]
    c = [float(clo[n]) for n in nodes]
    top = nodes[int(np.argmax(b))] if b else None
    return {
        "degree": _lst(d, 4),
        "betweenness": _lst(b, 4),
        "closeness": _lst(c, 4),
        "top_node": int(top) if top is not None else None,
        "n_nodes": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
    }


@register(
    "SC72",
    **_meta("SC72"),
    input_kind="panel",
    output_schema=("communities", "modularity", "n_communities", "n_nodes", "n_edges"),
    notes="networkx Louvain 社区发现（seed=42 固定，分辨率 1.0），模块度 Q 按无向图计算",
)
def sc72_communities(data: Any) -> Dict[str, Any]:
    from networkx.algorithms.community import louvain_communities, modularity  # noqa: PLC0415

    g = _graph(data)
    if g.number_of_edges() == 0:
        comms = [{n} for n in sorted(g.nodes())]
        q = 0.0
    else:
        comms = louvain_communities(g, seed=_SEED)
        q = float(modularity(g, comms))
    ordered = sorted((sorted(int(v) for v in c) for c in comms), key=lambda x: x[0] if x else 0)
    return {
        "communities": ordered,
        "modularity": _f(q, 4),
        "n_communities": len(ordered),
        "n_nodes": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
    }


@register(
    "SC73",
    **_meta("SC73"),
    input_kind="panel",
    output_schema=("times", "survival", "median", "n_events", "n"),
    notes="Kaplan-Meier 乘积极限（右删失）；median=首个 S(t)≤0.5 的时间，未达则 None",
)
def sc73_kaplan_meier(data: Any) -> Dict[str, Any]:
    t, e = _time_event(data)
    n = len(t)
    times: List[float] = []
    surv: List[float] = []
    s = 1.0
    for u in np.unique(t[e > 0]):
        at_risk = int(np.sum(t >= u))
        d = int(np.sum((t == u) & (e > 0)))
        if at_risk <= 0:
            continue
        s *= 1.0 - d / at_risk
        times.append(float(u))
        surv.append(s)
    med = next((tm for tm, sv in zip(times, surv, strict=False) if sv <= 0.5), None)
    return {
        "times": _lst(times),
        "survival": _lst(surv),
        "median": _f(med),
        "n_events": int(np.sum(e > 0)),
        "n": n,
    }


@register(
    "SC74",
    **_meta("SC74"),
    input_kind="events",
    output_schema=("chi2", "p", "observed", "expected", "groups", "n"),
    notes="Log-rank 检验（两组，右删失）：χ²=(O−E)²/V，df=1，正态等价于卡方",
)
def sc74_logrank(data: Any) -> Dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ValueError("logrank data must be a mapping")
    t, e = _time_event(data)
    raw = data.get("group", data.get("state"))
    if raw is None:
        raise ValueError("logrank data needs group/state")
    g = [str(v) for v in raw][: len(t)]
    labels = list(dict.fromkeys(g))
    if len(labels) < 2:
        return {
            "chi2": 0.0,
            "p": 1.0,
            "observed": 0.0,
            "expected": 0.0,
            "groups": labels,
            "n": len(t),
        }
    a = np.asarray([x == labels[0] for x in g], dtype=bool)
    o1 = e1 = v = 0.0
    for u in np.unique(t[e > 0]):
        n1 = float(np.sum(a & (t >= u)))
        n2 = float(np.sum((~a) & (t >= u)))
        ntot = n1 + n2
        d1 = float(np.sum(a & (t == u) & (e > 0)))
        dtot = float(np.sum((t == u) & (e > 0)))
        if ntot <= 1:
            continue
        o1 += d1
        e1 += dtot * n1 / ntot
        v += n1 * n2 * dtot * (ntot - dtot) / (ntot * ntot * (ntot - 1.0))
    chi2 = (o1 - e1) ** 2 / v if v > _EPS else 0.0
    p = float(sps.chi2.sf(chi2, 1))
    return {
        "chi2": _f(chi2),
        "p": _f(p),
        "observed": _f(o1, 4),
        "expected": _f(e1, 4),
        "groups": labels[:2],
        "n": len(t),
    }


@register(
    "SC75",
    **_meta("SC75"),
    input_kind="events",
    output_schema=("coef", "hr", "ci_low", "ci_high", "p", "n"),
    notes="Cox 比例风险（statsmodels PHReg，Efron ties）；x 可为单列或多列协变量",
)
def sc75_cox(data: Any) -> Dict[str, Any]:
    from statsmodels.duration.hazard_regression import PHReg  # noqa: PLC0415

    if not isinstance(data, Mapping):
        raise ValueError("cox data must be a mapping")
    t, e = _time_event(data)
    if "x" not in data:
        raise ValueError("cox data needs covariate x")
    xr = data["x"]
    x = np.asarray(xr, dtype=float)
    if x.ndim == 1:
        x = x.reshape(-1, 1)
    m = min(len(t), x.shape[0])
    try:
        res = PHReg(t[:m], x[:m], status=e[:m]).fit(disp=False)
        coef = np.asarray(res.params, dtype=float).ravel()
        ci = np.asarray(res.conf_int(), dtype=float)
        pvals = np.asarray(res.pvalues, dtype=float).ravel()
        if not (np.all(np.isfinite(coef)) and np.all(np.isfinite(pvals))):
            raise ValueError("non-finite coef")
    except Exception:  # 退化样本（全删失/完全分离/共线）→ 系数置 0，hr=1（简化口径）
        coef = np.zeros(x.shape[1])
        ci = np.column_stack([coef, coef])
        pvals = np.ones(x.shape[1])
    return {
        "coef": _lst(coef),
        "hr": _lst(np.exp(coef), 4),
        "ci_low": _lst(np.exp(ci[:, 0]), 4),
        "ci_high": _lst(np.exp(ci[:, 1]), 4),
        "p": _lst(pvals),
        "n": m,
    }


@register(
    "SC76",
    **_meta("SC76"),
    input_kind="series",
    output_schema=("shape", "scale", "mean", "loglik", "n"),
    notes="Weibull 拟合（scipy weibull_min，MLE 且 floc=0）",
)
def sc76_weibull(data: Any) -> Dict[str, Any]:
    x = _series(data)
    pos = x[x > 0]
    if len(pos) < 3:
        pos = np.abs(x) + 1e-9
    try:
        c, loc, scale = sps.weibull_min.fit(pos, floc=0.0)
        ll = float(np.sum(sps.weibull_min.logpdf(pos, c, loc=0.0, scale=scale)))
    except Exception:  # 退化（含零/常量）→ 指数分布近似（简化口径）
        c, scale = 1.0, float(np.mean(pos) or 1e-6)
        ll = float("nan")
    return {
        "shape": _f(c),
        "scale": _f(scale),
        "mean": _f(float(np.mean(x))),
        "loglik": _f(ll),
        "n": len(x),
    }


@register(
    "SC77",
    **_meta("SC77"),
    input_kind="events",
    output_schema=("mtbf", "failure_rate", "total_time", "n_events", "n"),
    notes="MTBF=总观测时长/失效数；failure_rate=1/MTBF（指数分布假设）",
)
def sc77_mtbf(data: Any) -> Dict[str, Any]:
    t, e = _time_event(data)
    total = float(np.sum(t))
    events = int(np.sum(e > 0))
    mtbf = total / events if events > 0 else None
    return {
        "mtbf": _f(mtbf),
        "failure_rate": _f(1.0 / mtbf) if mtbf else None,
        "total_time": _f(total),
        "n_events": events,
        "n": len(t),
    }


@register(
    "SC78",
    **_meta("SC78"),
    input_kind="series",
    output_schema=("center", "ucl", "lcl", "alarms", "sigma", "chart", "n"),
    notes="EWMA 控制图（λ=0.2, L=3）：σ 由移动极差 MR/1.128 估计，越界点记 alarms",
)
def sc78_control_chart(data: Any, lam: float = 0.2, L: float = 3.0) -> Dict[str, Any]:
    x = _series(data)
    n = len(x)
    mr = np.abs(np.diff(x))
    sigma = float(np.mean(mr) / 1.128) if len(mr) else 0.0
    center = float(np.mean(x))
    lam = float(min(max(lam, 1e-3), 1.0))
    ewma = np.zeros(n)
    prev = center
    for i, v in enumerate(x):
        prev = lam * v + (1.0 - lam) * prev
        ewma[i] = prev
    width = float(L) * sigma * math.sqrt(lam / (2.0 - lam)) if sigma > 0 else 0.0
    ucl, lcl = center + width, center - width
    alarms = [int(i) for i, v in enumerate(ewma) if v > ucl or v < lcl]
    return {
        "center": _f(center),
        "ucl": _f(ucl),
        "lcl": _f(lcl),
        "alarms": alarms,
        "sigma": _f(sigma),
        "chart": "ewma",
        "n": n,
    }


# ---------------------------------------------------------------- SC79–SC92


def _syn_meta() -> Dict[str, List[float]]:
    """synthetic：三组效应 1/2/3 各 10 条、se 全 1 → 解析解 FE 合并均值=2、Q=20、df=29、I²=0、H²=20/29。"""
    return {"effects": [1.0] * 10 + [2.0] * 10 + [3.0] * 10, "se": [1.0] * 30}


def _syn_egger() -> Dict[str, List[float]]:
    """synthetic：1/se 取 2/1/0.5 三档各 10 条，组内残差 ±0.2 且和为 0 →
    y=eff/se 对 1/se 的 OLS 截距解析解恰为 1.0。"""
    se = [0.5] * 10 + [1.0] * 10 + [2.0] * 10
    resid = [0.2, -0.2] * 15
    return {"effects": [(1.0 + 0.5 / s + r) * s for s, r in zip(se, resid, strict=False)], "se": se}


@register(
    "SC79",
    **_meta("SC79"),
    input_kind="pairs",
    output_schema=("pooled", "se", "ci_low", "ci_high", "z", "p", "n"),
    notes="固定效应 meta：逆方差加权 1/se²，z 检验双侧 p",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": _syn_meta(),
            "params": {},
            "expect": {"result.pooled": 2.0, "result.se": 0.182574, "result.n": 30},
        }
    ),
)
def sc79_meta_fixed(data: Any) -> Dict[str, Any]:
    eff, se = _effect_se(data)
    w = 1.0 / se**2
    pooled = float(np.sum(w * eff) / np.sum(w))
    se_p = float(math.sqrt(1.0 / np.sum(w)))
    z = pooled / se_p if se_p > _EPS else 0.0
    p = float(2.0 * (1.0 - sps.norm.cdf(abs(z))))
    return {
        "pooled": _f(pooled, 4),
        "se": _f(se_p),
        "ci_low": _f(pooled - 1.959964 * se_p, 4),
        "ci_high": _f(pooled + 1.959964 * se_p, 4),
        "z": _f(z),
        "p": _f(p),
        "n": len(eff),
    }


@register(
    "SC80",
    **_meta("SC80"),
    input_kind="pairs",
    output_schema=("pooled", "se", "ci_low", "ci_high", "tau2", "i2", "q", "n"),
    notes="随机效应 meta（DerSimonian-Laird 矩估计 τ²），置信区间用正态近似",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": _syn_meta(),
            "params": {},
            "expect": {
                "result.pooled": 2.0,
                "result.tau2": 0.0,
                "result.i2": 0.0,
                "result.q": 20.0,
            },
        }
    ),
)
def sc80_meta_random(data: Any) -> Dict[str, Any]:
    eff, se = _effect_se(data)
    d = _dl(eff, se)
    lo = d["re"] - 1.959964 * d["se_re"]
    hi = d["re"] + 1.959964 * d["se_re"]
    return {
        "pooled": _f(d["re"], 4),
        "se": _f(d["se_re"]),
        "ci_low": _f(lo, 4),
        "ci_high": _f(hi, 4),
        "tau2": _f(d["tau2"]),
        "i2": _f(d["i2"], 4),
        "q": _f(d["q"]),
        "n": len(eff),
    }


@register(
    "SC81",
    **_meta("SC81"),
    input_kind="pairs",
    output_schema=("q", "df", "p", "i2", "h2", "n"),
    notes="异质性 Cochran Q（χ²(df=k−1)）与 I²=max(0,(Q−df)/Q)，H²=Q/df",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": _syn_meta(),
            "params": {},
            "expect": {"result.q": 20.0, "result.df": 29, "result.i2": 0.0, "result.h2": 0.6897},
        }
    ),
)
def sc81_heterogeneity(data: Any) -> Dict[str, Any]:
    eff, se = _effect_se(data)
    d = _dl(eff, se)
    df = int(d["df"])
    p = float(sps.chi2.sf(d["q"], df)) if df > 0 else 1.0
    h2 = d["q"] / df if df > 0 else 1.0
    return {
        "q": _f(d["q"]),
        "df": df,
        "p": _f(p),
        "i2": _f(d["i2"], 4),
        "h2": _f(h2, 4),
        "n": len(eff),
    }


@register(
    "SC82",
    **_meta("SC82"),
    input_kind="pairs",
    output_schema=("intercept", "se", "t", "p", "n"),
    notes="Egger 回归：effect/se ~ 1/se 的 OLS 截距检验（截距显著≠0 提示漏斗图不对称）",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": _syn_egger(),
            "params": {},
            "expect": {"result.intercept": 1.0, "result.n": 30},
        }
    ),
)
def sc82_funnel_asymmetry(data: Any) -> Dict[str, Any]:
    eff, se = _effect_se(data)
    y = eff / se
    x = 1.0 / se
    design = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ beta
    df = len(y) - 2
    sigma2 = float(resid @ resid) / df if df > 0 else 0.0
    try:
        cov = sigma2 * np.linalg.inv(design.T @ design)
        se_i = float(math.sqrt(max(cov[0, 0], 0.0)))
    except np.linalg.LinAlgError:
        se_i = float("nan")
    t = float(beta[0] / se_i) if se_i and math.isfinite(se_i) and se_i > _EPS else 0.0
    p = float(2.0 * (1.0 - sps.t.cdf(abs(t), df))) if df > 0 else 1.0
    return {"intercept": _f(beta[0], 4), "se": _f(se_i), "t": _f(t), "p": _f(p), "n": len(eff)}


@register(
    "SC83",
    **_meta("SC83"),
    input_kind="pairs",
    output_schema=(
        "adj_pooled",
        "se",
        "ci_low",
        "ci_high",
        "n_filled",
        "side",
        "original_pooled",
        "n",
    ),
    notes="Trim-and-fill 简化口径：偏度定缺失侧，Duval-Tweedie 秩估计器 L0 + 迭代剪补，镜像补齐后逆方差加权",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": _syn_meta(),
            "params": {},
            "expect": {"result.original_pooled": 2.0, "result.n_filled": 0, "result.n": 30},
        }
    ),
)
def sc83_trim_and_fill(data: Any) -> Dict[str, Any]:
    eff, se = _effect_se(data)
    original = _dl(eff, se)["re"]
    n = len(eff)
    d0 = eff - original
    side = 1.0 if (float(sps.skew(d0)) if n > 2 else 0.0) >= 0 else -1.0

    def _drop(k0: int, center: float) -> np.ndarray:
        dd = eff - center
        idx = np.where(np.sign(dd) == side)[0]
        order = idx[np.argsort(-np.abs(dd[idx]), kind="stable")]
        keep = np.ones(n, dtype=bool)
        keep[order[:k0]] = False
        return keep

    k0, pooled = 0, original
    for _ in range(100):
        keep = _drop(k0, pooled)
        if keep.sum() < 3:
            k0 = max(0, k0 - 1)
            break
        pooled = _dl(eff[keep], se[keep])["re"]
        dd = eff - pooled
        idx = np.where(np.sign(dd) == side)[0]
        ranks = sps.rankdata(np.abs(dd))
        t_n = float(ranks[idx].sum())
        gamma = (4.0 * t_n - n * (n + 1)) / (2.0 * n - 1.0)
        k0_new = int(max(0, min(n - 3, round(gamma))))
        if k0_new == k0:
            break
        k0 = k0_new
    keep = _drop(k0, pooled)
    drop = np.where(~keep)[0]
    all_e = np.concatenate([eff[keep], 2.0 * pooled - eff[drop]]) if k0 else eff
    all_se = np.concatenate([se[keep], se[drop]]) if k0 else se
    adj = _dl(all_e, all_se)
    return {
        "adj_pooled": _f(adj["re"], 4),
        "se": _f(adj["se_re"]),
        "ci_low": _f(adj["re"] - 1.959964 * adj["se_re"], 4),
        "ci_high": _f(adj["re"] + 1.959964 * adj["se_re"], 4),
        "n_filled": int(k0),
        "side": "right" if side > 0 else "left",
        "original_pooled": _f(original, 4),
        "n": n,
    }


@register(
    "SC84",
    **_meta("SC84"),
    input_kind="panel",
    output_schema=("chi2", "df", "p", "missing_rate", "n_missing", "n"),
    notes="缺失机制（MCAR）简化检验：各列缺失行的其他列均值 vs 完整行均值，"
    "标准化差平方和服从 χ²(df=比较次数)，df=0 时 p=1",
)
def sc84_missing_mechanism(data: Any) -> Dict[str, Any]:
    m = _matrix(data)
    n, p = m.shape
    miss = np.isnan(m)
    complete = ~miss.any(axis=1)
    chi2, df = 0.0, 0
    for j in range(p):
        miss_rows = miss[:, j]
        if not miss_rows.any() or complete.sum() < 2:
            continue
        for k in range(p):
            if k == j:
                continue
            a = m[miss_rows, k]
            a = a[~np.isnan(a)]
            b = m[complete, k]
            if len(a) < 2 or len(b) < 2:
                continue
            va, vb = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
            se = math.sqrt(va / len(a) + vb / len(b))
            if se <= _EPS:
                continue
            diff = float(np.mean(a)) - float(np.mean(b))
            chi2 += (diff / se) ** 2
            df += 1
    p_val = float(sps.chi2.sf(chi2, df)) if df > 0 else 1.0
    n_missing = int(miss.sum())
    return {
        "chi2": _f(chi2),
        "df": df,
        "p": _f(p_val),
        "missing_rate": _f(n_missing / (n * p), 4) if n * p else 0.0,
        "n_missing": n_missing,
        "n": n,
    }


@register(
    "SC85",
    **_meta("SC85"),
    input_kind="panel",
    output_schema=("filled", "n_filled", "missing_cells", "n", "n_cols"),
    notes="KNN 插补（sklearn KNNImputer，k=5，距离加权）；全缺失列回退为该列中位数填充",
)
def sc85_knn_impute(data: Any, k: int = 5) -> Dict[str, Any]:
    from sklearn.impute import KNNImputer  # noqa: PLC0415

    m = _matrix(data)
    n, p = m.shape
    miss = int(np.isnan(m).sum())
    if miss == 0:
        filled = m.copy()
    else:
        all_nan = np.all(np.isnan(m), axis=0)
        work = m[:, ~all_nan]
        filled = m.copy()
        if work.shape[1] > 0:
            imp = KNNImputer(n_neighbors=max(1, int(k)), weights="distance")
            filled[:, ~all_nan] = imp.fit_transform(work)
        if all_nan.any():
            other = filled[:, ~all_nan]
            fallback = float(np.nanmedian(other)) if other.size else 0.0
            filled[:, all_nan] = fallback
        if np.isnan(filled).any():
            filled = np.nan_to_num(filled, nan=0.0)
    return {"filled": _mtx(filled), "n_filled": miss, "missing_cells": miss, "n": n, "n_cols": p}


@register(
    "SC86",
    **_meta("SC86"),
    input_kind="panel",
    output_schema=("distances", "threshold", "flags", "n_outliers", "n"),
    notes="马氏距离 D²（协方差伪逆），阈值取 χ²(0.975, df=列数)",
)
def sc86_mahalanobis(data: Any) -> Dict[str, Any]:
    m = _matrix(data)
    m = np.nan_to_num(m, nan=0.0)
    n, p = m.shape
    mu = m.mean(axis=0)
    cov = np.cov(m, rowvar=False)
    cov = np.atleast_2d(cov)
    try:
        inv = np.linalg.pinv(cov)
    except np.linalg.LinAlgError:
        inv = np.eye(p)
    diff = m - mu
    d2 = np.einsum("ij,jk,ik->i", diff, inv, diff)
    thr = float(sps.chi2.ppf(0.975, p))
    flags = [bool(v > thr) for v in d2]
    return {
        "distances": _lst(d2, 4),
        "threshold": _f(thr, 4),
        "flags": flags,
        "n_outliers": int(sum(flags)),
        "n": n,
    }


@register(
    "SC87",
    **_meta("SC87"),
    input_kind="panel",
    output_schema=("patterns", "n_patterns", "column_missing", "missing_rate", "n", "n_cols"),
    notes="缺失模式矩阵：逐行缺失掩码（1=缺失）计数 + 各列缺失数，按频次降序",
)
def sc87_missing_patterns(data: Any) -> Dict[str, Any]:
    m = _matrix(data)
    n, p = m.shape
    miss = np.isnan(m) if m.size else np.zeros((n, p), dtype=bool)
    counts: Dict[str, int] = {}
    for row in miss:
        key = "".join("1" if v else "0" for v in row)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    patterns = [{"pattern": k, "count": c, "share": _f(c / n, 4) if n else 0.0} for k, c in ordered]
    col_missing = [int(v) for v in miss.sum(axis=0)] if n else [0] * p
    total = n * p
    return {
        "patterns": patterns,
        "n_patterns": len(patterns),
        "column_missing": col_missing,
        "missing_rate": _f(int(miss.sum()) / total, 4) if total else 0.0,
        "n": n,
        "n_cols": p,
    }


@register(
    "SC88",
    **_meta("SC88"),
    input_kind="panel",
    output_schema=("dups", "exact_groups", "n_dups", "threshold", "n", "n_cols"),
    notes="重复记录检测：键列完全相同的精确重复 + 标准化行余弦相似度≥threshold 的近似重复（threshold=0.99）",
)
def sc88_duplicate_records(data: Any, threshold: float = 0.99) -> Dict[str, Any]:
    m = _matrix(data)
    n, p = m.shape
    rows = [tuple(None if np.isnan(v) else float(v) for v in row) for row in m]
    exact: Dict[Tuple[Any, ...], List[int]] = {}
    for i, r in enumerate(rows):
        exact.setdefault(r, []).append(i)
    exact_groups = [g for g in exact.values() if len(g) > 1]
    mu, sd = np.nanmean(m, axis=0), np.nanstd(m, axis=0)
    sd[sd <= _EPS] = 1.0
    z = np.nan_to_num((m - mu) / sd, nan=0.0)
    norm = np.linalg.norm(z, axis=1)
    norm[norm <= _EPS] = 1.0
    sim = (z @ z.T) / np.outer(norm, norm)
    pairs: List[List[int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if rows[i] == rows[j]:
                continue
            if float(sim[i, j]) >= float(threshold):
                pairs.append([i, j])
    dups = [[int(x) for x in g] for g in exact_groups] + pairs
    return {
        "dups": dups,
        "exact_groups": [[int(x) for x in g] for g in exact_groups],
        "n_dups": len(dups),
        "threshold": float(threshold),
        "n": n,
        "n_cols": p,
    }


@register(
    "SC89",
    **_meta("SC89"),
    input_kind="panel",
    output_schema=("violations", "n_violations", "n_rules", "n", "n_rows"),
    notes="一致性规则校验：range / monotone / compare / notnull 四类规则逐行检查",
)
def sc89_consistency_rules(data: Any) -> Dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ValueError("rule-check data must be a mapping with table and rules")
    table = data.get("table", data.get("records"))
    rules = data.get("rules")
    if table is None or rules is None:
        raise ValueError("rule-check data needs table and rules")
    cols: Dict[str, List[Any]] = {}
    if isinstance(table, Mapping):
        cols = {str(k): list(v) for k, v in table.items()}
    else:
        rows = list(table)
        if rows and isinstance(rows[0], Mapping):
            keys = list(rows[0].keys())
            cols = {str(k): [r.get(k) for r in rows] for k in keys}
        else:
            names = [f"c{i}" for i in range(len(rows[0]))] if rows else []
            cols = {nm: [r[i] for r in rows] for i, nm in enumerate(names)}
    n_rows = max((len(v) for v in cols.values()), default=0)
    violations: List[Dict[str, Any]] = []
    for ri, rule in enumerate(rules):
        kind = str(rule.get("type", "")).lower()
        col = str(rule.get("column", ""))
        if kind == "range":
            lo, hi = rule.get("lo"), rule.get("hi")
            for i, v in enumerate(cols.get(col, [])):
                if v is None:
                    continue
                if (lo is not None and float(v) < float(lo)) or (
                    hi is not None and float(v) > float(hi)
                ):
                    violations.append({"rule": ri, "row": i, "type": "range", "column": col})
        elif kind == "monotone":
            direction = str(rule.get("direction", "up"))
            seq = cols.get(col, [])
            for i in range(1, len(seq)):
                a, b = seq[i - 1], seq[i]
                if a is None or b is None:
                    continue
                bad = float(b) < float(a) if direction == "up" else float(b) > float(a)
                if bad:
                    violations.append({"rule": ri, "row": i, "type": "monotone", "column": col})
        elif kind == "compare":
            left, right = str(rule.get("left", "")), str(rule.get("right", ""))
            op = str(rule.get("op", "<="))
            ops = {
                "<=": lambda a, b: a <= b,
                "<": lambda a, b: a < b,
                ">=": lambda a, b: a >= b,
                ">": lambda a, b: a > b,
                "==": lambda a, b: a == b,
            }
            fn = ops.get(op)
            if fn is None:
                continue
            for i, (a, b) in enumerate(zip(cols.get(left, []), cols.get(right, []), strict=False)):
                if a is None or b is None:
                    continue
                if not fn(float(a), float(b)):
                    violations.append(
                        {"rule": ri, "row": i, "type": "compare", "column": f"{left}{op}{right}"}
                    )
        elif kind == "notnull":
            for i, v in enumerate(cols.get(col, [])):
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    violations.append({"rule": ri, "row": i, "type": "notnull", "column": col})
    return {
        "violations": violations,
        "n_violations": len(violations),
        "n_rules": len(list(rules)),
        "n": n_rows,
        "n_rows": n_rows,
    }


def _as_time(v: Any) -> float:
    if v is None:
        return float("nan")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("Z", "+00:00")
    try:
        from datetime import datetime  # noqa: PLC0415

        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return float("nan")


@register(
    "SC90",
    **_meta("SC90"),
    input_kind="panel",
    output_schema=("pass", "n_violations", "violations", "n", "max_lag"),
    notes="PIT 时间校验：数据可用时间 must ≤ 使用时间（ISO 字符串或数值时间戳），max_lag=最大超前秒数",
)
def sc90_pit_time(data: Any) -> Dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ValueError("PIT data must be a mapping with available and used")
    if "available" not in data or "used" not in data:
        raise ValueError("PIT data needs available and used")
    avail = [_as_time(v) for v in data["available"]]
    used = [_as_time(v) for v in data["used"]]
    n = min(len(avail), len(used))
    viol, max_lag = [], 0.0
    for i in range(n):
        a, u = avail[i], used[i]
        if not (math.isfinite(a) and math.isfinite(u)):
            viol.append(i)
            continue
        if a > u:
            viol.append(i)
            max_lag = max(max_lag, a - u)
    return {
        "pass": len(viol) == 0,
        "n_violations": len(viol),
        "violations": viol,
        "n": n,
        "max_lag": _f(max_lag),
    }


@register(
    "SC91",
    **_meta("SC91"),
    input_kind="series",
    output_schema=(
        "trend",
        "seasonal",
        "resid",
        "seasonal_strength",
        "trend_strength",
        "period",
        "n",
    ),
    notes="X-13 风格分解（statsmodels STL 近似，robust=False，周期默认 12；样本不足时周期降为 n//3）",
)
def sc91_stl_decompose(data: Any, period: int = 12) -> Dict[str, Any]:
    from statsmodels.tsa.seasonal import STL  # noqa: PLC0415

    x = _series(data)
    n = len(x)
    per = int(period)
    if n < 2 * per + 1:
        per = max(2, n // 3)
    res = STL(x, period=per, robust=False).fit()
    trend, seas, resid = res.trend, res.seasonal, res.resid
    var_r = float(np.var(resid))
    var_rs = float(np.var(resid + seas))
    var_tr = float(np.var(resid + trend))
    s_str = max(0.0, 1.0 - var_r / var_rs) if var_rs > _EPS else 0.0
    t_str = max(0.0, 1.0 - var_r / var_tr) if var_tr > _EPS else 0.0
    return {
        "trend": _lst(trend),
        "seasonal": _lst(seas),
        "resid": _lst(resid),
        "seasonal_strength": _f(s_str, 4),
        "trend_strength": _f(t_str, 4),
        "period": per,
        "n": n,
    }


@register(
    "SC92",
    **_meta("SC92"),
    input_kind="series",
    output_schema=("outliers", "n_outliers", "sigma", "threshold", "n"),
    notes="异常点识别（3σ 规则，简化口径）：残差=滚动中位数偏差，σ=MAD·1.4826；"
    "LS 由 CUSUM 变点 + 前后窗均值差>kσ 判定，TC=次期残留≥50%，否则 AO",
)
def sc92_outliers(data: Any, k: float = 3.0) -> Dict[str, Any]:
    x = _series(data)
    n = len(x)
    w = int(min(11, max(3, n // 10)))
    if w % 2 == 0:
        w += 1
    half = w // 2
    resid = np.array(
        [x[i] - float(np.median(x[max(0, i - half) : min(n, i + half + 1)])) for i in range(n)],
        dtype=float,
    )
    med = float(np.median(resid))
    mad = float(np.median(np.abs(resid - med)) * 1.4826)
    if mad > 0:
        sigma = mad
    elif float(np.std(resid)) > _EPS:
        sigma = float(np.std(resid))
    else:
        sigma = float(np.std(np.diff(x), ddof=1)) / math.sqrt(2.0) if n > 2 else 1.0
    sigma = max(sigma, _EPS)
    thr = float(k) * sigma

    outliers: List[Dict[str, Any]] = []
    ls_points: List[int] = []
    for cp in _cusum_points(x, 2.0):
        if half <= cp <= n - half:
            shift = abs(float(np.mean(x[cp : cp + half])) - float(np.mean(x[cp - half : cp])))
            if shift > thr:
                ls_points.append(cp)
                outliers.append(
                    {"index": int(cp), "type": "LS", "value": _f(x[cp]), "z": _f(shift / sigma, 4)}
                )

    flagged = [i for i in range(n) if abs(resid[i] - med) > thr]
    blocks: List[List[int]] = []
    for i in flagged:
        if blocks and i - blocks[-1][-1] <= 1:
            blocks[-1].append(i)
        else:
            blocks.append([i])
    for blk in blocks:
        j = max(blk, key=lambda i: abs(resid[i] - med))
        if any(abs(j - cp) <= half for cp in ls_points):
            continue
        v = float(resid[j] - med)
        kind = "AO"
        if (
            0 < j < n - 1
            and abs(resid[j + 1] - med) >= 0.5 * abs(v)
            and np.sign(resid[j + 1] - med) == np.sign(v)
        ):
            kind = "TC"
        outliers.append({"index": int(j), "type": kind, "value": _f(x[j]), "z": _f(v / sigma, 4)})
    outliers.sort(key=lambda d: d["index"])
    return {
        "outliers": outliers,
        "n_outliers": len(outliers),
        "sigma": _f(sigma),
        "threshold": _f(thr),
        "n": n,
    }
