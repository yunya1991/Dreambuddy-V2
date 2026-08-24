"""compat/data_compat 测试 — fetch_tavily_news 走 DataCenter tavily collector。

老 data_collector.fetch_tavily_news 返回 List[Dict] 含 title/content/url/source/published_at。
compat 版用 TavilyCollector 替换，返回格式不变。
"""
from data_center.compat.data_compat import fetch_tavily_news

TV_MOD = "data_center.compat.data_compat.TavilyCollector"


def test_fetch_tavily_news_basic(mocker):
    mock_cls = mocker.patch(TV_MOD)
    mock_collector = mock_cls.return_value
    mock_collector.is_available.return_value = True
    mock_collector.fetch.return_value = []

    # 构造 DataRecord 返回
    from data_center.core.contract import DataRecord

    mock_collector.fetch.return_value = [
        DataRecord(
            source="tavily", category="news", sub_category="BTC",
            timestamp="2026-08-24T12:00:00+08:00",
            metrics={"title": "BTC surges", "url": "http://x/1", "source": "CoinDesk"},
            events=[{"content": "Bitcoin rose 5%"}],
            timeseries=[], raw={"published_date": "2024-01-01"},
        )
    ]

    results = fetch_tavily_news("BTC", max_results=5)
    mock_collector.fetch.assert_called_once_with({"query": "BTC", "max_results": 5})
    assert len(results) == 1
    r = results[0]
    assert r["title"] == "BTC surges"
    assert r["url"] == "http://x/1"
    assert r["source"] == "CoinDesk"
    assert r["content"] == "Bitcoin rose 5%"
    assert r["published_at"] == "2024-01-01"


def test_fetch_tavily_no_key_returns_empty(mocker):
    mock_cls = mocker.patch(TV_MOD)
    mock_collector = mock_cls.return_value
    mock_collector.is_available.return_value = False

    results = fetch_tavily_news("BTC")
    assert results == []


def test_fetch_tavily_default_max_results(mocker):
    mock_cls = mocker.patch(TV_MOD)
    mock_collector = mock_cls.return_value
    mock_collector.is_available.return_value = True
    mock_collector.fetch.return_value = []

    fetch_tavily_news("ETH")
    mock_collector.fetch.assert_called_once_with({"query": "ETH", "max_results": 10})
