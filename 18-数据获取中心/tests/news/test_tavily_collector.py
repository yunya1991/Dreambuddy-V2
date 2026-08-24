"""Tavily collector 测试 — AI 搜索采集，迁移自 data_collector。

tavily-python 薄封装，client.search(query) -> results -> DataRecord(category=news)。
"""
from data_center.collectors.news.tavily_collector import TavilyCollector
from data_center.core.contract import DataRecord

TV_MOD = "data_center.collectors.news.tavily_collector.TavilyClient"


def test_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    c = TavilyCollector()
    assert c.is_available() is False
    assert c.fetch({"query": "BTC"}) == []


def test_no_query_returns_empty():
    c = TavilyCollector(config={"api_key": "fake"})
    assert c.fetch({}) == []


def test_fetch_results(mocker):
    mock_client_cls = mocker.patch(TV_MOD)
    mock_client = mock_client_cls.return_value
    mock_client.search.return_value = {
        "results": [
            {
                "title": "BTC hits 100k",
                "content": "Bitcoin reached 100000 USD",
                "url": "https://example.com/1",
                "source": "CoinDesk",
                "published_date": "2024-01-01T00:00:00Z",
            },
            {
                "title": "ETH news",
                "content": "Ethereum update",
                "url": "https://example.com/2",
                "source": "CoinTelegraph",
                "published_date": "2024-01-02T00:00:00Z",
            },
        ],
        "answer": "BTC is bullish",
    }
    c = TavilyCollector(config={"api_key": "fake"})
    recs = c.fetch({"query": "BTC price", "max_results": 5})

    # 验证 search 调用参数
    mock_client.search.assert_called_once_with(query="BTC price", max_results=5)

    assert len(recs) == 2
    r0 = recs[0]
    assert isinstance(r0, DataRecord)
    assert r0.source == "tavily"
    assert r0.category == "news"
    assert r0.sub_category == "BTC price"
    assert r0.metrics["title"] == "BTC hits 100k"
    assert r0.metrics["url"] == "https://example.com/1"
    assert r0.metrics["source"] == "CoinDesk"
    assert r0.events[0]["content"] == "Bitcoin reached 100000 USD"
    assert r0.raw["url"] == "https://example.com/1"


def test_default_max_results(mocker):
    mock_client_cls = mocker.patch(TV_MOD)
    mock_client = mock_client_cls.return_value
    mock_client.search.return_value = {"results": []}
    c = TavilyCollector(config={"api_key": "fake"})
    c.fetch({"query": "test"})
    mock_client.search.assert_called_once_with(query="test", max_results=10)


def test_empty_results(mocker):
    mock_client_cls = mocker.patch(TV_MOD)
    mock_client = mock_client_cls.return_value
    mock_client.search.return_value = {"results": []}
    c = TavilyCollector(config={"api_key": "fake"})
    assert c.fetch({"query": "nothing"}) == []
