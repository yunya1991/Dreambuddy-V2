"""Task 9 RED → GREEN tests — Auditor (JSONL per-parent) + RollingMetrics.

Behaviour under test (TR-9.1 … TR-9.4, rubric ≥4/5 completeness):
  TR-9.1 Schema completeness. Auditor.record_parent(result) writes ONE
      JSONL line to AUDIT_LOG_DIR/YYYY-MM-DD.jsonl. Each line must have
      ≥18 required keys across:
          parent / exec / estimator / router / algo / killswitch / failopen / children
      (≥ 4/5 of these 8 sections populated = threshold)

  TR-9.2 Rolling metrics every METRICS_FLUSH_INTERVAL_SEC: after N
      parents are recorded, flush_metrics_if_due() writes
      METRICS_JSON_PATH with aggregate dict:
        avg_slip_improvement_baseline_direct_market_bps
        fail_open_count_per_coin (dict: inst_id → count)
        algo_distribution_counts    (dict: algo_name → count)
        kill_switch_trigger_count   (int)
        total_parent_count          (int)
      We use force_flush=True in tests so no 60s waits.

  TR-9.3 Daily file rotation: write a parent with mocked UTC date
      2024-03-20 and one with 2024-03-21 → two files
      2024-03-20.jsonl and 2024-03-21.jsonl exist; correct line count each.

  TR-9.4 Idempotency by parent_id: record_parent with same parent_id
      twice → only ONE JSONL line exists (deduped). Call counts on
      file-append are <= 1 effectively; second call is a no-op (return
      "DUPLICATE_PARENT_ID_IGNORED" status).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "22-执行引擎中心"))


# =====================================================================
# shared helpers
# =====================================================================
def _parent_result_factory(
    *,
    parent_id: str,
    inst_id: str = "BTC-USDT-SWAP",
    algo_name: str = "SmartTWAP",
    algo_bucket: str = "TWAP15",
    slip_tee_bps: float = 3.0,
    slip_baseline_dm_bps: float = 8.0,
    killswitch_triggered: bool = False,
    fail_open_triggered: bool = False,
    fail_open_tag: str = "",
    children: int = 3,
    filled_sz: float = 0.5,
    ts: float | None = None,
) -> Dict[str, Any]:
    """Build a dict shaped like the real ExecutionResult but flattened so
    the Auditor can digest it easily.

    Shape mirrors what Task 10 Engine will emit:
      {parent, exec_outcome, estimate, router, algo, kill_switch, fail_open, children}
    """
    return {
        "ts_epoch_ms": int((ts or 1_710_000_000.0) * 1000),
        "parent": {
            "parent_id": parent_id,
            "inst_id": inst_id,
            "side": "buy",
            "pos_side": "long",
            "td_mode": "isolated",
            "leverage": 5,
            "sz": filled_sz,
            "decision_px": 70_000.0,
            "urgency": "NORMAL",
            "algo_override": None,
            "source": "ut_task9",
        },
        "estimate": {
            "slippage_bps": 2.5,
            "market_impact_usd": 10.1,
            "walk_depth_level": 2,
            "thin_book_warning": False,
            "fail_open": False,
        },
        "router": {
            "size_ratio_bps": 200.0,
            "bucket": algo_bucket,
            "urgency_shift_applied": 0,
        },
        "algo": {
            "name": algo_name,
            "num_slices": children,
            "num_escalations": 1 if algo_name.startswith("Smart") else 0,
            "rehang_count": 1 if algo_name == "SmartPassive" else 0,
        },
        "kill_switch": {
            "pre_allowed": True,
            "pre_reason": "" if True else "REJECT_SLIPPAGE_TOO_HIGH",
            "runtime_triggered": killswitch_triggered,
            "closeout_child_sent": killswitch_triggered,
        },
        "fail_open": {
            "triggered": fail_open_triggered,
            "tag": fail_open_tag,
            "lark_alert_sent": False,
        },
        "exec": {
            "avg_fill_px": 70_050.0,
            "filled_sz_total": filled_sz,
            "slippage_bps_vs_decision": slip_tee_bps,
            "baseline_direct_market_slippage_bps": slip_baseline_dm_bps,
            "total_execution_time_sec": children * 2.0,
            "vwap_children_usd": 35_025.0,
            "fee_total_usd": 0.05,
        },
        "children": [
            {
                "child_id": f"{parent_id}-ch-{i}",
                "ord_type": "limit" if i < children - 1 else "market",
                "tier": 0 if i < children - 1 else 3,
                "sz": round(filled_sz / children, 5),
                "avg_px": 70_050.0,
                "sz_filled": round(filled_sz / children, 5),
                "fee_usd": 0.01,
                "state": "filled",
            }
            for i in range(children)
        ],
    }


# =====================================================================
# Fixtures
# =====================================================================
@pytest.fixture
def audit_dir(tmp_path: Path) -> Path:
    d = tmp_path / "audit_jsonl"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def metrics_path(tmp_path: Path) -> Path:
    return tmp_path / "metrics.json"


# =====================================================================
# TR-9.1  Schema completeness  ≥4/5 rubric
# =====================================================================
class TestTR91SchemaCompleteness:
    _REQUIRED_SECTIONS = (
        "parent", "estimate", "router", "algo", "kill_switch",
        "fail_open", "exec", "children",  # 8 top-level sections
    )
    # For 4/5 threshold: at least ceil(4/5 * 8) = 7 populated.
    _MIN_POPULATED_SECTIONS = 7

    def test_auditor_writes_jsonl_file_for_parent(self, audit_dir, metrics_path):
        from tee_core.core.auditor import Auditor
        aud = Auditor(audit_dir=str(audit_dir), metrics_path=str(metrics_path))
        pr = _parent_result_factory(parent_id="P-SCHEMA-001", algo_name="DirectMarket",
                                     algo_bucket="DIRECT")
        status = aud.record_parent(pr)
        # Status: OK/WRITTEN or similar.
        assert isinstance(status, str) and status.upper().startswith("OK")
        # Exactly one file.
        files = list(audit_dir.glob("*.jsonl"))
        assert len(files) == 1, f"Expected 1 jsonl, got {[f.name for f in files]}"
        lines = [ln for ln in files[0].read_text(encoding="utf-8").splitlines() if ln]
        assert len(lines) == 1

    def test_each_line_has_min_18_required_keys_across_sections(
            self, audit_dir, metrics_path):
        """Rubric completeness: ≥18 required top-level+section keys present."""
        from tee_core.core.auditor import Auditor
        aud = Auditor(audit_dir=str(audit_dir), metrics_path=str(metrics_path))
        parents = [
            _parent_result_factory(parent_id="P-SCH-1", inst_id="BTC-USDT-SWAP",
                                    algo_name="DirectMarket", algo_bucket="DIRECT"),
            _parent_result_factory(parent_id="P-SCH-2", inst_id="ETH-USDT-SWAP",
                                    algo_name="SmartTWAP", algo_bucket="TWAP60",
                                    killswitch_triggered=True),
            _parent_result_factory(parent_id="P-SCH-3", inst_id="SOL-USDT-SWAP",
                                    algo_name="SmartPassive", algo_bucket="PASSIVE",
                                    fail_open_triggered=True,
                                    fail_open_tag="ORDERBOOK_TIMEOUT"),
            _parent_result_factory(parent_id="P-SCH-4", inst_id="AVAX-USDT-SWAP",
                                    slip_tee_bps=1.5, slip_baseline_dm_bps=4.0,
                                    algo_name="SmartTWAP"),
            _parent_result_factory(parent_id="P-SCH-5", inst_id="BTC-USDT-SWAP",
                                    algo_name="DirectMarket", algo_bucket="DIRECT"),
        ]
        for p in parents:
            aud.record_parent(p)

        # Read all JSONL lines (may be split across files if UTC day rollover).
        all_lines: List[str] = []
        for f in audit_dir.glob("*.jsonl"):
            all_lines.extend(l for l in f.read_text(encoding="utf-8").splitlines() if l)
        assert len(all_lines) == 5, f"Expected 5 lines, got {len(all_lines)}"

        REQUIRED_KEYS_MIN = 18
        # Expected keys across flattened/structured output: note we do NOT
        # require strict flattening, any reasonable shape with ≥18 keys is OK.
        def count_keys(obj: Any) -> int:
            if isinstance(obj, dict):
                return sum(1 + count_keys(v) for v in obj.values())
            if isinstance(obj, list):
                return sum(count_keys(v) for v in obj)
            return 0

        for raw in all_lines:
            rec = json.loads(raw)
            total = count_keys(rec)
            assert total >= REQUIRED_KEYS_MIN, (
                f"Audit JSONL line has only {total} keys (< {REQUIRED_KEYS_MIN}). "
                f"Keys (truncated): {list(rec.keys())[:10]}"
            )
            # 8 top-level sections; ensure ≥ MIN_POPULATED_SECTIONS are there.
            present_sections = sum(
                1 for s in self._REQUIRED_SECTIONS if s in rec
            )
            assert present_sections >= self._MIN_POPULATED_SECTIONS, (
                f"Only {present_sections}/{len(self._REQUIRED_SECTIONS)} sections "
                f"present. present = {[s for s in self._REQUIRED_SECTIONS if s in rec]}"
            )
            # parent.parent_id must always be set.
            assert rec.get("parent", {}).get("parent_id"), "parent_id missing"


# =====================================================================
# TR-9.2 Rolling metrics aggregate on flush
# =====================================================================
class TestTR92RollingMetrics:
    def test_flush_writes_aggregate_metrics_file(self, audit_dir, metrics_path):
        from tee_core.core.auditor import Auditor
        aud = Auditor(audit_dir=str(audit_dir), metrics_path=str(metrics_path),
                      flush_interval_sec=999999)  # don't auto-flush
        inputs = [
            ("M1", "BTC-USDT-SWAP", "SmartTWAP",     2.0, 6.0, False, False),
            ("M2", "BTC-USDT-SWAP", "SmartTWAP",     1.5, 5.5, False, False),
            ("M3", "ETH-USDT-SWAP", "DirectMarket",  5.0, 5.0, False, False),
            ("M4", "SOL-USDT-SWAP", "SmartPassive",  2.5, 9.0, True,  True),
            ("M5", "ETH-USDT-SWAP", "SmartTWAP",     3.0, 7.5, True,  False),
            ("M6", "BTC-USDT-SWAP", "SmartPassive",  1.0, 8.5, False, True),
        ]
        # (parent_id, inst, algo, tee_bps, dm_bps, ks_trigger, fo_trigger)
        for pid, inst, algo, tee, dm, ks, fo in inputs:
            pr = _parent_result_factory(
                parent_id=pid, inst_id=inst, algo_name=algo,
                algo_bucket=({"SmartTWAP": "TWAP15", "DirectMarket": "DIRECT",
                              "SmartPassive": "PASSIVE"}[algo]),
                slip_tee_bps=tee, slip_baseline_dm_bps=dm,
                killswitch_triggered=ks,
                fail_open_triggered=fo,
                fail_open_tag="ORDERBOOK_TIMEOUT" if fo else "",
            )
            aud.record_parent(pr)

        aud.flush_metrics(force=True)
        assert metrics_path.exists(), "metrics file not created"
        m = json.loads(metrics_path.read_text(encoding="utf-8"))

        # total_parent_count == 6
        assert m.get("total_parent_count") == 6, m

        # avg_slip_improvement_baseline_direct_market_bps
        # Σ(dm_bps - tee_bps) for each / N:
        # BTC: (6-2=4)+(5.5-1.5=4)+(8.5-1=7.5)=15.5 / 3 BTCs
        # ETH: (5-5=0)+(7.5-3=4.5)=4.5 / 2 ETHs
        # SOL: 9-2.5=6.5 / 1
        # Total Σimprovement = 15.5+4.5+6.5 = 26.5, mean = 26.5/6 ≈ 4.4167
        expected_avg = round((4 + 4 + 0 + 6.5 + 4.5 + 7.5) / 6, 4)
        actual_avg = round(float(m.get(
            "avg_slip_improvement_baseline_direct_market_bps", -1.0)), 4)
        assert abs(actual_avg - expected_avg) < 1e-3, (
            f"avg slip improvement mismatch: actual {actual_avg}, expected {expected_avg}"
        )

        # algo_distribution_counts:
        assert m["algo_distribution_counts"]["SmartTWAP"] == 3  # M1+M2+M5
        assert m["algo_distribution_counts"]["DirectMarket"] == 1
        assert m["algo_distribution_counts"]["SmartPassive"] == 2

        # kill_switch_trigger_count == 2 (M4, M5)
        assert m["kill_switch_trigger_count"] == 2

        # fail_open_count_per_coin: SOL, BTC == 1 each
        assert m["fail_open_count_per_coin"].get("SOL-USDT-SWAP") == 1
        assert m["fail_open_count_per_coin"].get("BTC-USDT-SWAP") == 1
        assert m["fail_open_count_per_coin"].get("ETH-USDT-SWAP") == 0 or \
            "ETH-USDT-SWAP" not in m["fail_open_count_per_coin"]

        # must have flushed_at timestamp
        assert "flushed_at_iso" in m or "flushed_at_epoch_ms" in m, (
            "metrics missing flush timestamp"
        )


# =====================================================================
# TR-9.3 Daily file rotation by UTC date
# =====================================================================
class TestTR93DailyRotation:
    def test_utc_date_split_writes_separate_files(self, audit_dir, metrics_path):
        from tee_core.core.auditor import Auditor
        aud = Auditor(audit_dir=str(audit_dir), metrics_path=str(metrics_path))

        # First parent: 2024-03-20T23:50 UTC → ts_epoch_ms matches
        ts1 = datetime(2024, 3, 20, 23, 50, 0, tzinfo=timezone.utc).timestamp()
        p1 = _parent_result_factory(parent_id="P-DAY-20", ts=ts1,
                                     inst_id="BTC-USDT-SWAP")
        p1["ts_epoch_ms"] = int(ts1 * 1000)
        aud.record_parent(p1)

        # Second parent: next day 2024-03-21T00:10 UTC
        ts2 = datetime(2024, 3, 21, 0, 10, 0, tzinfo=timezone.utc).timestamp()
        p2 = _parent_result_factory(parent_id="P-DAY-21", ts=ts2,
                                     inst_id="ETH-USDT-SWAP")
        p2["ts_epoch_ms"] = int(ts2 * 1000)
        aud.record_parent(p2)

        files = sorted(f.name for f in audit_dir.glob("*.jsonl"))
        assert "2024-03-20.jsonl" in files and "2024-03-21.jsonl" in files, (
            f"Expected day files but found: {files}"
        )
        f1_lines = [ln for ln in (audit_dir / "2024-03-20.jsonl"
                                  ).read_text(encoding="utf-8").splitlines() if ln]
        f2_lines = [ln for ln in (audit_dir / "2024-03-21.jsonl"
                                  ).read_text(encoding="utf-8").splitlines() if ln]
        assert len(f1_lines) == 1 and len(f2_lines) == 1, (
            f"Split wrong: day20 lines={len(f1_lines)}, day21={len(f2_lines)}"
        )


# =====================================================================
# TR-9.4 Parent-id dedup (idempotency)
# =====================================================================
class TestTR94ParentDedup:
    def test_same_parent_id_written_twice_keeps_one_line(
            self, audit_dir, metrics_path):
        from tee_core.core.auditor import Auditor
        aud = Auditor(audit_dir=str(audit_dir), metrics_path=str(metrics_path))
        p = _parent_result_factory(parent_id="P-DEDUP-001",
                                    inst_id="BTC-USDT-SWAP")
        status1 = aud.record_parent(p)
        status2 = aud.record_parent(p)

        files = list(audit_dir.glob("*.jsonl"))
        assert len(files) == 1
        lines = [ln for ln in files[0].read_text(encoding="utf-8").splitlines() if ln]
        assert len(lines) == 1, (
            f"Duplicate parent_id P-DEDUP-001 produced {len(lines)} lines (expect 1)"
        )
        # Second status should signal dedup.
        assert status1.upper().startswith("OK")
        assert "DUPLICATE" in status2.upper(), (
            f"Expected DUPLICATE sentinel in 2nd status, got: {status2!r}"
        )
