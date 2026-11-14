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
    assert out["value"] == -20.0  # 落库「转出-转入」+ 按 unit 归一（亿美元，scale=1e8）
    assert "亿美元" in out["text"] and "-20.00" in out["text"]
    assert out["points_n"] == 2

    empty = format_series_output(series=spec, points=[], days=7)
    assert empty["value"] is None
    assert "暂无历史数据" in empty["text"]


def test_defi_tvl_display_unit_is_yi_not_bln():
    """DeFi TVL 库内单位十亿美元 → 展示必须换成亿美元（147.88 bln = 1478.8 亿）。"""
    from l1agg.series_catalog import format_series_output, resolve_metric

    spec = resolve_metric("defi tvl")
    assert spec["unit"] == "亿美元"
    assert spec["scale"] == 0.1
    points = [
        {"value": 144.88, "ts": NOW - 2 * _DAY},
        {"value": 147.88, "ts": NOW},
    ]
    out = format_series_output(series=spec, points=points, days=90, quality="good")
    assert "1478.80 亿美元" in out["text"]
    assert "十亿" not in out["text"]
    assert out["value"] == 1478.8
    assert out["range"]["max"] == 1478.8


def test_format_series_output_window_coverage_honesty():
    """样本只覆盖 9 天却请求 90 天 → 文案如实标注，不能冒充近 90 天。"""
    from l1agg.series_catalog import format_series_output, resolve_metric

    spec = resolve_metric("defi tvl")
    points = [
        {"value": 81.08, "ts": NOW - 8 * _DAY},
        {"value": 77.50, "ts": NOW - 4 * _DAY},
        {"value": 73.88, "ts": NOW},
    ]
    out = format_series_output(series=spec, points=points, days=90, quality="partial")
    assert out["window"]["coverage_days"] == 9
    assert out["window"]["days"] == 90
    assert "最近" not in out["text"]
    assert "近 9 天（请求 90 天，样本不足）" in out["text"]
    assert "数据质量 partial" in out["text"]

    # 覆盖充分时不加「样本不足」噪音
    full = [{"value": 100 + i, "ts": NOW - (89 - i) * _DAY} for i in range(90)]
    ok = format_series_output(series=spec, points=full, days=90, quality="good")
    assert ok["window"]["coverage_days"] == 90
    assert "样本不足" not in ok["text"]
    assert "近 90 天" in ok["text"]


def test_funding_rate_uses_live_okx_source_and_keeps_precision():
    """资金费率取 okx_derivatives（旧 funding_rate 已停更）；小额百分比不能显示成 0.00。"""
    from l1agg.series_catalog import format_series_output, resolve_metric

    spec = resolve_metric("资金费率")
    assert (spec["sub_category"], spec["metric_name"]) == ("okx_derivatives", "funding_rate_pct")

    points = [
        {"value": 0.0012, "ts": NOW - _DAY},
        {"value": 0.000942, "ts": NOW},
    ]
    out = format_series_output(series=spec, points=points, days=7)
    assert "最新 0.0009" in out["text"]


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


# ============================================================
# S1-a：L0 `market.candles`（日频价格 → 1D/1W/1M K 线）
# ============================================================


@pytest.fixture
def candle_db(tmp_path, monkeypatch):
    db = tmp_path / "core.db"
    rows = []
    for i in range(40):
        ts = NOW - (39 - i) * _DAY
        rows.append(("okx", "BTC", "close_usd", 100.0 + i, ts))
        rows.append(("okx", "BTC", "volume_usd", 1000.0, ts))
    # 同一 UTC 日两条收盘：取最后一条；成交量按桶内求和
    rows.append(("okx", "BTC", "close_usd", 999.0, NOW - 2 * _DAY + 3600))
    rows.append(("okx", "BTC", "volume_usd", 500.0, NOW - 2 * _DAY + 3600))
    _make_db(str(db), rows)
    monkeypatch.setenv("DREAMBUDDY_CORE_DB", str(db))
    return str(db)


