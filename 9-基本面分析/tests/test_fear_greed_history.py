"""P2 fear_greed 长历史旁路：真实 DAL 观测 → sentiment 历史统计。"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines import dimension_history as dh  # noqa: E402
from engines import fear_greed_history as fgh  # noqa: E402


class _Repo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def query_metric_by_time(self, sub_category, metric_name, start, end):
        self.calls.append((sub_category, metric_name, start, end))
        return self.rows


def _rows(n=800):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        ("alternative.me", "value", float(i % 101), start + timedelta(days=i)) for i in range(n)
    ]


def test_backfill_gives_real_1y_and_3y_ranks_and_is_idempotent(tmp_path):
    repo = _Repo(_rows())
    result = fgh.backfill_fear_greed(
        repo=repo,
        base_dir=tmp_path,
        written_at="2026-11-12T00:00:00+00:00",
    )
    assert result["fetched"] == 800
    assert result["written"] == 800
    assert result["dry_run"] is False
    assert repo.calls[0][:2] == ("crypto_fear_greed", "value")

    history = dh.get_dimension_history("sentiment", base_dir=tmp_path)
    assert history["lookback_days"] == 800
    assert history["value_scale"] == "index_0_100"
    assert history["stats"]["pct_rank_1y"] is not None
    assert history["stats"]["pct_rank_3y"] is not None
    assert history["coverage"]["first_day"] == "2024-01-01"

    again = fgh.backfill_fear_greed(
        repo=repo,
        base_dir=tmp_path,
        written_at="2026-11-12T01:00:00+00:00",
    )
    assert again["written"] == 800
    assert len(dh.load_series("sentiment", base_dir=tmp_path)) == 800


def test_daily_dedup_uses_latest_timestamp_and_real_scale():
    day = datetime(2026, 11, 11, tzinfo=timezone.utc)
    rows = [
        ("alternative.me", "value", 10.0, day),
        ("alternative.me", "value", 90.0, day + timedelta(hours=12)),
        ("alternative.me", "value", -1.0, day + timedelta(days=1)),
        ("alternative.me", "value", 20.0, "not-a-date"),
    ]
    observations = fgh.observations_from_fear_greed(rows, written_at="2026-11-12T00:00:00Z")
    assert len(observations) == 1
    obs = observations[0]
    assert obs["date"] == "2026-11-11"
    assert obs["value"] == pytest.approx(90.0)
    assert obs["direction_score"] == pytest.approx(0.8)
    assert obs["direction"] == "up"
    assert obs["observed_date_source"] == "dal_timestamp"


def test_velocity_and_acceleration_use_adjacent_daily_changes():
    start = datetime(2026, 11, 10, tzinfo=timezone.utc)
    rows = [
        ("alternative.me", "value", value, start + timedelta(days=i))
        for i, value in enumerate((50.0, 75.0, 100.0))
    ]
    observations = fgh.observations_from_fear_greed(rows, written_at="2026-11-12T00:00:00Z")
    assert [row["velocity"] for row in observations] == [0.0, 0.5, 0.5]
    assert [row["acceleration"] for row in observations] == [0.0, 0.5, 0.0]
    assert observations[-1]["data_points"] == 3


def test_dry_run_fetches_without_writing(tmp_path):
    result = fgh.backfill_fear_greed(
        repo=_Repo(_rows(20)),
        base_dir=tmp_path,
        dry_run=True,
        written_at="2026-11-12T00:00:00Z",
    )
    assert result["written"] == 0
    assert result["observations"] == 20
    assert result["dry_run"] is True
    assert not (tmp_path / "dimension_history" / "sentiment.jsonl").exists()
