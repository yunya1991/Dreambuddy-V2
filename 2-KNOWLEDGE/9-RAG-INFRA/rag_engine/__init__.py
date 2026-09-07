# -*- coding: utf-8 -*-
"""RAG 融合引擎（阶段3）：关键词检索 + 混合检索 + 重排序 + 生成。

三路召回（向量 0.4 + 图谱 0.3 + 关键词 0.3）合并去重后经多信号重排序，
再组装为结构化 prompt 供上层 LLM 调用。所有环节遵循 FAIL-OPEN 原则。
"""

from .keyword_search import build_keyword_index, keyword_search
from .hybrid_retriever import hybrid_search, search_with_feedback
from .reranker import rerank
from .generator import generate

__all__ = [
    "build_keyword_index",
    "keyword_search",
    "hybrid_search",
    "search_with_feedback",
    "rerank",
    "generate",
]
