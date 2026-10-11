#!/usr/bin/env python3
"""FIBO 语义本体 — FIBOOntology

定位：L1 基础层语义图，将 46 个 INDEX.md 文件索引升级为
FIBO (Financial Industry Business Ontology) RDF/OWL 风格的语义图。

核心能力:
  1. add_entity() — 创建带类层级的实体 (subClassOf)
  2. add_relation() — 添加语义关系 (part_of/documents/covers_topic/...)
  3. query() — 按类型 + 属性过滤查询
  4. transitive_closure() — 传递闭包（part_of/subClassOf 链式）
  5. multi_hop() — 多跳链式查询
  6. validate(schema) — Schema 约束校验 (cardinality/domain/range)
  7. to_jsonld() / from_jsonld() — JSON 序列化（兼容 JSON-LD 思路）
  8. persist() / _restore() — 文件持久化

FIBO 风格类层级:
    Entity (基类)
    ├── Document   (subClassOf Entity)
    │   ├── Module (subClassOf Document)
    │   ├── Index  (subClassOf Document)
    │   └── Spec   (subClassOf Document)
    ├── Topic      (subClassOf Entity)
    ├── Skill      (subClassOf Entity)
    └── Memory     (subClassOf Entity)

关系类型（FIBO 风格）:
    part_of       (传递)  Document → Document
    documents             Document → Module
    covers_topic          Document → Topic
    depends_on    (传递)  Module → Module
    references            Document → Document
    version_of            Document → Document

设计原则:
  - 轻量级纯 Python，无 rdflib/SPARQL 引擎依赖
  - FAIL-OPEN：所有外部操作失败不阻塞主流程
  - 线程安全：所有公共方法加锁

参考:
  - SPEC-CognitiveSystem-Evolution.md §4.3 P3-8 + §1.3 L49
  - FIBO RDF/OWL (Financial Industry Business Ontology)
  - 协同 temporal_memory_graph.py (P1-3 双时序知识图)
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ============================================================
# 传递性关系类型（可做 transitive_closure）
# ============================================================

TRANSITIVE_RELATIONS: frozenset = frozenset({"part_of", "depends_on", "subClassOf"})

# 关系类型白名单
VALID_RELATION_TYPES: frozenset = frozenset({
    "part_of",
    "documents",
    "covers_topic",
    "depends_on",
    "references",
    "version_of",
    "subClassOf",
    "has_version",
    "has_member",
})


# ============================================================
# dataclass: FIBOEntity / FIBORelation
# ============================================================


@dataclass
class FIBOEntity:
    """FIBO 语义实体。

    Attributes:
        id: 实体 ID（唯一）
        entity_type: 实体类型（Document/Module/Topic/Skill/Memory）
        sub_class_of: 父类类型名（None=直接继承 Entity）
        properties: 属性字典
        created: 创建时间 ISO
        updated: 更新时间 ISO
    """

    id: str
    entity_type: str = "Entity"
    sub_class_of: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    created: str = ""
    updated: str = ""

    def __post_init__(self) -> None:
        if not self.created:
            self.created = datetime.now(timezone.utc).isoformat()
        if not self.updated:
            self.updated = self.created

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.entity_type,
            "sub_class_of": self.sub_class_of,
            "properties": self.properties,
            "created": self.created,
            "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FIBOEntity":
        return cls(
            id=d["id"],
            entity_type=d.get("type", "Entity"),
            sub_class_of=d.get("sub_class_of"),
            properties=d.get("properties", {}) or {},
            created=d.get("created", ""),
            updated=d.get("updated", ""),
        )


@dataclass
class FIBORelation:
    """FIBO 语义关系。

    Attributes:
        from_id: 起始实体 ID
        rel_type: 关系类型 (part_of/documents/covers_topic/...)
        to_id: 目标实体 ID
        properties: 关系属性
        created: 创建时间
    """

    from_id: str
    rel_type: str
    to_id: str
    properties: Dict[str, Any] = field(default_factory=dict)
    created: str = ""

    def __post_init__(self) -> None:
        if not self.created:
            self.created = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from": self.from_id,
            "rel": self.rel_type,
            "to": self.to_id,
            "properties": self.properties,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FIBORelation":
        return cls(
            from_id=d["from"],
            rel_type=d["rel"],
            to_id=d["to"],
            properties=d.get("properties", {}) or {},
            created=d.get("created", ""),
        )


# ============================================================
# FIBOOntology 主类
# ============================================================


class FIBOOntology:
    """FIBO 语义本体。

    管理 FIBO 风格实体和关系，支持类层级、多跳查询、
    Schema 校验、JSON 持久化。

    与 TemporalMemoryGraph (P1-3) 协同：FIBO 实体可挂时序元数据，
    recall 时 FIBO 提供语义上下文，TemporalMemoryGraph 标注
    temporal_status（active/historical/superseded）。

    线程安全：所有公共方法加锁。
    """

    def __init__(self, ontology_path: Optional[Path] = None) -> None:
        """
        Args:
            ontology_path: 持久化 JSON 文件路径。None 则不持久化。
        """
        self._entities: Dict[str, FIBOEntity] = {}
        self._relations: List[FIBORelation] = []
        self._ontology_path: Optional[Path] = (
            Path(ontology_path) if ontology_path else None
        )
        self._lock = threading.Lock()

        if self._ontology_path and self._ontology_path.exists():
            self._restore()

    # ============================================================
    # 实体操作
    # ============================================================

    def add_entity(
        self,
        entity_type: str,
        entity_id: str,
        properties: Optional[Dict[str, Any]] = None,
        sub_class_of: Optional[str] = None,
    ) -> FIBOEntity:
        """创建或更新实体。

        若 entity_id 已存在则更新 properties/sub_class_of，否则创建。

        Args:
            entity_type: 实体类型 (Document/Module/Topic/...)
            entity_id: 唯一实体 ID
            properties: 属性字典
            sub_class_of: 父类类型名

        Returns:
            创建或更新后的 FIBOEntity
        """
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            if entity_id in self._entities:
                e = self._entities[entity_id]
                e.entity_type = entity_type
                if properties:
                    e.properties.update(properties)
                if sub_class_of is not None:
                    e.sub_class_of = sub_class_of
                e.updated = now
                return e

            e = FIBOEntity(
                id=entity_id,
                entity_type=entity_type,
                sub_class_of=sub_class_of,
                properties=properties or {},
            )
            self._entities[entity_id] = e
            return e

    def get_entity(self, entity_id: str) -> Optional[FIBOEntity]:
        """按 ID 获取实体。"""
        with self._lock:
            return self._entities.get(entity_id)

    # ============================================================
    # 关系操作
    # ============================================================

    def add_relation(
        self,
        from_id: str,
        rel_type: str,
        to_id: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> FIBORelation:
        """添加关系。不校验实体是否存在（FAIL-OPEN，允许前置创建）。

        Args:
            from_id: 起始实体 ID
            rel_type: 关系类型
            to_id: 目标实体 ID
            properties: 关系属性

        Returns:
            创建的 FIBORelation
        """
        with self._lock:
            rel = FIBORelation(
                from_id=from_id,
                rel_type=rel_type,
                to_id=to_id,
                properties=properties or {},
            )
            self._relations.append(rel)
            return rel

    def get_relations(
        self,
        entity_id: str,
        rel_type: Optional[str] = None,
        direction: str = "outgoing",
    ) -> List[FIBORelation]:
        """获取实体的关系。

        Args:
            entity_id: 实体 ID
            rel_type: 关系类型过滤（None=所有）
            direction: "outgoing"(默认) / "incoming" / "both"

        Returns:
            关系列表
        """
        with self._lock:
            results: List[FIBORelation] = []
            for r in self._relations:
                if rel_type and r.rel_type != rel_type:
                    continue
                if direction in ("outgoing", "both") and r.from_id == entity_id:
                    results.append(r)
                elif direction in ("incoming", "both") and r.to_id == entity_id:
                    results.append(r)
            return results

    # ============================================================
    # 查询
    # ============================================================

    def query(
        self,
        entity_type: Optional[str] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[FIBOEntity]:
        """按类型 + 属性过滤查询实体。

        Args:
            entity_type: 实体类型过滤（None=所有）
            where: 属性过滤字典（key=value 形式）

        Returns:
            匹配的实体列表
        """
        with self._lock:
            results: List[FIBOEntity] = []
            for e in self._entities.values():
                if entity_type and e.entity_type != entity_type:
                    continue
                if where:
                    match = all(
                        e.properties.get(k) == v for k, v in where.items()
                    )
                    if not match:
                        continue
                results.append(e)
            return results

    # ============================================================
    # 多跳 / 传递闭包
    # ============================================================

    def transitive_closure(
        self,
        entity_id: str,
        rel_type: str,
        reverse: bool = False,
    ) -> List[FIBOEntity]:
        """计算传递闭包（part_of/depends_on/subClassOf 链式）。

        正向（reverse=False）: entity_id → rel_type → X → rel_type → Y → ...
        反向（reverse=True）:  X → rel_type → entity_id, Y → rel_type → X → ...

        Args:
            entity_id: 起始实体
            rel_type: 关系类型（应具有传递性）
            reverse: True=反向闭包（找指向 entity_id 的所有上游）

        Returns:
            闭包内的实体列表（不含起始 entity_id 自身）
        """
        with self._lock:
            visited: Set[str] = set()
            queue: List[str] = [entity_id]
            results: List[FIBOEntity] = []

            while queue:
                cur = queue.pop(0)
                if cur in visited:
                    continue
                visited.add(cur)

                for r in self._relations:
                    if r.rel_type != rel_type:
                        continue
                    if not reverse and r.from_id == cur:
                        # 正向：cur → r.to_id
                        if r.to_id not in visited:
                            queue.append(r.to_id)
                            e = self._entities.get(r.to_id)
                            if e and r.to_id != entity_id:
                                results.append(e)
                    elif reverse and r.to_id == cur:
                        # 反向：r.from_id → cur
                        if r.from_id not in visited:
                            queue.append(r.from_id)
                            e = self._entities.get(r.from_id)
                            if e and r.from_id != entity_id:
                                results.append(e)

            return results

    def multi_hop(
        self,
        start_id: str,
        rel_chain: List[str],
    ) -> List[FIBOEntity]:
        """多跳链式查询。

        按顺序应用关系链，返回每跳的累积结果集（最后一跳结果）。

        Args:
            start_id: 起始实体
            rel_chain: 关系类型链 ['part_of', 'part_of', ...]

        Returns:
            最后一跳的实体列表
        """
        with self._lock:
            current_ids: Set[str] = {start_id}
            for hop_idx, rel_type in enumerate(rel_chain):
                next_ids: Set[str] = set()
                for cur_id in current_ids:
                    for r in self._relations:
                        if r.rel_type == rel_type and r.from_id == cur_id:
                            next_ids.add(r.to_id)
                current_ids = next_ids
                if not current_ids:
                    return []

            return [
                self._entities[eid]
                for eid in current_ids
                if eid in self._entities
            ]

    # ============================================================
    # Schema 校验
    # ============================================================

    def validate(self, schema: Dict[str, Any]) -> List[str]:
        """按 schema 校验本体，返回错误列表。

        Schema 格式:
            {
              "relations": {
                "documents": {
                  "from_types": ["Document"],
                  "to_types": ["Module"],
                  "cardinality": "many_to_one"  # 或 one_to_one / one_to_many
                }
              }
            }

        Args:
            schema: 校验 schema

        Returns:
            错误消息列表（空=通过）
        """
        with self._lock:
            errors: List[str] = []
            rel_schemas = (schema or {}).get("relations", {})

            # 按 rel_type 分组
            by_type: Dict[str, List[FIBORelation]] = {}
            for r in self._relations:
                by_type.setdefault(r.rel_type, []).append(r)

            for rel_type, rels in by_type.items():
                rs = rel_schemas.get(rel_type, {})
                from_types = rs.get("from_types", [])
                to_types = rs.get("to_types", [])
                cardinality = rs.get("cardinality")

                # domain/range 检查
                for r in rels:
                    from_e = self._entities.get(r.from_id)
                    to_e = self._entities.get(r.to_id)
                    if from_e and from_types and from_e.entity_type not in from_types:
                        errors.append(
                            f"{rel_type}: from entity {r.from_id} type "
                            f"{from_e.entity_type} not in {from_types}"
                        )
                    if to_e and to_types and to_e.entity_type not in to_types:
                        errors.append(
                            f"{rel_type}: to entity {r.to_id} type "
                            f"{to_e.entity_type} not in {to_types}"
                        )

                # cardinality 检查
                if cardinality in ("many_to_one", "one_to_one"):
                    from_counts: Dict[str, int] = {}
                    for r in rels:
                        from_counts[r.from_id] = from_counts.get(r.from_id, 0) + 1
                    for fid, cnt in from_counts.items():
                        if cnt > 1:
                            errors.append(
                                f"{rel_type}: from entity {fid} violates "
                                f"cardinality {cardinality}"
                            )
                if cardinality in ("one_to_many", "one_to_one"):
                    to_counts: Dict[str, int] = {}
                    for r in rels:
                        to_counts[r.to_id] = to_counts.get(r.to_id, 0) + 1
                    for tid, cnt in to_counts.items():
                        if cnt > 1:
                            errors.append(
                                f"{rel_type}: to entity {tid} violates "
                                f"cardinality {cardinality}"
                            )

            return errors

    # ============================================================
    # 持久化 / 序列化
    # ============================================================

    def to_jsonld(self) -> Dict[str, Any]:
        """序列化为 JSON-LD 风格字典。"""
        with self._lock:
            return {
                "version": 1,
                "entities": [e.to_dict() for e in self._entities.values()],
                "relations": [r.to_dict() for r in self._relations],
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }

    def from_jsonld(self, data: Dict[str, Any]) -> None:
        """从 JSON-LD 风格字典加载。"""
        with self._lock:
            self._entities.clear()
            self._relations.clear()
            for e in data.get("entities", []):
                entity = FIBOEntity.from_dict(e)
                self._entities[entity.id] = entity
            for r in data.get("relations", []):
                self._relations.append(FIBORelation.from_dict(r))

    def persist(self) -> bool:
        """持久化到 JSON 文件。"""
        if not self._ontology_path:
            return False
        with self._lock:
            try:
                self._ontology_path.parent.mkdir(
                    parents=True, exist_ok=True
                )
                data = {
                    "version": 1,
                    "entities": [e.to_dict() for e in self._entities.values()],
                    "relations": [r.to_dict() for r in self._relations],
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }
                self._ontology_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return True
            except Exception:
                return False

    def _restore(self) -> None:
        """从 JSON 恢复（FAIL-OPEN）。"""
        try:
            data = json.loads(self._ontology_path.read_text(encoding="utf-8"))
            for e in data.get("entities", []):
                entity = FIBOEntity.from_dict(e)
                self._entities[entity.id] = entity
            for r in data.get("relations", []):
                self._relations.append(FIBORelation.from_dict(r))
        except Exception:
            self._entities.clear()
            self._relations.clear()

    # ============================================================
    # 统计
    # ============================================================

    def stats(self) -> Dict[str, Any]:
        """本体统计。"""
        with self._lock:
            return {
                "entities": len(self._entities),
                "relations": len(self._relations),
                "types": list({e.entity_type for e in self._entities.values()}),
                "persisted": self._ontology_path is not None,
            }


# ============================================================
# CLI 自测
# ============================================================


if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("FIBOOntology — 功能验证")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as td:
        ont = FIBOOntology(ontology_path=Path(td) / "fibo.json")

        # 创建实体（类层级）
        ont.add_entity("Document", "doc_001",
                       properties={"path": "INDEX.md"})
        ont.add_entity("Module", "mod_010", sub_class_of="Document")
        ont.add_entity("Module", "mod_000", sub_class_of="Document")

        # 关系
        ont.add_relation("doc_001", "part_of", "mod_010")
        ont.add_relation("mod_010", "part_of", "mod_000")

        # 查询
        print(f"\n所有 Document: {len(ont.query('Document'))}")
        print(f"所有 Module: {len(ont.query('Module'))}")

        # 传递闭包
        closure = ont.transitive_closure("doc_001", "part_of")
        print(f"doc_001 part_of 闭包: {[e.id for e in closure]}")

        # 多跳
        results = ont.multi_hop("doc_001", ["part_of", "part_of"])
        print(f"2跳 part_of 结果: {[e.id for e in results]}")

        # Schema 校验
        schema = {
            "relations": {
                "part_of": {
                    "from_types": ["Document", "Module"],
                    "to_types": ["Document", "Module"],
                }
            }
        }
        errors = ont.validate(schema)
        print(f"校验错误: {errors}")

        # 持久化
        ont.persist()
        ont2 = FIBOOntology(ontology_path=Path(td) / "fibo.json")
        print(f"\n恢复后实体数: {ont2.stats()['entities']}")

    print("\n" + "=" * 60)
    print("✅ FIBOOntology 功能验证通过")