def test_market_candles_daily(candle_db):
    ctx = _l0().fetch_context("market.candles", {"symbol": "BTC", "days": 60, "bar": "1d"})
    assert ctx["degraded"] is False
    data, meta = ctx["data"], ctx["meta"]
    assert data["sample_n"] == 40
    assert data["has_ohlc"] is False
    assert data["points"][-1]["close"] == 139.0
    assert meta["timezone"] == "UTC"
    assert meta["align_method"] == "daily_last"
    assert meta["quality"] == "partial"  # <120 根
    assert meta["missing_rate"] == 0.0 or meta["missing_rate"] < 0.05
    # 同一 UTC 日：收盘取最后一条；成交量本身是滚动 24h 口径，同日取最后值（不累加，避免重复计）
    assert data["points"][-3]["close"] == 999.0
    assert data["points"][-3]["volume"] == 500.0


def test_market_candles_weekly(candle_db):
    ctx = _l0().fetch_context("market.candles", {"symbol": "BTC", "days": 60, "bar": "1w"})
    points = ctx["data"]["points"]
    assert 5 <= len(points) <= 8
    # 周桶按 ISO 周一取整
    assert all(datetime.date.fromisoformat(p["timestamp"][:10]).weekday() == 0 for p in points)
    assert points[-1]["close"] == 139.0


def test_market_candles_invalid_bar(candle_db):
    ctx = _l0().fetch_context("market.candles", {"symbol": "BTC", "bar": "4h"})
    assert ctx["degraded"] is True
    assert ctx["meta"]["reason"] == "invalid_params"


def test_market_candles_empty_symbol(candle_db):
    ctx = _l0().fetch_context("market.candles", {"symbol": "NOPE", "days": 30})
    assert ctx["degraded"] is False
    assert ctx["data"]["sample_n"] == 0
    assert ctx["meta"]["quality"] == "empty"
    assert ctx["meta"]["reason"] == "no_history"


# ============================================================
# S1-b：market.candles OHLC 合并（`{symbol}/USDT` high/low → 桶内极值）
# ============================================================


@pytest.fixture
def candle_ohlc_db(tmp_path, monkeypatch):
    db = tmp_path / "core.db"
    rows = []
    for i in range(40):
        ts = NOW - (39 - i) * _DAY
        rows.append(("okx", "BTC", "close_usd", 100.0 + i, ts))
        rows.append(("okx", "BTC", "volume_usd", 1000.0, ts))
        # 同一 UTC 日两个小时快照：high 取 max(日+5)、low 取 min(日-5)
        rows.append(("ccxt", "BTC/USDT", "high", 100.0 + i + 3, ts - 3600))
        rows.append(("ccxt", "BTC/USDT", "high", 100.0 + i + 5, ts - 2 * 3600))
        rows.append(("ccxt", "BTC/USDT", "low", 100.0 + i - 3, ts - 3600))
        rows.append(("ccxt", "BTC/USDT", "low", 100.0 + i - 5, ts - 2 * 3600))
    _make_db(str(db), rows)
    monkeypatch.setenv("DREAMBUDDY_CORE_DB", str(db))
    return str(db)


def test_market_candles_ohlc_merged(candle_ohlc_db):
    ctx = _l0().fetch_context("market.candles", {"symbol": "BTC", "days": 60, "bar": "1d"})
    data, meta = ctx["data"], ctx["meta"]
    assert data["sample_n"] == 40
    assert data["has_ohlc"] is True
    assert meta["ohlc_coverage"] == 1.0
    assert meta["ohlc_source"] == "mm_metrics:BTC/USDT"
    assert meta["ohlc_note"]
    last = data["points"][-1]
    assert last["high"] == pytest.approx(144.0)  # 139 + 5
    assert last["low"] == pytest.approx(134.0)  # 139 - 5
    assert last["high"] >= last["close"] >= last["low"]


