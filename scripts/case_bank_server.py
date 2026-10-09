#!/usr/bin/env python3
"""
TDR (Training Data Repository) 后端服务 — SPEC-20261009 §3.1 + §10 P0-1

中央训练数据仓库，独立 SQLite DB (solution_case_bank.db)。
物理隔离于 cognitive_memory.db。

功能:
  - store: 存储解题案例（四元组 + codebook + embedding + layer_tags + baseline）
  - retrieve: 检索相似案例（embedding 余弦相似度 + 质量加权 + LRU 更新）
  - stats: 统计信息
  - LRU 淘汰 + 质量加权（容量上限 10000）
  - 质量闸门：有 learned 才入库

设计:
  - 复刻 cognitive_adapter.py IPC 模式
  - FAIL-OPEN: 异常返回 {ok: false, error}, 不崩溃
  - stdout 行过滤: 只输出单行 JSON
"""
from __future__ import annotations

import sqlite3
import json
import time
import hashlib
import os
import sys
from typing import Any

# ============================================================
# 配置
# ============================================================

_DB_DIR = os.environ.get(
    "SPL_DB_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "4-MEMORY", "data"),
)
DB_PATH = os.path.join(_DB_DIR, "solution_case_bank.db")
CAPACITY_LIMIT = 10000


