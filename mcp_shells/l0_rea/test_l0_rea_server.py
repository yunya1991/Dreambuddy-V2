#!/usr/bin/env python3
"""REA 壳（l0.rea.mcp）契约测试 — M3⑦ 验收。

覆盖：
  - tools/list 工具面（6 个两段式工具 + annotations）
  - submit_rea_analyze：返回 job_id + state=running，job 落 JSONL 持久层
  - poll_rea_analyze：job_id 查询（running/success/failed 状态机）
  - poll 缺 job_id：error_code=invalid；不存在 job：error_code=not_found
  - 持久层强制（DA1）：job 状态文件真实落盘（禁止内存态）
"""

import json
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = _REPO_ROOT / "mcp_shells" / "l0_rea" / "server.py"
JOBS_DIR = _REPO_ROOT / "33-REA逆向解析工程" / "reflection_data" / "mcp_jobs"


def _rpc(method: str, params: dict, call_name: str = None, arguments: dict = None) -> dict:
    reqs = (
        json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": {"name": call_name, "arguments": arguments} if call_name else params,
            }
        )
    )
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=reqs,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(_REPO_ROOT),
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    assert lines, f"no stdout; stderr={proc.stderr}"
    return json.loads(lines[-1])


def _call_tool(name: str, arguments: dict) -> dict:
    resp = _rpc("tools/call", None, call_name=name, arguments=arguments)
    assert "result" in resp, f"rpc error: {resp}"
    return json.loads(resp["result"]["content"][0]["text"])


def test_tools_list_six_tools():
    """工具面：6 个两段式工具（submit/poll × analyze/trace/compare），均只读。"""
    resp = _rpc("tools/list", {})
    tools = resp["result"]["tools"]
    names = [t["name"] for t in tools]
    assert names == [
        "submit_rea_analyze",
        "poll_rea_analyze",
        "submit_rea_trace",
        "poll_rea_trace",
        "submit_rea_compare",
        "poll_rea_compare",
    ]
    for t in tools:
        assert t["annotations"]["readOnlyHint"] is True
        assert t["annotations"]["destructiveHint"] is False


def test_submit_returns_job_id_and_persists():
    """submit：返回 job_id + state=running；job 状态落 JSONL 持久层（DA1）。"""
    env = _call_tool("submit_rea_analyze", {"target": "mcp_shells", "scope": "architecture"})
    assert env["ok"] is True
    assert env["source"] == "l0.rea.mcp"
    job_id = env["data"]["job_id"]
    assert job_id and env["data"]["state"] == "running"
    # 持久层强制：job 状态文件真实落盘
    job_file = JOBS_DIR / f"{job_id}.json"
    assert job_file.exists(), f"job file not persisted: {job_file}"


def test_poll_job_lifecycle():
    """poll：job 状态机（running → success/failed），结果信封完整。"""
    env = _call_tool("submit_rea_analyze", {"target": "mcp_shells", "scope": "architecture"})
    job_id = env["data"]["job_id"]
    # 轮询直至终态（最多 30s）
    state = "running"
    for _ in range(60):
        poll_env = _call_tool("poll_rea_analyze", {"job_id": job_id})
        assert poll_env["ok"] is True
        state = poll_env["data"]["state"]
        if state in ("success", "failed"):
            break
        time.sleep(0.5)
    assert state in ("success", "failed"), f"job stuck in running: {job_id}"
    if state == "success":
        assert "result" in poll_env["data"]
    else:
        assert "error" in poll_env["data"]


def test_poll_requires_job_id():
    """poll 缺 job_id：error_code=invalid。"""
    env = _call_tool("poll_rea_analyze", {})
    assert env["ok"] is False
    assert env["error_code"] == "invalid"


def test_poll_not_found():
    """poll 不存在的 job：error_code=not_found。"""
    env = _call_tool("poll_rea_analyze", {"job_id": "job-nonexistent0000"})
    assert env["ok"] is False
    assert env["error_code"] == "not_found"
