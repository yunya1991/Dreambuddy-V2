"""P3-8 FIBO 语义本体 TDD RED 测试

借鉴 FIBO (Financial Industry Business Ontology) RDF/OWL，将 46 个 INDEX.md
文件索引升级为语义图：
  - 实体类型层级 (subClassOf 传递)
  - 语义关系 (part_of/documents/covers_topic/depends_on/references/version_of)
  - Schema 约束 (cardinality/domain/range)
  - 多跳查询 (transitive closure + multi-hop)

RED 契约:
  1. fibo_ontology 模块不存在 → ImportError
  2. FIBOOntology 类不存在
  3. FIBOEntity / FIBORelation 不存在
  4. add_entity / add_relation / query / transitive_closure 不存在
  5. multi_hop / validate / to_jsonld / from_jsonld 不存在
  6. fibo_index_loader 模块不存在
  7. FIBOIndexLoader 类不存在
  8. parse_index / infer_part_of_from_path 不存在
  9. CognitiveLoopEntry 无 fibo_ontology 属性

参考: SPEC-CognitiveSystem-Evolution.md §4.3 P3-8 + §1.3 L49
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ============================================================
# FIBOOntology 核心类测试
# ============================================================


class TestFIBOOntologyCore:
    """FIBO 语义本体 — 核心实体/关系/查询能力。"""

    def test_import_fibo_ontology(self):
        """RED: fibo_ontology 模块可导入。"""
        from fibo_ontology import FIBOOntology  # noqa: F401

    def test_entity_dataclass(self):
        """RED: FIBOEntity dataclass 存在且有 sub_class_of 字段。"""
        from fibo_ontology import FIBOEntity

        e = FIBOEntity(id="doc_001", entity_type="Document", sub_class_of=None)
        assert e.id == "doc_001"
        assert e.entity_type == "Document"
        assert e.sub_class_of is None
        assert hasattr(e, "properties")
        assert hasattr(e, "created")

    def test_relation_dataclass(self):
        """RED: FIBORelation dataclass 存在。"""
        from fibo_ontology import FIBORelation

        r = FIBORelation(
            from_id="doc_001",
            rel_type="part_of",
            to_id="mod_010",
        )
        assert r.from_id == "doc_001"
        assert r.rel_type == "part_of"
        assert r.to_id == "mod_010"
        assert hasattr(r, "properties")

    def test_create_entity(self, tmp_path):
        """RED: add_entity() 创建实体并返回。"""
        from fibo_ontology import FIBOOntology

        ont = FIBOOntology(ontology_path=tmp_path / "fibo.json")
        e = ont.add_entity(
            entity_type="Document",
            entity_id="doc_001",
            properties={"path": "0-系统文档管理/INDEX.md", "role": "导航中枢"},
        )
        assert e.id == "doc_001"
        assert e.entity_type == "Document"
        assert e.properties["path"] == "0-系统文档管理/INDEX.md"
        # 应能通过 get_entity 获取
        got = ont.get_entity("doc_001")
        assert got is not None
        assert got.id == "doc_001"

    def test_class_hierarchy(self, tmp_path):
        """RED: sub_class_of 字段支持类继承链。"""
        from fibo_ontology import FIBOOntology

        ont = FIBOOntology(ontology_path=tmp_path / "fibo.json")
        # Module 是 Document 的子类
        ont.add_entity("Module", "mod_010", sub_class_of="Document")
        # TradingModule 是 Module 的子类
        ont.add_entity("TradingModule", "mod_010_t", sub_class_of="Module")

        e = ont.get_entity("mod_010_t")
        assert e.sub_class_of == "Module"

    def test_add_relation_part_of(self, tmp_path):
        """RED: add_relation() 添加 part_of 关系。"""
        from fibo_ontology import FIBOOntology

        ont = FIBOOntology(ontology_path=tmp_path / "fibo.json")
        ont.add_entity("Document", "doc_001")
        ont.add_entity("Module", "mod_010")
        rel = ont.add_relation("doc_001", "part_of", "mod_010")
        assert rel.from_id == "doc_001"
        assert rel.rel_type == "part_of"
        assert rel.to_id == "mod_010"

    def test_query_by_type(self, tmp_path):
        """RED: query(type=...) 按类型查询。"""
        from fibo_ontology import FIBOOntology

        ont = FIBOOntology(ontology_path=tmp_path / "fibo.json")
        ont.add_entity("Document", "doc_001")
        ont.add_entity("Document", "doc_002")
        ont.add_entity("Module", "mod_010")

        docs = ont.query(entity_type="Document")
        assert len(docs) == 2
        ids = {e.id for e in docs}
        assert ids == {"doc_001", "doc_002"}

    def test_query_with_where(self, tmp_path):
        """RED: query(type=..., where={...}) 属性过滤。"""
        from fibo_ontology import FIBOOntology

        ont = FIBOOntology(ontology_path=tmp_path / "fibo.json")
        ont.add_entity("Document", "doc_001", properties={"topic": "风控"})
        ont.add_entity("Document", "doc_002", properties={"topic": "交易"})
        ont.add_entity("Document", "doc_003", properties={"topic": "风控"})

        results = ont.query(entity_type="Document", where={"topic": "风控"})
        assert len(results) == 2
        assert all(r.properties["topic"] == "风控" for r in results)

    def test_transitive_closure_part_of(self, tmp_path):
        """RED: transitive_closure() 返回 part_of 传递闭包。

        doc_001 → part_of → mod_010 → part_of → mod_000
        从 doc_001 出发，应返回 [mod_010, mod_000]
        """
        from fibo_ontology import FIBOOntology

        ont = FIBOOntology(ontology_path=tmp_path / "fibo.json")
        ont.add_entity("Document", "doc_001")
        ont.add_entity("Module", "mod_010")
        ont.add_entity("Module", "mod_000")
        ont.add_relation("doc_001", "part_of", "mod_010")
        ont.add_relation("mod_010", "part_of", "mod_000")

        closure = ont.transitive_closure("doc_001", "part_of")
        ids = {e.id for e in closure}
        assert "mod_010" in ids
        assert "mod_000" in ids
        # doc_001 自身不在结果中
        assert "doc_001" not in ids

    def test_multi_hop_query(self, tmp_path):
        """RED: multi_hop() 链式查询（2跳 part_of）。

        doc_001 → part_of → mod_010 → part_of → mod_000
        multi_hop(doc_001, ['part_of', 'part_of']) → [mod_000]
        """
        from fibo_ontology import FIBOOntology

        ont = FIBOOntology(ontology_path=tmp_path / "fibo.json")
        ont.add_entity("Document", "doc_001")
        ont.add_entity("Module", "mod_010")
        ont.add_entity("Module", "mod_000")
        ont.add_relation("doc_001", "part_of", "mod_010")
        ont.add_relation("mod_010", "part_of", "mod_000")

        results = ont.multi_hop("doc_001", ["part_of", "part_of"])
        assert len(results) == 1
        assert results[0].id == "mod_000"

    def test_validate_cardinality(self, tmp_path):
        """RED: validate(schema) 检测 cardinality 违规。

        Schema 约束 documents 关系为 many_to_one，
        若 doc_001 → documents → mod_010 且 doc_001 → documents → mod_011，
        应报错（一个 Document 只能 documents 一个 Module）。
        """
        from fibo_ontology import FIBOOntology

        ont = FIBOOntology(ontology_path=tmp_path / "fibo.json")
        ont.add_entity("Document", "doc_001")
        ont.add_entity("Module", "mod_010")
        ont.add_entity("Module", "mod_011")
        ont.add_relation("doc_001", "documents", "mod_010")
        ont.add_relation("doc_001", "documents", "mod_011")  # 违反 many_to_one

        schema = {
            "relations": {
                "documents": {
                    "from_types": ["Document"],
                    "to_types": ["Module"],
                    "cardinality": "many_to_one",
                }
            }
        }
        errors = ont.validate(schema)
        assert any("documents" in err for err in errors)
        assert any("doc_001" in err for err in errors)

    def test_validate_domain_range(self, tmp_path):
        """RED: validate(schema) 检测 domain/range 类型违规。

        Module → documents → Document (domain 错，documents 的 domain 应是 Document)
        """
        from fibo_ontology import FIBOOntology

        ont = FIBOOntology(ontology_path=tmp_path / "fibo.json")
        ont.add_entity("Module", "mod_010")
        ont.add_entity("Document", "doc_001")
        ont.add_relation("mod_010", "documents", "doc_001")  # 反向，domain 违规

        schema = {
            "relations": {
                "documents": {
                    "from_types": ["Document"],
                    "to_types": ["Module"],
                }
            }
        }
        errors = ont.validate(schema)
        assert any("documents" in err for err in errors)

    def test_persist_and_restore(self, tmp_path):
        """RED: to_jsonld/from_jsonld 持久化与恢复。"""
        from fibo_ontology import FIBOOntology

        path = tmp_path / "fibo.json"
        ont = FIBOOntology(ontology_path=path)
        ont.add_entity("Document", "doc_001", properties={"path": "INDEX.md"})
        ont.add_entity("Module", "mod_010")
        ont.add_relation("doc_001", "part_of", "mod_010")
        ont.persist()

        # 恢复
        ont2 = FIBOOntology(ontology_path=path)
        assert ont2.get_entity("doc_001") is not None
        assert ont2.get_entity("mod_010") is not None
        rels = ont2.get_relations("doc_001", "part_of")
        assert len(rels) == 1
        assert rels[0].to_id == "mod_010"

    def test_stats(self, tmp_path):
        """RED: stats() 返回本体统计。"""
        from fibo_ontology import FIBOOntology

        ont = FIBOOntology(ontology_path=tmp_path / "fibo.json")
        ont.add_entity("Document", "doc_001")
        ont.add_entity("Module", "mod_010")
        ont.add_relation("doc_001", "part_of", "mod_010")
        s = ont.stats()
        assert s["entities"] == 2
        assert s["relations"] == 1


# ============================================================
# FIBOIndexLoader INDEX.md 解析器测试
# ============================================================


SAMPLE_INDEX_MD = """# 全项目文档索引 — INDEX

