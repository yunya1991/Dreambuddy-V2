#!/usr/bin/env python3
"""DB 级分级 TTL 单测：分级判据 / 白名单 / 两阶段淘汰 / 痕迹归位 / 容量门。"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory_ttl_manager as ttl  # noqa: E402
from memory_tree import MemoryTree  # noqa: E402

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
SCOPE = ("rag-bridge", "l0.scheduler", "l1_router")


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000000+00:00")


def _mkdb(tmp_path: Path, rows: list[tuple]) -> Path:
    """rows: (id, quality, source, days_ago, access_count, content)"""
    db = tmp_path / "mem.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE memories(id TEXT PRIMARY KEY, content TEXT, vector BLOB, "
        "quality_level TEXT, confidence REAL, tags TEXT, memory_type TEXT, source TEXT, "
        "created_at TEXT, updated_at TEXT, verify_count INTEGER, level TEXT, "
        "known_gaps TEXT, observations TEXT, external_id TEXT, access_count INTEGER, "
        "last_used_at INTEGER)"
    )
    con.execute("CREATE TABLE vec_memories(rowid INTEGER PRIMARY KEY, memory_id TEXT)")
    import hashlib

    for mid, quality, source, days, ac, content in rows:
        con.execute(
            "INSERT INTO memories(id, content, quality_level, source, created_at, "
            "access_count, last_used_at, tags) VALUES (?,?,?,?,?,?,NULL,'[]')",
            [mid, content, quality, source, _iso(days), ac],
        )
        con.execute(
            "INSERT INTO vec_memories(rowid, memory_id) VALUES (?,?)",
            [int(hashlib.md5(mid.encode()).hexdigest()[:12], 16), mid],
        )
    con.commit()
    con.close()
    return db


def _count(db: Path, sql: str, params=()) -> int:
    con = sqlite3.connect(db)
    try:
        return con.execute(sql, params).fetchone()[0]
    finally:
        con.close()


class _FakeVM:
    """替代 VectorMemoryInterface：只删 memories 行，验证「统一级联删除」调用点。"""

    def __init__(self, storage_path=None, allow_degraded=False):
        self.path = storage_path
        self.db = sqlite3.connect(storage_path)

    def delete(self, memory_id: str) -> bool:
        self.db.execute("DELETE FROM memories WHERE id=?", [memory_id])
        self.db.commit()
        return True

    def close(self) -> None:
        self.db.close()


@pytest.fixture()
def fake_vm(monkeypatch):
    import vector_memory_interface

    monkeypatch.setattr(vector_memory_interface, "VectorMemoryInterface", _FakeVM)


def _rows() -> list[tuple]:
    return [
        ("c_old", "C", "rag-bridge", 8, 0, "RAG 日志 旧"),
        ("c_new", "C", "rag-bridge", 3, 0, "RAG 日志 新"),
        ("c_used", "C", "rag-bridge", 30, 2, "RAG 日志 被用过"),
        ("b_old", "B", "rag-bridge", 15, 0, "B 级 旧"),
        ("b_young", "B", "rag-bridge", 8, 0, "B 级 未到 14 天"),
        ("real", "C", "mcp", 60, 0, "真实教训 非白名单"),
        ("s_keep", "S", "rag-bridge", 400, 0, "S 级 永不淘汰"),
    ]


def test_dry_run_counts_only(tmp_path):
    db = _mkdb(tmp_path, _rows())
    before = _count(db, "SELECT count(*) FROM memories")
    report = ttl.run_db_ttl_cycle(db_path=db, dry_run=True, scope=SCOPE, now=NOW)
    assert report["stage1"]["candidates"] == 2, "仅 c_old + b_old 同时满足分级 TTL 与未使用条件"
    assert report["stage1"]["promoted"] == 0
    assert report["pending_total"] == 0
    assert _count(db, "SELECT count(*) FROM memories") == before


def test_whitelist_and_usage_exclusion(tmp_path):
    db = _mkdb(tmp_path, _rows())
    con = ttl._open_db(db)
    cands = ttl._iter_expired(con, SCOPE, NOW)
    ids = {c["id"] for c in cands}
    con.close()
    assert ids == {"c_old", "b_old"}, "非白名单 / 已使用 / 未到期 / S 级 均不得入选"


def test_stage1_keeps_rows_and_removes_index(tmp_path):
    db = _mkdb(tmp_path, _rows())
    report = ttl.run_db_ttl_cycle(db_path=db, dry_run=False, scope=SCOPE, now=NOW, stage="1")
    assert report["stage1"]["promoted"] == 2
    assert report["pending_total"] == 2
    assert _count(db, "SELECT count(*) FROM memories") == 7, "阶段一只移索引，不删行"
    assert _count(db, "SELECT count(*) FROM vec_memories") == 5, "c_old/b_old 已移出索引"


def _tree() -> MemoryTree:
    nodes = {
        "18-数据获取中心": {
            "level": 1,
            "name": "18-数据获取中心",
            "parent": None,
            "keywords": ["数据获取"],
            "doc_anchors": ["18-数据获取中心/README.md"],
            "module_paths": ["18-数据获取中心"],
            "origin": "auto",
        },
        "18-数据获取中心/backfill": {
            "level": 2,
            "name": "backfill",
            "parent": "18-数据获取中心",
            "keywords": ["backfill"],
            "doc_anchors": [],
            "module_paths": ["18-数据获取中心/backfill"],
            "origin": "auto",
        },
        "18-数据获取中心/backfill/新闻快讯回填.md": {
            "level": 3,
            "name": "新闻快讯回填",
            "parent": "18-数据获取中心/backfill",
            "keywords": ["新闻快讯", "回填"],
            "doc_anchors": ["18-数据获取中心/backfill/新闻快讯回填.md"],
            "module_paths": [],
            "origin": "auto",
        },
    }
    return MemoryTree(nodes)


def test_stage2_after_grace_purges_without_trace_for_trajectory(tmp_path, fake_vm):
    """轨迹来源（rag-bridge 等）不留痕：阶段二只物理删除，不写 memory_traces（G11）。"""
    db = _mkdb(tmp_path, _rows())
    ttl.run_db_ttl_cycle(db_path=db, dry_run=False, scope=SCOPE, now=NOW, stage="1")
    later = NOW + timedelta(days=ttl.TTL_GRACE_DAYS + 1)
    report = ttl.run_db_ttl_cycle(
        db_path=db, dry_run=False, scope=SCOPE, now=later, tree=_tree(), stage="2"
    )
    assert report["stage2"]["eligible"] == 2
    assert _count(db, "SELECT count(*) FROM memories WHERE id IN ('c_old','b_old')") == 0
    assert _count(db, "SELECT count(*) FROM memory_traces") == 0
    assert report["stage2"]["trace_skipped_trajectory"] == 2
    assert report["pending_total"] == 0


def test_stage2_after_grace_traces_and_purges(tmp_path, fake_vm):
    rows = [("m_old", "C", "manual", 8, 0, "手工经验 幂等写入")]
    db = _mkdb(tmp_path, rows)
    scope = ("manual",)
    ttl.run_db_ttl_cycle(db_path=db, dry_run=False, scope=scope, now=NOW, stage="1")
    later = NOW + timedelta(days=ttl.TTL_GRACE_DAYS + 1)
    report = ttl.run_db_ttl_cycle(
        db_path=db, dry_run=False, scope=scope, now=later, tree=_tree(), stage="2"
    )
    assert report["stage2"]["eligible"] == 1
    assert _count(db, "SELECT count(*) FROM memories WHERE id='m_old'") == 0
    assert _count(db, "SELECT count(*) FROM memory_traces") == 1
    con = sqlite3.connect(db)
    from sqlite3 import Row

    con.row_factory = Row
    trace = con.execute("SELECT * FROM memory_traces LIMIT 1").fetchone()
    con.close()
    assert trace["project"] == "_orphan" or trace["project"] == "18-数据获取中心"
    assert len(trace["snippet_200"]) <= 200
    assert trace["keywords"], "痕迹必须保留关键词"
    assert report["pending_total"] == 0


def test_stage2_resolves_leaf_node_from_tree(tmp_path, fake_vm):
    rows = [("c1", "C", "manual", 8, 0, "新闻快讯 回填 幂等写入")]
    db = _mkdb(tmp_path, rows)
    ttl.run_db_ttl_cycle(db_path=db, dry_run=False, scope=("manual",), now=NOW, stage="1")
    later = NOW + timedelta(days=ttl.TTL_GRACE_DAYS + 1)
    ttl.run_db_ttl_cycle(
        db_path=db, dry_run=False, scope=("manual",), now=later, tree=_tree(), stage="2"
    )
    con = sqlite3.connect(db)
    project, node_path = con.execute("SELECT project, node_path FROM memory_traces").fetchone()
    con.close()
    assert project == "18-数据获取中心"
    assert node_path == "18-数据获取中心/backfill/新闻快讯回填.md", "痕迹必须挂到树梢而非乱堆"


def test_trace_leaf_cap(tmp_path, fake_vm, monkeypatch):
    monkeypatch.setattr(ttl, "TRACE_PER_LEAF", 2)
    rows = [(f"c{i}", "C", "manual", 8, 0, f"新闻快讯 回填 第{i}条") for i in range(4)]
    db = _mkdb(tmp_path, rows)
    ttl.run_db_ttl_cycle(db_path=db, dry_run=False, scope=("manual",), now=NOW, stage="1")
    later = NOW + timedelta(days=ttl.TTL_GRACE_DAYS + 1)
    ttl.run_db_ttl_cycle(
        db_path=db, dry_run=False, scope=("manual",), now=later, tree=_tree(), stage="2"
    )
    assert _count(db, "SELECT count(*) FROM memory_traces") == 2


def test_a_cap_deletes_oldest_within_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(ttl, "A_CAP", 3)  # A+S 共 4 条 → 超 1 条
    rows = [
        ("a1", "A", "rag-bridge", 300, 1, "A 最旧"),
        ("a2", "A", "rag-bridge", 200, 5, "A 次旧"),
        ("a3", "A", "rag-bridge", 100, 9, "A 最新"),
        ("s1", "S", "rag-bridge", 400, 0, "S 不淘汰"),
    ]
    db = _mkdb(tmp_path, rows)
    con = ttl._open_db(db)
    overflow = ttl._iter_a_overflow(con, SCOPE, NOW)
    con.close()
    assert [r["id"] for r in overflow] == ["a1"], "超上限时删最旧/最低频，S 永不动"
