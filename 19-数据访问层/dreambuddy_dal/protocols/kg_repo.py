"""
dreambuddy_dal.protocols.kg_repo — KnowledgeGraphRepository Protocol（KG 域）
对齐 SCHEMA_DESIGN.md §8 kg_entities / kg_entity_aliases / kg_triples + FTS5 全文索引
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Tuple


class KnowledgeGraphRepository(ABC):
    """
    知识图谱仓储：CBR 记忆 / 交易策略知识线 / DreamOS-KG。
    含 kg_entities（实体）、kg_entity_aliases（别名）、kg_triples（主谓宾三元组）、
    kg_entities_fts（FTS5 全文索引虚拟表）
    """

    @abstractmethod
    def upsert_entity(
        self,
        entity_id: str,
        entity_type: str,
        canonical_name: str,
        *,
        description: Optional[str] = None,
        attributes_json: Optional[str] = None,
    ) -> bool:
        """实体 upsert（主键 entity_id）"""
        ...

    @abstractmethod
    def add_alias(
        self, entity_id: str, alias: str, *, confidence: float = 1.0,
    ) -> bool:
        """给实体加别名（同一实体可多个别名；FTS5 建索引时实体名+别名合并）"""
        ...

    @abstractmethod
    def add_triple(
        self,
        subject_id: str,
        predicate: str,
        object_id: str,
        *,
        confidence: float = 1.0,
        source: Optional[str] = None,
        valid_from: Optional[datetime] = None,
    ) -> bool:
        """增加一条三元组：subject -[predicate]-> object"""
        ...

    @abstractmethod
    def fts_search_entities(
        self, query: str, *, limit: int = 20,
    ) -> List[Tuple[str, str, str, float]]:
        """
        FTS5 全文搜索实体（名称 / 别名 / 描述）。
        返回：[(entity_id, entity_type, canonical_name, fts_rank_bm25), ...]
        """
        ...

    @abstractmethod
    def query_subgraph_by_entity(
        self,
        entity_id: str,
        *,
        hops: int = 2,
        direction: str = "both",  # "out" / "in" / "both"
        min_confidence: float = 0.5,
    ) -> Tuple[List[Tuple[str, str, str, float]], List[Tuple[str, str, str]]]:
        """
        取实体 N 跳邻居子图（用于易经推理知识线扩展）。
        返回：(triples_list, entities_list)
          - triples_list: [(subject, predicate, object, confidence)]
          - entities_list: [(entity_id, entity_type, canonical_name)]
        """
        ...
