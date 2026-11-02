#!/usr/bin/env python3
"""评测壳（l0.eval.mcp）契约测试 — M2⑥ 验收。

覆盖：
  - tools/list 工具面与注册表登记一致（2 只读工具 + annotations）
  - 统一信封结构（ok/data/source/error_code）
  - eval_analyze 缺 eval_id：error_code=invalid
  - eval_analyze 不存在的 eval_id：error_code=not_found（经 45 HTTP 404 适配）
  - eval_report：经 45 HTTP metrics 适配（服务运行中则 ok=true）
"""

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = _REPO_ROOT / "mcp_shells" / "l0_eval" / "server.py"


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
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=reqs,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_REPO_ROOT),
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    assert lines, f"no stdout; stderr={proc.stderr}"
    resp = json.loads(lines[-1])
    assert "result" in resp, f"rpc error: {resp}"
    return json.loads(resp["result"]["content"][0]["text"])


def _tools_list() -> list:
    reqs = (
        json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    )
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=reqs,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_REPO_ROOT),
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    resp = json.loads(lines[-1])
    return resp["result"]["tools"]


def test_tools_list_matches_registry():
    """工具面与注册表（l0.eval.mcp）一致：2 只读工具 + annotations。"""
    tools = _tools_list()
    names = [t["name"] for t in tools]
    assert names == ["eval_analyze", "eval_report"]
    for t in tools:
        assert t["annotations"]["readOnlyHint"] is True
        assert t["annotations"]["destructiveHint"] is False


def test_eval_analyze_requires_eval_id():
    """缺 eval_id：error_code=invalid，信封结构完整。"""
    env = _call_tool("eval_analyze", {})
    assert env["ok"] is False
    assert env["error_code"] == "invalid"
    assert env["source"] == "l0.eval.mcp"
    assert "timestamp" in env and "version" in env


def test_eval_analyze_not_found():
    """不存在的 eval_id：经 45 HTTP 404 适配为 error_code=not_found。"""
    env = _call_tool("eval_analyze", {"eval_id": "eval-nonexistent-00000000"})
    assert env["ok"] is False
    assert env["error_code"] in (
        "not_found",
        "unavailable",
    )  # 404→not_found；服务不可达→unavailable


def test_eval_report_via_45_http():
    """eval_report：经 45 HTTP metrics 适配（服务运行中则 ok=true）。"""
    env = _call_tool("eval_report", {})
    # 45 服务运行中（systemd eval-api.service active）→ ok=true；若服务不可达则 unavailable
    assert env["source"] == "l0.eval.mcp"
    assert env["ok"] is True or env["error_code"] == "unavailable"
