def test_memory_engine_default_structured_retriever_by_case_id():
    from workflows.memory.memory_engine.engine import MemoryEngine

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
                "references": {"case_lessons": ["L1"]}
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

    memory = MemoryEngine(index_data=index_data)
    out = memory.retrieve_for_decision({"case_id": "TC_A"}, topk=1)

    assert out["structured_topk"][0]["id"] == "TC_B"
    assert out["structured_topk"][0]["refs"]["case_id"] == "TC_B"
    assert out["merged"][0]["id"] == "TC_B"

