"""compat/flow_compat 测试 — fetch_yahoo/fred 走 DataCenter + run_full_collection 转发。

fetch_yahoo_symbol 和 fetch_fred_series 用 YFinanceCollector/FredCollector 替换手写 HTTP；
run_full_collection 是复杂编排器，compat 版转发老实现 + 发 DeprecationWarning。
"""
import warnings
import pytest

from data_center.compat.flow_compat import (
    fetch_yahoo_symbol,
    fetch_fred_series,
    run_full_collection,
)

YF_MOD = "data_center.compat.flow_compat.YFinanceCollector"
FRED_MOD = "data_center.compat.flow_compat.FredCollector"
FLOW_MOD = "data_center.compat.flow_compat._run_full_collection_legacy"


def test_fetch_yahoo_symbol(mocker):
    """YFinanceCollector → 兼容 dict 返回。"""
    from data_center.core.contract import DataRecord
    import pandas as pd

    mock_cls = mocker.patch(YF_MOD)
    mock_collector = mock_cls.return_value
    mock_collector.is_available.return_value = True
    mock_collector.fetch.return_value = [
        DataRecord(
            source="yfinance", category="finance", sub_category="DX-Y.NYB",
            timestamp="2026-08-24T12:00:00+08:00",
            metrics={"symbol": "DX-Y.NYB", "price": 104.5, "currency": "USD"},
            events=[], timeseries=[],
            raw={"close": [104.5]},
        )
    ]

    result = fetch_yahoo_symbol("DX-Y.NYB")
    assert result is not None
    assert result["symbol"] == "DX-Y.NYB"
    assert result["price"] == 104.5
    assert result["currency"] == "USD"


def test_fetch_yahoo_symbol_none_on_error(mocker):
    mock_cls = mocker.patch(YF_MOD)
    mock_collector = mock_cls.return_value
    mock_collector.is_available.return_value = True
    mock_collector.fetch.return_value = []

    assert fetch_yahoo_symbol("INVALID") is None


def test_fetch_fred_series(mocker):
    from data_center.core.contract import DataRecord

    mock_cls = mocker.patch(FRED_MOD)
    mock_collector = mock_cls.return_value
    mock_collector.is_available.return_value = True
    mock_collector.fetch.return_value = [
        DataRecord(
            source="fred", category="macro", sub_category="FEDFUNDS",
            timestamp="2026-08-24T12:00:00+08:00",
            metrics={"value": 5.5, "series": "FEDFUNDS"},
            events=[], timeseries=[{"date": "2024-07", "value": 5.5}],
            raw={"observations": [{"value": "5.5"}]},
        )
    ]

    result = fetch_fred_series("FEDFUNDS", api_key="fake")
    assert result is not None
    assert result["series_id"] == "FEDFUNDS"
    assert result["value"] == 5.5


def test_fetch_fred_series_no_key(mocker):
    mock_cls = mocker.patch(FRED_MOD)
    mock_collector = mock_cls.return_value
    mock_collector.is_available.return_value = False

    assert fetch_fred_series("FEDFUNDS") is None


def test_run_full_collection_deprecated(mocker):
    """run_full_collection 转发老实现 + 发 DeprecationWarning。"""
    mock_legacy = mocker.patch(FLOW_MOD)
    mock_legacy.return_value = {"collection_timestamp": "2026-08-24", "layers": {}}

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = run_full_collection()

    assert result["collection_timestamp"] == "2026-08-24"
    assert len(w) == 1
    assert issubclass(w[0].category, DeprecationWarning)
    assert "data_center" in str(w[0].message).lower()