> **版本**: v2.8

## L1 — 顶层架构

| 文档 | 路径 | 职责 | 状态 |
|------|------|------|------|
| 架构总览 | [1-ARCHITECTURE/SYSTEM.md](../1-ARCHITECTURE/SYSTEM.md) | 架构唯一事实源 | ✅ |
| 治理章程 | [2-GOVERNANCE/CHARTER.md](../2-GOVERNANCE/CHARTER.md) | 系统根本大法 | ✅ |

## L2 — 子系统文档

### 10-经典指标系统

| 文档 | 路径 | 版本 |
|------|------|------|
| README | [10-经典指标系统/README.md](../10-经典指标系统/README.md) | - |
| 技术设计 | [10-经典指标系统/docs/TECHNICAL_DESIGN.md](../10-经典指标系统/docs/TECHNICAL_DESIGN.md) | v2.0 |
"""


class TestFIBOIndexLoader:
    """FIBO INDEX.md 解析器。"""

    def test_import_fibo_index_loader(self):
        """RED: fibo_index_loader 模块可导入。"""
        from fibo_index_loader import FIBOIndexLoader  # noqa: F401

    def test_parse_index_creates_entities(self, tmp_path):
        """RED: parse_index() 解析 markdown 表格创建实体。"""
        from fibo_ontology import FIBOOntology
        from fibo_index_loader import FIBOIndexLoader

        md_path = tmp_path / "INDEX.md"
        md_path.write_text(SAMPLE_INDEX_MD, encoding="utf-8")

        ont = FIBOOntology()
        loader = FIBOIndexLoader(ont)
        loader.parse_index(md_path)

        # 应至少创建 4 个 Document 实体（4 行表格）
        docs = ont.query(entity_type="Document")
        assert len(docs) >= 4

    def test_infer_part_of_from_path(self, tmp_path):
        """RED: 从路径层级推断 part_of 关系。

        路径 10-经典指标系统/docs/TECHNICAL_DESIGN.md 应 part_of 10-经典指标系统
        """
        from fibo_ontology import FIBOOntology
        from fibo_index_loader import FIBOIndexLoader

        md_path = tmp_path / "INDEX.md"
        md_path.write_text(SAMPLE_INDEX_MD, encoding="utf-8")

        ont = FIBOOntology()
        loader = FIBOIndexLoader(ont)
        loader.parse_index(md_path)

        # 应有 part_of 关系
        rels = []
        for e in ont.query(entity_type="Document"):
            rels.extend(ont.get_relations(e.id, "part_of"))
        assert len(rels) >= 1

    def test_infer_covers_topic_from_section(self, tmp_path):
        """RED: 从章节标题推断 covers_topic 关系。

        ## L2 — 子系统文档 下属文档 covers_topic 'L2' 或 '子系统'
        """
        from fibo_ontology import FIBOOntology
        from fibo_index_loader import FIBOIndexLoader

        md_path = tmp_path / "INDEX.md"
        md_path.write_text(SAMPLE_INDEX_MD, encoding="utf-8")

        ont = FIBOOntology()
        loader = FIBOIndexLoader(ont)
        loader.parse_index(md_path)

        # 应有 covers_topic 关系
        topic_rels = []
        for e in ont.query(entity_type="Document"):
            topic_rels.extend(ont.get_relations(e.id, "covers_topic"))
        assert len(topic_rels) >= 1

    def test_failopen_invalid_markdown(self, tmp_path):
        """RED: 解析失败不阻塞（FAIL-OPEN）。"""
        from fibo_ontology import FIBOOntology
        from fibo_index_loader import FIBOIndexLoader

        md_path = tmp_path / "bad.md"
        md_path.write_text("这不是 markdown 表格\n随便写的内容", encoding="utf-8")

        ont = FIBOOntology()
        loader = FIBOIndexLoader(ont)
        # 不应抛异常
        loader.parse_index(md_path)
        # 没有实体也无妨
        assert ont.stats()["entities"] >= 0

    def test_failopen_missing_file(self, tmp_path):
        """RED: 文件不存在不阻塞（FAIL-OPEN）。"""
        from fibo_ontology import FIBOOntology
        from fibo_index_loader import FIBOIndexLoader

        ont = FIBOOntology()
        loader = FIBOIndexLoader(ont)
        # 不存在的文件
        loader.parse_index(tmp_path / "nonexistent.md")
        assert ont.stats()["entities"] == 0


# ============================================================
# CognitiveLoopEntry 集成测试
# ============================================================


class TestCognitiveLoopEntryFIBO:
    """CognitiveLoopEntry FIBO 集成点。"""

    def test_fibo_ontology_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 fibo_ontology 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry

        assert hasattr(CognitiveLoopEntry, "__init__")
        # 检查源代码（避免实例化触发 DB 依赖）
        import inspect

        src = inspect.getsource(CognitiveLoopEntry.__init__)
        assert "fibo_ontology" in src
        assert "FIBOOntology" in src
