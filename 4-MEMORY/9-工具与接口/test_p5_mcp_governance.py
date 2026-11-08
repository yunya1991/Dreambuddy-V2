"""P5 契约治理测试：写 scope / principal / 幂等 / eval gate / tool annotations。"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_skill_indexer(monkeypatch):
    """避免写真实 SKILL.md。"""
    monkeypatch.setattr(
        "cognitive_mcp_server._find_skill_dir_by_name", lambda *a, **kw: None
    )
    monkeypatch.setattr("cognitive_mcp_server._load_skill_indexer", lambda: None)


def _record(args):
    from cognitive_mcp_server import _handle_record

    return json.loads(_handle_record(args))


def test_write_scope_disabled_by_default(monkeypatch):
    monkeypatch.setenv("COGNITIVE_MCP_MODE", "ssh")
    monkeypatch.delenv("COGNITIVE_MCP_WRITE_ENABLED", raising=False)
    result = _record({"content": "x", "tags": ""})
    assert result["ok"] is False
    assert result["error_code"] == "scope_denied"


def test_worker_principal_denied(monkeypatch):
    monkeypatch.setenv("COGNITIVE_MCP_MODE", "ssh")
    monkeypatch.setenv("COGNITIVE_MCP_WRITE_ENABLED", "true")
    monkeypatch.setenv("COGNITIVE_MCP_DEFAULT_PRINCIPAL", "worker")
    result = _record({"content": "x", "tags": ""})
    assert result["ok"] is False
    assert result["error_code"] == "principal_denied"


def test_admin_principal_allowed_and_eval_gate_shadow(monkeypatch):
    monkeypatch.setenv("COGNITIVE_MCP_MODE", "ssh")
    monkeypatch.setenv("COGNITIVE_MCP_WRITE_ENABLED", "true")
    monkeypatch.setenv("COGNITIVE_MCP_DEFAULT_PRINCIPAL", "admin")
    monkeypatch.setenv("COGNITIVE_MCP_EVAL_GATE_MODE", "shadow")
    with patch("cognitive_mcp_server._get_cle") as mock_cle:
        mock_cle.return_value.record.return_value = "VM-GOV-1"
        result = _record({"content": "x", "tags": ""})
    assert result["ok"] is True
    assert result["data"]["memory_id"] == "VM-GOV-1"
    assert result["data"]["principal"] == "admin"
    assert result["data"]["eval_gate"]["mode"] == "shadow"


def test_external_id_passthrough(monkeypatch):
    monkeypatch.setenv("COGNITIVE_MCP_MODE", "ssh")
    monkeypatch.setenv("COGNITIVE_MCP_WRITE_ENABLED", "true")
    monkeypatch.setenv("COGNITIVE_MCP_DEFAULT_PRINCIPAL", "admin")
    with patch("cognitive_mcp_server._get_cle") as mock_cle:
        mock_cle.return_value.record.return_value = "VM-GOV-2"
        _record(
            {
                "content": "x",
                "tags": "",
                "external_id": "ext-001",
            }
        )
    assert mock_cle.return_value.record.call_args.kwargs["external_id"] == "ext-001"


def test_eval_gate_enforce_blocks_without_eval_id(monkeypatch):
    monkeypatch.setenv("COGNITIVE_MCP_MODE", "ssh")
    monkeypatch.setenv("COGNITIVE_MCP_WRITE_ENABLED", "true")
    monkeypatch.setenv("COGNITIVE_MCP_DEFAULT_PRINCIPAL", "admin")
    monkeypatch.setenv("COGNITIVE_MCP_EVAL_GATE_MODE", "enforce")
    result = _record({"content": "x", "tags": ""})
    assert result["ok"] is False
    assert result["error_code"] == "eval_gate_denied"
    assert result["meta"]["eval_gate"]["decision"] == "BLOCK"


def test_tool_annotations():
    from cognitive_mcp_server import TOOL_DEFINITIONS

    by_name = {t["name"]: t for t in TOOL_DEFINITIONS}
    for name in ("recall", "unified_search", "stats", "health", "l4_status"):
        assert by_name[name]["annotations"]["readOnlyHint"] is True
    for name in ("record", "verify"):
        assert by_name[name]["annotations"]["readOnlyHint"] is False


def test_tool_names_match_definitions():
    """防止 TOOL_NAMES 与 TOOL_DEFINITIONS 漂移（l4_status 曾漏登记）。"""
    from cognitive_mcp_server import TOOL_DEFINITIONS, TOOL_NAMES

    assert TOOL_NAMES == {t["name"] for t in TOOL_DEFINITIONS}


def test_write_policy_snapshot(monkeypatch):
    from cognitive_mcp_server import _write_policy_snapshot

    monkeypatch.setenv("COGNITIVE_MCP_MODE", "ssh")
    monkeypatch.setenv("COGNITIVE_MCP_WRITE_ENABLED", "true")
    monkeypatch.setenv("COGNITIVE_MCP_DEFAULT_PRINCIPAL", "admin")
    monkeypatch.setenv("COGNITIVE_MCP_EVAL_GATE_MODE", "shadow")
    monkeypatch.setenv("COGNITIVE_MCP_DB_PATH", "C:/tmp/shared.db")
    policy = _write_policy_snapshot()
    assert policy["write_enabled"] is True
    assert policy["principal"] == "admin"
    assert policy["eval_gate_mode"] == "shadow"
    assert policy["db_path"].endswith("shared.db")
    assert "worker" not in policy["allowed_write_roles"]


def test_db_path_env_override(monkeypatch, tmp_path):
    import cognitive_mcp_server as server

    db = tmp_path / "custom_cognitive.db"
    monkeypatch.setenv("COGNITIVE_MCP_DB_PATH", str(db))
    server._reset_cle()
    try:
        cle = server._get_cle()
        assert str(cle._storage_path) == str(db)
        assert db.exists()
    finally:
        server._reset_cle()