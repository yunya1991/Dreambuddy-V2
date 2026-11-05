#!/usr/bin/env python3
"""trace_id 贯穿断言 — V5 验收（4 壳 × MCP_TRACE_ID 透传）。

宿主 MCP 在 env 注入 `MCP_TRACE_ID`，壳信封必须原样带出（SPEC §3.6 五跳透传，
V5 trace_id 贯穿率 100%）。本测试只走各壳的 invalid / not_found 只读路径：
零写盘、零外部服务依赖，CI 可直接跑。

覆盖壳：l0.data.mcp / l0.eval.mcp / l0.rea.mcp / l0.store-admin.mcp / l0.trade-exec.mcp
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
TRACE_ID = "trace-v5-coverage-0001"

_CASES = [
    (
        "l0_data",
        "l0.data.mcp",
        "data_fetch",
        {},  # 缺 scope → invalid，不触 DB
    ),
    (
        "l0_eval",
        "l0.eval.mcp",
        "eval_analyze",
        {},  # 缺 eval_id → invalid，不触 45 HTTP
    ),
    (
        "l0_rea",
        "l0.rea.mcp",
        "poll_rea_analyze",
        {"job_id": "job-nonexistent-v5"},  # job 不存在 → not_found，只读 JSONL
    ),
    (
        "l0_store_admin",
        "l0.store-admin.mcp",
        "store_admin_query",
        {},  # 缺 repo → invalid，不触 19-DAL
    ),
    (
        "l0_trade_exec",
        "l0.trade-exec.mcp",
        "place_order",
        {},  # 缺 symbol/side/size → invalid，零写盘、零行情请求
    ),
]


def _call_tool(shell: str, name: str, arguments: dict, store_path: Path) -> dict:
    """拉起壳进程（env 带 MCP_TRACE_ID），返回解析后的统一信封。

    AGENT_MAIL_SHADOW_STORE 指向测试临时路径，隔离 shadow store，
    避免测试调用污染生产 trajectories.jsonl。
    """
    server = _REPO_ROOT / "mcp_shells" / shell / "server.py"
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
    env = dict(os.environ)
    env["MCP_TRACE_ID"] = TRACE_ID
    env["AGENT_MAIL_SHADOW_STORE"] = str(store_path)
    # trade-exec 壳 import 时会初始化 paper 账本，隔离到测试临时目录，避免污染生产 ledger
    env["TRADE_EXEC_LEDGER_DIR"] = str(store_path.parent / "ledger")
    proc = subprocess.run(
        [sys.executable, str(server)],
        input=reqs,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    assert lines, f"no stdout; stderr={proc.stderr}"
    resp = json.loads(lines[-1])
    assert "result" in resp, f"rpc error: {resp}"
    return json.loads(resp["result"]["content"][0]["text"])


@pytest.mark.parametrize(
    "shell,source,tool,arguments",
    _CASES,
    ids=[c[0] for c in _CASES],
)
def test_trace_id_passthrough(shell, source, tool, arguments, tmp_path):
    """MCP_TRACE_ID 从宿主 env 贯穿到壳信封，且 source/version 与注册表一致。"""
    env = _call_tool(shell, tool, arguments, tmp_path / "traces.jsonl")
    assert env["trace_id"] == TRACE_ID
    assert env["source"] == source
    # 注册表 envelope_version 统一 0.1（V6 对齐实现）
    assert env["version"] == "0.1"
    # 只读失败路径：统一信封三态可区分（V3）
    assert env["ok"] is False
    assert env["error_code"] in ("invalid", "not_found")
