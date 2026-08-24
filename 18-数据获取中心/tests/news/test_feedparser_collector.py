"""Feedparser collector 测试 — 通用 RSS 采集。

feedparser 薄封装，parse(url) -> entries -> DataRecord(category=news)。
"""
from data_center.collectors.news.feedparser_collector import FeedparserCollector
from data_center.core.contract import DataRecord

FP_MOD = "data_center.collectors.news.feedparser_collector.feedparser"


def _fake_feed(title="CoinDesk", entries=None):
    return {
        "feed": {"title": title, "link": "https://example.com"},
        "entries": entries or [],
        "bozo": 0,
    }


def test_no_url_returns_empty():
    c = FeedparserCollector()
    assert c.fetch({}) == []


def test_fetch_entries(mocker):
    mock_fp = mocker.patch(FP_MOD)
    mock_fp.parse.return_value = _fake_feed(entries=[
        {
            "title": "BTC hits 100k",
            "link": "https://example.com/1",
            "summary": "summary1",
            "published": "Mon, 01 Jan 2024 00:00:00 GMT",
            "id": "id1",
            "author": "satoshi",
        },
        {
            "title": "ETH merges",
            "link": "https://example.com/2",
            "summary": "summary2",
            "published": "Mon, 02 Jan 2024 00:00:00 GMT",
            "id": "id2",
        },
    ])
    c = FeedparserCollector()
    recs = c.fetch({"feed_url": "https://example.com/feed", "max_items": 10})

    assert len(recs) == 2
    r0 = recs[0]
    assert isinstance(r0, DataRecord)
    assert r0.source == "feedparser"
    assert r0.category == "news"
    assert r0.sub_category == "CoinDesk"
    assert r0.metrics["title"] == "BTC hits 100k"
    assert r0.metrics["link"] == "https://example.com/1"
    assert r0.metrics["author"] == "satoshi"
    assert r0.events[0]["summary"] == "summary1"
    # raw 保留原始 entry
    assert r0.raw["id"] == "id1"


def test_max_items_limit(mocker):
    mock_fp = mocker.patch(FP_MOD)
    mock_fp.parse.return_value = _fake_feed(entries=[
        {"title": f"news-{i}", "link": f"https://example.com/{i}", "id": f"id-{i}"}
        for i in range(5)
    ])
    c = FeedparserCollector()
    recs = c.fetch({"feed_url": "https://example.com/feed", "max_items": 2})
    assert len(recs) == 2
    assert recs[0].metrics["title"] == "news-0"
    assert recs[1].metrics["title"] == "news-1"


def test_empty_feed_returns_empty(mocker):
    mock_fp = mocker.patch(FP_MOD)
    mock_fp.parse.return_value = _fake_feed(entries=[])
    c = FeedparserCollector()
    assert c.fetch({"feed_url": "https://example.com/feed"}) == []


def test_missing_feed_title_fallback(mocker):
    mock_fp = mocker.patch(FP_MOD)
    mock_fp.parse.return_value = {
        "feed": {},  # no title
        "entries": [{"title": "x", "link": "l", "id": "i"}],
    }
    c = FeedparserCollector()
    recs = c.fetch({"feed_url": "https://example.com/feed"})
    assert len(recs) == 1
    # 无 feed title 时 sub_category 用 feed_url
    assert recs[0].sub_category == "https://example.com/feed"
