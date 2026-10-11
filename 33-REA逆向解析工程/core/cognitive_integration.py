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
            "evidence_entries": list[dict],  # P1-L1-3: 供 Agent 写入 Evidence Ledger
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

    # P1-L1-3: 将 33-REA Evidence 转换为 EvidenceEntry dict 列表
    # SPEC §3.3：33-REA 的每条分析结论直接写入 Evidence Ledger
    evidence_entries = _convert_evidence_to_entries(investigation)

    return {
        "content": content,
        "quality_level": "B",
        "tags": ",".join(tags_list),
        "evidence_entries": evidence_entries,
    }


def _convert_evidence_to_entries(investigation: dict[str, Any]) -> list[dict[str, Any]]:
    """将 33-REA Evidence 列表转换为 EvidenceEntry dict 列表。

    每个 dict 可被 EvidenceEntry(**dict) 构造。
    SPEC §3.3：33-REA 的每条分析结论直接写入 Evidence Ledger。

    字段映射：
      subject: "33-REA"（固定标识来源系统）
      relation: evidence.content 提取的关系（或默认 "分析了"）
      object: evidence.content（结论内容）
      source: evidence.source 或 evidence.provenance
      confidence: evidence.confidence
      level: evidence.level.value
    """
    evidence_list = investigation.get("evidence", [])
    target = investigation.get("target", "unknown")

    entries: list[dict[str, Any]] = []
    for e in evidence_list:
        # 提取 level（可能是 Enum 或字符串）
        level = e.level.value if hasattr(e.level, "value") else str(e.level)

        # 提取 source（优先 provenance，其次 source）
        source = getattr(e, "provenance", None) or getattr(e, "source", "") or "33-REA"

        # content 作为 object（结论内容）
        obj = getattr(e, "content", "") or str(e)

        entries.append({
            "subject": "33-REA",
            "relation": "分析了",
            "object": obj,
            "source": f"33-REA:{source}",
            "confidence": float(getattr(e, "confidence", 0.5)),
            "level": level,
        })

    return entries


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


# ==================================================================
# PoE 扩展（Task 6）— 决策/方法论/审计的 record 参数生成
# ==================================================================

def prepare_decision_record_params(decision_result: dict[str, Any]) -> dict[str, Any]:
    """将设计决策还原结果格式化为 record() 调用参数。

    Args:
        decision_result: recover_decisions() 返回结果，含 decisions 列表

    Returns:
        {content, quality_level, tags}
    """
    target = decision_result.get("target", "?")
    decisions = decision_result.get("decisions", [])
    evidence_list = decision_result.get("evidence", [])

    lines: list[str] = []
    lines.append(f"[REA 设计决策还原 {target}]")
    lines.append(f"决策数: {len(decisions)}")
    lines.append("")

    for i, d in enumerate(decisions, 1):
        decision_text = d.get("decision", "") if isinstance(d, dict) else str(d)
        context_text = d.get("context", "") if isinstance(d, dict) else ""
        consequences = d.get("consequences", []) if isinstance(d, dict) else []
        alternatives = d.get("alternatives", []) if isinstance(d, dict) else []

        lines.append(f"{i}. {decision_text}")
        if context_text:
            lines.append(f"   上下文: {context_text}")
        if consequences:
            lines.append(f"   影响: {'; '.join(consequences)}")
        if alternatives:
            for alt in alternatives:
                alt_text = alt.get("result", "") if isinstance(alt, dict) else str(alt)
                lines.append(f"   替代方案: {alt_text}")
        lines.append("")

    # Evidence 摘要
    level_counts: dict[str, int] = {}
    for e in evidence_list:
        level = e.level.value if hasattr(e.level, "value") else str(e.level)
        level_counts[level] = level_counts.get(level, 0) + 1
    if level_counts:
        lines.append(f"Evidence 统计: {len(evidence_list)} 条")
        for level, count in sorted(level_counts.items()):
            lines.append(f"  {level}: {count}")

    tags = "rea-decision,33-REA,设计决策,PoE"
    if target:
        tags += f",target:{str(target)[-30:]}"

    return {
        "content": "\n".join(lines),
        "quality_level": "B",
        "tags": tags,
    }


