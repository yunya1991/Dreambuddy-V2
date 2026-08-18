from workflows.memory.memory_engine.engine import MemoryEngine


def test_memory_engine_check_consistency_reports_missing_episode_and_coverage():
    cases = [
        {
            "case_id": "TC_1",
            "execution": {
                "episode_refs": [
                    {"path": ".workbuddy/episodes/ep_exists.json"},
                    {"path": ".workbuddy/episodes/ep_missing.json"},
                ]
            },
        },
        {
            "case_id": "TC_2",
            "execution": {"episode_refs": [{"path": ".workbuddy/episodes/ep_exists.json"}]},
        },
    ]
    distills = [
        {"distill_id": "D_1", "supporting_case_ids": ["TC_1", "TC_UNKNOWN"]},
    ]
    stats = {"points": [{"id": "TC_1", "kind": "case"}]}
    index_data = {
        "case_features": {"TC_1": {}, "TC_2": {}},
        "distill_features": {"D_1": {"supporting_case_ids": ["TC_1", "TC_UNKNOWN"]}},
    }
    episodes_by_path = {
        ".workbuddy/episodes/ep_exists.json": {"trace_id": "ok"},
    }

    memory = MemoryEngine(
        index_data=index_data,
        cases=cases,
        distills=distills,
        stats=stats,
        episodes_by_path=episodes_by_path,
    )
    report = memory.check_consistency()

    assert report["summary"]["case_count"] == 2
    assert report["summary"]["episode_ref_count"] == 3
    # Partial credit coverage: TC_1=0.5 (1/2 resolved) + TC_2=1.0 (1/1 resolved) → 1.5/2 = 0.75
    assert report["summary"]["episode_coverage_ratio"] == 0.75
    assert report["summary"]["issues_total"] >= 2
    assert any(i["code"] == "MISSING_EPISODE_REF" for i in report["issues"])
    assert any(i["code"] == "DISTILL_SUPPORTING_CASE_NOT_FOUND" for i in report["issues"])


def test_memory_engine_health_score_penalizes_issues_and_low_coverage():
    memory = MemoryEngine(
        index_data={"case_features": {"TC_1": {}}, "distill_features": {}},
        cases=[{"case_id": "TC_1", "execution": {"episode_refs": [{"path": "missing.json"}]}}],
        episodes_by_path={},
    )

    score = memory.get_health_score()
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0
    assert score < 80.0


def test_memory_engine_check_consistency_validates_full_chain_schema():
    # case missing required "intent"
    cases = [{"case_id": "TC_1", "execution": {"episode_refs": []}, "review": {}, "quadrant": {}}]
    # distill has invalid enum kind + missing claim
    distills = [{"distill_id": "D_1", "kind": "unknown", "supporting_case_ids": ["TC_1"], "quadrant": {}, "migration_history": []}]
    # stats missing required "points"
    stats = {"snapshot_ts": "2026-01-01T00:00:00+08:00"}
    # index missing metadata/weights
    index_data = {"case_features": {"TC_1": {}}, "distill_features": {"D_1": {}}}

    memory = MemoryEngine(index_data=index_data, cases=cases, distills=distills, stats=stats, episodes_by_path={})
    report = memory.check_consistency()

    codes = {i["code"] for i in report["issues"]}
    assert "CASE_SCHEMA_INVALID" in codes
    assert "DISTILL_SCHEMA_INVALID" in codes
    assert "STATS_SCHEMA_INVALID" in codes
    assert "INDEX_SCHEMA_INVALID" in codes
