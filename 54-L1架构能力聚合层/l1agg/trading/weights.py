# -*- coding: utf-8 -*-
"""L1-D 动态轴权重（SPEC-54 §4.13 / ADR-V18/V19 / L1D-08，P2，**默认关闭**）。

四源合成（与 SPEC §4.13 逐字对应）：

    w*_i ∝ prior_i × (|IC_i| + ε)^κ / (σ_i + ε)      # 经济先验 × 近期有效性
    w*   ← simplex 投影 → clip [0.05, 0.40] → 再归一
    w_t  = (1−α)·w_{t−1} + α·w*                       # 部分调整，α = 0.1
    L1(w_t, w_{t−1}) ≤ 0.15                           # 单次换手上限

硬约束：
  - 权重只由 `observed_at ≤ as_of` 的历史与**已实现标签**决定，周度再平衡
    （`W-MON`）；再平衡之间完全冻结，纸面回放期间权重锁定为初始版本；
  - **禁止 LLM / 随机**；`weights_hash` 同 hash 必须复现同权重；
  - **等权否决权**：250 日滚动超额 >0 且单边 p<0.05 才启用，否则退回等权并置
    `weight_fallback=true`（预测组合之谜，Bates & Granger 1969 / Smith & Wallis 2009）；
  - 不确定性高时向 `prior` 收缩，`λ_u ∈ [0, 0.5]`（Jurado-Ludvigson-Ng 2015）。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

AXES = ("trend", "adx", "inertia", "coherence")
STATIC_WEIGHTS: Dict[str, float] = {
    "trend": 0.40,
    "adx": 0.25,
    "inertia": 0.20,
    "coherence": 0.15,
}
# 经济先验（美联储口径：先验不可被短期 IC 完全推翻，只做有限调整）
PRIOR_WEIGHTS: Dict[str, float] = dict(STATIC_WEIGHTS)
EQUAL_WEIGHTS: Dict[str, float] = dict.fromkeys(AXES, 0.25)

MIN_WEIGHT = 0.05
MAX_WEIGHT = 0.40
MAX_TURNOVER = 0.15
WINDOW = 250
MIN_OBS = 250
MIN_WINDOW = 500
ALPHA = 0.05
ALPHA_ADJUST = 0.1
KAPPA = 1.0
EPS = 1e-6
REBALANCE = "W-MON"
UNCERTAINTY_MAX = 0.5
WEIGHTS_VERSION = "weights-1.1.0"


# ---------------- 基础工具 ----------------


def weights_hash(weights: Mapping[str, float]) -> str:
    """权重指纹：`signal.weights_hash`；同 hash 必须复现同权重。"""
    material = {axis: round(float(weights.get(axis, 0.0)), 6) for axis in AXES}
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def is_rebalance_day(as_of: Optional[str]) -> bool:
    """周度再平衡判定：周一为再平衡日（`rebalance="W-MON"`）。"""
    if not as_of:
        return True
    try:
        day = _dt.date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return True
    return day.weekday() == 0


def week_key(as_of: Optional[str]) -> Optional[str]:
    """ISO 年-周键：同一周内权重必须完全冻结。"""
    if not as_of:
        return None
    try:
        day = _dt.date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return None
    iso = day.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _align(
    axis_values: Mapping[str, Sequence[float]], forward_returns: Sequence[float], window: int
) -> Dict[str, list]:
    fwd = [float(v) for v in forward_returns]
    axes = {axis: [float(v) for v in axis_values.get(axis, [])] for axis in AXES}
    lengths = [len(fwd)] + [len(v) for v in axes.values() if v]
    size = min(lengths)
    if size <= 0:
        return {axis: [] for axis in AXES} | {"fwd": []}
    start = max(0, size - int(window))
    return {axis: axes[axis][start:size] for axis in AXES} | {"fwd": fwd[start:size]}


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: Sequence[float], ddof: int = 1) -> float:
    n = len(values)
    if n <= ddof:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - ddof))


def axis_scores(
    axis_values: Mapping[str, Sequence[float]],
    forward_returns: Sequence[float],
    *,
    window: int = WINDOW,
) -> Dict[str, float]:
    """各轴与前瞻收益的协动强度 `mean(axis × fwd_ret)`（末 `window` 个样本）。"""
    data = _align(axis_values, forward_returns, window)
    fwd = data.pop("fwd")
    if not fwd:
        return dict.fromkeys(AXES, 0.0)
    scores: Dict[str, float] = {}
    for axis in AXES:
        values = data.get(axis) or []
        if len(values) != len(fwd):
            values = [0.0] * len(fwd)
        scores[axis] = round(sum(v * r for v, r in zip(values, fwd, strict=False)) / len(fwd), 10)
    return scores


def _corr(x: Sequence[float], y: Sequence[float]) -> float:
    n = min(len(x), len(y))
    if n < 3:
        return 0.0
    sx, sy = _std(x[:n]), _std(y[:n])
    if sx <= EPS or sy <= EPS:
        return 0.0
    mx, my = _mean(x[:n]), _mean(y[:n])
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n)) / (n - 1)
    return max(-1.0, min(1.0, cov / (sx * sy)))


def axis_reliability(
    axis_values: Mapping[str, Sequence[float]],
    forward_returns: Sequence[float],
    *,
    window: int = WINDOW,
) -> Dict[str, Dict[str, float]]:
    """`reliability = |IC| / σ_forecast`（σ 用残差近似 `σ_y·sqrt(1−IC²)`）。"""
    data = _align(axis_values, forward_returns, window)
    fwd = data.pop("fwd")
    out: Dict[str, Dict[str, float]] = {}
    sy = _std(fwd) if fwd else 0.0
    for axis in AXES:
        values = data.get(axis) or []
        ic = _corr(values, fwd) if values else 0.0
        sigma = sy * math.sqrt(max(0.0, 1.0 - ic * ic))
        out[axis] = {
            "ic": round(ic, 10),
            "sigma": round(sigma, 10),
            "reliability": round(abs(ic) / (sigma + EPS), 10),
        }
    return out


# ---------------- 合成算子 ----------------


def _simplex(raw: Mapping[str, float]) -> Dict[str, float]:
    shifted = {axis: max(0.0, float(raw.get(axis, 0.0))) for axis in AXES}
    total = sum(shifted.values())
    if total <= 0:
        return dict(EQUAL_WEIGHTS)
    return {axis: value / total for axis, value in shifted.items()}


def _clip_normalize(
    raw: Mapping[str, float], *, min_weight: float, max_weight: float
) -> Dict[str, float]:
    weights = _simplex(raw)
    for _ in range(20):
        weights = {
            axis: min(max_weight, max(min_weight, weight)) for axis, weight in weights.items()
        }
        gap = 1.0 - sum(weights.values())
        if abs(gap) <= 1e-12:
            break
        adjustable = [
            axis
            for axis in AXES
            if (gap > 0 and weights[axis] < max_weight - 1e-12)
            or (gap < 0 and weights[axis] > min_weight + 1e-12)
        ]
        if not adjustable:
            break
        share = gap / len(adjustable)
        weights = {
            axis: weight + share if axis in adjustable else weight
            for axis, weight in weights.items()
        }
    weights = {axis: min(max_weight, max(min_weight, weight)) for axis, weight in weights.items()}
    total = sum(weights.values())
    return {axis: round(weight / total, 6) for axis, weight in weights.items()}


def _shrink_to_prior(
    weights: Mapping[str, float], prior: Mapping[str, float], lam: float
) -> Dict[str, float]:
    """不确定性收缩：`w ← (1−λ_u)·w + λ_u·prior`（λ_u 截断 [0, 0.5]）。"""
    lam = max(0.0, min(UNCERTAINTY_MAX, float(lam)))
    return {
        axis: (1.0 - lam) * float(weights.get(axis, 0.0)) + lam * float(prior.get(axis, 0.0))
        for axis in AXES
    }


def _partial_adjust(
    target: Mapping[str, float], previous: Mapping[str, float], alpha: float
) -> Dict[str, float]:
    """部分调整：`w_t = (1−α)·w_{t−1} + α·w*`（α=0.1，防止单次跳变）。"""
    a = max(0.0, min(1.0, float(alpha)))
    return {
        axis: (1.0 - a) * float(previous.get(axis, 0.0)) + a * float(target.get(axis, 0.0))
        for axis in AXES
    }


def _limit_turnover(
    target: Mapping[str, float],
    previous: Mapping[str, float],
    *,
    max_turnover: float,
) -> Dict[str, float]:
    prev = {axis: float(previous.get(axis, 0.0)) for axis in AXES}
    weights = {axis: float(target.get(axis, 0.0)) for axis in AXES}
    for _ in range(6):
        turnover = 0.5 * sum(abs(weights[a] - prev[a]) for a in AXES)
        if turnover <= max_turnover + 1e-12:
            break
        factor = max_turnover / turnover
        weights = {a: prev[a] + (weights[a] - prev[a]) * factor for a in AXES}
        total = sum(weights.values())
        weights = {a: round(w / total, 6) for a, w in weights.items()}
    return weights


def oos_gate(
    excess: Optional[Sequence[float]], *, min_obs: int = MIN_OBS, alpha: float = ALPHA
) -> Dict[str, Any]:
    """样本外滚动超额（相对等权）的单边检验；`excess` 不足或未显著 → `passed=False`。"""
    xs = [float(v) for v in (excess or []) if v is not None]
    count = len(xs)
    out: Dict[str, Any] = {"n": count, "excess_mean": None, "t": None, "p_value": None}
    if count < max(3, int(min_obs)):
        return {**out, "passed": False, "reason": "insufficient_oos"}
    mean = sum(xs) / count
    var = sum((x - mean) ** 2 for x in xs) / (count - 1)
    sd = math.sqrt(var)
    if sd == 0:
        t = math.inf if mean > 0 else 0.0
        p = 0.0 if mean > 0 else 0.5
    else:
        t = mean / (sd / math.sqrt(count))
        p = 0.5 * math.erfc(t / math.sqrt(2.0))
    passed = mean > 0 and p < alpha
    return {
        "n": count,
        "excess_mean": round(mean, 10),
        "t": round(t, 6) if math.isfinite(t) else None,
        "p_value": round(p, 10),
        "passed": passed,
        "reason": None if passed else ("excess_not_positive" if mean <= 0 else "not_significant"),
    }


def _turnover(weights: Mapping[str, float], prev: Mapping[str, float]) -> float:
    return 0.5 * sum(abs(float(weights[a]) - float(prev.get(a, 0.0))) for a in AXES)


def dynamic_weights(
    axis_values: Optional[Mapping[str, Sequence[float]]] = None,
    forward_returns: Optional[Sequence[float]] = None,
    *,
    enabled: bool = False,
    oos_excess: Optional[Sequence[float]] = None,
    previous_weights: Optional[Mapping[str, float]] = None,
    window: int = WINDOW,
    min_obs: int = MIN_OBS,
    min_window: int = MIN_WINDOW,
    min_weight: float = MIN_WEIGHT,
    max_weight: float = MAX_WEIGHT,
    max_turnover: float = MAX_TURNOVER,
    alpha: float = ALPHA,
    adjust: float = ALPHA_ADJUST,
    kappa: float = KAPPA,
    as_of: Optional[str] = None,
    last_effective_date: Optional[str] = None,
    replay_locked: bool = False,
    uncertainty: Optional[float] = None,
    prior: Optional[Mapping[str, float]] = None,
    gap_weight: float = 0.0,
) -> Dict[str, Any]:
    """四源合成权重；返回 `{weights, axis_weights, weights_hash, weight_sources, ...}`。

    - `enabled=False`（默认）→ 静态先验权重，行为与引入动态权重前完全一致；
    - `replay_locked=True` → 纸面回放期锁定权重，绝不边跑边调；
    - 同一 ISO 周内（`as_of` 与 `last_effective_date` 同周）→ 完全冻结；
    - 其他情况：等权否决门禁 → IC/σ 合成 → 收缩 → 裁剪 → 部分调整 → 换手限速。
    """
    prior_map = {axis: float((prior or PRIOR_WEIGHTS).get(axis, 0.0)) for axis in AXES}
    prev = {axis: float((previous_weights or STATIC_WEIGHTS).get(axis, 0.0)) for axis in AXES}
    result: Dict[str, Any] = {
        "weights_version": WEIGHTS_VERSION,
        "enabled": bool(enabled),
        "axes": list(AXES),
        "rebalance": REBALANCE,
        "weight_fallback": False,
        "frozen": False,
        "gate": None,
        "flags": [],
    }
    if not enabled:
        weights = dict(STATIC_WEIGHTS)
        result["flags"].append("dynamic_disabled")
    elif replay_locked:
        weights = dict(prev)
        result["frozen"] = True
        result["flags"].append("weights_locked_replay")
    elif (
        as_of
        and previous_weights is not None
        and last_effective_date
        and week_key(as_of) == week_key(last_effective_date)
    ):
        weights = dict(prev)
        result["frozen"] = True
        result["flags"].append("weights_frozen")
    else:
        gate = oos_gate(oos_excess, min_obs=min_obs, alpha=alpha)
        result["gate"] = gate
        if not gate["passed"]:
            # 等权否决：不达标一律退回等权，不冒险用优化权重
            weights = dict(EQUAL_WEIGHTS)
            result["weight_fallback"] = True
            result["flags"].extend(["weight_fallback", gate["reason"] or "oos_gate_failed"])
        else:
            reliability = axis_reliability(axis_values or {}, forward_returns or [], window=window)
            samples = len(forward_returns or [])
            if samples < int(min_window):
                result["flags"].append("estimation_window_lt_500")
            raw = {
                axis: prior_map[axis]
                * ((abs(reliability[axis]["ic"]) + EPS) ** kappa)
                / (reliability[axis]["sigma"] + EPS)
                for axis in AXES
            }
            candidate = _simplex(raw)
            lam = 0.0
            if uncertainty is not None:
                lam = max(0.0, min(UNCERTAINTY_MAX, float(uncertainty) * UNCERTAINTY_MAX))
                candidate = _shrink_to_prior(candidate, prior_map, lam)
                result["flags"].append("uncertainty_shrink")
            candidate = _clip_normalize(candidate, min_weight=min_weight, max_weight=max_weight)
            weights = _limit_turnover(
                _partial_adjust(candidate, prev, adjust),
                prev,
                max_turnover=max_turnover,
            )
            result["weight_sources"] = {
                "prior": {axis: round(prior_map[axis], 6) for axis in AXES},
                "ic": {axis: reliability[axis]["ic"] for axis in AXES},
                "sigma": {axis: reliability[axis]["sigma"] for axis in AXES},
                "reliability": {axis: reliability[axis]["reliability"] for axis in AXES},
                "uncertainty": round(lam, 6),
            }
    result["weights"] = {axis: round(weights[axis], 6) for axis in AXES}
    result["turnover"] = round(_turnover(result["weights"], prev), 6)
    result["weights_hash"] = weights_hash(result["weights"])
    result["axis_weights"] = {
        **result["weights"],
        "gap": round(float(gap_weight), 6),
    }
    result.setdefault(
        "weight_sources",
        {
            "prior": {axis: round(prior_map[axis], 6) for axis in AXES},
            "ic": dict.fromkeys(AXES, 0.0),
            "sigma": dict.fromkeys(AXES, 0.0),
            "reliability": dict.fromkeys(AXES, 0.0),
            "uncertainty": 0.0,
        },
    )
    result["weight_sources"]["stability"] = {
        "turnover": result["turnover"],
        "stability": round(1.0 - result["turnover"], 6),
    }
    result["weights_effective_date"] = last_effective_date if result["frozen"] else as_of
    return result


__all__: List[str] = [
    "ALPHA",
    "ALPHA_ADJUST",
    "AXES",
    "EQUAL_WEIGHTS",
    "EPS",
    "KAPPA",
    "MAX_TURNOVER",
    "MAX_WEIGHT",
    "MIN_OBS",
    "MIN_WEIGHT",
    "MIN_WINDOW",
    "PRIOR_WEIGHTS",
    "REBALANCE",
    "STATIC_WEIGHTS",
    "UNCERTAINTY_MAX",
    "WEIGHTS_VERSION",
    "WINDOW",
    "axis_reliability",
    "axis_scores",
    "dynamic_weights",
    "is_rebalance_day",
    "oos_gate",
    "week_key",
    "weights_hash",
]
