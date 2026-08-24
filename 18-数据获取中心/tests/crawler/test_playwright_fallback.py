"""Playwright fallback 测试 — JS 站点兜底渲染。

mock sync_playwright 全链路，验证 URL 加载 + 渲染 HTML 提取 + 异常降级。
"""
from data_center.crawler.playwright_fallback import PlaywrightFallback

PW_MOD = "data_center.crawler.playwright_fallback.sync_playwright"

RENDERED_HTML = """
<html><body>
<div class="announcement-item"><a href="/a/1">Title1</a></div>
<div class="announcement-item"><a href="/a/2">Title2</a></div>
</body></html>
"""


def _mock_pw(mocker, html=RENDERED_HTML):
    """构造 sync_playwright mock 链路。"""
    mock_ctx = mocker.patch(PW_MOD)
    mock_browser = mock_ctx.return_value.__enter__.return_value.chromium.launch.return_value
    mock_page = mock_browser.new_page.return_value
    mock_page.content.return_value = html
    return mock_page


def test_render_returns_html(mocker):
    mock_page = _mock_pw(mocker)
    pf = PlaywrightFallback()
    html = pf.render("http://example.com/js-page")
    # goto 的第一个位置参数是 URL
    assert mock_page.goto.call_args[0][0] == "http://example.com/js-page"
    assert html == RENDERED_HTML


def test_render_and_parse(mocker):
    _mock_pw(mocker)
    site = {
        "url": "http://example.com/js-page",
        "selectors": {"item": ".announcement-item a", "title": "text", "link": "href"},
    }
    pf = PlaywrightFallback()
    items = pf.fetch_and_parse(site)
    assert len(items) == 2
    assert items[0]["title"] == "Title1"
    assert items[0]["link"] == "/a/1"


def test_missing_url_returns_empty():
    pf = PlaywrightFallback()
    assert pf.fetch_and_parse({"selectors": {"item": "a"}}) == []


def test_render_error_returns_empty(mocker):
    mock_ctx = mocker.patch(PW_MOD)
    mock_ctx.return_value.__enter__.return_value.chromium.launch.side_effect = RuntimeError("no browser")
    pf = PlaywrightFallback()
    assert pf.render("http://example.com") == ""
    assert pf.fetch_and_parse({"url": "http://x", "selectors": {"item": "a"}}) == []


def test_render_closes_browser(mocker):
    mock_ctx = mocker.patch(PW_MOD)
    mock_browser = mock_ctx.return_value.__enter__.return_value.chromium.launch.return_value
    pf = PlaywrightFallback()
    pf.render("http://example.com")
    mock_browser.close.assert_called_once()
