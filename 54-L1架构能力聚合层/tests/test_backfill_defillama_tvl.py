# -*- coding: utf-8 -*-
"""DeFiLlama 全局 TVL 回填测试（离线，fetch 注入假数据）。"""

import datetime
import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_SCRIPTS_DIR = os.path.join(_MODULE_ROOT, "scripts")
_DAL_ROOT = os.path.join(_MODULE_ROOT, "..", "19-数据访问层")
for _p in (_MODULE_ROOT, _SCRIPTS_DIR, _DAL_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backfill_defillama_tvl import run  # noqa: E402

_DAY = 86400
_NOW = datetime.datetime(2026, 11, 14, 12, 0, tzinfo=datetime.UTC)
_NOW_TS = int(_NOW.timestamp())


def _history(total_days, start_ts=None, tvl_last=147.88e9):
    """生成 asc 顺序的 {date, totalLiquidityUSD}；最后一天为 tvl_last。"""
    start_ts = start_ts if start_ts is not None else _NOW_TS - (total_days - 1) * _DAY
    rows = []
    for i in range(total_days):
        # 每天较前一日 +0.01B，保证最后一天 = tvl_last
        tvl = tvl_last - (total_days - 1 - i) * 0.01e9
        rows.append({"date": start_ts + i * _DAY, "totalLiquidityUSD": tvl})
    return rows


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, source, sub_category, metric_name, value, ts):
        self.calls.append((source, sub_category, metric_name, value, ts))
        return True


def test_run_scale_and_window():
    """单位换算 十亿美元、90 天窗口过滤、时间戳按天。"""
    rec = Recorder()
    stats = run(lambda: _history(120), rec, days=90, now=_NOW)

    assert stats["ok"] is True
    assert stats["fetched"] == 120
    # 截止日当天也回填（闭区间），120-90+1=31 天窗口
    assert stats["written"] == 91
    assert stats["skipped_out_of_range"] == 29
    assert all(c[0:3] == ("defillama", "chains_summary", "total_tvl_bln") for c in rec.calls)
    assert rec.calls[-1][3] == pytest.approx(147.88, abs=1e-4)
    assert rec.calls[-1][4] == datetime.datetime.fromtimestamp(_NOW_TS, datetime.UTC)


def test_run_skips_invalid_and_dry_run():
    rec = Recorder()
    rows = _history(10) + [
        {"date": None, "totalLiquidityUSD": 1.0},
        {"date": _NOW_TS, "totalLiquidityUSD": "bad"},
    ]
    stats = run(lambda: rows, rec, days=30, now=_NOW, dry_run=True)
    assert stats["skipped_invalid"] == 2
    assert stats["written"] == 10
    assert rec.calls == []


def test_run_fetch_error_is_recorded():
    def _boom():
        raise RuntimeError("HTTP 500")

    stats = run(_boom, Recorder(), days=30, now=_NOW)
    assert stats["ok"] is False
    assert "HTTP 500" in stats["errors"][0]


def test_run_idempotent_against_sqlite(tmp_path):
    """重复运行只覆盖不新增（mm_metrics 主键幂等）。"""
    from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (
        SqliteMarketMacroRepository,
    )

    db = tmp_path / "core.db"
    repo = SqliteMarketMacroRepository(str(db))
    fetch = lambda: _history(95)  # noqa: E731
    run(fetch, repo.upsert_metric, days=90, now=_NOW)
    first = _count_rows(str(db))
    run(fetch, repo.upsert_metric, days=90, now=_NOW)
    assert _count_rows(str(db)) == first == 91

    conn = sqlite3.connect(str(db))
    try:
        value = conn.execute(
            "SELECT metric_value FROM mm_metrics WHERE sub_category='chains_summary' "
            "AND metric_name='total_tvl_bln' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()
    assert value == pytest.approx(147.88, abs=1e-4)


def _count_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM mm_metrics WHERE sub_category='chains_summary' "
            "AND metric_name='total_tvl_bln'"
        ).fetchone()[0]
    finally:
        conn.close()
