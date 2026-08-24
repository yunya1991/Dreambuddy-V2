"""
TDD：P3-3 rotate.py（WAL checkpoint + 旧备份轮转保留 N 份）
================================================================
入口：
  from dreambuddy_dal.implementations.sqlite_unified.rotate import (
      wal_checkpoint, rotate_backups,
  )
  wal_checkpoint(db_path) → int (checkpointed_pages)
  rotate_backups(backup_dir, keep=7) → list[Path] deleted_files

设计要点（对齐 MIGRATION_PLAN §4.3）：
  1. PRAGMA wal_checkpoint(TRUNCATE) → 合并 WAL 到主库
  2. 扫描 backup_dir 下 dreambuddy_core_*.db[.enc] 文件
  3. 按 mtime 排序，保留最新 keep 份，其余删除（含 .sha256 sidecar）
  4. 返回被删除文件列表
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
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
# 1. WAL checkpoint 返回非负数（即使无 WAL 也不报错）
# ===========================================================================
def test_wal_checkpoint_returns_non_negative(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.rotate import wal_checkpoint
    pages = wal_checkpoint(db_path)
    assert isinstance(pages, int)
    assert pages >= 0


# ===========================================================================
# 2. rotate_backups：10 份 → keep=7 → 删 3 份
# ===========================================================================
def test_rotate_keeps_n_newest(tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.rotate import rotate_backups
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    # 创建 10 个备份文件（含 .sha256 sidecar）
    for i in range(10):
        ts = f"2026082{i}1_00000{i}"
        db_file = backup_dir / f"dreambuddy_core_{ts}.db"
        db_file.write_bytes(b"fake")
        (backup_dir / f"dreambuddy_core_{ts}.db.sha256").write_text("abc123")
    deleted = rotate_backups(str(backup_dir), keep=7)
    remaining = list(backup_dir.glob("dreambuddy_core_*.db"))
    remaining_sha = list(backup_dir.glob("dreambuddy_core_*.db.sha256"))
    assert len(remaining) == 7
    assert len(remaining_sha) == 7
    assert len(deleted) == 6  # 3 db + 3 sha256


# ===========================================================================
# 3. rotate_backups：keep=0 → 删全部
# ===========================================================================
def test_rotate_keep_zero_deletes_all(tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.rotate import rotate_backups
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for i in range(5):
        (backup_dir / f"dreambuddy_core_2026082{i}1_00000{i}.db").write_bytes(b"x")
    deleted = rotate_backups(str(backup_dir), keep=0)
    remaining = list(backup_dir.glob("dreambuddy_core_*.db"))
    assert len(remaining) == 0
    assert len(deleted) == 5


# ===========================================================================
# 4. rotate_backups：空目录 → 不报错，返回空列表
# ===========================================================================
def test_rotate_empty_dir(tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.rotate import rotate_backups
    backup_dir = tmp_path / "empty"
    backup_dir.mkdir()
    deleted = rotate_backups(str(backup_dir), keep=7)
    assert deleted == []
