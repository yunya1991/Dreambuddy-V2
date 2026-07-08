import json
from pathlib import Path

from workflows.memory.memory_engine.engine import MemoryEngine


def test_memory_engine_retrieve_for_decision_merges_structured_and_semantic():
    def structured_retriever(context, topk):
        assert context["query_text"] == "空仓 风险"
        assert topk == 3
        return [
            {"id": "TC_1", "kind": "case", "score": 0.9, "refs": {"case_id": "TC_1"}},
            {"id": "D_1", "kind": "distill", "score": 0.2, "refs": {"distill_id": "D_1"}},
        ]

    def semantic_retriever(context, topk):
        assert topk == 3
        return [
            {"id": "D_1", "kind": "distill", "score": 0.8, "refs": {"distill_id": "D_1"}},
            {"id": "TC_2", "kind": "case", "score": 0.6, "refs": {"case_id": "TC_2"}},
        ]

    memory = MemoryEngine(
        structured_retriever=structured_retriever,
        semantic_retriever=semantic_retriever,
    )

    out = memory.retrieve_for_decision({"query_text": "空仓 风险"}, topk=3)

    assert out["structured_topk"][0]["id"] == "TC_1"
    assert out["semantic_topk"][0]["id"] == "D_1"
    # merged_score = 0.7 * structured + 0.3 * semantic
    # semantic 缺失时回退 structured
    # TC_1 = 0.9, D_1 = 0.38, TC_2 = 0.18
    assert [x["id"] for x in out["merged"]] == ["TC_1", "D_1", "TC_2"]
    assert out["merged"][0]["merged_score"] == 0.9
    assert out["merged"][1]["merged_score"] == 0.38
    assert out["audit"]["structured_source"]["kind"] == "custom_retriever"
    assert out["audit"]["semantic_source"]["kind"] == "custom_retriever"
    assert out["audit"]["merge_rule"]["version"] == "v0.1"


def test_memory_engine_default_semantic_retriever_uses_cases_distills():
    memory = MemoryEngine(
        cases=[
            {
                "case_id": "TC_X",
                "intent": {"question": "风险高是否空仓"},
                "review": {"summary": "风险上升，控制仓位", "lessons": ["高波动先降杠杆"]},
            }
        ],
        distills=[
            {"distill_id": "D_X", "claim": "空仓优先", "actionable_rules": ["风险高时减少暴露"]}
        ],
    )

    out = memory.retrieve_for_decision({"query_text": "风险 空仓"}, topk=2)
    assert len(out["semantic_topk"]) == 2
    assert out["semantic_topk"][0]["kind"] in {"case", "distill"}
    assert all("refs" in item for item in out["semantic_topk"])
    assert all(item["vector_source"]["kind"] == "memory_fallback" for item in out["semantic_topk"])


def test_memory_engine_default_semantic_retriever_prefers_vector_docs(tmp_path):
    vector_dir = tmp_path / "vector"
    vector_dir.mkdir(parents=True, exist_ok=True)
    docs_path = vector_dir / "docs.jsonl"
    docs_path.write_text(
        '{"id":"TC_VEC:intent.question","kind":"case","text":"风险 空仓 降杠杆","refs":{"case_id":"TC_VEC","field":"intent.question"}}\n'
        '{"id":"D_VEC:claim","kind":"distill","text":"空仓优先","refs":{"distill_id":"D_VEC","field":"claim"}}\n',
        encoding="utf-8",
    )

    memory = MemoryEngine(
        vector_dir=vector_dir,
        cases=[
            {
                "case_id": "TC_FALLBACK",
                "intent": {"question": "这条不该被命中"},
                "review": {"summary": "fallback", "lessons": []},
            }
        ],
        distills=[],
    )

    out = memory.retrieve_for_decision({"query_text": "风险 空仓"}, topk=2)
    assert len(out["semantic_topk"]) == 2
    assert out["semantic_topk"][0]["id"].startswith("TC_VEC")
    assert out["semantic_topk"][0]["vector_source"]["kind"] == "vector_index"
    assert out["semantic_topk"][0]["vector_source"]["docs_file"] == "docs.jsonl"
    assert out["audit"]["structured_source"]["kind"] == "index_engine"
    assert out["audit"]["semantic_source"]["kind"] == "vector_index"


def test_memory_engine_semantic_retriever_fallback_when_vector_docs_invalid(tmp_path):
    vector_dir = tmp_path / "vector"
    vector_dir.mkdir(parents=True, exist_ok=True)
    (vector_dir / "manifest.json").write_text('{"version":"v0.1","docs_file":"docs.jsonl"}\n', encoding="utf-8")
    (vector_dir / "docs.jsonl").write_text("{not-json-line}\n", encoding="utf-8")

    memory = MemoryEngine(
        vector_dir=vector_dir,
        cases=[
            {
                "case_id": "TC_FALLBACK",
                "intent": {"question": "风险高是否空仓"},
                "review": {"summary": "", "lessons": []},
            }
        ],
        distills=[],
    )

    out = memory.retrieve_for_decision({"query_text": "风险 空仓"}, topk=1)
    assert len(out["semantic_topk"]) == 1
    assert out["semantic_topk"][0]["id"] == "TC_FALLBACK:intent.question"


