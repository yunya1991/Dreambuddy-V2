"""把评分结果渲染为 Markdown 报告（显式 --out 才落盘）。"""

from __future__ import annotations

from typing import Dict, List


def render_markdown(payload: Dict[str, object]) -> str:
    summary = payload.get("summary") or {}
    lines: List[str] = []
    lines.append("# SkillHub 产品优化评分报告")
    lines.append("")
    lines.append("- 评分卡版本：{}".format(payload.get("card_version")))
    lines.append(
        "- profile：{}（总分告警线 {}）".format(payload.get("profile"), payload.get("total_warn"))
    )
    lines.append(
        "- 汇总：{} 个对象，平均分 {}，blocker {}，warn {}".format(
            summary.get("count", 0),
            summary.get("average", 0),
            summary.get("blockers", 0),
            summary.get("warnings", 0),
        )
    )
    lines.append("")
    lines.append(
        "> 离线分是代理指标：回答「描信号是否足够被召回」，真实选择率请用 `ab` 子命令验证。"
    )
    lines.append("")
    lines.append("## 对象明细")
    lines.append("")
    lines.append("| 对象 | 类型 | 总分 | 等级 | blocker | warn |")
    lines.append("|---|---|---|---|---|---|")
    for result in payload.get("surfaces") or []:
        surface = result["surface"]
        lines.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                surface["surface_id"],
                surface["kind"],
                result["total"],
                result["grade"],
                result["blocker_count"],
                result["warning_count"],
            )
        )
    lines.append("")
    lines.append("## 失败项")
    lines.append("")
    for result in payload.get("surfaces") or []:
        failures = [item for item in result.get("findings") or [] if not item.get("passed")]
        if not failures:
            continue
        lines.append("### {}".format(result["surface"]["surface_id"]))
        lines.append("")
        lines.append("| 规则 | 严重度 | 维度 | 问题 | 建议 |")
        lines.append("|---|---|---|---|---|")
        for item in failures:
            lines.append(
                "| {} {} | {} | {} | {} | {} |".format(
                    item["rule_id"],
                    item["title"],
                    item["severity"],
                    item["dimension"],
                    item["message"],
                    item["advice"],
                )
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
