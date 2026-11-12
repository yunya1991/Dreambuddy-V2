#!/usr/bin/env python3
"""REA 壳（l0.rea.mcp）契约测试 — M3⑦ + SPEC-33-D 验收。

覆盖：
  - tools/list 工具面（15 个工具 = submit/poll/cancel × 4 + 3 个同步只读工具）+ annotations
  - schema 契约：deadline_ms / analyze.scope 枚举 / compare required / snapshot section 枚举与 limit 上限
  - submit_rea_analyze：返回 job_id + state=running，job 落 JSONL 持久层
  - poll/cancel：running/success/failed/timeout/cancelled 状态机与回滚语义
  - poll 缺 job_id：error_code=invalid；不存在 job：error_code=not_found
  - get_rea_snapshot：按 section 分页读取 analyze 快照（未知 snapshot_id 不抛异常）
  - 持久层强制（DA1）：job 状态文件真实落盘（禁止内存态）
"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells.l0_rea import server as rea_server  # noqa: E402

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
        encoding="utf-8",
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


def test_tools_list_twelve_tools_with_deadline_and_cancel():
    """工具面：既有 9 工具 + cancel × 3 + adapt_plan × 3；每个 submit 支持 deadline_ms。"""
    resp = _rpc("tools/list", {})
    tools = resp["result"]["tools"]
    names = [t["name"] for t in tools]
    # tools/list 从 47 registry 派生（单一事实源），顺序即 mcp_capabilities.yaml 登记顺序
    assert names == [
        "submit_rea_analyze",
        "poll_rea_analyze",
        "submit_rea_trace",
        "poll_rea_trace",
        "submit_rea_compare",
        "poll_rea_compare",
        "get_rea_snapshot",
        "rea_audit",
        "get_rea_methodology",
        "cancel_rea_analyze",
        "cancel_rea_trace",
        "cancel_rea_compare",
        "submit_rea_adapt_plan",
        "poll_rea_adapt_plan",
        "cancel_rea_adapt_plan",
    ]
    by_name = {t["name"]: t for t in tools}
    for kind in ("analyze", "trace", "compare", "adapt_plan"):
        deadline = by_name[f"submit_rea_{kind}"]["inputSchema"]["properties"]["deadline_ms"]
        assert deadline["default"] == 120000
        assert deadline["minimum"] == 1
        cancel_schema = by_name[f"cancel_rea_{kind}"]["inputSchema"]
        assert cancel_schema["required"] == ["job_id"]
    for t in tools:
        assert t["annotations"]["readOnlyHint"] is True
        assert t["annotations"]["destructiveHint"] is False


def test_rea_audit_schema_and_reject():
    """SPEC-33-E：rea_audit 同步工具；缺 falsifier 直接 reject 且无写入建议。"""
    tools = {t["name"]: t for t in _rpc("tools/list", {})["result"]["tools"]}
    schema = tools["rea_audit"]["inputSchema"]
    assert schema["required"] == ["target"]
    assert schema["properties"]["hypotheses"]["type"] == "array"
    assert schema["properties"]["lsp"]["type"] == "boolean"

    env = _call_tool(
        "rea_audit",
        {
            "target": "mcp_shells/l0_rea",
            "hypotheses": [{"hypothesis_id": "H-1", "claim": "可合并", "target_refs": ["server"]}],
        },
    )
    assert env["ok"] is True
    result = env["data"]["result"]
    assert result["mode"] == "hypothesis"
    assert result["hypotheses"][0]["gate"] == "reject"
    assert result["cognitive_hint"]["write"] == []


def test_methodology_tool_empty_failopen():
    """SPEC-33-E：方法论工具无输入时 fail-open，返回空模板 + known_gaps。"""
    env = _call_tool("get_rea_methodology", {})
    assert env["ok"] is True
    assert env["data"]["result"]["methodologies"] == []
    assert env["data"]["result"]["known_gaps"]


def test_tool_schemas_contract():
    """schema 契约：analyze scope 枚举 / compare 双必填 / snapshot section+limit。"""
    tools = {t["name"]: t for t in _rpc("tools/list", {})["result"]["tools"]}

    analyze = tools["submit_rea_analyze"]["inputSchema"]
    assert analyze["required"] == ["target"]
    assert analyze["properties"]["scope"]["enum"] == ["summary", "architecture", "full"]
    assert analyze["properties"]["scope"]["default"] == "summary"
    assert analyze["properties"]["force"]["type"] == "boolean"

    compare = tools["submit_rea_compare"]["inputSchema"]
    assert compare["required"] == ["target_a", "target_b"]
    assert compare["properties"]["scope"]["enum"] == ["summary", "architecture", "full"]

    snapshot = tools["get_rea_snapshot"]["inputSchema"]
    # SPEC-33-G §2.9：section=evolution 读无 AI 待办，不需要 snapshot_id
    assert snapshot["required"] == []
    assert snapshot["properties"]["limit"]["maximum"] == 200
    assert "modules" in snapshot["properties"]["section"]["enum"]
    assert "evolution" in snapshot["properties"]["section"]["enum"]
    assert "pack" in snapshot["properties"]["section"]["enum"]
    assert "archaeology" in snapshot["properties"]["section"]["enum"]
    assert "dependency_hygiene" in snapshot["properties"]["section"]["enum"]
    assert "diagnostics" in snapshot["properties"]["section"]["enum"]
    assert "runtime" in snapshot["properties"]["section"]["enum"]
    assert "sarif" in snapshot["properties"]["section"]["enum"]
    assert snapshot["properties"]["otel_path"]["type"] == "string"
    trace = tools["submit_rea_trace"]["inputSchema"]
    assert trace["properties"]["lsp"]["type"] == "boolean"
    assert trace["properties"]["lsp"]["default"] is False
    assert snapshot["properties"]["budget_bytes"]["minimum"] == 1
    assert snapshot["properties"]["metrics_config"]["type"] == "string"
    assert snapshot["properties"]["metrics_history"]["type"] == "string"
    for poll_name in ("poll_rea_analyze", "poll_rea_trace", "poll_rea_compare"):
        assert tools[poll_name]["inputSchema"]["required"] == ["job_id"]


def test_submit_returns_job_id_and_persists():
    """submit：返回 job_id + state=running；job 状态落 JSONL 持久层（DA1）。"""
    env = _call_tool("submit_rea_analyze", {"target": "mcp_shells", "scope": "full"})
    assert env["ok"] is True
    assert env["source"] == "l0.rea.mcp"
    job_id = env["data"]["job_id"]
    assert job_id and env["data"]["state"] == "running"
    # 持久层强制：job 状态文件真实落盘
    job_file = JOBS_DIR / f"{job_id}.json"
    assert job_file.exists(), f"job file not persisted: {job_file}"


def test_poll_job_lifecycle():
    """poll：job 状态机（running → success/failed），结果信封完整。"""
    env = _call_tool("submit_rea_analyze", {"target": "mcp_shells", "scope": "full"})
    job_id = env["data"]["job_id"]
    # 轮询直至终态（最多 30s）
    state = "running"
    poll_env = {}
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


def _wait_snapshot_id(target: str) -> str:
    env = _call_tool("submit_rea_analyze", {"target": target, "scope": "full"})
    job_id = env["data"]["job_id"]
    for _ in range(90):
        poll_env = _call_tool("poll_rea_analyze", {"job_id": job_id})
        data = poll_env["data"]
        if data["state"] == "success":
            node_out = data["result"]
            assert node_out["ok"] is True, node_out
            return node_out["result"]["snapshot_id"]
        if data["state"] == "failed":
            raise AssertionError(f"analyze job failed: {data.get('error')}")
        time.sleep(0.5)
    raise AssertionError(f"analyze job stuck in running: {job_id}")


def test_get_rea_snapshot_paginates():
    """get_rea_snapshot：按 section 分页返回（cursor/limit/total/next_cursor）。"""
    snapshot_id = _wait_snapshot_id("mcp_shells")
    env = _call_tool(
        "get_rea_snapshot",
        {"snapshot_id": snapshot_id, "section": "modules", "limit": 2, "cursor": 0},
    )
    assert env["ok"] is True
    node_out = env["data"]
    assert node_out["ok"] is True, node_out
    result = node_out["result"]
    assert result["snapshot_id"] == snapshot_id
    assert result["section"] == "modules"
    assert len(result["items"]) <= 2
    assert result["total"] >= len(result["items"])
    if result["total"] > 2:
        assert result["next_cursor"] == 2


def test_get_rea_snapshot_unknown_id_is_soft_error():
    """未知 snapshot_id：ok=false / error=snapshot_not_found，壳不抛异常。"""
    env = _call_tool("get_rea_snapshot", {"snapshot_id": "snapshot-does-not-exist"})
    assert env["ok"] is True  # 壳层信封成功，错误在节点结果内
    assert env["data"]["ok"] is False
    assert env["data"]["error"] == "snapshot_not_found"


def _direct_submit(name, args):
    before = set(threading.enumerate())
    envelope = json.loads(rea_server._handle_submit(name, args))
    assert envelope["ok"] is True
    workers = [
        thread
        for thread in set(threading.enumerate()) - before
        if not isinstance(thread, threading.Timer)
    ]
    assert len(workers) == 1
    return envelope, workers[0]


def _direct_poll(job_id):
    return json.loads(rea_server._handle_poll("poll_rea_analyze", {"job_id": job_id}))


def _wait_direct_state(job_id, states):
    deadline = time.monotonic() + 0.5
    envelope = _direct_poll(job_id)
    while envelope["data"]["state"] not in states and time.monotonic() < deadline:
        time.sleep(0.01)
        envelope = _direct_poll(job_id)
    return envelope


def _blocked_node(started, release):
    def fake(node_name, params):
        started.set()
        release.wait(2)
        return {"node": node_name, "ok": True, "result": {"done": True}}

    return fake


def test_deadline_expires_job_with_reason_and_no_result(tmp_path, monkeypatch):
    monkeypatch.setattr(rea_server, "JOBS_DIR", tmp_path)
    monkeypatch.delenv("REA_DEADLINE_ENABLED", raising=False)
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(rea_server, "_run_node_sync", _blocked_node(started, release))
    envelope, worker = _direct_submit("submit_rea_analyze", {"target": ".", "deadline_ms": 20})
    job_id = envelope["data"]["job_id"]
    try:
        assert started.wait(0.5)
        polled = _wait_direct_state(job_id, {"timeout"})
        assert polled["data"]["state"] == "timeout"
        assert polled["data"]["reason"]
        assert "result" not in polled["data"]
        persisted = json.loads((tmp_path / f"{job_id}.json").read_text().splitlines()[-1])
        assert persisted["state"] == "timeout"
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    assert _direct_poll(job_id)["data"]["state"] == "timeout"


def test_cancel_forces_terminal_state_after_grace(tmp_path, monkeypatch):
    assert hasattr(rea_server, "_handle_cancel")
    monkeypatch.setattr(rea_server, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(rea_server, "_CANCEL_GRACE_SECONDS", 0.02, raising=False)
    monkeypatch.delenv("REA_DEADLINE_ENABLED", raising=False)
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(rea_server, "_run_node_sync", _blocked_node(started, release))
    envelope, worker = _direct_submit("submit_rea_analyze", {"target": "."})
    job_id = envelope["data"]["job_id"]
    try:
        assert started.wait(0.5)
        cancelled = json.loads(rea_server._handle_cancel("cancel_rea_analyze", {"job_id": job_id}))
        assert cancelled["data"]["state"] == "cancelled"
        assert cancelled["data"]["forced"] is True
        polled = _direct_poll(job_id)
        assert polled["data"]["state"] == "cancelled"
        assert polled["data"]["reason"]
        assert "result" not in polled["data"]
        persisted = json.loads((tmp_path / f"{job_id}.json").read_text().splitlines()[-1])
        assert persisted["state"] == "cancelled"
        assert persisted["forced"] is True
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    assert _direct_poll(job_id)["data"]["state"] == "cancelled"


def test_cancel_worker_boundary_is_cooperative(tmp_path, monkeypatch):
    assert hasattr(rea_server, "_handle_cancel")
    monkeypatch.setattr(rea_server, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(rea_server, "_CANCEL_GRACE_SECONDS", 1.0, raising=False)
    monkeypatch.delenv("REA_DEADLINE_ENABLED", raising=False)
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(rea_server, "_run_node_sync", _blocked_node(started, release))
    envelope, worker = _direct_submit("submit_rea_analyze", {"target": "."})
    job_id = envelope["data"]["job_id"]
    release_timer = threading.Timer(0.05, release.set)
    try:
        assert started.wait(0.5)
        release_timer.start()
        cancelled = json.loads(rea_server._handle_cancel("cancel_rea_analyze", {"job_id": job_id}))
        assert cancelled["data"]["state"] == "cancelled"
        assert cancelled["data"]["forced"] is False
        worker.join(1)
        assert not worker.is_alive()
        polled = _direct_poll(job_id)
        assert polled["data"]["state"] == "cancelled"
        assert "result" not in polled["data"]
    finally:
        release.set()
        release_timer.cancel()
        worker.join(2)
    assert not worker.is_alive()


def test_deadline_rollback_ignores_deadline_ms(tmp_path, monkeypatch):
    monkeypatch.setattr(rea_server, "JOBS_DIR", tmp_path)
    monkeypatch.setenv("REA_DEADLINE_ENABLED", "0")
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(rea_server, "_run_node_sync", _blocked_node(started, release))
    envelope, worker = _direct_submit("submit_rea_analyze", {"target": ".", "deadline_ms": 1})
    job_id = envelope["data"]["job_id"]
    try:
        assert started.wait(0.5)
        time.sleep(0.02)
        assert _direct_poll(job_id)["data"]["state"] == "running"
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    assert _direct_poll(job_id)["data"]["state"] == "success"


def test_cancel_rollback_only_marks_without_changing_poll(tmp_path, monkeypatch):
    assert hasattr(rea_server, "_handle_cancel")
    monkeypatch.setattr(rea_server, "JOBS_DIR", tmp_path)
    monkeypatch.setenv("REA_DEADLINE_ENABLED", "0")
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(rea_server, "_run_node_sync", _blocked_node(started, release))
    envelope, worker = _direct_submit("submit_rea_analyze", {"target": "."})
    job_id = envelope["data"]["job_id"]
    try:
        assert started.wait(0.5)
        marked = json.loads(rea_server._handle_cancel("cancel_rea_analyze", {"job_id": job_id}))
        assert marked["data"]["state"] == "running"
        assert marked["data"]["cancel_requested"] is True
        assert _direct_poll(job_id)["data"]["state"] == "running"
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    assert _direct_poll(job_id)["data"]["state"] == "success"
