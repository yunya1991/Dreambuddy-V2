"""Generic spider 测试 — Scrapy Selector + requests 静态站采集。

generic_spider 用 Scrapy Selector 按 YAML 配置的选择器提取字段，支持 HTML 和 RSS。
"""
from data_center.crawler.generic_spider import GenericSpider

REQ_MOD = "data_center.crawler.generic_spider.requests"

HTML_NEWS = """
<html><body>
<ul class="newslist">
  <li><a href="/news/1">央行降息</a></li>
  <li><a href="/news/2">GDP 增长</a></li>
  <li><a href="/news/3">CPI 数据</a></li>
</ul>
</body></html>
"""

RSS_FEED = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>TestFeed</title>
    <item>
      <title>BTC hits 100k</title>
      <link>https://example.com/1</link>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
    </item>
    <item>
      <title>ETH update</title>
      <link>https://example.com/2</link>
      <pubDate>Mon, 02 Jan 2024 00:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def test_parse_html_news_list():
    """HTML 列表页：item 选择器 + text/href 提取。"""
    site = {
        "source": "pbc",
        "sub_category": "announcement",
        "selectors": {
            "item": ".newslist a",
            "title": "text",
            "link": "href",
        },
    }
    spider = GenericSpider()
    items = spider.parse(HTML_NEWS, site)
    assert len(items) == 3
    assert items[0]["title"] == "央行降息"
    assert items[0]["link"] == "/news/1"
    assert items[1]["title"] == "GDP 增长"


def test_parse_rss_feed():
    """RSS XML：标准 CSS 选择器 + ::text 提取。"""
    site = {
        "source": "coindesk",
        "sub_category": "news",
        "selectors": {
            "item": "item",
            "title": "title::text",
            "link": "link::text",
            "date": "pubDate::text",
        },
    }
    spider = GenericSpider()
    items = spider.parse(RSS_FEED, site)
    assert len(items) == 2
    assert items[0]["title"] == "BTC hits 100k"
    assert items[0]["link"] == "https://example.com/1"
    assert items[0]["date"] == "Mon, 01 Jan 2024 00:00:00 GMT"


def test_parse_empty_html():
    """空页面 → 空列表。"""
    spider = GenericSpider()
    items = spider.parse("<html></html>", {"selectors": {"item": ".x", "title": "text"}})
    assert items == []


def test_fetch_and_parse(mocker):
    """requests.get → HTML → parse 全链路。"""
    mock_req = mocker.patch(REQ_MOD)
    mock_req.get.return_value.text = HTML_NEWS
    mock_req.get.return_value.status_code = 200
    site = {
        "url": "http://example.com/news",
        "selectors": {"item": ".newslist a", "title": "text", "link": "href"},
    }
    spider = GenericSpider()
    items = spider.fetch_and_parse(site)
    mock_req.get.assert_called_once_with("http://example.com/news", timeout=30)
    assert len(items) == 3
    assert items[0]["title"] == "央行降息"


def test_fetch_http_error_returns_empty(mocker):
    """HTTP 非 200 → 空列表。"""
    mock_req = mocker.patch(REQ_MOD)
    mock_req.get.return_value.status_code = 404
    mock_req.get.return_value.text = "Not Found"
    spider = GenericSpider()
    assert spider.fetch_and_parse({"url": "http://x", "selectors": {"item": "a"}}) == []


def test_missing_url_returns_empty():
    spider = GenericSpider()
    assert spider.fetch_and_parse({"selectors": {"item": "a"}}) == []


def test_field_with_css_selector():
    """复杂 CSS 选择器提取。"""
    html = """
    <html><body>
    <div class="card"><h3 class="title">Card1</h3><a class="url" href="u1">link</a></div>
    <div class="card"><h3 class="title">Card2</h3><a class="url" href="u2">link</a></div>
    </body></html>
    """
    site = {
        "selectors": {
            "item": ".card",
            "title": ".title::text",
            "link": ".url::attr(href)",
        },
    }
    spider = GenericSpider()
    items = spider.parse(html, site)
    assert len(items) == 2
    assert items[0]["title"] == "Card1"
    assert items[0]["link"] == "u1"
    assert items[1]["title"] == "Card2"
