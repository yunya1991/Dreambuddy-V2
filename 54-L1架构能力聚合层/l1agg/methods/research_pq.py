# -*- coding: utf-8 -*-
"""调研族 P 组（风险与组合描述 P01–P14）与 Q 组（研究与检验协议 Q01–Q16）实现。

口径来源：`docs/RESEARCH-INSTITUTIONAL-L1-METHODS.md` §2.3 / §2.4；
编号、名称、层级、最小样本的唯一真源是 `research.specs_of("P"/"Q")`。

约定：
  - P 组统一 `input_kind="panel"`，数据 `{"returns": {sym: [日收益...]}}`（等长对齐），
    另兼容 `{"series": {...}}` 与扁平 `{sym: [...]}` 两种写法；
  - Q 组在函数内兼容 `{"factor","forward"}` / `{"x","y"}` / `{"series"}` 契约；
  - 只描述历史样本，不外推、不给交易建议；
  - 无网络、无 DB；随机过程固定 seed（默认 42）；浮点统一 r4/r6；
  - 维度/长度不满足前提时抛 ValueError（样本门禁由 `registry.run` 统一处理）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import numpy as np

from ._helpers import norm_cdf, norm_ppf, r4, r6
from .registry import register
from .research import specs_of
from .stats_core import t_two_sided_p

_EPS = 1e-12
_EULER = 0.5772156649015329


# ============================================================
# 元数据（name/group/layer/min_n 全部取自 research.py 的 SSoT）
# ============================================================

_META: Dict[str, Dict[str, Tuple[str, str, str, str, int]]] = {
    group: {row[0]: row for row in specs_of(group)} for group in ("P", "Q")
}


def _meta(method_id: str, *, input_kind: str = "panel") -> Dict[str, Any]:
    _id, name, group, layer, min_n = _META[method_id[0]][method_id]
    return {
        "method_id": _id,
        "name": name,
        "group": group,
        "layer": layer,
        "input_kind": input_kind,
        "min_n": min_n,
    }


# ============================================================
# 输入契约
# ============================================================


def _seq(value: Any) -> List[float]:
    """数值序列清洗：丢弃 None / 非有限值，保持原顺序。"""
    out: List[float] = []
    for v in value:
        if v is None:
            continue
        f = float(v)
        if math.isfinite(f):
            out.append(f)
    return out


def _panel(data: Any) -> Tuple[List[str], np.ndarray]:
    """P 组面板：返回 (symbols, T×d 收益矩阵)，按最小公共长度对齐。"""
    if not isinstance(data, Mapping):
        raise ValueError("panel data must be a mapping of symbol -> returns")
    inner: Any = None
    for key in ("returns", "series", "panel"):
        candidate = data.get(key)
        if isinstance(candidate, Mapping):
            inner = candidate
            break
    if inner is None:
        inner = {
            k: v for k, v in data.items() if isinstance(v, Sequence) and not isinstance(v, str)
        }
    if not inner:
        raise ValueError("empty panel: no symbol series found")
    by_name = {str(k): v for k, v in inner.items()}
    syms = sorted(by_name)
    cols = [_seq(by_name[s]) for s in syms]
    if not all(cols):
        raise ValueError("empty symbol series in panel")
    n = min(len(c) for c in cols)
    if n < 2:
        raise ValueError("panel needs at least 2 aligned observations")
    mat = np.column_stack([np.asarray(c[:n], dtype=float) for c in cols])
    return syms, mat


def _weights(syms: Sequence[str], source: Any) -> np.ndarray:
    """权重向量（缺失/全零时退化为等权，并归一化到和 1）。"""
    d = len(syms)
    if source is None:
        return np.full(d, 1.0 / d)
    if isinstance(source, Mapping):
        vec = np.asarray([float(source.get(s, 0.0)) for s in syms], dtype=float)
    else:
        vals = _seq(source)[:d]
        vec = np.zeros(d, dtype=float)
        vec[: len(vals)] = vals
    total = float(vec.sum())
    if total <= _EPS:
        return np.full(d, 1.0 / d)
    return vec / total


def _cov(R: np.ndarray) -> np.ndarray:
    n = R.shape[0]
    if n < 2:
        raise ValueError("covariance needs n>=2")
    X = R - R.mean(axis=0)
    return X.T @ X / (n - 1)


def _vols(R: np.ndarray, window: int, periods: int) -> Tuple[np.ndarray, int]:
    """实现波动率：std(logret, window)·√periods（等权样本标准差 ddof=1）。"""
    w = int(max(2, min(int(window), R.shape[0])))
    sub = R[-w:]
    if np.all(sub > -1.0):
        sub = np.log1p(sub)
    return sub.std(axis=0, ddof=1) * math.sqrt(float(periods)), w


def _two(data: Any) -> Tuple[np.ndarray, np.ndarray]:
    """Q 组双序列：factor/forward、factor/target、x/y、actual/expected。"""
    if not isinstance(data, Mapping):
        raise ValueError("paired data must be a mapping")
    for a, b in (
        ("factor", "forward"),
        ("factor", "target"),
        ("x", "y"),
        ("actual", "expected"),
    ):
        if a in data and b in data:
            xs, ys = _seq(data[a]), _seq(data[b])
            n = min(len(xs), len(ys))
            if n < 3:
                raise ValueError("need at least 3 paired points")
            return np.asarray(xs[:n], dtype=float), np.asarray(ys[:n], dtype=float)
    raise ValueError("paired data must contain factor/forward, x/y or actual/expected")


def _series(data: Any) -> np.ndarray:
    """Q 组单序列：series/values/x/returns/price，或裸 list。"""
    if isinstance(data, Mapping):
        for key in ("series", "values", "x", "returns", "price"):
            if key in data:
                return np.asarray(_seq(data[key]), dtype=float)
        raise ValueError("series data must contain series/values/x/returns/price")
    return np.asarray(_seq(data), dtype=float)


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    n = min(len(x), len(y))
    if n < 3:
        return None
    xs, ys = x[:n], y[:n]
    sx, sy = xs.std(), ys.std()
    if sx <= _EPS or sy <= _EPS:
        return 0.0
    return float(np.corrcoef(xs, ys)[0, 1])


def _rank(x: np.ndarray) -> np.ndarray:
    """平均秩（并列取中位秩），与 scipy.stats.rankdata 同口径。"""
    n = len(x)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(1, n + 1, dtype=float)
    xs = x[order]
    i = 0
    while i < n:
        j = i + 1
        while j < n and xs[j] == xs[i]:
            j += 1
        if j - i > 1:
            ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    return ranks


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    return _pearson(_rank(x), _rank(y))


def _rho_p(rho: float, k: int) -> float:
    if rho is None or k < 3:
        return None
    r = min(max(rho, -0.999999), 0.999999)
    t = r * math.sqrt((k - 2) / (1.0 - r * r))
    return r6(t_two_sided_p(t, k - 2))


# ============================================================
# P01–P14 风险与组合描述
# ============================================================


@register(
    **_meta("P01"),
    output_schema=("vol", "window", "n", "symbols"),
    notes="std(logret,20)·√365，窗口内等权样本标准差（ddof=1）",
)
def p01_realized_vol(data: Any, window: int = 20, periods: int = 365, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    vol, w = _vols(R, window, periods)
    return {
        "vol": {s: r6(v) for s, v in zip(syms, vol, strict=False)},
        "window": w,
        "n": int(R.shape[0]),
        "symbols": syms,
    }


@register(
    **_meta("P02"),
    output_schema=("scale", "realized", "target_vol", "n"),
    notes="scale = target_vol / realized_vol（realized 为 0 时 scale 记 0）",
)
def p02_vol_target(
    data: Any,
    target_vol: float = 0.10,
    window: int = 20,
    periods: int = 365,
    **_: Any,
) -> Dict[str, Any]:
    syms, R = _panel(data)
    vol, _ = _vols(R, window, periods)
    scale = {
        s: r6(float(target_vol) / v) if v > _EPS else 0.0 for s, v in zip(syms, vol, strict=False)
    }
    return {
        "scale": scale,
        "realized": {s: r6(v) for s, v in zip(syms, vol, strict=False)},
        "target_vol": r6(target_vol),
        "n": int(R.shape[0]),
    }


@register(
    **_meta("P03"),
    output_schema=("weights", "vols", "n"),
    notes="w_i = (1/σ_i)/Σ(1/σ_j)；σ_i 为窗口内实现波动率",
)
def p03_inverse_vol(data: Any, window: int = 20, periods: int = 365, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    vol, _ = _vols(R, window, periods)
    inv = np.where(vol > _EPS, 1.0 / np.maximum(vol, _EPS), 0.0)
    if inv.sum() <= _EPS:
        inv = np.ones_like(vol)
    w = inv / inv.sum()
    return {
        "weights": {s: r6(v) for s, v in zip(syms, w, strict=False)},
        "vols": {s: r6(v) for s, v in zip(syms, vol, strict=False)},
        "n": int(R.shape[0]),
    }


def _erc_weights(S: np.ndarray, tol: float = 1e-10, max_iter: int = 500) -> Tuple[np.ndarray, int]:
    """等风险贡献权重：循环坐标下降解 min ½wᵀΣw − Σ b_i ln w_i（b_i=1/d）。

    坐标 i 的一阶条件给出 σ_ii w_i² + c_i w_i − b_i = 0（c_i=Σ_{j≠i}σ_ij w_j），
    取正根更新；固定迭代上限 + 容差，全程无随机数，结果可复现。
    """
    d = S.shape[0]
    diag = np.diag(S).astype(float)
    if d == 0:
        raise ValueError("empty covariance")
    if np.any(diag <= _EPS):
        return np.full(d, 1.0 / d), 0
    b = np.full(d, 1.0 / d)
    w = 1.0 / np.sqrt(diag)
    w = w / w.sum()
    iters = 0
    for it in range(1, int(max_iter) + 1):
        prev = w.copy()
        for i in range(d):
            c = float(S[i] @ w - diag[i] * w[i])
            w[i] = (-c + math.sqrt(c * c + 4.0 * diag[i] * b[i])) / (2.0 * diag[i])
        iters = it
        if float(np.max(np.abs(w - prev))) < float(tol):
            break
    return w / w.sum(), iters


@register(
    **_meta("P04"),
    output_schema=("weights", "risk_contrib", "n", "iterations"),
    notes="等风险贡献：循环坐标下降 500 次上限、容差 1e-10；RC 为波动单位",
)
def p04_erc(data: Any, tol: float = 1e-10, max_iter: int = 500, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    S = _cov(R)
    w, iters = _erc_weights(S, tol=tol, max_iter=max_iter)
    sigma = math.sqrt(max(float(w @ S @ w), 0.0))
    rc = w * (S @ w) / sigma if sigma > _EPS else np.zeros_like(w)
    return {
        "weights": {s: r6(v) for s, v in zip(syms, w, strict=False)},
        "risk_contrib": {s: r6(v) for s, v in zip(syms, rc, strict=False)},
        "n": int(R.shape[0]),
        "iterations": iters,
    }


@register(
    **_meta("P05"),
    output_schema=("weights", "risk_contrib", "share", "total_risk", "n"),
    notes="RC_i = w_i(Σw)_i/σ_p，ΣRC_i = σ_p；share_i = RC_i/σ_p",
)
def p05_risk_contrib(data: Any, weights: Any = None, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    S = _cov(R)
    src = weights
    if src is None and isinstance(data, Mapping):
        src = data.get("weights", data.get("w"))
    w = _weights(syms, src)
    sigma = math.sqrt(max(float(w @ S @ w), 0.0))
    rc = w * (S @ w) / sigma if sigma > _EPS else np.zeros_like(w)
    share = rc / sigma if sigma > _EPS else np.zeros_like(w)
    return {
        "weights": {s: r6(v) for s, v in zip(syms, w, strict=False)},
        "risk_contrib": {s: r6(v) for s, v in zip(syms, rc, strict=False)},
        "share": {s: r6(v) for s, v in zip(syms, share, strict=False)},
        "total_risk": r6(sigma),
        "n": int(R.shape[0]),
    }


def _lw_analytic(X: np.ndarray) -> Tuple[np.ndarray, float]:
    """Ledoit–Wolf（常相关目标）解析收缩强度：δ = π̂/(T·γ̂)，截断到 [0,1]。"""
    T, d = X.shape
    Xc = X - X.mean(axis=0)
    S = Xc.T @ Xc / T  # 与 LW 一致用 1/T
    sd = np.sqrt(np.diag(S))
    if d < 2 or np.any(sd <= _EPS):
        return S, 0.0
    corr = S / np.outer(sd, sd)
    off_diag = corr[~np.eye(d, dtype=bool)]
    rbar = float(off_diag.mean())
    F = rbar * np.outer(sd, sd)
    np.fill_diagonal(F, np.diag(S))
    z = Xc[:, :, None] * Xc[:, None, :]
    pi_hat = float(z.var(axis=0, ddof=0).sum())
    gamma = float(((F - S) ** 2).sum())
    delta = 0.0 if gamma <= _EPS else float(np.clip((pi_hat / T) / gamma, 0.0, 1.0))
    return delta * F + (1.0 - delta) * S, delta


def _shrink_cov(X: np.ndarray) -> Tuple[np.ndarray, float, str]:
    try:
        from sklearn.covariance import ledoit_wolf

        cov, delta = ledoit_wolf(X, assume_centered=False)
        return np.asarray(cov, dtype=float), float(delta), "sklearn"
    except Exception:
        cov, delta = _lw_analytic(X)
        return np.asarray(cov, dtype=float), float(delta), "analytic"


@register(
    **_meta("P06"),
    output_schema=("delta", "cov", "symbols", "backend", "n"),
    notes="Σ̂ = δF + (1−δ)S；sklearn 可用时用其解析解，否则用 π̂/(Tγ̂) 简化解析式",
)
def p06_cov_shrinkage(data: Any, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    cov, delta, backend = _shrink_cov(R)
    return {
        "delta": r6(delta),
        "cov": [[r6(v) for v in row] for row in cov],
        "symbols": syms,
        "backend": backend,
        "n": int(R.shape[0]),
    }


@register(
    **_meta("P07"),
    output_schema=("lam", "vol", "cov", "symbols", "n"),
    notes="EWMA 协方差 S_t=λS_{t−1}+(1−λ)r_t r_tᵀ，λ 日频 0.94 / 月频 0.97",
)
def p07_ewma(
    data: Any, lam: float = 0.94, init_window: int = 20, periods: int = 365, **_: Any
) -> Dict[str, Any]:
    syms, R = _panel(data)
    T, d = R.shape
    lam = min(max(float(lam), 0.0), 0.999999)
    init = int(max(2, min(int(init_window), T)))
    S = _cov(R[:init])
    for t in range(init, T):
        r = R[t]
        S = lam * S + (1.0 - lam) * np.outer(r, r)
    vol = np.sqrt(np.maximum(np.diag(S), 0.0)) * math.sqrt(float(periods))
    return {
        "lam": r6(lam),
        "vol": {s: r6(v) for s, v in zip(syms, vol, strict=False)},
        "cov": [[r6(v) for v in row] for row in S],
        "symbols": syms,
        "n": T,
    }


@register(
    **_meta("P08"),
    output_schema=("ratio", "loadings", "k", "n"),
    notes="协方差特征分解，前 k 主成分解释比例 + 载荷（符号约定：最大绝对载荷为正）",
)
def p08_pca(data: Any, k: int = 3, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    S = _cov(R)
    vals, vecs = np.linalg.eigh(S)
    order = np.argsort(vals)[::-1]
    d = len(syms)
    kk = int(max(1, min(int(k), d)))
    vals = np.maximum(vals[order], 0.0)
    total = float(vals.sum())
    ratio = vals[:kk] / total if total > _EPS else np.zeros(kk)
    loadings = []
    for idx in order[:kk]:
        vec = vecs[:, idx].copy()
        pivot = int(np.argmax(np.abs(vec)))
        if vec[pivot] < 0:
            vec = -vec
        loadings.append([r6(v) for v in vec])
    return {
        "ratio": [r6(v) for v in ratio],
        "loadings": loadings,
        "k": kk,
        "n": int(R.shape[0]),
    }


@register(
    **_meta("P09"),
    output_schema=("var", "sigma", "z", "weights", "n"),
    notes="参数法 VaR：VaR = z·√(wᵀΣw)，95% 取 z=1.645",
)
def p09_param_var(data: Any, z: float = 1.645, weights: Any = None, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    S = _cov(R)
    src = weights
    if src is None and isinstance(data, Mapping):
        src = data.get("weights", data.get("w"))
    w = _weights(syms, src)
    sigma = math.sqrt(max(float(w @ S @ w), 0.0))
    return {
        "var": r6(float(z) * sigma),
        "sigma": r6(sigma),
        "z": r6(z),
        "weights": {s: r6(v) for s, v in zip(syms, w, strict=False)},
        "n": int(R.shape[0]),
    }


@register(
    **_meta("P10"),
    output_schema=("cvar", "var_hist", "quantile", "weights", "n"),
    notes="历史法 CVaR：−mean(r ≤ P5)，var_hist = −P5",
)
def p10_cvar(data: Any, quantile: float = 0.05, weights: Any = None, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    src = weights
    if src is None and isinstance(data, Mapping):
        src = data.get("weights", data.get("w"))
    w = _weights(syms, src)
    port = R @ w
    q = float(quantile)
    q = min(max(q, 1e-6), 0.5)
    thr = float(np.quantile(port, q))
    tail = port[port <= thr]
    cvar = float(-tail.mean()) if tail.size else float(-thr)
    return {
        "cvar": r6(cvar),
        "var_hist": r6(-thr),
        "quantile": r4(q),
        "weights": {s: r6(v) for s, v in zip(syms, w, strict=False)},
        "n": int(R.shape[0]),
    }


@register(
    **_meta("P11"),
    output_schema=("underwater", "max_drawdown", "symbols", "n"),
    notes="水下曲线 1 − cum/cummax，仅输入收益序列（等权复利净值）",
)
def p11_underwater(data: Any, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    equity = np.cumprod(1.0 + R, axis=0)
    peak = np.maximum.accumulate(equity, axis=0)
    uw = 1.0 - equity / np.where(np.abs(peak) > _EPS, peak, 1.0)
    return {
        "underwater": {s: [r6(v) for v in uw[:, j]] for j, s in enumerate(syms)},
        "max_drawdown": {s: r6(float(uw[:, j].max())) for j, s in enumerate(syms)},
        "symbols": syms,
        "n": int(R.shape[0]),
    }


@register(
    **_meta("P12"),
    output_schema=("allocation", "selection", "interaction", "active_return", "n"),
    notes="Brinson 三分解（时间平均权重/收益）：A+S+I = 主动收益",
)
def p12_brinson(data: Any, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    mu = R.mean(axis=0)
    base: Mapping[str, Any] = data if isinstance(data, Mapping) else {}
    wv = _weights(syms, base.get("w", base.get("weights")))
    wbv = _weights(syms, base.get("wb", base.get("benchmark_weights")))
    sector_map = base.get("sector", base.get("sectors", {}))
    if isinstance(sector_map, Mapping):
        labels = [str(sector_map.get(s, s)) for s in syms]
    else:
        labels = [str(s) for s in syms]
    groups: Dict[str, List[int]] = {}
    for j, label in enumerate(labels):
        groups.setdefault(label, []).append(j)
    allocation = selection = interaction = 0.0
    for idx in groups.values():
        W = float(wv[idx].sum())
        Wb = float(wbv[idx].sum())
        Rs = float((wv[idx] * mu[idx]).sum() / W) if W > _EPS else 0.0
        Rb = float((wbv[idx] * mu[idx]).sum() / Wb) if Wb > _EPS else 0.0
        allocation += (W - Wb) * Rb
        selection += Wb * (Rs - Rb)
        interaction += (W - Wb) * (Rs - Rb)
    active = float((wv * mu).sum() - (wbv * mu).sum())
    return {
        "allocation": r6(allocation),
        "selection": r6(selection),
        "interaction": r6(interaction),
        "active_return": r6(active),
        "n": int(R.shape[0]),
    }


@register(
    **_meta("P13"),
    output_schema=("rho_down", "rho_full", "n_down", "n"),
    notes="尾部相关：横截面均值收益 ≤ q 分位的样本内两两相关",
)
def p13_tail_corr(data: Any, q: float = 0.2, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    if R.shape[1] < 2:
        raise ValueError("tail correlation needs at least 2 symbols")
    cross = R.mean(axis=1)
    qq = min(max(float(q), 1e-3), 0.5)
    thr = float(np.quantile(cross, qq))
    mask = cross <= thr
    rho_down: Dict[str, Any] = {}
    rho_full: Dict[str, Any] = {}
    for i in range(R.shape[1]):
        for j in range(i + 1, R.shape[1]):
            key = f"{syms[i]}|{syms[j]}"
            rho_full[key] = r6(_pearson(R[:, i], R[:, j]))
            rho_down[key] = r6(_pearson(R[mask, i], R[mask, j])) if mask.sum() >= 3 else None
    return {
        "rho_down": rho_down,
        "rho_full": rho_full,
        "n_down": int(mask.sum()),
        "n": int(R.shape[0]),
    }


@register(
    **_meta("P14"),
    output_schema=("stability", "mean_rho", "std_rho", "window", "n"),
    notes="相关性稳定性：滚动相关 std/mean（mean≈0 时记 None）",
)
def p14_corr_stability(data: Any, window: int = 60, **_: Any) -> Dict[str, Any]:
    syms, R = _panel(data)
    if R.shape[1] < 2:
        raise ValueError("correlation stability needs at least 2 symbols")
    T = R.shape[0]
    w = int(max(3, min(int(window), T)))
    stability: Dict[str, Any] = {}
    pooled: List[float] = []
    for i in range(R.shape[1]):
        for j in range(i + 1, R.shape[1]):
            key = f"{syms[i]}|{syms[j]}"
            corrs = [_pearson(R[t : t + w, i], R[t : t + w, j]) for t in range(0, T - w + 1)]
            corrs = [c for c in corrs if c is not None]
            if not corrs:
                stability[key] = None
                continue
            mu = float(np.mean(corrs))
            sd = float(np.std(corrs, ddof=1)) if len(corrs) > 1 else 0.0
            stability[key] = r6(sd / mu) if abs(mu) > 1e-6 else None
            pooled.extend(corrs)
    return {
        "stability": stability,
        "mean_rho": r6(float(np.mean(pooled))) if pooled else None,
        "std_rho": r6(float(np.std(pooled, ddof=1))) if len(pooled) > 1 else None,
        "window": w,
        "n": T,
    }


# ============================================================
# Q01–Q16 研究与检验协议
# ============================================================


@register(
    **_meta("Q01", input_kind="series"),
    output_schema=("ic", "rank_ic", "n"),
    notes="corr(factor_t, fwd_ret_{t+1})：Pearson IC + Spearman RankIC",
)
def q01_ic(data: Any, **_: Any) -> Dict[str, Any]:
    x, y = _two(data)
    return {
        "ic": r6(_pearson(x, y)),
        "rank_ic": r6(_spearman(x, y)),
        "n": int(len(x)),
    }


@register(
    **_meta("Q02", input_kind="series"),
    output_schema=("icir", "ic_mean", "ic_std", "n_periods", "n"),
    notes="ICIR = mean(IC)/std(IC)；无 IC 序列时按 window 切片计算分段 IC",
)
def q02_icir(data: Any, window: int = 20, **_: Any) -> Dict[str, Any]:
    if isinstance(data, Mapping) and "ic" in data:
        ics = _seq(data["ic"])
        n = len(ics)
    else:
        x, y = _two(data)
        n = len(x)
        w = int(max(5, min(int(window), n)))
        ics = [_pearson(x[i : i + w], y[i : i + w]) for i in range(0, n - w + 1, w)]
        ics = [v for v in ics if v is not None]
    if len(ics) < 2:
        raise ValueError("ICIR needs at least 2 IC periods")
    arr = np.asarray(ics, dtype=float)
    mu = float(arr.mean())
    sd = float(arr.std(ddof=1))
    return {
        "icir": r6(mu / sd) if sd > _EPS else None,
        "ic_mean": r6(mu),
        "ic_std": r6(sd),
        "n_periods": len(ics),
        "n": int(n),
    }


@register(
    **_meta("Q03", input_kind="series"),
    output_schema=("ic_by_h", "horizons", "n"),
    notes="IC 衰减表：h∈{1,3,5,10,20} 的前瞻累计收益与当期因子相关",
)
def q03_ic_decay(
    data: Any, horizons: Sequence[int] = (1, 3, 5, 10, 20), **_: Any
) -> Dict[str, Any]:
    if not isinstance(data, Mapping) or "factor" not in data:
        raise ValueError("IC decay needs {'factor': [...]} plus returns/price/forward")
    f = np.asarray(_seq(data["factor"]), dtype=float)
    n = len(f)

    def target(h: int) -> np.ndarray:
        if "price" in data:
            p = np.asarray(_seq(data["price"]), dtype=float)
            m = min(n, len(p))
            return p[h:m] / p[: m - h] - 1.0
        if "returns" in data:
            r = np.asarray(_seq(data["returns"]), dtype=float)
            m = min(n, len(r))
            cs = np.concatenate([[0.0], np.cumsum(r[:m])])
            return cs[h + 1 :] - cs[1 : len(cs) - h]
        raise ValueError("IC decay needs returns or price series")

    hs = [int(h) for h in horizons]
    ic_by_h: Dict[str, Any] = {}
    for h in hs:
        if h < 1 or n - h < 3:
            ic_by_h[str(h)] = None
            continue
        y = target(h)
        ic_by_h[str(h)] = r6(_pearson(f[: len(y)], y))
    return {"ic_by_h": ic_by_h, "horizons": hs, "n": n}


@register(
    **_meta("Q04", input_kind="series"),
    output_schema=("rho", "p", "bucket_returns", "monotonic", "k", "n"),
    notes="分位单调性：k 分位组合平均收益与分位序号的 Spearman",
)
def q04_quantile_monotonic(data: Any, k: int = 5, **_: Any) -> Dict[str, Any]:
    x, y = _two(data)
    n = len(x)
    kk = int(max(3, min(int(k), n)))
    edges = np.quantile(x, np.linspace(0.0, 1.0, kk + 1))
    ids = np.searchsorted(edges[1:-1], x, side="right")
    means: List[float] = []
    raw: Dict[str, Any] = {}
    for b in range(kk):
        sub = y[ids == b]
        means.append(float(sub.mean()) if sub.size else float("nan"))
        raw[str(b)] = r6(float(sub.mean())) if sub.size else None
    valid = [(b, m) for b, m in enumerate(means) if math.isfinite(m)]
    rho = None
    if len(valid) >= 3:
        rho = _pearson(
            np.asarray([b for b, _ in valid], dtype=float),
            np.asarray([m for _, m in valid], dtype=float),
        )
    diffs = [m for _, m in valid]
    steps = [diffs[i + 1] - diffs[i] for i in range(len(diffs) - 1)]
    if steps and all(s > 0 for s in steps):
        monotonic = "increasing"
    elif steps and all(s < 0 for s in steps):
        monotonic = "decreasing"
    else:
        monotonic = "non_monotonic"
    return {
        "rho": r6(rho),
        "p": _rho_p(rho, len(valid)),
        "bucket_returns": raw,
        "monotonic": monotonic,
        "k": kk,
        "n": n,
    }


def _matrix(value: Any) -> np.ndarray:
    """T×N 矩阵：支持嵌套 list 或 {period: [values]}。"""
    if isinstance(value, Mapping):
        rows = [_seq(value[key]) for key in sorted(value)]
    else:
        rows = []
        for row in value:
            if isinstance(row, Sequence) and not isinstance(row, str):
                rows.append(_seq(row))
            else:
                rows.append([float(row)])
    if not rows:
        raise ValueError("empty matrix")
    width = min(len(r) for r in rows)
    if width < 2:
        raise ValueError("each period needs at least 2 assets")
    return np.asarray([r[:width] for r in rows], dtype=float)


@register(
    **_meta("Q05", input_kind="series"),
    output_schema=("lambda", "t", "se", "n_periods", "n_assets"),
    notes="Fama–MacBeth：逐期横截面 OLS 斜率 → 系数序列均值与 t 值",
)
def q05_fama_macbeth(data: Any, **_: Any) -> Dict[str, Any]:
    if not isinstance(data, Mapping) or "factor" not in data:
        raise ValueError("Fama-MacBeth needs {'factor': T×N, 'target': T×N}")
    ykey = "target" if "target" in data else ("forward" if "forward" in data else None)
    if ykey is None:
        raise ValueError("Fama-MacBeth needs target/forward matrix")
    F = _matrix(data["factor"])
    Y = _matrix(data[ykey])
    T = min(F.shape[0], Y.shape[0])
    N = min(F.shape[1], Y.shape[1])
    lams: List[float] = []
    for t in range(T):
        xs = F[t, :N]
        ys = Y[t, :N]
        if xs.std() <= _EPS:
            continue
        A = np.column_stack([np.ones(N), xs])
        beta, *_ = np.linalg.lstsq(A, ys, rcond=None)
        lams.append(float(beta[1]))
    if len(lams) < 2:
        raise ValueError("Fama-MacBeth needs at least 2 usable periods")
    arr = np.asarray(lams, dtype=float)
    lam = float(arr.mean())
    se = float(arr.std(ddof=1) / math.sqrt(len(arr)))
    return {
        "lambda": r6(lam),
        "t": r6(lam / se) if se > _EPS else None,
        "se": r6(se),
        "n_periods": len(lams),
        "n_assets": N,
    }


@register(
    **_meta("Q06", input_kind="series"),
    output_schema=("t_nw", "se", "lag", "mean", "n"),
    notes="Newey–West t：滞后 L=⌊4(n/100)^{2/9}⌋，Bartlett 核 HAC 方差",
)
def q06_newey_west(data: Any, **_: Any) -> Dict[str, Any]:
    s = _series(data)
    n = len(s)
    if n < 3:
        raise ValueError("Newey-West needs n>=3")
    mu = float(s.mean())
    e = s - mu
    lag = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    lag = max(0, min(lag, n - 1))
    gamma0 = float(e @ e) / n
    lrv = gamma0
    for lag_k in range(1, lag + 1):
        gl = float(e[lag_k:] @ e[:-lag_k]) / n
        lrv += 2.0 * (1.0 - lag_k / (lag + 1.0)) * gl
    se = math.sqrt(max(lrv, 0.0) / n)
    return {
        "t_nw": r6(mu / se) if se > _EPS else None,
        "se": r6(se),
        "lag": lag,
        "mean": r6(mu),
        "n": n,
    }


@register(
    **_meta("Q07", input_kind="series"),
    output_schema=("dsr", "sr", "sr0", "n_trials", "n"),
    notes="Deflated Sharpe：SR0 由多重试验次数 N 的期望极值给出，DSR=Φ(·)",
)
def q07_deflated_sharpe(
    data: Any, n_trials: int = 10, sr_var: float = None, **_: Any
) -> Dict[str, Any]:
    if isinstance(data, Mapping) and "sharpe" in data:
        sr = float(data["sharpe"])
        n = int(data.get("n", 0))
        g3, g4 = 0.0, 3.0
    else:
        r = _series(data)
        n = len(r)
        if n < 3:
            raise ValueError("deflated Sharpe needs n>=3")
        sd = float(r.std(ddof=1))
        if sd <= _EPS:
            raise ValueError("deflated Sharpe needs non-degenerate returns")
        mu = float(r.mean())
        sr = mu / sd
        g3 = float((((r - mu) / sd) ** 3).mean())
        g4 = float((((r - mu) / sd) ** 4).mean())
    N = int(max(1, n_trials))
    var = float(sr_var) if sr_var is not None else (1.0 + 0.5 * sr * sr) / max(n, 1)
    if N <= 1:
        sr0 = 0.0
    else:
        sr0 = math.sqrt(max(var, 0.0)) * (
            (1.0 - _EULER) * norm_ppf(1.0 - 1.0 / N) + _EULER * norm_ppf(1.0 - 1.0 / (N * math.e))
        )
    denom = max(1e-12, 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr * sr)
    z = (sr - sr0) * math.sqrt(max(n - 1, 1)) / math.sqrt(denom)
    return {
        "dsr": r6(norm_cdf(z)),
        "sr": r6(sr),
        "sr0": r6(sr0),
        "n_trials": N,
        "n": n,
    }


@register(
    **_meta("Q08", input_kind="series"),
    output_schema=("ic_first", "ic_second", "delta", "robust", "n"),
    notes="子样本稳健性：前后半段 IC 之差；符号一致即 robust",
)
def q08_subsample(data: Any, **_: Any) -> Dict[str, Any]:
    x, y = _two(data)
    n = len(x)
    h = n // 2
    if h < 3:
        raise ValueError("subsample robustness needs n>=6")
    ic1 = _pearson(x[:h], y[:h])
    ic2 = _pearson(x[h:], y[h:])
    robust = ic1 is not None and ic2 is not None and ic1 * ic2 > 0
    return {
        "ic_first": r6(ic1),
        "ic_second": r6(ic2),
        "delta": r6(ic2 - ic1) if (ic1 is not None and ic2 is not None) else None,
        "robust": bool(robust),
        "n": n,
    }


@register(
    **_meta("Q09", input_kind="series"),
    output_schema=("pass_ratio", "ic_by_window", "windows", "baseline", "n"),
    notes="参数扰动：窗口网格 {10,20,60,120} 的分段 IC 与全样本 IC 同号比例",
)
def q09_param_perturbation(
    data: Any, windows: Sequence[int] = (10, 20, 60, 120), **_: Any
) -> Dict[str, Any]:
    x, y = _two(data)
    n = len(x)
    baseline = _pearson(x, y)
    ws = [int(w) for w in windows]
    ic_by_window: Dict[str, Any] = {}
    agree = total = 0
    for w in ws:
        ww = int(max(5, min(w, n)))
        chunks = [_pearson(x[i : i + ww], y[i : i + ww]) for i in range(0, n - ww + 1, ww)]
        chunks = [c for c in chunks if c is not None]
        if not chunks:
            ic_by_window[str(w)] = None
            continue
        m = float(np.mean(chunks))
        ic_by_window[str(w)] = r6(m)
        if abs(m) > _EPS and baseline is not None and abs(baseline) > _EPS:
            total += 1
            agree += int((m > 0) == (baseline > 0))
    return {
        "pass_ratio": r6(agree / total) if total else 0.0,
        "ic_by_window": ic_by_window,
        "windows": ws,
        "baseline": r6(baseline),
        "n": n,
    }


def _events(data: Any, events: Any) -> List[int]:
    if events is None and isinstance(data, Mapping):
        events = data.get("events")
    if events is None:
        raise ValueError("event study needs an events index list")
    if isinstance(events, (int, float)):
        events = [events]
    return [int(e) for e in events]


def _cars(
    r: np.ndarray, events: Sequence[int], est: Sequence[int], ev: Sequence[int]
) -> Tuple[List[Tuple[float, float, int, int]], List[int]]:
    """逐事件：估计窗 [e+est0, e+est1) 均值调整，事件窗 [e+ev0, e+ev1] 累计异常收益。"""
    e0, e1 = int(est[0]), int(est[1])
    v0, v1 = int(ev[0]), int(ev[1])
    n = len(r)
    out: List[Tuple[float, float, int, int]] = []
    used: List[int] = []
    for e in events:
        a, b = e + e0, e + e1
        c, d = e + v0, e + v1
        if a < 0 or b > n or b - a < 3:
            continue
        if c < 0 or d + 1 > n or d < c:
            continue
        est_r = r[a:b]
        mu = float(est_r.mean())
        sd = float(est_r.std(ddof=1))
        ar = r[c : d + 1] - mu
        out.append((float(ar.sum()), sd, b - a, int(ar.size)))
        used.append(e)
    if not out:
        raise ValueError("no valid event window inside the series")
    return out, used


@register(
    **_meta("Q10", input_kind="series"),
    output_schema=("car", "n", "est_window", "event_window", "per_event", "events"),
    notes="事件窗 CAR：估计窗 [−120,−20] 均值调整，事件窗 [−5,+10]",
)
def q10_event_car(
    data: Any,
    events: Any = None,
    est_window: Sequence[int] = (-120, -20),
    event_window: Sequence[int] = (-5, 10),
    **_: Any,
) -> Dict[str, Any]:
    r = _series(data)
    evs = _events(data, events)
    cars, used = _cars(r, evs, est_window, event_window)
    vals = [c[0] for c in cars]
    return {
        "car": r6(float(np.mean(vals))),
        "n": len(vals),
        "est_window": [int(est_window[0]), int(est_window[1])],
        "event_window": [int(event_window[0]), int(event_window[1])],
        "per_event": [r6(v) for v in vals],
        "events": used,
    }


@register(
    **_meta("Q11", input_kind="series"),
    output_schema=("z_patell", "z_bmp", "p", "n", "est_window", "event_window"),
    notes="Patell：Z=ΣSAR/√(N·Q)，Q=(L1−2)/(L1−4)；BMP：SCAR 横截面标准化",
)
def q11_patell_bmp(
    data: Any,
    events: Any = None,
    est_window: Sequence[int] = (-120, -20),
    event_window: Sequence[int] = (-5, 10),
    **_: Any,
) -> Dict[str, Any]:
    r = _series(data)
    evs = _events(data, events)
    cars, _used = _cars(r, evs, est_window, event_window)
    sars: List[float] = []
    q_adj: List[float] = []
    for car, sd, l1, l2 in cars:
        if sd <= _EPS:
            continue
        sars.append(car / (sd * math.sqrt(l2)))
        q_adj.append((l1 - 2.0) / (l1 - 4.0) if l1 > 4 else 1.0)
    if not sars:
        raise ValueError("no event has a usable estimation-window volatility")
    N = len(sars)
    arr = np.asarray(sars, dtype=float)
    z_patell = float(arr.sum() / math.sqrt(max(float(np.sum(q_adj)), _EPS)))
    sd_sar = float(arr.std(ddof=1)) if N > 1 else 0.0
    z_bmp = float(arr.mean() / sd_sar * math.sqrt(N)) if sd_sar > _EPS else 0.0
    return {
        "z_patell": r6(z_patell),
        "z_bmp": r6(z_bmp),
        "p": r6(min(1.0, 2.0 * (1.0 - norm_cdf(abs(z_patell))))),
        "n": N,
        "est_window": [int(est_window[0]), int(est_window[1])],
        "event_window": [int(event_window[0]), int(event_window[1])],
    }


@register(
    **_meta("Q12", input_kind="series"),
    output_schema=("point", "ci_low", "ci_high", "b", "seed", "level", "n"),
    notes="Bootstrap 百分位区间：默认 B=1000、seed=42（固定，保证可复现）",
)
def q12_bootstrap_ci(
    data: Any, b: int = 1000, seed: int = 42, level: float = 0.95, **_: Any
) -> Dict[str, Any]:
    is_pair = isinstance(data, Mapping) and (
        ("factor" in data and "forward" in data) or ("x" in data and "y" in data)
    )
    if is_pair:
        x, y = _two(data)
        n = len(x)
        point = _pearson(x, y)

        def stat(idx: np.ndarray) -> float:
            v = _pearson(x[idx], y[idx])
            return 0.0 if v is None else v

    else:
        s = _series(data)
        n = len(s)
        point = float(s.mean())

        def stat(idx: np.ndarray) -> float:
            return float(s[idx].mean())

    rng = np.random.default_rng(int(seed))
    reps = int(max(20, b))
    vals = np.asarray([stat(rng.integers(0, n, n)) for _ in range(reps)], dtype=float)
    alpha = (1.0 - min(max(float(level), 0.0), 0.999)) / 2.0
    return {
        "point": r6(point),
        "ci_low": r6(float(np.quantile(vals, alpha))),
        "ci_high": r6(float(np.quantile(vals, 1.0 - alpha))),
        "b": reps,
        "seed": int(seed),
        "level": r4(level),
        "n": n,
    }


@register(
    **_meta("Q13", input_kind="series"),
    output_schema=("p_perm", "observed", "n_perm", "seed", "n"),
    notes="置换检验：打乱 forward 后重算 IC，p=(1+#{|perm|≥|obs|})/(1+N)",
)
def q13_permutation(data: Any, n_perm: int = 1000, seed: int = 42, **_: Any) -> Dict[str, Any]:
    x, y = _two(data)
    observed = _pearson(x, y)
    if observed is None:
        raise ValueError("permutation test needs a non-degenerate factor")
    rng = np.random.default_rng(int(seed))
    reps = int(max(20, n_perm))
    hits = 0
    for _ in range(reps):
        perm = rng.permutation(y)
        stat = _pearson(x, perm)
        if stat is not None and abs(stat) >= abs(observed):
            hits += 1
    return {
        "p_perm": r6((1.0 + hits) / (1.0 + reps)),
        "observed": r6(observed),
        "n_perm": reps,
        "seed": int(seed),
        "n": int(len(x)),
    }


@register(
    **_meta("Q14", input_kind="series"),
    output_schema=("p_adj", "method", "m", "reject", "alpha"),
    notes="多重比较：BH-FDR（默认，q_i ≥ p_i）或 Bonferroni，α 默认 0.05",
)
def q14_multiple_comparison(
    data: Any, method: str = "bh", alpha: float = 0.05, **_: Any
) -> Dict[str, Any]:
    if isinstance(data, Mapping):
        pvals = _seq(data.get("p", data.get("pvalues", [])))
    else:
        pvals = _seq(data)
    if not pvals:
        raise ValueError("multiple comparison needs a p-value list")
    m = len(pvals)
    a = float(alpha)
    name = str(method).lower()
    if name in ("bonferroni", "bonf"):
        adj = [r6(min(1.0, p * m)) for p in pvals]
        name = "bonferroni"
    else:
        order = sorted(range(m), key=lambda i: pvals[i])
        adj = [0.0] * m
        prev = 1.0
        for rank in range(m, 0, -1):
            idx = order[rank - 1]
            val = min(prev, pvals[idx] * m / rank)
            adj[idx] = min(1.0, val)
            prev = adj[idx]
        adj = [r6(v) for v in adj]
        name = "bh"
    return {
        "p_adj": adj,
        "method": name,
        "m": m,
        "reject": [bool(v <= a) for v in adj],
        "alpha": r4(a),
    }


def _count(data: Any) -> int:
    if isinstance(data, Mapping):
        for key in ("series", "values", "x", "factor", "returns", "p"):
            val = data.get(key)
            if isinstance(val, Sequence) and not isinstance(val, str):
                return len(val)
        for key in ("n", "sample_n"):
            val = data.get(key)
            if isinstance(val, (int, float)):
                return int(val)
        return 0
    if isinstance(data, Sequence) and not isinstance(data, str):
        return len(data)
    return 0


@register(
    **_meta("Q15", input_kind="series"),
    output_schema=("sufficient", "ok", "reason", "n", "required", "frequency"),
    notes="样本充分性：日频 n≥250 / 周频 104 / 月频 30；required 参数可覆盖",
)
def q15_sample_sufficiency(
    data: Any, frequency: str = "daily", required: int = None, **_: Any
) -> Dict[str, Any]:
    n = _count(data)
    freq = str(frequency).lower()
    default_req = {"daily": 250, "weekly": 104, "monthly": 30}.get(freq, 250)
    req = int(required) if required is not None else default_req
    ok = n >= req
    cmp = "≥" if ok else "<"
    return {
        "sufficient": bool(ok),
        "ok": bool(ok),
        "reason": f"n={n} {cmp} required={req}（{freq}）",
        "n": n,
        "required": req,
        "frequency": freq,
    }


def _cmp_key(value: Any) -> Tuple[int, Any]:
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


@register(
    **_meta("Q16", input_kind="series"),
    output_schema=("pass", "n_violations", "n", "violations"),
    notes="PIT 校验：数据可用时间必须 ≤ 信号时间，违反项逐条列出索引",
)
def q16_pit(data: Any, **_: Any) -> Dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ValueError("PIT check needs {'available': [...], 'signal': [...]}")
    avail = data.get("available", data.get("available_at"))
    sig = data.get("signal", data.get("signal_time", data.get("signal_at")))
    if avail is None or sig is None:
        raise ValueError("PIT check needs available and signal time lists")
    n = min(len(avail), len(sig))
    if n < 1:
        raise ValueError("PIT check needs at least 1 aligned timestamp")
    ka = [_cmp_key(avail[i]) for i in range(n)]
    ks = [_cmp_key(sig[i]) for i in range(n)]
    violations = [i for i in range(n) if ka[i] > ks[i]]
    return {
        "pass": not violations,
        "n_violations": len(violations),
        "n": n,
        "violations": violations,
    }
