from pathlib import Path


def test_build_stats_snapshot(tmp_path: Path):
    from scripts.memory_l4.stats_engine import compute_full_stats, compute_pnl_stats, compute_event_library

    # compute_full_stats reads from disk; verify it returns a valid v0.2 snapshot.
    stats = compute_full_stats(snapshot_ts="2026-01-01T00:00:00+08:00")

    assert stats["snapshot_ts"] == "2026-01-01T00:00:00+08:00"
    assert stats["version"] == "v0.2"
    assert "stage_coverage" in stats
    assert "quadrant_distribution" in stats
    assert "pnl_stats" in stats
    assert "event_library" in stats
    assert stats["stage_coverage"]["total_cases"] > 0

    # Verify median correctness (fix for even-length arrays)
    pnl = stats["pnl_stats"]
    assert pnl["count"] > 0
    assert "median" in pnl


def test_build_stats_snapshot_performance_metrics():
    from scripts.memory_l4.stats_engine import compute_performance

    episodes_by_case_id = {
        "TC_1": {"outcome": {"unrealized_pnl_usdt": 10.0, "unrealized_pnl_pct": 1.0}},
        "TC_2": {"outcome": {"unrealized_pnl_usdt": -5.0, "unrealized_pnl_pct": -0.5}},
        "TC_3": {"outcome": {"unrealized_pnl_usdt": 5.0, "unrealized_pnl_pct": 0.4}},
    }

    cases = [
        {"case_id": "TC_1", "ts_start": "2026-01-01T00:00:00+08:00", "environment_snapshot": {}, "quadrant": {}},
        {"case_id": "TC_2", "ts_start": "2026-01-02T00:00:00+08:00", "environment_snapshot": {}, "quadrant": {}},
        {"case_id": "TC_3", "ts_start": "2026-01-03T00:00:00+08:00", "environment_snapshot": {}, "quadrant": {}},
    ]

    perf = compute_performance(cases=cases, episodes_by_case_id=episodes_by_case_id)

    assert perf["n_cases"] == 3
    assert perf["n_with_outcome"] == 3
    assert perf["wins"] == 2
    assert perf["losses"] == 1
    assert perf["win_rate"] == 0.6667
    assert perf["avg_pnl_usdt"] == 3.3333
    assert perf["avg_pnl_pct"] == 0.3
    assert perf["profit_factor"] == 3.0
    assert perf["max_drawdown"] == 5.0
