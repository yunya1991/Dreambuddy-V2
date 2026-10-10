#!/usr/bin/env python3
"""debate_memory.py — 辩论记忆 CRUD（7 标准接口）

SPEC v2.0-rc3 第五节：4-MEMORY L2 应用记忆新增 "debate" 类型。
记忆子类型: argument-pattern / rhetorical-strategy / topic-knowledge / prediction

7 标准接口:
  1. search(query, top_k, min_quality) — 搜索辩论记忆
  2. add(content, quality_level, tags) — 添加辩论记忆
  3. update(memory_id, fields) — 更新辩论记忆
  4. get(memory_id) — 获取单条记忆
  5. stats() — 统计信息
  6. distill_candidates(min_quality, limit) — 蒸馏候选
  7. healthcheck() — 健康检查
"""
from __future__ import annotations

import json
import logging
import os
import random
import sqlite3
import time
from typing import Any

logger = logging.getLogger("debate.memory")

# 质量等级 → 分数映射
_QUALITY_SCORES = {
    "S": 0.95, "A": 0.70, "B": 0.40, "C": 0.20, "D": 0.10,
}

_QUALITY_ORDER = ["S", "A", "B", "C", "D"]


def _quality_to_score(quality: str) -> float:
    """质量等级转分数。"""
    return _QUALITY_SCORES.get(quality, 0.20)


def _score_to_quality(score: float) -> str:
    """分数转质量等级。"""
    if score >= 0.95:
        return "S"
    elif score >= 0.70:
        return "A"
    elif score >= 0.40:
        return "B"
    elif score >= 0.20:
        return "C"
    else:
        return "D"