def test_market_candles_ohlc_weekly_extremes(candle_ohlc_db):
    ctx = _l0().fetch_context("market.candles", {"symbol": "BTC", "days": 60, "bar": "1w"})
    points = ctx["data"]["points"]
    assert ctx["data"]["has_ohlc"] is True
    expected = {}
    for i in range(40):
        day = datetime.datetime.fromtimestamp(NOW - (39 - i) * _DAY, datetime.UTC)
        key = (day - datetime.timedelta(days=day.weekday())).strftime("%Y-%m-%d")
        expected.setdefault(key, []).append(100.0 + i)
    for p in points:
        week = p["timestamp"][:10]
        assert p["high"] == pytest.approx(max(expected[week]) + 5)
        assert p["low"] == pytest.approx(min(expected[week]) - 5)
        assert p["high"] >= p["close"] >= p["low"]


def test_market_candles_ohlc_partial_coverage_not_faked(candle_ohlc_db):
    db = os.environ["DREAMBUDDY_CORE_DB"]
    day_ts = NOW - 10 * _DAY
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE mm_metrics SET metric_value = 0 WHERE sub_category = 'BTC/USDT' "
        "AND metric_name = 'high' AND timestamp IN (?, ?)",
        (day_ts - 3600, day_ts - 2 * 3600),
    )
    conn.commit()
    conn.close()

    ctx = _l0().fetch_context("market.candles", {"symbol": "BTC", "days": 60, "bar": "1d"})
    data, meta = ctx["data"], ctx["meta"]
    assert data["has_ohlc"] is False  # 桶不全 → 不冒充完整 OHLC
    assert meta["ohlc_coverage"] == pytest.approx(0.975)
    uncovered = [p for p in data["points"] if "high" not in p]
    assert len(uncovered) == 1
    assert "low" not in uncovered[0]


def test_market_candles_without_ohlc_sub_keeps_close_only(candle_db):
    ctx = _l0().fetch_context("market.candles", {"symbol": "NOPE", "days": 30})
    assert ctx["degraded"] is False
    assert ctx["data"]["has_ohlc"] is False
    assert ctx["meta"]["ohlc_source"] == ""


# ============================================================
# S1-c：market.candles 1h（OHLC 子类小时级 last/high/low）
# ============================================================


@pytest.fixture
def candle_1h_db(tmp_path, monkeypatch):
    db = tmp_path / "core.db"
    rows = []
    base = NOW - 200 * 3600
    for i in range(150):
        ts = base + i * 3600
        rows += [
            ("ccxt", "BTC/USDT", "last", 100.0 + i, ts),
            ("ccxt", "BTC/USDT", "high", 101.0 + i, ts),
            ("ccxt", "BTC/USDT", "low", 99.0 + i, ts),
        ]
    # 脏小时（high=0）三腿不齐 → 该小时必须被剔除，不得回填
    extra = base + 150 * 3600
    rows += [
        ("ccxt", "BTC/USDT", "last", 250.0, extra),
        ("ccxt", "BTC/USDT", "high", 0.0, extra),
        ("ccxt", "BTC/USDT", "low", 249.0, extra),
    ]
    _make_db(str(db), rows)
    monkeypatch.setenv("DREAMBUDDY_CORE_DB", str(db))
    return str(db)


def test_market_candles_hourly_from_ohlc_sub(candle_1h_db):
    ctx = _l0().fetch_context("market.candles", {"symbol": "BTC", "days": 60, "bar": "1h"})
    data, meta = ctx["data"], ctx["meta"]
    assert data["sample_n"] == 150
    assert data["has_ohlc"] is True
    assert meta["bar"] == "1h" and meta["align_method"] == "hourly_last"
    assert meta["ohlc_coverage"] == 1.0
    last = data["points"][-1]
    assert last["close"] == pytest.approx(249.0)
    assert last["high"] == pytest.approx(250.0)
    assert last["low"] == pytest.approx(248.0)
    assert all("high" in p and "low" in p for p in data["points"])


