# -*- coding: utf-8 -*-
"""
test_core.py — 核心路径单元测试
===============================
SPEC-41-文件索引系统 v0.6 §9（测试计划：分块/分词/检索/权限核心路径）
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.chunker import Chunker, WINDOW_LINES, WINDOW_OVERLAP
from core.tokenizer import tokenize, JiebaTokenizer


# ---------- chunker 三级兜底（SPEC §2.2 / §9） ----------

class TestChunker:
    def setup_method(self):
        self.chunker = Chunker()

    def test_heading_boundary(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# 标题一\n内容A\n\n## 标题二\n内容B\n", encoding="utf-8")
        chunks = self.chunker.chunk(f)
        assert len(chunks) == 2
        assert chunks[0].boundary_kind == "heading"
        assert chunks[0].heading == "标题一"
        assert chunks[1].heading == "标题二"

    def test_paragraph_boundary(self, tmp_path):
        f = tmp_path / "plain.txt"
        f.write_text("第一段内容\n\n第二段内容\n\n第三段内容\n", encoding="utf-8")
        chunks = self.chunker.chunk(f)
        assert len(chunks) == 3
        assert all(c.boundary_kind == "paragraph" for c in chunks)

    def test_window_boundary_and_overlap(self, tmp_path):
        f = tmp_path / "raw.txt"
        # 无空行无标题：触发窗口兜底
        f.write_text("\n".join(f"line{i}" for i in range(WINDOW_LINES * 2)), encoding="utf-8")
        chunks = self.chunker.chunk(f)
        assert all(c.boundary_kind == "window" for c in chunks)
        assert len(chunks) >= 2
        # 窗口重叠 16 行：第二块前 16 行与第一块末尾相同
        first_tail = chunks[0].content.splitlines()[-WINDOW_OVERLAP:]
        second_head = chunks[1].content.splitlines()[:WINDOW_OVERLAP]
        assert first_tail == second_head

    def test_code_chunk_by_def(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text(
            "import os\n\ndef foo():\n    return 1\n\ndef bar():\n    return 2\n",
            encoding="utf-8",
        )
        chunks = self.chunker.chunk(f)
        assert all(c.boundary_kind == "code" for c in chunks)
        assert len(chunks) >= 2


# ---------- tokenizer 分词（SPEC §2.2 / §9） ----------

class TestTokenizer:
    def test_chinese(self):
        tokens = tokenize("文件索引系统")
        assert "文件" in tokens or "索引" in tokens

    def test_camel_case(self):
        tokens = tokenize("SearchAPIWrapper")
        assert "search" in tokens and "api" in tokens and "wrapper" in tokens

    def test_fullwidth(self):
        # 全角字母转半角后分词
        tokens = tokenize("ＡＢＣ ｔｅｓｔ")
        assert "test" in tokens

    def test_stopwords(self):
        tokens = tokenize("the 的 and 了")
        assert tokens == []

    def test_mixed(self):
        tokens = tokenize("PostgreSQL存储层迁移")
        assert len(tokens) > 0


# ---------- searcher 打分与过滤（SPEC §9，依赖数据库） ----------

DB_AVAILABLE = True
try:
    from core.db import Database
    Database.instance().initialize()
except Exception:
    DB_AVAILABLE = False


@pytest.mark.skipif(not DB_AVAILABLE, reason="PostgreSQL fis 库不可用")
class TestSearcher:
    def test_search_l1(self):
        from core.searcher import Searcher
        s = Searcher()
        result = s.search("SPEC", limit=10)
        assert result.took_ms < 100  # P0 验收：<100ms
        assert isinstance(result.hits, list)

    def test_search_limit_cap(self):
        from core.searcher import Searcher
        s = Searcher()
        result = s.search("a", limit=999)
        assert len(result.hits) <= 100  # 上限 100

    def test_search_type_filter(self):
        from core.searcher import Searcher
        s = Searcher()
        result = s.search("md", filters={"type": ["doc"]}, limit=10)
        assert all(h.type == "doc" for h in result.hits)


@pytest.mark.skipif(not DB_AVAILABLE, reason="PostgreSQL fis 库不可用")
class TestSearchAPIPermission:
    def test_fail_open_no_credential(self):
        from api.search_api import SearchAPI
        import os
        api = SearchAPI(root=str(Path(__file__).resolve().parent.parent))
        # 显式传入错误凭证 → FAIL-OPEN 空结果
        result = api.search("SPEC", agent_token="wrong-token")
        assert result["hits"] == []

    def test_agent_token_full_visibility(self, monkeypatch):
        from api.search_api import SearchAPI
        monkeypatch.setenv("FIS_AGENT_TOKEN", "test-token-123")
        api = SearchAPI(root=str(Path(__file__).resolve().parent.parent))
        result = api.search("SPEC", agent_token="test-token-123", limit=5)
        assert isinstance(result["hits"], list)

    def test_private_filtered_for_user(self, monkeypatch):
        from api.search_api import SearchAPI
        api = SearchAPI(root=str(Path(__file__).resolve().parent.parent))
        hits = [
            type("H", (), {"source": {"path": "private/secret.md", "line": 1}})(),
            type("H", (), {"source": {"path": "docs/readme.md", "line": 1}})(),
        ]
        filtered = api._apply_visibility(hits, user_id="alice", agent_authorized=False)
        assert all("private/" not in h.source["path"] for h in filtered)
