"""P0-1：L2 MCP 壳 meta 计量补齐测试（GAP-01 的壳侧一半）。

覆盖:
  - 4 个 L2 壳的工具结果都带 meta.model / tokens_used / budget_remaining
  - 计量取自结果自带 budget 快照；缺失时按 total_tokens - tokens_used 推导
  - submit 类只有申请额度时：tokens_used=0、remaining=申请额度
  - model=none 的纯指标壳（emergence）tokens 强制 0
  - 非 L2 壳完全不受影响；既有 meta 键保留
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_shells._shared.l2_meta import attach_l2_meta  # noqa: E402
from mcp_shells._shared.shell_runtime import handle_request  # noqa: E402


def test_dreamos_budget_meta_from_result_snapshot():
    env = {
        "ok": True,
        "result": {
            "job_id": "job-1",
            "budget": {"total_tokens": 1000, "tokens_used": 300, "budget_remaining": 700},
        },
        "meta": {"shell": "l2.dreamos.mcp", "mock_engine": True},
    }
    out = attach_l2_meta(env, shell_id="l2.dreamos.mcp", tool_name="get_result")
    meta = out["meta"]
    assert meta["layer"] == "L2"
    assert meta["capability_id"] == "l2.dreamos.mcp"
    assert meta["run_id"] == "job-1"
    assert meta["model"] == "unspecified"
    assert meta["tokens_used"] == 300
    assert meta["budget_remaining"] == 700
    assert meta["shell"] == "l2.dreamos.mcp"  # 既有键保留
    assert meta["mock_engine"] is True


def test_remaining_derived_from_total_minus_used():
    env = {"ok": True, "result": {"budget": {"total_tokens": 500, "tokens_used": 50}}}
    out = attach_l2_meta(env, shell_id="l2.train.mcp", tool_name="get_train")
    assert out["meta"]["tokens_used"] == 50
    assert out["meta"]["budget_remaining"] == 450


def test_submit_uses_requested_allocation():
    env = {"ok": True, "job_id": "job-2"}
    out = attach_l2_meta(
        env,
        shell_id="l2.train.mcp",
        tool_name="trigger_training",
        arguments={"budget": {"total_tokens": 800}},
    )
    assert out["meta"]["tokens_used"] == 0
    assert out["meta"]["budget_remaining"] == 800


def test_no_llm_shell_is_zero_token():
    env = {"ok": True, "result": {"d1": 0.3}}
    out = attach_l2_meta(env, shell_id="l2.emergence.mcp", tool_name="get_emergence")
    assert out["meta"]["model"] == "none"
    assert out["meta"]["tokens_used"] == 0


def test_model_argument_wins():
    env = {"ok": True, "result": {"budget": {"total_tokens": 10, "tokens_used": 4}}}
    out = attach_l2_meta(
        env,
        shell_id="l2.debate.mcp",
        tool_name="start_debate",
        arguments={"model": "qwen-max"},
    )
    assert out["meta"]["model"] == "qwen-max"
    assert out["meta"]["tokens_used"] == 4


def test_non_l2_shell_untouched():
    env = {"ok": True, "data": {"x": 1}, "meta": {}}
    assert attach_l2_meta(env, shell_id="l1.trading.mcp", tool_name="quote") is env
    assert env["meta"] == {}


def test_degraded_envelope_still_metered():
    env = {
        "ok": False,
        "degraded": True,
        "error_code": "unavailable",
        "meta": {"reason": "boom"},
    }
    out = attach_l2_meta(env, shell_id="l2.dreamos.mcp", tool_name="get_result")
    assert out["meta"]["degraded"] is True
    assert out["meta"]["tokens_used"] == 0


def test_handle_request_fills_meta_for_l2_shell():
    def handler(_args):
        return {
            "ok": True,
            "job_id": "job-9",
            "budget": {"total_tokens": 100, "tokens_used": 10, "budget_remaining": 90},
        }

    resp = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_budget", "arguments": {}},
        },
        shell_id="l2.dreamos.mcp",
        tools=[],
        handlers={"get_budget": handler},
    )
    envelope = json.loads(resp["result"]["content"][0]["text"])
    assert envelope["meta"]["tokens_used"] == 10
    assert envelope["meta"]["budget_remaining"] == 90
    assert envelope["meta"]["model"]
    assert resp["result"]["isError"] is False
