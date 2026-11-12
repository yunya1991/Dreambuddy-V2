"""统一价格源（G10）单测：口径映射 / 分页 / fallback / 缓存。

全部离线：网络层 `_get_json` 一律 monkeypatch，不触达交易所。
"""

from __future__ import annotations

import json

import pytest
from data_center.market import price_source as ps

DAY = 86_400_000
T0 = 1_700_000_000_000


def _okx_rows(n: int, start_ts: int = T0, confirm: str = "1") -> list[list]:
    return [
        [str(start_ts + i * DAY), "1", "2", "0.5", str(10 + i), "100", "0", "0", confirm]
        for i in range(n)
    ]


# ── 口径映射 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "inst"),
    [
        ("BTC/USDT", "BTC-USDT-SWAP"),
        ("BTC/USDT:USDT", "BTC-USDT-SWAP"),
        ("BTC-USDT-SWAP", "BTC-USDT-SWAP"),
        ("eth-usdt", "ETH-USDT-SWAP"),
        ("XAU", "XAU-USDT-SWAP"),
    ],
)
def test_to_inst_id(raw, inst):
    assert ps.to_inst_id(raw) == inst


def test_to_binance_symbol():
    assert ps.to_binance_symbol("BTC/USDT:USDT") == "BTCUSDT"
    assert ps.to_binance_symbol("XAU-USDT-SWAP") == "XAUUSDT"


def test_okx_bar_drops_unclosed():
    closed = ps._okx_bar(_okx_rows(1)[0])
    assert closed == {
        "ts_ms": T0,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 10.0,
        "volume": 100.0,
        "source": "okx",
    }
    assert ps._okx_bar(_okx_rows(1, confirm="0")[0]) is None
    assert ps._okx_bar(["1", "2"]) is None


# ── 分页与去重 ───────────────────────────────────────────────


def test_okx_daily_paginates_and_dedupes(monkeypatch):
    """两页各 100 根、时间不重叠 → 去重后按 ts 升序，截断到 days。"""
    first = _okx_rows(100, start_ts=T0 + 100 * DAY)
    second = _okx_rows(100, start_ts=T0)

    def fake_get(url, **_kwargs):
        if "history-candles" in url:
            return {"code": "0", "data": list(reversed(second))}
        return {"code": "0", "data": list(reversed(first))}

    monkeypatch.setattr(ps, "_get_json", fake_get)
    bars = ps._okx_daily("BTC-USDT-SWAP", days=150)

    assert len(bars) == 150
    assert [b["ts_ms"] for b in bars] == sorted(b["ts_ms"] for b in bars)
    assert len({b["ts_ms"] for b in bars}) == 150


def test_okx_daily_stops_on_empty_page(monkeypatch):
    def fake_get(url, **_kwargs):
        if "candles?" in url:
            return {"code": "0", "data": _okx_rows(3)}
        return {"code": "0", "data": []}

    monkeypatch.setattr(ps, "_get_json", fake_get)
    assert len(ps._okx_daily("BTC-USDT-SWAP", days=100)) == 3


# ── 主源 / fallback ──────────────────────────────────────────


def test_fetch_daily_falls_back_to_binance(monkeypatch):
    monkeypatch.setattr(ps, "_okx_daily", lambda *_a, **_k: [])
    binance_bar = ps._okx_bar(_okx_rows(1)[0]) | {"source": "binance"}
    monkeypatch.setattr(ps, "_binance_daily", lambda *_a, **_k: [binance_bar])

    result = ps.fetch_daily("BTC/USDT", days=10)
    assert result["source"] == "binance"
    assert result["fallback_used"] is True
    assert result["inst_id"] == "BTC-USDT-SWAP"


def test_fetch_daily_raises_when_all_sources_empty(monkeypatch):
    monkeypatch.setattr(ps, "_okx_daily", lambda *_a, **_k: [])
    monkeypatch.setattr(ps, "_binance_daily", lambda *_a, **_k: [])

    with pytest.raises(ps.PriceSourceError):
        ps.fetch_daily("BTC/USDT", days=10)


def test_fetch_closes_returns_ascending_closes(monkeypatch):
    bars = [ps._okx_bar(row) for row in _okx_rows(3)]
    monkeypatch.setattr(ps, "fetch_daily", lambda *_a, **_k: {"bars": bars})
    assert ps.fetch_closes("BTC", days=3) == [10.0, 11.0, 12.0]


# ── 缓存 roundtrip ───────────────────────────────────────────


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "CACHE_DIR", tmp_path / "ohlcv")
    return tmp_path / "ohlcv"


def test_write_and_read_cache_roundtrip(cache_dir):
    bars = [ps._okx_bar(row) for row in _okx_rows(3)]
    meta = ps.write_cache(
        "BTC",
        {
            "bars": bars,
            "source": "okx",
            "fallback_used": False,
            "n_bars": 3,
            "first": "x",
            "last": "y",
        },
    )

    assert meta["n_bars"] == 3
    assert meta["n_gaps"] == 0
    assert (cache_dir / "BTC_1D.csv").is_file()
    on_disk = json.loads((cache_dir / "BTC_1D.meta.json").read_text(encoding="utf-8"))
    assert on_disk["source"] == "okx"

    df = ps.read_cache("BTC")
    assert list(df.columns) == ["date", *ps.CANONICAL_COLUMNS]
    assert df["close"].tolist() == [10.0, 11.0, 12.0]


def test_write_cache_records_gaps(cache_dir):
    rows = _okx_rows(2) + _okx_rows(2, start_ts=T0 + 4 * DAY)
    bars = [ps._okx_bar(row) for row in rows]
    meta = ps.write_cache(
        "BTC",
        {
            "bars": bars,
            "source": "okx",
            "fallback_used": False,
            "n_bars": 4,
            "first": "x",
            "last": "y",
        },
    )
    assert meta["n_gaps"] == 1
    assert meta["missing_days_total"] == 2


def test_load_daily_serves_cache_without_network(cache_dir, monkeypatch):
    bars = [ps._okx_bar(row) for row in _okx_rows(5)]
    ps.write_cache(
        "BTC",
        {
            "bars": bars,
            "source": "okx",
            "fallback_used": False,
            "n_bars": 5,
            "first": "x",
            "last": "y",
        },
    )
    monkeypatch.setattr(ps, "fetch_daily", lambda *_a, **_k: pytest.fail("不应回源"))

    df, meta = ps.load_daily("BTC", days=5)
    assert len(df) == 5
    assert meta["source"] == "okx"


# ── 静态守护：40 域不得直连交易所取日线 ──────────────────────


def test_no_direct_exchange_in_40_domain():
    """G10 硬约束：40 域生产脚本的价格必须走本模块（仅允许 funding/OI 与指数序列例外）。"""
    root = ps._BASE.parent / "40-周期神经网络系统"
    offenders = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("fetch_ohlcv(", "ccxt.binance(", "ccxt.bybit("):
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert offenders == []
