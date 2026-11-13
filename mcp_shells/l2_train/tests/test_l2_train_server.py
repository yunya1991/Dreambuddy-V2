"""l2.train.mcp 契约测试 — control 层异步 job store + trigger_training Mandate。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_shells.l2_train import server  # noqa: E402


def _rpc(method: str, params=None) -> dict:
    req = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        req["params"] = params
    return server._handle_request(req)


def _text(r: dict) -> str:
    return r["result"]["content"][0]["text"]


def _submit(trainer: str = "ray-test", tokens: int = 500, seed: str = "t1") -> dict:
    return _rpc(
        "tools/call",
        {
            "name": "trigger_training",
            "arguments": {
                "trainer": trainer,
                "mandate": f"MANDATE-{seed}",
                "budget": {"total_tokens": tokens},
                "trace_id": f"TRACE-{seed}",
            },
        },
    )


@pytest.fixture(autouse=True)
def _cleanup(monkeypatch):
    monkeypatch.setenv("TRAIN_MOCK_ENGINE", "0")
    server._reset_governance()
    for f in server._JOB_DIR.glob("*.json"):
        f.unlink(missing_ok=True)
    yield


def test_tools_list_exact():
    r = _rpc("tools/list")
    names = {t["name"] for t in r["result"]["tools"]}
    assert names == {"trigger_training", "get_training_status", "list_runs"}


def test_trigger_training_is_write():
    r = _rpc("tools/list")
    t = {x["name"]: x for x in r["result"]["tools"]}["trigger_training"]
    assert t["annotations"]["readOnlyHint"] is False
    assert t["annotations"]["destructiveHint"] is True


def test_get_training_status_is_readonly():
    r = _rpc("tools/list")
    for name in ("get_training_status", "list_runs"):
        t = {x["name"]: x for x in r["result"]["tools"]}[name]
        assert t["annotations"]["readOnlyHint"] is True


def test_initialize():
    r = _rpc("initialize")
    assert r["result"]["serverInfo"]["name"] == "l2.train.mcp"


def test_trigger_training_ok():
    r = _submit()
    p = json.loads(_text(r))
    assert p["ok"] is True
    assert p["run_id"].startswith("tr_")
    assert p["state"] == "submitted"


def test_trigger_training_missing_mandate():
    r = _rpc(
        "tools/call",
        {
            "name": "trigger_training",
            "arguments": {
                "trainer": "x",
                "budget": {"total_tokens": 10},
                "trace_id": "y",
            },
        },
    )
    p = json.loads(_text(r))
    assert p["ok"] is False
    assert p["error_code"] == "invalid"
    assert "mandate" in str(p.get("reason", "")).lower()


def test_trigger_training_missing_budget():
    r = _rpc(
        "tools/call",
        {
            "name": "trigger_training",
            "arguments": {"trainer": "x", "mandate": "m", "trace_id": "y"},
        },
    )
    p = json.loads(_text(r))
    assert p["ok"] is False
    assert "budget" in str(p.get("reason", "")).lower()


def test_trigger_training_rate_limit():
    original = server._RATE_LIMIT
    server._RATE_LIMIT = 1
    try:
        _submit(seed="a")
        r2 = _submit(seed="b")
        p2 = json.loads(_text(r2))
        assert p2["ok"] is False
        assert p2["error_code"] == "rate_limited"
    finally:
        server._RATE_LIMIT = original
        server._reset_governance()


def test_get_training_status_not_found():
    r = _rpc("tools/call", {"name": "get_training_status", "arguments": {"run_id": "tr_nope"}})
    p = json.loads(_text(r))
    assert p["ok"] is False
    assert p["error_code"] == "not_found"


def test_get_training_status_ok():
    resp = _submit()
    run_id = json.loads(_text(resp))["run_id"]
    r = _rpc("tools/call", {"name": "get_training_status", "arguments": {"run_id": run_id}})
    p = json.loads(_text(r))
    assert p["ok"] is True
    assert p["state"] == "submitted"


def test_list_runs_ok():
    _submit(seed="1")
    _submit(seed="2")
    r = _rpc("tools/call", {"name": "list_runs", "arguments": {}})
    p = json.loads(_text(r))
    assert p["ok"] is True
    assert p["total"] >= 2
    assert isinstance(p["runs"], list)


def test_list_runs_state_filter():
    _submit(seed="s1")
    r = _rpc("tools/call", {"name": "list_runs", "arguments": {"state_filter": "done"}})
    p = json.loads(_text(r))
    # 所有 run 都是 submitted（mock engine 已禁用），state_filter=done 应该返回空
    for run in p["runs"]:
        assert run["state"] == "done"
    assert len(p["runs"]) == 0


def test_trigger_training_budget_not_int():
    r = _rpc(
        "tools/call",
        {
            "name": "trigger_training",
            "arguments": {
                "trainer": "x",
                "mandate": "m",
                "budget": {"total_tokens": "lots"},
                "trace_id": "y",
            },
        },
    )
    p = json.loads(_text(r))
    assert p["ok"] is False


def test_source_no_db_direct():
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8").lower()
    for kw in ["import psycopg", "import sqlite3", "postgres://", "cognitive_memory.db"]:
        assert kw not in src


def test_shell_source_name():
    assert server.SHELL_SOURCE == "l2.train.mcp"
