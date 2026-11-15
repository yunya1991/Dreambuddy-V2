#!/usr/bin/env python3
"""DB 级指纹去重单测：指纹分组 / 代表选择与合并 / S 保护 / 轨迹 scope / 限批。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from consolidation_engine import dedupe_memories  # noqa: E402

NOW = "2026-11-16T00:00:00+00:00"


def _mkdb(tmp_path: Path, rows: list[tuple]) -> Path:
    """rows: (id, content, quality, verify_count, access_count, tags, source)"""
    db = tmp_path / "mem.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE memories(id TEXT PRIMARY KEY, content TEXT, quality_level TEXT, "
        "verify_count INTEGER, access_count INTEGER, last_used_at INTEGER, created_at TEXT, "
        "updated_at TEXT, tags TEXT, source TEXT)"
    )
    for mid, content, quality, verify, access, tags, source in rows:
        con.execute(
            "INSERT INTO memories(id, content, quality_level, verify_count, access_count, "
            "last_used_at, created_at, updated_at, tags, source) VALUES (?,?,?,?,?,NULL,?,?,?,?)",
            [mid, content, quality, verify, access, NOW, NOW, tags, source],
        )
    con.commit()
    con.close()
    return db


class _FakeVM:
    def __init__(self, storage_path=None, allow_degraded=False):
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
        # 组 1：同内容 3 条，A 级应胜出并合并统计
        ("m1", "同一个教训：止损必须前置", "C", 0, 0, '["a"]', "mcp"),
        ("m2", "同一个教训：止损必须前置", "A", 2, 3, '["b"]', "mcp"),
        ("m3", "同一个教训：止损必须前置", "C", 1, 0, '["c"]', "mcp"),
        # 组 2：S 保护（两条 S 不得互删）
        ("s1", "S 级公理不能删", "S", 0, 0, "[]", "mcp"),
        ("s2", "S 级公理不能删", "S", 0, 0, "[]", "mcp"),
        # 组 3：轨迹类重复（默认 scope 排除）
        ("r1", "[RAG检索] 同一查询", "C", 0, 0, "[]", "rag-bridge"),
        ("r2", "[RAG检索] 同一查询", "C", 0, 0, "[]", "rag-bridge"),
        # 唯一内容
        ("u1", "独一无二的内容", "B", 0, 0, "[]", "mcp"),
    ]


def _count(db: Path, sql: str) -> int:
    con = sqlite3.connect(db)
    try:
        return con.execute(sql).fetchone()[0]
    finally:
        con.close()


def test_dry_run_reports_only(tmp_path):
    db = _mkdb(tmp_path, _rows())
    report = dedupe_memories(str(db), dry_run=True)
    assert report["ok"] and report["dry_run"]
    assert report["rows_scanned"] == 6, "默认排除 2 条轨迹"
    assert report["groups_duplicate"] == 2
    assert report["duplicates"] == 3, "组1 去 2 条 + 组2 S 保护不计入"
    assert report["skipped_s_protected"] == 1
    assert report["deleted"] == 0
    assert _count(db, "SELECT count(*) FROM memories") == 8


def test_apply_merges_and_deletes(tmp_path, fake_vm):
    db = _mkdb(tmp_path, _rows())
    report = dedupe_memories(str(db), dry_run=False)
    assert report["merged"] == 1 and report["deleted"] == 2
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rep = con.execute("SELECT * FROM memories WHERE id='m2'").fetchone()
    left = con.execute("SELECT id FROM memories ORDER BY id").fetchall()
    con.close()
    assert [r[0] for r in left] == ["m2", "r1", "r2", "s1", "s2", "u1"]
    assert rep["quality_level"] == "A", "代表质量取组内最高"
    assert rep["verify_count"] == 3 and rep["access_count"] == 3, "统计量求和而非取最大"
    assert set(eval(rep["tags"])) == {"a", "b", "c"}, "tags 取并集"


def test_s_grade_never_deleted(tmp_path, fake_vm):
    db = _mkdb(tmp_path, _rows())
    dedupe_memories(str(db), dry_run=False)
    assert _count(db, "SELECT count(*) FROM memories WHERE id IN ('s1','s2')") == 2


def test_trajectory_excluded_by_default_included_on_demand(tmp_path, fake_vm):
    db = _mkdb(tmp_path, _rows())
    assert dedupe_memories(str(db), dry_run=True)["rows_scanned"] == 6
    report = dedupe_memories(str(db), dry_run=True, include_trajectory=True)
    assert report["rows_scanned"] == 8
    assert report["groups_duplicate"] == 3


def test_limit_processes_biggest_group_first(tmp_path, fake_vm):
    db = _mkdb(tmp_path, _rows())
    report = dedupe_memories(str(db), dry_run=False, limit=1)
    assert report["groups_batch"] == 1 and report["deleted"] == 2
    assert _count(db, "SELECT count(*) FROM memories WHERE id='r1'") == 1, "轨迹组未被处理"


def test_keep_max_two(tmp_path):
    db = _mkdb(tmp_path, _rows())
    report = dedupe_memories(str(db), dry_run=True, keep_max=2)
    assert report["duplicates"] == 1, "组1 保留 2 条只多 1 条"
