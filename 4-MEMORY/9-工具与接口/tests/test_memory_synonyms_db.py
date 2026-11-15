#!/usr/bin/env python3
"""DB 级近义合并单测：双门（余弦 + 标识符骨架）/ B 级地板 / S 保护 / 维度门 / 轨迹 scope。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from consolidation_engine import merge_synonyms  # noqa: E402

NOW = "2026-11-16T00:00:00+00:00"
DIM = 512


def _vec(base: int = 0, jitter: float = 0.0) -> bytes:
    """构造近似共线的 512 维向量（jitter 很小时余弦趋近 1）。"""
    v = np.zeros(DIM, dtype=np.float32)
    v[base % DIM] = 1.0
    if jitter:
        v[(base + 1) % DIM] = jitter
    return v.tobytes()


def _mkdb(tmp_path: Path, rows: list[tuple]) -> Path:
    """rows: (id, content, quality, verify_count, access_count, tags, source, vector)"""
    db = tmp_path / "mem.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE memories(id TEXT PRIMARY KEY, content TEXT, quality_level TEXT, "
        "verify_count INTEGER, access_count INTEGER, last_used_at INTEGER, created_at TEXT, "
        "updated_at TEXT, tags TEXT, source TEXT, vector BLOB)"
    )
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO meta(key, value) VALUES('embed_dim', ?)", [str(DIM)])
    for mid, content, quality, verify, access, tags, source, vector in rows:
        con.execute(
            "INSERT INTO memories(id, content, quality_level, verify_count, access_count, "
            "last_used_at, created_at, updated_at, tags, source, vector) "
            "VALUES (?,?,?,?,?,NULL,?,?,?,?,?)",
            [mid, content, quality, verify, access, NOW, NOW, tags, source, vector],
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
        # 组 1：同一事实的两种写法（标识符骨架一致，仅语序不同）→ 应合并
        ("n1", "fix a.py b.py 步骤1 步骤2 验证✓", "C", 0, 0, '["x"]', "mcp", _vec(0)),
        ("n2", "步骤1 步骤2 fix a.py b.py 验证✓", "C", 1, 0, '["y"]', "mcp", _vec(0, 0.001)),
        # 组 2：余弦极高但标识符不同（Phase2 vs Phase6）→ 硬门拒绝合并
        ("d1", "feat Phase2 Task1 wrapper 已验证", "B", 0, 0, "[]", "mcp", _vec(1)),
        ("d2", "feat Phase6 Task1 wrapper 已验证", "B", 0, 0, "[]", "mcp", _vec(1, 0.001)),
        # 组 3：S 保护
        ("s1", "S 公理 keep a.py 验证✓", "S", 0, 0, "[]", "mcp", _vec(2)),
        ("s2", "S 公理 keep a.py 验证✓ 复述", "S", 0, 0, "[]", "mcp", _vec(2, 0.001)),
        # 维度不符（256 维）→ 不参与
        (
            "w1",
            "fix a.py b.py 步骤1 步骤2 验证✓",
            "C",
            0,
            0,
            "[]",
            "mcp",
            np.zeros(256, np.float32).tobytes(),
        ),
        # 轨迹类默认排除
        ("r1", "[RAG检索] fix a.py 步骤1 步骤2 验证✓", "C", 0, 0, "[]", "rag-bridge", _vec(3)),
        (
            "r2",
            "[RAG检索] 步骤1 步骤2 fix a.py 验证✓",
            "C",
            0,
            0,
            "[]",
            "rag-bridge",
            _vec(3, 0.001),
        ),
    ]


def _count(db: Path, sql: str) -> int:
    con = sqlite3.connect(db)
    try:
        return con.execute(sql).fetchone()[0]
    finally:
        con.close()


def test_dry_run_reports_only(tmp_path):
    db = _mkdb(tmp_path, _rows())
    report = merge_synonyms(str(db), dry_run=True)
    assert report["ok"] and report["dry_run"]
    assert report["rows_scanned"] == 7, "9 条中 2 条轨迹被默认排除"
    assert report["rows_vector_usable"] == 6, "256 维那条被维度门排除"
    assert report["skipped_dim_mismatch"] == 1
    assert report["exact_duplicates_excluded"] == 0
    assert report["groups_duplicate"] == 2, "组 1 命中 + 组 3（S 保护，仅计数不执行）"
    assert report["skipped_s_protected"] == 1
    assert report["deleted"] == 0
    assert _count(db, "SELECT count(*) FROM memories") == 9


def test_identifier_guard_blocks_distinct_facts(tmp_path):
    db = _mkdb(tmp_path, _rows())
    report = merge_synonyms(str(db), dry_run=True)
    assert report["pairs_candidate"] >= 1, "余弦门确实放行了高相似对"
    keeps = {s["keep"] for s in report.get("samples", [])}
    assert "d1" not in keeps and "d2" not in keeps, "只差标识符的不同事实不得合并"


def test_apply_merges_with_b_floor(tmp_path, fake_vm):
    db = _mkdb(tmp_path, _rows())
    report = merge_synonyms(str(db), dry_run=False)
    assert report["merged"] == 1 and report["deleted"] == 1
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rep = con.execute("SELECT * FROM memories WHERE id='n2'").fetchone()
    left = {r[0] for r in con.execute("SELECT id FROM memories").fetchall()}
    con.close()
    assert left == {"n2", "d1", "d2", "s1", "s2", "w1", "r1", "r2"}, "n2 verify 更多当选代表"
    assert rep["quality_level"] == "B", "近义合并后质量不低于 B"
    assert rep["verify_count"] == 1, "统计量求和"
    assert set(eval(rep["tags"])) == {"x", "y"}, "tags 并集"


def test_s_grade_group_protected(tmp_path, fake_vm):
    db = _mkdb(tmp_path, _rows())
    merge_synonyms(str(db), dry_run=False)
    assert _count(db, "SELECT count(*) FROM memories WHERE id IN ('s1','s2')") == 2


def test_threshold_floor_rejects_dangerous_config(tmp_path):
    db = _mkdb(tmp_path, _rows())
    report = merge_synonyms(str(db), dry_run=True, threshold=0.5)
    assert report["ok"] is False and "threshold_too_low" in report["error"]


def test_trajectory_excluded_by_default(tmp_path):
    db = _mkdb(tmp_path, _rows())
    assert merge_synonyms(str(db), dry_run=True)["rows_scanned"] == 7
    report = merge_synonyms(str(db), dry_run=True, include_trajectory=True)
    assert report["rows_scanned"] == 9
