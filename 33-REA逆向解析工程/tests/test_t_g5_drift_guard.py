"""T-G5 漂移守卫 — RED 测试

SPEC-33-G G-G5 / §2.3 metric_drift：
  - 度量相对基线超阈值（cycles / god_components / fan_out 涨幅，adoption 跌幅）→ 降级 review
  - 降级同时必须产出 Evidence（不可只告警不留证）
  - 阈值来自配置（不写死），严格大于才触发
  - 基线为 0 且当前 > 0 → 保守判 drift

RED 契约：core.evolution.drift_guard 不存在。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from core.evolution.drift_guard import DriftGuard

BASE = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now=BASE):
        self.now = now

    def __call__(self):
        return self.now


def _guard(tmp_path, **overrides):
    kwargs = {"evidence_dir": tmp_path / "reflection_data" / "evidence", "clock": Clock()}
    kwargs.update(overrides)
    return DriftGuard(**kwargs)


def _evidence_lines(tmp_path):
    path = tmp_path / "reflection_data" / "evidence" / "drift_guard.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_no_drift_stays_ok(tmp_path):
    result = _guard(tmp_path).guard(
        current={"cycles": 100, "god_components": 10, "fan_out": 20, "adoption": 50},
        baseline={"cycles": 100, "god_components": 10, "fan_out": 20, "adoption": 50},
    )
    assert result["status"] == "ok"
    assert result["drifts"] == []
    assert _evidence_lines(tmp_path) == []


def test_cycles_increase_over_threshold_degrades_review(tmp_path):
    result = _guard(tmp_path).guard(
        current={"cycles": 140},
        baseline={"cycles": 100},
    )
    assert result["status"] == "review"
    drift = result["drifts"][0]
    assert drift["metric"] == "cycles"
    assert drift["pct"] == 40.0
    assert drift["threshold"] == 30.0


def test_exact_threshold_does_not_trigger(tmp_path):
    result = _guard(tmp_path).guard(current={"cycles": 130}, baseline={"cycles": 100})
    assert result["status"] == "ok"


def test_god_components_and_fan_out_are_guarded(tmp_path):
    result = _guard(tmp_path).guard(
        current={"god_components": 16, "fan_out": 31},
        baseline={"god_components": 10, "fan_out": 20},
    )
    metrics = {drift["metric"] for drift in result["drifts"]}
    assert {"god_components", "fan_out"} <= metrics


def test_metric_decrease_is_not_drift_for_increase_metrics(tmp_path):
    result = _guard(tmp_path).guard(current={"cycles": 60}, baseline={"cycles": 100})
    assert result["status"] == "ok"


def test_adoption_drop_triggers_review(tmp_path):
    result = _guard(tmp_path).guard(current={"adoption": 75}, baseline={"adoption": 100})
    assert result["status"] == "review"
    assert result["drifts"][0]["metric"] == "adoption"
    assert result["drifts"][0]["pct"] == -25.0


def test_custom_thresholds_from_config(tmp_path):
    guard = _guard(tmp_path, thresholds={"cycles_pct": 10.0})
    result = guard.guard(current={"cycles": 115}, baseline={"cycles": 100})
    assert result["status"] == "review"
    assert result["drifts"][0]["threshold"] == 10.0


def test_zero_baseline_is_conservative_drift(tmp_path):
    result = _guard(tmp_path).guard(current={"cycles": 5}, baseline={"cycles": 0})
    assert result["status"] == "review"
    assert result["drifts"][0]["pct"] is None


def test_guard_writes_append_only_evidence(tmp_path):
    guard = _guard(tmp_path)
    first = guard.guard(current={"cycles": 140}, baseline={"cycles": 100})
    second = guard.guard(current={"fan_out": 40}, baseline={"fan_out": 20})

    assert "evidence_id" in first and "evidence_id" in second
    assert first["evidence_id"] != second["evidence_id"]

    lines = _evidence_lines(tmp_path)
    assert len(lines) == 2
    assert lines[0]["kind"] == "metric_drift"
    assert lines[0]["verdict"] == "review"
    assert lines[0]["baseline"] == {"cycles": 100}
    assert lines[0]["current"] == {"cycles": 140}
    assert lines[1]["drifts"][0]["metric"] == "fan_out"
