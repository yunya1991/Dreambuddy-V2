"""
SqliteKnowledgeGraphRepository：SQLite Unified 知识图谱实现
--------------------------------------------------------------
Protocol ↔ schema_init 差异处理：
| Protocol 参数                              | schema 列                     | 处理方式               |
|-------------------------------------------|-------------------------------|----------------------|
| upsert_entity: entity_type                | category                      | 改名                 |
| upsert_entity: canonical_name             | label                         | 改名                 |
| upsert_entity: description + attributes_json | metadata (JSON)             | 合并 JSON 存入      |
| add_alias: confidence (1.0)               | ALTER TABLE → confidence REAL | _ensure_proto_columns |
| add_triple: subject_id/object_id          | subject/object                | 改名                 |
| add_triple: source                        | sources (JSON 数组)           | JSON 数组包一层      |
| fts_search_entities: 只搜实体（名称/别名） | kg_terms_fts (需手动同步 insert) | _sync_entity_to_fts |
| query_subgraph_by_entity: N 跳递归        | SQL 自连接 1/2 hop            | 循环展开 UNION ALL   |
"""
from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone as _tz_utc
from typing import List, Optional, Set, Tuple

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.protocols.kg_repo import KnowledgeGraphRepository


# ===================================================================== helpers
def _iso_z(dt: object) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz_utc.utc)
        return dt.astimezone(_tz_utc.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(dt)


# ===================================================================== 实现
class SqliteKnowledgeGraphRepository(KnowledgeGraphRepository):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_proto_columns()

    # ------------------------------------------------------------------ 补列
    def _ensure_proto_columns(self) -> None:
        """kg_entity_aliases 缺 confidence 列 → ALTER。"""
        with get_sqlite_connection(self.db_path) as conn:
            cols = {c[1] for c in conn.execute("PRAGMA table_info(kg_entity_aliases)").fetchall()}
            if "confidence" not in cols:
                conn.execute(
                    "ALTER TABLE kg_entity_aliases ADD COLUMN confidence REAL DEFAULT 1.0"
                )

    # ================================================================ 实体 upsert
    def upsert_entity(
        self,
        entity_id: str,
        entity_type: str,
        canonical_name: str,
        *,
        description: Optional[str] = None,
        attributes_json: Optional[str] = None,
    ) -> bool:
        # 合并 metadata JSON
        meta: dict = {}
        if description:
            meta["description"] = description
        if attributes_json:
            try:
                attr = json.loads(attributes_json) if isinstance(attributes_json, str) else attributes_json
                if isinstance(attr, dict):
                    meta["attributes"] = attr
            except Exception:
                meta["attributes_raw"] = attributes_json
        meta_s = json.dumps(meta, ensure_ascii=False) if meta else None

        with get_sqlite_connection(self.db_path) as conn:
            # 查是否存在
            existing = conn.execute(
                "SELECT 1 FROM kg_entities WHERE entity_id=?", (entity_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE kg_entities SET label=?, category=?, metadata=?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE entity_id=?
                    """,
                    (canonical_name, entity_type, meta_s, entity_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO kg_entities (entity_id, label, category, metadata)
                    VALUES (?, ?, ?, ?)
                    """,
                    (entity_id, canonical_name, entity_type, meta_s),
                )
                # FTS5 手动同步（实体名+分类 → 一个 term，用实体的 rowid）
                rowid_row = conn.execute(
                    "SELECT rowid FROM kg_entities WHERE entity_id=?", (entity_id,)
                ).fetchone()
                if rowid_row:
                    rid = rowid_row[0]
                    fts_term = f"{canonical_name} {entity_type}"
                    try:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO kg_terms_fts(rowid, term, entity_id, triple_id)
                            VALUES (?, ?, ?, NULL)
                            """,
                            (rid, fts_term, entity_id),
                        )
                    except Exception:
                        # 外部 content 表 FTS5 有些环境 insert 方式不同，容错跳过
                        pass
        return True

    # ================================================================ 别名
    def add_alias(
        self, entity_id: str, alias: str, *, confidence: float = 1.0,
    ) -> bool:
        try:
            with get_sqlite_connection(self.db_path) as conn:
                # INSERT OR IGNORE → UNIQUE(entity_id, alias)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO kg_entity_aliases
                        (entity_id, alias, is_primary, confidence)
                    VALUES (?, ?, 0, ?)
                    """,
                    (entity_id, alias, float(confidence)),
                )
                # 别名同步进 FTS5：找实体 rowid，再用 rowid 同条追加 term（OR REPLACE 合并）
                rowid_row = conn.execute(
                    "SELECT rowid FROM kg_entities WHERE entity_id=?", (entity_id,)
                ).fetchone()
                lbl_row = conn.execute(
                    "SELECT label, category FROM kg_entities WHERE entity_id=?", (entity_id,)
                ).fetchone()
                if rowid_row and lbl_row:
                    rid = rowid_row[0]
                    lbl, cat = lbl_row
                    fts_term = f"{lbl} {cat} {alias}"
                    try:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO kg_terms_fts(rowid, term, entity_id, triple_id)
                            VALUES (?, ?, ?, NULL)
                            """,
                            (rid, fts_term, entity_id),
                        )
                    except Exception:
                        pass
        except Exception:
            # UNIQUE 冲突也返回 True（幂等）
            return True
        return True

    # ================================================================ 三元组
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
        sources_s = json.dumps([source], ensure_ascii=False) if source else None
        vf_s = _iso_z(valid_from) if valid_from else None
        with get_sqlite_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO kg_triples
                    (subject, predicate, object, confidence, sources, valid_from)
                VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                """,
                (
                    subject_id, predicate, object_id,
                    float(confidence), sources_s, vf_s,
                ),
            )
            triple_id = cur.lastrowid
            # FTS5 同步三元组关键词：subject + predicate + object → term
            try:
                fts_term = f"{subject_id} {predicate} {object_id}"
                conn.execute(
                    """
                    INSERT OR REPLACE INTO kg_terms_fts(rowid, term, entity_id, triple_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (triple_id, fts_term, subject_id, triple_id),
                )
            except Exception:
                pass
        return True

    # ================================================================ FTS 搜索
    def fts_search_entities(
        self, query: str, *, limit: int = 20,
    ) -> List[Tuple[str, str, str, float]]:
        # FTS5 MATCH：直接 term 关键词模糊
        safe_q = " ".join(str(query).split())  # 去空，简化用 LIKE 方案兜底
        out: list[tuple] = []
        with get_sqlite_connection(self.db_path) as conn:
            # 优先用 FTS5 MATCH
            try:
                rows = conn.execute(
                    """
                    SELECT DISTINCT f.entity_id, e.category, e.label,
                           bm25(kg_terms_fts) AS r
                    FROM kg_terms_fts f
                    LEFT JOIN kg_entities e ON e.entity_id = f.entity_id
                    WHERE kg_terms_fts MATCH ?
                      AND e.entity_id IS NOT NULL
                    ORDER BY r ASC
                    LIMIT ?
                    """,
                    (safe_q, limit),
                ).fetchall()
                for eid, cat, lbl, r in rows:
                    out.append((eid, cat or "", lbl or "", float(r or 0)))
            except Exception:
                # 兜底方案：实体表 LIKE（忽略 FTS5 MATCH 语法错误）
                like = f"%{safe_q}%"
                rows = conn.execute(
                    """
                    SELECT entity_id, category, label, 0.0
                    FROM kg_entities
                    WHERE label LIKE ? OR category LIKE ? OR entity_id LIKE ?
                    ORDER BY entity_id
                    LIMIT ?
                    """,
                    (like, like, like, limit),
                ).fetchall()
                out = [(r[0], r[1] or "", r[2] or "", float(r[3])) for r in rows]
        return out

    # ================================================================ N 跳子图
    def query_subgraph_by_entity(
        self,
        entity_id: str,
        *,
        hops: int = 2,
        direction: str = "both",  # "out" / "in" / "both"
        min_confidence: float = 0.5,
    ) -> Tuple[List[Tuple[str, str, str, float]], List[Tuple[str, str, str]]]:
        triples_out: List[Tuple[str, str, str, float]] = []
        seen_triple_keys: Set[str] = set()
        entity_set: Set[str] = {entity_id}

        effective_hops = max(1, min(int(hops), 3))
        min_c = float(min_confidence)

        with get_sqlite_connection(self.db_path) as conn:
            frontier: Set[str] = {entity_id}
            for _ in range(effective_hops):
                if not frontier:
                    break
                next_frontier: Set[str] = set()
                placeholders = ",".join("?" for _ in frontier)
                params: list[object] = [min_c] + list(frontier)

                # OUT：subject IN frontier → (s, p, o, c)
                if direction in ("out", "both"):
                    rows = conn.execute(
                        f"""
                        SELECT subject, predicate, object, confidence
                        FROM kg_triples
                        WHERE confidence >= ?
                          AND subject IN ({placeholders})
                          AND (valid_to IS NULL OR valid_to >= CURRENT_TIMESTAMP)
                        """,
                        params,
                    ).fetchall()
                    for s, p, o, c in rows:
                        key = f"OUT|{s}|{p}|{o}"
                        if key not in seen_triple_keys:
                            seen_triple_keys.add(key)
                            triples_out.append((s, p, o, float(c)))
                            entity_set.add(s)
                            entity_set.add(o)
                            next_frontier.add(o)

                # IN：object IN frontier → (s, p, o, c)
                if direction in ("in", "both"):
                    rows = conn.execute(
                        f"""
                        SELECT subject, predicate, object, confidence
                        FROM kg_triples
                        WHERE confidence >= ?
                          AND object IN ({placeholders})
                          AND (valid_to IS NULL OR valid_to >= CURRENT_TIMESTAMP)
                        """,
                        params,
                    ).fetchall()
                    for s, p, o, c in rows:
                        key = f"IN|{s}|{p}|{o}"
                        if key not in seen_triple_keys:
                            seen_triple_keys.add(key)
                            triples_out.append((s, p, o, float(c)))
                            entity_set.add(s)
                            entity_set.add(o)
                            next_frontier.add(s)

                frontier = next_frontier

            # 实体详情
            if entity_set:
                eps = ",".join("?" for _ in entity_set)
                ent_rows = conn.execute(
                    f"""
                    SELECT entity_id, category, label FROM kg_entities
                    WHERE entity_id IN ({eps})
                    """,
                    list(entity_set),
                ).fetchall()
            else:
                ent_rows = []
        entities_list = [(r[0], r[1] or "", r[2] or "") for r in ent_rows]
        return triples_out, entities_list


__all__ = ["SqliteKnowledgeGraphRepository"]