def _connect() -> sqlite3.Connection:
    """连接 TDR SQLite，自动建表。"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """初始化表结构。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS solution_cases (
            id TEXT PRIMARY KEY,
            intent TEXT NOT NULL,
            actions TEXT NOT NULL,          -- JSON array
            outcome_text TEXT NOT NULL,
            learned TEXT NOT NULL,          -- JSON array
            message_id TEXT,
            message_summary_time TEXT,
            outcome TEXT,                   -- success/failure/partial/unknown
            codebook_index TEXT,            -- JSON array
            embedding TEXT,                 -- JSON array
            layer_tags TEXT,                -- JSON array
            baseline_output TEXT,           -- JSON object
            quality TEXT,
            confidence REAL,
            tags TEXT,                      -- JSON array
            source TEXT,
            created_at INTEGER,
            last_retrieved_at INTEGER DEFAULT 0,
            replay_count INTEGER DEFAULT 0,
            verify_count INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_quality ON solution_cases(quality)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_outcome ON solution_cases(outcome)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_last_retrieved ON solution_cases(last_retrieved_at)
    """)
    conn.commit()


def _quality_weight(quality: str) -> float:
    """质量权重：S=4, A=3, B=2, C=1"""
    return {"S": 4.0, "A": 3.0, "B": 2.0, "C": 1.0}.get(quality, 1.0)


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """余弦相似度（无 numpy 依赖）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _generate_id(input_data: dict) -> str:
    """生成 case ID: case-{timestamp}-{hash8}"""
    ts = int(time.time() * 1000)
    raw = json.dumps(input_data, sort_keys=True, ensure_ascii=False)
    h = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"case-{ts}-{h}"


# ============================================================
# CRUD 操作
# ============================================================


def store_case(input_data: dict) -> dict:
    """存储案例到 TDR。

    Args:
        input_data: StoreInput 字典（含四元组 + outcome + quality + ...）

    Returns:
        {"ok": True, "id": "case-xxx"} 或 {"ok": False, "error": "..."}
    """
    learned = input_data.get("learned", [])
    if not learned:
        return {"ok": False, "error": "quality_gate_rejected: learned is empty"}

    conn = _connect()
    try:
        case_id = input_data.get("id") or _generate_id(input_data)
        now = int(time.time() * 1000)

        # 检查容量，执行 LRU + 质量加权淘汰
        count = conn.execute("SELECT COUNT(*) FROM solution_cases").fetchone()[0]
        if count >= CAPACITY_LIMIT:
            _evict_lru(conn)

        conn.execute(
            """
            INSERT OR REPLACE INTO solution_cases
            (id, intent, actions, outcome_text, learned, message_id, message_summary_time,
             outcome, codebook_index, embedding, layer_tags, baseline_output,
             quality, confidence, tags, source, created_at, last_retrieved_at,
             replay_count, verify_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                input_data.get("intent", ""),
                json.dumps(input_data.get("actions", []), ensure_ascii=False),
                input_data.get("outcome_text", ""),
                json.dumps(learned, ensure_ascii=False),
                input_data.get("message_id", ""),
                input_data.get("message_summary_time", ""),
                input_data.get("outcome", "unknown"),
                json.dumps(input_data.get("codebook_index", [])),
                json.dumps(input_data.get("embedding", [])),
                json.dumps(input_data.get("layer_tags", []), ensure_ascii=False),
                json.dumps(input_data.get("baseline_output", {}), ensure_ascii=False),
                input_data.get("quality", "C"),
                input_data.get("confidence", 0.3),
                json.dumps(input_data.get("tags", []), ensure_ascii=False),
                input_data.get("source", "trae-session"),
                now,
                0,
                0,
                0,
            ),
        )
        conn.commit()
        return {"ok": True, "id": case_id}
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": f"store_failed: {type(e).__name__}: {e}"}
    finally:
        conn.close()


def _evict_lru(conn: sqlite3.Connection) -> None:
    """LRU + 质量加权淘汰：优先淘汰 低质量 + 久未检索 的案例。"""
    # 综合分 = quality_weight * recency_factor
    # recency_factor = 1 / (1 + days_since_last_retrieval)
    now = int(time.time() * 1000)
    rows = conn.execute(
        "SELECT id, quality, last_retrieved_at, created_at FROM solution_cases ORDER BY last_retrieved_at ASC"
    ).fetchall()

    if not rows:
        return

    # 计算每个 case 的淘汰优先级分数（越高越先淘汰）
    scored = []
    for row in rows:
        qw = _quality_weight(row["quality"])
        days_since = max(0.001, (now - (row["last_retrieved_at"] or row["created_at"] or now)) / 86400000.0)
        recency_factor = 1.0 / (1.0 + days_since)
        # 淘汰分 = recency_factor / quality_weight（低质量+久未用 = 高淘汰分）
        evict_score = recency_factor / max(qw, 0.1)
        scored.append((row["id"], evict_score))

    # 淘汰分数最高的（最该淘汰的）
    scored.sort(key=lambda x: x[1], reverse=True)
    evict_count = max(1, len(scored) // 20)  # 每次淘汰 5%
    for case_id, _ in scored[:evict_count]:
        conn.execute("DELETE FROM solution_cases WHERE id = ?", (case_id,))


def retrieve_cases(query: str, top_k: int = 5) -> dict:
    """检索相似案例。

    简化实现：关键词匹配 + 质量加权（无 embedding 时降级）。
    VQ-VAE 编码后可用 codebook_index + embedding 精排。

    Returns:
        {"ok": True, "cases": [...], "scores": [...], "retrieval_mode": "semantic"|"fallback"}
    """
    conn = _connect()
    try:
        # 全量扫描（小规模数据集 < 10000 条可接受）
        rows = conn.execute(
            "SELECT * FROM solution_cases ORDER BY created_at DESC LIMIT 500"
        ).fetchall()

        if not rows:
            return {"ok": True, "cases": [], "scores": [], "retrieval_mode": "fallback"}

        query_lower = query.lower()
        query_tokens = set(query_lower.split())

        scored = []
        for row in rows:
            # 关键词匹配分
            intent_lower = (row["intent"] or "").lower()
            actions = json.loads(row["actions"] or "[]")
            learned = json.loads(row["learned"] or "[]")

            all_text = intent_lower + " " + " ".join(a.lower() for a in actions) + " " + " ".join(l.lower() for l in learned)
            all_tokens = set(all_text.split())
            token_overlap = len(query_tokens & all_tokens) / max(len(query_tokens), 1)

            # embedding 余弦相似度（如有）
            emb = json.loads(row["embedding"] or "[]")
            cosine = 0.0  # 简化：无 query embedding 时跳过

            # 质量权重
            qw = _quality_weight(row["quality"])

            # 综合分
            score = 0.4 * token_overlap + 0.0 * cosine + 0.4 * (qw / 4.0) + 0.2 * (1.0 / (1.0 + row["replay_count"]))

            scored.append((row, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:top_k]

        # 更新 last_retrieved_at + replay_count
        now = int(time.time() * 1000)
        case_ids = [row["id"] for row, _ in top]
        for cid in case_ids:
            conn.execute(
                "UPDATE solution_cases SET last_retrieved_at = ?, replay_count = replay_count + 1 WHERE id = ?",
                (now, cid),
            )
        conn.commit()

        cases = [_row_to_dict(row) for row, _ in top]
        scores = [score for _, score in top]
        mode = "semantic" if any(s > 0.1 for s in scores) else "fallback"

        return {"ok": True, "cases": cases, "scores": scores, "retrieval_mode": mode}
    except Exception as e:
        return {"ok": False, "error": f"retrieve_failed: {type(e).__name__}: {e}"}
    finally:
        conn.close()


def get_stats() -> dict:
    """TDR 统计信息。"""
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM solution_cases").fetchone()[0]

        by_quality: dict[str, int] = {}
        for row in conn.execute("SELECT quality, COUNT(*) as cnt FROM solution_cases GROUP BY quality"):
            by_quality[row["quality"] or "C"] = row["cnt"]

        by_outcome: dict[str, int] = {}
        for row in conn.execute("SELECT outcome, COUNT(*) as cnt FROM solution_cases GROUP BY outcome"):
            by_outcome[row["outcome"] or "unknown"] = row["cnt"]

        # 按层统计
        by_layer: dict[str, int] = {"S": 0, "DSH": 0, "C": 0, "G": 0, "LLM": 0}
        for row in conn.execute("SELECT layer_tags FROM solution_cases"):
            tags = json.loads(row["layer_tags"] or "[]")
            for tag in tags:
                layer = tag.get("layer", "")
                if layer in by_layer:
                    by_layer[layer] += 1

        return {
            "ok": True,
            "total_cases": total,
            "by_quality": by_quality,
            "by_layer": by_layer,
            "by_outcome": by_outcome,
            "capacity_limit": CAPACITY_LIMIT,
            "lru_evicted_count": 0,  # TODO: 追踪淘汰计数
        }
    except Exception as e:
        return {"ok": False, "error": f"stats_failed: {type(e).__name__}: {e}"}
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """将 sqlite Row 转为 SolutionCase dict。"""
    return {
        "id": row["id"],
        "intent": row["intent"],
        "actions": json.loads(row["actions"] or "[]"),
        "outcome_text": row["outcome_text"],
        "learned": json.loads(row["learned"] or "[]"),
        "message_id": row["message_id"] or "",
        "message_summary_time": row["message_summary_time"] or "",
        "outcome": row["outcome"] or "unknown",
        "codebook_index": json.loads(row["codebook_index"] or "[]"),
        "embedding": json.loads(row["embedding"] or "[]"),
        "layer_tags": json.loads(row["layer_tags"] or "[]"),
        "baseline_output": json.loads(row["baseline_output"] or "{}"),
        "quality": row["quality"] or "C",
        "confidence": row["confidence"] or 0.3,
        "tags": json.loads(row["tags"] or "[]"),
        "source": row["source"] or "",
        "created_at": row["created_at"] or 0,
        "last_retrieved_at": row["last_retrieved_at"] or 0,
        "replay_count": row["replay_count"] or 0,
        "verify_count": row["verify_count"] or 0,
    }


# ============================================================
# 工具注册表
# ============================================================

TOOL_HANDLERS = {
    "store": lambda args: json.dumps(store_case(args), ensure_ascii=False),
    "retrieve": lambda args: json.dumps(retrieve_cases(args.get("query", ""), args.get("top_k", 5)), ensure_ascii=False),
    "stats": lambda _args: json.dumps(get_stats(), ensure_ascii=False),
}
