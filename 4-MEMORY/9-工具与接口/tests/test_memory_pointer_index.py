#!/usr/bin/env python3
"""M1 指针索引单测：容量门 / 签名幂等 / 查询命中与降级 / 摘要截断。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_pointer_index import (  # noqa: E402
    NOTE_MAX,
    query_pointers,
    stats_pointers,
    upsert_pointer,
)


def _mkdb(tmp_path: Path) -> Path:
    db = tmp_path / "mem.db"
    sqlite3.connect(db).close()
    return db


def test_upsert_dry_run_does_not_write(tmp_path):
    db = _mkdb(tmp_path)
    rep = upsert_pointer(str(db), "recall 不写回 access_count", dry_run=True)
    assert rep["ok"] and rep["dry_run"] and rep["action"] == "insert"
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "memory_pointers" not in tables, "dry-run 连建表都不允许（本地生产库只读）"


def test_upsert_is_idempotent_by_signature(tmp_path):
    db = _mkdb(tmp_path)
    upsert_pointer(str(db), "Recall 不写回", project="4-MEMORY", dry_run=False)
    rep = upsert_pointer(str(db), "recall   不写回", module_path="a.py:1", dry_run=False)
    assert rep["action"] == "update" and rep["count"] == 1, "归一化后签名相同即更新"


def test_budget_gate_fail_loud(tmp_path):
    db = _mkdb(tmp_path)
    for i in range(2):
        assert upsert_pointer(str(db), f"问题{i}", dry_run=False, budget=2)["ok"]
    rep = upsert_pointer(str(db), "问题3", dry_run=False, budget=2)
    assert rep["ok"] is False and rep["error"] == "pin_budget_exceeded"
    assert "抽象合并" in rep["hint"]
    assert stats_pointers(str(db), budget=2)["needs_merge"] is True


def test_query_hit_returns_anchor(tmp_path):
    db = _mkdb(tmp_path)
    upsert_pointer(
        str(db),
        "recall 命中不写回 access_count",
        project="4-MEMORY",
        module_path="4-MEMORY/9-工具与接口/cognitive_loop_entry.py:595",
        keywords="recall access_count 写回",
        dry_run=False,
    )
    rep = query_pointers(str(db), "recall 命中后没有写回 access_count")
    assert rep["ok"] and len(rep["results"]) == 1
    hit = rep["results"][0]
    assert hit["module_path"].endswith("cognitive_loop_entry.py:595")
    assert len(hit["summary"]) <= 120


def test_query_miss_is_degraded_not_empty(tmp_path):
    db = _mkdb(tmp_path)
    upsert_pointer(str(db), "完全无关的签名", keywords="alpha beta", dry_run=False)
    rep = query_pointers(str(db), "zzz yyy")
    assert rep["ok"] is False and rep["degraded_reason"] in {"pointer_no_hit"}


def test_empty_index_degraded(tmp_path):
    db = _mkdb(tmp_path)
    rep = query_pointers(str(db), "任意问题")
    assert rep["ok"] is False and rep["degraded_reason"] == "pointer_index_empty"
    assert rep["next"] == "D3"


def test_note_truncated(tmp_path):
    db = _mkdb(tmp_path)
    upsert_pointer(str(db), "长摘要", note="x" * 500, dry_run=False)
    con = sqlite3.connect(db)
    note = con.execute("SELECT note FROM memory_pointers").fetchone()[0]
    con.close()
    assert len(note) == NOTE_MAX
