# -*- coding: utf-8 -*-
"""调研族 X 组（横截面统计 12 条）/ O 组（时间序列算子 15 条）真实实现。

口径来源：`docs/RESEARCH-INSTITUTIONAL-L1-METHODS.md` §2.1 / §2.2；
编号、名称、层级、最小样本一律取自 `research.py` 的 `specs_of()`（SSoT，此处不重复维护）。

数据契约：
  - X 组（``input_kind="panel"``）：``{"series": {sym: [num, ...]}}``，各序列等长（已对齐）。
    横截面在每个时间点上计算，输出**最近一期**横截面结果 + ``n``（标的数）。
  - O 组（``input_kind="series"``）：``[num, ...]`` 或 ``{"series": [...]}``；
    O09/O10 为双序列（``input_kind="pairs"``）：``{"x": [...], "y": [...]}``。
  - 窗口参数 ``d`` 缺省 20，越界时安全截断：delay 截到 ``[0, n-1]``，
    其余算子截到 ``[下限, n]``（单序列下限 2，双序列下限 3）。

纯确定性计算：无网络 / 无 DB / 无 LLM；仅 numpy 用于最小二乘求解。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import numpy as np

from ._helpers import (
    EPS,
    bucket,
    clean,
    mean,
    r6,
    series,
    std,
    two,
    var,
)
from .registry import register
from .research import specs_of

# ---------------------------------------------------------------- 元数据

_META: Dict[str, Tuple[str, str, str, str, int]] = {
    row[0]: row for row in specs_of("X") + specs_of("O")
}


def _meta(method_id: str) -> Dict[str, Any]:
    """从 SSoT 取 name/group/layer/min_n（缺失即导入期报错，不静默兜底）。"""
    _, name, group, layer, min_n = _META[method_id]
    return {"name": name, "group": group, "layer": layer, "min_n": min_n}


# ---------------------------------------------------------------- 通用工具


def _round_list(values: Sequence[Any]) -> List[Any]:
    return [None if v is None else r6(float(v)) for v in values]


def _window(params: Mapping[str, Any], n: int, minimum: int = 2) -> int:
    """窗口参数 d：缺省 20，越界截断到 [minimum, n]。"""
    try:
        d = int(params.get("d", 20))
    except (TypeError, ValueError):
        d = 20
    return max(minimum, min(d, n))


def _lag(params: Mapping[str, Any], n: int) -> int:
    """delay 的滞后阶：允许 0，截断到 [0, n-1]。"""
    try:
        d = int(params.get("d", 20))
    except (TypeError, ValueError):
        d = 20
    return max(0, min(d, n - 1))


def _roll(xs: Sequence[float], d: int, fn) -> List[Any]:
    """滚动窗口结果（长度与输入一致，i+1<d 的位置为 None）。"""
    out: List[Any] = []
    for i in range(len(xs)):
        out.append(None if i + 1 < d else fn(xs[i - d + 1 : i + 1]))
    return out


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    ma, mb = mean(list(a[:n])), mean(list(b[:n]))
    va = sum((x - ma) ** 2 for x in a[:n])
    vb = sum((y - mb) ** 2 for y in b[:n])
    if va <= EPS or vb <= EPS:
        return 0.0
    cov = sum((x - ma) * (y - mb) for x, y in zip(a[:n], b[:n], strict=True))
    return cov / math.sqrt(va * vb)


def _pct_rank(values: Sequence[float]) -> List[float]:
    """横截面百分位（pandas rank(pct=True) 同口径：平均法处理并列，再除以 n）。"""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg / n
        i = j + 1
    return ranks


# ---------------------------------------------------------------- 面板工具


def _panel(data: Any) -> Tuple[List[str], List[List[float]]]:
    """``{"series": {sym: [...]}}`` → (按名称升序的标的列表, 等长序列列表)。"""
    if not isinstance(data, Mapping):
        raise ValueError("panel data must be {'series': {sym: [...]}}")
    raw = data.get("series")
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError("panel data must contain non-empty 'series' mapping")
    names = sorted(str(k) for k in raw)
    by_key = {str(k): clean(raw[k]) for k in raw}
    cols: List[List[float]] = []
    for nm in names:
        vals = by_key[nm]
        if len(vals) < 2:
            raise ValueError(f"panel series {nm!r} needs at least 2 points")
        cols.append(vals)
    m = min(len(c) for c in cols)
    if len(names) < 3:
        raise ValueError("panel needs at least 3 symbols")
    return names, [c[-m:] for c in cols]


def _latest(data: Any) -> Tuple[List[str], List[float], List[float]]:
    names, cols = _panel(data)
    return names, [c[-1] for c in cols], [c[-2] for c in cols]


def _labels(names: Sequence[str], raw: Any) -> List[str]:
    if raw is None:
        return ["all"] * len(names)
    if isinstance(raw, Mapping):
        return [str(raw.get(nm, "all")) for nm in names]
    labels = [str(v) for v in raw]
    if len(labels) != len(names):
        raise ValueError("group labels must align with panel symbols")
    return labels


def _pick_exposure(raw: Any, name: str) -> float:
    """单因子暴露取值：mapping 按标的取（序列取末值），序列取均值。"""
    if isinstance(raw, Mapping):
        value = raw.get(name)
        if value is None:
            nums = [float(v) for v in raw.values() if v is not None]
            return mean(nums) if nums else 0.0
        if isinstance(value, Sequence) and not isinstance(value, str):
            clean_vals = clean(value)
            return clean_vals[-1] if clean_vals else 0.0
        return float(value)
    nums = [float(v) for v in raw if v is not None]
    return mean(nums) if nums else 0.0


def _exposure_matrix(
    factor: Any, names: Sequence[str]
) -> Tuple[List[str], List[List[float]], bool]:
    """因子暴露矩阵：返回 (因子名列表, 暴露列, 是否等权代理)。"""
    if factor is None:
        return ["market"], [[1.0] * len(names)], True
    if isinstance(factor, Mapping):
        if factor and all(isinstance(v, Mapping) for v in factor.values()):
            labels = sorted(str(k) for k in factor)
            cols = [[_pick_exposure(factor[lab], nm) for nm in names] for lab in labels]
            return labels, cols, False
        return ["factor"], [[_pick_exposure(factor, nm) for nm in names]], False
    if isinstance(factor, Sequence) and not isinstance(factor, str):
        vals = [float(v) for v in factor if v is not None]
        if len(vals) != len(names):
            raise ValueError("factor sequence must align with panel symbols")
        return ["factor"], [vals], False
    raise ValueError("factor must be a mapping or a sequence")


def _weights(raw: Any, names: Sequence[str]) -> List[float]:
    if raw is None:
        return [1.0] * len(names)
    if isinstance(raw, Mapping):
        vals = [abs(float(raw.get(nm) or 0.0)) for nm in names]
    else:
        vals = [abs(float(v)) for v in raw]
        if len(vals) != len(names):
            raise ValueError("weights must align with panel symbols")
    return vals if sum(vals) > EPS else [1.0] * len(names)


def _reg_fit(data: Any, params: Mapping[str, Any], *, weighted: bool):
    """横截面因子回归：r_i = α + Σ β_k f_ik + ε_i。

    返回 (names, y, labels, betas, alpha, r2, resid)。
    等权市场因子代理（factor 缺省）时暴露全为 1，与截距共线 → 退化为
    β = 横截面加权均值、α = 0、r2 = 0（口径在 notes 中声明）。
    """
    names, cols = _panel(data)
    y = np.array([c[-1] - c[-2] for c in cols], dtype=float)
    labels, exposures, proxy = _exposure_matrix(params.get("factor"), names)
    w = _weights(params.get("weights"), names) if weighted else None
    if proxy:
        ww = np.asarray(w, dtype=float) if w is not None else np.ones(len(y))
        beta = float((ww * y).sum() / ww.sum()) if ww.sum() > EPS else float(y.mean())
        return names, y, labels, {labels[0]: beta}, 0.0, 0.0, y - beta
    design = np.column_stack([np.ones(len(y))] + [np.asarray(c, dtype=float) for c in exposures])
    fit_x, fit_y = design, y
    if w is not None:
        sw = np.sqrt(np.asarray(w, dtype=float))
        fit_x, fit_y = design * sw[:, None], y * sw
    coef, *_ = np.linalg.lstsq(fit_x, fit_y, rcond=None)
    resid = y - design @ coef
    sse = float(resid @ resid)
    sst = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - sse / sst if sst > EPS else 0.0
    betas = {lab: float(coef[i + 1]) for i, lab in enumerate(labels)}
    return names, y, labels, betas, float(coef[0]), float(r2), resid


# ================================================================ X 组：横截面


@register(
    "X01",
    **_meta("X01"),
    input_kind="panel",
    output_schema=("z", "n"),
    notes="最近一期横截面 z=(x−mean_pool)/std_pool（样本标准差）；std=0 时 z 记 0",
)
def x01_zscore(data: Any, **params: Any) -> Dict[str, Any]:
    names, vals, _ = _latest(data)
    mu, sd = mean(vals), std(vals)
    z = {nm: (r6((v - mu) / sd) if sd > EPS else 0.0) for nm, v in zip(names, vals, strict=True)}
    return {"z": z, "n": len(names)}


@register(
    "X02",
    **_meta("X02"),
    input_kind="panel",
    output_schema=("pct", "n"),
    notes="最近一期横截面 rank(pct=True)：平均法处理并列后除以标的数",
)
def x02_pct_rank(data: Any, **params: Any) -> Dict[str, Any]:
    names, vals, _ = _latest(data)
    pct = _pct_rank(vals)
    return {"pct": {nm: r6(p) for nm, p in zip(names, pct, strict=True)}, "n": len(names)}


@register(
    "X03",
    **_meta("X03"),
    input_kind="panel",
    output_schema=("resid", "n"),
    notes="最近一期 x−group_mean；group 参数缺省时全样本同一组（即整体去均值）",
)
def x03_neutralize(data: Any, **params: Any) -> Dict[str, Any]:
    names, vals, _ = _latest(data)
    labels = _labels(names, params.get("group"))
    groups: Dict[str, List[float]] = {}
    for lab, v in zip(labels, vals, strict=True):
        groups.setdefault(lab, []).append(v)
    resid = {nm: r6(v - mean(groups[lab])) for nm, lab, v in zip(names, labels, vals, strict=True)}
    return {"resid": resid, "n": len(names)}


@register(
    "X04",
    **_meta("X04"),
    input_kind="panel",
    output_schema=("bucket", "counts", "n"),
    notes="最近一期等频分桶（k 缺省 5，线性插值分位）；bucket 为 0..k−1，counts 为各桶标的数",
)
def x04_quantile_bucket(data: Any, **params: Any) -> Dict[str, Any]:
    names, vals, _ = _latest(data)
    try:
        k = int(params.get("k", 5))
    except (TypeError, ValueError):
        k = 5
    k = max(2, min(k, len(vals)))
    _, ids = bucket(vals, k)
    counts: Dict[str, int] = {str(b): 0 for b in range(k)}
    for i in ids:
        counts[str(i)] += 1
    return {
        "bucket": {nm: int(i) for nm, i in zip(names, ids, strict=True)},
        "counts": counts,
        "n": len(names),
    }


@register(
    "X05",
    **_meta("X05"),
    input_kind="panel",
    output_schema=("spread", "t", "n"),
    notes="最近一期多空价差：最高分位均值 − 最低分位均值；t 为 Welch 两样本 t 值",
)
def x05_long_short(data: Any, **params: Any) -> Dict[str, Any]:
    _, vals, _ = _latest(data)
    try:
        k = int(params.get("k", 5))
    except (TypeError, ValueError):
        k = 5
    k = max(2, min(k, max(2, len(vals) // 2)))
    _, ids = bucket(vals, k)
    low = [v for v, i in zip(vals, ids, strict=True) if i == 0]
    high = [v for v, i in zip(vals, ids, strict=True) if i == k - 1]
    if not low or not high:
        return {"spread": 0.0, "t": 0.0, "n": len(vals)}
    spread = mean(high) - mean(low)
    se = math.sqrt(var(high) / len(high) + var(low) / len(low))
    t = spread / se if se > EPS else 0.0
    return {"spread": r6(spread), "t": r6(t), "n": len(vals)}


@register(
    "X06",
    **_meta("X06"),
    input_kind="panel",
    output_schema=("dispersion", "mean", "n"),
    notes="最近一期横截面离散度 std_pool（样本标准差）与横截面均值",
)
def x06_dispersion(data: Any, **params: Any) -> Dict[str, Any]:
    _, vals, _ = _latest(data)
    return {"dispersion": r6(std(vals)), "mean": r6(mean(vals)), "n": len(vals)}


@register(
    "X07",
    **_meta("X07"),
    input_kind="panel",
    output_schema=("breadth", "advance", "decline", "n"),
    notes="市场宽度：最近一期上涨家数 / 总家数（平盘计入分母但不计入上涨家数）",
)
def x07_breadth(data: Any, **params: Any) -> Dict[str, Any]:
    names, vals, prev = _latest(data)
    diffs = [v - p for v, p in zip(vals, prev, strict=True)]
    advance = sum(1 for d in diffs if d > 0)
    decline = sum(1 for d in diffs if d < 0)
    return {
        "breadth": r6(advance / len(names)),
        "advance": advance,
        "decline": decline,
        "n": len(names),
    }


@register(
    "X08",
    **_meta("X08"),
    input_kind="panel",
    output_schema=("ratio", "agree", "pairs", "n"),
    notes="同向率：最近一期同涨同跌对数 / 全部两两对数（平盘不计入分子）",
)
def x08_same_direction(data: Any, **params: Any) -> Dict[str, Any]:
    names, vals, prev = _latest(data)
    signs = [1 if v > p else (-1 if v < p else 0) for v, p in zip(vals, prev, strict=True)]
    agree = 0
    pairs = 0
    for i in range(len(signs)):
        for j in range(i + 1, len(signs)):
            pairs += 1
            if signs[i] != 0 and signs[i] == signs[j]:
                agree += 1
    ratio = agree / pairs if pairs else 0.0
    return {"ratio": r6(ratio), "agree": agree, "pairs": pairs, "n": len(names)}


@register(
    "X09",
    **_meta("X09"),
    input_kind="panel",
    output_schema=("betas", "alpha", "r2", "n"),
    notes="横截面 OLS：r_i = α + Σβ_k f_ik + ε_i（r 为最近一期收益）；"
    "factor 支持 {因子: {sym: 暴露}} / {sym: 暴露} / 等长暴露序列；"
    "缺省为等权市场因子代理（暴露全 1），与截距共线时退化为 β=横截面均值、α=0、r2=0",
)
def x09_factor_exposure(data: Any, **params: Any) -> Dict[str, Any]:
    names, _, _, betas, alpha, r2, _ = _reg_fit(data, params, weighted=False)
    return {
        "betas": {k: r6(v) for k, v in betas.items()},
        "alpha": r6(alpha),
        "r2": r6(r2),
        "n": len(names),
    }


@register(
    "X10",
    **_meta("X10"),
    input_kind="panel",
    output_schema=("specific", "std", "n"),
    notes="特质收益 ε_i（X09 同口径 OLS 残差）+ 残差跨标的样本标准差；"
    "factor 缺省为等权市场因子代理（退化为去均值）",
)
def x10_specific_return(data: Any, **params: Any) -> Dict[str, Any]:
    names, _, _, _, _, _, resid = _reg_fit(data, params, weighted=False)
    values = [float(v) for v in resid]
    return {
        "specific": {nm: r6(v) for nm, v in zip(names, values, strict=True)},
        "std": r6(std(values)),
        "n": len(names),
    }


@register(
    "X11",
    **_meta("X11"),
    input_kind="panel",
    output_schema=("factor_ret", "alpha", "r2", "n"),
    notes="因子收益：加权最小二乘（权重 = √weights，缺省等权）横截面回归的因子系数；"
    "r2 为未加权拟合优度；factor 缺省为等权市场因子代理",
)
def x11_factor_return(data: Any, **params: Any) -> Dict[str, Any]:
    names, _, _, betas, alpha, r2, _ = _reg_fit(data, params, weighted=True)
    return {
        "factor_ret": {k: r6(v) for k, v in betas.items()},
        "alpha": r6(alpha),
        "r2": r6(r2),
        "n": len(names),
    }


@register(
    "X12",
    **_meta("X12"),
    input_kind="panel",
    output_schema=("rho", "n", "lag"),
    notes="横截面自相关：corr(rank_t, rank_{t−1})，秩为平均法百分位（Spearman 口径）",
)
def x12_cross_autocorr(data: Any, **params: Any) -> Dict[str, Any]:
    names, vals, prev = _latest(data)
    rho = _pearson(_pct_rank(vals), _pct_rank(prev))
    return {"rho": r6(rho), "n": len(names), "lag": 1}


# ================================================================ O 组：时序算子


@register(
    "O01",
    **_meta("O01"),
    input_kind="series",
    output_schema=("series", "n"),
    notes="delay(x, d)=x_{t−d}；d 缺省 20，首 d 位为 None",
)
def o01_delay(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    n = len(xs)
    d = _lag(params, n)
    out = ([None] * d + list(xs[:-d])) if d else list(xs)
    return {"series": _round_list(out), "n": n}


@register(
    "O02",
    **_meta("O02"),
    input_kind="series",
    output_schema=("series", "n"),
    notes="delta(x, d)=x_t−x_{t−d}；d 缺省 20，前 d 位为 None",
)
def o02_delta(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    n = len(xs)
    d = _window(params, n, 1)
    out = [None if i < d else xs[i] - xs[i - d] for i in range(n)]
    return {"series": _round_list(out), "n": n}


@register(
    "O03",
    **_meta("O03"),
    input_kind="series",
    output_schema=("series", "n"),
    notes="ts_sum(x, d)=Σ_{i=0..d−1} x_{t−i}；d 缺省 20，越界截断到 [2, n]",
)
def o03_ts_sum(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    n = len(xs)
    d = _window(params, n, 2)
    return {"series": _round_list(_roll(xs, d, sum)), "n": n}


@register(
    "O04",
    **_meta("O04"),
    input_kind="series",
    output_schema=("mean", "std", "n"),
    notes="ts_mean / ts_std：滚动均值与样本标准差（ddof=1）；d 缺省 20，越界截断",
)
def o04_ts_mean_std(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    n = len(xs)
    d = _window(params, n, 2)
    return {
        "mean": _round_list(_roll(xs, d, lambda w: mean(list(w)))),
        "std": _round_list(_roll(xs, d, lambda w: std(list(w)))),
        "n": n,
    }


@register(
    "O05",
    **_meta("O05"),
    input_kind="series",
    output_schema=("min", "max", "n"),
    notes="ts_min / ts_max：滚动极值；d 缺省 20，越界截断到 [2, n]",
)
def o05_ts_min_max(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    n = len(xs)
    d = _window(params, n, 2)
    return {
        "min": _round_list(_roll(xs, d, min)),
        "max": _round_list(_roll(xs, d, max)),
        "n": n,
    }


@register(
    "O06",
    **_meta("O06"),
    input_kind="series",
    output_schema=("argmax", "argmin", "n"),
    notes="ts_argmax / ts_argmin：窗口极值距今天数（0=当期，d−1=窗口最老）；"
    "并列取最早出现位置；d 缺省 20，越界截断到 [2, n]",
)
def o06_ts_arg_extreme(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    n = len(xs)
    d = _window(params, n, 2)

    def _ago(win: Sequence[float], want_max: bool) -> int:
        target = max(win) if want_max else min(win)
        return len(win) - 1 - win.index(target)

    return {
        "argmax": _roll(xs, d, lambda w: _ago(w, True)),
        "argmin": _roll(xs, d, lambda w: _ago(w, False)),
        "n": n,
    }


@register(
    "O07",
    **_meta("O07"),
    input_kind="series",
    output_schema=("series", "n"),
    notes="ts_rank(x, d)：当期值在窗口内的百分位（平均法处理并列）；d 缺省 20，越界截断",
)
def o07_ts_rank(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    n = len(xs)
    d = _window(params, n, 2)

    def _rank(win: Sequence[float]) -> float:
        cur = win[-1]
        less = sum(1 for v in win if v < cur)
        equal = sum(1 for v in win if v == cur)
        return (less + (equal + 1) / 2.0) / len(win)

    return {"series": _round_list(_roll(xs, d, _rank)), "n": n}


@register(
    "O08",
    **_meta("O08"),
    input_kind="series",
    output_schema=("series", "n"),
    notes="ts_zscore(x, d)=(x_t−ts_mean)/ts_std；std=0 记 0；d 缺省 20，越界截断",
)
def o08_ts_zscore(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    n = len(xs)
    d = _window(params, n, 2)

    def _z(win: Sequence[float]) -> float:
        mu, sd = mean(list(win)), std(list(win))
        return (win[-1] - mu) / sd if sd > EPS else 0.0

    return {"series": _round_list(_roll(xs, d, _z)), "n": n}


@register(
    "O09",
    **_meta("O09"),
    input_kind="pairs",
    output_schema=("corr", "n"),
    notes="ts_corr(x, y, d)：滚动 Pearson 相关；d 缺省 20，越界截断到 [3, n]",
)
def o09_ts_corr(data: Any, **params: Any) -> Dict[str, Any]:
    xs, ys = two(data)
    n = min(len(xs), len(ys))
    d = _window(params, n, 3)
    out = []
    for i in range(n):
        if i + 1 < d:
            out.append(None)
        else:
            out.append(_pearson(xs[i - d + 1 : i + 1], ys[i - d + 1 : i + 1]))
    return {"corr": _round_list(out), "n": n}


@register(
    "O10",
    **_meta("O10"),
    input_kind="pairs",
    output_schema=("cov", "n"),
    notes="ts_cov(x, y, d)：滚动样本协方差（ddof=1）；d 缺省 20，越界截断到 [3, n]",
)
def o10_ts_cov(data: Any, **params: Any) -> Dict[str, Any]:
    xs, ys = two(data)
    n = min(len(xs), len(ys))
    d = _window(params, n, 3)

    def _cov(wa: Sequence[float], wb: Sequence[float]) -> float:
        ma, mb = mean(list(wa)), mean(list(wb))
        return sum((a - ma) * (b - mb) for a, b in zip(wa, wb, strict=True)) / (len(wa) - 1)

    out = []
    for i in range(n):
        if i + 1 < d:
            out.append(None)
        else:
            lo = i - d + 1
            out.append(_cov(xs[lo : i + 1], ys[lo : i + 1]))
    return {"cov": _round_list(out), "n": n}


@register(
    "O11",
    **_meta("O11"),
    input_kind="series",
    output_schema=("series", "n"),
    notes="decay_linear(x, d)：线性衰减加权均值，最近一期权重 d、向前递减至 1；"
    "d 缺省 20，越界截断到 [2, n]",
)
def o11_decay_linear(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    n = len(xs)
    d = _window(params, n, 2)

    def _decay(win: Sequence[float]) -> float:
        w = [float(j + 1) for j in range(len(win))]  # 窗口内由老到新，新值权重最大
        total = sum(w)
        return sum(wj * v for wj, v in zip(w, win, strict=True)) / total

    return {"series": _round_list(_roll(xs, d, _decay)), "n": n}


@register(
    "O12",
    **_meta("O12"),
    input_kind="series",
    output_schema=("scaled", "a", "n"),
    notes="scale(x, a)=x·a/Σ|x|（a 缺省 1.0，对整个输入序列归一）；Σ|x|=0 时全 0",
)
def o12_scale(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    try:
        a = float(params.get("a", 1.0))
    except (TypeError, ValueError):
        a = 1.0
    total = sum(abs(v) for v in xs)
    scaled = [v * a / total if total > EPS else 0.0 for v in xs]
    return {"scaled": _round_list(scaled), "a": r6(a), "n": len(xs)}


@register(
    "O13",
    **_meta("O13"),
    input_kind="series",
    output_schema=("series", "n"),
    notes="signedpower(x, e)=sign(x)·|x|^e（e 缺省 2.0）",
)
def o13_signedpower(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    try:
        e = float(params.get("e", 2.0))
    except (TypeError, ValueError):
        e = 2.0
    out = [math.copysign(abs(v) ** e, v) if v != 0 else 0.0 for v in xs]
    return {"series": _round_list(out), "n": len(xs)}


@register(
    "O14",
    **_meta("O14"),
    input_kind="series",
    output_schema=("rank", "n"),
    notes="rank(x)：输入序列内部横截面百分位（pandas rank(pct=True) 同口径，并列取平均秩）",
)
def o14_rank(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    return {"rank": _round_list(_pct_rank(xs)), "n": len(xs)}


@register(
    "O15",
    **_meta("O15"),
    input_kind="series",
    output_schema=("resid", "group_n", "n"),
    notes="indneutralize(x, g)：组内去均值，g 为与序列等长的分组标签（参数名 g / group）；"
    "缺省全部同组（整体去均值）",
)
def o15_indneutralize(data: Any, **params: Any) -> Dict[str, Any]:
    xs = series(data)
    n = len(xs)
    raw = params.get("g", params.get("group"))
    if raw is None:
        labels = ["all"] * n
    else:
        labels = [str(v) for v in raw]
        if len(labels) != n:
            raise ValueError("group labels must align with the series")
    buckets: Dict[str, List[float]] = {}
    for lab, v in zip(labels, xs, strict=True):
        buckets.setdefault(lab, []).append(v)
    resid = [v - mean(buckets[lab]) for lab, v in zip(labels, xs, strict=True)]
    return {"resid": _round_list(resid), "group_n": len(buckets), "n": n}
