# -*- coding: utf-8 -*-
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from l1agg.experiment_registry import (  # noqa: E402
    build_registry,
    from_emergence,
    from_prereg,
    load_emergence_dashboard,
    read_registry,
    summarize,
    write_registry,
)

STAMP = "2026-11-16T12:00:00+00:00"


def _prereg(**overrides):
    base = {
        "experiment_id": "EXP-abc-20261116-01",
        "arm_scheme": "aba_v1",
        "endpoint": "excess_hit",
        "status": "running",
        "verdict": None,
        "verdict_scheme": None,
        "reason_code": None,
        "periods_observed": 4,
    }
    base.update(overrides)
    return base


def _emergence(entry):
    return from_emergence(entry, generated_at=STAMP)


def test_from_prereg_maps_period_record():
    record = from_prereg(
        _prereg(verdict="verified", reason_code="eight_periods_same_sign"), generated_at=STAMP
    )
    assert record["unit"] == "period"
    assert record["arm_scheme"] == "aba_v1"
    assert record["endpoint"] == "excess_hit"
    assert record["verdict"] == "verified"
    assert record["verdict_scheme"] == "stat_relation_v1"
    assert record["n"] == 4
    assert record["provenance"] == "experiment_prereg.db"


def test_empty_verdict_has_no_scheme():
    record = from_prereg(_prereg(), generated_at=STAMP)
    assert record["verdict"] is None and record["verdict_scheme"] is None


def test_from_emergence_maps_session_record():
    record = _emergence(
        {
            "run_id": "D3A-0000ebfa7eba",
            "verdict": "verified",
            "reason": "CI_low>0",
            "evidence": "experiments/d3a.json",
        }
    )
    assert record["unit"] == "session"
    assert record["arm_scheme"] == "abcd_2x2_v1"
    assert record["endpoint"] == "time_to_correct_action"
    assert record["verdict_scheme"] == "d3_online_ab_v1"
    assert record["status"] == "closed"


def test_build_registry_keeps_units_separate():
    document = build_registry(
        [_prereg()], [_emergence({"run_id": "D3A-1", "verdict": "candidate"})], generated_at=STAMP
    )
    assert document["record_count"] == 2
    assert [record["unit"] for record in document["records"]] == ["period", "session"]
    assert document["skipped"] == []


def test_build_registry_rejects_bad_records():
    bad_prereg = _prereg(experiment_id="EXP-bad", arm_scheme="abcd_2x2_v1")
    bad_session = _emergence({"run_id": "D3A-bad", "verdict": "probably"})
    document = build_registry([bad_prereg], [bad_session], generated_at=STAMP)
    assert document["record_count"] == 0
    reasons = {item["reason"] for item in document["skipped"]}
    assert reasons == {"arm_scheme_mismatch", "invalid_verdict"}


def test_build_registry_dedupes_same_experiment():
    first = _prereg(verdict=None)
    second = _prereg(verdict="candidate", periods_observed=5)
    document = build_registry([first, second], [], generated_at=STAMP)
    assert document["record_count"] == 1
    assert document["records"][0]["verdict"] == "candidate"


def test_summarize_never_crosses_units():
    document = build_registry(
        [_prereg(verdict="verified")],
        [
            _emergence({"run_id": "D3A-1", "verdict": "candidate"}),
            _emergence({"run_id": "D3A-2", "verdict": "candidate"}),
        ],
        generated_at=STAMP,
    )
    summary = summarize(document)
    assert summary["cross_unit_total"] is None
    period, session = summary["units"]
    assert period["total"] == 1 and period["verdicts"]["verified"] == 1
    assert session["total"] == 2 and session["verdicts"]["candidate"] == 2


def test_write_and_read_roundtrip(tmp_path):
    document = build_registry([_prereg(verdict="verified")], [], generated_at=STAMP)
    path = str(tmp_path / "experiment_registry.jsonl")
    assert write_registry(document, path)["written"] == 1
    rows = read_registry(path)
    assert len(rows) == 1 and rows[0]["experiment_id"] == "EXP-abc-20261116-01"
    assert read_registry(str(tmp_path / "absent.jsonl")) == []


def test_load_emergence_dashboard_fail_open(tmp_path):
    assert load_emergence_dashboard(str(tmp_path / "absent.json")) == []

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_emergence_dashboard(str(broken)) == []

    good = tmp_path / "dashboard.json"
    good.write_text(
        json.dumps(
            {
                "generated_at": "2026-11-09T17:13:41+00:00",
                "entries": [
                    {"run_id": "D3A-1", "verdict": "candidate", "evidence": "experiments/d3a.json"},
                    "not-a-dict",
                ],
            }
        ),
        encoding="utf-8",
    )
    rows = load_emergence_dashboard(str(good))
    assert len(rows) == 1
    assert rows[0]["generated_at"] == "2026-11-09T17:13:41+00:00"