def test_memory_engine_semantic_retriever_reads_docs_file_from_manifest(tmp_path):
    vector_dir = tmp_path / "vector"
    vector_dir.mkdir(parents=True, exist_ok=True)
    (vector_dir / "manifest.json").write_text('{"version":"v0.1","docs_file":"custom_docs.jsonl"}\n', encoding="utf-8")
    (vector_dir / "custom_docs.jsonl").write_text(
        '{"id":"TC_MF:intent.question","kind":"case","text":"风险 空仓","refs":{"case_id":"TC_MF","field":"intent.question"}}\n',
        encoding="utf-8",
    )

    memory = MemoryEngine(vector_dir=vector_dir, cases=[], distills=[])
    out = memory.retrieve_for_decision({"query_text": "风险 空仓"}, topk=1)
    assert len(out["semantic_topk"]) == 1
    assert out["semantic_topk"][0]["id"] == "TC_MF:intent.question"
    assert out["semantic_topk"][0]["vector_source"]["docs_file"] == "custom_docs.jsonl"


def test_memory_engine_retrieve_writes_audit_artifact_when_enabled(tmp_path):
    audit_dir = tmp_path / "audit"
    memory = MemoryEngine(
        audit_dir=audit_dir,
        cases=[{"case_id": "TC_A", "intent": {"question": "风险 空仓"}, "review": {"summary": "", "lessons": []}}],
        distills=[],
    )

    out = memory.retrieve_for_decision(
        {"query_text": "风险 空仓", "write_audit_artifact": True, "trace_id": "TRACE_X"},
        topk=1,
    )
    artifact_path = out["audit"].get("artifact_path")
    assert artifact_path

    p = Path(artifact_path)
    assert p.exists()
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["audit_schema_version"] == "v0.1"
    assert payload["trace_id"] == "TRACE_X"
    assert payload["request"]["query_text"] == "风险 空仓"
    assert payload["result"]["audit"]["merge_rule"]["version"] == "v0.1"
    assert p.parent.name.count("-") == 2


def test_memory_engine_retrieve_no_audit_artifact_by_default(tmp_path):
    audit_dir = tmp_path / "audit"
    memory = MemoryEngine(
        audit_dir=audit_dir,
        cases=[{"case_id": "TC_A", "intent": {"question": "风险 空仓"}, "review": {"summary": "", "lessons": []}}],
        distills=[],
    )

    out = memory.retrieve_for_decision({"query_text": "风险 空仓"}, topk=1)
    assert out["audit"].get("artifact_path") is None
    assert list(audit_dir.glob("*.json")) == []


def test_memory_engine_audit_rotation_keeps_latest_n(tmp_path):
    audit_dir = tmp_path / "audit"
    memory = MemoryEngine(
        audit_dir=audit_dir,
        max_audit_files_per_day=2,
        cases=[{"case_id": "TC_A", "intent": {"question": "风险 空仓"}, "review": {"summary": "", "lessons": []}}],
        distills=[],
    )

    for i in range(3):
        out = memory.retrieve_for_decision(
            {"query_text": "风险 空仓", "write_audit_artifact": True, "trace_id": f"T{i}"},
            topk=1,
        )
        assert out["audit"]["artifact_path"]

    day_dirs = [p for p in audit_dir.iterdir() if p.is_dir()]
    assert len(day_dirs) == 1
    files = sorted(day_dirs[0].glob("*.json"))
    assert len(files) == 2
    names = [f.name for f in files]
    assert any("T1" in n for n in names)
    assert any("T2" in n for n in names)


def test_memory_engine_pinecone_retriever_used_when_enabled():
    def pinecone_retriever(context, topk):
        assert context["query_text"] == "风险 空仓"
        assert topk == 2
        return [
            {
                "id": "D_PC:claim",
                "kind": "distill",
                "score": 0.88,
                "refs": {"distill_id": "D_PC"},
                "matched_text": "空仓优先",
                "vector_source": {"kind": "pinecone", "index": "memory-dev"},
            }
        ]

    memory = MemoryEngine(
        pinecone_retriever=pinecone_retriever,
        cases=[],
        distills=[],
    )
    out = memory.retrieve_for_decision({"query_text": "风险 空仓", "use_pinecone": True}, topk=2)
    assert out["semantic_topk"][0]["id"] == "D_PC:claim"
    assert out["audit"]["semantic_source"]["kind"] == "pinecone"


def test_memory_engine_pinecone_fail_soft_fallback_local():
    def pinecone_retriever(context, topk):
        raise RuntimeError("pinecone timeout")

    memory = MemoryEngine(
        pinecone_retriever=pinecone_retriever,
        cases=[
            {
                "case_id": "TC_LOCAL",
                "intent": {"question": "风险高是否空仓"},
                "review": {"summary": "", "lessons": []},
            }
        ],
        distills=[],
    )
    out = memory.retrieve_for_decision({"query_text": "风险 空仓", "use_pinecone": True}, topk=1)
    assert out["semantic_topk"][0]["id"] == "TC_LOCAL:intent.question"
    assert out["audit"]["semantic_source"]["kind"] == "memory_fallback"
    assert "pinecone_error" in out["audit"]["semantic_source"]
