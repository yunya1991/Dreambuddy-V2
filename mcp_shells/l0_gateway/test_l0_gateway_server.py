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