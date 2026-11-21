"""把失败项转成可执行改写建议（规则驱动，不调用模型）。"""

from __future__ import annotations

from typing import Dict, List

from .rules import SEVERITY_RANK


def advise(payload: Dict[str, object], min_severity: str = "info") -> List[Dict[str, object]]:
    floor = SEVERITY_RANK.get(min_severity, 1)
    items: List[Dict[str, object]] = []
    for result in payload.get("surfaces") or []:
        surface = result["surface"]
        for finding in result.get("findings") or []:
            if finding.get("passed"):
                continue
            severity = str(finding.get("severity") or "info")
            if SEVERITY_RANK.get(severity, 0) < floor:
                continue
            items.append(
                {
                    "surface_id": surface["surface_id"],
                    "kind": surface["kind"],
                    "path": surface["path"],
                    "rule_id": finding["rule_id"],
                    "title": finding["title"],
                    "severity": severity,
                    "weight": finding["weight"],
                    "problem": finding["message"],
                    "advice": finding["advice"],
                    "evidence": finding["evidence"],
                }
            )
    items.sort(
        key=lambda item: (
            -SEVERITY_RANK.get(str(item["severity"]), 0),
            -float(item["weight"]),
            str(item["surface_id"]),
            str(item["rule_id"]),
        )
    )
    return items


def render_text(items: List[Dict[str, object]]) -> str:
    if not items:
        return "没有需要改写的项。"
    lines = ["建议清单（按严重度与权重排序）："]
    for index, item in enumerate(items, start=1):
        lines.append(
            "{}. [{}] {} · {}（{}）".format(
                index, item["severity"], item["surface_id"], item["title"], item["rule_id"]
            )
        )
        lines.append("   问题：{}".format(item["problem"]))
        lines.append("   建议：{}".format(item["advice"]))
        evidence = item.get("evidence") or {}
        if evidence:
            lines.append("   证据：{}".format(evidence))
    return "\n".join(lines)
