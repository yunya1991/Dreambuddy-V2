"""MCPClient stdio 协议测试（使用临时 fake shell，无网络）。"""

import sys

import pytest
from core.mcp_client import MCPClient, MCPError


def _fake_shell(tmp_path):
    path = tmp_path / "fake_mcp_server.py"
    path.write_text(
        """
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "initialize":
        resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"protocolVersion": "x"}}
    elif method == "tools/call":
        env = {"ok": True, "data": {"tool": req["params"]["name"],
                                    "args": req["params"].get("arguments")},
               "source": "fake"}
        resp = {"jsonrpc": "2.0", "id": req["id"],
                "result": {"content": [{"type": "text",
                                        "text": json.dumps(env)}]}}
    else:
        resp = {"jsonrpc": "2.0", "id": req["id"],
                "error": {"code": -32601, "message": "no"}}
    print(json.dumps(resp), flush=True)
""",
        encoding="utf-8",
    )
    return path


def test_call_roundtrip(tmp_path):
    client = MCPClient(_fake_shell(tmp_path), python_bin=sys.executable, timeout=10)
    with client:
        env = client.call("echo", {"x": 1})
    assert env["ok"] is True
    assert env["data"] == {"tool": "echo", "args": {"x": 1}}


def test_missing_shell_raises(tmp_path):
    client = MCPClient(tmp_path / "missing.py", python_bin=sys.executable, timeout=2)
    with pytest.raises(MCPError):
        client.start()


def test_context_manager_closes(tmp_path):
    client = MCPClient(_fake_shell(tmp_path), python_bin=sys.executable, timeout=10)
    with client:
        assert client._proc is not None
    assert client._proc is None
