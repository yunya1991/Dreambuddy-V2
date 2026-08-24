"""GDELT collector 测试 — 全球事件/新闻流。

GDELT DOC 2.0 API 直连（requests），无 Key 需求，query -> articles -> DataRecord。
"""
from data_center.collectors.news.gdelt_collector import GdeltCollector
from data_center.core.contract import DataRecord

REQ_MOD = "data_center.collectors.news.gdelt_collector.requests"


def _fake_response(articles=None):
    """模拟 requests.Response。"""
    class _Resp:
        def __init__(self, data):
            self._data = data
            self.status_code = 200
        def json(self):
            return self._data
        @property
        def text(self):
            return ""
    return _Resp({"articles": articles or []})


def test_no_query_returns_empty():
    c = GdeltCollector()
    assert c.fetch({}) == []


def test_is_available_always_true():
    """GDELT 免费，无 Key 需求。"""
    assert GdeltCollector().is_available() is True


def test_fetch_articles(mocker):
    mock_req = mocker.patch(REQ_MOD)
    mock_req.get.return_value = _fake_response(articles=[
        {
            "url": "https://example.com/1",
            "title": "BTC surge",
            "seendate": "20240101T120000Z",
            "domain": "coindesk.com",
            "sourcecountry": "US",
            "language": "English",
        },
        {
            "url": "https://example.com/2",
            "title": "ETH update",
            "seendate": "20240102T120000Z",
            "domain": "cointelegraph.com",
            "sourcecountry": "UK",
            "language": "English",
        },
    ])
    c = GdeltCollector()
    recs = c.fetch({"query": "bitcoin", "max_records": 5})

    # 验证 API 调用参数
    call_kwargs = mock_req.get.call_args[1]
    assert call_kwargs["params"]["query"] == "bitcoin"
    assert call_kwargs["params"]["format"] == "json"

    assert len(recs) == 2
    r0 = recs[0]
    assert isinstance(r0, DataRecord)
    assert r0.source == "gdelt"
    assert r0.category == "news"
    assert r0.sub_category == "bitcoin"
    assert r0.metrics["title"] == "BTC surge"
    assert r0.metrics["url"] == "https://example.com/1"
    assert r0.metrics["domain"] == "coindesk.com"
    assert r0.raw["seendate"] == "20240101T120000Z"


def test_empty_response(mocker):
    mock_req = mocker.patch(REQ_MOD)
    mock_req.get.return_value = _fake_response(articles=[])
    c = GdeltCollector()
    assert c.fetch({"query": "nothing"}) == []


def test_default_max_records(mocker):
    mock_req = mocker.patch(REQ_MOD)
    mock_req.get.return_value = _fake_response(articles=[])
    c = GdeltCollector()
    c.fetch({"query": "test"})
    call_params = mock_req.get.call_args[1]["params"]
    assert call_params["maxrecords"] == 10


def test_non_json_response_returns_empty(mocker):
    """GDELT 有时返回空 body（无匹配），不应抛异常。"""
    mock_req = mocker.patch(REQ_MOD)

    class _EmptyResp:
        status_code = 200
        text = ""
        def json(self):
            raise ValueError("No JSON")

    mock_req.get.return_value = _EmptyResp()
    c = GdeltCollector()
    assert c.fetch({"query": "test"}) == []
