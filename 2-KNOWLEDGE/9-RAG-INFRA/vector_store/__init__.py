# -*- coding: utf-8 -*-
"""向量检索层（阶段1）：Markdown 分块、向量化、构建索引、语义检索。"""

from . import config
from .chunker import chunk_markdown
from .embedder import Embedder
from .build_index import build_index
from .search import search

__all__ = ["config", "chunk_markdown", "Embedder", "build_index", "search"]
