"""
TDD：P3-1 backup.py（全量备份 + SHA256 校验 + AES256 加密）
================================================================
入口：
  from dreambuddy_dal.implementations.sqlite_unified.backup import (
      backup_database, verify_backup,
  )
  backup_path = backup_database(db_path, backup_dir, *, encrypt=True, passphrase=None)
  ok = verify_backup(backup_path, *, passphrase=None)

设计要点（对齐 MIGRATION_PLAN §4.1）：
  1. VACUUM INTO 做在线全量备份（不锁库，WAL-safe）
  2. SHA256 校验和写 .sha256 sidecar 文件
  3. AES256-GCM 加密（passphrase 非 None 时；否则明文 .db）
  4. 备份文件名：dreambuddy_core_YYYYmmdd_HHMMSS.db[.enc]
"""
from __future__ import annotations

import os
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
# 1. 明文备份：生成 .db + .sha256，可 verify
# ===========================================================================
def test_plain_backup_creates_db_and_sha256(db_path, tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.backup import (
        backup_database, verify_backup,
    )
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    bpath = backup_database(db_path, str(backup_dir), encrypt=False)
    assert Path(bpath).exists()
    sha_path = Path(bpath + ".sha256")
    assert sha_path.exists()
    ok = verify_backup(bpath)
    assert ok is True


# ===========================================================================
# 2. 加密备份：生成 .enc + .sha256，解密后可 verify
# ===========================================================================
def test_encrypted_backup_roundtrip(db_path, tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.backup import (
        backup_database, verify_backup,
    )
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    bpath = backup_database(
        db_path, str(backup_dir),
        encrypt=True, passphrase="test_pass_123",
    )
    assert Path(bpath).exists()
    assert bpath.endswith(".enc")
    ok = verify_backup(bpath, passphrase="test_pass_123")
    assert ok is True


# ===========================================================================
# 3. 加密备份：错误 passphrase → verify 失败
# ===========================================================================
def test_encrypted_backup_wrong_passphrase_fails(db_path, tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.backup import (
        backup_database, verify_backup,
    )
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    bpath = backup_database(
        db_path, str(backup_dir),
        encrypt=True, passphrase="correct_pass",
    )
    ok = verify_backup(bpath, passphrase="wrong_pass")
    assert ok is False


# ===========================================================================
# 4. 备份文件可被 SQLite 打开（数据一致）
# ===========================================================================
def test_backup_is_valid_sqlite(db_path, tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.backup import backup_database
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    bpath = backup_database(db_path, str(backup_dir), encrypt=False)
    with get_sqlite_connection(bpath) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
    assert "ma_schema_version" in tables
    assert "tr_trades" in tables
