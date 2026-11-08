#!/usr/bin/env python3
"""库管壳（l0.store-admin.mcp）只读契约测试 — M4⑩ 验收。

覆盖：
  - tools/list 工具面与注册表登记一致（2 工具 + annotations）
  - 统一信封结构（ok/data/source/error_code）
  - store_admin_status 健康返回（mode=read-only）
  - store_admin_query invalid 入参返回 error_code=invalid
  - 库管只读（D2）：工具面不含任何写工具
"""

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = _REPO_ROOT / "mcp_shells" / "l0_store_admin" / "server.py"


def _rpc(reqs: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=reqs,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=str(_REPO_ROOT),
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    assert lines, f"no stdout; stderr={proc.stderr}"
    return json.loads(lines[-1])


def _call_tool(name: str, arguments: dict) -> dict:
    reqs = (
        json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
    )
    resp = _rpc(reqs)
    assert "result" in resp, f"rpc error: {resp}"
    return json.loads(resp["result"]["content"][0]["text"])


def _tools_list() -> list:
    reqs = (
        json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    )
    return _rpc(reqs)["result"]["tools"]


def test_tools_list_matches_registry():
    """工具面与注册表（mcp_capabilities.yaml l0.store-admin.mcp）一致：2 工具 + annotations。"""
    tools = _tools_list()
    names = [t["name"] for t in tools]
    assert names == ["store_admin_status", "store_admin_query"]
    for t in tools:
        assert t["annotations"]["readOnlyHint"] is True
        assert t["annotations"]["destructiveHint"] is False


def test_no_write_tools():
    """库管只读（D2）：工具面不含任何写工具。"""
    tools = _tools_list()
    for t in tools:
        assert "write" not in t["name"]
        assert t["annotations"]["readOnlyHint"] is True


def test_status_envelope():
    """store_admin_status：统一信封 + mode=read-only。"""
    env = _call_tool("store_admin_status", {})
    assert env["ok"] is True
    assert env["source"] == "l0.store-admin.mcp"
    assert env["data"]["mode"] == "read-only"


def test_query_invalid_args():
    """store_admin_query：缺 table 返回 error_code=invalid（非静默）。"""
    env = _call_tool("store_admin_query", {})
    assert env["ok"] is False
    assert env["error_code"] == "invalid"


def test_unknown_tool_rejected():
    """未登记工具名：JSON-RPC -32601 拒绝。"""
    reqs = (
        json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "store_admin_write", "arguments": {}},
            }
        )
    )
    resp = _rpc(reqs)
    assert resp.get("error", {}).get("code") == -32601
