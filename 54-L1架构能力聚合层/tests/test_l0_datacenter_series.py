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


def test_registry_keywords_self_resolve():
    """注册表自洽：每个 curated 条目至少一个关键词能解析回自身（含去空格归一）。"""
    from l1agg.series_catalog import CURATED_SERIES

    unresolved = []
    for item in CURATED_SERIES:
        want = (item["sub_category"], item["metric_name"])
        if not any(
            resolve_metric(kw)
            and (resolve_metric(kw)["sub_category"], resolve_metric(kw)["metric_name"]) == want
            for kw in item["keywords"]
        ):
            unresolved.append((want, item["keywords"]))
    assert not unresolved, unresolved


def test_registry_normalizes_spaces():
    """「ETF总净流入」与「ETF 净流入」等价命中同一条序列。"""
    spec = resolve_metric("ETF总净流入近30天走势")
    assert (spec["sub_category"], spec["metric_name"]) == ("etf_flow", "total_flow")
    assert (spec.get("scale") or 1.0) == 1.0


def test_format_series_output_scale_and_sign():
    """索引输出统一模板：缩放、符号修正、空数据文案。"""
    from l1agg.series_catalog import format_series_output, resolve_whale_metric

    spec = resolve_whale_metric("查询巨鲸动向")
    points = [
        {"value": 1e9, "ts": NOW - 2 * _DAY},
        {"value": 2e9, "ts": NOW - _DAY},
    ]
    out = format_series_output(
        series=spec, points=points, days=7, quality="good", source="dal_mm_metrics"
    )
    assert out["id"] == "exchanges_whales::whale_netflow_to_ex_usd"
    assert out["value"] == -2e9  # 落库「转出-转入」，展示净流入需翻转
    assert "亿美元" in out["text"] and "-20.00" in out["text"]
    assert out["points_n"] == 2

    empty = format_series_output(series=spec, points=[], days=7)
    assert empty["value"] is None
    assert "暂无历史数据" in empty["text"]


def test_exec_metric_series_end_to_end(series_db):
    """L1 执行器直答：命中指标别名 → L0 真实序列 → 含 sample_n 的回答。"""
    from data_query_executor import exec_metric_series

    result = exec_metric_series("BTC恐惧贪婪近30天变化")
    assert result["success"] is True
    assert result["data"]["sample_n"] == 1
    assert result["data"]["sub_category"] == "crypto_fear_greed"
    assert "恐惧贪婪" in result["data"]["label"]
    assert "恐惧贪婪" in result["answer"]

    miss = exec_metric_series("今天天气怎么样")
    assert miss["success"] is True
    assert miss["data"] is None


# ============================================================
# S1 扩展：关键词注册表（巨鲸 / 经济日历）+ L0 datacenter.events
# ============================================================


