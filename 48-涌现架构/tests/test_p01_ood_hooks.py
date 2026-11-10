"""P0-1 OOD hooks 回归测试（方案 A）。

覆盖：
  - A1 CaseIngestGate.evaluate_and_ingest 的 OOS 区间拒绝 + 缺时间戳 fail-closed
  - A2 BayesianMemoryUpdater.update_confidence 的 OOS 不更新 + 审计记录
  - 向后兼容：不传 oos_intervals 时行为不变
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (
    str(ROOT),
    str(ROOT / "1-ARCHITECTURE"),
    str(ROOT / "4-MEMORY" / "9-工具与接口"),
):
    if p not in sys.path:
        sys.path.insert(0, p)

from bayesian_memory_updater import BayesianMemoryUpdater  # noqa: E402

from dreamos.core.compute.case_ingest_gate import (  # noqa: E402
    CaseIngestGate,
    IngestDecision,
)

OOS = [(datetime(2026, 11, 4, tzinfo=timezone.utc), datetime(2026, 11, 5, tzinfo=timezone.utc))]


# ──────────────────────── A1: CaseIngestGate ────────────────────────


def _high_value_cycle(ts="2026-11-09T10:00:00Z"):
    return {
        "direction": 1,
        "signals": ["macd_cross", "volume_break", "rsi_reversal", "trend_follow"],
        "indicators": {"atr": 2.5, "slippage": 0.0005},
        "pnl_pct": 0.18,
        "confidence": 0.92,
        "ts": ts,
    }


class TestCaseIngestGateOOD:
    def test_backward_compat_no_oos(self):
        called = []
        gate = CaseIngestGate(
            recall_fn=lambda *a, **k: [],
            ingest_fn=lambda *a, **k: called.append(True) or "case-ok",
        )
        r = gate.evaluate_and_ingest(_high_value_cycle())
        assert r.decision in (IngestDecision.INGEST, IngestDecision.SKIP, IngestDecision.DEFERRED)
        assert "oos_interval_excluded" not in (r.reason or "")

    def test_oos_interval_rejects_ingest(self):
        called = []
        gate = CaseIngestGate(
            recall_fn=lambda *a, **k: [],
            ingest_fn=lambda *a, **k: called.append(True),
        )
        r = gate.evaluate_and_ingest(_high_value_cycle("2026-11-04T12:00:00Z"), oos_intervals=OOS)
        assert r.decision == IngestDecision.SKIP
        assert "oos_interval_excluded" in (r.reason or "")
        assert r.ingested is False
        assert called == []  # 未入库

    def test_oos_left_boundary_inclusive(self):
        gate = CaseIngestGate()
        r = gate.evaluate_and_ingest(_high_value_cycle("2026-11-04T00:00:00Z"), oos_intervals=OOS)
        assert r.decision == IngestDecision.SKIP
        assert "oos_interval_excluded" in (r.reason or "")

    def test_oos_right_boundary_exclusive(self):
        gate = CaseIngestGate()
        r = gate.evaluate_and_ingest(_high_value_cycle("2026-11-05T00:00:00Z"), oos_intervals=OOS)
        # 右开边界：不命中 OOS，走正常估值
        assert "oos_interval_excluded" not in (r.reason or "")

    def test_missing_ts_fail_closed(self):
        cycle = _high_value_cycle("2026-11-09T10:00:00Z")
        cycle.pop("ts")
        gate = CaseIngestGate()
        r = gate.evaluate_and_ingest(cycle, oos_intervals=OOS)
        assert r.decision == IngestDecision.SKIP
        assert "missing_timestamp_fail_closed" in (r.reason or "")

    def test_missing_ts_allowed(self):
        cycle = _high_value_cycle("2026-11-09T10:00:00Z")
        cycle.pop("ts")
        gate = CaseIngestGate()
        r = gate.evaluate_and_ingest(cycle, oos_intervals=OOS, allow_missing_ts=True)
        assert "missing_timestamp_fail_closed" not in (r.reason or "")

    def test_numeric_epoch_ts_parsed(self):
        cycle = _high_value_cycle()
        cycle["ts"] = 1762243200.0  # 2025-11-04-ish inside OOS
        # 选一个落在 OOS 区间内的 epoch：2026-11-04T12:00Z
        cycle["ts"] = 1793784000.0
        gate = CaseIngestGate()
        r = gate.evaluate_and_ingest(cycle, oos_intervals=OOS)
        assert r.decision == IngestDecision.SKIP
        assert "oos_interval_excluded" in (r.reason or "")


# ───────────────────── A2: BayesianMemoryUpdater ────────────────────


def _make_updater(tmp_path: Path) -> BayesianMemoryUpdater:
    u = BayesianMemoryUpdater(str(tmp_path))
    u.add_memory(
        memory_id="m1",
        content="test",
        initial_confidence=0.5,
        initial_verify_count=2,
    )
    return u


class TestBayesianUpdaterOOD:
    def test_backward_compat_updates(self, tmp_path):
        u = _make_updater(tmp_path)
        vc_before = u.memories["m1"].verify_count
        u.update_confidence("m1", observation_success=True, followed_memory=True)
        # 正常路径应累计验证次数
        assert u.memories["m1"].verify_count == vc_before + 1

    def test_oos_observation_no_update(self, tmp_path):
        u = _make_updater(tmp_path)
        prior = u.memories["m1"].confidence
        vc_before = u.memories["m1"].verify_count
        post, q = u.update_confidence(
            "m1",
            observation_success=True,
            followed_memory=True,
            observation_ts=datetime(2026, 11, 4, 12, tzinfo=timezone.utc),
            oos_intervals=OOS,
        )
        assert post == pytest.approx(prior)
        assert u.memories["m1"].verify_count == vc_before  # 未计数
        assert q == u.memories["m1"].quality_level
        assert len(u.get_oos_audit_log()) == 1
        assert u.get_oos_audit_log()[0]["reason"] == "in_interval"

    def test_missing_ts_fail_closed_no_update(self, tmp_path):
        u = _make_updater(tmp_path)
        prior = u.memories["m1"].confidence
        post, _ = u.update_confidence(
            "m1",
            observation_success=True,
            followed_memory=True,
            oos_intervals=OOS,
        )
        assert post == pytest.approx(prior)
        assert u.get_oos_audit_log()[0]["reason"] == "missing_ts"

    def test_out_of_oos_updates(self, tmp_path):
        u = _make_updater(tmp_path)
        vc_before = u.memories["m1"].verify_count
        u.update_confidence(
            "m1",
            observation_success=True,
            followed_memory=True,
            observation_ts=datetime(2026, 11, 9, 10, tzinfo=timezone.utc),
            oos_intervals=OOS,
        )
        # 区间外 → 正常更新
        assert u.memories["m1"].verify_count == vc_before + 1
        assert u.get_oos_audit_log() == []
