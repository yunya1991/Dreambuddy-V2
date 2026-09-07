"""YFinance stock_info / stock_financials 路由测试 — TDD 先红后绿。

覆盖 2 类新路由 + 向后兼容：
- stock_info：yf.Ticker(symbol).info → trailingPE / forwardPE / operatingMargins / returnOnEquity / marketCap / revenueGrowth
- stock_financials：yf.Ticker(symbol).financials → 营收/盈利季度 DataFrame
- 无 route 参数 → 走原有价格获取逻辑（向后兼容）

yfinance 薄封装，产出 DataRecord(category=finance)。
"""
import pandas as pd
import pytest

from data_center.core.contract import DataRecord

YF_MOD = "data_center.collectors.finance.yfinance_collector.yf"


def _info_resp():
    """模拟 yf.Ticker('NVDA').info 响应。"""
    return {
        "trailingPE": 65.5,
        "forwardPE": 55.2,
        "operatingMargins": 0.337,
        "returnOnEquity": 0.91,
        "marketCap": 3_000_000_000_000,
        "revenueGrowth": 0.94,
        "longName": "NVIDIA Corporation",
        "currency": "USD",
    }


def _financials_df():
    """模拟 yf.Ticker('NVDA').financials 响应。"""
    return pd.DataFrame(
        {
            "2025-07-31": [30_040_000_000, 16_600_000_000, 18_750_000_000],
            "2025-04-30": [26_040_000_000, 14_810_000_000, 16_550_000_000],
            "2025-01-31": [22_100_000_000, 12_540_000_000, 14_020_000_000],
            "2024-10-31": [18_120_000_000, 9_500_000_000, 10_490_000_000],
        },
        index=["Total Revenue", "Net Income", "EBITDA"],
    )


# ---------------------------------------------------------------------------
# stock_info 路由
# ---------------------------------------------------------------------------

def test_stock_info_returns_pe_ratio(mocker):
    """stock_info 路由返回 trailingPE / forwardPE / operatingMargins 等指标。"""
    from data_center.collectors.finance.yfinance_collector import YFinanceCollector

    mock_yf = mocker.patch(YF_MOD)
    mock_ticker = mock_yf.Ticker.return_value
    mock_ticker.info = _info_resp()

    c = YFinanceCollector()
    recs = c.fetch({"route": "stock_info", "symbol": "NVDA"})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "yfinance"
    assert r.category == "finance"
    assert r.sub_category == "stock_info_NVDA"
    # 核心财务指标
    assert r.metrics["trailingPE"] == pytest.approx(65.5)
    assert r.metrics["forwardPE"] == pytest.approx(55.2)
    assert r.metrics["operatingMargins"] == pytest.approx(0.337)
    assert r.metrics["returnOnEquity"] == pytest.approx(0.91)
    assert r.metrics["marketCap"] == pytest.approx(3_000_000_000_000)
    assert r.metrics["revenueGrowth"] == pytest.approx(0.94)
    # 元信息
    assert r.metrics["symbol"] == "NVDA"
    assert r.metrics["longName"] == "NVIDIA Corporation"
    assert r.metrics["currency"] == "USD"
    # raw 保留原始 URL 溯源
    assert r.raw["route"] == "stock_info"


def test_stock_info_missing_field_defaults_to_none(mocker):
    """info 部分字段缺失 → 默认 0.0，不抛异常。"""
    from data_center.collectors.finance.yfinance_collector import YFinanceCollector

    mock_yf = mocker.patch(YF_MOD)
    mock_ticker = mock_yf.Ticker.return_value
    mock_ticker.info = {
        "trailingPE": 65.5,
        "longName": "Test Corp",
        # forwardPE / operatingMargins / returnOnEquity / marketCap / revenueGrowth 缺失
    }

    c = YFinanceCollector()
    recs = c.fetch({"route": "stock_info", "symbol": "TEST"})

    assert len(recs) == 1
    r = recs[0]
    assert r.metrics["trailingPE"] == pytest.approx(65.5)
    assert r.metrics["forwardPE"] == pytest.approx(0.0)
    assert r.metrics["operatingMargins"] == pytest.approx(0.0)
    assert r.metrics["returnOnEquity"] == pytest.approx(0.0)
    assert r.metrics["marketCap"] == pytest.approx(0.0)
    assert r.metrics["revenueGrowth"] == pytest.approx(0.0)


def test_stock_info_empty_info_returns_empty(mocker):
    """info 返回空 dict → 返回空列表。"""
    from data_center.collectors.finance.yfinance_collector import YFinanceCollector

    mock_yf = mocker.patch(YF_MOD)
    mock_ticker = mock_yf.Ticker.return_value
    mock_ticker.info = {}

    c = YFinanceCollector()
    recs = c.fetch({"route": "stock_info", "symbol": "TEST"})

    assert len(recs) == 0


