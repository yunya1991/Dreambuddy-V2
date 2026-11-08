#!/usr/bin/env python3
"""数据壳（l0.data.mcp）只读契约测试 — M2⑤ 验收。

覆盖：
  - tools/list 工具面与注册表登记一致（4 工具 + annotations）
  - 统一信封结构（ok/data/source/error_code）
  - 写面 Ban 默认禁：data_store_write 未授权调用被明确拒绝（非静默）
  - 只读工具 invalid 入参返回 error_code=invalid
"""

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = _REPO_ROOT / "mcp_shells" / "l0_data" / "server.py"


def _call_tool(name: str, arguments: dict) -> dict:
    """拉起数据壳进程，initialize + tools/call，返回解析后的信封。"""
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
        encoding="utf-8",
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
        encoding="utf-8",
        timeout=60,
        cwd=str(_REPO_ROOT),
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    resp = json.loads(lines[-1])
    return resp["result"]["tools"]


def test_tools_list_matches_registry():
    """工具面与注册表（mcp_capabilities.yaml l0.data.mcp）一致：4 工具 + annotations。"""
    tools = _tools_list()
    names = [t["name"] for t in tools]
    assert names == ["data_fetch", "data_collect_once", "data_store_read", "data_store_write"]
    by_name = {t["name"]: t for t in tools}
    # 只读工具 annotations
    for n in ("data_fetch", "data_collect_once", "data_store_read"):
        assert by_name[n]["annotations"]["readOnlyHint"] is True
        assert by_name[n]["annotations"]["destructiveHint"] is False
    # 写工具 annotations
    assert by_name["data_store_write"]["annotations"]["readOnlyHint"] is False
    assert by_name["data_store_write"]["annotations"]["destructiveHint"] is True


def test_write_banned_by_default():
    """SPEC §3.3：写面默认禁，未授权调用明确拒绝（ok=false + error_code=conflict）。"""
    env = _call_tool("data_store_write", {"table": "t", "data": {"x": 1}})
    assert env["ok"] is False
    assert env["error_code"] == "conflict"
    assert "Mandate" in json.dumps(env)


def test_data_fetch_invalid_scope():
    """只读工具 invalid 入参：error_code=invalid，统一信封结构完整。"""
    env = _call_tool("data_fetch", {})
    assert env["ok"] is False
    assert env["error_code"] == "invalid"
    assert env["source"] == "l0.data.mcp"
    assert "timestamp" in env and "version" in env


def test_data_store_read_requires_table():
    """data_store_read 缺 table：error_code=invalid。"""
    env = _call_tool("data_store_read", {})
    assert env["ok"] is False
    assert env["error_code"] == "invalid"


def test_data_store_read_unsupported_table():
    """表白名单：非 mm_metrics 的表明确 invalid（禁任意表查询）。"""
    env = _call_tool("data_store_read", {"table": "tr_trades"})
    assert env["ok"] is False
    assert env["error_code"] == "invalid"
    assert "whitelist" in json.dumps(env)


def test_data_store_read_requires_metric_filters():
    """mm_metrics 缺 sub_category/metric_name：invalid（防全表扫描）。"""
    env = _call_tool("data_store_read", {"table": "mm_metrics", "limit": 5})
    assert env["ok"] is False
    assert env["error_code"] == "invalid"
    assert "sub_category" in json.dumps(env)


def test_data_store_read_dal_wired():
    """DAL 接线验证：mm_metrics 合法 filters 不得再返回 import/get_container 类错误。

    本地 19-数据访问层/data/dreambuddy_core.db 存在时应 ok=True；
    DAL 或库不可用时允许 unavailable（FAIL-OPEN），但 reason 必须是
    repo/查询层错误，而非 sys.path/API 层错误（回归历史根因）。
    """
    env = _call_tool(
        "data_store_read",
        {
            "table": "mm_metrics",
            "filters": {
                "sub_category": "tether_current",
                "metric_name": "usdt_circulating_usd_bln",
            },
            "limit": 5,
        },
    )
    if env["ok"]:
        assert isinstance(env["data"]["rows"], list)
        assert env["data"]["table"] == "mm_metrics"
    else:
        assert env["error_code"] == "unavailable"
        reason = json.dumps(env)
        assert "No module named" not in reason
        assert "get_container" not in reason
