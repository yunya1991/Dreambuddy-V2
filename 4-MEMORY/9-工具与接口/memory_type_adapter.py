"""Memory Type Adapter — 认知记忆类型分层适配。

基于 CoALA 4 层记忆模型（working/episodic/semantic/procedural），
为认知记忆增加 type 字段，支持类型推断和过滤。

工程约束：HC-1a（独立模块，不修改认知核心）/ FAIL-OPEN
"""
from __future__ import annotations

from typing import Any

# 记忆类型常量
TYPE_SEMANTIC = "semantic"      # 事实/规则/硬约束/偏好
TYPE_EPISODIC = "episodic"      # 事件/经历/解决路径（默认）
TYPE_PROCEDURAL = "procedural"  # 技能/工作流/方法

VALID_TYPES = {TYPE_SEMANTIC, TYPE_EPISODIC, TYPE_PROCEDURAL}

# 类型推断规则：tags 命中则映射到对应类型
_SEMANTIC_TAGS = {"硬约束", "偏好", "规则", "事实", "决策", "规范", "semantic"}
_PROCEDURAL_TAGS = {"SKILL", "skill", "工作流", "方法", "流程", "procedural", "SKILL治理"}


def infer_memory_type(tags: list[str] | None) -> str:
    """根据 tags 推断记忆类型。

    规则：
    - tags 含 procedural 关键词 → procedural
    - tags 含 semantic 关键词 → semantic
    - 否则默认 episodic

    Args:
        tags: 记忆标签列表

    Returns:
        记忆类型字符串（semantic/episodic/procedural）
    """
    if not tags:
        return TYPE_EPISODIC
    tag_set = set(tags)
    if tag_set & _PROCEDURAL_TAGS:
        return TYPE_PROCEDURAL
    if tag_set & _SEMANTIC_TAGS:
        return TYPE_SEMANTIC
    return TYPE_EPISODIC


def validate_type(mem_type: str | None) -> str:
    """验证并归一化记忆类型，无效值回退为 episodic（FAIL-OPEN）。"""
    if mem_type is None:
        return TYPE_EPISODIC
    mem_type = str(mem_type).lower().strip()
    if mem_type in VALID_TYPES:
        return mem_type
    return TYPE_EPISODIC


def filter_by_type(memories: list[dict[str, Any]], mem_type: str | None) -> list[dict[str, Any]]:
    """按记忆类型过滤。

    Args:
        memories: 记忆列表
        mem_type: 目标类型，None 表示不过滤

    Returns:
        过滤后的记忆列表。FAIL-OPEN：类型无效时返回原列表。
    """
    if mem_type is None:
        return memories
    target = validate_type(mem_type)
    if target == TYPE_EPISODIC and mem_type is not None:
        # 显式请求 episodic，只返回有 type=episodic 或无 type 的记忆
        return [m for m in memories if m.get("type", TYPE_EPISODIC) == target]
    return [m for m in memories if m.get("type", TYPE_EPISODIC) == target]


def attach_type(memory: dict[str, Any], mem_type: str | None = None,
                tags: list[str] | None = None) -> dict[str, Any]:
    """为记忆附加 type 字段。

    Args:
        memory: 记忆字典
        mem_type: 显式指定的类型，None 时根据 tags 推断
        tags: 用于推断类型的标签

    Returns:
        附加了 type 字段的记忆字典（原对象被修改并返回）
    """
    if mem_type is not None:
        memory["type"] = validate_type(mem_type)
    else:
        memory["type"] = infer_memory_type(tags or memory.get("tags", []))
    return memory
