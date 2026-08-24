"""
TDD：P3-2 integrity.py（PRAGMA integrity_check + ma_integrity_log 审计）
=====================================================================
入口：
  from dreambuddy_dal.implementations.sqlite_unified.integrity import (
      run_integrity_check,
  )
  result = run_integrity_check(db_path)
  → IntegrityResult(ok, errors, fk_violations, logged)

设计要点（对齐 MIGRATION_PLAN §4.2）：
  1. PRAGMA integrity_check → ok / error list
  2. PRAGMA foreign_key_check → FK 违规列表
  3. 结果写入 ma_integrity_log 表（category='integrity_check'）
  4. 返回 IntegrityResult dataclass
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "dreambuddy_core.db"
        with get_sqlite_connection(str(db)) as conn:
            init_db_schema(conn)
        yield str(db)


# ===========================================================================
# 1. 健康 DB → ok=True, errors=[], fk_violations=[]
# ===========================================================================
def test_integrity_check_healthy_db(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.integrity import (
        run_integrity_check,
    )
    result = run_integrity_check(db_path)
    assert result.ok is True
    assert result.errors == []
    assert result.fk_violations == []


# ===========================================================================
# 2. 结果写入 ma_integrity_log
# ===========================================================================
def test_integrity_check_writes_log(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.integrity import (
        run_integrity_check,
    )
    run_integrity_check(db_path)
    with get_sqlite_connection(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM ma_integrity_log"
        ).fetchone()
    assert row[0] >= 1


# ===========================================================================
# 3. 连续运行 → 每次追加一条 log（不幂等，审计需要历史轨迹）
# ===========================================================================
def test_integrity_check_accumulates_log(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.integrity import (
        run_integrity_check,
    )
    run_integrity_check(db_path)
    run_integrity_check(db_path)
    with get_sqlite_connection(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM ma_integrity_log"
        ).fetchone()
    assert row[0] >= 2


# ===========================================================================
# 4. IntegrityResult 有时间戳字段
# ===========================================================================
def test_integrity_result_has_timestamp(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.integrity import (
        run_integrity_check,
    )
    result = run_integrity_check(db_path)
    assert result.checked_at is not None
    assert len(result.checked_at) > 0
