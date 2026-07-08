import json
from pathlib import Path

from workflows.memory.memory_engine.engine import MemoryEngine


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_build_vector_artifacts_writes_docs_and_manifest(tmp_path: Path):
    cases = [
        {
            "case_id": "TC_1",
            "intent": {"question": "为什么这里要空仓?"},
            "review": {"summary": "回顾总结", "lessons": ["lesson_a", "lesson_b"]},
        }
    ]
    distills = [
        {"distill_id": "D_1", "claim": "claim_x", "actionable_rules": ["rule_1", "rule_2"]}
    ]
    memory = MemoryEngine(
        cases=cases,
        distills=distills,
        index_data={"metadata": {"feature_version": "v9.test"}},
    )

    vector_dir = tmp_path / "vector"
    out = memory.build_vector_artifacts(vector_dir)

    docs_path = vector_dir / "docs.jsonl"
    manifest_path = vector_dir / "manifest.json"
    assert docs_path.exists()
    assert manifest_path.exists()
    assert out["docs_count"] == 7

    lines = [ln for ln in docs_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    docs = [json.loads(ln) for ln in lines]
    assert any(d["id"] == "TC_1:intent.question" and d["kind"] == "case" for d in docs)
    assert any(d["id"] == "D_1:claim" and d["kind"] == "distill" for d in docs)

    manifest = _read_json(manifest_path)
    assert manifest["version"] == "v0.1"
    assert manifest["docs_count"] == len(docs)
    assert manifest["embedding"]["provider"] == "local-placeholder"
    assert "source_snapshot_ts" in manifest
    assert manifest["doc_fields"]["case"] == ["intent.question", "review.summary", "review.lessons"]
    assert manifest["doc_fields"]["distill"] == ["claim", "actionable_rules"]
    assert manifest["feature_version"] == "v9.test"
    assert "index_id" in manifest
