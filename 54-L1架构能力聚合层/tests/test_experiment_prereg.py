# -*- coding: utf-8 -*-
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from l1agg.experiment_prereg import (  # noqa: E402
    COOLDOWN_DAYS,
    DEDUP_DAYS,
    advance_status,
    apply_outcome,
    export_prereg_jsonl,
    frozen_params_hash,
    hypothesis_key,
    preregister,
    read_prereg,
)

NOW = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)


def _proposal(**overrides):
    base = {
        "relation_type": "R1",
        "target": "BTC",
        "horizon": 5,
        "param_name": "min_members",
        "delta_sign": "+",
        "hypothesis": "放宽 min_members 后超额命中率不下降",
        "evidence_ids": ["eval-1", "eval-2"],
        "params": {"min_members": 8},
    }
    base.update(overrides)
    return base


def test_hypothesis_key_is_structural():
    first = hypothesis_key(
        relation_type="R1", target="BTC", horizon=5, param_name="min_members", delta_sign="+"
    )
    second = hypothesis_key(
        relation_type="R1", target="BTC", horizon=5, param_name="min_members", delta_sign="+"
    )
    assert first == second and len(first) == 40

    flipped = hypothesis_key(
        relation_type="R1", target="BTC", horizon=5, param_name="min_members", delta_sign="-"
    )
    assert flipped != first

    other_horizon = hypothesis_key(
        relation_type="R1", target="BTC", horizon=20, param_name="min_members", delta_sign="+"
    )
    assert other_horizon != first


def test_preregister_creates_frozen_record(tmp_path):
    path = str(tmp_path / "prereg.db")
    result = preregister(_proposal(), db_path=path, now=NOW)
    assert result["ok"] is True
    assert result["experiment_id"].startswith("EXP-")
    assert result["frozen_params_hash"] == frozen_params_hash({"min_members": 8})

    rows = read_prereg(db_path=path)
    assert len(rows) == 1
    row = rows[0]
    assert (
        row["arm_scheme"] == "aba_v1"
        and row["unit"] == "period"
        and row["endpoint"] == "excess_hit"
    )
    assert row["guardrail"]["min_periods"] == 3
    assert row["evidence_ids"] == ["eval-1", "eval-2"]
    assert row["params"] == {"min_members": 8}
    assert row["status"] == "preregistered" and row["verdict"] is None


def test_duplicate_hypothesis_within_30_days_rejected(tmp_path):
    path = str(tmp_path / "prereg.db")
    first = preregister(_proposal(), db_path=path, now=NOW)
    assert first["ok"] is True

    duplicate = preregister(
        _proposal(hypothesis="换一种说法也一样被拦住", params={"min_members": 7}),
        db_path=path,
        now=NOW + timedelta(days=DEDUP_DAYS - 1),
    )
    assert duplicate["ok"] is False and duplicate["reason"] == "duplicate_hypothesis"

    later = preregister(_proposal(), db_path=path, now=NOW + timedelta(days=DEDUP_DAYS + 1))
    assert later["ok"] is True and later["experiment_id"] != first["experiment_id"]


def test_suggestion_cooldown_blocks_repeat(tmp_path):
    path = str(tmp_path / "prereg.db")
    first = preregister(_proposal(suggestion_id="SUG-1"), db_path=path, now=NOW)
    assert first["ok"] is True

    second = preregister(
        _proposal(suggestion_id="SUG-1", param_name="vol_pct_max", delta_sign="-"),
        db_path=path,
        now=NOW + timedelta(days=COOLDOWN_DAYS - 1),
    )
    assert second["ok"] is False and second["reason"] == "cooldown_active"

    third = preregister(
        _proposal(suggestion_id="SUG-1", param_name="vol_pct_max", delta_sign="-"),
        db_path=path,
        now=NOW + timedelta(days=COOLDOWN_DAYS + 1),
    )
    assert third["ok"] is True


