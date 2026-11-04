# -*- coding: utf-8 -*-
"""编排层延迟基线(47 SPEC D4: 壳 P50 ≤ in-process P50 + 45ms)。

两种模式:
  默认(fake): call_worker_tool 全链(真 mandate_gate + 真 47 registry
    + FakeShell)的 P50/P95 —— 编排层自身开销基线。
  --real:    换 stdio 真壳(stdio_shell_launcher, verifer/store_admin_status,
    l0.store-admin.mcp),管理器按 ADR-10 语义复用(全程单壳进程),与同口径
    fake 基线对比,给出真实传输分量与 D4 判定。

用法: python3 scripts/bench_worker_tool_call.py [rounds] [--real]
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.shell_handles import ShellHandleManager  # noqa: E402
from core.stdio_shell_launcher import stdio_launcher  # noqa: E402
from core.worker_tool_call import call_worker_tool  # noqa: E402

D4_BUDGET_MS = 45


class _FakeShell:
    def __init__(self, spec):
        self.spec = spec

    def call(self, tool, args=None):
        return {"ok": True, "data": {"tool": tool}}

    def close(self):
        pass


def _measure(rounds: int, role: str, tool: str, launcher) -> list:
    """同口径测量:管理器全程复用(ADR-10 单壳),逐轮计时 call_worker_tool。"""
    mgr = ShellHandleManager(launcher=launcher, flags={"enable_shell_handles": True})
    flags = {"enable_worker_tool_call": True}
    lat_ms = []
    try:
        for i in range(rounds):
            t0 = time.perf_counter()
            r = call_worker_tool(role, tool, manager=mgr, flags=flags, trace_id="bench-%d" % i)
            lat_ms.append((time.perf_counter() - t0) * 1000.0)
            assert r["ok"] is True, "round %d not ok: %s" % (i, r.get("error_code"))
    finally:
        mgr.close_all()
    lat_ms.sort()
    return lat_ms


def _summary(lat_ms: list) -> dict:
    return {
        "p50_ms": round(statistics.median(lat_ms), 3),
        "p95_ms": round(lat_ms[int(len(lat_ms) * 0.95) - 1], 3),
        "min_ms": round(lat_ms[0], 3),
        "max_ms": round(lat_ms[-1], 3),
    }


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rounds = int(args[0]) if args else 200
    real = "--real" in sys.argv

    if not real:
        # 历史口径(管理器每轮换新、FakeShell)保持可比性
        flags = {"enable_worker_tool_call": True}
        lat_ms = []
        for i in range(rounds):
            mgr = ShellHandleManager(
                launcher=lambda spec: _FakeShell(spec),
                flags={"enable_shell_handles": True},
            )
            t0 = time.perf_counter()
            r = call_worker_tool(
                "research", "recall", manager=mgr, flags=flags, trace_id="bench-%d" % i
            )
            lat_ms.append((time.perf_counter() - t0) * 1000.0)
            assert r["ok"] is True
            mgr.close_all()
        lat_ms.sort()
        report = {
            "mode": "orchestration_only",
            "rounds": rounds,
            "chain": "mandate_gate(real) -> registry_map(real) -> handle(fake shell)",
            **_summary(lat_ms),
            "d4_budget_ms": D4_BUDGET_MS,
            "orchestration_within_budget": statistics.median(lat_ms) < D4_BUDGET_MS,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    # --real: 真壳 D4 复测(verifier/store_admin_status → l0.store-admin.mcp)
    fake_lat = _measure(rounds, "verifier", "store_admin_status", lambda spec: _FakeShell(spec))
    try:
        real_lat = _measure(rounds, "verifier", "store_admin_status", stdio_launcher)
    except Exception as exc:
        print(
            json.dumps(
                {"mode": "real_shell", "error": "real shell launch/measure failed: %s" % exc},
                ensure_ascii=False,
            )
        )
        return 2
    fake_p50 = statistics.median(fake_lat)
    real_p50 = statistics.median(real_lat)
    transport_component = real_p50 - fake_p50
    report = {
        "mode": "real_shell",
        "rounds": rounds,
        "chain": "mandate_gate(real) -> registry_map(real) -> stdio shell(l0.store-admin.mcp)",
        "fake_baseline": _summary(fake_lat),
        "real_shell": _summary(real_lat),
        "transport_component_ms": round(transport_component, 3),
        "d4_budget_ms": D4_BUDGET_MS,
        "d4_ok": transport_component <= D4_BUDGET_MS,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["d4_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
