# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from l1agg.reflection import (  # noqa: E402
    SCHEMA_VERSION,
    apply_outcomes,
    build_suggestions,
    read_suggestions,
    record_suggestions,
    validate_suggestions,
)

STAMP = "2026-11-16T00:00:00+00:00"


def _gated(**overrides):
    base = {
        "allowed": [],
        "blocked": [],
        "conflicts": [],
        "ablation": {"by_reason": {"ma_against": 0, "vol_extreme": 0, "crowded": 0, "conflict": 0}},
    }
    base.update(overrides)
    return base


def test_conflict_generates_followup_suggestion():
    document = build_suggestions(
        _gated(conflicts=[{"target": "BTC", "horizon": 5}]), as_of="2026-11-16"
    )
    assert document["suggestion_count"] == 1
    item = document["suggestions"][0]
    assert item["type"] == "conflict_followup"
    assert item["ab_slot"] == "B"
    assert item["status"] == "pending"
    assert item["evidence"] == {"conflicts": 1}
    assert validate_suggestions(document) == []


def test_gate_relax_and_tighten_thresholds():
    relax = build_suggestions(_gated(ablation={"by_reason": {"ma_against": 2}}), as_of="2026-11-16")
    assert [item["type"] for item in relax["suggestions"]] == ["gate_relax"]

    tighten = build_suggestions(
        _gated(ablation={"by_reason": {"vol_extreme": 1, "crowded": 1}}), as_of="2026-11-16"
    )
    assert [item["type"] for item in tighten["suggestions"]] == ["gate_tighten"]
    assert tighten["suggestions"][0]["evidence"] == {"extreme_blocked": 2}

    below = build_suggestions(
        _gated(ablation={"by_reason": {"ma_against": 1, "vol_extreme": 1}}), as_of="2026-11-16"
    )
    assert below["suggestion_count"] == 0


def test_weak_only_allowed_raises_evidence_bar():
    document = build_suggestions(
        _gated(allowed=[{"target": "BTC", "horizon": 5, "strength": "weak"}]),
        as_of="2026-11-16",
    )
    assert [item["type"] for item in document["suggestions"]] == ["evidence_bar"]


def test_suggestion_ids_are_deterministic():
    doc = _gated(conflicts=[{"target": "BTC", "horizon": 5}])
    first = build_suggestions(doc, as_of="2026-11-16")
    second = build_suggestions(doc, as_of="2026-11-16")
    assert first == second
    assert first["suggestions"][0]["suggestion_id"].startswith("SUG-conflict_followup-2026-11-16-")


def test_validate_requires_ab_slot_and_unique_ids():
    document = build_suggestions(_gated(conflicts=[{"target": "BTC"}]), as_of="2026-11-16")
    document["suggestions"][0]["ab_slot"] = ""
    assert any("ab_slot" in error for error in validate_suggestions(document))

    duplicated = build_suggestions(_gated(conflicts=[{"target": "BTC"}]), as_of="2026-11-16")
    duplicated["suggestions"].append(dict(duplicated["suggestions"][0]))
    assert any("重复" in error for error in validate_suggestions(duplicated))


def test_record_is_idempotent_and_rejects_invalid(tmp_path):
    path = str(tmp_path / "reflection.db")
    document = build_suggestions(
        _gated(
            conflicts=[{"target": "BTC", "horizon": 5}],
            ablation={"by_reason": {"ma_against": 2}},
        ),
        as_of="2026-11-16",
    )
    first = record_suggestions(document, db_path=path, created_at=STAMP)
    assert first["ok"] is True and first["inserted"] == 2
    second = record_suggestions(document, db_path=path, created_at=STAMP)
    assert second["inserted"] == 0 and second["duplicates"] == 2

    broken = {
        "schema_version": SCHEMA_VERSION,
        "as_of": "2026-11-16",
        "suggestions": [{"type": "gate_relax"}],
    }
    rejected = record_suggestions(broken, db_path=path)
    assert rejected["ok"] is False and rejected["inserted"] == 0


def test_outcomes_backfill_and_slot_mismatch(tmp_path):
    path = str(tmp_path / "reflection.db")
    document = build_suggestions(
        _gated(conflicts=[{"target": "BTC"}], ablation={"by_reason": {"ma_against": 2}}),
        as_of="2026-11-16",
    )
    record_suggestions(document, db_path=path, created_at=STAMP)
    ids = [item["suggestion_id"] for item in document["suggestions"]]

    result = apply_outcomes(
        [
            {"suggestion_id": ids[0], "ab_slot": "B", "metric": "excess_hit", "delta": 0.02},
            {"suggestion_id": "SUG-unknown", "ab_slot": "B"},
            {"suggestion_id": ids[1], "ab_slot": "A"},
        ],
        db_path=path,
        evaluated_at=STAMP,
    )
    assert result == {
        "ok": True,
        "matched": 1,
        "unknown": 1,
        "ab_slot_mismatch": 1,
        "evaluated_at": STAMP,
    }
    assert len(read_suggestions(db_path=path, status="evaluated")) == 1
    rejected = read_suggestions(db_path=path, status="rejected")
    assert len(rejected) == 1 and rejected[0]["suggestion_id"] == ids[1]
    evaluated = read_suggestions(db_path=path, status="evaluated")[0]
    assert evaluated["outcome"]["delta"] == 0.02


def test_outcomes_on_missing_ledger(tmp_path):
    result = apply_outcomes([{"suggestion_id": "X"}], db_path=str(tmp_path / "absent.db"))
    assert result["ok"] is False and result["reason"] == "ledger_missing"
    assert read_suggestions(db_path=str(tmp_path / "absent.db")) == []
