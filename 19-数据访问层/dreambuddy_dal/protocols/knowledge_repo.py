"""
dreambuddy_dal.protocols.knowledge_repo — 知识库只读 Repository Protocol

对齐 DATA_AND_COGNITIVE_READONLY_ACCESS_SPEC §5.2
只读方法：vector_search / fts_search / hybrid_search
写入（ingest/vectorize）走 knowledge-ingest 工作流，不在此 Protocol 暴露。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional


class KnowledgeRepository(ABC):
    """
    知识库只读仓储。
    读=前端/LLM 直接调用（vector/fts/hybrid search）；
    写=knowledge-ingest SKILL → build_index.py。
    """

    @abstractmethod
    def vector_search(self, query: str, top_k: int = 5) -> List[dict]:
        """向量语义检索知识库。

        Args:
            query: 查询文本
            top_k: 返回上限

        Returns:
            结果列表，每项含 content/score/source/chunk_id
        """
        ...

    @abstractmethod
    def fts_search(self, query: str, top_k: int = 5) -> List[dict]:
        """BM25 全文检索知识库。

        Args:
            query: 查询文本
            top_k: 返回上限

        Returns:
            结果列表，每项含 content/score/source/heading
        """
        ...

    @abstractmethod
    def hybrid_search(self, query: str, top_k: int = 5) -> List[dict]:
        """混合检索（向量+全文+图谱），返回重排序结果。

        Args:
            query: 查询文本
            top_k: 返回上限

        Returns:
            结果列表，含 final_score / retrieval_methods
        """
        ...
