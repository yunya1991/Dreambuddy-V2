"""RAG 测试全局隔离：避免污染生产 bridge / Chroma / 知识图谱默认路径。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_rag_side_effects(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_BRIDGE_MAP_PATH", str(tmp_path / "map.jsonl"))
    monkeypatch.setenv("TEST_BRIDGE_WEIGHT_PATH", str(tmp_path / "weight.json"))
    try:
        import evolution.ingest as ingest

        monkeypatch.setattr(ingest, "CHROMA_DB_PATH", str(tmp_path / "chroma"))
    except Exception:
        pass
    try:
        import knowledge_graph.schema as schema

        monkeypatch.setattr(schema, "DEFAULT_GRAPH_PATH", tmp_path / "graph.json")
    except Exception:
        pass