def _make_events_db(path: str, rows) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE mm_events (
            event_id TEXT PRIMARY KEY, event_time INTEGER NOT NULL, event_type TEXT NOT NULL,
            subtype TEXT, source TEXT NOT NULL, title TEXT, confidence REAL, quality TEXT,
            payload_json TEXT
        )
        """)
    conn.executemany(
        "INSERT INTO mm_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(f"e{i}", *r, None) for i, r in enumerate(rows)],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def events_db(tmp_path, monkeypatch):
    db = tmp_path / "core.db"
    _make_events_db(
        str(db),
        [
            # 过去：不该出现在「下一次」结果里
            (NOW - 10 * _DAY, "fomc", "statement", "fed_calendar", "FOMC 旧会", 1.0, "A"),
            (NOW + 20 * _DAY, "fomc", "statement", "fed_calendar", "FOMC 12月", 1.0, "A"),
            (NOW + 70 * _DAY, "fomc", "statement", "fed_calendar", "FOMC 1月", 1.0, "A"),
            (NOW + 5 * _DAY, "nfp", "release", "macro_calendar", "Employment Situation", 1.0, "A"),
            (NOW + 900 * _DAY, "fomc", "statement", "fed_calendar", "窗口外 FOMC", 1.0, "A"),
        ],
    )
    monkeypatch.setenv("DREAMBUDDY_CORE_DB", str(db))
    return str(db)


def test_resolve_whale_metric():
    from l1agg.series_catalog import resolve_whale_metric

    net = resolve_whale_metric("查询巨鲸动向")
    assert (net["sub_category"], net["metric_name"]) == (
        "exchanges_whales",
        "whale_netflow_to_ex_usd",
    )
    assert net["sign"] == -1.0  # 落库口径为「转出-转入」，展示净流入需翻转

    inflow = resolve_whale_metric("巨鲸流入交易所")
    assert inflow["metric_name"] == "whale_24h_to_ex_usd"


def test_resolve_event_kind():
    from l1agg.series_catalog import resolve_event_kind

    assert resolve_event_kind("下一次议息会议是什么时候")["kind"] == "fomc"
    assert resolve_event_kind("下次非农什么时候公布")["kind"] == "nfp"
    assert resolve_event_kind("今天天气怎么样") is None


def test_events_scope_returns_future_sorted(events_db):
    ctx = _l0().fetch_context("datacenter.events", {"kinds": ["fomc"], "limit": 3})
    assert ctx["degraded"] is False
    events = ctx["data"]
    assert [e["title"] for e in events] == ["FOMC 12月", "FOMC 1月"]
    assert events[0]["event_time_cst"].startswith("2026-12")
    assert ctx["source"] == "dal_mm_events"


def test_events_scope_rejects_bad_limit(events_db):
    ctx = _l0().fetch_context("datacenter.events", {"limit": 0})
    assert ctx["degraded"] is True
    assert ctx["meta"]["reason"] == "invalid_params"


def test_events_scope_missing_table_degrades(series_db):
    ctx = _l0().fetch_context("datacenter.events", {"limit": 3})
    assert ctx["degraded"] is True
    assert ctx["meta"]["reason"] == "read_error"


def test_exec_calendar_event_end_to_end(events_db):
    from data_query_executor import exec_calendar_event

    result = exec_calendar_event("下一次议息会议是什么时候")
    assert result["success"] is True
    assert result["data"]["kind"] == "fomc"
    assert "2026-12" in result["answer"]
    assert result["data"]["events"][0]["event_type"] == "fomc"


def test_exec_whale_flow_end_to_end(series_db, monkeypatch):
    """巨鲸执行器：只依赖 exchanges_whales 序列，符号按注册表翻转。"""
    import data_query_executor as dqe

    db = os.environ["DREAMBUDDY_CORE_DB"]
    conn = sqlite3.connect(db)
    # 落库口径 = 转出-转入：负值代表净流入
    conn.executemany(
        "INSERT INTO mm_metrics VALUES (?, ?, ?, ?, ?)",
        [
            ("coinglass", "exchanges_whales", "whale_netflow_to_ex_usd", -1.0e8, NOW - 2 * _DAY),
            ("coinglass", "exchanges_whales", "whale_netflow_to_ex_usd", -3.0e8, NOW - _DAY),
            ("coinglass", "exchanges_whales", "whale_24h_to_ex_usd", 4.0e9, NOW - _DAY),
            ("coinglass", "exchanges_whales", "whale_24h_from_ex_usd", 3.0e9, NOW - _DAY),
            ("coinglass", "exchanges_whales", "whales_transfer_count", 1000.0, NOW - _DAY),
        ],
    )
    conn.commit()
    conn.close()

    result = dqe.exec_whale_flow("巨鲸动向")
    assert result["success"] is True
    assert result["data"]["metric_name"] == "whale_netflow_to_ex_usd"
    assert result["data"]["stats"]["last"] == 3.0e8  # -3e8 落库 → +3亿净流入
    assert "净流入" in result["answer"]
    assert "1000 笔" in result["answer"]
