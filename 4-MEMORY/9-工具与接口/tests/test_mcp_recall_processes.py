#!/usr/bin/env python3
"""MCP recall 返回值 processes 字段单测（设计节 3.3 + GC5 向后兼容）。

Task 16: include_process=True 时返回 processes；False 时向后兼容仅 memories+count。
M1② 同步修订（2026-11-02）：
  - 认知壳返回已包统一信封（ok/data/source/timestamp），memories/processes 位于 data 内
  - CLE mock 改为 patch cognitive_mcp_server.get_cle（_cle_instance 已不被 _get_cle 读取）
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    with (
        patch("cognitive_mcp_server.get_cle", return_value=mock_cle),
        patch("cognitive_mcp_server._get_skill_loader") as mock_loader,
    ):
        mock_loader.return_value.retrieve.return_value = {
            "meta": [_make_skill_tuple()],
            "applied": [],
        }
        result = json.loads(srv._handle_recall({"context": "写测试 tdd", "include_process": True}))
    # M1②：统一信封结构，业务数据在 data 内
    assert result["ok"] is True
    data = result["data"]
    assert "processes" in data
    assert "meta" in data["processes"]
    assert len(data["processes"]["meta"]) == 1
    assert data["processes"]["meta"][0]["skill_id"] == "tdd"
    assert "process_block_markdown" in data["processes"]


def test_recall_backward_compatible_when_include_process_false():
    """GC5：include_process=False 时返回与改造前一致（仅 memories+count）。"""
    import cognitive_mcp_server as srv

    mock_cle = MagicMock()
    mock_cle.recall.return_value = [{"id": "M1", "content": "test"}]
    with patch("cognitive_mcp_server.get_cle", return_value=mock_cle):
        result = json.loads(srv._handle_recall({"context": "test", "include_process": False}))
    assert result["ok"] is True
    data = result["data"]
    assert "memories" in data
    assert "count" in data
    assert "processes" not in data


def test_recall_default_include_process_true():
    """默认 include_process=True（设计节 3.3）。"""
    import cognitive_mcp_server as srv

    mock_cle = MagicMock()
    mock_cle.recall.return_value = []
    with (
        patch("cognitive_mcp_server.get_cle", return_value=mock_cle),
        patch("cognitive_mcp_server._get_skill_loader") as mock_loader,
    ):
        mock_loader.return_value.retrieve.return_value = {"meta": [], "applied": []}
        result = json.loads(srv._handle_recall({"context": "test"}))
    assert result["ok"] is True
    assert "processes" in result["data"]
