def test_query_returns_topk_with_references():
    from scripts.memory_l4.query_similar import query_similar_cases

    index_data = {
        "metadata": {"weights": {"struct": 0.4, "num": 0.4, "strategy": 0.2}},
        "case_features": {
            "TC_A": {
                "regime": "RANGE_BOUND",
                "decision": "SHORT",
                "reason_codes": ["LOW_SCORE", "NEGATIVE_EDGE"],
                "tags": ["t1"],
                "scores": {"trend_strength": 5},
                "total_score": 35,
                "edge": -90,
                "matched_strategy": "sunzi_003",
                "category": "兵力部署",
                "directive_bias": "WAIT",
                "references": {"case_lessons": ["L1", "L2", "L3", "L4"]}
            },
            "TC_B": {
                "regime": "RANGE_BOUND",
                "decision": "SHORT",
                "reason_codes": ["LOW_SCORE"],
                "tags": ["t1"],
                "scores": {"trend_strength": 6},
                "total_score": 36,
                "edge": -80,
                "matched_strategy": "sunzi_003",
                "category": "兵力部署",
                "directive_bias": "WAIT",
                "references": {"case_lessons": ["B1"]}
            }
        },
        "distill_features": {
            "D_1": {"kind": "risk_signal", "claim": "c", "actionable_rules": ["R1", "R2"], "supporting_case_ids": ["TC_B"]}
        }
    }

    res = query_similar_cases(index_data, case_id="TC_A", topk=1)

    assert res["results"][0]["case_id"] == "TC_B"
    assert len(res["results"][0]["references"]["case_lessons"]) <= 3
    assert "distill_refs" in res["results"][0]["references"]

