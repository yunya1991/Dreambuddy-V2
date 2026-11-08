# -*- coding: utf-8 -*-
"""P0 控制面测试：mcpctl profile / doctor + 漂移比对逻辑。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcpctl  # noqa: E402
from check_mcp_tool_drift import diff_tools, run as drift_run  # noqa: E402


def _doc():
    return mcpctl.load_registry(mcpctl.REGISTRY_DEFAULT)


def test_profile_research_generates_expected_shells():
    cfg, warnings, errors = mcpctl.build_profile(
        _doc(), "research", repo_root=mcpctl.REPO_ROOT, python_exe=sys.executable
    )
    assert errors == []
    assert set(cfg["mcpServers"]) == {"cognition", "semantic-39", "rea"}
    cognition = cfg["mcpServers"]["cognition"]
    assert cognition["env"]["COGNITIVE_MCP_WRITE_ENABLED"] == "false"
    assert cognition["args"][0].endswith("cognitive_mcp_server.py")
    assert any("P1" in w for w in warnings)


def test_profile_unknown_role_returns_error():
    _, _, errors = mcpctl.build_profile(_doc(), "does-not-exist")
    assert errors and "未知角色" in errors[0]


def test_profile_ssh_only_affects_ssh_stdio_shells():
    cfg, _, errors = mcpctl.build_profile(
        _doc(),
        "research",
        repo_root=mcpctl.REPO_ROOT,
        python_exe=sys.executable,
        ssh_host="dreambuddy-remote",
    )
    assert errors == []
    assert cfg["mcpServers"]["cognition"]["command"] == "ssh"
    assert cfg["mcpServers"]["rea"]["command"] == sys.executable


def test_profile_all_roles_cover_their_tools():
    doc = _doc()
    for role in doc.get("worker_roles") or {}:
        _, _, errors = mcpctl.build_profile(
            doc, role, repo_root=mcpctl.REPO_ROOT, python_exe=sys.executable
        )
        assert errors == [], f"{role}: {errors}"


def test_profile_gateway_single_entry():
    cfg, warnings, errors = mcpctl.build_profile(
        _doc(),
        "research",
        repo_root=mcpctl.REPO_ROOT,
        python_exe=sys.executable,
        gateway=True,
    )
    assert errors == []
    assert warnings == []
    assert list(cfg["mcpServers"]) == ["l0-research"]
    entry = cfg["mcpServers"]["l0-research"]
    assert entry["args"][1:3] == ["--role", "research"]
    assert Path(entry["args"][0]).as_posix().endswith("l0_gateway/server.py")


def test_profile_gateway_rejects_write_tool_in_role():
    doc = _doc()
    bad = json.loads(json.dumps(doc))
    bad["worker_roles"]["research"]["tools"].append("record")
    _, _, errors = mcpctl.build_profile(bad, "research", gateway=True)
    assert errors and "写工具" in errors[0]


def test_install_writes_host_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / "host-mcp.json"
    monkeypatch.setitem(
        mcpctl.HOST_CONFIGS,
        "test-host",
        {
            "name": "test",
            "path": str(cfg_path),
            "needs_project": False,
            "writable": True,
        },
    )
    rc = mcpctl.main(["install", "--role", "verifier", "--host", "test-host"])
    assert rc == 0
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"eval", "store-admin", "cognition"}


def test_agent_card_role_tools_exact():
    doc = _doc()
    card = mcpctl.build_agent_card(
        doc,
        "research",
        repo_root=mcpctl.REPO_ROOT,
        python_exe=sys.executable,
    )
    assert [t["name"] for t in card["capabilities"]["tools"]] == doc["worker_roles"][
        "research"
    ]["tools"]
    assert card["server"]["args"][1:3] == ["--role", "research"]
    assert card["capabilities"]["read_only"] is True


def test_cards_check_roundtrip_and_drift(tmp_path):
    out = tmp_path / "agent_cards.json"
    assert mcpctl.main(["cards", "--out", str(out)]) == 0
    assert mcpctl.main(["cards", "--out", str(out), "--check"]) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["cards"]["research"]["server"]["command"] == "<PYTHON>"
    assert data["cards"]["research"]["server"]["env"]["PYTHONPATH"] == "<REPO_ROOT>"
    data["cards"]["research"]["capabilities"]["tool_count"] += 1
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert mcpctl.main(["cards", "--out", str(out), "--check"]) == 1


def test_new_shell_generates_files(tmp_path, capsys):
    rc = mcpctl.main(
        [
            "new-shell",
            "--name",
            "demo-svc",
            "--domain",
            "data",
            "--port",
            "analysis",
            "--tools",
            "demo_read:read,demo_write:write",
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    server = tmp_path / "mcp_shells" / "demo-svc" / "server.py"
    test = tmp_path / "mcp_shells" / "demo-svc" / "test_demo_svc_server.py"
    assert server.exists() and test.exists()
    src = server.read_text(encoding="utf-8")
    assert "run_stdio(SHELL_SOURCE, TOOL_DEFS, TOOL_HANDLERS)" in src
    assert "demo_write" in src
    assert "requires_mandate: true" in capsys.readouterr().out


def test_new_shell_register_inserts_registry(tmp_path, monkeypatch):
    reg = tmp_path / "registry.yaml"
    reg.write_text(mcpctl.REGISTRY_DEFAULT.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(mcpctl, "validate_registry", lambda *a, **k: 0)
    rc = mcpctl.main(
        [
            "new-shell",
            "--name",
            "demo-svc",
            "--domain",
            "data",
            "--port",
            "analysis",
            "--tools",
            "demo_read:read",
            "--repo-root",
            str(tmp_path),
            "--registry",
            str(reg),
            "--register",
        ]
    )
    assert rc == 0
    text = reg.read_text(encoding="utf-8")
    assert "shell_id: l0.demo-svc.mcp" in text
    assert "demo_read" in text


def test_profile_writes_mcp_json(tmp_path):
    out = tmp_path / ".mcp.json"
    rc = mcpctl.main(
        [
            "profile",
            "--role",
            "verifier",
            "--out",
            str(out),
            "--python",
            sys.executable,
        ]
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"eval", "store-admin", "cognition"}


def test_diff_tools_detects_extra_missing_and_annotation():
    shell = {
        "tools": [
            {"name": "a", "annotations": {"readOnlyHint": True}},
            {"name": "b", "annotations": {"readOnlyHint": True}},
        ]
    }
    actual = [
        {"name": "a", "annotations": {"readOnlyHint": False}},
        {"name": "c", "annotations": {"readOnlyHint": True}},
    ]
    extra, missing, mismatch = diff_tools(shell, actual)
    assert extra == ["c"]
    assert missing == ["b"]
    assert mismatch == [("a", True, False)]


def test_drift_run_fails_on_unregistered_tool(tmp_path):
    fake_shell = tmp_path / "fake_server.py"
    fake_shell.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    req = json.loads(line)\n"
        "    if req.get('method') == 'initialize':\n"
        "        out = {'jsonrpc':'2.0','id':req['id'],'result':{'protocolVersion':'2024-11-05','capabilities':{'tools':{}}}}\n"
        "    elif req.get('method') == 'tools/list':\n"
        "        out = {'jsonrpc':'2.0','id':req['id'],'result':{'tools':[{'name':'a'}]}}\n"
        "    else:\n"
        "        continue\n"
        "    print(json.dumps(out), flush=True)\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "schema_version: '1.1-mcp'\n"
        "shells:\n"
        "  - shell_id: fake.mcp\n"
        "    status: available\n"
        "    transport: stdio\n"
        f"    shell_path: {json.dumps(str(fake_shell))}\n"
        "    envelope_version: '0.1'\n"
        "    tools:\n"
        "      - name: a\n"
        "        port: memory\n"
        "        domain: cognition\n"
        "        read_write: read\n"
        "        requires_mandate: false\n"
        "        annotations: {readOnlyHint: true, destructiveHint: false}\n"
        "      - name: b\n"
        "        port: memory\n"
        "        domain: cognition\n"
        "        read_write: read\n"
        "        requires_mandate: false\n"
        "        annotations: {readOnlyHint: true, destructiveHint: false}\n",
        encoding="utf-8",
    )
    assert drift_run(registry, quiet=True) == 1


@pytest.mark.integration
def test_real_shells_have_no_drift():
    """真实拉起全部 available 壳，注册表与代码必须一致（P0 门禁本体）。"""
    assert drift_run(quiet=True, timeout=60.0) == 0