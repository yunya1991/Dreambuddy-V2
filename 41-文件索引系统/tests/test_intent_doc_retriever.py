"""SPEC-41-L1 P4：执行器文档按需 retrieve。"""

import json
import re
import sys
from pathlib import Path

import pytest

_INDEX_ROOT = Path(__file__).resolve().parent.parent
if str(_INDEX_ROOT) not in sys.path:
    sys.path.insert(0, str(_INDEX_ROOT))

from core.intent_doc_retriever import IntentDocRetriever  # noqa: E402


def _unit(root: Path, intent_id: str, *, doc: bool = True) -> Path:
    unit = root / intent_id
    unit.mkdir(parents=True)
    (unit / "intent.yaml").write_text(
        f"id: {intent_id}\ncategory: test\nkeywords: alpha,beta\n",
        encoding="utf-8",
    )
    if doc:
        (unit / "executor.md").write_text(
            f"# {intent_id}\n\n执行器规范与边界条件\n",
            encoding="utf-8",
        )
    (unit / "examples_zh.jsonl").write_text(
        json.dumps({"message": "正例"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (unit / "negatives_zh.jsonl").write_text(
        json.dumps({"message": "反例"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return unit


def test_retrieve_loads_only_requested_intent(tmp_path, monkeypatch):
    unit = _unit(tmp_path, "data_query")
    _unit(tmp_path, "price_query")
    read_paths = []
    original_read_text = Path.read_text

    def recording_read_text(path, *args, **kwargs):
        read_paths.append(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", recording_read_text)
    result = IntentDocRetriever(tmp_path).retrieve("data_query")

    assert result["found"] is True
    assert result["degraded"] is False
    assert result["metadata"]["category"] == "test"
    assert "边界条件" in result["executor_doc"]
    assert result["examples"]["zh"] == [{"message": "正例"}]
    assert result["negatives"]["zh"] == [{"message": "反例"}]
    assert read_paths
    assert all(path.parent == unit for path in read_paths)


def test_retrieve_caches_loaded_unit(tmp_path):
    unit = _unit(tmp_path, "data_query")
    retriever = IntentDocRetriever(tmp_path)
    first = retriever.retrieve("data_query")
    (unit / "executor.md").write_text("changed", encoding="utf-8")

    second = retriever.retrieve("data_query")

    assert second["executor_doc"] == first["executor_doc"]


@pytest.mark.parametrize("intent_id", ["", "../data_query", "bad-intent", "data/query"])
def test_retrieve_rejects_invalid_intent_id(tmp_path, intent_id):
    result = IntentDocRetriever(tmp_path).retrieve(intent_id)

    assert result["found"] is False
    assert result["degraded"] is True
    assert result["errors"] == ["invalid_intent_id"]


def test_retrieve_missing_unit_degrades(tmp_path):
    result = IntentDocRetriever(tmp_path).retrieve("data_query")

    assert result["found"] is False
    assert result["degraded"] is True
    assert result["errors"] == ["intent_unit_not_found"]


def test_retrieve_missing_executor_doc_degrades(tmp_path):
    _unit(tmp_path, "data_query", doc=False)

    result = IntentDocRetriever(tmp_path).retrieve("data_query")

    assert result["found"] is False
    assert result["degraded"] is True
    assert "executor_doc_not_found" in result["errors"]
    assert result["examples"]["zh"] == [{"message": "正例"}]


def test_retrieve_malformed_jsonl_preserves_valid_rows(tmp_path):
    unit = _unit(tmp_path, "data_query")
    (unit / "examples_zh.jsonl").write_text('{"message":"保留"}\nnot-json\n', encoding="utf-8")

    result = IntentDocRetriever(tmp_path).retrieve("data_query")

    assert result["found"] is True
    assert result["degraded"] is True
    assert result["examples"]["zh"] == [{"message": "保留"}]
    assert any("examples_zh.jsonl:2" in error for error in result["errors"])


def test_retrieve_invalid_utf8_degrades(tmp_path):
    unit = _unit(tmp_path, "data_query")
    (unit / "executor.md").write_bytes(b"\xff\xfe")

    result = IntentDocRetriever(tmp_path).retrieve("data_query")

    assert result["found"] is False
    assert result["degraded"] is True
    assert "executor_doc_not_found" in result["errors"]


def test_repository_covers_registered_intents():
    registry = (
        _INDEX_ROOT.parent / "3.1-FRONTEND" / "src" / "lib" / "l1-intent-registry.ts"
    ).read_text(encoding="utf-8")
    intent_ids = re.findall(r"\bintent:\s*'([^']+)'", registry)
    retriever = IntentDocRetriever()

    assert len(intent_ids) == 21
    for intent_id in intent_ids:
        result = retriever.retrieve(intent_id)
        assert result["found"] is True, (intent_id, result["errors"])
        assert result["degraded"] is False, (intent_id, result["errors"])
