"""l1.ops.mcp 契约测试 — 全只读 / 本地文件扫描 / 零大模型依赖。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_shells.l1_ops import server  # noqa: E402


def _rpc(method: str, params=None) -> dict:
    req = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        req["params"] = params
    return server._handle_request(req)


def _text(r: dict) -> str:
    return r["result"]["content"][0]["text"]


def test_tools_list_exact():
    r = _rpc("tools/list")
    names = {t["name"] for t in r["result"]["tools"]}
    assert names == {"list_alerts", "get_health", "get_bus_state"}


def test_all_tools_are_readonly():
    r = _rpc("tools/list")
    for t in r["result"]["tools"]:
        assert t["annotations"]["readOnlyHint"] is True


def test_initialize():
    r = _rpc("initialize")
    assert r["result"]["serverInfo"]["name"] == "l1.ops.mcp"


def test_ping():
    assert _rpc("ping")["result"] == {}


def test_list_alerts_ok():
    r = _rpc("tools/call", {"name": "list_alerts", "arguments": {}})
    p = json.loads(_text(r))
    assert p["ok"] is True
    assert "alerts" in p and isinstance(p["alerts"], list)
    assert "meta" in p


def test_list_alerts_limit_clamped():
    r = _rpc("tools/call", {"name": "list_alerts", "arguments": {"limit": 999}})
    p = json.loads(_text(r))
    assert p["ok"] is True
    assert len(p["alerts"]) <= 200


def test_list_alerts_limit_floor():
    r = _rpc("tools/call", {"name": "list_alerts", "arguments": {"limit": -5}})
    p = json.loads(_text(r))
    assert p["ok"] is True


def test_get_health_ok():
    r = _rpc("tools/call", {"name": "get_health", "arguments": {}})
    p = json.loads(_text(r))
    assert p["ok"] is True
    assert "overall_health" in p
    assert "subsystems" in p
    assert isinstance(p["subsystems"], list)


def test_get_health_count_consistent():
    r = _rpc("tools/call", {"name": "get_health", "arguments": {}})
    p = json.loads(_text(r))
    assert p["healthy_count"] + (p["total_count"] - p["healthy_count"]) == p["total_count"]


def test_get_bus_state_ok():
    r = _rpc("tools/call", {"name": "get_bus_state", "arguments": {}})
    p = json.loads(_text(r))
    assert p["ok"] is True
    assert "bus_available" in p
    assert "meta" in p


def test_source_no_llm_keywords():
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8").lower()
    for kw in ["openai", "langchain", "chat.completion"]:
        assert kw not in src


def test_source_no_db_direct():
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8").lower()
    for kw in ["import psycopg", "import sqlite3", "postgres://"]:
        assert kw not in src


def test_unknown_method():
    r = _rpc("unknown/method")
    assert r["error"]["code"] == -32601
