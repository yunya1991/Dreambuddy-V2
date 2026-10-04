"""EventMarketReactionCollector 测试 — 事件前后价格快照。

覆盖：资产价格快照采集、事件窗口判定、FAIL-OPEN、DataRecord 契约。
"""
import pytest

from data_center.collectors.macro.event_market_reaction_collector import (
    EventMarketReactionCollector,
)
from data_center.core.contract import DataRecord

REACTION_MOD = "data_center.collectors.macro.event_market_reaction_collector"


def test_source_category():
    assert EventMarketReactionCollector.source == "event_reaction"
    assert EventMarketReactionCollector.category == "macro"


def test_fetch_price_snapshot(mocker):
    """采集指定资产的价格快照。"""
    mock_price = mocker.patch(f"{REACTION_MOD}._fetch_price_data")
    mock_price.return_value = [
        {"date": "2026-09-15", "close": 4350.0},
        {"date": "2026-09-16", "close": 4320.0},
        {"date": "2026-09-17", "close": 4280.0},
    ]

    c = EventMarketReactionCollector()
    recs = c.fetch({
        "symbol": "gold",
        "event_date": "2026-09-16",
        "days_before": 1,
        "days_after": 1,
    })

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.sub_category == "gold"
    assert r.metrics["event_date"] == "2026-09-16"
    assert r.metrics["price_before"] == 4350.0
    assert r.metrics["price_event"] == 4320.0
    assert r.metrics["price_after"] == 4280.0
    assert r.metrics["change_pct"] == pytest.approx(-0.92, abs=0.01)  # (4280-4320)/4320


def test_supported_symbols():
    """支持的资产列表。"""
    c = EventMarketReactionCollector()
    assert "gold" in c.SUPPORTED_SYMBOLS
    assert "btc" in c.SUPPORTED_SYMBOLS
    assert "dxy" in c.SUPPORTED_SYMBOLS
    assert "us10y" in c.SUPPORTED_SYMBOLS


def test_unsupported_symbol_returns_empty():
    c = EventMarketReactionCollector()
    assert c.fetch({"symbol": "eth", "event_date": "2026-09-16"}) == []


def test_fail_open_when_price_unavailable(mocker):
    """价格数据不可用时降级返回空。"""
    mock_price = mocker.patch(f"{REACTION_MOD}._fetch_price_data")
    mock_price.side_effect = Exception("yfinance error")

    c = EventMarketReactionCollector()
    recs = c.fetch({"symbol": "gold", "event_date": "2026-09-16"})
    assert recs == []


def test_no_event_date_returns_empty():
    c = EventMarketReactionCollector()
    assert c.fetch({"symbol": "gold"}) == []


def test_change_pct_calculation(mocker):
    """涨跌幅计算：(price_after - price_event) / price_event。"""
    mock_price = mocker.patch(f"{REACTION_MOD}._fetch_price_data")
    mock_price.return_value = [
        {"date": "2026-09-15", "close": 100.0},
        {"date": "2026-09-16", "close": 100.0},
        {"date": "2026-09-17", "close": 105.0},
    ]

    c = EventMarketReactionCollector()
    recs = c.fetch({"symbol": "btc", "event_date": "2026-09-16"})
    assert recs[0].metrics["change_pct"] == pytest.approx(5.0, abs=0.01)
