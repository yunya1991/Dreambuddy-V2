# -*- coding: utf-8 -*-
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from l1agg.signal import (  # noqa: E402
    SCHEMA_VERSION,
    apply_gating,
    synthesize_signals,
    to_json,
    validate_document,
    validate_gated,
)


def _row(eval_id, *, target="BTC", horizon=5, rank_ic=0.3, excess=0.25, gate=True):
    return {
        "eval_id": eval_id,
        "target": target,
        "horizon": horizon,
        "method": "B14",
        "transform": "raw",
        "rank_ic": rank_ic,
        "excess_hit": excess,
        "gate_pass": gate,
    }


def test_single_strong_relationship_becomes_signal():
    document = synthesize_signals([_row("e1")], as_of="2026-11-16")
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["signal_count"] == 1
    signal = document["signals"][0]
    assert signal["signal_id"] == "SIG-BTC-h5"
    assert signal["direction"] == 1
    assert signal["strength"] == "strong"
    assert signal["score"] == 1.0
    assert signal["members"] == ["e1"]
    assert signal["as_of"] == "2026-11-16"
    assert validate_document(document) == []


def test_negative_direction_and_buckets():
    document = synthesize_signals(
        [_row("e1", rank_ic=-0.2, excess=0.12), _row("e2", target="SP500", excess=0.05)]
    )
    btc = next(item for item in document["signals"] if item["target"] == "BTC")
    sp500 = next(item for item in document["signals"] if item["target"] == "SP500")
    assert btc["direction"] == -1 and btc["strength"] == "medium"
    assert sp500["direction"] == 1 and sp500["strength"] == "weak"
    assert document["skipped"] == 0


def test_same_direction_members_are_weighted():
    document = synthesize_signals([_row("e1", excess=0.25), _row("e2", excess=0.12)])
    signal = document["signals"][0]
    assert signal["members"] == ["e1", "e2"]
    assert signal["weight"] == 1.6
    assert signal["score"] == 1.0
    assert signal["strength"] == "strong"


def test_conflict_is_reported_without_signal():
    document = synthesize_signals(
        [
            _row("e1", rank_ic=0.4, excess=0.30),
            _row("e2", rank_ic=-0.3, excess=0.05),
        ]
    )
    assert document["signal_count"] == 0
    assert document["conflict_count"] == 1
    conflict = document["conflicts"][0]
    assert conflict["target"] == "BTC" and conflict["horizon"] == 5
    assert {member["direction"] for member in conflict["members"]} == {1, -1}
    assert validate_document(document) == []


def test_skips_weak_gated_and_invalid_rows():
    document = synthesize_signals(
        [
            _row("e1", excess=0.01),
            _row("e2", gate=False),
            _row("e3", rank_ic=0.0),
            _row("e4", target="", excess=0.30),
        ]
    )
    assert document["signal_count"] == 0
    assert document["skipped"] == 4


def test_output_is_deterministic():
    rows = [_row("e2", excess=0.12), _row("e1", excess=0.25)]
    first = to_json(synthesize_signals(rows, as_of="2026-11-16"))
    second = to_json(synthesize_signals(list(reversed(rows)), as_of="2026-11-16"))
    assert first == second
    assert json.loads(first)["signals"][0]["members"] == ["e1", "e2"]


def test_validate_rejects_bad_documents():
    document = synthesize_signals([_row("e1")])
    document["signals"][0]["direction"] = 0
    document["signals"][0]["strength"] = "extreme"
    errors = validate_document(document)
    assert any("direction" in error for error in errors)
    assert any("strength" in error for error in errors)

    duplicated = synthesize_signals([_row("e1")])
    duplicated["signals"].append(dict(duplicated["signals"][0]))
    assert any("重复" in error for error in validate_document(duplicated))


def _ctx(**overrides):
    base = {"ma_state": "up", "vol_pct": 0.4, "crowd_pct": 0.3}
    base.update(overrides)
    return base


def test_gating_allows_aligned_signal():
    gated = apply_gating(synthesize_signals([_row("e1")]), {"BTC": _ctx()})
    assert gated["signal_count"] == 1 and gated["blocked_count"] == 0
    assert gated["allowed"][0]["gating"]["decision"] == "allowed"
    assert gated["allowed"][0]["gating"]["context"]["ma_state"] == "up"
    assert validate_gated(gated) == []


def test_gating_blocks_against_trend_or_extremes():
    gated = apply_gating(
        synthesize_signals([_row("e1")]),
        {"BTC": _ctx(ma_state="down", vol_pct=0.95, crowd_pct=0.95)},
    )
    reasons = gated["blocked"][0]["gating"]["reasons"]
    assert set(reasons) == {"ma_against", "vol_extreme", "crowded"}
    assert gated["signal_count"] == 0
    assert gated["ablation"]["by_reason"]["ma_against"] == 1
    assert validate_gated(gated) == []


def test_gating_blocks_conflict_and_missing_context():
    conflict = synthesize_signals(
        [_row("e1", rank_ic=0.4, excess=0.30), _row("e2", rank_ic=-0.3, excess=0.05)]
    )
    gated = apply_gating(conflict, {})
    assert gated["blocked"][0]["gating"]["reasons"] == ["conflict"]
    assert gated["ablation"]["by_reason"]["conflict"] == 1

    missing = apply_gating(synthesize_signals([_row("e1")]), {})
    assert missing["blocked"][0]["gating"]["reasons"] == ["missing_context"]
    assert missing["ablation"]["by_reason"]["missing_context"] == 1


def test_gating_ablation_no_gate_vs_with_gate():
    rows = [_row("e1", target="BTC"), _row("e2", target="SP500", excess=0.12)]
    gated = apply_gating(
        synthesize_signals(rows),
        {"BTC": _ctx(), "SP500": _ctx(ma_state="down")},
    )
    assert gated["ablation"]["no_gate"]["signals"] == 2
    assert gated["ablation"]["with_gate"]["signals"] == 1
    assert gated["ablation"]["delta"] == 1
    assert gated["ablation"]["no_gate"]["targets"] == ["BTC", "SP500"]
    assert gated["ablation"]["with_gate"]["targets"] == ["BTC"]


def test_gated_validation_rejects_bad_blocked():
    gated = apply_gating(synthesize_signals([_row("e1")]), {})
    gated["blocked"][0]["gating"]["reasons"] = []
    assert any("reasons" in error for error in validate_gated(gated))
