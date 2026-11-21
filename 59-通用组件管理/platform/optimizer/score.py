"""五维加权评分与 blocker 聚合。"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import rules
from .loaders import Surface


def _grade(total: float, card: dict) -> str:
    thresholds = card.get("thresholds") or {}
    if total >= float(thresholds.get("grade_a", 90)):
        return "A"
    if total >= float(thresholds.get("grade_b", 75)):
        return "B"
    if total >= float(thresholds.get("grade_c", 60)):
        return "C"
    return "D"


def score_surface(
    surface: Surface, card: dict, siblings: Optional[List[str]] = None
) -> Dict[str, object]:
    findings = rules.evaluate(surface, card, siblings)
    dimensions_cfg = card.get("dimensions") or {}
    buckets: Dict[str, Dict[str, float]] = {}
    for finding in findings:
        bucket = buckets.setdefault(finding.dimension, {"earned": 0.0, "max": 0.0})
        bucket["earned"] += finding.earned
        bucket["max"] += finding.weight

    dimensions: Dict[str, Dict[str, object]] = {}
    weighted_total = 0.0
    weight_sum = 0.0
    for name, config in dimensions_cfg.items():
        bucket = buckets.get(name)
        if not bucket or bucket["max"] <= 0:
            continue
        score = round(100.0 * bucket["earned"] / bucket["max"], 2)
        weight = float(config.get("weight") or 0)
        dimensions[name] = {
            "label": config.get("label") or name,
            "weight": weight,
            "score": score,
            "earned": round(bucket["earned"], 2),
            "max": round(bucket["max"], 2),
        }
        weighted_total += score * weight
        weight_sum += weight

    total = round(weighted_total / weight_sum, 2) if weight_sum else 0.0
    blockers = [
        item.to_dict() for item in findings if not item.passed and item.severity == "blocker"
    ]
    warnings = [item.to_dict() for item in findings if not item.passed and item.severity == "warn"]
    return {
        "surface": surface.to_dict(),
        "total": total,
        "grade": _grade(total, card),
        "dimensions": dimensions,
        "findings": [item.to_dict() for item in findings],
        "blockers": blockers,
        "warnings": warnings,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
    }


def siblings_by_family(surfaces: List[Surface]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for surface in surfaces:
        if surface.kind != "mcp_tool":
            continue
        tool_name = str(surface.get("name") or "")
        grouped.setdefault(surface.family, []).append(tool_name)
    return grouped


def score_all(surfaces: List[Surface], card: dict, profile: str = "legacy") -> Dict[str, object]:
    siblings_map = siblings_by_family(surfaces)
    results = [
        score_surface(
            surface, card, siblings_map.get(surface.family) if surface.kind == "mcp_tool" else None
        )
        for surface in surfaces
    ]
    profile_cfg = (card.get("profiles") or {}).get(profile) or {}
    warn_threshold = float(profile_cfg.get("total_warn", 0))
    below = [
        {
            "surface_id": item["surface"]["surface_id"],
            "total": item["total"],
            "grade": item["grade"],
        }
        for item in results
        if item["total"] < warn_threshold
    ]
    return {
        "card_version": card.get("version"),
        "profile": profile,
        "total_warn": warn_threshold,
        "surfaces": results,
        "summary": {
            "count": len(results),
            "blockers": sum(int(item["blocker_count"]) for item in results),
            "warnings": sum(int(item["warning_count"]) for item in results),
            "average": (
                round(sum(float(item["total"]) for item in results) / len(results), 2)
                if results
                else 0.0
            ),
            "below_total_warn": below,
        },
    }
