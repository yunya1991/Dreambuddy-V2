"""TAG_HOOKS 自动触发机制测试（RED 阶段）。

SPEC: 1-ARCHITECTURE/SPEC-20260930-COGNITIVE-TAG-HOOKS-AUTO-LOOP.md

测试 _resolve_triggered_skills 和 _handle_record 的 TAG_HOOKS 逻辑：
- tag 精确匹配 → 返回对应 skill
- 多 tag 叠加 → 返回所有匹配 skill
- 去重 → 同一 skill 只返回一次
- 无匹配 → 返回空列表
- FAIL-OPEN → 异常不阻塞
"""
import json
import os
import sys
from unittest.mock import patch, MagicMock
import pytest

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_SCRIPT_DIR)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)


# ============================================================
# T1-T8: _resolve_triggered_skills 单元测试
# ============================================================

def test_t1_tag_hooks_doc_sync():
    """T1: tags=['doc-sync'] → triggered_skills == ['dream-doc-sync-workflow']"""
    from cognitive_mcp_server import _resolve_triggered_skills
    result = _resolve_triggered_skills(["doc-sync"])
    assert result == ["dream-doc-sync-workflow"]


def test_t2_tag_hooks_wiki_compile():
    """T2: tags=['wiki-compile'] → triggered_skills == ['wiki-ingest-trigger']"""
    from cognitive_mcp_server import _resolve_triggered_skills
    result = _resolve_triggered_skills(["wiki-compile"])
    assert result == ["wiki-ingest-trigger"]


def test_t3_tag_hooks_hermes_reflection():
    """T3: tags=['hermes反思'] → triggered_skills == ['dream-self-iteration-workflow']"""
    from cognitive_mcp_server import _resolve_triggered_skills
    result = _resolve_triggered_skills(["hermes反思"])
    assert result == ["dream-self-iteration-workflow"]


def test_t4_tag_hooks_skill_creation():
    """T4: tags=['SKILL'] → triggered_skills == ['skill-creator']"""
    from cognitive_mcp_server import _resolve_triggered_skills
    result = _resolve_triggered_skills(["SKILL"])
    assert result == ["skill-creator"]


def test_t5_tag_hooks_hard_constraint():
    """T5: tags=['硬约束'] → triggered_skills == ['dream-arch-collaboration-workflow']"""
    from cognitive_mcp_server import _resolve_triggered_skills
    result = _resolve_triggered_skills(["硬约束"])
    assert result == ["dream-arch-collaboration-workflow"]


def test_t6_tag_hooks_multi_tag():
    """T6: tags=['doc-sync','hermes反思'] → 两个 skill 都触发"""
    from cognitive_mcp_server import _resolve_triggered_skills
    result = _resolve_triggered_skills(["doc-sync", "hermes反思"])
    assert "dream-doc-sync-workflow" in result
    assert "dream-self-iteration-workflow" in result
    assert len(result) == 2


def test_t7_tag_hooks_no_match():
    """T7: tags=['普通经验','交易域'] → triggered_skills == []"""
    from cognitive_mcp_server import _resolve_triggered_skills
    result = _resolve_triggered_skills(["普通经验", "交易域"])
    assert result == []


def test_t8_tag_hooks_empty_tags():
    """T8: tags=[] → triggered_skills == []"""
    from cognitive_mcp_server import _resolve_triggered_skills
    result = _resolve_triggered_skills([])
    assert result == []


# ============================================================
# T9: FAIL-OPEN 测试
# ============================================================

def test_t9_tag_hooks_fail_open():
    """T9: _resolve_triggered_skills 遇到异常 → 返回空列表，不崩溃"""
    from cognitive_mcp_server import _resolve_triggered_skills
    # 传入非预期类型触发异常
    result = _resolve_triggered_skills(None)  # type: ignore
    assert result == []


def test_t9b_handle_record_fail_open_on_hook():
    """T9b: _handle_record 中 TAG_HOOKS 异常不阻塞 record 返回"""
    from cognitive_mcp_server import _handle_record
    # Mock CLE 的 record 返回正常 memory_id
    mock_cle = MagicMock()
    mock_cle.record.return_value = "VM-test-fail-open"
    with patch("cognitive_mcp_server._get_cle", return_value=mock_cle):
        # 即使传入异常 tags，record 仍应正常返回
        resp = _handle_record({
            "content": "test",
            "tags": None,  # 异常输入
        })
        data = json.loads(resp)
        assert data["memory_id"] == "VM-test-fail-open"
        assert data["status"] == "recorded"
        assert "triggered_skills" in data


# ============================================================
# T10: 去重测试
# ============================================================

def test_t10_tag_hooks_dedup():
    """T10: 两个 tag 映射同一 skill → triggered_skills 去重"""
    from cognitive_mcp_server import _resolve_triggered_skills, TAG_HOOKS
    # 临时扩展 TAG_HOOKS 添加两个 tag 映射同一 skill
    with patch.dict(TAG_HOOKS, {
        "tag-a": ["dream-doc-sync-workflow"],
        "tag-b": ["dream-doc-sync-workflow"],
    }):
        result = _resolve_triggered_skills(["tag-a", "tag-b"])
        assert result == ["dream-doc-sync-workflow"]  # 去重，只有一个


# ============================================================
# 集成测试：_handle_record 返回 triggered_skills
# ============================================================

def test_integration_handle_record_returns_triggered_skills():
    """集成: _handle_record(tags='doc-sync') → response 含 triggered_skills"""
    from cognitive_mcp_server import _handle_record
    mock_cle = MagicMock()
    mock_cle.record.return_value = "VM-integration-test"
    with patch("cognitive_mcp_server._get_cle", return_value=mock_cle):
        resp = _handle_record({
            "content": "测试 doc-sync 触发",
            "tags": "doc-sync",
            "quality_level": "B",
        })
        data = json.loads(resp)
        assert data["memory_id"] == "VM-integration-test"
        assert data["status"] == "recorded"
        assert data["triggered_skills"] == ["dream-doc-sync-workflow"]


def test_integration_handle_record_no_trigger():
    """集成: _handle_record(tags='普通') → triggered_skills 为空"""
    from cognitive_mcp_server import _handle_record
    mock_cle = MagicMock()
    mock_cle.record.return_value = "VM-no-trigger"
    with patch("cognitive_mcp_server._get_cle", return_value=mock_cle):
        resp = _handle_record({
            "content": "普通经验",
            "tags": "普通经验,交易域",
        })
        data = json.loads(resp)
        assert data["triggered_skills"] == []