def test_market_candles_hourly_without_ohlc_sub(candle_db):
    ctx = _l0().fetch_context("market.candles", {"symbol": "NOPE", "days": 30, "bar": "1h"})
    assert ctx["degraded"] is False
    assert ctx["data"]["sample_n"] == 0
    assert ctx["meta"]["reason"] == "no_ohlc_source"


# ============================================================
# S1-d：真实日线 OHLC（18 中心 1h 回填的 `*_1d`）优先于 ticker 合并
# ============================================================


@pytest.fixture
def candle_true_ohlc_db(tmp_path, monkeypatch):
    db = tmp_path / "core.db"
    rows = []
    for i in range(10):
        day = (NOW - (9 - i) * _DAY) // _DAY * _DAY
        rows += [
            ("binance", "BTC/USDT", "open_1d", 100.0 + i, day),
            ("binance", "BTC/USDT", "high_1d", 106.0 + i, day),
            ("binance", "BTC/USDT", "low_1d", 94.0 + i, day),
            ("binance", "BTC/USDT", "close_1d", 102.0 + i, day),
            ("binance", "BTC/USDT", "volume_1d", 500.0, day),
            # 干扰项：日频 close_usd 与 ticker 高低点均与真实日线不一致
            ("okx", "BTC", "close_usd", 200.0 + i, day),
            ("ccxt", "BTC/USDT", "high", 300.0 + i, day),
            ("ccxt", "BTC/USDT", "low", 150.0 + i, day),
        ]
    _make_db(str(db), rows)
    monkeypatch.setenv("DREAMBUDDY_CORE_DB", str(db))
    return str(db)


def test_market_candles_prefers_true_daily_ohlc(candle_true_ohlc_db):
    ctx = _l0().fetch_context("market.candles", {"symbol": "BTC", "days": 30, "bar": "1d"})
    data, meta = ctx["data"], ctx["meta"]
    assert data["sample_n"] == 10
    assert data["has_ohlc"] is True
    assert meta["ohlc_source"] == "mm_metrics:BTC/USDT#1d"
    assert meta["align_method"] == "binance_1h_agg"
    last = data["points"][-1]
    assert last["close"] == pytest.approx(111.0)  # 真实日线 close_1d，而非 close_usd=209
    assert last["high"] == pytest.approx(115.0)
    assert last["low"] == pytest.approx(103.0)
    assert last["open"] == pytest.approx(109.0)
    assert last["volume"] == pytest.approx(500.0)


def test_market_candles_true_ohlc_weekly_aggregation(candle_true_ohlc_db):
    ctx = _l0().fetch_context("market.candles", {"symbol": "BTC", "days": 30, "bar": "1w"})
    points = ctx["data"]["points"]
    assert ctx["data"]["has_ohlc"] is True
    expected = {}
    for i in range(10):
        day = datetime.datetime.fromtimestamp((NOW - (9 - i) * _DAY) // _DAY * _DAY, datetime.UTC)
        key = (day - datetime.timedelta(days=day.weekday())).strftime("%Y-%m-%d")
        expected.setdefault(key, []).append(i)
    for p in points:
        idxs = expected[p["timestamp"][:10]]
        assert p["open"] == pytest.approx(100.0 + min(idxs))
        assert p["high"] == pytest.approx(106.0 + max(idxs))
        assert p["low"] == pytest.approx(94.0 + min(idxs))
        assert p["close"] == pytest.approx(102.0 + max(idxs))
        assert p["volume"] == pytest.approx(500.0 * len(idxs))


def test_market_candles_true_ohlc_invalid_day_skipped(candle_true_ohlc_db):
    db = os.environ["DREAMBUDDY_CORE_DB"]
    bad_day = (NOW - 3 * _DAY) // _DAY * _DAY
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE mm_metrics SET metric_value = 130.0 WHERE sub_category = 'BTC/USDT' "
        "AND metric_name = 'close_1d' AND timestamp = ?",
        (bad_day,),
    )
    conn.commit()
    conn.close()

    ctx = _l0().fetch_context("market.candles", {"symbol": "BTC", "days": 30, "bar": "1d"})
    data = ctx["data"]
    assert data["sample_n"] == 9  # close>high 的非法日整天剔除
    assert all(p["high"] >= p["close"] >= p["low"] for p in data["points"])


