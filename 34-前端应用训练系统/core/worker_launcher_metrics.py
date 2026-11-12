# -*- coding: utf-8 -*-
"""D3 拉起器可观测：指标聚合（PROPOSAL-P0-D3 §4.8 / W4）。

每轮 `WorkerLauncher.run_once` 结束后，把本轮统计并入
`<state_dir>/metrics.json`：
  - 累计计数：consumed/executed/done/failed/retried/timeouts/role_rejections/errors
  - 滚动时延窗口 → P50/P95/max
  - 在途峰值；成功率 = done / (done + failed)

只读派生字段（P50/P95/成功率）由原始计数与窗口现算，文件损坏时 FAIL-OPEN
（重新开始计数），不阻塞拉起器主循环。
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_CST = timezone(timedelta(hours=8))
_COUNTER_KEYS = (
    "consumed",
    "skipped",
    "executed",
    "done",
    "receipts",
    "failed",
    "retried",
    "recovered",
    "timeouts",
    "role_rejections",
    "bad_lines",
)
DEFAULT_WINDOW = 500


def _percentile(sorted_values: List[int], q: float) -> Optional[float]:
    """nearest-rank 分位数；空窗口返回 None。"""
    if not sorted_values:
        return None
    index = int(math.ceil(q / 100.0 * len(sorted_values))) - 1
    return float(sorted_values[max(0, min(index, len(sorted_values) - 1))])


class LauncherMetrics:
    """把多轮 run_once 统计聚合成可对账的本地 JSON。"""

    def __init__(self, path: Optional[str], *, window: int = DEFAULT_WINDOW) -> None:
        self.path = path
        self.window = max(1, int(window))

    # ---------- 对外 ----------

    def record(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """并入一轮统计并落盘；返回派生后的快照。"""
        data = self._load()
        data["passes"] = int(data.get("passes") or 0) + 1

        counters = data.get("counters")
        counters = dict(counters) if isinstance(counters, dict) else {}
        for key in _COUNTER_KEYS:
            counters[key] = int(counters.get(key) or 0) + int(stats.get(key) or 0)
        counters["errors"] = int(counters.get("errors") or 0) + len(stats.get("errors") or [])
        data["counters"] = counters

        peak = int(stats.get("in_flight_peak") or 0)
        data["in_flight_peak"] = max(int(data.get("in_flight_peak") or 0), peak)
        data["pass_offset"] = int(stats.get("pass_offset") or 0)

        durations = data.get("durations_ms")
        durations = [int(x) for x in durations] if isinstance(durations, list) else []
        durations.extend(int(x) for x in (stats.get("latencies_ms") or []))
        data["durations_ms"] = durations[-self.window :]

        data["updated_at"] = datetime.now(_CST).isoformat(timespec="seconds")
        snapshot = self.snapshot(data)
        stored = dict(data)
        stored.update(snapshot)  # 落盘同时保留原始窗口与派生字段，便于 status/外部对账
        self._save(stored)
        return snapshot

    def snapshot(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """派生只读视图：计数、分位数、成功率。"""
        data = self._load() if data is None else data
        counters = data.get("counters")
        counters = dict(counters) if isinstance(counters, dict) else {}
        durations = sorted(int(x) for x in (data.get("durations_ms") or []))
        done = int(counters.get("done") or 0)
        failed = int(counters.get("failed") or 0)
        terminal = done + failed
        return {
            "updated_at": data.get("updated_at"),
            "passes": int(data.get("passes") or 0),
            "counters": {key: int(counters.get(key) or 0) for key in _COUNTER_KEYS + ("errors",)},
            "in_flight_peak": int(data.get("in_flight_peak") or 0),
            "pass_offset": int(data.get("pass_offset") or 0),
            "latency_ms": {
                "count": len(durations),
                "p50": _percentile(durations, 50),
                "p95": _percentile(durations, 95),
                "max": float(durations[-1]) if durations else None,
            },
            "success_rate": round(done / terminal, 4) if terminal else None,
        }

    # ---------- 存储 ----------

    def _load(self) -> Dict[str, Any]:
        if not self.path or not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _save(self, data: Dict[str, Any]) -> None:
        if not self.path:
            return
        data["updated_at"] = datetime.now(_CST).isoformat(timespec="seconds")
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            pass
