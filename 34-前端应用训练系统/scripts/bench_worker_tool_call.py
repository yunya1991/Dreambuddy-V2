# -*- coding: utf-8 -*-
"""编排层延迟基线(47 SPEC D4: 壳 P50 ≤ in-process P50 + 45ms 的编排侧分量)。

测量 call_worker_tool 全链(真 mandate_gate + 真 47 registry + FakeShell)
的 P50/P95,验证编排层自身开销远小于 45ms 预算——壳 stdio 传输分量待
stdio launcher 落地后用同脚本换真壳复测( launcher 注入点不变)。

用法: python3 scripts/bench_worker_tool_call.py [rounds]
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.shell_handles import ShellHandleManager  # noqa: E402
from core.worker_tool_call import call_worker_tool  # noqa: E402


class _FakeShell:
    def __init__(self, spec):
        self.spec = spec

    def call(self, tool, args=None):
        return {"ok": True, "data": {"tool": tool}}

    def close(self):
        pass


def main() -> int:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 200
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
        "rounds": rounds,
        "chain": "mandate_gate(real) -> registry_map(real) -> handle(fake shell)",
        "p50_ms": round(statistics.median(lat_ms), 3),
        "p95_ms": round(lat_ms[int(len(lat_ms) * 0.95) - 1], 3),
        "min_ms": round(lat_ms[0], 3),
        "max_ms": round(lat_ms[-1], 3),
        "d4_budget_ms": 45,
        "orchestration_within_budget": statistics.median(lat_ms) < 45,
        "note": "stdio 传输分量待 stdio launcher 落地后换真壳复测",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
