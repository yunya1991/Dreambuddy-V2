"""Generic spider — Scrapy Selector + requests 静态站采集。

按 YAML 配置的 CSS 选择器提取字段，支持 HTML 和 RSS。
Scrapy Selector (parsel) 是成熟的 CSS/XPath 解析引擎，薄封装避免造轮子。
"""
from __future__ import annotations

import requests
from scrapy.selector import Selector


class GenericSpider:
    """通用采集器：按 site 配置的选择器提取字段。"""

    def fetch_and_parse(self, site: dict) -> list[dict]:
        """拉取页面 → 解析 → 返回字段 dict 列表。"""
        url = site.get("url")
        if not url:
            return []
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            return []
        return self.parse(resp.text, site)

    def parse(self, html: str, site: dict) -> list[dict]:
        """从 HTML/XML 字符串提取字段，返回 dict 列表。"""
        selectors = site.get("selectors", {})
        item_sel = selectors.get("item")
        if not item_sel:
            return []

        # RSS/Atom 等 XML 内容用 XML 模式（HTML 模式把 <link> 当 void 元素）
        sel_type = "xml" if self._is_xml(html) else "html"
        root = Selector(text=html, type=sel_type)
        items = root.css(item_sel)
        field_selectors = {k: v for k, v in selectors.items() if k != "item"}

        results: list[dict] = []
        for item in items:
            fields = self._extract_fields(item, field_selectors)
            if fields:
                results.append(fields)
        return results

    def _extract_fields(self, item: Selector, field_selectors: dict) -> dict:
        """对单个 item Selector 按字段选择器提取值。"""
        fields: dict = {}
        for name, sel in field_selectors.items():
            value = self._extract_one(item, sel)
            if value is not None:
                fields[name] = value
        return fields

    def _extract_one(self, item: Selector, sel: str) -> str | None:
        """按单个选择器提取值。

        规则：
        - "text" → item 自身的文本
        - "href" → item 自身的 href 属性
        - 含 "::text" → CSS 选择器 + 文本提取
        - 含 "::attr(name)" → CSS 选择器 + 属性提取
        - 其他 → CSS 选择器，默认提取文本
        """
        if sel == "text":
            return item.css("::text").get()
        if sel == "href":
            return item.attrib.get("href")
        # 标准 Scrapy CSS 选择器（含 ::text / ::attr 后缀）
        return item.css(sel).get()

    @staticmethod
    def _is_xml(text: str) -> bool:
        """检测内容是否为 XML（RSS/Atom），用于切换 Selector 解析模式。"""
        stripped = text.lstrip()[:200].lower()
        return stripped.startswith("<?xml") or "<rss" in stripped or "<feed" in stripped