def test_invalid_proposals_rejected(tmp_path):
    path = str(tmp_path / "prereg.db")
    assert preregister(_proposal(evidence_ids=[]), db_path=path)["reason"] == "invalid_proposal"
    assert preregister(_proposal(params={}), db_path=path)["reason"] == "invalid_proposal"
    assert (
        preregister(_proposal(arm_scheme="abcd_2x2_v1"), db_path=path)["reason"]
        == "invalid_proposal"
    )
    assert preregister(_proposal(unit="session"), db_path=path)["reason"] == "invalid_proposal"
    assert (
        preregister(_proposal(endpoint="time_to_action"), db_path=path)["reason"]
        == "invalid_proposal"
    )
    assert (
        preregister(_proposal(guardrail={"min_periods": 0}), db_path=path)["reason"]
        == "invalid_proposal"
    )
    missing = _proposal()
    missing.pop("delta_sign")
    assert preregister(missing, db_path=path)["reason"] == "invalid_proposal"


def test_status_transitions_are_guarded(tmp_path):
    path = str(tmp_path / "prereg.db")
    experiment_id = preregister(_proposal(), db_path=path, now=NOW)["experiment_id"]

    assert advance_status(experiment_id, "closed", db_path=path)["reason"] == "illegal_transition"
    assert advance_status(experiment_id, "running", db_path=path)["ok"] is True
    assert advance_status(experiment_id, "closed", db_path=path)["ok"] is True
    assert advance_status(experiment_id, "running", db_path=path)["reason"] == "illegal_transition"
    assert advance_status("EXP-nope", "running", db_path=path)["reason"] == "not_found"


def test_apply_outcome_requires_scheme_and_stores_verdict(tmp_path):
    path = str(tmp_path / "prereg.db")
    experiment_id = preregister(_proposal(), db_path=path, now=NOW)["experiment_id"]

    wrong = apply_outcome(
        {
            "experiment_id": experiment_id,
            "verdict": "verified",
            "verdict_scheme": "d3_online_ab_v1",
        },
        db_path=path,
    )
    assert wrong["ok"] is False and wrong["reason"] == "verdict_scheme_mismatch"

    bad = apply_outcome(
        {
            "experiment_id": experiment_id,
            "verdict": "probably",
            "verdict_scheme": "stat_relation_v1",
        },
        db_path=path,
    )
    assert bad["ok"] is False and bad["reason"] == "invalid_verdict"

    ok = apply_outcome(
        {
            "experiment_id": experiment_id,
            "verdict": "verified",
            "verdict_scheme": "stat_relation_v1",
            "effect": 0.041,
            "reason_code": "eight_periods_same_sign",
        },
        db_path=path,
    )
    assert ok["ok"] is True
    row = read_prereg(db_path=path)[0]
    assert row["verdict"] == "verified" and row["verdict_scheme"] == "stat_relation_v1"
    assert abs(row["effect"] - 0.041) < 1e-9
    assert row["evaluated_at"]


def test_export_jsonl_for_ingest(tmp_path):
    path = str(tmp_path / "prereg.db")
    preregister(_proposal(), db_path=path, now=NOW)
    preregister(_proposal(param_name="hit_extreme_z", delta_sign="+"), db_path=path, now=NOW)
    out = str(tmp_path / "experiment_prereg.jsonl")
    result = export_prereg_jsonl(out, db_path=path)
    assert result["exported"] == 2
    with open(out, "r", encoding="utf-8") as fh:
        lines = [line for line in fh.read().splitlines() if line.strip()]
    assert len(lines) == 2
    assert '"unit": "period"' in lines[0]


def test_missing_registry_is_fail_open(tmp_path):
    path = str(tmp_path / "absent.db")
    assert read_prereg(db_path=path) == []
    assert (
        apply_outcome(
            {"experiment_id": "X", "verdict": "verified", "verdict_scheme": "stat_relation_v1"},
            db_path=path,
        )["reason"]
        == "registry_missing"
    )
    assert advance_status("X", "running", db_path=path)["reason"] == "registry_missing"
