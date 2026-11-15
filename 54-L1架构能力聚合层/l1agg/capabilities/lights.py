# -*- coding: utf-8 -*-
"""D-E19 信号点亮投影（SPEC-54-L1交易层 §5.2 / §5.3，P0-4）。

定位：把 `direction_rule` **已算好的**轴值投影成公开的轴级状态，零重算。
本模块不读库、不写库、不调 LLM、不重算任何统计量。

轴映射（内部四轴 → 点亮四轴）：

  | 点亮轴 | 内部来源 | 归一化 |
  |---|---|---|
  | `trend` | `axes.trend` / `axis_weights.trend`（D-E15 多窗口斜率符号一致度） | `|v| / w` |
  | `inertia` | `axes.inertia` / `axis_weights.inertia`（EMA 排列） | `|v| / w` |
  | `foresight` | `axes.coherence` / `axis_weights.coherence`（前瞻共振 / 领先滞后） | `|v| / w` |
  | `cycle` | I39 带通·周期相位（外部传入，已是 [0,1] 归一值） | 原样 |

  `adx` 轴不单列（趋势强度修饰）；`gap` 轴默认关闭，均不进入点亮。

硬边界：
  - `state` 只用 `lit/warm/dim/conflict/unavailable`，禁止方向措辞（LT-G1）；
  - `conflict` 是**只读旗标**：`trend.lit` 且 `foresight.flags` 命中
    `vix_pct_ge_0.90 / vix_divergence / curve_inverted`，**不读** `foresight.strength`；
  - 短样本 `n < min_rows` / `gate != ok` / `not_collected` → 整标的 `unavailable`
    （`unavailable` 优先于一切，LT-G6 / §5.3）；
  - `strength = Σ lw_k × normalized_axis_k`，`lw` 只取 `light_weights`（三权分立 B-LT3），
    缺失轴剔除后按剩余权重重新归一（不静默按 0 计）；
  - 权重/阈值运行期非法 → 降级等权 + `weights_degraded=true`（展示层 FAIL-OPEN）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..chart_weights import (
    DEFAULT_MIN_ROWS,
    ChartWeights,
    ChartWeightsError,
    light_weights_hash,
    validate_weights,
)
from ..chart_weights import (
    load as load_chart_weights,
)
from .envelope import (
    STATUS_GOOD,
    STATUS_PARTIAL,
    build,
    quality,
    quality_for,
    unavailable,
)

CAPABILITY = "D-E19"
INTENT_LIGHTS = "trend_query"

AXES: Tuple[str, ...] = ("trend", "inertia", "cycle", "foresight")
STATES: Tuple[str, ...] = ("lit", "warm", "dim", "conflict", "unavailable")
BUCKETS: Tuple[str, ...] = ("high", "mid", "low", "none")
DEFAULT_THRESHOLDS: Dict[str, float] = {"lit_pct": 0.70, "warm_pct": 0.40}

# `conflict` 只读旗标（§5.3 第 4 条）；只认这些名字，不读 strength
CONFLICT_FLAGS: Tuple[str, ...] = (
    "vix_pct_ge_0.90",
    "vix_divergence",
    "curve_inverted",
)

AXIS_CAPABILITY: Dict[str, str] = {
    "trend": "D-E15",
    "inertia": "D-E15",
    "foresight": "D-E11",
    "cycle": "I39",
}
# 内部轴 → 点亮轴（cycle 由 I39 外部传入，不在此映射）
_INNER_AXIS: Dict[str, str] = {
    "trend": "trend",
    "inertia": "inertia",
    "foresight": "coherence",
}

METHODS: List[str] = ["I37", "I39", "I36"]
# I39 带通·周期分解的样本门槛（`fed_methods.i39_bandpass` 的 min_n），低于此不产周期事实
I39_MIN_N = 750
CYCLE_PERIOD_BAND: Tuple[float, float] = (30.0, 90.0)
_UNAVAILABLE_STATUS = frozenset({"not_collected", "unavailable", "missing", "empty"})


# ------------------------------------------------------------ 归一（零重算）
def _clamp01(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(0.0, min(1.0, number))


def normalize_axis(axis_value: Any, axis_weight: Any) -> Optional[float]:
    """`|axis_value| / axis_weight`，截断 [0,1]；轴权重 ≤0 或缺值 → None（不伪造）。"""
    if axis_value is None or axis_weight is None:
        return None
    try:
        weight = float(axis_weight)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(weight) or weight <= 0.0:
        return None
    return _clamp01(abs(float(axis_value)) / weight)


def axes_from_direction(
    scored: Mapping[str, Any],
    *,
    cycle: Optional[Mapping[str, Any]] = None,
    foresight_flags: Sequence[str] = (),
    foresight_evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """把 `direction_rule.score/decide` 的轴值归一为点亮四轴事实（不重算）。

    `foresight_evidence` 只做披露（I36 前瞻分布摘要），**不参与强度计算**：
    `foresight.strength` 仍等于 `coherence` 轴归一（LT-AC3 一致性契约）。
    """
    axes_raw = dict((scored or {}).get("axes") or {})
    weights = dict((scored or {}).get("axis_weights") or {})
    facts: Dict[str, Dict[str, Any]] = {}
    for light_axis, inner in _INNER_AXIS.items():
        facts[light_axis] = {
            "strength": normalize_axis(axes_raw.get(inner), weights.get(inner)),
            "capability": AXIS_CAPABILITY[light_axis],
            "axis_value": axes_raw.get(inner),
            "axis_weight": weights.get(inner),
            "flags": list(foresight_flags) if light_axis == "foresight" else [],
            "evidence": dict(foresight_evidence or {}) if light_axis == "foresight" else {},
        }
    block = dict(cycle or {})
    facts["cycle"] = {
        "strength": _clamp01(block.get("strength")),
        "capability": str(block.get("capability") or AXIS_CAPABILITY["cycle"]),
        "flags": [str(flag) for flag in block.get("flags") or ()],
        "evidence": dict(block.get("evidence") or {}),
    }
    return facts


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def cycle_from_bandpass(result: Mapping[str, Any], *, capability: str = "I39") -> Dict[str, Any]:
    """I39 带通输出 → 点亮 `cycle` 轴块（零重算：只读 I39 已发布字段）。

    `strength = clamp01(|cycle_tail| / amplitude)`——当前周期偏离中枢的程度相对
    **自身振幅**（I39 的 `amplitude` 是 log 价差段的总体标准差），无外部常数；
    `period_days` 缺失/越出 30–90 → 显式 flags，不伪造相位。
    """
    data = dict(result or {})
    period = _number(data.get("period_days"))
    amplitude = _number(data.get("amplitude"))
    points = data.get("cycle") or ()
    tail = None
    if isinstance(points, (list, tuple)) and points:
        last = points[-1]
        tail = _number(last.get("value")) if isinstance(last, Mapping) else _number(last)

    flags: List[str] = []
    if period is None:
        flags.append("period_missing")
    elif not CYCLE_PERIOD_BAND[0] <= period <= CYCLE_PERIOD_BAND[1]:
        flags.append("period_out_of_band")

    strength: Optional[float] = None
    if amplitude is None or amplitude <= 0.0:
        flags.append("amplitude_unavailable")
    elif tail is None:
        flags.append("cycle_missing")
    else:
        strength = _clamp01(abs(tail) / amplitude)

    return {
        "strength": strength,
        "capability": capability,
        "flags": flags,
        "evidence": {
            "period_days": period,
            "phase_deg": _number(data.get("phase_deg")),
            "amplitude": amplitude,
            "cycle_last": tail,
            "cycle_slope": _number(data.get("cycle_slope")),
            "n": data.get("n"),
        },
    }


# ------------------------------------------------------------ 权重/阈值
def _equal_weights() -> Dict[str, float]:
    share = round(1.0 / len(AXES), 6)
    return dict.fromkeys(AXES, share)


def resolve_light_weights(
    cfg: Optional[ChartWeights],
    weights: Any = None,
    *,
    mode: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """解析点亮四轴权重（FAIL-OPEN）：`off` → 等权；非法 → 等权 + `weights_degraded`。"""
    base: Mapping[str, Any] = cfg.light_weights if cfg is not None else dict(weights or {})
    resolved_mode = str(mode or (cfg.mode if cfg is not None else "on"))
    resolved_source = str(source or (cfg.source if cfg is not None else "config"))
    out: Dict[str, Any] = {
        "weights": {},
        "source": resolved_source,
        "mode": resolved_mode,
        "weights_degraded": False,
        "flags": [],
    }
    if resolved_mode != "on":
        out["weights"] = _equal_weights()
        out["source"] = "equal"
        out["flags"].append("light_weights_off")
        return out
    candidate = {axis: round(float(base.get(axis, 0.0) or 0.0), 6) for axis in AXES}
    try:
        validate_weights(
            "light_weights",
            candidate,
            min_weight=0.0,
            max_weight=1.0,
            tolerance=float(cfg.sum_tolerance if cfg is not None else 1e-6),
        )
    except ChartWeightsError as exc:
        out["weights"] = _equal_weights()
        out["source"] = "equal"
        out["weights_degraded"] = True
        out["flags"].extend(["light_weights_invalid", str(exc)])
        return out
    out["weights"] = candidate
    return out


def resolve_thresholds(
    cfg: Optional[ChartWeights], thresholds: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """解析阈值（FAIL-OPEN）：越界或非数值 → 回落 0.70/0.40 并标 `thresholds_invalid`。"""
    merged: Dict[str, Any] = dict(cfg.thresholds if cfg is not None else DEFAULT_THRESHOLDS)
    merged.update(dict(thresholds or {}))
    out: Dict[str, Any] = {"thresholds": dict(DEFAULT_THRESHOLDS), "flags": []}
    try:
        lit = float(merged.get("lit_pct", DEFAULT_THRESHOLDS["lit_pct"]))
        warm = float(merged.get("warm_pct", DEFAULT_THRESHOLDS["warm_pct"]))
    except (TypeError, ValueError):
        out["flags"].append("thresholds_invalid")
        return out
    if not (math.isfinite(lit) and math.isfinite(warm)) or not 0.0 <= warm <= lit <= 1.0:
        out["flags"].append("thresholds_invalid")
        return out
    out["thresholds"] = {"lit_pct": lit, "warm_pct": warm}
    return out


# ------------------------------------------------------------ 投影
def _classify(strength: float, thresholds: Mapping[str, float]) -> Tuple[str, str]:
    """强度 → (state, bucket)；分档口径只表达统计一致性，不表达多空。"""
    if strength >= float(thresholds["lit_pct"]):
        return "lit", "high"
    if strength >= float(thresholds["warm_pct"]):
        return "warm", "mid"
    return "dim", "low"


def _evidence(axis: str, fact: Mapping[str, Any]) -> Dict[str, Any]:
    evidence: Dict[str, Any] = {"capability": str(fact.get("capability") or AXIS_CAPABILITY[axis])}
    if fact.get("axis_value") is not None:
        evidence["axis_value"] = round(float(fact["axis_value"]), 6)
    if fact.get("axis_weight") is not None:
        evidence["axis_weight"] = round(float(fact["axis_weight"]), 6)
    evidence.update(dict(fact.get("evidence") or {}))
    return evidence


def _unavailable_entry(
    entry: Mapping[str, Any],
    reason: str,
    *,
    light_hash: str,
    n: int,
    threshold: int,
    status: str,
) -> Dict[str, Any]:
    """整标的不可点亮：四轴全 `unavailable`，`unavailable` 优先于一切。"""
    axis_flags = [reason] if reason else []
    extra_flags = list(axis_flags)
    if status and status != "available":
        extra_flags.append(f"status_{status}")
    axes = {
        axis: {
            "state": "unavailable",
            "strength": None,
            "bucket": "none",
            "evidence": {},
            "flags": list(axis_flags),
        }
        for axis in AXES
    }
    return {
        "symbol": str(entry.get("symbol") or ""),
        "class": str(entry.get("class") or entry.get("view") or "未分类"),
        "as_of": entry.get("as_of"),
        "axes": axes,
        "strength": None,
        "summary": {"lit_n": 0, "warm_n": 0, "conflict_n": 0, "unavailable_n": len(AXES)},
        "light_weights_hash": light_hash,
        "n": int(n),
        "min_rows": int(threshold),
        "status": "unavailable",
        "flags": sorted(set(extra_flags)),
    }


def light_entry(
    entry: Mapping[str, Any],
    *,
    weights: Mapping[str, float],
    thresholds: Mapping[str, float],
    light_hash: str,
    min_rows: int,
) -> Dict[str, Any]:
    """单个标的的点亮投影（入参含 `scored`，或显式 `axes` 事实）。"""
    n = int(entry.get("n") or 0)
    threshold = int(entry.get("min_rows") or min_rows)
    status = str(entry.get("status") or "available")
    gate = str(entry.get("gate") or "ok")

    if status in _UNAVAILABLE_STATUS:
        return _unavailable_entry(
            entry,
            f"status_{status}",
            light_hash=light_hash,
            n=n,
            threshold=threshold,
            status=status,
        )
    if gate != "ok":
        return _unavailable_entry(
            entry, f"gate_{gate}", light_hash=light_hash, n=n, threshold=threshold, status=status
        )
    if n < threshold:
        return _unavailable_entry(
            entry,
            f"history_lt_{threshold}",
            light_hash=light_hash,
            n=n,
            threshold=threshold,
            status=status,
        )

    explicit = entry.get("axes")
    if isinstance(explicit, Mapping):
        facts: Dict[str, Dict[str, Any]] = {}
        for axis in AXES:
            item = explicit.get(axis)
            if isinstance(item, Mapping):
                facts[axis] = {
                    "strength": _clamp01(item.get("strength")),
                    "capability": str(item.get("capability") or AXIS_CAPABILITY[axis]),
                    "flags": [str(flag) for flag in item.get("flags") or ()],
                    "evidence": dict(item.get("evidence") or {}),
                }
            else:
                facts[axis] = {
                    "strength": _clamp01(item),
                    "capability": AXIS_CAPABILITY[axis],
                    "flags": [],
                    "evidence": {},
                }
    else:
        facts = axes_from_direction(
            entry.get("scored") or {},
            cycle=entry.get("cycle"),
            foresight_flags=[str(flag) for flag in entry.get("foresight_flags") or ()],
            foresight_evidence=entry.get("foresight_evidence"),
        )

    axes_out: Dict[str, Dict[str, Any]] = {}
    for axis in AXES:
        fact = facts[axis]
        strength = fact.get("strength")
        flags = sorted({str(flag) for flag in fact.get("flags") or ()})
        if strength is None:
            axes_out[axis] = {
                "state": "unavailable",
                "strength": None,
                "bucket": "none",
                "evidence": _evidence(axis, fact),
                "flags": sorted(set(flags + ["axis_missing"])),
            }
            continue
        state, bucket = _classify(float(strength), thresholds)
        axes_out[axis] = {
            "state": state,
            "strength": float(strength),
            "bucket": bucket,
            "evidence": _evidence(axis, fact),
            "flags": flags,
        }

    # `conflict` 只读旗标：trend 已点亮且 foresight 命中外部风险旗标
    foresight = axes_out["foresight"]
    if (
        axes_out["trend"]["state"] == "lit"
        and foresight["state"] != "unavailable"
        and set(foresight["flags"]) & set(CONFLICT_FLAGS)
    ):
        foresight["state"] = "conflict"

    participating = [axis for axis in AXES if axes_out[axis]["state"] != "unavailable"]
    total_weight = sum(float(weights[axis]) for axis in participating)
    strength: Optional[float] = None
    if participating and total_weight > 0.0:
        strength = round(
            sum(
                float(weights[axis]) / total_weight * float(axes_out[axis]["strength"])
                for axis in participating
            ),
            6,
        )

    summary = {
        "lit_n": sum(1 for axis in AXES if axes_out[axis]["state"] == "lit"),
        "warm_n": sum(1 for axis in AXES if axes_out[axis]["state"] == "warm"),
        "conflict_n": sum(1 for axis in AXES if axes_out[axis]["state"] == "conflict"),
        "unavailable_n": len(AXES) - len(participating),
    }
    entry_flags = {str(flag) for flag in entry.get("flags") or ()}
    entry_flags.update(f"axis_missing_{axis}" for axis in AXES if axis not in participating)
    entry_flags.update(foresight["flags"])
    return {
        "symbol": str(entry.get("symbol") or ""),
        "class": str(entry.get("class") or entry.get("view") or "未分类"),
        "as_of": entry.get("as_of"),
        "axes": axes_out,
        "strength": strength,
        "summary": summary,
        "light_weights_hash": light_hash,
        "n": n,
        "min_rows": threshold,
        "status": "available" if len(participating) == len(AXES) else "partial",
        "flags": sorted(entry_flags),
    }


def light_block(
    entries: Sequence[Mapping[str, Any]],
    *,
    weights: Any = None,
    thresholds: Optional[Mapping[str, Any]] = None,
    min_rows: Optional[int] = None,
    mode: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """产出 D-E19 能力块（`gate=ok`；无入参时 `gate=empty`）。"""
    cfg = weights if isinstance(weights, ChartWeights) else None
    resolved = resolve_light_weights(cfg, weights, mode=mode, source=source)
    resolved_thresholds = resolve_thresholds(cfg, thresholds)
    threshold = int(
        min_rows if min_rows is not None else (cfg.min_rows if cfg else DEFAULT_MIN_ROWS)
    )
    light_hash = light_weights_hash(resolved["weights"], resolved_thresholds["thresholds"])

    rows = [
        light_entry(
            entry,
            weights=resolved["weights"],
            thresholds=resolved_thresholds["thresholds"],
            light_hash=light_hash,
            min_rows=threshold,
        )
        for entry in entries or ()
        if isinstance(entry, Mapping)
    ]
    if not rows:
        return {
            "gate": "empty",
            "methods": list(METHODS),
            "reason": "no_entries",
            "lights": [],
            "meta": {"n": 0},
        }

    meta = {
        "n": len(rows),
        "light_weights": {axis: round(float(resolved["weights"][axis]), 6) for axis in AXES},
        "light_weights_hash": light_hash,
        "light_weights_source": resolved["source"],
        "light_weights_mode": resolved["mode"],
        "weights_degraded": bool(resolved["weights_degraded"]),
        "thresholds": {
            "lit_pct": resolved_thresholds["thresholds"]["lit_pct"],
            "warm_pct": resolved_thresholds["thresholds"]["warm_pct"],
        },
        "thresholds_uncalibrated": not bool(cfg.calibrated_at if cfg is not None else ""),
        "min_rows": threshold,
        "states": list(STATES),
        "conflict_flags": list(CONFLICT_FLAGS),
        "flags": sorted(set(resolved["flags"] + resolved_thresholds["flags"])),
    }
    summary = {
        "lit_n": sum(row["summary"]["lit_n"] for row in rows),
        "warm_n": sum(row["summary"]["warm_n"] for row in rows),
        "conflict_n": sum(row["summary"]["conflict_n"] for row in rows),
        "unavailable_n": sum(row["summary"]["unavailable_n"] for row in rows),
    }
    return {
        "gate": "ok",
        "methods": list(METHODS),
        "lights": rows,
        "summary": summary,
        "meta": meta,
    }


def lights(
    entries: Sequence[Mapping[str, Any]],
    *,
    weights: Any = None,
    thresholds: Optional[Mapping[str, Any]] = None,
    min_rows: Optional[int] = None,
    mode: Optional[str] = None,
    source: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """D-E19 信封：`data.lights` 轴级状态数组（public，随信封返回，非图种）。"""
    cfg = weights if isinstance(weights, ChartWeights) else None
    if cfg is None and not weights:
        try:
            cfg = load_chart_weights()
        except ChartWeightsError:
            cfg = None
    block = light_block(
        entries,
        weights=cfg if cfg is not None else weights,
        thresholds=thresholds,
        min_rows=min_rows,
        mode=mode,
        source=source,
    )
    if block.get("gate") != "ok":
        return unavailable(
            capability=CAPABILITY,
            intent=INTENT_LIGHTS,
            reason="点亮无可用轴输入（未提供标的）",
            trace_id=trace_id,
        )

    meta = block["meta"]
    threshold = int(meta["min_rows"])
    counts = [int(row["n"]) for row in block["lights"] if int(row["n"]) > 0]
    if not counts:
        return unavailable(
            capability=CAPABILITY,
            intent=INTENT_LIGHTS,
            reason="点亮输入无有效观测（样本为 0）",
            trace_id=trace_id,
        )
    sample_n = min(counts)
    q = quality_for(
        sample_n,
        min_n=threshold,
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    reasons: List[str] = []
    if meta["weights_degraded"]:
        reasons.append("light_weights_degraded")
    if any(row["status"] != "available" for row in block["lights"]):
        reasons.append("axes_unavailable")
    if reasons:
        q = quality(
            status=STATUS_PARTIAL,
            sample_n=int(q["sample_n"]),
            span=q.get("span"),
            degraded_reason="+".join(reasons),
            sources=["market.candles"],
            align_method="utc_daily_close",
            timezone="UTC",
        )

    summary = block["summary"]
    head = (
        f"点亮投影覆盖 {len(block['lights'])} 个标的："
        f"lit {summary['lit_n']} / warm {summary['warm_n']} / "
        f"conflict {summary['conflict_n']} / unavailable {summary['unavailable_n']} 轴；"
        f"权重指纹 {meta['light_weights_hash'][:12]}。"
    )
    tail = (
        "样本不足或轴缺失已降级披露，短样本一律不点亮。"
        if q["status"] != STATUS_GOOD
        else "全部标的样本达标，四轴均参与合成。"
    )
    answer = f"{head}{tail}历史统计，不代表未来。"

    payload = {
        "lights": block["lights"],
        "capabilities": {CAPABILITY: block},
        "params": {"min_n": threshold},
    }
    return build(
        capability=CAPABILITY,
        intent=INTENT_LIGHTS,
        answer=answer,
        data=payload,
        quality_block=q,
        trace_id=trace_id,
    )


__all__ = [
    "AXES",
    "AXIS_CAPABILITY",
    "BUCKETS",
    "CAPABILITY",
    "CONFLICT_FLAGS",
    "DEFAULT_THRESHOLDS",
    "INTENT_LIGHTS",
    "METHODS",
    "STATES",
    "axes_from_direction",
    "light_block",
    "light_entry",
    "lights",
    "normalize_axis",
    "resolve_light_weights",
    "resolve_thresholds",
]
