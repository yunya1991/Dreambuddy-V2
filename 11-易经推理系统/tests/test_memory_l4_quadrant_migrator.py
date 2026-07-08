def test_compute_case_x_from_episode_pct():
    from scripts.memory_l4.quadrant_migrator import compute_case_quadrant_update

    case = {"case_id": "TC_1", "quadrant": {"x": 0.0, "y": 0.0, "evidence": {"y_human": 0.0}}}
    episode = {"outcome": {"unrealized_pnl_pct": 2.5}}

    out = compute_case_quadrant_update(case, episode)
    assert round(out["x"], 2) == 0.5
    assert 0.0 <= out["y"] <= 1.0
    assert out["evidence"]["y_perf"] <= 0.4


def test_compute_distill_y_and_append_migration():
    from scripts.memory_l4.quadrant_migrator import update_distill_with_migration

    distill = {
        "distill_id": "D_1",
        "supporting_case_ids": ["TC_1", "TC_2"],
        "quadrant": {"x": 0.0, "y": 0.1, "evidence": {"y_human": 0.2}},
        "migration_history": [],
    }
    episodes_by_case_id = {
        "TC_1": {"outcome": {"unrealized_pnl_pct": 2.0}},
        "TC_2": {"outcome": {"unrealized_pnl_pct": -1.0}},
    }

    out = update_distill_with_migration(distill, episodes_by_case_id, snapshot_ts="2026-05-10T00:00:00+08:00")
    q = out["quadrant"]
    assert 0.0 <= q["y"] <= 1.0
    assert q["evidence"]["y_perf"] <= 0.4
    assert len(out["migration_history"]) == 1
    assert out["migration_history"][0]["reason"] == "performance_update"
