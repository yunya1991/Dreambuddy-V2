#!/usr/bin/env python3
"""M1 指针型记忆索引 — 问题签名 → 项目 / 组件 / 文档锚点 / 入口文件:行。

记忆三形态里 M1 是最高优先级形态：只存"去哪找"，不存细节内容。
硬上限 150 条（CLAUDE.md 记忆准入标准）；超限必须抽象合并，禁止无声膨胀。

与 `memory_tree.py` 的分工：
    memory_tree  — 目录/章节级定位（自动生成，893 节点，无人工维护成本）
    memory_pointer— 问题级签名（人工攒出来的高频入口，≤150 条）

存储：`cognitive_memory.db` 的 `memory_pointers` 表（不新建库，不新建平行存储）。

用法:
    python memory_pointer_index.py stats
    python memory_pointer_index.py query "recall 命中不写回 access_count"
    python memory_pointer_index.py upsert --signature "recall 不写回" \
        --project 4-MEMORY --component cognitive_loop_entry.py \
        --module-path 4-MEMORY/9-工具与接口/cognitive_loop_entry.py:595 --apply
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from memory_tree import tokenize

_DB_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "cognitive_memory.db"
PIN_BUDGET = 150
NOTE_MAX = 120
SUMMARY_MAX = 120


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _open(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con


def ensure_table(con: sqlite3.Connection) -> None:
    """幂等建表（云/本地都可重复执行）。"""
    con.execute(
        "CREATE TABLE IF NOT EXISTS memory_pointers("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "signature TEXT NOT NULL UNIQUE,"
        "project TEXT,"
        "component TEXT,"
        "doc_anchor TEXT,"
        "module_path TEXT,"
        "keywords TEXT,"
        "note TEXT,"
        "hits INTEGER NOT NULL DEFAULT 0,"
        "created_at TEXT,"
        "updated_at TEXT,"
        "last_used_at INTEGER)"
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_pointers_project ON memory_pointers(project)")
    con.commit()


def _has_table(con: sqlite3.Connection) -> bool:
    """只读探测：查询路径**禁止**建表（本地生产库只读，CLAUDE.md 硬约束）。"""
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_pointers'"
    ).fetchone()
    return row is not None


def _normalize(signature: str) -> str:
    return " ".join((signature or "").strip().lower().split())


def upsert_pointer(
    db_path: str,
    signature: str,
    project: str = "",
    component: str = "",
    doc_anchor: str = "",
    module_path: str = "",
    keywords: str = "",
    note: str = "",
    dry_run: bool = True,
    budget: int = PIN_BUDGET,
) -> dict:
    """写入/更新一条指针。容量门：新增签名前先校验 ≤budget，超限 fail-loud。"""
    sig = _normalize(signature)
    if not sig:
        return {"ok": False, "error": "empty_signature"}
    if not Path(db_path).exists():
        return {"ok": False, "error": f"db_not_found: {db_path}"}

    con = _open(db_path)
    try:
        has_table = _has_table(con)
        row = (
            con.execute("SELECT * FROM memory_pointers WHERE signature=?", [sig]).fetchone()
            if has_table
            else None
        )
        count = (
            con.execute("SELECT count(*) FROM memory_pointers").fetchone()[0] if has_table else 0
        )
        if row is None and count >= budget:
            return {
                "ok": False,
                "error": "pin_budget_exceeded",
                "count": count,
                "budget": budget,
                "hint": "超限必须抽象合并旧指针（合并同类问题签名），禁止直接扩容",
            }
        payload = {
            "signature": sig,
            "project": project,
            "component": component,
            "doc_anchor": doc_anchor,
            "module_path": module_path,
            "keywords": keywords,
            "note": (note or "")[:NOTE_MAX],
            "updated_at": _now(),
        }
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "action": "update" if row else "insert",
                "count": count,
                "budget": budget,
                "pointer": payload,
            }
        ensure_table(con)
        if row is None:
            con.execute(
                "INSERT INTO memory_pointers(signature, project, component, doc_anchor, "
                "module_path, keywords, note, hits, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,0,?,?)",
                [
                    payload["signature"],
                    project,
                    component,
                    doc_anchor,
                    module_path,
                    keywords,
                    payload["note"],
                    payload["updated_at"],
                    payload["updated_at"],
                ],
            )
            action = "insert"
        else:
            con.execute(
                "UPDATE memory_pointers SET project=?, component=?, doc_anchor=?, module_path=?, "
                "keywords=?, note=?, updated_at=? WHERE signature=?",
                [
                    project,
                    component,
                    doc_anchor,
                    module_path,
                    keywords,
                    payload["note"],
                    payload["updated_at"],
                    sig,
                ],
            )
            action = "update"
        con.commit()
        return {
            "ok": True,
            "dry_run": False,
            "action": action,
            "count": count + (1 if action == "insert" else 0),
            "budget": budget,
        }
    finally:
        con.close()


def query_pointers(
    db_path: str, text: str, top_k: int = 5, min_score: float = 0.5, touch: bool = False
) -> dict:
    """按问题描述做确定性关键词匹配，命中即返回锚点（不读正文）。"""
    if not Path(db_path).exists():
        return {"ok": False, "error": f"db_not_found: {db_path}"}
    con = _open(db_path)
    try:
        if not _has_table(con):
            return {"ok": False, "degraded_reason": "pointer_index_empty", "next": "D3"}
        rows = con.execute("SELECT * FROM memory_pointers").fetchall()
        if not rows:
            return {"ok": False, "degraded_reason": "pointer_index_empty", "next": "D3"}
        q_tokens = set(tokenize(text))
        scored = []
        for r in rows:
            hay = " ".join(
                str(r[k] or "")
                for k in ("signature", "keywords", "project", "component", "doc_anchor")
            )
            h_tokens = set(tokenize(hay))
            if not q_tokens or not h_tokens:
                continue
            overlap = q_tokens & h_tokens
            if not overlap:
                continue
            score = len(overlap) / len(q_tokens)
            if score < min_score:
                continue
            scored.append((score, r))
        if not scored:
            return {"ok": False, "degraded_reason": "pointer_no_hit", "next": "D1/D3"}
        scored.sort(key=lambda x: (-x[0], -(x[1]["hits"] or 0)))
        picked = scored[:top_k]
        if touch:
            now = int(datetime.now(timezone.utc).timestamp())
            for _score, r in picked:
                con.execute(
                    "UPDATE memory_pointers SET hits=hits+1, last_used_at=? WHERE id=?",
                    [now, r["id"]],
                )
            con.commit()
        return {
            "ok": True,
            "degraded": False,
            "results": [
                {
                    "signature": r["signature"],
                    "project": r["project"],
                    "component": r["component"],
                    "doc_anchor": r["doc_anchor"],
                    "module_path": r["module_path"],
                    "summary": (r["note"] or r["signature"] or "")[:SUMMARY_MAX],
                    "score": round(score, 3),
                    "hits": r["hits"],
                }
                for score, r in picked
            ],
        }
    finally:
        con.close()


def stats_pointers(db_path: str, budget: int = PIN_BUDGET) -> dict:
    if not Path(db_path).exists():
        return {"ok": False, "error": f"db_not_found: {db_path}"}
    con = _open(db_path)
    try:
        if not _has_table(con):
            return {
                "ok": True,
                "count": 0,
                "budget": budget,
                "usage": "0%",
                "needs_merge": False,
                "by_project": {},
            }
        count = con.execute("SELECT count(*) FROM memory_pointers").fetchone()[0]
        projects = con.execute(
            "SELECT project, count(*) c FROM memory_pointers GROUP BY project ORDER BY c DESC"
        ).fetchall()
        return {
            "ok": True,
            "count": count,
            "budget": budget,
            "usage": f"{count / budget:.0%}",
            "needs_merge": count >= budget,
            "by_project": {r["project"] or "": r["c"] for r in projects},
        }
    finally:
        con.close()


def _cli(args) -> int:
    if args.command == "stats":
        out = stats_pointers(args.db, args.budget)
    elif args.command == "query":
        out = query_pointers(
            args.db, args.text, top_k=args.top_k, min_score=args.min_score, touch=args.touch
        )
    elif args.command == "upsert":
        out = upsert_pointer(
            args.db,
            signature=args.signature,
            project=args.project,
            component=args.component,
            doc_anchor=args.doc_anchor,
            module_path=args.module_path,
            keywords=args.keywords,
            note=args.note,
            dry_run=not args.apply,
            budget=args.budget,
        )
    elif args.command == "list":
        con = _open(args.db)
        try:
            if not _has_table(con):
                out = {"ok": True, "count": 0, "pointers": []}
            else:
                rows = con.execute(
                    "SELECT signature, project, component, module_path, hits FROM memory_pointers "
                    "ORDER BY hits DESC, id"
                ).fetchall()
                out = {"ok": True, "count": len(rows), "pointers": [dict(r) for r in rows]}
        finally:
            con.close()
    else:
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="M1 指针型记忆索引（≤150 条）")
    parser.add_argument("--db", default=str(_DB_DEFAULT), help="cognitive_memory.db 路径")
    parser.add_argument("--budget", type=int, default=PIN_BUDGET, help="容量上限（默认 150）")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("stats", help="容量与分布")
    sub.add_parser("list", help="列出全部指针")
    p_q = sub.add_parser("query", help="按问题描述查询指针")
    p_q.add_argument("text")
    p_q.add_argument("--top-k", type=int, default=5)
    p_q.add_argument("--min-score", type=float, default=0.5)
    p_q.add_argument("--touch", action="store_true", help="回写 hits（生产写，需云端执行）")
    p_u = sub.add_parser("upsert", help="写入/更新指针（默认 dry-run）")
    p_u.add_argument("--signature", required=True, help="问题签名（归一化后唯一）")
    p_u.add_argument("--project", default="")
    p_u.add_argument("--component", default="")
    p_u.add_argument("--doc-anchor", default="")
    p_u.add_argument("--module-path", default="")
    p_u.add_argument("--keywords", default="")
    p_u.add_argument("--note", default="", help=f"摘要（截断 {NOTE_MAX} 字）")
    p_u.add_argument("--apply", action="store_true", help="实际写入（缺省仅 dry-run）")

    raise SystemExit(_cli(parser.parse_args()))
