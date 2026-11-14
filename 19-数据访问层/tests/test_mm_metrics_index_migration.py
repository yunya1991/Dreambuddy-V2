# -*- coding: utf-8 -*-
"""S1.0-1: mm_metrics 索引迁移与 DAL 自愈测试。

校验三件事：
  1. 脚本在缺索引的库上创建 idx_mm_metrics_query，且区间查询走索引；
  2. 脚本幂等（第二次运行不重复创建）；
  3. DAL 首次建表即带索引（新建库不会退化为全表扫描）。
"""

import datetime
import os
import sqlite3
import sys

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_DAL_ROOT = os.path.join(_TESTS_DIR, "..")
_SCRIPTS_DIR = os.path.join(_DAL_ROOT, "scripts")
for _p in (_DAL_ROOT, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from migrate_mm_metrics_index import (  # noqa: E402
    _INDEX_NAME,
    _QUERY,
    migrate,
)

_SCHEMA = """
CREATE TABLE mm_metrics (
    source TEXT NOT NULL,
    sub_category TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    timestamp INTEGER NOT NULL,
    PRIMARY KEY (source, sub_category, metric_name, timestamp)
) WITHOUT ROWID
"""


def _make_db(path, rows=500, with_index=False):
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    now = int(datetime.datetime.now().timestamp())
    conn.executemany(
        "INSERT INTO mm_metrics (source, sub_category, metric_name, metric_value, timestamp)"
        " VALUES ('src', 'cat', 'm1', ?, ?)",
        [(float(i), now - (rows - i) * 86400) for i in range(rows)],
    )
    if with_index:
        conn.execute(
            f"CREATE INDEX {_INDEX_NAME} ON mm_metrics (sub_category, metric_name, timestamp)"
        )
    conn.commit()
    conn.close()


def _plan_uses_index(path):
    conn = sqlite3.connect(path)
    plan = conn.execute("EXPLAIN QUERY PLAN " + _QUERY, ("cat", "m1", 0, 2**31)).fetchall()
    conn.close()
    return any(_INDEX_NAME in str(r[3]) for r in plan)


class TestMigrateScript:
    def test_creates_index_when_missing(self, tmp_path):
        db = str(tmp_path / "fresh.db")
        _make_db(db)
        assert _plan_uses_index(db) is False

        result = migrate(db)

        assert result["status"] == "ok"
        assert result["index_existed"] is False
        assert result["index_created"] is True
        assert result["plan_uses_index"] is True
        assert _plan_uses_index(db) is True

    def test_idempotent_second_run(self, tmp_path):
        db = str(tmp_path / "fresh.db")
        _make_db(db)
        migrate(db)
        result = migrate(db)
        assert result["index_existed"] is True
        assert result["index_created"] is False
        assert result["status"] == "ok"

    def test_dry_run_does_not_create(self, tmp_path):
        db = str(tmp_path / "fresh.db")
        _make_db(db)
        result = migrate(db, dry_run=True)
        assert result["index_created"] is False
        assert result["plan_uses_index"] is False
        assert _plan_uses_index(db) is False

    def test_table_missing_is_skipped(self, tmp_path):
        db = str(tmp_path / "empty.db")
        sqlite3.connect(db).close()
        result = migrate(db)
        assert result["status"] == "table_missing"

    def test_db_missing(self, tmp_path):
        result = migrate(str(tmp_path / "nope.db"))
        assert result["status"] == "db_missing"

    def test_bench_returns_real_rows(self, tmp_path):
        db = str(tmp_path / "fresh.db")
        _make_db(db)
        result = migrate(db)
        assert result["bench_after"], "基准结果不应为空"
        assert any(b["returned"] > 0 for b in result["bench_after"])


class TestDalSelfHeal:
    def test_first_insert_creates_index(self, tmp_path):
        from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (
            SqliteMarketMacroRepository,
        )
        from dreambuddy_dal.migrations.init_schema import init_schema

        db = str(tmp_path / "dal.db")
        init_schema(db)
        repo = SqliteMarketMacroRepository(db)
        repo.upsert_metric(
            source="src",
            sub_category="cat",
            metric_name="m1",
            metric_value=1.0,
            ts=datetime.datetime.now(),
        )

        conn = sqlite3.connect(db)
        idx = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (_INDEX_NAME,)
        ).fetchone()
        conn.close()
        assert idx is not None
        assert _plan_uses_index(db) is True


@pytest.mark.parametrize("rows", [200, 800])
def test_index_survives_small_and_large(tmp_path, rows):
    db = str(tmp_path / f"db{rows}.db")
    _make_db(db, rows=rows)
    assert migrate(db)["plan_uses_index"] is True
