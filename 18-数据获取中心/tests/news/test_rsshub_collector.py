"""RSSHub collector 测试 — RSSHub 路由 -> feedparser。

route -> base_url + route -> feedparser.parse -> DataRecord(source=rsshub)。
"""
from data_center.collectors.news.rsshub_collector import RsshubCollector
from data_center.core.contract import DataRecord

FP_MOD = "data_center.collectors.news.feedparser_collector.feedparser"


def test_route_to_url(mocker):
    """route + base_url 组装成完整 feed URL 传给 feedparser.parse。"""
    mock_fp = mocker.patch(FP_MOD)
    mock_fp.parse.return_value = {
        "feed": {"title": "CoinDesk"},
        "entries": [
            {"title": "t1", "link": "l1", "id": "i1"},
        ],
    }
    c = RsshubCollector(config={"base_url": "https://rsshub.app"})
    recs = c.fetch({"route": "/coindesk/news"})

    # 验证 feedparser.parse 被调用时 URL 正确拼接
    call_args = mock_fp.parse.call_args
    assert call_args[0][0] == "https://rsshub.app/coindesk/news"

    assert len(recs) == 1
    assert recs[0].source == "rsshub"
    assert recs[0].category == "news"
    assert recs[0].sub_category == "CoinDesk"


def test_default_base_url(mocker):
    """无 config 时使用默认 base_url。"""
    mock_fp = mocker.patch(FP_MOD)
    mock_fp.parse.return_value = {"feed": {}, "entries": []}
    c = RsshubCollector()
    c.fetch({"route": "/test"})
    call_url = mock_fp.parse.call_args[0][0]
    assert call_url.startswith("https://")


def test_no_route_returns_empty():
    c = RsshubCollector()
    assert c.fetch({}) == []


def test_max_items_passed_through(mocker):
    mock_fp = mocker.patch(FP_MOD)
    mock_fp.parse.return_value = {
        "feed": {"title": "T"},
        "entries": [
            {"title": f"n-{i}", "link": f"l-{i}", "id": f"i-{i}"}
            for i in range(10)
        ],
    }
    c = RsshubCollector()
    recs = c.fetch({"route": "/x", "max_items": 3})
    assert len(recs) == 3


def test_records_are_valid(mocker):
    mock_fp = mocker.patch(FP_MOD)
    mock_fp.parse.return_value = {
        "feed": {"title": "News"},
        "entries": [{"title": "t", "link": "l", "id": "i", "summary": "s"}],
    }
    c = RsshubCollector()
    recs = c.fetch({"route": "/news"})
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "rsshub"
    assert r.metrics["title"] == "t"
    assert r.events[0]["summary"] == "s"
