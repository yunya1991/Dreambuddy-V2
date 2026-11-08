# -*- coding: utf-8 -*-
"""统一壳运行时（shell_runtime）契约测试 — P3。

覆盖：
  - MCP 协议版本协商（请求版本回显 / 未知版本回退）
  - tools/list 从 registry 派生（工具顺序、未登记 handler 不暴露）
  - handler 返回值归一化（dict → 信封 / 异常 → unavailable）
"""

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.shell_runtime import (  # noqa: E402
    DEFAULT_PROTOCOL_VERSION,
    build_tool_list,
    handle_request,
    negotiate_protocol_version,
)

_SHELL_ID = "l0.data.mcp"
_DEFS = {
    "data_fetch": {"description": "d"},
    "data_collect_once": {"description": "d"},
    "data_store_read": {"description": "d"},
    "data_store_write": {"description": "d"},
}


def test_negotiate_known_version_echoes():
    assert negotiate_protocol_version("2025-06-18") == "2025-06-18"
    assert negotiate_protocol_version("2024-11-05") == "2024-11-05"


def test_negotiate_unknown_or_missing_falls_back():
    assert negotiate_protocol_version("2099-01-01") == DEFAULT_PROTOCOL_VERSION
    assert negotiate_protocol_version(None) == DEFAULT_PROTOCOL_VERSION
    assert negotiate_protocol_version(123) == DEFAULT_PROTOCOL_VERSION


def test_initialize_echoes_requested_version():
    tools = build_tool_list(_SHELL_ID, _DEFS)
    resp = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        shell_id=_SHELL_ID,
        tools=tools,
        handlers={},
    )
    assert resp["result"]["protocolVersion"] == "2025-06-18"
    assert resp["result"]["serverInfo"]["name"] == _SHELL_ID


def test_tools_list_follows_registry_and_hides_unregistered_handler():
    extended = dict(_DEFS, internal_debug={"description": "not registered"})
    tools = build_tool_list(_SHELL_ID, extended)
    names = [t["name"] for t in tools]
    assert names == ["data_fetch", "data_collect_once", "data_store_read", "data_store_write"]
    assert "internal_debug" not in names


def test_missing_registry_tool_definition_raises():
    partial = dict(_DEFS)
    partial.pop("data_store_write")
    with pytest.raises(Exception, match="缺少 code 定义"):
        build_tool_list(_SHELL_ID, partial)


def _call(handler):
    tools = build_tool_list(_SHELL_ID, _DEFS)
    resp = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "data_fetch", "arguments": {"scope": "x"}},
        },
        shell_id=_SHELL_ID,
        tools=tools,
        handlers={"data_fetch": handler},
    )
    envelope = json.loads(resp["result"]["content"][0]["text"])
    return envelope, resp["result"]["isError"]


def test_handler_dict_without_ok_is_wrapped():
    envelope, is_error = _call(lambda args: {"rows": []})
    assert envelope["ok"] is True
    assert envelope["data"] == {"rows": []}
    assert envelope["source"] == _SHELL_ID
    assert is_error is False


def test_handler_exception_returns_unavailable_envelope():
    def boom(args):
        raise RuntimeError("boom")

    envelope, is_error = _call(boom)
    assert envelope["ok"] is False
    assert envelope["error_code"] == "unavailable"
    assert envelope["degraded"] is True
    assert is_error is True