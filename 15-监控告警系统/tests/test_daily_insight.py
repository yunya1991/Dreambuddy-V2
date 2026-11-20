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


def _outbox_db(tmp_path: Path, rows: list[tuple]) -> Path:
    import sqlite3

    runtime = tmp_path / "23-四层闭环自进化交易架构/runtime"
    runtime.mkdir(parents=True)
    db = runtime / "execution_outbox.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE execution_outbox (state TEXT, created_at TEXT, updated_at TEXT)")
    conn.executemany("INSERT INTO execution_outbox VALUES (?,?,?)", rows)
    conn.commit()
    conn.close()
    return tmp_path


def test_collect_outbox_uses_window_ratio(tmp_path: Path):
    """历史存量失败不应污染当窗失败率；submitted 是生产终态不算 stuck。"""
    old = "2026-11-10T00:00:00+00:00"
    win_ts = "2026-11-17T03:00:00+00:00"  # Asia/Shanghai 11-17 11:00
    rows = [
        ("failed", old, old),
        ("failed", old, old),
        ("failed", old, old),
        ("filled", win_ts, win_ts),
        ("submitted", win_ts, win_ts),
        ("submitted", win_ts, win_ts),
        ("submitted", win_ts, win_ts),
    ]
    repo = _outbox_db(tmp_path, rows)

    win = di.window_for(date(2026, 11, 17), "Asia/Shanghai")
    out = di.collect_outbox(repo, win, 300)

    assert out["present"] is True
    assert out["window_states"]["submitted"] == 3
    assert out["window_total"] == 4
    assert out["window_attempts"] == 4
    assert out["window_failed"] == 0
    assert out["window_failed_ratio"] == 0.0
    # 累计口径仍保留（3/7 失败）
    assert out["failed_ratio"] == round(3 / 7, 4)
    # submitted 即使很旧也不是 stuck
    assert out["stuck"] == 0


def test_collect_outbox_stuck_only_pending(tmp_path: Path):
    stale = "2026-11-17T03:00:00+00:00"
    rows = [
        ("pending", stale, stale),
        ("submitting", stale, stale),
        ("submitted", stale, stale),
        ("archived", stale, stale),
    ]
    repo = _outbox_db(tmp_path, rows)
    win = di.window_for(date(2026, 11, 17), "Asia/Shanghai")
    out = di.collect_outbox(repo, win, 300)
    assert out["stuck"] == 2


def test_detect_findings_outbox_prefers_window_ratio():
    metrics = base_metrics()
    metrics["outbox"] = {
        "present": True,
        "total": 1158,
        "states": {"failed": 1142, "submitted": 16},
        "failed_ratio": 0.9862,
        "window_total": 20,
        "window_states": {"filled": 20},
        "window_attempts": 20,
        "window_failed": 0,
        "window_failed_ratio": 0.0,
        "stuck": 0,
    }
    ids = {f["id"] for f in di.detect_findings(metrics, CFG)}
    assert "22_OUTBOX_FAILED" not in ids
    assert "22_OUTBOX_STUCK" not in ids

    metrics["outbox"]["window_failed"] = 10
    metrics["outbox"]["window_failed_ratio"] = 0.5
    ids = {f["id"] for f in di.detect_findings(metrics, CFG)}
    assert "22_OUTBOX_FAILED" in ids


def test_push_decision_suppresses_empty_window():
    metrics = base_metrics()
    assert di.push_decision(metrics, True, False) == (True, "ok")
    assert di.push_decision(metrics, False, False) == (False, "not requested")

    metrics["chain_23"]["events"] = 0
    ok, reason = di.push_decision(metrics, True, False)
    assert ok is False
    assert "无 23 链路事件" in reason
    # 显式覆盖仍然可推
    assert di.push_decision(metrics, True, True) == (True, "ok")


def test_render_marks_40_reserved():
    metrics = base_metrics()
    win = di.window_for(date(2026, 11, 17), "Asia/Shanghai")
    md = di.render_markdown("2026-11-17", win, metrics, [], None, {"ok": False, "error": "test"})
    assert "40 周期神经网络（预留）" in md
    assert "本期预留" in md


def test_chain_stale_gate_suppresses_chain_findings():
    """链路停跑时只报数据缺失，不再输出推理链降级类误报。"""
    metrics = base_metrics()
    metrics["chain_23"]["last_event_age_hours"] = 19.0
    ids = {f["id"] for f in di.detect_findings(metrics, CFG)}
    assert "23_CHAIN_STALE" in ids
    assert "23_N2_DEGRADED" not in ids
    assert "23_RI_CONSTANT" not in ids
    assert "23_ESS_TOPDIR_EMPTY" not in ids
    assert "23_DSTAR_WAIT" not in ids


def test_chain_no_event_gate():
    metrics = base_metrics()
    chain = metrics["chain_23"]
    chain["events"] = 0
    chain["n9"] = {"count": 0, "ri": {"count": 0}, "tier": {}, "l4_v": {}}
    chain["n2"] = {"count": 0, "degraded_ratio": 0.0}
    chain["n10"] = {"count": 0}
    ids = {f["id"] for f in di.detect_findings(metrics, CFG)}
    assert "23_CHAIN_NO_EVENT" in ids
    assert "23_SIGNAL_SILENCE" not in ids


def test_dstar_uses_full_distribution_not_skip_reason():
    """N8 有 pass 样本时，skip 原因全是 d_star_wait 不应报「恒 WAIT」。"""
    metrics = base_metrics()
    n8 = metrics["chain_23"]["n8"]
    n8["d_star"] = {"long": 400, "WAIT": 100}
    n8["d_star_wait_ratio"] = 0.2
    ids = {f["id"] for f in di.detect_findings(metrics, CFG)}
    assert "23_DSTAR_WAIT" not in ids


def test_dstar_all_wait_flagged_by_distribution():
    metrics = base_metrics()
    n8 = metrics["chain_23"]["n8"]
    n8["d_star"] = {"WAIT": 500}
    n8["d_star_wait_ratio"] = 1.0
    findings = {f["id"]: f for f in di.detect_findings(metrics, CFG)}
    assert "23_DSTAR_WAIT" in findings
    assert "全量 d_star=WAIT" in findings["23_DSTAR_WAIT"]["title"]
