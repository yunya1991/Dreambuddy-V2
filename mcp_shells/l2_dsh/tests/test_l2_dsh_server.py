"""l2.dsh.mcp 契约测试 — L2-E DSH 编排面只读（GAP-03 / SPEC-56 P2）。

覆盖：
  C1 tools/list 精确 = [get_router_summary, get_ticket_status, get_worker_roster]
  C2 全只读注解 + initialize
  C3 registry ↔ _TOOL_DEFS 一致（shell_runtime 派生）
  C4 Router 摘要：状态计数 / 漂移 / 缺失快照
  C5 Ticket 状态：单票 / 列表 / not_found / invalid
  C6 Worker 角色：白名单 + 自检 problems
  C7 壳零 DB 直连 + 零 LLM 依赖 + 只读（源码禁词扫描）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_shells._shared.shell_runtime import build_tool_list  # noqa: E402
from mcp_shells.l2_dsh import server  # noqa: E402


def _rpc(method: str, params=None) -> dict:
    req = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        req["params"] = params
    return server._handle_request(req)


def _call(name: str, arguments: dict) -> dict:
    return json.loads(
        _rpc("tools/call", {"name": name, "arguments": arguments})["result"]["content"][0]["text"]
    )


@pytest.fixture()
def l0_root(tmp_path, monkeypatch):
    """隔离 L0 根：写两票 live（一票无 worker）+ 一票 ended。"""
    store = tmp_path / "34-前端应用训练系统" / "dsh_tickets.jsonl"
    store.parent.mkdir(parents=True)
    records = [
        {"ticket_id": "TK-a", "state": "live", "worker_id": "w-1", "stored_at": 1},
        {"ticket_id": "TK-b", "state": "live", "stored_at": 2},
        {
            "ticket_id": "TK-c",
            "state": "ended",
            "stored_at": 3,
            "history": [{"to": "live"}, {"to": "ended"}],
        },
    ]
    store.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv("DREAMBUDDY_L0_ROOT", str(tmp_path))
    return tmp_path


def test_tools_list_exact():
    r = _rpc("tools/list")
    names = {t["name"] for t in r["result"]["tools"]}
    assert names == {"get_router_summary", "get_ticket_status", "get_worker_roster"}


def test_all_tools_are_readonly():
    for t in _rpc("tools/list")["result"]["tools"]:
        assert t["annotations"]["readOnlyHint"] is True
        assert t["annotations"]["destructiveHint"] is False


def test_initialize():
    r = _rpc("initialize")
    assert r["result"]["serverInfo"]["name"] == "l2.dsh.mcp"


def test_registry_matches_tool_defs():
    derived = {t["name"] for t in build_tool_list(server.SHELL_SOURCE, server._TOOL_DEFS)}
    assert derived == set(server._TOOL_DEFS)


def test_router_summary_counts_and_drift(l0_root):
    env = _call("get_router_summary", {"limit": 10})
    assert env["ok"] is True
    data = env["data"]
    assert data["counts"]["total"] == 3
    assert data["counts"]["live"] == 2
    assert data["counts"]["ended"] == 1
    assert data["drift"] == ["TK-b"]
    assert data["store_exists"] is True
    assert env["meta"]["loop_pass_stats"] == "in_process_only_unavailable"
    assert env["source"] == "l2.dsh.mcp"


def test_router_summary_missing_store_degrades_to_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAMBUDDY_L0_ROOT", str(tmp_path))
    env = _call("get_router_summary", {})
    assert env["ok"] is True
    assert env["data"]["counts"]["total"] == 0
    assert env["data"]["store_exists"] is False


def test_ticket_status_by_id(l0_root):
    env = _call("get_ticket_status", {"ticket_id": "TK-c"})
    assert env["ok"] is True
    ticket = env["data"]["ticket"]
    assert ticket["ticket_id"] == "TK-c"
    assert ticket["state"] == "ended"
    assert ticket["history_count"] == 2
    assert len(ticket["history_tail"]) == 2


def test_ticket_status_not_found(l0_root):
    env = _call("get_ticket_status", {"ticket_id": "TK-none"})
    assert env["ok"] is False
    assert env["error_code"] == "not_found"


def test_ticket_status_list_by_state(l0_root):
    env = _call("get_ticket_status", {"state": "live"})
    assert env["ok"] is True
    assert env["data"]["matched_total"] == 2
    assert {t["ticket_id"] for t in env["data"]["tickets"]} == {"TK-a", "TK-b"}


def test_ticket_status_invalid_state(l0_root):
    env = _call("get_ticket_status", {"state": "bogus"})
    assert env["ok"] is False
    assert env["error_code"] == "invalid"


def test_worker_roster_ok():
    env = _call("get_worker_roster", {})
    assert env["ok"] is True
    assert env["data"]["role_count"] >= 1
    assert isinstance(env["data"]["problems"], list)
    assert env["meta"]["readonly"] is True


def test_unknown_method():
    assert _rpc("unknown/method")["error"]["code"] == -32601


def test_source_no_db_direct():
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8").lower()
    for kw in [
        "import psycopg",
        "import sqlite3",
        "postgres://",
        "postgresql://",
        "create table",
        "insert into",
    ]:
        assert kw not in src


def test_source_no_llm_keywords():
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8").lower()
    for kw in ["openai", "langchain", "chat.completion", "transformers", "ollama"]:
        assert kw not in src


def test_shell_source_name():
    assert server.SHELL_SOURCE == "l2.dsh.mcp"
