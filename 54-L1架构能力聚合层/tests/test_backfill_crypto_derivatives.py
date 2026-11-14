# -*- coding: utf-8 -*-
"""加密域内回填测试（离线，网络层全部注入假 fetcher/假响应）。"""

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

from backfill_crypto_derivatives import (  # noqa: E402
    TARGETS,
    UNBOUND,
    fetch_binance_funding,
    fetch_binance_vision_oi,
    fetch_okx_funding,
    fetch_okx_long_short,
    fetch_okx_oi,
    oi_as_market,
    parse_farside_markdown,
    parse_vision_metrics_csv,
    run,
)

_TODAY = datetime.date(2026, 11, 14)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, source, sub_category, metric_name, value, ts):
        self.calls.append((source, sub_category, metric_name, value, ts))
        return True


def _rows(n=3, end=_TODAY, metric="m"):
    return [
        {
            "ts": datetime.datetime.combine(
                end - datetime.timedelta(days=n - 1 - i), datetime.time(), datetime.UTC
            ),
            "values": {metric: float(i)},
        }
        for i in range(n)
    ]


def _fake_fetchers(n=3):
    return {t["key"]: (lambda start, today: _rows(n)) for t in TARGETS}


def test_targets_cover_crypto_plan():
    """覆盖 OI / 多空 / 资金费率 / ETF；清算诚实登记为未采集。"""
    keys = {t["key"] for t in TARGETS}
    assert {
        "okx_oi",
        "oi_market",
        "okx_ls",
        "okx_ls_top",
        "okx_funding",
        "binance_funding",
        "binance_oi",
        "etf_flow",
    } == keys
    assert "liquidation" in UNBOUND


def test_storage_contract_per_target():
    """OI/费率落 okx_derivatives，长历史费率落 funding_rate，ETF 落 farside。"""
    rec = Recorder()
    run(_fake_fetchers(2), rec, only=["okx_oi", "binance_funding", "etf_flow"], today=_TODAY)
    keys = {(c[0], c[1], c[2]) for c in rec.calls}
    assert keys == {
        ("okx_derivatives", "okx_derivatives", "m"),
        ("binance_funding_rate", "funding_rate", "m"),
        ("farside", "etf_flow", "m"),
    }


def test_run_dry_run_writes_nothing():
    rec = Recorder()
    stats = run(_fake_fetchers(4), rec, dry_run=True, only=["okx_oi"], today=_TODAY)
    assert rec.calls == []
    assert stats["targets"][0]["written"] == 4
    assert stats["total_written"] == 4


def test_run_records_fetch_error_and_continues():
    def flaky(start, today):
        raise RuntimeError("HTTP 429")

    fetchers = {t["key"]: flaky for t in TARGETS}
    fetchers["okx_ls"] = lambda start, today: _rows(2)
    stats = run(fetchers, Recorder(), only=["okx_oi", "okx_ls"], today=_TODAY)
    assert stats["ok"] is False
    by_key = {r["key"]: r for r in stats["targets"]}
    assert "429" in by_key["okx_oi"]["errors"][0]
    assert by_key["okx_ls"]["written"] == 2


def test_fetch_okx_oi_filters_and_sorts(monkeypatch):
    body = {"data": [["1794657600000", "3468276281.7"], ["1794571200000", "3300000000.0"]]}
    monkeypatch.setattr("backfill_crypto_derivatives._get_json", lambda url, timeout=30.0: body)
    rows = fetch_okx_oi(start=datetime.date(2026, 11, 12))
    assert [r["values"]["open_interest_usd"] for r in rows] == [3300000000.0, 3468276281.7]
    assert rows[0]["ts"].tzinfo is datetime.UTC


def test_fetch_okx_long_short_derives_pcts(monkeypatch):
    body = {"data": [["1794657600000", "1.61"]]}
    monkeypatch.setattr("backfill_crypto_derivatives._get_json", lambda url, timeout=30.0: body)
    row = fetch_okx_long_short()[0]
    assert row["values"]["long_short_ratio"] == 1.61
    assert row["values"]["long_account_pct"] == pytest.approx(61.69, abs=0.01)
    assert row["values"]["short_account_pct"] == pytest.approx(38.31, abs=0.01)


def test_fetch_okx_funding_pages_backwards(monkeypatch):
    pages = {
        None: [
            {"fundingTime": "1794657600000", "fundingRate": "0.0001"},
            {"fundingTime": "1794628800000", "fundingRate": "-0.0002"},
        ],
        1794628800000: [
            {"fundingTime": "1794600000000", "fundingRate": "0.0003"},
        ],
    }

    def fake_get(url, timeout=30.0):
        cursor = None
        if "after=" in url:
            cursor = int(url.split("after=")[1])
        return {"data": pages.get(cursor, [])}

    monkeypatch.setattr("backfill_crypto_derivatives._get_json", fake_get)
    rows = fetch_okx_funding(start=datetime.date(2026, 11, 12))
    assert [r["values"]["funding_rate_pct"] for r in rows] == [
        pytest.approx(0.03),
        pytest.approx(-0.02),
        pytest.approx(0.01),
    ]


