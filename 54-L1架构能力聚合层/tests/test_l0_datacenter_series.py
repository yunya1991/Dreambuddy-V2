# -*- coding: utf-8 -*-
"""S1: L0 `datacenter.series` + 指标字典离线用例（临时库，不触真实 DB）。"""

import datetime
import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_CORE_DIR = os.path.join(_MODULE_ROOT, "..", "34-前端应用训练系统", "core")
_FRONTEND_SCRIPTS = os.path.join(_MODULE_ROOT, "..", "3.1-FRONTEND", "scripts")
for _p in (_MODULE_ROOT, _CORE_DIR, _FRONTEND_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from l0_foundation import L0Foundation  # noqa: E402
from l1agg.series_catalog import (  # noqa: E402
    MODULE_SERIES,
    module_series,
    resolve_days,
    resolve_metric,
)

_DAY = 86400
NOW = int(datetime.datetime(2026, 11, 14, 12, 0, tzinfo=datetime.UTC).timestamp())


def _make_db(path: str, rows) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE mm_metrics (
            source TEXT NOT NULL, sub_category TEXT NOT NULL, metric_name TEXT NOT NULL,
            metric_value REAL, timestamp INTEGER NOT NULL,
            PRIMARY KEY (source, sub_category, metric_name, timestamp)
        ) WITHOUT ROWID
        """)
    conn.execute(
        "CREATE INDEX idx_mm_metrics_lookup ON mm_metrics (sub_category, metric_name, timestamp)"
    )
    conn.executemany("INSERT INTO mm_metrics VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


@pytest.fixture
def series_db(tmp_path, monkeypatch):
    db = tmp_path / "core.db"
    rows = []
    # 40 天日频收盘价
    for i in range(40):
        rows.append(("okx", "BTC", "close_usd", 100.0 + i, NOW - (39 - i) * _DAY))
    # 同一 UTC 日两条：日频降采样应取日内最后一条
    rows.append(("fear_greed", "crypto_fear_greed", "value", 10.0, NOW - 2 * _DAY))
    rows.append(("fear_greed", "crypto_fear_greed", "value", 20.0, NOW - 2 * _DAY + 3600))
    # 跨源同 ts 重复：source 字典序最小者保留
    rows.append(("binance_futures", "funding_rate", "funding_rate_pct", 0.01, NOW - _DAY))
    rows.append(("binance_funding_rate", "funding_rate", "funding_rate_pct", 0.02, NOW - _DAY))
    # NULL 值必须被剔除
    rows.append(("feedparser", "news", "caption", None, NOW - _DAY))
    _make_db(str(db), rows)
    monkeypatch.setenv("DREAMBUDDY_CORE_DB", str(db))
    return str(db)


def _l0() -> L0Foundation:
    return L0Foundation()


def test_daily_series_good_quality(series_db):
    ctx = _l0().fetch_context(
        "datacenter.series", {"sub_category": "BTC", "metric_name": "close_usd", "days": 60}
    )
    assert ctx["degraded"] is False
    data, meta = ctx["data"], ctx["meta"]
    assert data["sample_n"] == 40
    assert meta["quality"] == "good"
    assert meta["agg"] == "daily"
    assert data["points"][-1]["value"] == 139.0
    assert data["points"][-1]["timestamp"].endswith("Z")


def test_same_day_keeps_last_point(series_db):
    ctx = _l0().fetch_context(
        "datacenter.series",
        {"sub_category": "crypto_fear_greed", "metric_name": "value", "days": 10},
    )
    points = ctx["data"]["points"]
    assert len(points) == 1
    assert points[0]["value"] == 20.0  # 同日取最后一条，而非首条
    assert ctx["meta"]["quality"] == "partial"


def test_cross_source_dedup(series_db):
    ctx = _l0().fetch_context(
        "datacenter.series",
        {"sub_category": "funding_rate", "metric_name": "funding_rate_pct", "days": 10},
    )
    assert ctx["meta"]["raw_n"] == 1
    assert ctx["meta"]["sources"] == ["binance_funding_rate"]
    assert ctx["data"]["points"][0]["value"] == 0.02


def test_partial_quality_below_30(series_db):
    ctx = _l0().fetch_context(
        "datacenter.series", {"sub_category": "BTC", "metric_name": "close_usd", "days": 5}
    )
    assert ctx["data"]["sample_n"] == 5
    assert ctx["meta"]["quality"] == "partial"


def test_raw_and_monthly_agg(series_db):
    raw = _l0().fetch_context(
        "datacenter.series",
        {"sub_category": "BTC", "metric_name": "close_usd", "days": 60, "agg": "raw"},
    )
    assert raw["data"]["sample_n"] == 40
    monthly = _l0().fetch_context(
        "datacenter.series",
        {"sub_category": "BTC", "metric_name": "close_usd", "days": 60, "agg": "monthly"},
    )
    assert 1 <= monthly["data"]["sample_n"] <= 3
    assert monthly["meta"]["quality"] == "partial"


@pytest.mark.parametrize(
    "params",
    [
        {"sub_category": "BTC", "metric_name": "close_usd", "days": 0},
        {"sub_category": "BTC", "metric_name": "close_usd", "days": 1826},
        {"sub_category": "BTC", "metric_name": "close_usd", "days": "abc"},
        {"sub_category": "BTC;DROP TABLE mm_metrics", "metric_name": "close_usd"},
        {"sub_category": "BTC", "metric_name": "close_usd", "agg": "hourly"},
        {"sub_category": "", "metric_name": "close_usd"},
    ],
)
def test_invalid_params_degraded(series_db, params):
    ctx = _l0().fetch_context("datacenter.series", params)
    assert ctx["degraded"] is True
    assert ctx["meta"]["reason"] == "invalid_params"


def test_missing_db_degraded(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAMBUDDY_CORE_DB", str(tmp_path / "nope.db"))
    ctx = _l0().fetch_context(
        "datacenter.series", {"sub_category": "BTC", "metric_name": "close_usd", "days": 30}
    )
    assert ctx["degraded"] is True
    assert ctx["meta"]["reason"] == "source_missing"


def test_empty_series_reports_no_history(series_db):
    ctx = _l0().fetch_context(
        "datacenter.series", {"sub_category": "NOPE", "metric_name": "value", "days": 30}
    )
    assert ctx["degraded"] is False
    assert ctx["data"]["sample_n"] == 0
    assert ctx["meta"]["quality"] == "empty"
    assert ctx["meta"]["reason"] == "no_history"


def test_catalog_covers_11_modules():
    assert set(MODULE_SERIES) == {
        "macro",
        "onchain",
        "sentiment",
        "valuation",
        "flow",
        "breadth",
        "capital_flow",
        "intermarket",
        "news",
        "narrative",
        "calendar",
    }
    for key in MODULE_SERIES:
        spec = module_series(key)
        assert spec["series"], key
        assert 1 <= spec["days"] <= 1825


def test_resolve_metric_and_days():
    cpi = resolve_metric("近一年CPI走势")
    assert (cpi["sub_category"], cpi["metric_name"]) == ("CPIAUCSL", "value")
    assert resolve_days("近一年CPI走势", 30) == 365

    fg = resolve_metric("BTC恐惧贪婪近30天变化")
    assert (fg["sub_category"], fg["metric_name"]) == ("crypto_fear_greed", "value")
    assert resolve_days("BTC恐惧贪婪近30天变化", 90) == 30

    assert resolve_metric("今天天气怎么样") is None


def test_exec_metric_series_end_to_end(series_db):
    """L1 执行器直答：命中指标别名 → L0 真实序列 → 含 sample_n 的回答。"""
    from data_query_executor import exec_metric_series

    result = exec_metric_series("BTC恐惧贪婪近30天变化")
    assert result["success"] is True
    assert result["data"]["sample_n"] == 1
    assert result["data"]["label"] == "恐惧贪婪指数"
    assert "恐惧贪婪" in result["answer"]

    miss = exec_metric_series("今天天气怎么样")
    assert miss["success"] is True
    assert miss["data"] is None
