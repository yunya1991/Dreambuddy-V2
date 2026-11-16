# -*- coding: utf-8 -*-
"""跨资产龙头回填测试（离线，网络层全部注入假 fetcher）。"""

import datetime
import os
import sqlite3
import sys
import urllib.error

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_SCRIPTS_DIR = os.path.join(_MODULE_ROOT, "scripts")
_DAL_ROOT = os.path.join(_MODULE_ROOT, "..", "19-数据访问层")
for _p in (_MODULE_ROOT, _SCRIPTS_DIR, _DAL_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backfill_cross_asset_leaders import (  # noqa: E402
    TARGETS,
    _get,
    fetch_fred,
    fetch_nasdaq,
    run,
)

_TODAY = datetime.date(2026, 11, 14)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, source, sub_category, metric_name, value, ts):
        self.calls.append((source, sub_category, metric_name, value, ts))
        return True


def _rows(n, end=_TODAY):
    return [
        {"date": end - datetime.timedelta(days=n - 1 - i), "close": 100.0 + i} for i in range(n)
    ]


def _fake_fetchers(n=5):
    return {venue: (lambda target, start: _rows(n)) for venue in ("nasdaq", "okx", "fred")}


def test_targets_cover_backfill_plan():
    """回填清单覆盖美股龙头/ETF、金属、能源；JP225 因历史不足不纳入。"""
    symbols = {t["symbol"] for t in TARGETS}
    assert {"DJIA", "NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "META"} <= symbols
    assert {"SPY", "QQQ", "XAG", "XCU", "BZ", "NG"} <= symbols
    assert "JP225" not in symbols


def test_storage_contract_price_vs_series():
    """价格类写 <SYMBOL>.close_usd；FRED 系列写 <SERIES_ID>.value。"""
    rec = Recorder()
    run(_fake_fetchers(2), rec, years=3, only=["NVDA", "XAG", "BZ"], today=_TODAY)
    keys = {(c[0], c[1], c[2]) for c in rec.calls}
    assert keys == {
        ("nasdaq", "NVDA", "close_usd"),
        ("okx", "XAG", "close_usd"),
        ("fred", "DCOILBRENTEU", "value"),
    }
    # 时间戳按 UTC 日 00:00 落库
    assert rec.calls[0][4] == datetime.datetime(2026, 11, 13, tzinfo=datetime.UTC)


def test_run_dry_run_writes_nothing():
    rec = Recorder()
    stats = run(_fake_fetchers(3), rec, dry_run=True, only=["NVDA"], today=_TODAY)
    assert rec.calls == []
    assert stats["targets"][0]["written"] == 3


def test_run_writes_volume_and_amount_for_nasdaq():
    """美股有成交量时额外落 volume / amount_usd；OKX/FRED 不应产生这两个指标。"""

    def nasdaq_rows(target, start):
        return [
            {
                "date": _TODAY - datetime.timedelta(days=1),
                "close": 100.0,
                "volume": 1_000.0,
                "amount": 100_000.0,
            },
        ]

    rec = Recorder()
    stats = run({"nasdaq": nasdaq_rows}, rec, only=["NVDA"], today=_TODAY)
    keys = {(c[0], c[1], c[2]) for c in rec.calls}
    assert keys == {
        ("nasdaq", "NVDA", "close_usd"),
        ("nasdaq", "NVDA", "volume"),
        ("nasdaq", "NVDA", "amount_usd"),
    }
    assert stats["targets"][0]["volume_written"] == 1
    assert stats["total_volume_written"] == 1


def test_run_records_fetch_error_and_continues():
    calls = {"n": 0}

    def flaky(target, start):
        calls["n"] += 1
        if target["symbol"] == "NVDA":
            raise RuntimeError("HTTP 429")
        return _rows(2)

    stats = run(
        {"nasdaq": flaky, "okx": flaky, "fred": flaky},
        Recorder(),
        only=["NVDA", "AAPL"],
        today=_TODAY,
    )
    assert stats["ok"] is False
    by_symbol = {r["symbol"]: r for r in stats["targets"]}
    assert "429" in by_symbol["NVDA"]["errors"][0]
    assert by_symbol["AAPL"]["written"] == 2


def test_get_falls_back_to_curl_on_403(monkeypatch):
    """Nasdaq 对 Python urllib 返回 403 时回退 curl（本机 2026-11-16 实测）。"""

    def boom(req, timeout=25.0):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", None, None)

    monkeypatch.setattr("backfill_cross_asset_leaders.urllib.request.urlopen", boom)
    seen = {}
    monkeypatch.setattr(
        "backfill_cross_asset_leaders._curl_json",
        lambda url, timeout=40.0: seen.setdefault("url", url) and '{"ok": 1}',
    )
    assert _get("https://api.nasdaq.com/x") == '{"ok": 1}'
    assert "nasdaq" in seen["url"]


def test_fetch_nasdaq_parses_and_filters(monkeypatch):
    body = {
        "data": {
            "tradesTable": {
                "rows": [
                    {"date": "11/13/2026", "close": "$162.85", "volume": "365,796,600"},
                    {"date": "11/12/2026", "close": "$1,166.19", "volume": "N/A"},
                    {"date": "bad-date", "close": "$1.00"},
                    {"date": "11/11/2026", "close": "N/A"},
                ]
            }
        }
    }
    monkeypatch.setattr(
        "backfill_cross_asset_leaders._get",
        lambda url, timeout=25.0: __import__("json").dumps(body),
    )
    rows = fetch_nasdaq("NVDA", "stocks", datetime.date(2026, 1, 1), _TODAY)
    assert [r["close"] for r in rows] == [1166.19, 162.85]
    assert rows[0]["date"] == datetime.date(2026, 11, 12)
    # 成交量缺失记为 0；成交额 = close × volume
    assert rows[0]["volume"] == 0.0
    assert rows[1]["volume"] == 365796600.0
    assert round(rows[1]["amount"], 2) == round(162.85 * 365796600, 2)


def test_fetch_fred_skips_missing_and_window(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    csv_text = "observation_date,DCOILBRENTEU\n2026-11-10,64.1\n2026-11-11,\n2026-11-12,63.5\n2020-01-02,68.9\n"
    monkeypatch.setattr("backfill_cross_asset_leaders._curl", lambda url, timeout=60.0: csv_text)
    rows = fetch_fred("DCOILBRENTEU", datetime.date(2026, 1, 1))
    assert [r["date"].isoformat() for r in rows] == ["2026-11-10", "2026-11-12"]
    assert rows[-1]["close"] == 63.5


def test_fetch_fred_prefers_api_when_key(monkeypatch):
    """有 Key 走 api.stlouisfed.org（fredgraph.csv 对云端出口 IP 会 RST）。"""
    seen = {}

    def fake_get(url, timeout=25.0):
        seen["url"] = url
        return (
            '{"observations": [{"date": "2026-11-12", "value": "63.5"},'
            ' {"date": "2026-11-11", "value": "."},'
            ' {"date": "2026-10-01", "value": "67.2"}]}'
        )

    monkeypatch.setattr("backfill_cross_asset_leaders._curl", fake_get)
    rows = fetch_fred("DHHNGSP", datetime.date(2026, 1, 1), api_key="k-test")
    assert "api.stlouisfed.org" in seen["url"]
    assert "observation_start=2026-01-01" in seen["url"]
    assert [r["close"] for r in rows] == [67.2, 63.5]


def test_run_idempotent_against_sqlite(tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (
        SqliteMarketMacroRepository,
    )

    db = tmp_path / "core.db"
    repo = SqliteMarketMacroRepository(str(db))
    run(_fake_fetchers(10), repo.upsert_metric, only=["NVDA"], today=_TODAY)
    first = _count(str(db))
    run(_fake_fetchers(10), repo.upsert_metric, only=["NVDA"], today=_TODAY)
    assert _count(str(db)) == first == 10

    conn = sqlite3.connect(str(db))
    try:
        value = conn.execute(
            "SELECT metric_value FROM mm_metrics WHERE sub_category='NVDA' "
            "AND metric_name='close_usd' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()
    assert value == pytest.approx(109.0)


def _count(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM mm_metrics WHERE sub_category='NVDA' AND metric_name='close_usd'"
        ).fetchone()[0]
    finally:
        conn.close()
