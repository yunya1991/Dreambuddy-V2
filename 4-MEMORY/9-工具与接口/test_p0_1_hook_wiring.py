"""P0-1 接线 TDD RED 测试

验证 cognitive_mcp_server._handle_record / _handle_verify
调用 skill_indexer.record_hook / verify_hook 建立 skill↔memory 双向关联。

RED 契约：
  - _handle_record 响应应包含 skill_links 字段（record_hook 结果列表）
  - _handle_verify 响应应包含 skill_hooks 字段（verify_hook 结果列表）
  - skill_indexer 不可用时 FAIL-OPEN（字段为空列表，主流程不中断）

参考：SPEC-CognitiveSystem-Evolution.md §2.2.1 P0-1
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest


# ─────────────────────────────── RED: _handle_record ───────────────────────────────

def test_handle_record_returns_skill_links_field():
    """RED: _handle_record 响应应包含 skill_links 字段。
    当前未接线 record_hook → 字段不存在 → 断言失败。
    """
    from cognitive_mcp_server import _handle_record
    with patch("cognitive_mcp_server._get_cle") as mock_cle:
        mock_cle.return_value.record.return_value = "VM-TEST-RECORD"
        result = json.loads(_handle_record({
            "content": "测试经验",
            "tags": "doc-sync",
        }))
    assert "skill_links" in result, (
        "P0-1 RED: _handle_record 响应应包含 skill_links 字段（record_hook 结果）"
    )


def test_handle_record_skill_links_populated_when_skill_indexer_available():
    """RED: 当 skill_indexer 可用且 triggered_skills 非空时，
    skill_links 应包含 record_hook 调用结果。
    """
    from cognitive_mcp_server import _handle_record
    fake_hook_result = {"skill_id": "dream-doc-sync-workflow",
                        "memory_id": "VM-TEST", "linked": True,
                        "written": False, "apply_count_incremented": False}
    fake_si = MagicMock()
    fake_si.record_hook.return_value = fake_hook_result
    with patch("cognitive_mcp_server._get_cle") as mock_cle, \
         patch("cognitive_mcp_server._load_skill_indexer", return_value=fake_si), \
         patch("cognitive_mcp_server._find_skill_dir_by_name", return_value=None):
        mock_cle.return_value.record.return_value = "VM-TEST"
        result = json.loads(_handle_record({
            "content": "测试", "tags": "doc-sync",
        }))
    assert result["skill_links"], "skill_links 非空"
    assert result["skill_links"][0]["skill_id"] == "dream-doc-sync-workflow"
    # record_hook 被调用，传入了 skill_id + memory_id
    fake_si.record_hook.assert_called_once()


def test_handle_record_fail_open_when_skill_indexer_unavailable():
    """FAIL-OPEN: skill_indexer 不可用时，record 仍正常返回，skill_links 为空列表。"""
    from cognitive_mcp_server import _handle_record
    with patch("cognitive_mcp_server._get_cle") as mock_cle, \
         patch("cognitive_mcp_server._load_skill_indexer", return_value=None):
        mock_cle.return_value.record.return_value = "VM-TEST-FAIL"
        result = json.loads(_handle_record({"content": "x", "tags": ""}))
    assert result["memory_id"] == "VM-TEST-FAIL"
    assert result["skill_links"] == []


# ─────────────────────────────── RED: _handle_verify ───────────────────────────────

def test_handle_verify_returns_skill_hooks_field():
    """RED: _handle_verify 响应应包含 skill_hooks 字段。
    当前未接线 verify_hook → 字段不存在 → 断言失败。
    """
    from cognitive_mcp_server import _handle_verify
    with patch("cognitive_mcp_server._get_cle") as mock_cle:
        mock_cle.return_value.verify.return_value = {"ok": True, "confidence": 0.5}
        result = json.loads(_handle_verify({
            "memory_id": "VM-TEST-VERIFY",
            "success": True,
        }))
    assert "skill_hooks" in result, (
        "P0-1 RED: _handle_verify 响应应包含 skill_hooks 字段（verify_hook 结果）"
    )


def test_handle_verify_skill_hooks_populated_when_skill_has_cognitive_link():
    """RED: 当 memory_id 关联了 SKILL（cognitive_links 包含该 memory_id）时，
    skill_hooks 应包含 verify_hook 调用结果。
    """
    from cognitive_mcp_server import _handle_verify
    # 构造一个 fake SkillEntry，cognitive_links 包含目标 memory_id
    fake_entry = MagicMock()
    fake_entry.name = "dream-test-skill"
    fake_entry.cognitive_links = ["VM-TEST-VERIFY"]
    fake_entry.status = "shadow"
    fake_entry.confidence = 0.6
    fake_entry.apply_count = 1
    fake_hook_result = {"skill_id": "dream-test-skill", "suggested": "shadow→active",
                        "lifecycle_written": False, "confidence_updated": True}
    fake_si = MagicMock()
    fake_si.scan_skills.return_value = [fake_entry]
    fake_si.verify_hook.return_value = fake_hook_result
    with patch("cognitive_mcp_server._get_cle") as mock_cle, \
         patch("cognitive_mcp_server._load_skill_indexer", return_value=fake_si), \
         patch("cognitive_mcp_server._find_skill_dir_by_name", return_value=None):
        mock_cle.return_value.verify.return_value = {"ok": True}
        result = json.loads(_handle_verify({
            "memory_id": "VM-TEST-VERIFY", "success": True,
        }))
    assert result["skill_hooks"], "skill_hooks 非空"
    fake_si.verify_hook.assert_called_once()


def test_handle_verify_fail_open_when_skill_indexer_unavailable():
    """FAIL-OPEN: skill_indexer 不可用时，verify 仍正常返回，skill_hooks 为空列表。"""
    from cognitive_mcp_server import _handle_verify
    with patch("cognitive_mcp_server._get_cle") as mock_cle, \
         patch("cognitive_mcp_server._load_skill_indexer", return_value=None):
        mock_cle.return_value.verify.return_value = {"ok": True, "confidence": 0.5}
        result = json.loads(_handle_verify({
            "memory_id": "VM-TEST", "success": True,
        }))
    assert result.get("ok") is True
    assert result["skill_hooks"] == []


def test_handle_verify_fail_open_when_no_skill_linked():
    """FAIL-OPEN: memory_id 未关联任何 SKILL 时，skill_hooks 为空，不报错。"""
    from cognitive_mcp_server import _handle_verify
    fake_si = MagicMock()
    fake_si.scan_skills.return_value = []  # 无任何 SKILL
    with patch("cognitive_mcp_server._get_cle") as mock_cle, \
         patch("cognitive_mcp_server._load_skill_indexer", return_value=fake_si):
        mock_cle.return_value.verify.return_value = {"ok": True}
        result = json.loads(_handle_verify({
            "memory_id": "VM-NO-LINK", "success": True,
        }))
    assert result["skill_hooks"] == []
