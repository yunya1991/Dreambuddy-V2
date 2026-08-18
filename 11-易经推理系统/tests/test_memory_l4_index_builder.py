from pathlib import Path


def test_build_index_from_case_and_distill(tmp_path: Path):
    from scripts.memory_l4.index_builder import build_index_data

    cases = [
        {
            "case_id": "TC_1",
            "inst_id": "BTC-USDT-SWAP",
            "tags": ["t1"],
            "environment_snapshot": {"regime": "RANGE_BOUND"},
            "execution": {"episode_refs": [{"trace_id": "trace_x", "path": ".workbuddy/episodes/episode_20260420_125149.json"}]},
            "review": {"summary": "s", "theory_practice_consistency": "consistent", "lessons": ["L1", "L2", "L3", "L4"]}
        }
    ]
    distills = [
        {
            "distill_id": "D_1",
            "kind": "risk_signal",
            "claim": "claim",
            "actionable_rules": ["R1", "R2", "R3", "R4"],
            "supporting_case_ids": ["TC_1"],
            "quadrant": {"x": 0.0, "y": 0.0, "evidence": {"weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2}, "y_perf": 0, "y_consistency": 0, "y_human": 0}}
        }
    ]

    idx = build_index_data(snapshot_ts="2026-01-01T00:00:00+08:00", cases=cases, distills=distills, episodes_by_path={})

    assert idx["metadata"]["weights"] == {"struct": 0.4, "num": 0.4, "strategy": 0.2}
    assert "TC_1" in idx["case_features"]
    assert idx["case_features"]["TC_1"]["regime"] == "RANGE_BOUND"
    assert "D_1" in idx["distill_features"]
    assert idx["distill_features"]["D_1"]["claim"] == "claim"
