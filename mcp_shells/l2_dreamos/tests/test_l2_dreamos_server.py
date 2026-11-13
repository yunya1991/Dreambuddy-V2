"""l2.dreamos.mcp 五工具契约测试（异步 submit/poll/get_result 范式）。

覆盖：
  C1 tools/list 精确 = [submit_run, poll_run, get_result, get_intent, get_budget]
  C2 initialize / ping / serverInfo.name 正确
  C3 submit_run 正常创建 job + 频控 + 并发限制 + 参数校验
  C4 poll_run 状态查询 + not_found
  C5 get_result 完成态可读 + 未完成 not_ready + 失败态 job_failed + truncated
  C6 get_intent / get_budget 只读元数据
  C7 注解正确（submit_run readOnlyHint=false + 其余只读）
  C8 壳零 DB 直连 + 源码禁词扫描
  C9 状态机推进：submitted → running → done
  C10 结果超 2MB 截断
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_shells.l2_dreamos import server  # noqa: E402


def _rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    req = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        req["params"] = params
    return server._handle_request(req)


def _content_text(response: dict) -> str:
    return response["result"]["content"][0]["text"]


def _submit(seed: str = "test-run", tokens: int = 1000, trace_id: str = "t1") -> dict:
    return _rpc(
        "tools/call",
        {
            "name": "submit_run",
            "arguments": {
                "intent": seed,
                "budget": {"total_tokens": tokens},
                "trace_id": trace_id,
            },
        },
    )


@pytest.fixture(autouse=True)
def _cleanup_jobs(monkeypatch):
    """每个测试前清理 job 目录 + 重置治理 state + 禁用 mock 引擎后台线程。"""
    monkeypatch.setenv("DREAMOS_MOCK_ENGINE", "0")  # 禁用后台线程，测试手动推进状态
    server._reset_governance()

    job_dir = Path(server._JOB_DIR)
    if job_dir.exists():
        for f in job_dir.glob("*.json"):
            f.unlink(missing_ok=True)
        for f in job_dir.glob("*.json.tmp"):
            f.unlink(missing_ok=True)
    yield


# ════════════════════════════════════════════════════════════════════════════
# C1 tools/list
# ════════════════════════════════════════════════════════════════════════════


def test_tools_list_exact_five_tools():
    resp = _rpc("tools/list")
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"submit_run", "poll_run", "get_result", "get_intent", "get_budget"}


def test_tools_list_submit_is_write():
    """submit_run 是 L2 写工具 → readOnlyHint=false, destructiveHint=true。"""
    resp = _rpc("tools/list")
    by_name = {t["name"]: t for t in resp["result"]["tools"]}
    submit = by_name["submit_run"]
    assert submit["annotations"]["readOnlyHint"] is False
    assert submit["annotations"]["destructiveHint"] is True


def test_tools_list_others_are_readonly():
    resp = _rpc("tools/list")
    by_name = {t["name"]: t for t in resp["result"]["tools"]}
    for name in ("poll_run", "get_result", "get_intent", "get_budget"):
        assert by_name[name]["annotations"]["readOnlyHint"] is True


# ════════════════════════════════════════════════════════════════════════════
# C2 initialize / ping
# ════════════════════════════════════════════════════════════════════════════


def test_initialize():
    init = _rpc("initialize")
    assert init["result"]["serverInfo"]["name"] == "l2.dreamos.mcp"
    assert init["result"]["serverInfo"]["version"] == "0.1"


def test_ping():
    ping = _rpc("ping")
    assert ping["result"] == {}


# ════════════════════════════════════════════════════════════════════════════
# C3 submit_run
# ════════════════════════════════════════════════════════════════════════════


def test_submit_run_ok():
    resp = _submit("my-first-run", 5000)
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is True
    assert payload["run_id"].startswith("dr_")
    assert payload["state"] == "submitted"
    assert payload["created_at"] is not None
    assert payload["meta"]["shell"] == "l2.dreamos.mcp"


def test_submit_run_empty_intent_rejected():
    resp = _rpc(
        "tools/call",
        {
            "name": "submit_run",
            "arguments": {"intent": "", "budget": {"total_tokens": 100}},
        },
    )
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid"


def test_submit_run_missing_budget_rejected():
    resp = _rpc(
        "tools/call",
        {
            "name": "submit_run",
            "arguments": {"intent": "hello"},
        },
    )
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid"


def test_submit_run_budget_not_int_rejected():
    resp = _rpc(
        "tools/call",
        {
            "name": "submit_run",
            "arguments": {"intent": "hi", "budget": {"total_tokens": "lots"}},
        },
    )
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid"


def test_submit_run_concurrent_limit():
    """并发上限 _MAX_CONCURRENT = 4，填满后拒绝。"""
    original = server._MAX_CONCURRENT
    try:
        server._MAX_CONCURRENT = 2
        # 第一次会 submit + 线程立即 acquire；第二次也会 submit + 线程 acquire
        # 但 count 在 submit_run 里只给线程用，submit_run 自己不 acquire
        # 所以这里测的是 rate limit，不是 concurrent
        # 直接调 concurrent_acquire 来填
        server._reset_governance()
        assert server._concurrent_acquire()
        assert server._concurrent_acquire()
        assert not server._concurrent_acquire()  # 已满
    finally:
        server._MAX_CONCURRENT = original
        server._reset_governance()


def test_submit_run_rate_limit():
    """频控：超过 _RATE_LIMIT_PER_MIN 后拒绝。"""
    original_rl = server._RATE_LIMIT_PER_MIN
    try:
        server._RATE_LIMIT_PER_MIN = 1
        server._reset_governance()
        resp1 = _submit("r1")
        p1 = json.loads(_content_text(resp1))
        assert p1["ok"] is True

        resp2 = _submit("r2")
        p2 = json.loads(_content_text(resp2))
        assert p2["ok"] is False
        assert p2["error_code"] == "rate_limited"
    finally:
        server._RATE_LIMIT_PER_MIN = original_rl
        server._reset_governance()


# ════════════════════════════════════════════════════════════════════════════
# C4 poll_run
# ════════════════════════════════════════════════════════════════════════════


def test_poll_run_not_found():
    resp = _rpc("tools/call", {"name": "poll_run", "arguments": {"run_id": "dr_nonexist"}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "not_found"


def test_poll_run_unknown_method():
    resp = _rpc("unknown/method")
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_poll_run_states_progress():
    """状态机：submitted → running → done（手动推进，因为 mock 引擎已禁用）。"""
    resp = _submit("state-machine", 3000)
    run_id = json.loads(_content_text(resp))["run_id"]

    # 初始：submitted
    resp0 = _rpc("tools/call", {"name": "poll_run", "arguments": {"run_id": run_id}})
    p0 = json.loads(_content_text(resp0))
    assert p0["state"] == "submitted"

    # 手动推进 → running
    server._write_job(
        run_id,
        {
            "state": "running",
            "created_at": "t0",
            "started_at": "t1",
            "budget": {"total_tokens": 3000},
        },
    )
    resp1 = _rpc("tools/call", {"name": "poll_run", "arguments": {"run_id": run_id}})
    p1 = json.loads(_content_text(resp1))
    assert p1["state"] == "running"

    # 手动推进 → done
    server._write_job(
        run_id,
        {
            "state": "done",
            "created_at": "t0",
            "started_at": "t1",
            "completed_at": "t2",
            "budget": {"total_tokens": 3000},
            "result": {"status": "completed"},
        },
    )
    resp2 = _rpc("tools/call", {"name": "poll_run", "arguments": {"run_id": run_id}})
    p2 = json.loads(_content_text(resp2))
    assert p2["state"] == "done"


# ════════════════════════════════════════════════════════════════════════════
# C5 get_result
# ════════════════════════════════════════════════════════════════════════════


def test_get_result_not_ready():
    """未完成 job → not_ready。"""
    # 提交后立刻 get_result（在 submitted/running 阶段）
    resp = _submit("not-ready", 2000)
    run_id = json.loads(_content_text(resp))["run_id"]
    # 抢先直接写 submitted 状态，确保没推进
    server._write_job(
        run_id,
        {
            "run_id": run_id,
            "state": "running",
            "created_at": "2026-01-01T00:00:00+00:00",
            "result": None,
            "error": None,
        },
    )
    resp = _rpc("tools/call", {"name": "get_result", "arguments": {"run_id": run_id}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "not_ready"


def test_get_result_not_found():
    resp = _rpc(
        "tools/call",
        {"name": "get_result", "arguments": {"run_id": "dr_not_exist"}},
    )
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "not_found"


def test_get_result_ok():
    """完成的 job → result 可读。"""
    resp = _submit("result-test", 5000)
    run_id = json.loads(_content_text(resp))["run_id"]
    # 手动推进到 done
    server._write_job(
        run_id,
        {
            "run_id": run_id,
            "state": "done",
            "created_at": "2026-01-01T00:00:00+00:00",
            "started_at": "2026-01-01T00:00:01+00:00",
            "completed_at": "2026-01-01T00:00:05+00:00",
            "result": {
                "schema_version": "0.1",
                "status": "completed",
                "intent_name": "result-test",
                "elapsed_sec": 4.0,
                "tokens_used": 1500,
            },
            "budget": {"total_tokens": 5000, "tokens_used": 1500, "budget_remaining": 3500},
        },
    )

    resp = _rpc("tools/call", {"name": "get_result", "arguments": {"run_id": run_id}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is True
    assert payload["state"] == "done"
    assert payload["result"]["status"] == "completed"
    assert payload["budget"]["tokens_used"] == 1500


def test_get_result_truncated():
    """result 超 2MB → truncated=True。"""
    resp = _submit("big-result", 10000)
    run_id = json.loads(_content_text(resp))["run_id"]
    # 直接写一个超大的 result
    server._write_job(
        run_id,
        {
            "run_id": run_id,
            "state": "done",
            "created_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:01:00+00:00",
            "result": {
                "schema_version": "0.1",
                "big_data": "X" * (3 * 1024 * 1024),
            },
            "budget": {"total_tokens": 10000, "tokens_used": 1000, "budget_remaining": 9000},
        },
    )
    resp = _rpc("tools/call", {"name": "get_result", "arguments": {"run_id": run_id}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is True
    assert payload["truncated"] is True


def test_get_result_failed_job():
    """状态为 failed → job_failed。"""
    resp = _submit("failed-test", 1000)
    run_id = json.loads(_content_text(resp))["run_id"]
    server._write_job(
        run_id,
        {
            "run_id": run_id,
            "state": "failed",
            "created_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:01:00+00:00",
            "error": "intent parsing error",
            "result": None,
        },
    )
    resp = _rpc("tools/call", {"name": "get_result", "arguments": {"run_id": run_id}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "job_failed"
    assert "intent parsing" in payload["reason"]


# ════════════════════════════════════════════════════════════════════════════
# C6 get_intent / get_budget
# ════════════════════════════════════════════════════════════════════════════


def test_get_intent_ok():
    resp = _submit("super-intent", 999, trace_id="TRACE-ABC")
    run_id = json.loads(_content_text(resp))["run_id"]
    resp = _rpc("tools/call", {"name": "get_intent", "arguments": {"run_id": run_id}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is True
    assert payload["intent"] == "super-intent"
    assert payload["trace_id"] == "TRACE-ABC"
    assert payload["state"] == "submitted" or payload["state"] == "running"


def test_get_intent_not_found():
    resp = _rpc("tools/call", {"name": "get_intent", "arguments": {"run_id": "dr_nope"}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "not_found"


def test_get_budget_ok():
    resp = _submit("budget-check", 7777)
    run_id = json.loads(_content_text(resp))["run_id"]
    resp = _rpc("tools/call", {"name": "get_budget", "arguments": {"run_id": run_id}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is True
    assert payload["budget"]["total_tokens"] == 7777
    assert payload["budget"]["tokens_used"] == 0
    assert payload["budget"]["budget_remaining"] == 7777


# ════════════════════════════════════════════════════════════════════════════
# C8 源码禁词扫描 + 零 DB 直连
# ════════════════════════════════════════════════════════════════════════════


def test_source_has_no_db_direct_keywords():
    source = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    forbidden = [
        "import psycopg",
        "import sqlite3",
        "import psycopg2",
        "postgres://",
        "sqlite:///",
        "cognitive_memory.db",
    ]
    for kw in forbidden:
        assert kw.lower() not in source.lower(), f"禁词 {kw!r} 违反 H7：l2.dreamos 永不直连 DB"


def test_shell_source_name():
    assert server.SHELL_SOURCE == "l2.dreamos.mcp"


def test_result_truncate_direct():
    """_truncate_result 直接调用测试。"""
    big = {"data": "X" * (3 * 1024 * 1024)}
    slim, truncated = server._truncate_result(big, "run-123")
    assert truncated is True
    assert isinstance(slim, dict)


def test_result_truncate_small():
    small = {"data": "hello"}
    out, truncated = server._truncate_result(small, "run-123")
    assert truncated is False
    assert out == small