def test_stock_info_missing_symbol_returns_empty(mocker):
    """stock_info 路由但缺少 symbol → 返回空列表。"""
    from data_center.collectors.finance.yfinance_collector import YFinanceCollector

    mocker.patch(YF_MOD)

    c = YFinanceCollector()
    recs = c.fetch({"route": "stock_info"})

    assert recs == []


# ---------------------------------------------------------------------------
# stock_financials 路由
# ---------------------------------------------------------------------------

def test_stock_financials_returns_revenue(mocker):
    """stock_financials 路由返回营收/盈利季度时序列。"""
    from data_center.collectors.finance.yfinance_collector import YFinanceCollector

    mock_yf = mocker.patch(YF_MOD)
    mock_ticker = mock_yf.Ticker.return_value
    mock_ticker.financials = _financials_df()

    c = YFinanceCollector()
    recs = c.fetch({"route": "stock_financials", "symbol": "NVDA"})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "yfinance"
    assert r.category == "finance"
    assert r.sub_category == "stock_financials_NVDA"
    # metrics
    assert r.metrics["symbol"] == "NVDA"
    assert r.metrics["quarters"] == 4
    assert r.metrics["latest_revenue"] == pytest.approx(30_040_000_000)
    assert r.metrics["latest_net_income"] == pytest.approx(16_600_000_000)
    # timeseries 每季度一条（最旧在前，最新在后）
    assert len(r.timeseries) == 4
    assert r.timeseries[0]["date"] == "2024-10-31"
    assert r.timeseries[0]["revenue"] == pytest.approx(18_120_000_000)
    assert r.timeseries[3]["date"] == "2025-07-31"
    assert r.timeseries[3]["revenue"] == pytest.approx(30_040_000_000)
    assert r.timeseries[3]["net_income"] == pytest.approx(16_600_000_000)
    assert r.timeseries[3]["ebitda"] == pytest.approx(18_750_000_000)
    # raw
    assert r.raw["route"] == "stock_financials"


def test_stock_financials_empty_df_returns_empty(mocker):
    """financials 返回空 DataFrame → 返回空列表。"""
    from data_center.collectors.finance.yfinance_collector import YFinanceCollector

    mock_yf = mocker.patch(YF_MOD)
    mock_ticker = mock_yf.Ticker.return_value
    mock_ticker.financials = pd.DataFrame()

    c = YFinanceCollector()
    recs = c.fetch({"route": "stock_financials", "symbol": "TEST"})

    assert len(recs) == 0


def test_stock_financials_missing_symbol_returns_empty(mocker):
    """stock_financials 路由但缺少 symbol → 返回空列表。"""
    from data_center.collectors.finance.yfinance_collector import YFinanceCollector

    mocker.patch(YF_MOD)

    c = YFinanceCollector()
    recs = c.fetch({"route": "stock_financials"})

    assert recs == []


# ---------------------------------------------------------------------------
# 向后兼容：无 route 参数 → 走原有价格获取逻辑
# ---------------------------------------------------------------------------

def test_no_route_falls_back_to_price_fetch(mocker):
    """无 route 参数 → 走原有价格获取逻辑（向后兼容）。"""
    from data_center.collectors.finance.yfinance_collector import YFinanceCollector

    idx = pd.DatetimeIndex(["2026-08-21", "2026-08-22"])
    mock_yf = mocker.patch(YF_MOD)
    mock_ticker = mock_yf.Ticker.return_value
    mock_ticker.history.return_value = pd.DataFrame({"Close": [100.0, 102.5]}, index=idx)

    c = YFinanceCollector()
    recs = c.fetch({"symbol": "DX-Y.NYB"})

    assert len(recs) == 1
    r = recs[0]
    assert r.sub_category == "DX-Y.NYB"
    assert r.metrics["price"] == pytest.approx(102.5)
    # 确认调用的是 history()，不是 info/financials
    mock_ticker.history.assert_called_once()


# ---------------------------------------------------------------------------
# 容错
# ---------------------------------------------------------------------------

def test_stock_info_exception_returns_empty(mocker):
    """stock_info 异常 → fail-open 返回空列表。"""
    from unittest.mock import PropertyMock
    from data_center.collectors.finance.yfinance_collector import YFinanceCollector

    mock_yf = mocker.patch(YF_MOD)
    mock_ticker = mock_yf.Ticker.return_value
    # info 属性访问抛异常
    type(mock_ticker).info = PropertyMock(side_effect=RuntimeError("boom"))

    c = YFinanceCollector()
    recs = c.fetch({"route": "stock_info", "symbol": "TEST"})

    assert recs == []


def test_stock_financials_exception_returns_empty(mocker):
    """stock_financials 异常 → fail-open 返回空列表。"""
    from unittest.mock import PropertyMock
    from data_center.collectors.finance.yfinance_collector import YFinanceCollector

    mock_yf = mocker.patch(YF_MOD)
    mock_ticker = mock_yf.Ticker.return_value
    type(mock_ticker).financials = PropertyMock(side_effect=RuntimeError("boom"))

    c = YFinanceCollector()
    recs = c.fetch({"route": "stock_financials", "symbol": "TEST"})

    assert recs == []
