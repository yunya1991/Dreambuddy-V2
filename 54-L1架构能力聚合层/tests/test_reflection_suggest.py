"""T7-3 / T7-4：反思建议产出器 + 做梦树消费口。"""

from __future__ import annotations

import json
import os
import sys

import pytest

_L1_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR = os.path.join(_L1_DIR, "scripts")
for path in (_L1_DIR, _SCRIPTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import reflection_suggest as rs  # noqa: E402


def _row(decision: str, reasons=(), strength="medium", target="BTC"):
    return {
        "ledger_id": f"{target}-{decision}-{len(reasons)}",
        "as_of": "2026-11-16",
        "target": target,
        "horizon": 20,
        "direction": 1,
        "strength": strength,
        "decision": decision,
        "reasons": list(reasons),
    }


def test_build_document_counts_gate_reasons():
    rows = [
        _row("allowed"),
        _row("blocked", ["ma_against"]),
        _row("blocked", ["ma_against"]),
        _row("blocked", ["vol_extreme", "crowded"]),
        _row("blocked", ["conflict"]),
    ]
    document = rs.build_document(rows, as_of="2026-11-16", ab_slot="B")

    summary = document["gate_summary"]
    assert summary["journal_rows"] == 5
    assert summary["allowed"] == 1
    assert summary["blocked"] == 4
    assert summary["conflicts"] == 1
    assert summary["by_reason"]["ma_against"] == 2

    types = {item["type"] for item in document["suggestions"]}
    assert "conflict_followup" in types
    assert "gate_relax" in types
    assert "gate_tighten" in types
    for item in document["suggestions"]:
        assert item["suggestion_id"]
        assert item["ab_slot"] == "B"


def test_weak_only_allowed_triggers_evidence_bar():
    document = rs.build_document([_row("allowed", strength="weak")], as_of="2026-11-16")
    assert [item["type"] for item in document["suggestions"]] == ["evidence_bar"]


def test_empty_journal_yields_zero_suggestions():
    document = rs.build_document([], as_of="2026-11-16")
    assert document["suggestion_count"] == 0
    assert document["suggestions"] == []
    assert rs.render_dreamer_feed(document) == []


def test_invalid_ab_slot_rejected():
    from l1agg.reflection import build_suggestions

    with pytest.raises(ValueError):
        build_suggestions({"allowed": [], "conflicts": []}, ab_slot="C")


def test_write_outputs_creates_feed_with_consumer(tmp_path):
    document = rs.build_document(
        [_row("blocked", ["ma_against"]), _row("blocked", ["ma_against"])],
        as_of="2026-11-16",
    )
    paths = rs.write_outputs(document, out_dir=str(tmp_path))
    assert os.path.exists(paths["suggestions"])

    with open(paths["suggestions"], encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved["suggestion_count"] == len(saved["suggestions"])

    with open(paths["dreamer_feed"], encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    assert lines
    assert all(line["consumer"] == rs.CONSUMER for line in lines)
    assert all(line["ab_slot"] in ("A", "B") for line in lines)
    assert all(line["suggestion_id"] for line in lines)


def test_no_write_does_not_touch_reflection_table(tmp_path, monkeypatch):
    db_path = str(tmp_path / "reflection.db")
    monkeypatch.setattr("l1agg.reflection.DB_FILE", db_path)

    result = rs.run(as_of="2026-11-16", out_dir=str(tmp_path / "out"), write=False)
    assert result["ok"] is True
    assert "recorded" not in result
    assert not os.path.exists(db_path)
