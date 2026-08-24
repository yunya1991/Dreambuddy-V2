"""YFinance collector 测试 — 迁移自 flow_collector.fetch_yahoo_symbol（DXY/美债）。

yfinance 薄封装，产出 DataRecord(category=finance)。
"""
import pandas as pd
import pytest

from data_center.collectors.finance.yfinance_collector import YFinanceCollector
from data_center.core.contract import DataRecord

YF_MOD = "data_center.collectors.finance.yfinance_collector.yf"


def _df():
    idx = pd.DatetimeIndex(["2026-08-21", "2026-08-22"])
    return pd.DataFrame({"Close": [100.0, 102.5]}, index=idx)


def test_fetch_returns_datarecord(mocker):
    mocker.patch(YF_MOD).Ticker.return_value.history.return_value = _df()
    c = YFinanceCollector()
    recs = c.fetch({"symbol": "DX-Y.NYB"})
    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "yfinance"
    assert r.category == "finance"
    assert r.sub_category == "DX-Y.NYB"
    assert r.metrics["price"] == 102.5
    assert r.metrics["symbol"] == "DX-Y.NYB"
    assert r.timeseries[0]["close"] == 102.5


def test_empty_history_returns_empty(mocker):
    mocker.patch(YF_MOD).Ticker.return_value.history.return_value = pd.DataFrame()
    c = YFinanceCollector()
    assert c.fetch({"symbol": "^TNX"}) == []


def test_is_available_default_true():
    assert YFinanceCollector().is_available() is True
