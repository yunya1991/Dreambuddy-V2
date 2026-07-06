import json
from pathlib import Path


def test_update_bandit_scores_updates_mean_and_count():
    from workflows.memory.memory_engine.optimizer import update_bandit_scores

    state = {}
    events = [
        {"item_id": "TC_1", "episode": {"outcome": {"unrealized_pnl_pct": 2.0}}, "ts": "2026-05-10T00:00:00+08:00"},
        {"item_id": "TC_1", "episode": {"outcome": {"unrealized_pnl_pct": -1.0}}, "ts": "2026-05-10T00:01:00+08:00"},
    ]
    new_state, updates = update_bandit_scores(events, state)
    item = new_state["TC_1"]
    assert item["n"] == 2
    assert 0.0 <= item["reward_mean"] <= 1.0
    assert len(updates) == 2


def test_score_with_ucb_explores_lower_count_more():
    from workflows.memory.memory_engine.optimizer import score_with_ucb

    state = {
        "A": {"n": 1, "reward_mean": 0.5},
        "B": {"n": 20, "reward_mean": 0.5},
    }
    a = score_with_ucb("A", state, total_steps=21)
    b = score_with_ucb("B", state, total_steps=21)
    assert a > b


def test_unrealized_discount_applies():
    from workflows.memory.memory_engine.optimizer import update_bandit_scores

    state = {}
    events = [{"item_id": "TC_1", "episode": {"outcome": {"unrealized_pnl_pct": 5.0}}, "ts": "2026-05-10T00:00:00+08:00"}]
    new_state, _ = update_bandit_scores(events, state, unrealized_discount=0.5)
    assert new_state["TC_1"]["reward_mean"] <= 0.5


def test_write_bandit_audit_artifact(tmp_path: Path):
    from workflows.memory.memory_engine.optimizer import write_bandit_audit_artifact

    updates = [{"item_id": "TC_1", "reward": 0.4, "old_n": 0, "new_n": 1}]
    path = write_bandit_audit_artifact(
        updates=updates,
        context={"trace_id": "TRACE_B", "reason": "episode_reward"},
        audit_dir=tmp_path / "audit",
    )
    p = Path(path)
    assert p.exists()
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["trace_id"] == "TRACE_B"
    assert payload["updates"][0]["item_id"] == "TC_1"


