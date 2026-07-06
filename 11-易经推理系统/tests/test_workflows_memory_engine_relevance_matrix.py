def test_memory_engine_build_relevance_matrix_basic():
    from workflows.memory.memory_engine.engine import MemoryEngine

    def structured_retriever(context, topk):
        return [
            {"id": "TC_1", "kind": "case", "score": 0.9, "refs": {"case_id": "TC_1"}},
            {"id": "D_1", "kind": "distill", "score": 0.4, "refs": {"distill_id": "D_1"}},
        ][:topk]

    def semantic_retriever(context, topk):
        return [
            {"id": "D_1", "kind": "distill", "score": 0.8, "refs": {"distill_id": "D_1"}},
            {"id": "TC_2", "kind": "case", "score": 0.6, "refs": {"case_id": "TC_2"}},
        ][:topk]

    memory = MemoryEngine(structured_retriever=structured_retriever, semantic_retriever=semantic_retriever)
    out = memory.build_relevance_matrix({"query_text": "风险 空仓"}, topk=3)

    assert out["query"]["query_text"] == "风险 空仓"
    assert len(out["items"]) == 3
    first = out["items"][0]
    assert "relevance" in first
    assert "components" in first
    assert "structured" in first["components"]
    assert "semantic" in first["components"]
    assert "performance_weight" in first["components"]


def test_memory_engine_build_relevance_matrix_with_performance_weight():
    from workflows.memory.memory_engine.engine import MemoryEngine

    def structured_retriever(context, topk):
        return [{"id": "TC_1", "kind": "case", "score": 0.5, "refs": {"case_id": "TC_1"}}]

    memory = MemoryEngine(structured_retriever=structured_retriever, semantic_retriever=lambda c, t: [])
    out = memory.build_relevance_matrix(
        {"query_text": "test", "performance_weight_by_id": {"TC_1": 0.9}},
        topk=1,
    )
    item = out["items"][0]
    assert item["components"]["performance_weight"] == 0.9
    assert item["relevance"] > 0.5


def test_memory_engine_build_relevance_matrix_with_bandit_weight(tmp_path):
    from workflows.memory.memory_engine.engine import MemoryEngine

    def structured_retriever(context, topk):
        return [{"id": "TC_1", "kind": "case", "score": 0.5, "refs": {"case_id": "TC_1"}}]

    state_path = tmp_path / "bandit_state.json"
    state_path.write_text('{"TC_1":{"n":2,"reward_mean":0.6,"reward_sum":1.2}}', encoding="utf-8")

    memory = MemoryEngine(structured_retriever=structured_retriever, semantic_retriever=lambda c, t: [], bandit_state_path=state_path)
    out = memory.build_relevance_matrix({"query_text": "test", "use_bandit": True}, topk=1)
    item = out["items"][0]
    assert item["components"]["bandit_weight"] > 0.0
