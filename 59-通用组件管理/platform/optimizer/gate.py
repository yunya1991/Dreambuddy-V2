"""发布门禁：blocker 硬阻断，总分只告警。"""

from __future__ import annotations

from typing import Dict, List


def enforced_severities(card: dict, profile: str) -> List[str]:
    profile_cfg = (card.get("profiles") or {}).get(profile) or {}
    return list(profile_cfg.get("enforce") or ["blocker"])


def blocking_findings(
    payload: Dict[str, object], card: dict, profile: str
) -> List[Dict[str, object]]:
    enforced = set(enforced_severities(card, profile))
    blocked: List[Dict[str, object]] = []
    for result in payload.get("surfaces") or []:
        surface = result["surface"]
        for finding in result.get("findings") or []:
            if finding.get("passed"):
                continue
            if str(finding.get("severity")) not in enforced:
                continue
            blocked.append(
                {
                    "surface_id": surface["surface_id"],
                    "kind": surface["kind"],
                    "path": surface["path"],
                    "rule_id": finding["rule_id"],
                    "title": finding["title"],
                    "message": finding["message"],
                    "advice": finding["advice"],
                }
            )
    return blocked


def exit_code(blocked: List[Dict[str, object]]) -> int:
    return 1 if blocked else 0


def render_text(blocked: List[Dict[str, object]], payload: Dict[str, object], profile: str) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "发布门禁（profile={}）：{} 个评分对象，平均分 {}，blocker {} 项，warn {} 项".format(
            profile,
            summary.get("count", 0),
            summary.get("average", 0),
            summary.get("blockers", 0),
            summary.get("warnings", 0),
        )
    ]
    if blocked:
        lines.append("阻断项：")
        for index, item in enumerate(blocked, start=1):
            lines.append(
                "  {}. [{}] {} · {}".format(
                    index, item["rule_id"], item["surface_id"], item["title"]
                )
            )
            lines.append("     问题：{}".format(item["message"]))
            lines.append("     建议：{}".format(item["advice"]))
    else:
        lines.append("通过：没有命中 blocker。")
    below = summary.get("below_total_warn") or []
    if below:
        lines.append("总分告警（不阻断）：")
        for item in below:
            lines.append(
                "  - {} 总分 {}（{} 级）".format(item["surface_id"], item["total"], item["grade"])
            )
    lines.append("提示：离线分是代理指标，真实选择率请用 ab 子命令验证。")
    return "\n".join(lines)
