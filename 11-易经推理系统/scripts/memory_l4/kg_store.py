"""
交易知识图谱存储模块

参考 Smriti (vn-envy/Smriti) 的 SQLite 三元组存储设计：
- 使用 subject-predicate-object 三元组表示知识
- 支持双时态（valid_from/invalid_at）
- SQLite 内置 FTS5 全文搜索
- 向量存储支持（可选 numpy）

交易领域定制：
- 实体类型：Instrument, Strategy, Regime, Hexagram, TradeCase, Distill, Constraint
- 关系类型：has_regime, uses_strategy, has_hexagram, resulted_in, learned_from, confirms, contradicts
"""

import re
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

try:
    import numpy as np
except ImportError:
    np = None

from dataclasses import dataclass, field


@dataclass
class Triple:
    """知识图谱三元组。"""
    id: Optional[int] = None
    subject: str = ""
    predicate: str = ""
    object: str = ""
    statement: str = ""
    kind: str = "knowledge"
    entities: List[str] = field(default_factory=list)
    event_date: Optional[str] = None
    ingested_at: Optional[str] = None
    valid_from: Optional[str] = None
    invalid_at: Optional[str] = None
    superseded_by: Optional[int] = None


@dataclass
class Entity:
    """知识图谱实体。"""
    name: str
    type: str = "unknown"
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KGQueryResult:
    """知识图谱查询结果。"""
    triples: List[Triple]
    entities: List[Entity]
    score: float = 0.0


_SCHEMA_BASE = """
CREATE TABLE IF NOT EXISTS triples(
    id INTEGER PRIMARY KEY,
    subject TEXT, predicate TEXT, object TEXT,
    statement TEXT, kind TEXT,
    event_date TEXT, ingested_at TEXT,
    valid_from TEXT, invalid_at TEXT,
    superseded_by INTEGER
);
CREATE TABLE IF NOT EXISTS entities(
    name TEXT PRIMARY KEY,
    type TEXT,
    properties TEXT
);
CREATE TABLE IF NOT EXISTS entity_aliases(
    alias TEXT PRIMARY KEY,
    canonical TEXT
);
CREATE INDEX IF NOT EXISTS idx_triples_spo ON triples(subject, predicate, object);
CREATE INDEX IF NOT EXISTS idx_triples_subj_pred ON triples(subject, predicate);
CREATE INDEX IF NOT EXISTS idx_triples_pred ON triples(predicate);
CREATE INDEX IF NOT EXISTS idx_triples_kind ON triples(kind);
"""


