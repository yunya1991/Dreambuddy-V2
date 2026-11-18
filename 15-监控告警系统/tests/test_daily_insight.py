"""daily_insight.py 单元测试（本期只覆盖 23 核心链）。"""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/daily_insight.py"
spec = importlib.util.spec_from_file_location("daily_insight", SCRIPT)
di = importlib.util.module_from_spec(spec)
spec.loader.exec_module(di)

CFG = {
    "enabled_chains": ["23"],
    "reserved_chains": ["40"],
    "thresholds": {
        "ri_min_samples": 10,
        "ri_constant_ratio": 0.8,
        "ess_topdir_empty_ratio": 0.8,
        "probe_tier_ratio": 0.8,
        "dstar_wait_ratio": 0.8,
        "n2_degraded_ratio": 0.9,
        "cv_degraded_ratio": 0.5,
        "g_dim_missing_ratio": 0.5,
        "chain_completion_min": 0.95,
        "ledger_stale_hours": 24,
        "outbox_stuck_seconds": 300,
        "outbox_failed_ratio": 0.2,
    },
    "nn40_artifacts": [],
}


def base_metrics() -> dict:
    return {
        "chain_23": {
            "events": 100,
            "stage_counts": {},
            "n9": {
                "count": 50,
                "ri": {"count": 50, "distinct": 1, "mode": 0.5, "mode_ratio": 1.0},
                "tier": {"probe": 50},
                "l4_v": {"count": 50, "mode": -0.016},
                "ess_top_direction_coverage": 50,
                "ess_top_direction_empty_ratio": 1.0,
                "ripple_is_source_ratio": 0.0,
                "reflection_eligible_ratio": 0.0,
                "vol_ratio": {"count": 50, "mode": 2.0},
            },
            "n8": {
                "count": 50,
                "skip_total": 50,
                "skip_reasons": {"d_star_wait": 50},
                "ri": {"count": 50, "distinct": 1, "mode": 0.5, "mode_ratio": 1.0},
            },
            "n10": {"count": 0, "actions": {}, "tiers": {}, "ri": {"count": 0}},
            "n2": {
                "count": 50,
                "degraded_ratio": 1.0,
                "fallback_flags": {"OI_NONE": 50},
                "quality_score": {"count": 50, "mode": 0.34},
            },
            "n5": {"count": 0, "dimensions": {}, "directions": {}, "strength": {}},
            "n6": {"count": 50, "degraded_ratio": 0.0, "degraded_modes": {}, "g_dim_status": {}},
            "n7": {"count": 50, "validated_ratio": 1.0, "score_gap": {}},
            "chain_completion": {"signal_chains": 0, "complete_chains": 0, "ratio": 0.0},
            "decisions": {"count": 0},
        },
        "nn_40": {
            "enabled": False,
            "reserved": True,
            "artifacts": [],
            "stale_count": 0,
            "missing_count": 0,
            "cycle": {},
            "strategy": {},
            "fund_flow_layers": {},
        },
        "outbox": {"present": False},
        "exec_22": {"ledger": {"present": False}, "sltp": {"present": False}},
    }


def test_window_for_calendar_day():
    win = di.window_for(date(2026, 11, 17), "Asia/Shanghai")
    assert win["start"] == "2026-11-17T00:00:00+08:00"
    assert win["end"] == "2026-11-18T00:00:00+08:00"
    assert win["start_ts"] < win["end_ts"]


def test_window_recent_hours():
    win = di.window_recent(24, "Asia/Shanghai")
    assert win["end_ts"] - win["start_ts"] == 24 * 3600
    assert win["mode"] == "rolling_24h"


def test_num_stats_mode_ratio():
    stats = di.num_stats([0.5, 0.5, 0.5, 0.8])
    assert stats["count"] == 4
    assert stats["distinct"] == 2
    assert stats["mode"] == 0.5
    assert stats["mode_ratio"] == 0.75


def test_detect_findings_core_23():
    findings = di.detect_findings(base_metrics(), CFG)
    ids = {f["id"] for f in findings}
    assert "23_N8_RI_CONSTANT" in ids
    assert "23_RI_CONSTANT" in ids
    assert "23_ESS_TOPDIR_EMPTY" in ids
    assert "23_TIER_PROBE" in ids
    assert "23_DSTAR_WAIT" in ids
    assert "23_N2_DEGRADED" in ids
    assert "23_SIGNAL_SILENCE" in ids
    # 40 未启用，不应产生 40 链异常
    assert not any(f["area"] == "40" for f in findings)


def test_detect_findings_ignores_40_when_reserved():
    metrics = base_metrics()
    metrics["nn_40"]["artifacts"] = [
        {
            "name": "cycle_state",
            "present": True,
            "severity": "P1",
            "ttl_seconds": 100,
            "age_hours": 999,
            "stale": True,
        }
    ]
    findings = di.detect_findings(metrics, CFG)
    assert not any(f["area"] == "40" for f in findings)


def test_collect_chain23_counts(tmp_path: Path):
    runtime = tmp_path / "23-四层闭环自进化交易架构/runtime"
    runtime.mkdir(parents=True)
    rows = [
        {"stage": "N1", "status": "enter", "ts": "2026-11-17T02:00:00+00:00"},
        {
            "stage": "N9",
            "status": "pass",
            "ts": "2026-11-17T02:01:00+00:00",
            "data": {"ri": 0.5, "tier": "probe", "l4_v": -0.016, "ess_top_direction": ""},
        },
        {
            "stage": "N9",
            "status": "pass",
            "ts": "2026-11-17T02:02:00+00:00",
            "data": {"ri": 0.5, "tier": "probe", "l4_v": -0.016, "ess_top_direction": ""},
        },
        {
            "stage": "N8",
            "status": "skip",
            "ts": "2026-11-17T02:03:00+00:00",
            "data": {"ri": 0.5, "reason_category": "d_star_wait"},
        },
        {
            "stage": "N10",
            "status": "pass",
            "ts": "2026-11-17T02:04:00+00:00",
            "chain_id": "dec-1",
            "data": {"action": "long", "ri": 0.72, "tier": "trend"},
        },
    ]
    (runtime / "chain_events-20261117.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    win = di.window_for(date(2026, 11, 17), "Asia/Shanghai")
    out = di.collect_chain23(tmp_path, win)
    assert out["events"] == 5
    assert out["n9"]["ri"]["count"] == 2
    assert out["n8"]["skip_reasons"] == {"d_star_wait": 1}
    assert out["n10"]["count"] == 1


def test_collect_nn40_disabled(tmp_path: Path):
    out = di.collect_nn40(tmp_path, CFG)
    assert out["enabled"] is False
    assert out["reserved"] is True
    assert out["artifacts"] == []


def test_render_marks_40_reserved():
    metrics = base_metrics()
    win = di.window_for(date(2026, 11, 17), "Asia/Shanghai")
    md = di.render_markdown("2026-11-17", win, metrics, [], None, {"ok": False, "error": "test"})
    assert "40 周期神经网络（预留）" in md
    assert "本期预留" in md
