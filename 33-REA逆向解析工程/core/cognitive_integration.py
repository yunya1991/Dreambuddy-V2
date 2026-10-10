"""认知记忆集成 — 将逆向分析结果接入认知记忆系统。

设计原则：
- 分析结果格式化为认知记忆内容（供 record 工具使用）
- 不直接调用 MCP（由调用方/Agent 执行 record）
- 记忆内容包含：目标 + 四阶段摘要 + Evidence 统计 + known_gaps
- tags 标注分析类型，便于后续 recall 检索

调用方式：
    investigation = investigate(target)
    params = prepare_record_params(investigation)
    # Agent 调用: record(content=params["content"], quality_level=params["quality_level"], tags=params["tags"])
"""

from __future__ import annotations

from typing import Any


def prepare_memory_content(investigation: dict[str, Any]) -> str:
    """将调查结果格式化为认知记忆内容字符串。

    Args:
        investigation: investigate() 返回的完整调查报告

    Returns:
        格式化的记忆内容字符串
    """
    target = investigation.get("target", "?")
    feature = investigation.get("feature", "")
    summary = investigation.get("summary", "")
    phases = investigation.get("phases", {})
    evidence_list = investigation.get("evidence", [])
    known_gaps = investigation.get("known_gaps", [])

    # 统计 Evidence 层级分布
    level_counts: dict[str, int] = {}
    for e in evidence_list:
        level = e.level.value if hasattr(e.level, "value") else str(e.level)
        level_counts[level] = level_counts.get(level, 0) + 1

    # 提取各阶段关键信息
    locate = phases.get("locate", {})
    trace = phases.get("trace", {})
    reduce = phases.get("reduce", {})

    lines: list[str] = []
    lines.append(f"[33-REA 逆向分析结果 {target}]")

    if feature:
        lines.append(f"功能: {feature}")

    lines.append(f"摘要: {summary}")
    lines.append("")
    lines.append("阶段结果:")
    lines.append(
        f"  定位(Locate): {locate.get('language', '?')} "
        f"{locate.get('target_type', '?')} | "
        f"{len(locate.get('modules', []))} 模块 | "
        f"{len(locate.get('entry_points', []))} 入口"
    )
    lines.append(
        f"  追踪(Trace): "
        f"{len(trace.get('all_functions', []))} 函数, "
        f"{len(trace.get('callers', {}))} 调用关系"
    )
    lines.append(
        f"  还原(Reduce): "
        f"{len(reduce.get('functions', []))} 函数分析, "
        f"{len(reduce.get('patterns', []))} 算法模式"
    )

    lines.append("")
    lines.append(f"Evidence 统计: {len(evidence_list)} 条")
    for level, count in sorted(level_counts.items()):
        lines.append(f"  {level}: {count}")

    if known_gaps:
        lines.append("")
        lines.append(f"已知局限 ({len(known_gaps)}):")
        for gap in known_gaps[:10]:  # 最多列 10 条
            lines.append(f"  - {gap}")
        if len(known_gaps) > 10:
            lines.append(f"  ... 共 {len(known_gaps)} 条")

    return "\n".join(lines)


def prepare_record_params(investigation: dict[str, Any]) -> dict[str, Any]:
    """准备认知记忆 record() 调用参数。

    Args:
        investigation: investigate() 返回的完整调查报告

    Returns:
        {
            "content": str,
            "quality_level": "B",
            "tags": str (逗号分隔),
        }
    """
    content = prepare_memory_content(investigation)

    # 构建标签
    phases = investigation.get("phases", {})
    locate = phases.get("locate", {})
    language = locate.get("language", "unknown")

    tags_list = [
        "33-REA",
        "逆向分析",
        "investigation",
        "认知记忆",
        f"language:{language}",
    ]

    feature = investigation.get("feature")
    if feature:
        tags_list.append(f"feature:{feature[:20]}")

    return {
        "content": content,
        "quality_level": "B",
        "tags": ",".join(tags_list),
    }


class CognitiveIntegration:
    """认知记忆集成器 — 将逆向分析结果转换为认知记忆格式。

    用法：
        ci = CognitiveIntegration()
        params = ci.to_record_params(investigation_result)
        # 由 Agent 调用 record(content=params["content"], ...)
    """

    def to_record_params(self, investigation: dict[str, Any]) -> dict[str, Any]:
        """将调查结果转换为 record 参数。"""
        return prepare_record_params(investigation)

    def to_memory_content(self, investigation: dict[str, Any]) -> str:
        """将调查结果转换为记忆内容字符串。"""
        return prepare_memory_content(investigation)

    @staticmethod
    def should_record(investigation: dict[str, Any]) -> bool:
        """判断调查结果是否值得记录到认知记忆。

        规则：
        - 至少有 1 条 Evidence
        - 调查成功完成（有 summary）
        - 非无效目标
        """
        if not investigation.get("summary"):
            return False
        if not investigation.get("evidence"):
            return False
        phases = investigation.get("phases", {})
        locate = phases.get("locate", {})
        if not locate.get("valid", True):
            return False
        return True
