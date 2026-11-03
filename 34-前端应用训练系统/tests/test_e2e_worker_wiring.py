# -*- coding: utf-8 -*-
"""E2E: Worker 工具调用接线全链(T-DSH-P4)。

真 47 registry + 真 mandate_gate(默认 checker) + ShellHandleManager(假 launcher)
+ settle 五通道: 验证 ADR-4(能力集)/ADR-9+H7(写工具)/ADR-10(单壳)/B1(错误语义)
在编排链路上的闭环,以及开关全关时的 FAIL-OPEN 不崩。
"""

from __future__ import annotations

from core.settle_channels import SETTLE_CHANNELS, settle_via_channels
from core.shell_handles import ShellHandleManager
from core.worker_tool_call import call_worker_tool

ON = {"enable_worker_tool_call": True}


class FakeShell:
    def __init__(self, spec):
        self.spec = spec
        self.closed = False

    def call(self, tool, args=None):
        return {"ok": True, "data": {"tool": tool, "by": self.spec["shell_id"]}}

    def close(self):
        self.closed = True


def make_manager():
    return ShellHandleManager(
        launcher=lambda spec: FakeShell(spec),
        flags={"enable_shell_handles": True},
    )


class TestEndToEndWiring:
    def test_authorized_call_real_gate(self):
        """research 调 recall(角色集内) → 真 gate 放行 → 壳调用 ok。"""
        audits = []
        r = call_worker_tool(
            "research",
            "recall",
            args={"context": "e2e"},
            manager=make_manager(),
            flags=ON,
            trace_id="e2e-1",
            recorder=audits.append,
        )
        assert r["ok"] is True
        assert r["data"]["by"] == "l0.cognition.mcp"
        assert audits[0]["trace_id"] == "e2e-1"

    def test_cross_role_forbidden_real_gate(self):
        """engineer 调 eval_analyze(不在 engineer 集) → forbidden(ADR-4)。"""
        r = call_worker_tool("engineer", "eval_analyze", manager=make_manager(), flags=ON)
        assert r["ok"] is False and r["error_code"] == "forbidden"

    def test_write_tool_blocked_real_gate(self):
        """record(requires_mandate) → H7 纵深拦截,任何 Worker 角色都 forbidden。"""
        r = call_worker_tool("research", "record", manager=make_manager(), flags=ON)
        assert r["ok"] is False and r["error_code"] == "forbidden"

    def test_single_shell_across_roles(self):
        """research/engineer 都调 cognition 壳工具 → 同进程单壳(ADR-10)。"""
        mgr = make_manager()
        call_worker_tool("research", "recall", manager=mgr, flags=ON)
        call_worker_tool("engineer", "recall", manager=mgr, flags=ON)
        assert list(mgr.stats().keys()) == ["l0.cognition.mcp"]
        assert mgr.stats()["l0.cognition.mcp"]["handles_issued"] == 2

    def test_result_settles_through_channels(self):
        """调用结果 → settle 五系统全通道(P3 已落地) → 全 ok。"""
        r = call_worker_tool("research", "recall", manager=make_manager(), flags=ON)
        flags = {"enable_settle_channel_%s" % c: True for c in SETTLE_CHANNELS}
        channels = {c: (lambda res, ctx, _c=c: {"channel": _c}) for c in SETTLE_CHANNELS}
        report = settle_via_channels(r, {"trace_id": "e2e-2"}, channels=channels, flags=flags)
        assert all(v["status"] == "ok" for v in report.values())
        assert set(report.keys()) == set(SETTLE_CHANNELS)

    def test_all_switches_off_fail_open(self):
        """开关全关 → 明确错误不崩(H1/H2);settle 全 disabled。"""
        r = call_worker_tool("research", "recall", manager=make_manager(), flags={})
        assert r["ok"] is False and r["error_code"] == "disabled"
        report = settle_via_channels(r, {}, channels={}, flags={})
        assert all(v["status"] in ("disabled", "unconfigured") for v in report.values())
