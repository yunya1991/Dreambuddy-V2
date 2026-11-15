# -*- coding: utf-8 -*-
"""L1D-09 comparison 对照表 + 三重障碍事后打分单测（ADR-V17）。"""

import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.trading import comparison, store  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "trading.db")
    store.migrate(path)
    return path


def test_record_and_idempotent_fill(db):
    row = comparison.record_comparison(
        "2026-11-14", "BTC", l1_direction=1, l1_strength=0.72, l2_verdict="bullish", db_path=db
    )
    assert row["l1_direction"] == 1 and row["l2_verdict"] == "bullish"
    again = comparison.record_comparison(
        "2026-11-14", "BTC", l1_direction=1, l1_strength=0.72, db_path=db
    )
    assert again["l1_direction"] == 1
    assert len(comparison.list_comparisons(db)) == 1


def test_l2_cannot_overwrite_l1(db):
    comparison.record_comparison("2026-11-14", "BTC", l1_direction=1, l1_strength=0.72, db_path=db)
    with pytest.raises(comparison.ComparisonError):
        comparison.record_comparison(
            "2026-11-14", "BTC", l1_direction=-1, l1_strength=0.72, db_path=db
        )
    with pytest.raises(comparison.ComparisonError):
        comparison.record_comparison(
            "2026-11-14", "BTC", l1_direction=1, l1_strength=0.5, db_path=db
        )
    row = comparison.list_comparisons(db)[0]
    assert row["l1_direction"] == 1 and row["l1_strength"] == 0.72


def test_l2_verdict_first_write_wins(db):
    comparison.record_comparison("2026-11-14", "BTC", l1_direction=1, l1_strength=0.7, db_path=db)
    assert comparison.set_l2_verdict("2026-11-14", "BTC", "bullish", db_path=db) is True
    assert comparison.set_l2_verdict("2026-11-14", "BTC", "bullish", db_path=db) is False
    with pytest.raises(comparison.ComparisonError):
        comparison.set_l2_verdict("2026-11-14", "BTC", "bearish", db_path=db)
    assert comparison.list_comparisons(db)[0]["l2_verdict"] == "bullish"


def test_triple_barrier_upper_hit_long():
    out = comparison.triple_barrier(
        100.0, [101.0, 103.0], [99.0, 100.0], atr=1.0, direction=1, closes=[101.0, 103.0]
    )
    assert out["label"] == comparison.LABEL_UPPER
    assert out["bars"] == 2 and out["exit_px"] == 102.0
    assert out["gross_ret"] == pytest.approx(0.02)
    assert out["cost"] == pytest.approx(0.006)
    assert out["realized_ret"] == pytest.approx(0.014)


def test_triple_barrier_lower_hit_short():
    out = comparison.triple_barrier(
        100.0, [101.0, 100.0], [99.0, 97.0], atr=1.0, direction=-1, closes=[100.0, 97.0]
    )
    assert out["label"] == comparison.LABEL_LOWER
    assert out["exit_px"] == 98.0
    assert out["gross_ret"] == pytest.approx(0.02)
    assert out["realized_ret"] == pytest.approx(0.014)


def test_triple_barrier_time_exit():
    out = comparison.triple_barrier(
        100.0,
        [100.5] * 12,
        [99.5] * 12,
        atr=1.0,
        direction=1,
        closes=[100.0] * 12,
    )
    assert out["label"] == comparison.LABEL_TIME
    assert out["bars"] == comparison.BARRIER_DAYS
    assert out["exit_px"] == 100.0
    assert out["gross_ret"] == 0.0
    assert out["realized_ret"] == pytest.approx(-0.006)


def test_score_comparison_writes_back(db):
    comparison.record_comparison("2026-11-14", "BTC", l1_direction=1, l1_strength=0.7, db_path=db)
    result = comparison.score_comparison(
        "2026-11-14",
        "BTC",
        entry_px=100.0,
        highs=[101.0, 103.0],
        lows=[99.0, 100.0],
        closes=[101.0, 103.0],
        atr=1.0,
        db_path=db,
    )
    assert result["l1_direction"] == 1
    assert result["realized_ret"] == pytest.approx(0.014)
    row = comparison.list_comparisons(db)[0]
    assert row["realized_ret"] == pytest.approx(0.014)
    assert row["scored_at"] and row["l1_direction"] == 1

    with pytest.raises(comparison.ComparisonError):
        comparison.score_comparison(
            "2026-11-13",
            "BTC",
            entry_px=100.0,
            highs=[101.0],
            lows=[99.0],
            atr=1.0,
            db_path=db,
        )


def test_score_flat_direction_scores_zero(db):
    comparison.record_comparison("2026-11-14", "BTC", l1_direction=0, l1_strength=0.0, db_path=db)
    out = comparison.score_comparison(
        "2026-11-14",
        "BTC",
        entry_px=100.0,
        highs=[101.0],
        lows=[99.0],
        atr=1.0,
        db_path=db,
    )
    assert out["realized_ret"] == 0.0
    assert out["flags"] == ["flat_position"]
