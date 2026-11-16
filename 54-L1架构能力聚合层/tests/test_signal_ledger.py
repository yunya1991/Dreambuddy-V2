# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from l1agg.signal import apply_gating, synthesize_signals  # noqa: E402
from l1agg.signal_ledger import (  # noqa: E402
    forbidden_columns,
    journal_columns,
    read_journal,
    record_signals,
)

STAMP = "2026-11-16T00:00:00+00:00"


def _row(eval_id, *, target="BTC", horizon=5, rank_ic=0.35, excess=0.25, gate=1):
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


def _gated():
    return apply_gating(
        synthesize_signals([_row("e1"), _row("e2", target="SP500")], as_of="2026-11-16"),
        {
            "BTC": {"ma_state": "up", "vol_pct": 0.3, "crowd_pct": 0.2},
            "SP500": {"ma_state": "down", "vol_pct": 0.3, "crowd_pct": 0.2},
        },
    )


def test_record_allowed_and_blocked(tmp_path):
    path = str(tmp_path / "ledger.db")
    result = record_signals(_gated(), db_path=path, recorded_at=STAMP)
    assert result["ok"] is True
    assert result["inserted"] == 2 and result["duplicates"] == 0

    allowed = read_journal(db_path=path, decision="allowed")
    blocked = read_journal(db_path=path, decision="blocked")
    assert [row["target"] for row in allowed] == ["BTC"]
    assert [row["target"] for row in blocked] == ["SP500"]
    assert blocked[0]["reasons"] == ["ma_against"]
    assert blocked[0]["context"]["ma_state"] == "down"
    assert allowed[0]["members"] == ["e1"]


def test_record_is_idempotent(tmp_path):
    path = str(tmp_path / "ledger.db")
    first = record_signals(_gated(), db_path=path, recorded_at=STAMP)
    second = record_signals(_gated(), db_path=path, recorded_at=STAMP)
    assert first["inserted"] == 2
    assert second["inserted"] == 0 and second["duplicates"] == 2
    assert len(read_journal(db_path=path)) == 2


def test_journal_has_no_trading_columns(tmp_path):
    path = str(tmp_path / "ledger.db")
    record_signals(_gated(), db_path=path, recorded_at=STAMP)
    columns = journal_columns(db_path=path)
    assert "decision" in columns and "reasons_json" in columns
    assert forbidden_columns(db_path=path) == []


def test_read_journal_filter_and_limit(tmp_path):
    path = str(tmp_path / "ledger.db")
    record_signals(_gated(), db_path=path, recorded_at=STAMP)
    assert len(read_journal(db_path=path, target="BTC")) == 1
    assert read_journal(db_path=path, target="NOPE") == []
    assert len(read_journal(db_path=path, limit=1)) == 1


def test_record_empty_document(tmp_path):
    path = str(tmp_path / "ledger.db")
    result = record_signals(
        {"signals": [], "blocked": [], "conflicts": []}, db_path=path, recorded_at=STAMP
    )
    assert result["inserted"] == 0 and result["duplicates"] == 0
    assert read_journal(db_path=path) == []


def test_missing_ledger_reads_as_empty(tmp_path):
    assert read_journal(db_path=str(tmp_path / "absent.db")) == []
    assert journal_columns(db_path=str(tmp_path / "absent.db")) == []


def test_signal_query_to_ledger_end_to_end(tmp_path):
    from test_signal_exports import _db
    from test_signal_exports import _row as _export_row

    registry = _db(tmp_path, [_export_row("e1")])
    from l1agg.capabilities.signal_exports import signal_query

    out = signal_query(
        db_path=str(registry),
        as_of="2026-11-16",
        context={"BTC": {"ma_state": "up", "vol_pct": 0.2, "crowd_pct": 0.2}},
    )
    ledger = str(tmp_path / "ledger.db")
    result = record_signals(out["data"], db_path=ledger, recorded_at=STAMP)
    assert result["inserted"] == 1
    rows = read_journal(db_path=ledger)
    assert rows[0]["decision"] == "allowed"
    assert rows[0]["target"] == "BTC"
    assert rows[0]["as_of"] == "2026-11-16"
    assert forbidden_columns(db_path=ledger) == []
