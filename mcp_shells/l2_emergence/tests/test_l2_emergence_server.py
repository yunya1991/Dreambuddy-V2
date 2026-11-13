"""l2.emergence.mcp 契约测试 — control 层 readonly-observe / 扫 48 涌现架构。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_shells.l2_emergence import server  # noqa: E402


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
    assert names == {"get_emergence_metrics", "list_experiments", "get_experiment_report"}


def test_all_tools_are_readonly():
    r = _rpc("tools/list")
    for t in r["result"]["tools"]:
        assert t["annotations"]["readOnlyHint"] is True


def test_initialize():
    r = _rpc("initialize")
    assert r["result"]["serverInfo"]["name"] == "l2.emergence.mcp"


def test_get_emergence_metrics_ok():
    r = _rpc("tools/call", {"name": "get_emergence_metrics", "arguments": {}})
    p = json.loads(_text(r))
    assert p["ok"] is True
    assert "available" in p
    assert "trials_summary" in p
    assert "meta" in p


def test_get_emergence_metrics_available_field_consistent():
    r = _rpc("tools/call", {"name": "get_emergence_metrics", "arguments": {}})
    p = json.loads(_text(r))
    assert isinstance(p["available"], bool)
    if p["available"]:
        assert (Path(server._EM_DIR)).exists()


def test_list_experiments_ok():
    r = _rpc("tools/call", {"name": "list_experiments", "arguments": {}})
    p = json.loads(_text(r))
    assert p["ok"] is True
    assert isinstance(p["runs"], list)
    assert "meta" in p


def test_list_experiments_limit_clamped():
    r = _rpc("tools/call", {"name": "list_experiments", "arguments": {"limit": 999}})
    p = json.loads(_text(r))
    assert len(p["runs"]) <= 200


def test_get_experiment_report_not_found():
    r = _rpc(
        "tools/call",
        {"name": "get_experiment_report", "arguments": {"run_id": "NONE-EXISTENT-RUN-XX99"}},
    )
    p = json.loads(_text(r))
    # 48-涌现架构/events/asil 里确实没这个 run
    assert p["ok"] is False or "run_id" in p.get("reason", "")
    if p["ok"] is False:
        assert p["error_code"] == "not_found"


def test_get_experiment_report_missing_arg():
    r = _rpc("tools/call", {"name": "get_experiment_report", "arguments": {}})
    p = json.loads(_text(r))
    assert p["ok"] is False
    assert p["error_code"] == "invalid"


def test_source_no_db_direct():
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8").lower()
    for kw in ["import psycopg", "import sqlite3", "postgres://"]:
        assert kw not in src


def test_source_no_llm_keywords_strict():
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8").lower()
    for kw in ["openai", "langchain", "chat.completion", "transformers"]:
        assert kw not in src


def test_shell_source_name():
    assert server.SHELL_SOURCE == "l2.emergence.mcp"


def test_emergence_dir_constant():
    assert "48-涌现架构" in str(server._EM_DIR)


def test_unknown_method():
    r = _rpc("unknown/method")
    assert r["error"]["code"] == -32601
