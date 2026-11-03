# -*- coding: utf-8 -*-
"""RED: Worker 工具调用链接线(ADR-4/9/10 落线, T-DSH-P4)。

链路: mandate_gate(ADR-4 能力集+H7 写工具纵深) → tool→shell 解析
(47 registry 唯一载体) → ShellHandleManager(ADR-10 单壳句柄) → 壳调用。

错误语义(47 SPEC §3.2 B1 定稿, Worker 工具调用=主功能禁 FAIL-OPEN 伪装):
  开关关 → ok=false + error_code=disabled
  越权   → ok=false + error_code=forbidden(gate 已审计留痕)
  未知工具 → ok=false + error_code=not_found
  壳不可用/调用异常 → ok=false + error_code=unavailable + meta.degraded=true
"""

from __future__ import annotations

from core.shell_handles import ShellHandleManager
from core.worker_tool_call import call_worker_tool


class FakeShell:
    def __init__(self, spec, fail_tools=None):
        self.spec = spec
        self.fail_tools = fail_tools or set()
        self.closed = False

    def call(self, tool, args=None):
        if tool in self.fail_tools:
            raise RuntimeError("shell crashed on %s" % tool)
        return {"ok": True, "data": {"tool": tool, "echo": args}}

    def close(self):
        self.closed = True


def make_manager(fail_tools=None):
    def launcher(spec):
        return FakeShell(spec, fail_tools=fail_tools)

    return ShellHandleManager(launcher=launcher, flags={"enable_shell_handles": True})


ON = {"enable_worker_tool_call": True}
OFF = {}


def allow_all(role, tool):
    return True


def deny_all(role, tool):
    return False


# ---------------------------------------------------------------------------
# 开关与门禁
# ---------------------------------------------------------------------------


class TestSwitchAndGate:
    def test_switch_off_disabled(self):
        r = call_worker_tool(
            "research", "recall", checker=allow_all, manager=make_manager(), flags=OFF
        )
        assert r["ok"] is False
        assert r["error_code"] == "disabled"

    def test_forbidden_by_gate(self):
        r = call_worker_tool(
            "research", "recall", checker=deny_all, manager=make_manager(), flags=ON
        )
        assert r["ok"] is False
        assert r["error_code"] == "forbidden"

    def test_forbidden_does_not_touch_manager(self):
        mgr = make_manager()
        r = call_worker_tool("research", "recall", checker=deny_all, manager=mgr, flags=ON)
        assert r["error_code"] == "forbidden"
        assert mgr.stats() == {}  # 未取任何句柄

    def test_unknown_tool_not_found(self):
        r = call_worker_tool(
            "research", "no_such_tool", checker=allow_all, manager=make_manager(), flags=ON
        )
        assert r["ok"] is False
        assert r["error_code"] == "not_found"

    def test_bad_input(self):
        r = call_worker_tool(None, "recall", checker=allow_all, manager=make_manager(), flags=ON)
        assert r["ok"] is False
        r2 = call_worker_tool("research", None, checker=allow_all, manager=make_manager(), flags=ON)
        assert r2["ok"] is False


# ---------------------------------------------------------------------------
# 正常链路
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_call_ok_envelope(self):
        r = call_worker_tool(
            "research",
            "recall",
            args={"context": "x"},
            checker=allow_all,
            manager=make_manager(),
            flags=ON,
            trace_id="t-1",
        )
        assert r["ok"] is True
        assert r["data"]["tool"] == "recall"
        assert r["meta"]["trace_id"] == "t-1"

    def test_tool_routed_to_owning_shell(self):
        """data_fetch 属 l0.data.mcp;eval_analyze 属 l0.eval.mcp(47 registry)。"""
        mgr = make_manager()
        r1 = call_worker_tool("engineer", "data_fetch", checker=allow_all, manager=mgr, flags=ON)
        r2 = call_worker_tool("verifier", "eval_analyze", checker=allow_all, manager=mgr, flags=ON)
        assert r1["ok"] is True and r2["ok"] is True
        assert sorted(mgr.stats().keys()) == ["l0.data.mcp", "l0.eval.mcp"]

    def test_same_shell_shared_across_calls(self):
        """同壳多工具调用 → 单壳实例(ADR-10)。"""
        mgr = make_manager()
        call_worker_tool("engineer", "data_fetch", checker=allow_all, manager=mgr, flags=ON)
        call_worker_tool("engineer", "data_store_read", checker=allow_all, manager=mgr, flags=ON)
        assert mgr.stats()["l0.data.mcp"]["handles_issued"] == 2


# ---------------------------------------------------------------------------
# B1 壳故障语义
# ---------------------------------------------------------------------------


class TestShellFailure:
    def test_shell_unavailable_when_handle_none(self):
        mgr = ShellHandleManager(launcher=None, flags={"enable_shell_handles": True})
        r = call_worker_tool("research", "recall", checker=allow_all, manager=mgr, flags=ON)
        assert r["ok"] is False
        assert r["error_code"] == "unavailable"
        assert r["meta"]["degraded"] is True

    def test_shell_call_exception_unavailable(self):
        mgr = make_manager(fail_tools={"recall"})
        r = call_worker_tool("research", "recall", checker=allow_all, manager=mgr, flags=ON)
        assert r["ok"] is False
        assert r["error_code"] == "unavailable"
        assert r["meta"]["degraded"] is True


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------


class TestAudit:
    def test_recorder_receives_outcome(self):
        records = []

        def recorder(entry):
            records.append(entry)

        call_worker_tool(
            "research",
            "recall",
            checker=allow_all,
            manager=make_manager(),
            flags=ON,
            trace_id="t-9",
            recorder=recorder,
        )
        assert len(records) == 1
        e = records[0]
        assert e["role"] == "research" and e["tool"] == "recall"
        assert e["ok"] is True and e["trace_id"] == "t-9"

    def test_recorder_failure_does_not_break_call(self):
        def bad_recorder(entry):
            raise RuntimeError("audit sink down")

        r = call_worker_tool(
            "research",
            "recall",
            checker=allow_all,
            manager=make_manager(),
            flags=ON,
            recorder=bad_recorder,
        )
        assert r["ok"] is True
