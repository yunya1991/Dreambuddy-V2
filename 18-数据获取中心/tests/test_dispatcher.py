"""Registry + Dispatcher 测试 — 对齐 TECHNICAL_DESIGN.md §5.1/§3.2。

DataCenter.fetch(category, source=..., ...) 路由到注册的 collector；
未注册源抛 SourceUnavailableError；category=web 走爬虫轨（M1 stub 返回空）。
"""
import pandas as pd
import pytest

from data_center.core.dispatcher import DataCenter
from data_center.core.errors import SourceUnavailableError

FRED_MOD = "data_center.collectors.macro.fred_collector.Fred"
YF_MOD = "data_center.collectors.finance.yfinance_collector.yf"


def _make_series():
    idx = [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-08-01")]
    return pd.Series([5.0, 5.25], index=idx)


def test_default_registry_has_fred():
    dc = DataCenter()
    assert ("macro", "fred") in dc.list_collectors()


def test_fetch_routes_to_fred(mocker):
    mocker.patch(FRED_MOD).return_value.get_series.return_value = _make_series()
    dc = DataCenter(config={"api_key": "fake-key"})
    recs = dc.fetch("macro", series="FEDFUNDS", source="fred")
    assert len(recs) == 1
    assert recs[0].source == "fred"
    assert recs[0].sub_category == "FEDFUNDS"


def test_unregistered_source_raises(mocker):
    mocker.patch(FRED_MOD)  # 防止任何误路由触网
    dc = DataCenter()
    with pytest.raises(SourceUnavailableError):
        dc.fetch("macro", series="X", source="nonexistent")


def test_web_routes_to_crawler(mocker, tmp_path):
    """web 走爬虫轨 CrawlerRunner（M3 接入）。"""
    config_path = str(tmp_path / "sites.yaml")
    tmp_path.joinpath("sites.yaml").write_text("sites:\n  s:\n    enabled: false\n")
    mock_runner_cls = mocker.patch(
        "data_center.crawler.runner.CrawlerRunner"
    )
    mock_runner_cls.return_value.run.return_value = []
    dc = DataCenter()
    assert dc.fetch("web", config=config_path) == []
    mock_runner_cls.assert_called_once_with(config_path=config_path)


# === M2 dispatcher 路由测试 ===

def test_all_m2_collectors_registered():
    """M2 全部 collector 应注册到默认 registry。"""
    dc = DataCenter()
    collectors = set(dc.list_collectors())
    expected = {
        ("macro", "fred"),
        ("finance", "yfinance"),
        ("chain", "ccxt"),
        ("chain", "etherscan"),
        ("news", "feedparser"),
        ("news", "rsshub"),
        ("news", "tavily"),
        ("news", "gdelt"),
    }
    assert expected <= collectors


def test_fetch_routes_to_yfinance(mocker):
    mocker.patch(YF_MOD).Ticker.return_value.history.return_value = pd.DataFrame(
        {"Close": [100.0, 102.5]},
        index=pd.DatetimeIndex(["2026-08-21", "2026-08-22"]),
    )
    dc = DataCenter()
    recs = dc.fetch("finance", symbol="DX-Y.NYB", source="yfinance")
    assert len(recs) == 1
    assert recs[0].source == "yfinance"


def test_fetch_routes_to_ccxt(mocker):
    mock_ccxt = mocker.patch("data_center.collectors.chain.ccxt_collector.ccxt")
    mock_ex = mocker.MagicMock()
    mock_ex.fetch_ticker.return_value = {"last": 50000, "bid": 49999, "ask": 50001}
    mock_ccxt.binance.return_value = mock_ex
    dc = DataCenter()
    recs = dc.fetch("chain", symbol="BTC/USDT", source="ccxt")
    assert len(recs) == 1
    assert recs[0].source == "ccxt"
    assert recs[0].metrics["last"] == 50000.0


def test_fetch_routes_to_etherscan_gas(mocker):
    mock_es = mocker.patch(
        "data_center.collectors.chain.etherscan_collector.Etherscan"
    ).return_value
    mock_es.get_gas_oracle.return_value = {
        "ProposeGasPrice": "12", "SafeGasPrice": "10", "FastGasPrice": "15",
    }
    dc = DataCenter(config={"api_key": "fake"})
    recs = dc.fetch("chain", kind="gas", source="etherscan")
    assert len(recs) == 1
    assert recs[0].source == "etherscan"
    assert recs[0].metrics["propose_gas"] == 12.0


def test_fetch_routes_to_feedparser(mocker):
    mock_fp = mocker.patch(
        "data_center.collectors.news.feedparser_collector.feedparser"
    )
    mock_fp.parse.return_value = {
        "feed": {"title": "TestFeed"},
        "entries": [{"title": "news1", "link": "l1", "id": "i1"}],
    }
    dc = DataCenter()
    recs = dc.fetch("news", feed_url="https://example.com/feed", source="feedparser")
    assert len(recs) == 1
    assert recs[0].source == "feedparser"
    assert recs[0].sub_category == "TestFeed"


def test_fetch_routes_to_rsshub(mocker):
    mock_fp = mocker.patch(
        "data_center.collectors.news.feedparser_collector.feedparser"
    )
    mock_fp.parse.return_value = {
        "feed": {"title": "CoinDesk"},
        "entries": [{"title": "t", "link": "l", "id": "i"}],
    }
    dc = DataCenter()
    recs = dc.fetch("news", route="/coindesk/news", source="rsshub")
    assert len(recs) == 1
    assert recs[0].source == "rsshub"


def test_fetch_routes_to_tavily(mocker):
    mock_client = mocker.patch(
        "data_center.collectors.news.tavily_collector.TavilyClient"
    ).return_value
    mock_client.search.return_value = {
        "results": [{"title": "t", "content": "c", "url": "u", "source": "s"}]
    }
    dc = DataCenter(config={"api_key": "fake"})
    recs = dc.fetch("news", query="BTC", source="tavily")
    assert len(recs) == 1
    assert recs[0].source == "tavily"


def test_fetch_routes_to_gdelt(mocker):
    mock_req = mocker.patch(
        "data_center.collectors.news.gdelt_collector.requests"
    )
    class _Resp:
        status_code = 200
        def json(self):
            return {"articles": [{"title": "t", "url": "u", "domain": "d"}]}
    mock_req.get.return_value = _Resp()
    dc = DataCenter()
    recs = dc.fetch("news", query="bitcoin", source="gdelt")
    assert len(recs) == 1
    assert recs[0].source == "gdelt"
