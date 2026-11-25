# -*- coding: utf-8 -*-
"""B18 写入路径：`upsert_metric` 必须把每次观测追加到 `mm_metric_vintages`。

背景（SPEC-54 §4.12 第 7 条 / ADR-V20）：宏观数据修订会覆盖主表旧值，
回放若只见修订后数字即为前视。最小可用 vintage = `(metric, period, observed_at)`
追加式存储；本测试锁死「主表仍覆盖、vintage 不丢观测」两条口径。
"""

import datetime
import os
import sqlite3
import sys

_DAL_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _DAL_ROOT not in sys.path:
    sys.path.insert(0, _DAL_ROOT)

from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (  # noqa: E402
    SqliteMarketMacroRepository,
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


def _repo(tmp_path):
    db = str(tmp_path / "mm.db")
    conn = sqlite3.connect(db)
    conn.execute(_SCHEMA)
    conn.commit()
    conn.close()
    return db, SqliteMarketMacroRepository(db)


def test_upsert_metric_appends_vintage_and_keeps_main_overwrite(tmp_path):
    db, repo = _repo(tmp_path)
    period = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
    assert repo.upsert_metric("macro", "cpi", "us_cpi_yoy", 2.9, period)
    assert repo.upsert_metric("macro", "cpi", "us_cpi_yoy", 3.1, period)

    conn = sqlite3.connect(db)
    try:
        main = conn.execute(
            "SELECT metric_value FROM mm_metrics WHERE metric_name='us_cpi_yoy'"
        ).fetchall()
        vintages = conn.execute(
            "SELECT metric_value FROM mm_metric_vintages"
            " WHERE metric_name='us_cpi_yoy' ORDER BY observed_at ASC"
        ).fetchall()
    finally:
        conn.close()
    assert len(main) == 1 and main[0][0] == 3.1  # 主表仍是最新修订值
    assert len(vintages) == 2  # 两次观测都留存
    assert [row[0] for row in vintages] == [2.9, 3.1]


def test_vintage_table_autocreates_and_is_idempotent(tmp_path):
    db, repo = _repo(tmp_path)
    period = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
    repo.upsert_metric("macro", "gdp", "us_gdp", 1.0, period)
    repo.upsert_metric("macro", "gdp", "us_gdp", 2.0, period)
    conn = sqlite3.connect(db)
    try:
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='mm_metric_vintages'"
        ).fetchone()
        count = conn.execute("SELECT COUNT(*) FROM mm_metric_vintages").fetchone()[0]
        index = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_vintages_replay'"
        ).fetchone()
    finally:
        conn.close()
    assert schema is not None and "observed_at" in schema[0]
    assert index is not None
    assert count == 2


def test_repeated_same_value_does_not_grow_vintage(tmp_path):
    """周期型指标重复采到同一个值时不追加 vintage（幂等写入）。

    云端膨胀根因：fred 等源每轮轮询都为同一 (period, value) 落一条 vintage，
    180 天内单序列可达数百条。值未变 = 非修订，不构成新观测。
    """
    db, repo = _repo(tmp_path)
    period = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
    for _ in range(5):
        repo.upsert_metric("fred", "macro", "m2_sl", 21.5, period)
    conn = sqlite3.connect(db)
    try:
        vintages = conn.execute("SELECT metric_value FROM mm_metric_vintages").fetchall()
        main = conn.execute("SELECT metric_value FROM mm_metrics").fetchall()
    finally:
        conn.close()
    assert [row[0] for row in vintages] == [21.5]
    assert [row[0] for row in main] == [21.5]


def test_same_value_after_revision_still_appends(tmp_path):
    """值变化后即使回到旧值，也必须记为新观测（修订不可合并）。"""
    db, repo = _repo(tmp_path)
    period = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
    for value in (2.9, 2.9, 3.1, 3.1, 2.9):
        repo.upsert_metric("fred", "cpi", "us_cpi_yoy", value, period)
    conn = sqlite3.connect(db)
    try:
        vintages = conn.execute(
            "SELECT metric_value FROM mm_metric_vintages ORDER BY observed_at ASC"
        ).fetchall()
    finally:
        conn.close()
    assert [row[0] for row in vintages] == [2.9, 3.1, 2.9]


def test_as_of_replay_reads_only_observations_before_cutoff(tmp_path):
    db, repo = _repo(tmp_path)
    period = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
    repo.upsert_metric("macro", "cpi", "us_cpi_yoy", 2.9, period)
    conn = sqlite3.connect(db)
    try:
        cutoff = conn.execute("SELECT MAX(observed_at) FROM mm_metric_vintages").fetchone()[0]
    finally:
        conn.close()
    repo.upsert_metric("macro", "cpi", "us_cpi_yoy", 3.1, period)
    conn = sqlite3.connect(db)
    try:
        value = conn.execute(
            "SELECT metric_value FROM mm_metric_vintages"
            " WHERE metric_name='us_cpi_yoy' AND observed_at <= ?"
            " ORDER BY observed_at DESC LIMIT 1",
            (cutoff,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert value == 2.9


def test_append_vintages_skips_unchanged_replay(tmp_path):
    """回填脚本整段重放时，取值未变的行不得重复追加。

    云端每 600s 跑一次 18→19 回填，每次把 18 data_center.db 的全部指标重放一遍；
    不做幂等就会每轮都为同一 (period_ts, value) 追加一条，单日约 2000 万行。
    """
    from dreambuddy_dal.implementations.sqlite_unified.vintage import append_vintages

    db, _repo_obj = _repo(tmp_path)
    rows = [("fred", "macro", "m2_sl", 21.5, 1000), ("fred", "macro", "m2_sl", 21.7, 2000)]
    conn = sqlite3.connect(db)
    try:
        assert append_vintages(conn, rows, observed_at=100) == 2
        conn.commit()
        assert append_vintages(conn, rows, observed_at=200) == 0  # 整段重放：全部同值
        conn.commit()
        changed = [("fred", "macro", "m2_sl", 21.5, 1000), ("fred", "macro", "m2_sl", 21.9, 2000)]
        assert append_vintages(conn, changed, observed_at=300) == 1  # 只有真实修订
        conn.commit()
        got = conn.execute(
            "SELECT period_ts, metric_value FROM mm_metric_vintages ORDER BY period_ts, observed_at"
        ).fetchall()
    finally:
        conn.close()
    assert got == [(1000, 21.5), (2000, 21.7), (2000, 21.9)]
