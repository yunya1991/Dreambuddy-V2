def test_memory_engine_retrieve_for_decision_structured_only():
    from workflows.memory.memory_engine.engine import MemoryEngine

    def structured_retriever(context, topk):
        assert context["regime"] == "RANGE_BOUND"
        assert topk == 2
        return [
            {"id": "TC_1", "kind": "case", "score": 0.9, "refs": {"case_id": "TC_1"}},
            {"id": "D_1", "kind": "distill", "score": 0.8, "refs": {"distill_id": "D_1"}}
        ]

    memory = MemoryEngine(structured_retriever=structured_retriever)
    out = memory.retrieve_for_decision({"regime": "RANGE_BOUND"}, topk=2)

    assert out["structured_topk"][0]["id"] == "TC_1"
    assert out["semantic_topk"] == []
    assert out["merged"][0]["id"] == "TC_1"
    assert out["merged"][0]["refs"]["case_id"] == "TC_1"


def test_memory_engine_analyze_failure_memory(tmp_path):
    from workflows.memory.memory_engine.engine import MemoryEngine

    cases = [
        {
            "case_id": "TC_1",
            "inst_id": "BTC-USDT-SWAP",
            "environment_snapshot": {"regime": "RANGE_BOUND"},
            "execution": {"episode_refs": [{"path": "episodes/e1.json"}]},
        }
    ]
    episodes_by_case_id = {
        "TC_1": {"outcome": {"realized_pnl_pct": -1.1, "exit_reason": "stop_loss"}}
    }
    memory = MemoryEngine(cases=cases)
    out = memory.analyze_failure_memory(
        snapshot_ts="2026-05-10T12:00:00+08:00",
        episodes_by_case_id=episodes_by_case_id,
        output_dir=tmp_path,
    )
    assert out["summary"]["failed_cases"] == 1
    assert out["summary"]["risk_signals_count"] == 1
