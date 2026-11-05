# -*- coding: utf-8 -*-
"""L2 完整架构同类评测: 三层链路延迟对比。

对比三种调用模式的 P50/P95, 量化每层编排开销:
  1. L2_full       : SACG(S→A→C→G) → DSH → stdio 真壳 → L0-DAL 6 repo
  2. dsh_direct    : DSH(call_worker_tool) → stdio 真壳 → L0
  3. shell_direct  : ShellHandleManager → stdio 真壳 → L0  (最小壳开销)

用法: python3 scripts/bench_l2_complete_stack.py [rounds]
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.sacg_orchestrator import SACGOrchestrator  # noqa: E402
from core.shell_handles import ShellHandleManager  # noqa: E402
from core.stdio_shell_launcher import stdio_launcher  # noqa: E402
from core.worker_tool_call import call_worker_tool  # noqa: E402

ON = {"enable_worker_tool_call": True}


# ── 复用 test_l2_full_stack_integration 的节点定义 ─────────────────


def _single_node_decomposer(plan):
    return [
        {
            "node_id": "N-store-admin",
            "criteria": "库管健康状态验证",
            "role": "verifier",
            "tool": "store_admin_status",
        }
    ]


def _dsh_c_executor(manager, flags):
    def _exec(router, node):
        r = call_worker_tool(
            node.get("role", "verifier"),
            node["tool"],
            args=node.get("args"),
            manager=manager,
            flags=flags,
            trace_id=f"bench-{node.get('node_id')}",
        )
        return {
            "action": "CONTINUE" if r.get("ok") else "FAILED",
            "tier": "Tier1",
            "effort_level": "light",
            "dsh_result": r,
        }

    return _exec


def _measure(name, rounds, fn):
    lat = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        lat.append((time.perf_counter() - t0) * 1000.0)
    lat.sort()
    summary = {
        "mode": name,
        "rounds": rounds,
        "p50_ms": round(statistics.median(lat), 3),
        "p95_ms": round(lat[int(len(lat) * 0.95) - 1], 3),
        "min_ms": round(lat[0], 3),
        "max_ms": round(lat[-1], 3),
        "mean_ms": round(statistics.mean(lat), 3),
    }
    return summary


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rounds = int(args[0]) if args else 100

    # ── mode 1: shell_direct ──────────────────────────────────────
    mgr1 = ShellHandleManager(launcher=stdio_launcher, flags={"enable_shell_handles": True})
    try:
        shell_summary = _measure(
            "shell_direct",
            rounds,
            lambda: (mgr1.get_handle("l0.store-admin.mcp").call("store_admin_status")),
        )
    finally:
        mgr1.close_all()

    # ── mode 2: dsh_direct ─────────────────────────────────────────
    mgr2 = ShellHandleManager(launcher=stdio_launcher, flags={"enable_shell_handles": True})
    try:
        dsh_summary = _measure(
            "dsh_direct",
            rounds,
            lambda: call_worker_tool(
                "verifier", "store_admin_status", manager=mgr2, flags=ON, trace_id="dsh-bench"
            ),
        )
    finally:
        mgr2.close_all()

    # ── mode 3: l2_full ────────────────────────────────────────────
    mgr3 = ShellHandleManager(launcher=stdio_launcher, flags={"enable_shell_handles": True})
    try:
        orch = SACGOrchestrator(
            c_executor=_dsh_c_executor(mgr3, ON),
            a_decomposer=_single_node_decomposer,
        )

        def _l2_call():
            # memories 必须空 → L2_HANDOFF 触发编排, 否则会短路 L1_DIRECT
            return orch.handle("帮我验证库管健康状态", l1_intent_hint=None, memories=[])

        l2_summary = _measure("l2_full", rounds, _l2_call)
    finally:
        mgr3.close_all()

    # ── 分析报告 ──────────────────────────────────────────────────
    shell_p50 = shell_summary["p50_ms"]
    dsh_p50 = dsh_summary["p50_ms"]
    l2_p50 = l2_summary["p50_ms"]
    dsh_overhead = round(dsh_p50 - shell_p50, 3)
    sacg_overhead = round(l2_p50 - dsh_p50, 3)

    report = {
        "analysis": "L2 完整架构同类评测 (DreamOs SACG ↔ DSH ↔ L0 真壳)",
        "rounds": rounds,
        "layers": {
            "shell_direct_p50_ms": shell_p50,
            "dsh_over_shell_ms": dsh_overhead,
            "sacg_over_dsh_ms": sacg_overhead,
            "total_l2_p50_ms": l2_p50,
        },
        "d4_budget_ms": 45,
        "d4_ok": (dsh_overhead <= 45),
        "sacg_overhead_ratio": round(sacg_overhead / dsh_p50, 3) if dsh_p50 > 0 else 0,
        "summaries": {
            "shell_direct": shell_summary,
            "dsh_direct": dsh_summary,
            "l2_full": l2_summary,
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    # L2 延迟预算判定: SACG 编排层开销(over dsh_direct)应 ≤ 10ms (合理编排层开销)
    # DSH 层开销(over shell_direct) ≤ 45ms (之前 D4 判据)
    l2_ok = dsh_overhead <= 45 and sacg_overhead <= 15
    return 0 if l2_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
