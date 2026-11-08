"""Whoosh 不可用时的纯 Python BM25 回退测试。"""

from __future__ import annotations

import importlib

import pytest

ks = importlib.import_module("rag_engine.keyword_search")


@pytest.fixture
def kb_dir(tmp_path):
    (tmp_path / "finance").mkdir()
    (tmp_path / "finance" / "kalman.md").write_text(
        "# Kalman 滤波\n\nKalman 滤波用于状态估计，适合量化交易中的噪声平滑。\n",
        encoding="utf-8",
    )
    (tmp_path / "finance" / "risk.md").write_text(
        "# 风控\n\n止损与仓位管理是交易系统的核心风控规则。\n",
        encoding="utf-8",
    )
    (tmp_path / "other.md").write_text("# 其他\n\n这是一篇与查询无关的文档。\n", encoding="utf-8")
    return tmp_path


def test_bm25_fallback_builds_and_ranks(monkeypatch, kb_dir, tmp_path):
    monkeypatch.setattr(ks, "_WHOOSH_AVAILABLE", False)
    index_dir = tmp_path / "kwindex"
    stats = ks.build_keyword_index(kb_dir, index_path=index_dir)
    assert stats["backend"] == "bm25_fallback"
    assert stats["total_docs"] >= 3
    assert (index_dir / ks._BM25_FILE).exists()

    hits = ks.keyword_search("Kalman", top_k=3, index_path=index_dir)
    assert hits
    assert "kalman" in hits[0]["source_file"].lower()
    assert hits[0]["score"] > 0


def test_bm25_empty_query(monkeypatch, kb_dir, tmp_path):
    monkeypatch.setattr(ks, "_WHOOSH_AVAILABLE", False)
    index_dir = tmp_path / "kwindex2"
    ks.build_keyword_index(kb_dir, index_path=index_dir)
    assert ks.keyword_search("", index_path=index_dir) == []


def test_bm25_missing_index(monkeypatch, tmp_path):
    monkeypatch.setattr(ks, "_WHOOSH_AVAILABLE", False)
    assert ks.keyword_search("Kalman", index_path=tmp_path / "missing") == []
