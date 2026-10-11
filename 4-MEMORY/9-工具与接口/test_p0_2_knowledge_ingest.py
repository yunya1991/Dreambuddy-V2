"""P0-2 record → RAG 向量化 TDD RED 测试

验证 cognitive_mcp_server._handle_record 对 tags 含 "knowledge-ingest" 的记忆
返回 knowledge_ingest_required 硬标记，区别于 triggered_skills 软触发。

SPEC: SPEC-CognitiveSystem-Evolution.md §2.2.2 P0-2
现状: 新记忆只入认知库，知识库 RAG 检索不到最新经验
修复: _handle_record 对 tags 含 knowledge-ingest 的记忆强制标记，Agent 层执行 knowledge-ingest SKILL
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest


# ─────────────────────────────── RED: knowledge_ingest_required 标记 ───────────────────────────────

def test_handle_record_knowledge_ingest_required_when_tag_present():
    """RED: tags 含 'knowledge-ingest' 时，响应应包含 knowledge_ingest_required=True。
    当前未实现 → 字段不存在 → 断言失败。
    """
    from cognitive_mcp_server import _handle_record
    with patch("cognitive_mcp_server._get_cle") as mock_cle:
        mock_cle.return_value.record.return_value = "VM-TEST-KI"
        result = json.loads(_handle_record({
            "content": "调研结论：马丁策略在震荡市夏普优于趋势市",
            "tags": "knowledge-ingest,调研,马丁策略",
        }))
    assert result.get("knowledge_ingest_required") is True, (
        "P0-2 RED: tags 含 knowledge-ingest 时应返回 knowledge_ingest_required=True"
    )


def test_handle_record_knowledge_ingest_not_required_when_tag_absent():
    """RED: tags 不含 'knowledge-ingest' 时，knowledge_ingest_required 应为 False。"""
    from cognitive_mcp_server import _handle_record
    with patch("cognitive_mcp_server._get_cle") as mock_cle:
        mock_cle.return_value.record.return_value = "VM-TEST-NO-KI"
        result = json.loads(_handle_record({
            "content": "普通经验记录",
            "tags": "bugfix,mcp",
        }))
    assert result.get("knowledge_ingest_required") is False, (
        "P0-2: tags 不含 knowledge-ingest 时 knowledge_ingest_required 应为 False"
    )


def test_handle_record_knowledge_ingest_required_field_exists_always():
    """RED: knowledge_ingest_required 字段应始终存在（True 或 False），不缺失。"""
    from cognitive_mcp_server import _handle_record
    with patch("cognitive_mcp_server._get_cle") as mock_cle:
        mock_cle.return_value.record.return_value = "VM-TEST-FIELD"
        result = json.loads(_handle_record({
            "content": "无 tags 的记录",
            "tags": "",
        }))
    assert "knowledge_ingest_required" in result, (
        "P0-2: knowledge_ingest_required 字段应始终存在"
    )


def test_handle_record_knowledge_ingest_mark_distinct_from_triggered_skills():
    """RED: knowledge_ingest_required 是硬标记，独立于 triggered_skills 软触发。
    即使 triggered_skills 已包含 knowledge-ingest（TAG_HOOKS 映射），
    knowledge_ingest_required 仍需作为独立布尔字段存在。
    """
    from cognitive_mcp_server import _handle_record
    with patch("cognitive_mcp_server._get_cle") as mock_cle:
        mock_cle.return_value.record.return_value = "VM-TEST-DISTINCT"
        result = json.loads(_handle_record({
            "content": "调研经验",
            "tags": "knowledge-ingest",
        }))
    # triggered_skills 是软触发（列表），knowledge_ingest_required 是硬标记（布尔）
    assert isinstance(result.get("knowledge_ingest_required"), bool)
    assert "knowledge-ingest" in result.get("triggered_skills", [])


def test_handle_record_knowledge_ingest_required_preserves_main_flow():
    """FAIL-OPEN: knowledge_ingest_required 标记不影响 record 主流程字段。"""
    from cognitive_mcp_server import _handle_record
    with patch("cognitive_mcp_server._get_cle") as mock_cle:
        mock_cle.return_value.record.return_value = "VM-TEST-PRESERVE"
        result = json.loads(_handle_record({
            "content": "测试",
            "tags": "knowledge-ingest",
        }))
    # 主流程字段仍存在
    assert result["memory_id"] == "VM-TEST-PRESERVE"
    assert result["status"] == "recorded"
    assert "triggered_skills" in result
    assert "skill_links" in result  # P0-1 字段
    # P0-2 新增字段
    assert result["knowledge_ingest_required"] is True
