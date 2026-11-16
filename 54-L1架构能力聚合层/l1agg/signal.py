# -*- coding: utf-8 -*-
"""S6 基信号合成（SPEC-20261116 §5.7 / T6-1）。

只做「关系方向 × 强度分档 → 基信号」的确定性投影：
  - 输入是 MERS/Discovery 已成形的行（不重新估计关系）；
  - 同 (target, horizon) 多条关系按强度加权合成一个 score；
  - 多空并存 → 记入 conflicts，不产出方向信号（门控在 T6-2）；
  - 不写库、不下单、不调用 LLM。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping, Optional

SCHEMA_VERSION = "1.0"
DEFAULT_THRESHOLDS = {"strong": 0.20, "medium": 0.10, "weak": 0.03}
BUCKET_WEIGHTS = {"strong": 1.0, "medium": 0.6, "weak": 0.3}
BUCKET_ORDER = ("strong", "medium", "weak")
SIGNAL_KEYS = (
    "signal_id",
    "target",
    "horizon",
    "direction",
    "strength",
    "score",
    "weight",
    "members",
    "as_of",
)
GATE_LIMITS = {"vol_pct_max": 0.9, "crowd_pct_max": 0.9}
GATE_REASONS = ("conflict", "missing_context", "ma_against", "vol_extreme", "crowded")


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _strength(excess: float, thresholds: Mapping[str, float]) -> str:
    if excess >= float(thresholds["strong"]):
        return "strong"
    if excess >= float(thresholds["medium"]):
        return "medium"
    if excess >= float(thresholds["weak"]):
        return "weak"
    return "none"


def _direction(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def synthesize_signals(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: str = "",
    thresholds: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """把通过门禁的关系行合成为基信号；同一输入必须得到同一输出。"""
    limits = dict(DEFAULT_THRESHOLDS)
    limits.update({key: float(value) for key, value in (thresholds or {}).items()})
    grouped: Dict[tuple, List[Dict[str, Any]]] = {}
    skipped = 0

    for row in rows:
        if row.get("gate_pass") is False:
            skipped += 1
            continue
        direction = _direction(_num(row.get("rank_ic")) or 0.0)
        if direction == 0:
            skipped += 1
            continue
        excess = _num(row.get("excess_hit"))
        if excess is None:
            excess = abs(_num(row.get("rank_ic")) or 0.0)
        bucket = _strength(excess, limits)
        if bucket == "none":
            skipped += 1
            continue
        target = str(row.get("target") or "")
        horizon = int(row.get("horizon") or 0)
        if not target or horizon <= 0:
            skipped += 1
            continue
        grouped.setdefault((target, horizon), []).append(
            {
                "eval_id": str(row.get("eval_id") or ""),
                "method": row.get("method"),
                "transform": row.get("transform"),
                "direction": direction,
                "strength": bucket,
                "weight": BUCKET_WEIGHTS[bucket],
                "excess_hit": excess,
            }
        )

    signals: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    for target, horizon in sorted(grouped):
        members = sorted(
            grouped[(target, horizon)], key=lambda item: (item["eval_id"], item["method"])
        )
        directions = {item["direction"] for item in members}
        if len(directions) > 1:
            conflicts.append(
                {
                    "target": target,
                    "horizon": horizon,
                    "members": [
                        {
                            "eval_id": item["eval_id"],
                            "method": item["method"],
                            "direction": item["direction"],
                            "strength": item["strength"],
                        }
                        for item in members
                    ],
                }
            )
            continue
        total_weight = sum(item["weight"] for item in members)
        score = sum(item["direction"] * item["weight"] for item in members) / total_weight
        strength = min(
            (item["strength"] for item in members),
            key=lambda name: BUCKET_ORDER.index(name),
        )
        signals.append(
            {
                "signal_id": f"SIG-{target}-h{horizon}",
                "target": target,
                "horizon": horizon,
                "direction": _direction(score),
                "strength": strength,
                "score": round(score, 6),
                "weight": round(total_weight, 6),
                "members": [item["eval_id"] for item in members],
                "as_of": as_of,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "thresholds": {key: float(limits[key]) for key in ("strong", "medium", "weak")},
        "signal_count": len(signals),
        "conflict_count": len(conflicts),
        "skipped": skipped,
        "signals": signals,
        "conflicts": conflicts,
    }


def validate_document(document: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {SCHEMA_VERSION}")
    if not isinstance(document.get("signals"), list):
        return errors + ["signals 必须是列表"]
    seen: set[str] = set()
    for index, signal in enumerate(document["signals"]):
        prefix = f"signals[{index}]"
        missing = [key for key in SIGNAL_KEYS if key not in signal]
        if missing:
            errors.append(f"{prefix} 缺字段 {missing}")
            continue
        if signal["signal_id"] in seen:
            errors.append(f"{prefix} signal_id 重复：{signal['signal_id']}")
        seen.add(signal["signal_id"])
        if signal["direction"] not in (-1, 1):
            errors.append(f"{prefix} direction 必须是 ±1")
        if signal["strength"] not in BUCKET_WEIGHTS:
            errors.append(f"{prefix} strength 非法")
        score = signal["score"]
        if not isinstance(score, (int, float)) or not -1.0 <= float(score) <= 1.0:
            errors.append(f"{prefix} score 必须在 [-1, 1]")
        if not signal["members"]:
            errors.append(f"{prefix} members 不能为空")
    for index, conflict in enumerate(document.get("conflicts") or []):
        if not conflict.get("members"):
            errors.append(f"conflicts[{index}] members 不能为空")
    return errors


def to_json(document: Mapping[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2)


def _context_snapshot(context: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(context, Mapping):
        return {"ma_state": None, "vol_pct": None, "crowd_pct": None}
    return {
        "ma_state": context.get("ma_state"),
        "vol_pct": _num(context.get("vol_pct")),
        "crowd_pct": _num(context.get("crowd_pct")),
    }


def _gate_reasons(
    signal: Mapping[str, Any], context: Optional[Mapping[str, Any]], limits: Mapping[str, float]
) -> List[str]:
    if not isinstance(context, Mapping):
        return ["missing_context"]
    reasons: List[str] = []
    state = str(context.get("ma_state") or "")
    direction = int(signal.get("direction") or 0)
    if direction == 1 and state != "up":
        reasons.append("ma_against")
    if direction == -1 and state != "down":
        reasons.append("ma_against")
    vol = _num(context.get("vol_pct"))
    if vol is None or vol > float(limits["vol_pct_max"]):
        reasons.append("vol_extreme")
    crowd = _num(context.get("crowd_pct"))
    if crowd is None or crowd > float(limits["crowd_pct_max"]):
        reasons.append("crowded")
    return reasons


def apply_gating(
    document: Mapping[str, Any],
    context: Mapping[str, Mapping[str, Any]],
    *,
    limits: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """T6-2：方向 × MA 状态 + 波动/拥挤分位门控；冲突与缺上下文一律 blocked。"""
    caps = dict(GATE_LIMITS)
    caps.update({key: float(value) for key, value in (limits or {}).items()})
    allowed: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []

    for conflict in document.get("conflicts") or []:
        target = str(conflict.get("target") or "")
        blocked.append(
            {
                "target": target,
                "horizon": int(conflict.get("horizon") or 0),
                "direction": 0,
                "members": [member.get("eval_id") for member in conflict.get("members") or []],
                "gating": {
                    "decision": "blocked",
                    "reasons": ["conflict"],
                    "context": _context_snapshot(context.get(target)),
                },
            }
        )

    for signal in document.get("signals") or []:
        target = str(signal.get("target") or "")
        snapshot = context.get(target)
        reasons = _gate_reasons(signal, snapshot, caps)
        item = dict(signal)
        item["gating"] = {
            "decision": "blocked" if reasons else "allowed",
            "reasons": reasons,
            "context": _context_snapshot(snapshot),
        }
        (blocked if reasons else allowed).append(item)

    by_reason = dict.fromkeys(GATE_REASONS, 0)
    for item in blocked:
        for reason in item["gating"]["reasons"]:
            by_reason[reason] = by_reason.get(reason, 0) + 1

    no_gate = document.get("signals") or []
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": document.get("as_of") or "",
        "limits": {key: float(caps[key]) for key in ("vol_pct_max", "crowd_pct_max")},
        "signal_count": len(allowed),
        "blocked_count": len(blocked),
        "skipped": int(document.get("skipped") or 0),
        "allowed": allowed,
        "blocked": blocked,
        "ablation": {
            "no_gate": {
                "signals": len(no_gate),
                "targets": sorted({str(item.get("target")) for item in no_gate}),
            },
            "with_gate": {
                "signals": len(allowed),
                "targets": sorted({str(item.get("target")) for item in allowed}),
            },
            "delta": len(no_gate) - len(allowed),
            "by_reason": by_reason,
        },
    }


def validate_gated(document: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {SCHEMA_VERSION}")
    allowed = document.get("allowed")
    blocked = document.get("blocked")
    if not isinstance(allowed, list) or not isinstance(blocked, list):
        return errors + ["allowed/blocked 必须是列表"]
    for index, item in enumerate(allowed):
        gating = item.get("gating") or {}
        if gating.get("decision") != "allowed" or gating.get("reasons"):
            errors.append(f"allowed[{index}] 必须 decision=allowed 且 reasons 为空")
        if item.get("direction") not in (-1, 1):
            errors.append(f"allowed[{index}] direction 必须是 ±1")
    for index, item in enumerate(blocked):
        reasons = (item.get("gating") or {}).get("reasons") or []
        if not reasons:
            errors.append(f"blocked[{index}] reasons 不能为空")
        unknown = [reason for reason in reasons if reason not in GATE_REASONS]
        if unknown:
            errors.append(f"blocked[{index}] 含未知原因 {unknown}")
    ablation = document.get("ablation") or {}
    if ablation.get("delta") != ablation.get("no_gate", {}).get("signals", 0) - ablation.get(
        "with_gate", {}
    ).get("signals", 0):
        errors.append("ablation.delta 与 no_gate/with_gate 不一致")
    return errors
