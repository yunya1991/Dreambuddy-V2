"""Playwright fallback — JS 站点兜底渲染。

对 js_render=true 的站点用 Playwright headless 浏览器渲染后再解析。
渲染后的 HTML 交给 GenericSpider 按选择器提取字段。
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright

from data_center.crawler.generic_spider import GenericSpider


class PlaywrightFallback:
    """JS 站点兜底渲染器。"""

    def __init__(self):
        self._spider = GenericSpider()

    def render(self, url: str) -> str:
        """用 Playwright 渲染 URL，返回页面 HTML。异常时返回空字符串。"""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=30000)
                html = page.content()
                browser.close()
                return html
        except Exception:
            return ""

    def fetch_and_parse(self, site: dict) -> list[dict]:
        """渲染 + 解析全链路。"""
        url = site.get("url")
        if not url:
            return []
        html = self.render(url)
        if not html:
            return []
        return self._spider.parse(html, site)
