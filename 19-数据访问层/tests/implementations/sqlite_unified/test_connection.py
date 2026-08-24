"""
P0-4 TDD RED：connection.py + 异常分类 + PRAGMA 断言 + auto_retry_locked
对齐 SCHEMA_DESIGN.md §0.2 PRAGMA 配置表（8 条） + TECHNICAL_DESIGN §4.2 异常分类矩阵
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest


# ---------- 1. 异常分类枚举测试 ----------
class TestSqliteErrorClassification:
    def test_5_categories_exist(self):
        """TECHNICAL_DESIGN §4.2 要求 5 类：BUSY / CONSTRAINT / CORRUPT / IO / OTHER"""
        from dreambuddy_dal.connection import SQLiteErrorCategory
        expected = {"BUSY", "CONSTRAINT", "CORRUPT", "IO_ERROR", "OTHER"}
        assert {e.value for e in SQLiteErrorCategory} == expected

    def test_classify_exception_has_mapping(self):
        """classify_sqlite_exception(exception) -> SQLiteErrorCategory"""
        from dreambuddy_dal.connection import SQLiteErrorCategory, classify_sqlite_exception
        # OperationalError("database is locked") → BUSY
        e1 = sqlite3.OperationalError("database is locked")
        assert classify_sqlite_exception(e1) == SQLiteErrorCategory.BUSY
        # IntegrityError("UNIQUE constraint") → CONSTRAINT
        e2 = sqlite3.IntegrityError("UNIQUE constraint failed: tr_trades.trade_id")
        assert classify_sqlite_exception(e2) == SQLiteErrorCategory.CONSTRAINT
        # DatabaseError("database disk image is malformed") → CORRUPT
        e3 = sqlite3.DatabaseError("database disk image is malformed")
        assert classify_sqlite_exception(e3) == SQLiteErrorCategory.CORRUPT


# ---------- 2. PRAGMA 配置测试（SCHEMA_DESIGN §0.2 表 8 条）----------
class TestPragmaConfigApplied:
    """
    get_sqlite_connection(db_path) 必须在连接后立刻应用 8 条 PRAGMA，
    并对 critical 4 条做断言校验（ASSERTION 校验）。
    """
    @pytest.fixture
    def temp_db(self):
        from dreambuddy_dal.connection import get_sqlite_connection
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "pragmatest.db")
            with get_sqlite_connection(db_path) as conn:
                yield conn

    def test_journal_mode_is_wal(self, temp_db):
        r = temp_db.execute("PRAGMA journal_mode").fetchone()
        assert r[0].lower() == "wal", f"PRAGMA journal_mode != WAL，实际={r[0]}"

    def test_foreign_keys_on(self, temp_db):
        r = temp_db.execute("PRAGMA foreign_keys").fetchone()
        assert r[0] == 1

    def test_busy_timeout_is_5000(self, temp_db):
        r = temp_db.execute("PRAGMA busy_timeout").fetchone()
        assert r[0] == 5000, f"busy_timeout 不是 5000ms，实际={r[0]}"

    def test_synchronous_is_normal(self, temp_db):
        r = temp_db.execute("PRAGMA synchronous").fetchone()
        # 1 = NORMAL
        assert r[0] == 1, f"synchronous 不是 NORMAL(1)，实际={r[0]}"

    def test_temp_store_is_memory(self, temp_db):
        r = temp_db.execute("PRAGMA temp_store").fetchone()
        assert r[0] == 2  # 2 = MEMORY

    def test_mmap_size_is_256mb(self, temp_db):
        r = temp_db.execute("PRAGMA mmap_size").fetchone()
        expected = 256 * 1024 * 1024  # 268435456
        assert r[0] == expected, f"mmap_size != 256MB，实际={r[0]}"

    def test_cache_size_is_negative(self, temp_db):
        """cache_size 负值代表 KB（-20000 = 20MB cache）"""
        r = temp_db.execute("PRAGMA cache_size").fetchone()
        assert r[0] < 0, f"cache_size 必须是负数（KB），实际={r[0]}"
        # 至少 10MB 缓存
        assert abs(r[0]) >= 10000, "cache_size 绝对值 < 10MB"


# ---------- 3. auto_retry_locked 退避测试 ----------
class TestAutoRetryLocked:
    def test_retry_on_locked_succeeds_third_attempt(self):
        """前 2 次抛 OperationalError(locale 含 locked)，第 3 次成功 → 计数==3"""
        from dreambuddy_dal.connection import auto_retry_locked
        calls = []

        @auto_retry_locked
        def flaky(expect_fail_count: int) -> str:
            calls.append(1)
            if len(calls) <= expect_fail_count:
                raise sqlite3.OperationalError("database is locked")
            return "OK"

        # 前两次抛，3 次成功
        result = flaky(expect_fail_count=2)
        assert result == "OK"
        assert len(calls) == 3  # 重试了 2 次 + 最后 1 次

    def test_retry_surrenders_after_3_retries(self):
        """连续 4 次 locked（max_retries=3 次重试后）→ 抛最后一次异常"""
        from dreambuddy_dal.connection import auto_retry_locked

        @auto_retry_locked(max_retries=3)
        def always_locked() -> str:
            raise sqlite3.OperationalError("database is locked")

        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            always_locked()

    def test_non_busy_errors_never_retried(self):
        """CORRUPT / UNIQUE constraint 不是 BUSY，直接抛出不重试"""
        from dreambuddy_dal.connection import auto_retry_locked

        @auto_retry_locked
        def throw_unique_violation():
            raise sqlite3.IntegrityError("UNIQUE constraint failed")

        with pytest.raises(sqlite3.IntegrityError):
            throw_unique_violation()
