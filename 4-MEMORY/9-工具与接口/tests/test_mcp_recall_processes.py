#!/usr/bin/env python3
"""MCP recall 返回值 processes 字段单测（设计节 3.3 + GC5 向后兼容）。

Task 16: include_process=True 时返回 processes；False 时向后兼容仅 memories+count。
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_SCRIPT_DIR = Path(__file__).parent
_PARENT = _SCRIPT_DIR.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))


def _make_skill_tuple(skill_id="tdd", display_name="TDD", score=0.8):
    """模拟 SkillLoader.retrieve 返回的元组格式 (SuperpowersSkill, float, str)。"""
    from cognitive_superpowers import SuperpowersSkill
    sk = SuperpowersSkill(
        skill_id=skill_id,
        display_name=display_name,
        description="test desc",
        version="v1",
        raw_skill_md="",
        hard_gates=["gate1"],
        checklists=["cl1"],
        trigger_keywords=[],
        supplement=None,
        md5_of_base="x",
        localized=False,
    )
    return (sk, score, "matched tdd keyword")


def test_recall_returns_processes_field():
    import cognitive_mcp_server as srv
    mock_cle = MagicMock()
    mock_cle.recall.return_value = [{"id": "M1", "content": "test", "quality_level": "B"}]
    srv._cle_instance = mock_cle
    with patch("cognitive_mcp_server._get_skill_loader") as mock_loader:
        mock_loader.return_value.retrieve.return_value = {
            "meta": [_make_skill_tuple()],
            "applied": [],
        }
        result = json.loads(srv._handle_recall({"context": "写测试 tdd", "include_process": True}))
    assert "processes" in result
    assert "meta" in result["processes"]
    assert len(result["processes"]["meta"]) == 1
    assert result["processes"]["meta"][0]["skill_id"] == "tdd"
    assert "process_block_markdown" in result["processes"]


def test_recall_backward_compatible_when_include_process_false():
    """GC5：include_process=False 时返回与改造前一致（仅 memories+count）。"""
    import cognitive_mcp_server as srv
    mock_cle = MagicMock()
    mock_cle.recall.return_value = [{"id": "M1", "content": "test"}]
    srv._cle_instance = mock_cle
    result = json.loads(srv._handle_recall({"context": "test", "include_process": False}))
    assert "memories" in result
    assert "count" in result
    assert "processes" not in result


def test_recall_default_include_process_true():
    """默认 include_process=True（设计节 3.3）。"""
    import cognitive_mcp_server as srv
    mock_cle = MagicMock()
    mock_cle.recall.return_value = []
    srv._cle_instance = mock_cle
    with patch("cognitive_mcp_server._get_skill_loader") as mock_loader:
        mock_loader.return_value.retrieve.return_value = {"meta": [], "applied": []}
        result = json.loads(srv._handle_recall({"context": "test"}))
    assert "processes" in result
