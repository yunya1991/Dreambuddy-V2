# -*- coding: utf-8 -*-
"""L0 角色网关（l0.gateway）契约测试 — P1。

覆盖：
  - tools/list 精确等于 registry 角色白名单
  - 角色外工具 → forbidden
  - 写工具进入 Worker 角色 → 启动即拒绝
  - 调用成功透传壳信封 + gateway_role/shell_id 元数据
  - 壳不可用 → unavailable 降级
  - 真实拉起 verifier 网关：tools/list + eval_analyze 缺参 → invalid
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.shell_runtime import load_registry_doc  # noqa: E402
from mcp_shells.l0_gateway.server import L0Gateway  # noqa: E402

GATEWAY = _REPO_ROOT / "mcp_shells" / "l0_gateway" / "server.py"


class _FakeShell:
    def __init__(self, tools):
        self._tools = tools

    def list_tools(self):
        return self._tools


class _FakeHandle:
    def __init__(self, tools, envelope=None):
        self.shell = _FakeShell(tools)
        self._envelope = envelope or {"ok": True, "data": {}, "meta": {}}

    def call(self, tool, args):
        return {
            "ok": True,
            "data": {"tool": tool, "args": args},
            "meta": dict(self._envelope.get("meta") or {}),
        }


class _FakeManager:
    def __init__(self, mapping):
        self._mapping = mapping

    def get_handle(self, shell_id, force_new=False):
        return self._mapping.get(shell_id)


def _fake_manager(doc, role):
    shells = {s["shell_id"]: s for s in doc["shells"]}
    mapping = {}
    for sid in doc["worker_roles"][role]["shells"]:
        tools = [
            {"name": t["name"], "description": "d", "inputSchema": {"type": "object"}}
            for t in shells[sid]["tools"]
        ]
        mapping[sid] = _FakeHandle(tools)
    return _FakeManager(mapping)


def _call(gateway, tool, args=None):
    resp = gateway.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args or {}},
        }
    )
    return json.loads(resp["result"]["content"][0]["text"])


def test_initialize_negotiates_version_and_embeds_agent_card():
    doc = load_registry_doc()
    gateway = L0Gateway(doc, "research", _fake_manager(doc, "research"))
    resp = gateway.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }
    )
    assert resp["result"]["protocolVersion"] == "2025-06-18"
    card = resp["result"]["serverInfo"]["_meta"]["agent_card"]
    assert card["role"] == "research"
    assert card["capabilities"]["tool_count"] == len(doc["worker_roles"]["research"]["tools"])
    assert {t["name"] for t in card["capabilities"]["tools"]} == set(
        doc["worker_roles"]["research"]["tools"]
    )


def test_tools_list_equals_role_whitelist():
    doc = load_registry_doc()
    gateway = L0Gateway(doc, "research", _fake_manager(doc, "research"))
    resp = gateway.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == doc["worker_roles"]["research"]["tools"]
    assert len(names) <= 10


def test_tool_outside_role_is_forbidden():
    doc = load_registry_doc()
    gateway = L0Gateway(doc, "research", _fake_manager(doc, "research"))
    env = _call(gateway, "record", {"content": "x"})
    assert env["ok"] is False
    assert env["error_code"] == "forbidden"
    assert env["meta"]["role"] == "research"


def test_write_tool_in_role_rejected_at_startup():
    doc = load_registry_doc()
    bad = json.loads(json.dumps(doc))
    bad["worker_roles"]["research"]["tools"].append("record")
    with pytest.raises(ValueError, match="只读"):
        L0Gateway(bad, "research", _fake_manager(doc, "research"))


def test_unknown_role_rejected():
    doc = load_registry_doc()
    with pytest.raises(ValueError, match="未知角色"):
        L0Gateway(doc, "no-such-role", _FakeManager({}))


def test_dispatch_passes_through_and_adds_meta():
    doc = load_registry_doc()
    gateway = L0Gateway(doc, "research", _fake_manager(doc, "research"))
    env = _call(gateway, "recall", {"context": "x", "top_k": 1})
    assert env["ok"] is True
    assert env["data"]["tool"] == "recall"
    assert env["meta"]["gateway_role"] == "research"
    assert env["meta"]["shell_id"] == "l0.cognition.mcp"


def test_unavailable_shell_degrades():
    doc = load_registry_doc()
    gateway = L0Gateway(doc, "research", _FakeManager({}))
    env = _call(gateway, "recall", {})
    assert env["ok"] is False
    assert env["error_code"] == "unavailable"
    assert env["meta"]["shell_id"] == "l0.cognition.mcp"


@pytest.mark.integration
def test_real_verifier_gateway_end_to_end():
    env = dict(os.environ, PYTHONPATH=str(_REPO_ROOT), PYTHONIOENCODING="utf-8")
    reqs = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        + "\n"
        + json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "eval_analyze", "arguments": {}},
            }
        )
        + "\n"
    )
    proc = subprocess.run(
        [sys.executable, str(GATEWAY), "--role", "verifier"],
        input=reqs,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    responses = {}
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and msg.get("id") in (1, 2, 3):
            responses[msg["id"]] = msg

    assert 1 in responses, proc.stderr
    assert responses[1]["result"]["serverInfo"]["name"] == "l0-gateway-verifier"
    names = [t["name"] for t in responses[2]["result"]["tools"]]
    assert names == load_registry_doc()["worker_roles"]["verifier"]["tools"]

    envelope = json.loads(responses[3]["result"]["content"][0]["text"])
    assert envelope["ok"] is False
    assert envelope["error_code"] == "invalid"
    assert envelope["meta"]["gateway_role"] == "verifier"


def _engineer_catalog_gateway(*, with_cold: bool = False):
    """构造带真实 schema 形态的 engineer 目录；冷工具仅存在于测试角色副本。"""
    doc = json.loads(json.dumps(load_registry_doc()))
    if with_cold:
        doc["worker_roles"]["engineer"]["tools"].append("rea_metrics")
        rea_spec = next(s for s in doc["shells"] if s["shell_id"] == "l0.rea.mcp")
        rea_spec["tools"].append(
            {
                "name": "rea_metrics",
                "read_write": "read",
                "requires_mandate": False,
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            }
        )

    manager = _fake_manager(doc, "engineer")
    live_tools = manager._mapping["l0.rea.mcp"].shell._tools
    for tool in live_tools:
        if tool["name"] == "submit_rea_analyze":
            tool["description"] = "Submit REA analyze job"
            tool["inputSchema"] = {
                "type": "object",
                "properties": {"target": {"type": "string", "description": "本地目录或文件路径"}},
                "required": ["target"],
            }
        elif tool["name"] == "rea_metrics":
            tool["description"] = "Collect code metrics"
            tool["inputSchema"] = {
                "type": "object",
                "properties": {"target": {"type": "string", "description": "待采集目录"}},
                "required": ["target"],
            }
    return doc, L0Gateway(doc, "engineer", manager), manager


def _catalog_response(gateway, params=None):
    return gateway.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": params or {},
        }
    )


def _catalog_bytes(response):
    return len(json.dumps(response, ensure_ascii=False).encode("utf-8"))


def test_engineer_catalog_compacts_hot_schema_within_8kb():
    _doc, gateway, _manager = _engineer_catalog_gateway()
    resp = _catalog_response(gateway)
    tools = {t["name"]: t for t in resp["result"]["tools"]}

    assert resp["result"]["families"] == []
    assert _catalog_bytes(resp) <= 8192
    schema = tools["submit_rea_analyze"]["inputSchema"]
    assert schema["required"] == ["target"]
    assert schema["properties"]["target"] == {"type": "string"}
    original = gateway.load_tools()[0]["inputSchema"]
    assert original["properties"]["target"]["description"] == "本地目录或文件路径"


def test_engineer_catalog_advertises_cold_tool_as_single_line():
    _doc, gateway, _manager = _engineer_catalog_gateway(with_cold=True)
    resp = _catalog_response(gateway)
    tools = {t["name"]: t for t in resp["result"]["tools"]}

    assert tools["rea_metrics"] == {
        "name": "rea_metrics",
        "description": "Collect code metrics",
        "family": "metrics",
    }
    assert resp["result"]["families"] == ["metrics"]


def test_engineer_catalog_family_expands_full_cold_schema():
    _doc, gateway, _manager = _engineer_catalog_gateway(with_cold=True)
    resp = _catalog_response(gateway, {"family": "metrics"})

    assert resp["result"]["family"] == "metrics"
    assert [t["name"] for t in resp["result"]["tools"]] == ["rea_metrics"]
    schema = resp["result"]["tools"][0]["inputSchema"]
    assert schema["properties"]["target"]["description"] == "待采集目录"
    assert _catalog_bytes(resp) <= 4096


def test_engineer_catalog_trims_hot_tools_over_8kb():
    _doc, gateway, manager = _engineer_catalog_gateway()
    recall = next(
        t for t in manager._mapping["l0.cognition.mcp"].shell._tools if t["name"] == "recall"
    )
    recall["inputSchema"] = {
        "type": "object",
        "properties": {"context": {"type": "string", "const": "x" * 9000}},
    }
    resp = _catalog_response(gateway)

    assert _catalog_bytes(resp) <= 8192
    assert "recall" in resp["result"]["trimmed"]
    assert "submit_rea_analyze" in {t["name"] for t in resp["result"]["tools"]}


def test_engineer_catalog_trims_cold_family_over_4kb():
    _doc, gateway, manager = _engineer_catalog_gateway(with_cold=True)
    cold = next(
        t for t in manager._mapping["l0.rea.mcp"].shell._tools if t["name"] == "rea_metrics"
    )
    cold["inputSchema"]["properties"]["payload"] = {"type": "string", "const": "x" * 5000}
    resp = _catalog_response(gateway, {"family": "metrics"})

    assert _catalog_bytes(resp) <= 4096
    assert resp["result"]["tools"] == []
    assert resp["result"]["trimmed"] == ["rea_metrics"]


def test_engineer_catalog_rollback_restores_full_schemas(monkeypatch):
    monkeypatch.setenv("REA_CATALOG_HOT_ONLY", "0")
    _doc, gateway, _manager = _engineer_catalog_gateway(with_cold=True)
    resp = _catalog_response(gateway)
    tools = {t["name"]: t for t in resp["result"]["tools"]}

    assert "families" not in resp["result"]
    assert tools["submit_rea_analyze"]["inputSchema"]["properties"]["target"]["description"]
    assert tools["rea_metrics"]["inputSchema"]["required"] == ["target"]


def test_engineer_catalog_cold_tool_call_contract_is_unchanged():
    _doc, gateway, _manager = _engineer_catalog_gateway(with_cold=True)
    _catalog_response(gateway)
    envelope = _call(gateway, "rea_metrics", {"target": "/tmp/project"})

    assert envelope["ok"] is True
    assert envelope["data"] == {
        "tool": "rea_metrics",
        "args": {"target": "/tmp/project"},
    }
