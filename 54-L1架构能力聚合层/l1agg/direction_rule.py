# -*- coding: utf-8 -*-
"""L1-D 方向规则（`direction_rule`，SPEC-54 §4.7 / ADR-V15）。

定位：把 L1-S 已算好的确定性统计事实，按显式参数合成 `direction ∈ {-1,0,1}`
与 `strength ∈ [0,1]`。**纯函数：同输入同参数 → 字节一致**；禁止 LLM / 随机 / 采样。

硬边界：
  - 所有口径（斜率、ADX、EMA、同向率、p_adj）一律由 L1-S 传入，本模块**不重算**；
  - 输出只进内部 `signal` 表（`visibility=internal`），**永不进信封**（ADR-V14）；
  - 方向是统计外推的标签，不是投资建议；对外措辞受 ADR-V10 约束。

四轴（总分 −100…+100，SPEC §4.7）：
  趋势延续 40 · 趋势强度 25 · 惯性（EMA 排列）20 · 前瞻共振 15；周期律本期只记录。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence

import yaml

PARAMS_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "direction_rule.yaml")
)

AXIS_TREND = 40.0
AXIS_ADX = 25.0
AXIS_INERTIA = 20.0
AXIS_COHERENCE = 15.0
AXIS_GAP = 0.0
AXIS_NAMES = ("trend", "adx", "inertia", "coherence", "gap")
STRENGTH_MODES = ("abs_total", "quantile_dispersion")

_FLAT = 0.0
_REQUIRED_KEYS = ("version", "windows", "window_weights", "adx_bands", "flat_threshold")
_EMA_ORDER = ("bull", "bear", "mixed")


class DirectionRuleError(ValueError):
    """参数/契约错误（配置非法直接抛，不静默降级）。"""


# ---------------- 参数 ----------------


def load_params(path: Optional[str] = None) -> Dict[str, Any]:
    """读 YAML 参数块；缺键、权重长度不一致、窗口非正一律抛错。"""
    target = path or PARAMS_FILE
    with open(target, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    block = raw.get("direction_rule", raw) if isinstance(raw, Mapping) else {}
    if not isinstance(block, Mapping):
        raise DirectionRuleError("direction_rule 必须是映射")
    params = dict(block)
    validate_params(params)
    return params


def validate_params(params: Mapping[str, Any]) -> None:
    for key in _REQUIRED_KEYS:
        if key not in params:
            raise DirectionRuleError(f"缺少参数 {key}")
    windows = list(params["windows"])
    weights = list(params["window_weights"])
    if not windows or len(windows) != len(weights):
        raise DirectionRuleError("windows 与 window_weights 长度必须一致且非空")
    if any(int(w) <= 0 for w in windows):
        raise DirectionRuleError("windows 必须为正整数")
    if any(float(w) <= 0 for w in weights):
        raise DirectionRuleError("window_weights 必须为正数")
    if abs(sum(float(w) for w in weights) - 1.0) > 1e-6:
        raise DirectionRuleError("window_weights 之和必须为 1")
    bands = list(params["adx_bands"])
    if not bands or any(len(b) != 3 for b in bands):
        raise DirectionRuleError("adx_bands 必须是 [lo, hi, score] 三元组列表")
    if "exit_threshold" in params and float(params["exit_threshold"]) >= float(
        params["flat_threshold"]
    ):
        raise DirectionRuleError("exit_threshold 必须小于 flat_threshold")
    weights = axis_weights(params)
    if any(w < 0 for w in weights.values()):
        raise DirectionRuleError("axis_weights 必须非负")
    if sum(weights.values()) <= 0:
        raise DirectionRuleError("axis_weights 不能全为 0")
    mode = str(params.get("strength_mode", "abs_total"))
    if mode not in STRENGTH_MODES:
        raise DirectionRuleError(f"未知 strength_mode: {mode}")
    if float(params.get("dispersion_ref", 0.1)) <= 0:
        raise DirectionRuleError("dispersion_ref 必须为正")


def axis_weights(params: Mapping[str, Any]) -> Dict[str, float]:
    """四轴（+ 可选 gap）权重；未配置时回落到方法库默认 40/25/20/15/0。"""
    raw = params.get("axis_weights") or {}
    defaults = {
        "trend": AXIS_TREND,
        "adx": AXIS_ADX,
        "inertia": AXIS_INERTIA,
        "coherence": AXIS_COHERENCE,
        "gap": AXIS_GAP,
    }
    return {name: float(raw.get(name, defaults[name])) for name in AXIS_NAMES}


def canonical(obj: Any) -> Any:
    """JSON 往返归一（元组→列表、键排序），保证快照可哈希可比较。"""
    return json.loads(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str))


def params_hash(params: Mapping[str, Any]) -> str:
    """参数指纹：`signal` 表据此回放同一规则（含 version）。"""
    payload = json.dumps(
        canonical(params), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


DEFAULT_PARAMS: Dict[str, Any] = load_params()


# ---------------- 打分 ----------------


def _sign(value: Any) -> int:
    if value is None:
        return 0
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0
    if abs(x) < 1e-12:
        return 0
    return 1 if x > 0 else -1


def _r6(value: float) -> float:
    return round(float(value), 6)


def _window_weights(params: Mapping[str, Any], flags: List[str]) -> List[float]:
    """窗口权重：默认取配置；`midas.enabled` 时由 Beta 多项式按频率生成（§4.12 第 2 条）。"""
    base = [float(w) for w in params["window_weights"]]
    cfg = params.get("midas") or {}
    if not cfg.get("enabled"):
        return base
    from .methods.fed_methods import midas_weights

    table = midas_weights(
        [int(w) for w in params["windows"]],
        theta1=float(cfg.get("theta1", 1.0)),
        theta2=float(cfg.get("theta2", 3.0)),
    )
    flags.append("midas_weights")
    return [float(w) for w in table["weights"]]


def _trend_axis(
    slope_table: Optional[Sequence[Mapping[str, Any]]],
    params: Mapping[str, Any],
    flags: List[str],
    weight: float = AXIS_TREND,
) -> float:
    """四窗口 `sign(slope)` 加权一致度 × 轴权重；`t` 与 `slope` 异号记不一致。

    缺失窗口（D-E15 的 `window_gt_sample`）不伪造：按剩余权重归一，并打降级旗标。
    """
    windows = [int(w) for w in params["windows"]]
    weights = _window_weights(params, flags)
    rows: Dict[int, Mapping[str, Any]] = {}
    for row in slope_table or []:
        try:
            rows[int(row.get("window"))] = row
        except (TypeError, ValueError, AttributeError):
            continue
    weighted = 0.0
    used_weight = 0.0
    missing: List[int] = []
    for window, w in zip(windows, weights, strict=False):
        row = rows.get(window)
        slope = row.get("slope") if row else None
        if slope is None:
            missing.append(window)
            continue
        sign = _sign(slope)
        t_value = row.get("t")
        if sign != 0 and _sign(t_value) == -sign:
            sign = 0  # t 与 slope 异号视为不一致
        weighted += w * sign
        used_weight += w
    if missing:
        flags.append("degraded_windows")
    if used_weight <= 0:
        flags.append("trend_data_missing")
        return 0.0
    return _r6(weighted / used_weight * float(weight))


def _adx_axis(
    adx: Any, params: Mapping[str, Any], flags: List[str], weight: float = AXIS_ADX
) -> float:
    """ADX 分档（<20→0 / 20–25→0.5 / >25→1.0）× DI 方向 × 轴权重。"""
    if not isinstance(adx, Mapping) or adx.get("adx14") is None:
        flags.append("adx_missing")
        return 0.0
    value = float(adx["adx14"])
    band = 0.0
    for low, high, score in params["adx_bands"]:
        if float(low) <= value < float(high):
            band = float(score)
            break
    direction = _sign(
        float(adx["plus_di"]) - float(adx["minus_di"])
        if adx.get("plus_di") is not None and adx.get("minus_di") is not None
        else None
    )
    if direction == 0:
        flags.append("di_missing")
    return _r6(band * direction * float(weight))


def _ema_order(ema: Any, flags: List[str]) -> Optional[str]:
    if not isinstance(ema, Mapping):
        flags.append("ema_missing")
        return None
    order = ema.get("order")
    if order in _EMA_ORDER:
        return str(order)
    fast, slow, trend = ema.get("ema12"), ema.get("ema26"), ema.get("ema50")
    if fast is None or slow is None or trend is None:
        flags.append("ema_missing")
        return None
    flags.append("ema_order_derived")
    fast, slow, trend = float(fast), float(slow), float(trend)
    if fast > slow > trend:
        return "bull"
    if fast < slow < trend:
        return "bear"
    return "mixed"


def _inertia_axis(order: Optional[str], flags: List[str], weight: float = AXIS_INERTIA) -> float:
    """EMA 排列：bull→+1、mixed→+0.4、bear→−1，× 轴权重。"""
    if order == "bull":
        return _r6(float(weight))
    if order == "mixed":
        return _r6(0.4 * float(weight))
    if order == "bear":
        return _r6(-float(weight))
    return 0.0


def _coherence_axis(
    rate: Any,
    trend_axis: float,
    params: Mapping[str, Any],
    flags: List[str],
    weight: float = AXIS_COHERENCE,
) -> float:
    """同向率 `(r−0.5)×2` 截断 [0,1]，符号随趋势轴；缺失记 0 并标 `coherence_missing`。"""
    if not params.get("use_same_direction", True):
        return 0.0
    if not isinstance(rate, Mapping) or rate.get("r") is None:
        flags.append("coherence_missing")
        return 0.0
    magnitude = max(0.0, min(1.0, (float(rate["r"]) - 0.5) * 2.0))
    sign = _sign(trend_axis)
    if sign == 0:
        return 0.0
    return _r6(sign * magnitude * float(weight))


def _gap_axis(
    gap: Any,
    params: Mapping[str, Any],
    weights: Mapping[str, float],
    flags: List[str],
) -> Optional[float]:
    """协整 gap 轴（§4.12 第 3/4 条）：泰勒式显式系数，默认均值回归符号。

    `gap_z = (raw − neutral) / scale`，分数 = `−sign(gap_z)·min(1,|gap_z|)·w_gap`；
    价格显著高于均衡 → 负分，与趋势轴方向常相反，天然构成对冲结构。
    """
    cfg = dict(params.get("gap_axis") or {})
    weight = max(0.0, float(weights.get("gap", 0.0)))
    enabled = bool(cfg.get("enabled", False)) or weight > 0
    if not enabled:
        return None
    if weight <= 0:
        weight = max(0.0, float(cfg.get("weight", 10.0)))
    if not isinstance(gap, Mapping) or gap.get("gap_z") is None:
        flags.append("gap_missing")
        return None
    scale = float(cfg.get("scale", 1.0))
    if scale == 0:
        raise DirectionRuleError("gap_axis.scale 不能为 0")
    gap_z = (float(gap["gap_z"]) - float(cfg.get("neutral", 0.0))) / scale
    sign = 1.0 if str(cfg.get("sign", "mean_reversion")) == "mean_reversion" else -1.0
    return _r6(-sign * _sign(gap_z) * min(1.0, abs(gap_z)) * weight)


def _seasonality_record(
    seasonality: Any, params: Mapping[str, Any], flags: List[str]
) -> Optional[Dict[str, Any]]:
    """周期律本期只记录（`seasonality_mode=record_only`）；深度 <5 年必须为 null。"""
    if not isinstance(seasonality, Mapping) or not seasonality:
        return None
    if params.get("seasonality_mode") != "record_only":
        return None
    depth = seasonality.get("depth_years")
    if depth is not None and float(depth) < 5.0:
        flags.append("seasonality_depth_lt_5y")
        return None
    return dict(canonical(seasonality))


def score(inputs: Mapping[str, Any], params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """四轴 + 可选 gap 轴打分；`inputs` 缺项按降级处理（不抛错、不补造数据）。"""
    p = dict(params or DEFAULT_PARAMS)
    clock = inputs or {}
    flags: List[str] = []
    weights = axis_weights(p)

    trend = _trend_axis(clock.get("slope_table"), p, flags, weights["trend"])
    adx_axis = _adx_axis(clock.get("adx"), p, flags, weights["adx"])
    order = _ema_order(clock.get("ema"), flags)
    inertia = _inertia_axis(order, flags, weights["inertia"])
    coherence = _coherence_axis(
        clock.get("same_direction_rate"), trend, p, flags, weights["coherence"]
    )
    gap_axis = _gap_axis(clock.get("equilibrium_gap"), p, weights, flags)

    p_adj = clock.get("p_adj")
    if p.get("use_significance", True):
        if p_adj is None:
            # D-G22 缺失时不得静默跳过显著性门：显式降级，便于下游审计。
            flags.append("significance_unavailable")
        elif float(p_adj) > float(p["hac_alpha"]):
            adx_axis = _r6(adx_axis * 0.5)
            flags.append("hac_insignificant")

    seasonality = _seasonality_record(clock.get("seasonality"), p, flags)

    axes: Dict[str, float] = {
        "trend": trend,
        "adx": adx_axis,
        "inertia": inertia,
        "coherence": coherence,
    }
    if gap_axis is not None:
        axes["gap"] = gap_axis
    total = _r6(max(-100.0, min(100.0, sum(axes.values()))))
    return {
        "total": total,
        "axes": axes,
        "axis_weights": (
            weights if gap_axis is not None else {k: v for k, v in weights.items() if k != "gap"}
        ),
        "ema_order": order,
        "flags": sorted(set(flags)),
        "seasonality": seasonality,
    }


def _strength(
    inputs: Mapping[str, Any], params: Mapping[str, Any], total: float, flags: List[str]
) -> float:
    """强度：默认 `|total|/100`；`quantile_dispersion` 用 I36 的 `q90−q10` 预测离散度。"""
    mode = str(params.get("strength_mode", "abs_total"))
    if mode == "quantile_dispersion":
        block = inputs.get("forward_distribution")
        if isinstance(block, Mapping) and block.get("dispersion") is not None:
            ref = float(params.get("dispersion_ref", 0.1))
            flags.append("strength_from_dispersion")
            return _r6(min(1.0, abs(float(block["dispersion"])) / ref))
        flags.append("forward_distribution_missing")
    return _r6(min(1.0, abs(total) / 100.0))


def strength_band(strength: float) -> str:
    """强度分档：flat <0.30 ≤ weak <0.55 ≤ moderate <0.75 ≤ strong（统计强度，非建议）。"""
    value = float(strength)
    if value < 0.30:
        return "flat"
    if value < 0.55:
        return "weak"
    if value < 0.75:
        return "moderate"
    return "strong"


def decide(
    inputs: Mapping[str, Any],
    params: Optional[Mapping[str, Any]] = None,
    *,
    as_of: Optional[str] = None,
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """产出一条可回放的内部方向记录（字段与 `signal` 表一一对应）。"""
    p = dict(params or DEFAULT_PARAMS)
    scored = score(inputs, p)
    total = float(scored["total"])
    flat_threshold = float(p["flat_threshold"])
    direction = 0 if abs(total) < flat_threshold else _sign(total)
    flags = list(scored["flags"])
    strength = _strength(inputs or {}, p, total, flags)
    if direction == 0:
        flags = sorted(set(flags + ["flat"]))
    return {
        "as_of": as_of,
        "symbol": symbol,
        "rule_version": p["version"],
        "params_hash": params_hash(p),
        "direction": direction,
        "strength": strength,
        "band": strength_band(strength),
        "total": total,
        "axes": scored["axes"],
        "axis_weights": scored["axis_weights"],
        "ema_order": scored["ema_order"],
        "flags": flags,
        "seasonality": scored["seasonality"],
        "inputs_snapshot": canonical(inputs or {}),
    }


__all__ = [
    "AXIS_TREND",
    "AXIS_ADX",
    "AXIS_INERTIA",
    "AXIS_COHERENCE",
    "AXIS_GAP",
    "AXIS_NAMES",
    "DEFAULT_PARAMS",
    "DirectionRuleError",
    "PARAMS_FILE",
    "STRENGTH_MODES",
    "axis_weights",
    "canonical",
    "decide",
    "load_params",
    "params_hash",
    "score",
    "strength_band",
    "validate_params",
]