# ============================================================
# 日线对齐（收盘锚点）：真实日线 00:00 vs 日频快照 16:00 → 同一 UTC 日键
# ============================================================


@pytest.fixture
def candle_mixed_db(tmp_path, monkeypatch):
    db = tmp_path / "core.db"
    rows = []
    for i in range(40):
        day_ts = NOW - (39 - i) * _DAY  # 12:00 观测 → 归一后为当日 00:00
        bar_ts = day_ts - 12 * 3600
        snap_ts = day_ts + 4 * 3600  # 16:00 快照
        rows += [
            ("binance", "BTC/USDT", "open_1d", 100.0 + i, bar_ts),
            ("binance", "BTC/USDT", "high_1d", 102.0 + i, bar_ts),
            ("binance", "BTC/USDT", "low_1d", 98.0 + i, bar_ts),
            ("binance", "BTC/USDT", "close_1d", 100.0 + i, bar_ts),
            ("binance", "BTC/USDT", "volume_1d", 10.0, bar_ts),
            ("okx", "BTC", "close_usd", 100.5 + i, snap_ts),
            ("okx", "ETH", "close_usd", 50.0 + i, snap_ts),
        ]
    _make_db(str(db), rows)
    monkeypatch.setenv("DREAMBUDDY_CORE_DB", str(db))
    return str(db)


def test_candles_close_anchor_bar_vs_snapshot(candle_mixed_db):
    auto = _l0().fetch_context("market.candles", {"symbol": "BTC", "days": 60, "bar": "1d"})
    assert auto["meta"]["close_anchor"] == "bar_close"
    assert all(p["ts"] % _DAY == 0 for p in auto["data"]["points"])

    snap = _l0().fetch_context(
        "market.candles",
        {"symbol": "BTC", "days": 60, "bar": "1d", "source_policy": "snapshot"},
    )
    assert snap["meta"]["close_anchor"] == "snapshot_last"
    pts = snap["data"]["points"]
    # 日键归一到 UTC 日首，真实观测时刻保留在 close_ts
    assert all(p["ts"] % _DAY == 0 for p in pts)
    assert pts[-1]["close"] == pytest.approx(139.5)
    assert pts[-1]["close_ts"].endswith("T16:00:00Z")


def test_candles_snapshot_policy_aligns_cross_symbol_day_keys(candle_mixed_db):
    btc = _l0().fetch_context(
        "market.candles",
        {"symbol": "BTC", "days": 60, "bar": "1d", "source_policy": "snapshot"},
    )
    eth = _l0().fetch_context(
        "market.candles",
        {"symbol": "ETH", "days": 60, "bar": "1d", "source_policy": "snapshot"},
    )
    assert btc["meta"]["close_anchor"] == eth["meta"]["close_anchor"] == "snapshot_last"
    assert [p["timestamp"] for p in btc["data"]["points"]] == [
        p["timestamp"] for p in eth["data"]["points"]
    ]


def test_candles_bars_policy_requires_true_bars(candle_mixed_db):
    ctx = _l0().fetch_context(
        "market.candles",
        {"symbol": "ETH", "days": 60, "bar": "1d", "source_policy": "bars"},
    )
    assert ctx["degraded"] is False
    assert ctx["data"]["sample_n"] == 0
    assert ctx["meta"]["reason"] == "no_true_bars"
    assert ctx["meta"]["close_anchor"] == "bar_close"


def test_candles_invalid_source_policy(candle_mixed_db):
    ctx = _l0().fetch_context(
        "market.candles", {"symbol": "BTC", "days": 60, "source_policy": "ffill"}
    )
    assert ctx["degraded"] is True
    assert ctx["meta"]["reason"] == "invalid_params"
