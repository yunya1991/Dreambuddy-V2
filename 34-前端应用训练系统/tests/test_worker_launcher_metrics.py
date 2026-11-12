# -*- coding: utf-8 -*-
"""W4 可观测：指标聚合单测（PROPOSAL-P0-D3 §4.8）。"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.worker_launcher_metrics import LauncherMetrics  # noqa: E402


def test_record_merges_counters_and_persists(tmp_path):
    path = tmp_path / "metrics.json"
    metrics = LauncherMetrics(str(path))

    snap = metrics.record(
        {
            "executed": 2,
            "done": 1,
            "failed": 1,
            "receipts": 2,
            "latencies_ms": [100, 300],
            "in_flight_peak": 2,
            "pass_offset": 128,
        }
    )
    assert snap["passes"] == 1
    assert snap["counters"]["executed"] == 2
    assert snap["counters"]["done"] == 1
    assert snap["latency_ms"] == {"count": 2, "p50": 100.0, "p95": 300.0, "max": 300.0}
    assert snap["success_rate"] == 0.5
    assert snap["in_flight_peak"] == 2
    assert snap["pass_offset"] == 128

    snap = metrics.record({"done": 1, "latencies_ms": [500], "in_flight_peak": 1, "errors": ["x"]})
    assert snap["passes"] == 2
    assert snap["counters"]["done"] == 2
    assert snap["counters"]["errors"] == 1
    assert snap["in_flight_peak"] == 2
    assert snap["latency_ms"]["count"] == 3
    assert snap["latency_ms"]["p95"] == 500.0
    assert snap["success_rate"] == round(2 / 3, 4)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["passes"] == 2
    assert len(stored["durations_ms"]) == 3


def test_rolling_window_keeps_latest(tmp_path):
    metrics = LauncherMetrics(str(tmp_path / "m.json"), window=3)
    snap = metrics.record({"latencies_ms": [1, 2, 3, 4, 5]})
    assert snap["latency_ms"]["count"] == 3
    assert snap["latency_ms"]["max"] == 5.0
    assert snap["latency_ms"]["p50"] == 4.0


def test_corrupt_file_fails_open(tmp_path):
    path = tmp_path / "metrics.json"
    path.write_text("{not json", encoding="utf-8")
    metrics = LauncherMetrics(str(path))
    snap = metrics.record({"done": 1, "latencies_ms": [7]})
    assert snap["counters"]["done"] == 1
    assert snap["latency_ms"]["p50"] == 7.0


def test_disabled_metrics_writes_nothing(tmp_path):
    metrics = LauncherMetrics(None)
    snap = metrics.record({"done": 1})
    assert snap["counters"]["done"] == 1
    assert list(tmp_path.iterdir()) == []