def test_fetch_binance_funding_paginates(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, timeout=30.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                {"fundingTime": "1794600000000", "fundingRate": "0.0001"},
                {"fundingTime": "1794628800000", "fundingRate": "0.0002"},
            ] * 500  # 恰好满页 → 触发下一页
        return [{"fundingTime": "1794657600000", "fundingRate": "0.0003"}]

    monkeypatch.setattr("backfill_crypto_derivatives._get_json", fake_get)
    rows = fetch_binance_funding(start=datetime.date(2026, 11, 1))
    assert calls["n"] == 2
    assert rows[-1]["values"]["funding_rate_pct"] == pytest.approx(0.03)


def test_oi_as_market_renames_metric():
    """聚合口径 OI 单列 `_ccy` 指标，避免污染 ccxt 单合约的规范序列。"""
    rows = [{"ts": _rows(1)[0]["ts"], "values": {"open_interest_usd": 3.4e9}}]
    assert oi_as_market(rows) == [
        {"ts": rows[0]["ts"], "values": {"open_interest_value_ccy": 3.4e9}}
    ]


def test_parse_farside_markdown():
    text = (
        "| Date | IBIT | FBTC | Total |\n"
        "| --- | --- | --- | --- |\n"
        "| 12 Nov 2026 | 111.7 | (95.1) | 16.6 |\n"
        "| 11 Nov 2026 | - | 0.0 | (20.0) |\n"
        "| Total | 1.0 | 2.0 | 3.0 |\n"
    )
    rows = parse_farside_markdown(text, start=datetime.date(2026, 11, 1))
    assert len(rows) == 2
    assert rows[0]["values"] == {"IBIT": 0.0, "FBTC": 0.0, "total_flow": -20.0}
    assert rows[1]["values"] == {"IBIT": 111.7, "FBTC": -95.1, "total_flow": 16.6}


def _vision_zip(value: float, amount: float) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "BTCUSDT-metrics-2026-11-10.csv",
            "create_time,symbol,sum_open_interest,sum_open_interest_value,"
            "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
            "count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
            f"2026-11-10 00:00:00,BTCUSDT,{amount - 1},{value - 1},1,1,1,1\n"
            f"2026-11-10 23:55:00,BTCUSDT,{amount},{value},1,1,1,1\n",
        )
    return buf.getvalue()


def test_parse_vision_metrics_csv_takes_last_row():
    rows = (
        "create_time,symbol,sum_open_interest,sum_open_interest_value\n"
        "2026-11-10 00:00:00,BTCUSDT,90000,8000000000\n"
        "2026-11-10 23:55:00,BTCUSDT,92000,8700000000\n"
    )
    assert parse_vision_metrics_csv(rows) == {
        "open_interest_value_binance": 8700000000.0,
        "open_interest_btc_binance": 92000.0,
    }
    assert parse_vision_metrics_csv("not,a,metrics,file") is None


def test_fetch_binance_vision_skips_404(monkeypatch):
    """缺文件（404）跳过，不伪造；只回填已存在的日子。"""

    def fake_get_bytes(url, timeout=30.0):
        return _vision_zip(8.7e9, 92000.0) if "2026-11-10" in url else None

    monkeypatch.setattr("backfill_crypto_derivatives._get_bytes", fake_get_bytes)
    rows = fetch_binance_vision_oi(datetime.date(2026, 11, 10), today=datetime.date(2026, 11, 12))
    assert len(rows) == 1
    assert rows[0]["ts"].date() == datetime.date(2026, 11, 10)
    assert rows[0]["values"]["open_interest_value_binance"] == pytest.approx(8.7e9)


def test_run_idempotent_against_sqlite(tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (
        SqliteMarketMacroRepository,
    )

    db = tmp_path / "core.db"
    repo = SqliteMarketMacroRepository(str(db))
    run(_fake_fetchers(10), repo.upsert_metric, only=["okx_oi"], today=_TODAY)
    first = _count(str(db))
    run(_fake_fetchers(10), repo.upsert_metric, only=["okx_oi"], today=_TODAY)
    assert _count(str(db)) == first == 10


def _count(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM mm_metrics WHERE sub_category='okx_derivatives'"
        ).fetchone()[0]
    finally:
        conn.close()
