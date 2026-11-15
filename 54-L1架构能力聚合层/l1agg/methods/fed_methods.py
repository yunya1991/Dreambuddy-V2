# -*- coding: utf-8 -*-
"""美联储调研方法落地（SPEC-54 §4.12 / §4.14）：I35–I39 + 四个工具函数。

边界（与全仓一致）：
  - 纯确定性计算，**禁止 LLM / 随机 / 采样**（ADR-V15）；同输入同参数字节一致；
  - 方法层唯一 SSoT：能力层只调用 `registry.run`，不得重算口径；
  - 未达 `min_n` 一律由 `run()` 返回 `gate=insufficient_samples`，不静默降级。

登记清单（SPEC §4.14）：
  I35 协整（Engle-Granger）→ `equilibrium_gap` 轴，min_n=500
  I36 分位回归（Growth-at-Risk）→ 前瞻分布 q10/q50/q90，min_n=500
  I37 Kalman / DFM 局部线性趋势 → level + slope + ±1σ，min_n=250
  I38 DMA / 区制权重（遗忘因子）→ 状态依赖权重，min_n=750
  I39 带通滤波 / STL 式周期分解 → 30–90 日周期成分，min_n=750

工具函数（§4.12 第 2/4/6/8 条）：
  `midas_weights` 混合频率 Beta 多项式权重（Ghysels, 2004）
  `fci_composite` 金融状况指数（Ledoit-Wolf 收缩 + 风险平价）
  `uncertainty_index` 不确定性指数（Jurado-Ludvigson-Ng 式残差波动）
  `taylor_gap` 泰勒规则式显式系数 gap 标准化（可审计）
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .registry import register

_EPS = 1e-12


def _f(value: Any, digits: int = 10) -> Any:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _lst(values: Any, digits: int = 10) -> List[Any]:
    return [_f(v, digits) for v in np.asarray(values, dtype=float).ravel()]


def _series(data: Any, key: Optional[str] = None) -> List[float]:
    """取一维序列：`data` 可为 list，或 dict 里的 `key`（默认自动挑一个）。"""
    if key is not None:
        values = data.get(key) if isinstance(data, Mapping) else None
        if values is None or isinstance(values, str):
            raise ValueError(f"missing '{key}' series")
        return [float(v) for v in values]
    if isinstance(data, Mapping):
        for name in ("series", "values", "close", "price", "x"):
            values = data.get(name)
            if isinstance(values, Sequence) and not isinstance(values, str):
                return [float(v) for v in values]
        seqs = [v for v in data.values() if isinstance(v, Sequence) and not isinstance(v, str)]
        if len(seqs) != 1:
            raise ValueError("ambiguous series")
        return [float(v) for v in seqs[0]]
    if isinstance(data, Sequence) and not isinstance(data, str):
        return [float(v) for v in data]
    raise ValueError("unsupported series payload")


def _pair(data: Mapping[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    x = np.asarray([float(v) for v in data.get("x") or []], dtype=float)
    y = np.asarray([float(v) for v in data.get("y") or []], dtype=float)
    n = min(len(x), len(y))
    if n == 0:
        raise ValueError("empty x/y")
    return x[-n:], y[-n:]


def _ols(y: np.ndarray, x: np.ndarray) -> Tuple[float, float]:
    """一元 OLS：返回 (intercept, slope)；x 无方差直接抛错。"""
    xm, ym = float(x.mean()), float(y.mean())
    sxx = float(((x - xm) ** 2).sum())
    if sxx <= _EPS * max(1.0, float((x**2).sum())):
        raise ValueError("regressor is constant")
    slope = float(((x - xm) * (y - ym)).sum()) / sxx
    return ym - slope * xm, slope


# ============================================================
# 工具：混合频率（MIDAS）
# ============================================================


def midas_weights(
    windows: Sequence[int], *, theta1: float = 1.0, theta2: float = 3.0
) -> Dict[str, Any]:
    """MIDAS Beta 多项式权重（Ghysels et al., 2004）：按频率给权重，不强行重采样。

    权重取自 Beta(θ1, θ2) 在 `k` 个等距滞后格点上的密度（格点中点），归一为 1；
    θ1=1, θ2=3 时高频（短窗口）权重更大，符合「高频信息先到」的直觉。
    """
    ws = [int(w) for w in windows]
    if not ws or any(w <= 0 for w in ws):
        raise ValueError("windows must be positive")
    if theta1 <= 0 or theta2 <= 0:
        raise ValueError("theta must be positive")
    k = len(ws)
    raw: List[float] = []
    for i in range(k):
        u = (i + 0.5) / k
        raw.append((u ** (theta1 - 1.0)) * ((1.0 - u) ** (theta2 - 1.0)))
    total = sum(raw)
    if total <= 0:
        raw = [1.0] * k
        total = float(k)
    weights = [r / total for r in raw]
    return {
        "windows": ws,
        "theta": [_f(theta1, 6), _f(theta2, 6)],
        "weights": [_f(w) for w in weights],
        "sum": _f(sum(weights)),
    }


# ============================================================
# 工具：金融状况指数（Ledoit-Wolf 收缩 + 风险平价）
# ============================================================


def _lw_shrinkage(returns: np.ndarray) -> Tuple[np.ndarray, float]:
    """Ledoit-Wolf 常相关目标收缩：返回 (收缩后协方差, 收缩强度 δ)。"""
    t, k = returns.shape
    sample = np.cov(returns, rowvar=False, ddof=1)
    sample = np.atleast_2d(sample)
    var = np.diag(sample).copy()
    sd = np.sqrt(np.maximum(var, _EPS))
    corr = sample / np.outer(sd, sd)
    off = ~np.eye(k, dtype=bool)
    rbar = float(corr[off].sum() / (k * (k - 1))) if k > 1 else 0.0
    target = rbar * np.outer(sd, sd)
    np.fill_diagonal(target, var)
    centred = returns - returns.mean(axis=0)
    pi_mat = np.zeros((k, k))
    for i in range(k):
        for j in range(k):
            pi_mat[i, j] = float(((centred[:, i] * centred[:, j]) ** 2).sum()) / t
    gamma = float(((sample - target) ** 2).sum())
    delta = float(pi_mat.sum()) / gamma if gamma > _EPS else 0.0
    delta = min(1.0, max(0.0, delta))
    return (1.0 - delta) * sample + delta * target, delta


def _risk_parity(cov: np.ndarray, *, iterations: int = 300) -> np.ndarray:
    """风险平价权重：逆边际风险固定点迭代（确定性，阻尼 0.5）。"""
    k = cov.shape[0]
    weights = np.full(k, 1.0 / k)
    for _ in range(int(iterations)):
        marginal = cov @ weights
        marginal = np.where(np.abs(marginal) > _EPS, marginal, _EPS)
        target = 1.0 / marginal
        target = target / target.sum()
        weights = 0.5 * weights + 0.5 * target
        weights = weights / weights.sum()
    return weights


def fci_composite(
    series: Mapping[str, Sequence[float]],
    *,
    signs: Optional[Mapping[str, float]] = None,
    window: int = 250,
) -> Dict[str, Any]:
    """FCI 合成（§4.12 第 6 条）：Ledoit-Wolf 收缩 + 风险平价 → 单一可读指数。

    每个分量先做 z-score（点对点、只用传入样本），方向由 `signs` 显式声明
    （缺省 +1，可审计）；指数 = Σ signᵢ·wᵢ·zᵢ，只保留末 `window` 个点。
    """
    names = sorted(series)
    if not names:
        raise ValueError("empty series")
    columns = {name: [float(v) for v in series[name]] for name in names}
    n = min(len(v) for v in columns.values())
    if n < 3:
        raise ValueError("fci needs n>=3")
    matrix = np.column_stack([columns[name][-n:] for name in names])
    z = np.zeros_like(matrix)
    for j in range(matrix.shape[1]):
        col = matrix[:, j]
        sd = float(col.std(ddof=0))
        z[:, j] = (col - float(col.mean())) / (sd if sd > _EPS else 1.0)
    rets = np.diff(z, axis=0)
    cov, delta = _lw_shrinkage(rets) if z.shape[1] > 1 else (np.array([[1.0]]), 0.0)
    weights = _risk_parity(cov)
    sign_vec = np.array([float((signs or {}).get(name, 1.0)) for name in names], dtype=float)
    index = (z * weights * sign_vec).sum(axis=1)
    tail = min(len(index), int(window))
    return {
        "components": names,
        "weights": _lst(weights, 6),
        "signs": _lst(sign_vec, 6),
        "shrinkage": _f(delta, 6),
        "index": _lst(index[-tail:], 6),
        "level": _f(index[-1], 6),
        "n": int(n),
    }


# ============================================================
# 工具：不确定性指数（Jurado-Ludvigson-Ng 式）
# ============================================================


def uncertainty_index(series: Sequence[float], *, window: int = 60) -> Dict[str, Any]:
    """不确定性指数：AR(1) 预测残差的滚动波动 → 历史百分位 ∈[0,1]。

    高不确定 → 权重向 `prior` 收缩，收缩系数 `λ_u = min(0.5, index·0.5)`
    （SPEC §4.13：`λ_u ∈ [0, 0.5]`）。
    """
    values = np.asarray([float(v) for v in series], dtype=float)
    if len(values) < 5:
        raise ValueError("uncertainty needs n>=5")
    lag, cur = values[:-1], values[1:]
    intercept, slope = _ols(cur, lag)
    resid = cur - (intercept + slope * lag)
    vol: List[float] = []
    w = max(2, int(window))
    for i in range(w - 1, len(resid)):
        seg = resid[i - w + 1 : i + 1]
        vol.append(float(seg.std(ddof=1)))
    if not vol:
        raise ValueError("insufficient residual history")
    current = vol[-1]
    pct = sum(1 for v in vol if v <= current) / len(vol)
    index = max(0.0, min(1.0, pct))
    return {
        "index": _f(index, 6),
        "lambda_u": _f(min(0.5, index * 0.5), 6),
        "vol": _f(current),
        "ar1_slope": _f(slope, 6),
        "n": int(len(values)),
    }


# ============================================================
# 工具：泰勒规则式 gap 标准化（显式系数、可审计）
# ============================================================


def taylor_gap(
    value: float,
    *,
    neutral: float = 0.0,
    scale: float = 1.0,
    coefficient: float = 1.0,
    clip: float = 3.0,
) -> Dict[str, Any]:
    """`gap = coefficient·(value − neutral) / scale`，截断 ±clip（默认 ±3σ）。

    系数全部显式传入并回传，便于审计（§4.12 第 4 条）。
    """
    if scale == 0:
        raise ValueError("scale must be non-zero")
    gap = float(coefficient) * (float(value) - float(neutral)) / float(scale)
    gap = max(-float(clip), min(float(clip), gap))
    return {
        "gap": _f(gap),
        "coefficient": _f(coefficient, 6),
        "neutral": _f(neutral, 6),
        "scale": _f(scale, 6),
        "clip": _f(clip, 6),
    }


# ============================================================
# I35 协整（Engle-Granger）→ equilibrium_gap
# ============================================================


@register(
    "I35",
    name="协整 / 误差修正（Engle-Granger）",
    group="I",
    layer="D2",
    input_kind="pairs",
    min_n=500,
    output_schema=(
        "beta",
        "alpha",
        "gap",
        "gap_z",
        "half_life",
        "adf_stat",
        "adf_p",
        "cointegrated",
        "n",
    ),
    notes="两步法：y=a+b·x OLS → 残差 ADF（常数项、1 阶增广）；gap=末残差，gap_z 用残差标准差标准化",
)
def i35_cointegration(data: Mapping[str, Any], **_kwargs: Any) -> Dict[str, Any]:
    from statsmodels.tsa.stattools import adfuller

    x, y = _pair(data)
    n = len(y)
    alpha, beta = _ols(y, x)
    resid = y - (alpha + beta * x)
    adf = adfuller(resid, maxlag=1, autolag=None, regression="c", result_object=False)
    stat, p_value = float(adf[0]), float(adf[1])
    sd = float(resid.std(ddof=1)) if n > 2 else 0.0
    gap = float(resid[-1])
    gap_z = gap / sd if sd > _EPS else 0.0
    rho, _ = _ols(resid[1:], resid[:-1])
    half_life = None
    if -1.0 < rho < 0.0:
        half_life = -math.log(2.0) / math.log(1.0 + rho)
    return {
        "beta": _f(beta),
        "alpha": _f(alpha),
        "gap": _f(gap),
        "gap_z": _f(gap_z),
        "half_life": _f(half_life, 4),
        "adf_stat": _f(stat, 6),
        "adf_p": _f(float(p_value), 6),
        "cointegrated": bool(float(p_value) < 0.05),
        "n": int(n),
    }


# ============================================================
# I36 分位回归（Growth-at-Risk）
# ============================================================


@register(
    "I36",
    name="分位回归（Growth-at-Risk）",
    group="I",
    layer="D2",
    input_kind="pairs",
    min_n=500,
    output_schema=("q10", "q50", "q90", "dispersion", "slopes", "n"),
    notes="τ=0.1/0.5/0.9 的分位回归（statsmodels QuantReg），预测值取末样本；dispersion=q90−q10 作为 strength 依据",
)
def i36_quantile_regression(
    data: Mapping[str, Any], taus: Sequence[float] = (0.1, 0.5, 0.9), **_: Any
) -> Dict[str, Any]:
    import statsmodels.api as sm

    x, y = _pair(data)
    design = sm.add_constant(x, has_constant="add")
    preds: Dict[str, float] = {}
    slopes: Dict[str, float] = {}
    last = np.array([1.0, float(x[-1])])
    for tau in taus:
        fit = sm.QuantReg(y, design).fit(q=float(tau), max_iter=1000)
        params = np.asarray(fit.params, dtype=float)
        preds[str(_f(tau, 2))] = float(params @ last)
        slopes[str(_f(tau, 2))] = float(params[1])
    return {
        "q10": _f(preds.get("0.1")),
        "q50": _f(preds.get("0.5")),
        "q90": _f(preds.get("0.9")),
        "dispersion": _f((preds.get("0.9") or 0.0) - (preds.get("0.1") or 0.0)),
        "slopes": {k: _f(v, 8) for k, v in slopes.items()},
        "n": int(len(y)),
    }


# ============================================================
# I37 Kalman / DFM 局部线性趋势
# ============================================================


def kalman_local_linear(
    values: Sequence[float],
    *,
    q_level: float = 1e-2,
    q_slope: float = 1e-5,
    r: float = 1.0,
) -> Dict[str, Any]:
    """局部线性趋势状态空间滤波（level + slope），返回末值与全程路径。

    先对原序列做 z-score 再滤波（尺度无关、无需调参），最后按原尺度还原；
    方差全部给定为常数，**不做 MLE**，保证同输入字节一致。
    """
    arr = np.asarray([float(v) for v in values], dtype=float)
    n = len(arr)
    if n < 3:
        raise ValueError("kalman needs n>=3")
    mu = float(arr.mean())
    sd = float(arr.std(ddof=0)) or 1.0
    z = (arr - mu) / sd
    state = np.array([float(z[0]), 0.0])
    cov = np.diag([1.0, 1e-3])
    transition = np.array([[1.0, 1.0], [0.0, 1.0]])
    obs = np.array([1.0, 0.0])
    noise = np.diag([float(q_level), float(q_slope)])
    levels: List[float] = []
    slopes: List[float] = []
    level_sigma: List[float] = []
    slope_sigma: List[float] = []
    for t in range(n):
        if t > 0:
            state = transition @ state
            cov = transition @ cov @ transition.T + noise
        innovation = float(z[t]) - float(obs @ state)
        var_obs = float(obs @ cov @ obs) + float(r)
        gain = (cov @ obs) / var_obs
        state = state + gain * innovation
        cov = cov - np.outer(gain, obs @ cov)
        cov = (cov + cov.T) / 2.0
        levels.append(float(state[0]))
        slopes.append(float(state[1]))
        level_sigma.append(math.sqrt(max(float(cov[0, 0]), _EPS)))
        slope_sigma.append(math.sqrt(max(float(cov[1, 1]), 1e-18)))
    tail = min(n, 500)
    start = n - tail
    path = [
        {
            "index": int(start + i),
            "level": _f(mu + sd * levels[start + i], 6),
            "lower": _f(mu + sd * (levels[start + i] - level_sigma[start + i]), 6),
            "upper": _f(mu + sd * (levels[start + i] + level_sigma[start + i]), 6),
        }
        for i in range(tail)
    ]
    return {
        "level": _f(mu + sd * levels[-1]),
        "slope": _f(sd * slopes[-1]),
        "level_sigma": _f(sd * level_sigma[-1]),
        "slope_se": _f(sd * slope_sigma[-1]),
        "band": [
            _f(mu + sd * (levels[-1] - level_sigma[-1])),
            _f(mu + sd * (levels[-1] + level_sigma[-1])),
        ],
        "path": path,
        "n": int(n),
    }


@register(
    "I37",
    name="Kalman / DFM 平滑（局部线性趋势）",
    group="I",
    layer="D2",
    input_kind="series",
    min_n=250,
    output_schema=("level", "slope", "level_sigma", "slope_se", "band", "path", "n"),
    notes="level+slope 状态空间，q_level=1e-2 / q_slope=1e-5 / r=1.0（z-score 后），附 ±1σ 置信带",
)
def i37_kalman(data: Any, **_: Any) -> Dict[str, Any]:
    values = (
        _series(data, "values") if isinstance(data, Mapping) and "values" in data else _series(data)
    )
    return kalman_local_linear(values)


# ============================================================
# I38 DMA / 区制权重（遗忘因子，Koop & Korobilis）
# ============================================================


@register(
    "I38",
    name="DMA / 区制权重（遗忘因子）",
    group="I",
    layer="D2",
    input_kind="panel",
    min_n=750,
    output_schema=("weights", "best", "switched", "entropy", "effective_n", "lambda", "n"),
    notes="预测似然加权 + 遗忘因子 λ=0.99（Raftery & Karny 式），series 内除 actual 外均为模型预测",
)
def i38_dma(data: Mapping[str, Any], *, lam: float = 0.99, **_: Any) -> Dict[str, Any]:
    series = data.get("series") if isinstance(data, Mapping) else None
    if not isinstance(series, Mapping) or "actual" not in series:
        raise ValueError("dma expects {'series': {'actual': [...], 'model_1': [...]}}")
    if not 0.0 < float(lam) <= 1.0:
        raise ValueError("lambda must be in (0,1]")
    names = [k for k in sorted(series) if k != "actual"]
    if not names:
        raise ValueError("dma needs at least one model")
    actual = np.asarray([float(v) for v in series["actual"]], dtype=float)
    models = {k: np.asarray([float(v) for v in series[k]], dtype=float) for k in names}
    n = min([len(actual)] + [len(v) for v in models.values()])
    actual = actual[-n:]
    for key in models:
        models[key] = models[key][-n:]
    k = len(names)
    probs = np.full(k, 1.0 / k)
    mse = np.full(k, 1e-6)
    history: List[Dict[str, Any]] = []
    prev_best = names[int(np.argmax(probs))]
    switched = False
    for t in range(n):
        err = np.array([actual[t] - models[name][t] for name in names], dtype=float)
        mse = float(lam) * mse + (1.0 - float(lam)) * err**2
        sigma = np.maximum(np.sqrt(mse), 1e-8)
        loglik = -0.5 * ((err / sigma) ** 2 + np.log(2.0 * math.pi * sigma**2))
        weights = (probs ** float(lam)) * np.exp(loglik - loglik.max())
        total = float(weights.sum())
        probs = weights / total if total > _EPS else np.full(k, 1.0 / k)
        best = names[int(np.argmax(probs))]
        if best != prev_best:
            switched = True
            prev_best = best
        if t >= n - 100:
            history.append(
                {
                    "index": int(t),
                    "weights": {name: _f(probs[i], 6) for i, name in enumerate(names)},
                    "best": best,
                }
            )
    entropy = float(-(probs * np.log(np.maximum(probs, _EPS))).sum())
    return {
        "models": names,
        "weights": {name: _f(probs[i], 6) for i, name in enumerate(names)},
        "best": names[int(np.argmax(probs))],
        "switched": bool(switched),
        "entropy": _f(entropy, 6),
        "effective_n": _f(math.exp(entropy), 4),
        "lambda": _f(lam, 4),
        "history": history,
        "n": int(n),
    }


# ============================================================
# I39 带通滤波 / STL 式周期分解（30–90 日）
# ============================================================


@register(
    "I39",
    name="带通滤波 / 周期分解（30–90 日）",
    group="I",
    layer="D2",
    input_kind="series",
    min_n=750,
    output_schema=("period_days", "amplitude", "phase_deg", "cycle_slope", "cycle", "n"),
    notes="因果 MA 差带通（MA(short)−MA(long)）保留 30–90 日成分；周期用 rFFT 峰值，相位用末窗 sin/cos 投影",
)
def i39_bandpass(
    data: Any, *, short: int = 30, long: int = 90, lookback: int = 750, **_: Any
) -> Dict[str, Any]:
    values = _series(data)
    n = len(values)
    if short < 2 or long <= short:
        raise ValueError("require 2 <= short < long")
    if n < long + 1:
        raise ValueError("bandpass needs n>long")
    logs = np.log(np.maximum(np.asarray(values, dtype=float), _EPS))
    ma_short = _trailing_mean(logs, short)
    ma_long = _trailing_mean(logs, long)
    cycle = ma_short - ma_long
    cycle = cycle[~np.isnan(cycle)]
    tail = min(len(cycle), int(lookback))
    segment = cycle[-tail:]
    spectrum = np.abs(np.fft.rfft(segment - segment.mean()))
    freqs = np.fft.rfftfreq(len(segment), d=1.0)
    period_days = None
    amp = float(segment.std(ddof=1)) if len(segment) > 2 else 0.0
    if spectrum.size > 2:
        band = (freqs > 0) & (freqs >= 1.0 / float(long)) & (freqs <= 1.0 / float(short))
        idx = int(np.argmax(np.where(band, spectrum, -np.inf)))
        if spectrum[idx] > 0 and freqs[idx] > 0:
            period_days = 1.0 / float(freqs[idx])
    phase_deg = None
    if period_days:
        window = max(4, int(round(period_days)))
        seg = segment[-window:]
        grid = np.arange(len(seg), dtype=float)
        re = float((seg * np.cos(2 * np.pi * grid / period_days)).sum())
        im = float((seg * np.sin(2 * np.pi * grid / period_days)).sum())
        phase_deg = math.degrees(math.atan2(im, re))
    span = min(30, len(segment))
    cycle_slope = None
    if span >= 3:
        idx = np.arange(span, dtype=float)
        y = segment[-span:]
        cycle_slope = float(np.polyfit(idx, y, 1)[0])
    return {
        "period_days": _f(period_days, 2),
        "amplitude": _f(amp),
        "phase_deg": _f(phase_deg, 2),
        "cycle_slope": _f(cycle_slope),
        "cycle": [
            {"index": int(len(cycle) - tail + i), "value": _f(v, 6)} for i, v in enumerate(segment)
        ],
        "n": int(n),
    }


def _trailing_mean(values: np.ndarray, window: int) -> np.ndarray:
    """因果滚动均值，首个完整窗口前填 NaN；返回与输入等长的数组（去 NaN 后对齐尾部）。"""
    n = len(values)
    out = np.full(n, np.nan)
    if window > n:
        return out
    cumsum = np.cumsum(np.insert(values, 0, 0.0))
    out[window - 1 :] = (cumsum[window:] - cumsum[:-window]) / window
    return out


__all__ = [
    "fci_composite",
    "i35_cointegration",
    "i36_quantile_regression",
    "i37_kalman",
    "i38_dma",
    "i39_bandpass",
    "kalman_local_linear",
    "midas_weights",
    "taylor_gap",
    "uncertainty_index",
]