def _fts_ddl() -> str:
    """FTS5 全文索引。"""
    return """
CREATE VIRTUAL TABLE IF NOT EXISTS triples_fts USING fts5(
    statement, subject, predicate, object,
    content='triples', content_rowid='id'
);
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    name, type,
    content='entities', content_rowid='name'
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class KGStore:
    """交易知识图谱 SQLite 存储。"""

    def __init__(self, path: Optional[str] = None, stem: bool = False):
        if path is None:
            from scripts.memory_l4.paths import workbuddy_dir
            path = str(workbuddy_dir() / "memory_l4" / "kg" / "knowledge_graph.db")
        self.path = path
        self.stem = stem
        self._init_db()

    def _init_db(self) -> None:
        db_path = self.path
        if "/" in db_path or "\\" in db_path:
            import os
            dir_path = os.path.dirname(db_path)
            os.makedirs(dir_path, exist_ok=True)
        self.db = sqlite3.connect(db_path, isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=5000")
        for attempt in range(5):
            try:
                self.db.execute("PRAGMA journal_mode=WAL")
                self.db.execute("PRAGMA synchronous=NORMAL")
                self.db.executescript(_SCHEMA_BASE)
                self.db.executescript(_fts_ddl())
                break
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower():
                    raise
                import time as _time
                _time.sleep(0.05 * (2 ** attempt))

    def add_triple(self, triple: Triple) -> int:
        """添加三元组。"""
        cur = self.db.execute(
            """INSERT INTO triples(subject, predicate, object, statement, kind,
                                  event_date, ingested_at, valid_from, invalid_at, superseded_by)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                triple.subject,
                triple.predicate,
                triple.object,
                triple.statement,
                triple.kind,
                triple.event_date,
                triple.ingested_at or utcnow(),
                triple.valid_from or utcnow(),
                triple.invalid_at,
                triple.superseded_by,
            ),
        )
        return cur.lastrowid

    def add_entity(self, entity: Entity) -> None:
        """添加实体。"""
        import json
        self.db.execute(
            "INSERT OR REPLACE INTO entities(name, type, properties) VALUES(?, ?, ?)",
            (entity.name, entity.type, json.dumps(entity.properties, ensure_ascii=False)),
        )

    def add_entity_alias(self, alias: str, canonical: str) -> None:
        """添加实体别名。"""
        self.db.execute(
            "INSERT OR REPLACE INTO entity_aliases(alias, canonical) VALUES(?, ?)",
            (alias, canonical),
        )

    def get_triples_by_subject(self, subject: str) -> List[Triple]:
        """按主体查询三元组。"""
        rows = self.db.execute(
            "SELECT * FROM triples WHERE subject = ? AND (invalid_at IS NULL OR invalid_at > ?)",
            (subject, utcnow()),
        ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def get_triples_by_predicate(self, predicate: str) -> List[Triple]:
        """按谓词查询三元组。"""
        rows = self.db.execute(
            "SELECT * FROM triples WHERE predicate = ? AND (invalid_at IS NULL OR invalid_at > ?)",
            (predicate, utcnow()),
        ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def get_triples_by_object(self, obj: str) -> List[Triple]:
        """按对象查询三元组。"""
        rows = self.db.execute(
            "SELECT * FROM triples WHERE object = ? AND (invalid_at IS NULL OR invalid_at > ?)",
            (obj, utcnow()),
        ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def get_triple(self, subject: str, predicate: str, obj: str) -> Optional[Triple]:
        """查询特定三元组。"""
        row = self.db.execute(
            "SELECT * FROM triples WHERE subject = ? AND predicate = ? AND object = ?",
            (subject, predicate, obj),
        ).fetchone()
        return self._row_to_triple(row) if row else None

    def search_triples(self, query: str, limit: int = 20) -> List[Triple]:
        """全文搜索三元组。"""
        tokens = re.findall(r"\w+", query, re.UNICODE)
        tokens = [t for t in tokens if len(t) > 1][:32]
        if not tokens:
            return []
        fts_query = " OR ".join(f'"{t}"' for t in tokens)
        rows = self.db.execute(
            f"SELECT * FROM triples WHERE id IN (SELECT rowid FROM triples_fts WHERE statement MATCH ?) LIMIT ?",
            (fts_query, limit),
        ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def get_entity(self, name: str) -> Optional[Entity]:
        """获取实体。"""
        row = self.db.execute("SELECT * FROM entities WHERE name = ?", (name,)).fetchone()
        if not row:
            alias = self.db.execute(
                "SELECT canonical FROM entity_aliases WHERE alias = ?", (name,)
            ).fetchone()
            if alias:
                row = self.db.execute(
                    "SELECT * FROM entities WHERE name = ?", (alias[0],)
                ).fetchone()
        if row:
            import json
            return Entity(
                name=row[0],
                type=row[1],
                properties=json.loads(row[2]) if row[2] else {},
            )
        return None

    def list_entities_by_type(self, entity_type: str) -> List[Entity]:
        """按类型列出实体。"""
        rows = self.db.execute("SELECT * FROM entities WHERE type = ?", (entity_type,)).fetchall()
        import json
        return [
            Entity(name=r[0], type=r[1], properties=json.loads(r[2]) if r[2] else {})
            for r in rows
        ]

    def get_entity_triples(self, entity_name: str) -> List[Triple]:
        """获取实体相关的所有三元组。"""
        entity = self.get_entity(entity_name)
        if not entity:
            return []
        canonical = entity.name
        rows = self.db.execute(
            """SELECT * FROM triples WHERE subject = ? OR object = ?
               AND (invalid_at IS NULL OR invalid_at > ?)""",
            (canonical, canonical, utcnow()),
        ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def supersede_triple(self, triple_id: int, new_triple: Triple) -> int:
        """替换三元组（双时态）。"""
        self.db.execute(
            "UPDATE triples SET invalid_at = ?, superseded_by = ? WHERE id = ?",
            (utcnow(), new_triple.id, triple_id),
        )
        return self.add_triple(new_triple)

    def get_stats(self) -> Dict[str, Any]:
        """统计信息。"""
        triple_count = self.db.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
        entity_count = self.db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        kinds = self.db.execute(
            "SELECT kind, COUNT(*) FROM triples GROUP BY kind"
        ).fetchall()
        predicates = self.db.execute(
            "SELECT predicate, COUNT(*) FROM triples GROUP BY predicate"
        ).fetchall()
        return {
            "triple_count": triple_count,
            "entity_count": entity_count,
            "kind_distribution": dict(kinds),
            "predicate_distribution": dict(predicates),
        }

    @staticmethod
    def _row_to_triple(row: Tuple) -> Triple:
        return Triple(
            id=row[0],
            subject=row[1],
            predicate=row[2],
            object=row[3],
            statement=row[4],
            kind=row[5],
            event_date=row[6],
            ingested_at=row[7],
            valid_from=row[8],
            invalid_at=row[9],
            superseded_by=row[10],
        )

    def close(self) -> None:
        """关闭数据库连接。"""
        self.db.close()
