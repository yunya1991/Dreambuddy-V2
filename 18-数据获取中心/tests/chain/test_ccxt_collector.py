"""CCXT collector 测试 — 迁移自 flow_collector 交易所行情。

ccxt 薄封装，fetch_ticker -> DataRecord(category=chain)。
"""
from data_center.collectors.chain.ccxt_collector import CcxtCollector
from data_center.core.contract import DataRecord

CCXT_MOD = "data_center.collectors.chain.ccxt_collector.ccxt"


def test_fetch_ticker(mocker):
    mock_ccxt = mocker.patch(CCXT_MOD)
    mock_exchange = mock_ccxt.binance.return_value
    mock_exchange.fetch_ticker.return_value = {
        "symbol": "BTC/USDT", "last": 60000.0, "bid": 59999.0, "ask": 60001.0,
        "high": 61000.0, "low": 59000.0, "volume": 123.4,
    }
    c = CcxtCollector()
    recs = c.fetch({"symbol": "BTC/USDT", "exchange": "binance", "kind": "ticker"})
    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "ccxt"
    assert r.category == "chain"
    assert r.sub_category == "BTC/USDT"
    assert r.metrics["last"] == 60000.0
    assert r.metrics["exchange"] == "binance"
    assert r.metrics["volume"] == 123.4
    assert r.metrics["bid"] == 59999.0


def test_is_available_true():
    assert CcxtCollector().is_available() is True