class DebateMemory:
    """辩论记忆 CRUD（7 标准接口）。

    使用 SQLite 存储，与 cognitive_memory.db 共享基础设施。
    辩论记忆表: debate_memories
    """

    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: SQLite 数据库路径。默认使用 4-MEMORY/data/cognitive_memory.db。
                     ":memory:" 用于内存数据库（测试用）。
        """
        if db_path is None:
            repo_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", ".."))
            db_path = os.path.join(repo_root, "data", "cognitive_memory.db")
        self._db_path = db_path
        self._persistent = db_path == ":memory:"
        self._persist_conn = self._open()
        self._init_db()

    def _open(self) -> sqlite3.Connection:
        """打开数据库连接。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _conn(self) -> sqlite3.Connection:
        """获取数据库连接。"""
        if self._persistent:
            return self._persist_conn
        return self._open()

    def _init_db(self):
        """初始化数据库表。"""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS debate_memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    quality_level TEXT DEFAULT 'C',
                    score REAL DEFAULT 0.20,
                    tags TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.0,
                    verify_count INTEGER DEFAULT 0,
                    verified INTEGER DEFAULT 0,
                    created_at REAL,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_debate_tags
                ON debate_memories(tags)
            """)
            # SPEC v1.2-rc1 §6 P1: CBR 案例表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS debate_cbr_cases (
                    case_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    topic_type TEXT DEFAULT 'general',
                    strategies_used TEXT DEFAULT '[]',
                    winner TEXT DEFAULT 'draw',
                    bull_score REAL DEFAULT 0.0,
                    bear_score REAL DEFAULT 0.0,
                    effective_strategies TEXT DEFAULT '[]',
                    adaptation_hints TEXT DEFAULT '[]',
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cbr_topic
                ON debate_cbr_cases(topic)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cbr_type
                ON debate_cbr_cases(topic_type)
            """)
            # SPEC v1.2-rc1 §6 P1: 策略权重表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS debate_strategy_weights (
                    strategy TEXT NOT NULL,
                    topic_type TEXT NOT NULL,
                    alpha REAL DEFAULT 1.0,
                    beta REAL DEFAULT 1.0,
                    updated_at REAL,
                    PRIMARY KEY (strategy, topic_type)
                )
            """)
            # SPEC v1.2-rc1 §6 P1: Persona Elo 表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS debate_elo (
                    persona TEXT PRIMARY KEY,
                    elo REAL DEFAULT 1200.0,
                    debates INTEGER DEFAULT 0,
                    updated_at REAL
                )
            """)
            conn.commit()

    # ── 1. add ──────────────────────────────────────────────

    def add(self, content: str, quality_level: str = "C",
            tags: str = "debate") -> str | None:
        """添加辩论记忆。

        Returns: memory_id，失败返回 None。
        """
        mid = f"DM-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
        score = _quality_to_score(quality_level)
        now = time.time()
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO debate_memories "
                    "(id, content, quality_level, score, tags, confidence, "
                    "verify_count, verified, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 0.0, 0, 0, ?, ?)",
                    (mid, content, quality_level, score, tags, now, now),
                )
                conn.commit()
            logger.debug("辩论记忆已添加: %s tags=%s", mid, tags)
            return mid
        except sqlite3.Error as e:
            logger.error("添加辩论记忆失败: %s", e)
            return None

    # ── 2. get ──────────────────────────────────────────────

    def get(self, memory_id: str) -> dict | None:
        """获取单条记忆。"""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM debate_memories WHERE id = ?",
                    (memory_id,),
                ).fetchone()
                if row is None:
                    return None
                return dict(row)
        except sqlite3.Error as e:
            logger.error("获取辩论记忆失败: %s", e)
            return None

    # ── 3. search ───────────────────────────────────────────

    def search(self, query: str, top_k: int = 5,
               min_quality: str = "C") -> list[dict]:
        """搜索辩论记忆。

        按 tags 和 content 模糊匹配，按 score 降序排列。
        """
        min_score = _quality_to_score(min_quality)
        pattern = f"%{query}%"
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM debate_memories "
                    "WHERE score >= ? AND (content LIKE ? OR tags LIKE ?) "
                    "ORDER BY score DESC LIMIT ?",
                    (min_score, pattern, pattern, top_k),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error("搜索辩论记忆失败: %s", e)
            return []

    # ── 4. update ───────────────────────────────────────────

    def update(self, memory_id: str, **fields) -> bool:
        """更新辩论记忆字段。

        支持更新: quality_level, score, tags, confidence, verify_count, verified.
        """
        allowed = {"quality_level", "score", "tags", "confidence",
                   "verify_count", "verified", "content"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False

        # 如果更新 quality_level，自动更新 score
        if "quality_level" in updates and "score" not in updates:
            updates["score"] = _quality_to_score(updates["quality_level"])

        updates["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [memory_id]

        try:
            with self._conn() as conn:
                conn.execute(
                    f"UPDATE debate_memories SET {set_clause} WHERE id = ?",
                    values,
                )
                conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error("更新辩论记忆失败: %s", e)
            return False

    # ── 5. stats ────────────────────────────────────────────

    def stats(self) -> dict:
        """统计信息。"""
        try:
            with self._conn() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM debate_memories"
                ).fetchone()[0]
                by_quality = {}
                for q in _QUALITY_ORDER:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM debate_memories WHERE quality_level = ?",
                        (q,),
                    ).fetchone()[0]
                    if count > 0:
                        by_quality[q] = count
                verified = conn.execute(
                    "SELECT COUNT(*) FROM debate_memories WHERE verified = 1"
                ).fetchone()[0]
            return {
                "total": total,
                "by_quality": by_quality,
                "verified": verified,
            }
        except sqlite3.Error as e:
            logger.error("统计辩论记忆失败: %s", e)
            return {"total": 0, "by_quality": {}, "verified": 0}

    # ── 6. distill_candidates ───────────────────────────────

    def distill_candidates(self, min_quality: str = "B",
                           limit: int = 10) -> list[dict]:
        """获取可蒸馏的候选记忆（min_quality 以上）。

        蒸馏：将多条相似记忆合并为更高层级的抽象记忆。
        """
        min_score = _quality_to_score(min_quality)
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM debate_memories "
                    "WHERE score >= ? ORDER BY score DESC LIMIT ?",
                    (min_score, limit),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error("获取蒸馏候选失败: %s", e)
            return []

    # ── 7. healthcheck ──────────────────────────────────────

    def healthcheck(self) -> dict:
        """健康检查。"""
        try:
            with self._conn() as conn:
                conn.execute("SELECT 1 FROM debate_memories LIMIT 1")
            return {"ok": True, "db_path": self._db_path}
        except sqlite3.Error as e:
            return {"ok": False, "error": str(e), "db_path": self._db_path}

    # ============================================================
    # SPEC v1.2-rc1 §6 P1: CBR 案例表 + 策略权重表 + Elo 表
    # ============================================================

    # ── CBR 案例 ──────────────────────────────────────────────

    def add_cbr_case(
        self,
        topic: str,
        topic_type: str = "general",
        strategies_used: str = "[]",
        winner: str = "draw",
        bull_score: float = 0.0,
        bear_score: float = 0.0,
        effective_strategies: str = "[]",
        adaptation_hints: str = "[]",
    ) -> str | None:
        """添加 CBR 案例。"""
        case_id = f"CBR-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
        now = time.time()
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO debate_cbr_cases "
                    "(case_id, topic, topic_type, strategies_used, winner, "
                    "bull_score, bear_score, effective_strategies, "
                    "adaptation_hints, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (case_id, topic, topic_type, strategies_used, winner,
                     bull_score, bear_score, effective_strategies,
                     adaptation_hints, now),
                )
                conn.commit()
            return case_id
        except sqlite3.Error as e:
            logger.error("添加 CBR 案例失败: %s", e)
            return None

    def search_cbr_cases(
        self, query: str, top_k: int = 5,
        topic_type: str | None = None,
    ) -> list[dict]:
        """搜索 CBR 案例 (LIKE 模糊匹配)。"""
        pattern = f"%{query}%"
        try:
            with self._conn() as conn:
                if topic_type:
                    rows = conn.execute(
                        "SELECT * FROM debate_cbr_cases "
                        "WHERE topic LIKE ? AND topic_type = ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (pattern, topic_type, top_k),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM debate_cbr_cases "
                        "WHERE topic LIKE ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (pattern, top_k),
                    ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error("搜索 CBR 案例失败: %s", e)
            return []

    def cbr_case_count(self) -> int:
        """CBR 案例总数。"""
        try:
            with self._conn() as conn:
                return conn.execute(
                    "SELECT COUNT(*) FROM debate_cbr_cases"
                ).fetchone()[0]
        except sqlite3.Error:
            return 0

    # ── 策略权重 ──────────────────────────────────────────────

    def add_strategy_weight(
        self,
        strategy: str,
        topic_type: str,
        alpha: float = 1.0,
        beta: float = 1.0,
    ) -> bool:
        """添加或替换策略权重 (UPSERT)。"""
        now = time.time()
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO debate_strategy_weights "
                    "(strategy, topic_type, alpha, beta, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (strategy, topic_type, alpha, beta, now),
                )
                conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error("添加策略权重失败: %s", e)
            return False

    def get_strategy_weights(
        self, topic_type: str,
    ) -> list[dict]:
        """获取指定话题类型的所有策略权重。"""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM debate_strategy_weights "
                    "WHERE topic_type = ? ORDER BY alpha DESC",
                    (topic_type,),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error("获取策略权重失败: %s", e)
            return []

    def update_strategy_weight(
        self,
        strategy: str,
        topic_type: str,
        alpha: float,
        beta: float,
    ) -> bool:
        """更新策略权重 (如不存在则插入)。"""
        now = time.time()
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO debate_strategy_weights "
                    "(strategy, topic_type, alpha, beta, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (strategy, topic_type, alpha, beta, now),
                )
                conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error("更新策略权重失败: %s", e)
            return False

    # ── Persona Elo ───────────────────────────────────────────

    def add_elo(
        self,
        persona: str,
        elo: float = 1200.0,
        debates: int = 0,
    ) -> bool:
        """添加 Persona Elo 记录 (如不存在)。"""
        now = time.time()
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO debate_elo "
                    "(persona, elo, debates, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (persona, elo, debates, now),
                )
                conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error("添加 Elo 失败: %s", e)
            return False

    def get_elo(self, persona: str) -> dict | None:
        """获取 Persona Elo。"""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM debate_elo WHERE persona = ?",
                    (persona,),
                ).fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error("获取 Elo 失败: %s", e)
            return None

    def update_elo(
        self,
        persona: str,
        elo: float,
        debates: int,
    ) -> bool:
        """更新 Persona Elo (如不存在则插入)。"""
        now = time.time()
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO debate_elo "
                    "(persona, elo, debates, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (persona, elo, debates, now),
                )
                conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error("更新 Elo 失败: %s", e)
            return False
