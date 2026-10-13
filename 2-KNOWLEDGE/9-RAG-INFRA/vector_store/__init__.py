# -*- coding: utf-8 -*-
"""向量检索层（阶段1）：Markdown 分块、向量化、构建索引、语义检索。"""

from . import config
from .chunker import chunk_markdown
from .embedder import Embedder

# chromadb 相关功能为可选增强：chromadb 不可用时，chunker/embedder 仍可独立使用，
# keyword_search 等不依赖向量检索的模块不受阻塞（FAIL-OPEN）。
try:
    from .build_index import build_index
    from .search import search
    _VECTOR_AVAILABLE = True
except ImportError:
    build_index = None  # type: ignore[assignment]
    search = None  # type: ignore[assignment]
    _VECTOR_AVAILABLE = False

__all__ = ["config", "chunk_markdown", "Embedder", "build_index", "search"]