def prepare_methodology_record_params(methodology_result: dict[str, Any]) -> dict[str, Any]:
    """将方法论抽象结果格式化为 record() 调用参数。

    Args:
        methodology_result: abstract_methodology() 返回结果，含 methodologies 列表

    Returns:
        {content, quality_level, tags}
    """
    methodologies = methodology_result.get("methodologies", [])
    evidence_list = methodology_result.get("evidence", [])

    lines: list[str] = []
    lines.append("[REA 方法论抽象结果]")
    lines.append(f"方法论数: {len(methodologies)}")
    lines.append("")

    for i, m in enumerate(methodologies, 1):
        problem = m.get("problem_pattern", "")
        solution = m.get("solution_pattern", "")
        applicability = m.get("applicability", [])
        known_gaps = m.get("known_gaps", [])
        source_projects = m.get("source_projects", [])

        lines.append(f"{i}. 问题模式: {problem}")
        lines.append(f"   解法模式: {solution}")
        if applicability:
            lines.append(f"   适用条件: {'; '.join(applicability)}")
        if source_projects:
            lines.append(f"   来源项目: {', '.join(source_projects)}")
        if known_gaps:
            lines.append(f"   已知局限: {'; '.join(known_gaps)}")
        lines.append("")

    if evidence_list:
        lines.append(f"Evidence 统计: {len(evidence_list)} 条")

    tags = "rea-methodology,33-REA,方法论,PoE"

    return {
        "content": "\n".join(lines),
        "quality_level": "B",
        "tags": tags,
    }


def prepare_audit_record_params(audit_result: dict[str, Any]) -> dict[str, Any]:
    """将 AI 审计结果格式化为 record() 调用参数。

    Args:
        audit_result: audit_ai_output() 返回结果

    Returns:
        {content, quality_level, tags}
    """
    target = audit_result.get("target", "?")
    evi_score = audit_result.get("evidence_chain_score", 0.0)
    cov_score = audit_result.get("coverage_score", 0.0)
    complexity = audit_result.get("complexity_penalty", 0.0)
    poe_score = audit_result.get("poe_score", 0.0)
    gate = audit_result.get("gate_decision", "review")
    debts = audit_result.get("cognitive_debt", [])
    audit_layer = audit_result.get("audit_layer_status", {})

    lines: list[str] = []
    lines.append(f"[PoE AI 产出审计 {target}]")
    lines.append(f"门禁决策: {gate.upper()}")
    lines.append(f"poe_score: {poe_score:.3f}")
    lines.append(f"证据链完整度: {evi_score:.3f}")
    lines.append(f"覆盖率: {cov_score:.3f}")
    lines.append(f"复杂度惩罚: {complexity:.3f}")
    if audit_layer:
        lines.append(
            f"证明链层: Decision={audit_layer.get('design_decision', False)}, "
            f"Narrative={audit_layer.get('narrative', False)}, "
            f"Methodology={audit_layer.get('methodology', False)}"
        )
    lines.append("")

    # 债务摘要
    lines.append(f"认知债务: {len(debts)} 条")
    for i, d in enumerate(debts, 1):
        dtype = d.get("type", "") if isinstance(d, dict) else ""
        desc = d.get("description", "") if isinstance(d, dict) else str(d)
        lines.append(f"  {i}. [{dtype}] {desc}")

    # quality_level：pass→A，review→B，reject→C
    quality_map = {"pass": "A", "review": "B", "reject": "C"}
    quality_level = quality_map.get(gate, "B")

    tags = "rea-audit,33-REA,PoE,ai-audit"
    if gate:
        tags += f",gate:{gate}"

    return {
        "content": "\n".join(lines),
        "quality_level": quality_level,
        "tags": tags,
    }
