"""l1.strategy.mcp 四工具契约测试（只读 / 无大模型 / HTTP 封装 25-28 端口）。

覆盖：
  C1 tools/list 精确 = [list_strategies, get_strategy_version, get_approval_state, list_signal_triggers]
  C2 initialize / ping / serverInfo.name 正确
  C3 list_strategies 正常 + 不可达 FAIL-OPEN + scope 过滤
  C4 get_strategy_version 正常 + 空 strategy_id 校验 + 不可达 FAIL-OPEN
  C5 get_approval_state 正常 + 空 trace_id 校验 + 不可达 FAIL-OPEN
  C6 list_signal_triggers 默认 limit + 超限截断 + 不可达 FAIL-OPEN
  C7 所有工具 annotations.readOnlyHint=true，无 write
  C8 壳零大模型依赖（源码禁词扫描）
  C9 _http_get FAIL-OPEN：HTTPError / URLError / JSONDecodeError 都返回 ok=false
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_shells.l1_strategy import server  # noqa: E402


def _rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    req = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        req["params"] = params
    return server._handle_request(req)


def _content_text(response: dict) -> str:
    return response["result"]["content"][0]["text"]


# ════════════════════════════════════════════════════════════════════════════
# C1 tools/list
# ════════════════════════════════════════════════════════════════════════════


def test_tools_list_exact_four_tools():
    resp = _rpc("tools/list")
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {
        "list_strategies",
        "get_strategy_version",
        "get_approval_state",
        "list_signal_triggers",
    }


def test_tools_list_all_readonly_hint():
    """硬约束 H1 继承：L1 strategy 壳全只读。"""
    resp = _rpc("tools/list")
    for tool in resp["result"]["tools"]:
        ann = tool.get("annotations", {})
        assert ann.get("readOnlyHint") is True, f"{tool['name']} must be readOnly"
        assert ann.get("destructiveHint") is False or ann.get("destructiveHint") is None
    assert all(
        t["name"] not in ("forward_signal", "trigger_execution") for t in resp["result"]["tools"]
    )


# ════════════════════════════════════════════════════════════════════════════
# C2 initialize / ping
# ════════════════════════════════════════════════════════════════════════════


def test_initialize():
    init = _rpc("initialize")
    assert init["result"]["serverInfo"]["name"] == "l1.strategy.mcp"
    assert init["result"]["serverInfo"]["version"] == "0.1"
    assert init["result"]["protocolVersion"] == "2024-11-05"


def test_ping():
    ping = _rpc("ping")
    assert ping["result"] == {}


# ════════════════════════════════════════════════════════════════════════════
# C3 list_strategies
# ════════════════════════════════════════════════════════════════════════════


def test_list_strategies_ok():
    fake = {"ok": True, "entries": [{"strategy_id": "s1"}, {"strategy_id": "s2"}]}
    with patch.object(server, "_http_get", return_value=fake):
        resp = _rpc("tools/call", {"name": "list_strategies", "arguments": {}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is True
    assert payload["total"] == 2
    assert payload["strategies"] == [{"strategy_id": "s1"}, {"strategy_id": "s2"}]
    assert payload["meta"]["upstream"] == "26-策略管理模块"


def test_list_strategies_service_unavailable_fail_open():
    fake = {"ok": False, "error_code": "unavailable", "reason": "服务不可达"}
    with patch.object(server, "_http_get", return_value=fake):
        resp = _rpc("tools/call", {"name": "list_strategies", "arguments": {}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "unavailable"


def test_list_strategies_scope_passed_through():
    # 验证 scope 参数被正确传递给 _http_get
    captured = {}

    def fake_get(url):
        captured["url"] = url
        return {"ok": True, "entries": []}

    with patch.object(server, "_http_get", side_effect=fake_get):
        _rpc("tools/call", {"name": "list_strategies", "arguments": {"scope": "active"}})
    assert "scope=active" in captured["url"]


# ════════════════════════════════════════════════════════════════════════════
# C4 get_strategy_version
# ════════════════════════════════════════════════════════════════════════════


def test_get_strategy_version_ok():
    fake = {"ok": True, "strategy_id": "s1", "version": "1.3", "params": {}}
    with patch.object(server, "_http_get", return_value=fake):
        resp = _rpc(
            "tools/call",
            {"name": "get_strategy_version", "arguments": {"strategy_id": "s1"}},
        )
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is True
    assert payload["strategy_id"] == "s1"
    assert payload["meta"]["upstream"] == "26-策略管理模块"


def test_get_strategy_version_empty_id_rejected():
    resp = _rpc(
        "tools/call",
        {"name": "get_strategy_version", "arguments": {"strategy_id": ""}},
    )
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid"


def test_get_strategy_version_unavailable_fail_open():
    fake = {"ok": False, "error_code": "unavailable", "reason": "HTTP 连接拒绝"}
    with patch.object(server, "_http_get", return_value=fake):
        resp = _rpc(
            "tools/call",
            {"name": "get_strategy_version", "arguments": {"strategy_id": "s1"}},
        )
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "unavailable"


def test_get_strategy_version_url_contains_id():
    captured = {}

    def fake_get(url):
        captured["url"] = url
        return {"ok": True}

    with patch.object(server, "_http_get", side_effect=fake_get):
        _rpc(
            "tools/call",
            {"name": "get_strategy_version", "arguments": {"strategy_id": "STRAT-42"}},
        )
    assert "STRAT-42" in captured["url"]


# ════════════════════════════════════════════════════════════════════════════
# C5 get_approval_state
# ════════════════════════════════════════════════════════════════════════════


def test_get_approval_state_ok():
    fake = {"ok": True, "trace_id": "t1", "stage": "C5", "state": "pending"}
    with patch.object(server, "_http_get", return_value=fake):
        resp = _rpc(
            "tools/call",
            {"name": "get_approval_state", "arguments": {"trace_id": "t1"}},
        )
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is True
    assert payload["trace_id"] == "t1"
    assert payload["pipeline_state"]["stage"] == "C5"
    assert payload["meta"]["upstream"] == "27-策略治理审批系统"


def test_get_approval_state_empty_trace_id_rejected():
    resp = _rpc(
        "tools/call",
        {"name": "get_approval_state", "arguments": {"trace_id": None}},
    )
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid"


def test_get_approval_state_unavailable_fail_open():
    fake = {"ok": False, "error_code": "unavailable"}
    with patch.object(server, "_http_get", return_value=fake):
        resp = _rpc(
            "tools/call",
            {"name": "get_approval_state", "arguments": {"trace_id": "t1"}},
        )
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False


def test_get_approval_state_url_contains_trace_id():
    captured = {}

    def fake_get(url):
        captured["url"] = url
        return {"ok": True}

    with patch.object(server, "_http_get", side_effect=fake_get):
        _rpc(
            "tools/call",
            {"name": "get_approval_state", "arguments": {"trace_id": "TRACE-99"}},
        )
    assert "TRACE-99" in captured["url"]
    assert "pipeline/state" in captured["url"]


# ════════════════════════════════════════════════════════════════════════════
# C6 list_signal_triggers
# ════════════════════════════════════════════════════════════════════════════


def test_list_signal_triggers_ok():
    fake = {"ok": True, "events": [{"event": "entry"}, {"event": "exit"}]}
    with patch.object(server, "_http_get", return_value=fake):
        resp = _rpc("tools/call", {"name": "list_signal_triggers", "arguments": {}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is True
    assert payload["total"] == 2
    assert payload["meta"]["upstream"] == "28-策略信号触发模块"
    assert payload["meta"]["limit"] == 50


def test_list_signal_triggers_limit_capped():
    # limit > 500 → 截断为 500
    captured = {}

    def fake_get(url):
        captured["url"] = url
        return {"ok": True, "events": []}

    with patch.object(server, "_http_get", side_effect=fake_get):
        _rpc(
            "tools/call",
            {"name": "list_signal_triggers", "arguments": {"limit": 999}},
        )
    assert "limit=500" in captured["url"]


def test_list_signal_triggers_limit_floor():
    # limit < 1 → 至少 1
    captured = {}

    def fake_get(url):
        captured["url"] = url
        return {"ok": True, "events": []}

    with patch.object(server, "_http_get", side_effect=fake_get):
        _rpc(
            "tools/call",
            {"name": "list_signal_triggers", "arguments": {"limit": 0}},
        )
    assert "limit=1" in captured["url"]


def test_list_signal_triggers_invalid_limit_defaults():
    # 非数字 limit → 默认 50
    captured = {}

    def fake_get(url):
        captured["url"] = url
        return {"ok": True, "events": []}

    with patch.object(server, "_http_get", side_effect=fake_get):
        _rpc(
            "tools/call",
            {"name": "list_signal_triggers", "arguments": {"limit": "abc"}},
        )
    assert "limit=50" in captured["url"]


def test_list_signal_triggers_unavailable_fail_open():
    fake = {"ok": False, "error_code": "unavailable"}
    with patch.object(server, "_http_get", return_value=fake):
        resp = _rpc("tools/call", {"name": "list_signal_triggers", "arguments": {}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is False


# ════════════════════════════════════════════════════════════════════════════
# C9 _http_get FAIL-OPEN 矩阵
# ════════════════════════════════════════════════════════════════════════════


def test_http_get_urlerror_fail_open():
    """网络不可达 → ok=false + error_code=unavailable。"""
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("Connection refused"),
    ):
        result = server._http_get("http://127.0.0.1:1/nope")
    assert result["ok"] is False
    assert result["error_code"] == "unavailable"


def test_http_get_http_error_fail_open():
    """HTTP 4xx/5xx → ok=false + error_code=http_error。"""

    class _FakeHTTPError(urllib.error.HTTPError):
        def __init__(self):
            pass

        def read(self):
            return b"detail"

    err = _FakeHTTPError()
    err.code = 500
    with patch("urllib.request.urlopen", side_effect=err):
        result = server._http_get("http://127.0.0.1:1/x")
    assert result["ok"] is False
    assert result["error_code"] == "http_error"
    assert "500" in result["reason"]


def test_http_get_json_decode_error_fail_open():
    """非 JSON 响应 → ok=false + error_code=parse_error。"""

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"not json"

    with patch("urllib.request.urlopen", return_value=_FakeResp()):
        result = server._http_get("http://127.0.0.1:1/y")
    assert result["ok"] is False
    assert result["error_code"] == "parse_error"


def test_http_get_success_returns_dict():
    """正常响应 → ok=true + 完整 JSON。"""

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true, "entries": [1,2]}'

    with patch("urllib.request.urlopen", return_value=_FakeResp()):
        result = server._http_get("http://127.0.0.1:1/z")
    assert result["ok"] is True
    assert result["entries"] == [1, 2]


# ════════════════════════════════════════════════════════════════════════════
# C8 壳零大模型依赖 / 禁词扫描
# ════════════════════════════════════════════════════════════════════════════


def test_source_has_no_llm_keywords():
    """硬约束：l1.strategy 壳不含任何大模型调用关键字。"""
    source = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    forbidden = ["openai", "chat.completion", "anthropic", "langchain", "transformers"]
    for kw in forbidden:
        assert kw.lower() not in source.lower(), f"禁止词 {kw!r} 出现在 l1.strategy 源码"


def test_serverinfo_name_is_correct():
    assert server.SHELL_SOURCE == "l1.strategy.mcp"


# ════════════════════════════════════════════════════════════════════════════
# 未知 method → -32601
# ════════════════════════════════════════════════════════════════════════════


def test_unknown_method_returns_error():
    resp = _rpc("unknown/method")
    assert "error" in resp
    assert resp["error"]["code"] == -32601
