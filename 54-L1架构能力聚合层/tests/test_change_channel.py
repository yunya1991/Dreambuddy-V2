# -*- coding: utf-8 -*-
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from l1agg.change_channel import (  # noqa: E402
    decide_verdict,
    nested_check,
    propose_change,
    record_verdict,
)
from l1agg.experiment_prereg import preregister, read_prereg  # noqa: E402

DATES = [str(date(2026, 1, 1) + timedelta(days=i)) for i in range(40)]

OK_STATS = {
    "degraded": False,
    "leakage_free": True,
    "mean_inner_score": 0.5,
    "mean_outer_score": 0.48,
    "selection_gap": 0.02,
}


def _eval(candidate, train, test):
    return 1.0 if candidate == "good" else 0.0


def test_nested_check_runs_48_walk_forward():
    stats = nested_check(DATES, ["good", "bad"], _eval)
    assert stats["degraded"] is False
    assert stats["leakage_free"] is True
    assert stats["n_outer_folds"] == 4
    assert stats["mean_outer_score"] == 1.0
    assert "folds" not in stats


def test_nested_check_degrades_on_short_history():
    stats = nested_check(DATES[:10], ["good"], _eval)
    assert stats["degraded"] is True
    assert stats["reason"] == "insufficient_dates"


def test_decide_verdict_rules_in_order():
    assert decide_verdict(
        {"degraded": True, "reason": "no_valid_fold"},
        same_sign_periods=9,
        wilson_lb=0.9,
        base_rate=0.5,
        effect_bps=50,
        cost_bps=10,
    ) == {"verdict": "insufficient_data", "reason_code": "no_valid_fold"}

    assert (
        decide_verdict(
            {**OK_STATS, "leakage_free": False},
            same_sign_periods=9,
            wilson_lb=0.9,
            base_rate=0.5,
            effect_bps=50,
            cost_bps=10,
        )["verdict"]
        == "insufficient_data"
    )

    assert (
        decide_verdict(
            {**OK_STATS, "mean_inner_score": 0.0},
            same_sign_periods=9,
            wilson_lb=0.9,
            base_rate=0.5,
            effect_bps=50,
            cost_bps=10,
        )["reason_code"]
        == "non_positive_inner_score"
    )

    assert (
        decide_verdict(
            {**OK_STATS, "selection_gap": 0.2},
            same_sign_periods=9,
            wilson_lb=0.9,
            base_rate=0.5,
            effect_bps=50,
            cost_bps=10,
        )["reason_code"]
        == "selection_overfit"
    )

    assert (
        decide_verdict(
            OK_STATS,
            same_sign_periods=4,
            wilson_lb=0.9,
            base_rate=0.5,
            effect_bps=50,
            cost_bps=10,
            opposite_significant=True,
        )["verdict"]
        == "falsified"
    )

    assert (
        decide_verdict(
            OK_STATS,
            same_sign_periods=2,
            wilson_lb=0.9,
            base_rate=0.5,
            effect_bps=50,
            cost_bps=10,
        )["reason_code"]
        == "fewer_than_three_periods"
    )


def test_verified_requires_eight_periods_and_economics():
    seven = decide_verdict(
        OK_STATS, same_sign_periods=7, wilson_lb=0.9, base_rate=0.5, effect_bps=50, cost_bps=10
    )
    assert seven == {"verdict": "candidate", "reason_code": "three_to_seven_periods"}

    weak_wilson = decide_verdict(
        OK_STATS, same_sign_periods=8, wilson_lb=0.5, base_rate=0.5, effect_bps=50, cost_bps=10
    )
    assert weak_wilson["verdict"] == "candidate"

    expensive = decide_verdict(
        OK_STATS, same_sign_periods=8, wilson_lb=0.9, base_rate=0.5, effect_bps=8, cost_bps=10
    )
    assert expensive["verdict"] == "candidate"

    verified = decide_verdict(
        OK_STATS, same_sign_periods=8, wilson_lb=0.9, base_rate=0.5, effect_bps=50, cost_bps=10
    )
    assert verified == {"verdict": "verified", "reason_code": "eight_periods_and_wilson_above_base"}


def test_propose_change_requires_verified(tmp_path):
    rejected = propose_change(
        experiment_id="EXP-1",
        verdict="candidate",
        current_version="stats-2026.11.1",
        params={"min_members": 8},
        frozen_params_hash="abc",
        rollback_dir=str(tmp_path),
    )
    assert rejected == {"ok": False, "reason": "not_verified", "verdict": "candidate"}
    assert not any(tmp_path.iterdir())

    ok = propose_change(
        experiment_id="EXP-1",
        verdict="verified",
        current_version="stats-2026.11.1",
        params={"min_members": 8},
        frozen_params_hash="abc",
        rollback_dir=str(tmp_path),
    )
    assert ok["ok"] is True
    assert ok["previous_version"] == "stats-2026.11.1"
    assert ok["new_version"] == "stats-2026.11.2"

    with open(ok["snapshot_path"], "r", encoding="utf-8") as fh:
        snapshot = json.load(fh)
    assert snapshot["previous_version"] == "stats-2026.11.1"
    assert snapshot["frozen_params_hash"] == "abc"
    assert snapshot["params"] == {"min_members": 8}


def test_record_verdict_writes_prereg(tmp_path):
    db_path = str(tmp_path / "prereg.db")
    experiment_id = preregister(
        {
            "relation_type": "R1",
            "target": "BTC",
            "horizon": 5,
            "param_name": "min_members",
            "delta_sign": "+",
            "hypothesis": "放宽 min_members 后超额不降",
            "evidence_ids": ["eval-1"],
            "params": {"min_members": 8},
        },
        db_path=db_path,
    )["experiment_id"]

    decision = decide_verdict(
        OK_STATS, same_sign_periods=8, wilson_lb=0.9, base_rate=0.5, effect_bps=50, cost_bps=10
    )
    assert (
        record_verdict(
            experiment_id=experiment_id, decision=decision, effect=50.0, db_path=db_path
        )["ok"]
        is True
    )

    row = read_prereg(db_path=db_path)[0]
    assert row["verdict"] == "verified"
    assert row["verdict_scheme"] == "stat_relation_v1"
    assert row["reason_code"] == "eight_periods_and_wilson_above_base"