def test_write_bandit_audit_artifact_includes_reason_counts(tmp_path: Path):
    from workflows.memory.memory_engine.optimizer import write_bandit_audit_artifact

    updates = [
        {"item_id": "TC_1", "reward": 0.4, "old_n": 0, "new_n": 1, "reason": "episode_close_realized"},
        {"item_id": "TC_2", "reward": 0.3, "old_n": 2, "new_n": 3, "reason": "episode_ingest_estimated"},
        {"item_id": "TC_3", "reward": 0.2, "old_n": 1, "new_n": 2, "reason": "episode_close_realized"},
    ]
    path = write_bandit_audit_artifact(
        updates=updates,
        context={"trace_id": "TRACE_C", "reason": "episode_close_realized"},
        audit_dir=tmp_path / "audit",
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["summary"]["reason_counts"]["episode_close_realized"] == 2
    assert payload["summary"]["reason_counts"]["episode_ingest_estimated"] == 1


def test_memory_engine_update_bandit_from_episodes_persists_state_and_audit(tmp_path: Path):
    from workflows.memory.memory_engine.engine import MemoryEngine

    state_path = tmp_path / "bandit" / "latest.json"
    audit_dir = tmp_path / "audit"
    memory = MemoryEngine(bandit_state_path=state_path, audit_dir=audit_dir)
    out = memory.update_bandit_from_episodes(
        events=[
            {
                "item_id": "TC_1",
                "episode": {"outcome": {"unrealized_pnl_pct": 1.5}},
                "ts": "2026-05-10T00:00:00+08:00",
            }
        ],
        context={"trace_id": "TRACE_EP", "reason": "episode_reward"},
    )

    assert out["updates_count"] == 1
    assert out["state_path"] == str(state_path)
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["TC_1"]["n"] == 1
    assert out["audit_path"]
    assert Path(out["audit_path"]).exists()


def test_memory_engine_update_bandit_from_episodes_propagates_reason_to_updates(tmp_path: Path):
    from workflows.memory.memory_engine.engine import MemoryEngine

    state_path = tmp_path / "bandit" / "latest.json"
    audit_dir = tmp_path / "audit"
    memory = MemoryEngine(bandit_state_path=state_path, audit_dir=audit_dir)
    out = memory.update_bandit_from_episodes(
        events=[
            {
                "item_id": "TC_1",
                "episode": {"outcome": {"unrealized_pnl_pct": 1.5}},
                "ts": "2026-05-10T00:00:00+08:00",
            }
        ],
        context={"trace_id": "TRACE_EP2", "reason": "episode_close_realized"},
    )
    payload = json.loads(Path(out["audit_path"]).read_text(encoding="utf-8"))
    assert payload["updates"][0]["reason"] == "episode_close_realized"


def test_memory_engine_update_bandit_from_episodes_writes_daily_rollup(tmp_path: Path):
    from workflows.memory.memory_engine.engine import MemoryEngine

    state_path = tmp_path / "bandit" / "latest.json"
    audit_dir = tmp_path / "audit"
    memory = MemoryEngine(bandit_state_path=state_path, audit_dir=audit_dir)

    memory.update_bandit_from_episodes(
        events=[{"item_id": "TC_1", "episode": {"outcome": {"unrealized_pnl_pct": 1.2}}, "ts": "2026-05-10T00:00:00+08:00"}],
        context={"trace_id": "R1", "reason": "episode_close_realized"},
    )
    memory.update_bandit_from_episodes(
        events=[{"item_id": "TC_2", "episode": {"outcome": {"unrealized_pnl_pct": 0.8}}, "ts": "2026-05-10T00:01:00+08:00"}],
        context={"trace_id": "R2", "reason": "episode_ingest_estimated"},
    )

    day_dirs = [p for p in (audit_dir / "bandit").iterdir() if p.is_dir()]
    assert day_dirs, "expected at least one day directory under audit/bandit"
    summary_path = day_dirs[0] / "summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["total_updates"] == 2
    assert summary["reason_counts"]["episode_close_realized"] == 1
    assert summary["reason_counts"]["episode_ingest_estimated"] == 1
    assert summary["recommended_alert_threshold_pct"] == 40


def test_memory_engine_daily_rollup_recommended_threshold_adaptive_quantile(tmp_path: Path):
    from workflows.memory.memory_engine.engine import MemoryEngine

    state_path = tmp_path / "bandit" / "latest.json"
    audit_dir = tmp_path / "audit"
    bandit_root = audit_dir / "bandit"
    # Preload 6 historical day summaries to build a 7-day window with today's update.
    historical = [
        ("2000-01-01", 35),
        ("2000-01-02", 40),
        ("2000-01-03", 45),
        ("2000-01-04", 50),
        ("2000-01-05", 55),
        ("2000-01-06", 60),
    ]
    for day, ratio in historical:
        d = bandit_root / day
        d.mkdir(parents=True, exist_ok=True)
        realized = int(ratio)
        estimated = max(0, 100 - realized)
        (d / "summary.json").write_text(
            json.dumps(
                {
                    "total_updates": 1,
                    "reason_counts": {
                        "episode_close_realized": realized,
                        "episode_ingest_estimated": estimated,
                    },
                    "recommended_alert_threshold_pct": 40,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    memory = MemoryEngine(bandit_state_path=state_path, audit_dir=audit_dir)
    memory.update_bandit_from_episodes(
        events=[{"item_id": "TC_1", "episode": {"outcome": {"unrealized_pnl_pct": 1.2}}, "ts": "2026-05-10T00:00:00+08:00"}],
        context={"trace_id": "R3", "reason": "episode_close_realized"},
    )

    day_dirs = sorted([p for p in bandit_root.iterdir() if p.is_dir()])
    latest_summary = json.loads((day_dirs[-1] / "summary.json").read_text(encoding="utf-8"))
    assert latest_summary["recommended_alert_threshold_pct"] >= 42
    assert latest_summary["recommended_alert_threshold_pct"] <= 43
    meta = latest_summary["threshold_meta"]
    assert meta["window_days"] == 7
    assert meta["sample_size"] == 7
    assert meta["percentile"] == 25
