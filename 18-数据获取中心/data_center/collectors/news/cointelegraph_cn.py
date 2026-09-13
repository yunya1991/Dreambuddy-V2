"""Cointelegraph 中文 Collector — 通过 Scrapling stealthy + adaptive 抓取首页新闻。

渲染路径（FAIL-OPEN）：
  1. Scrapling StealthyFetcher（Patchright）
  2. Scrapling 内部回退链（stealthy→dynamic→http→static）

adaptive=true 启用 Scrapling 自适应解析，页面改版后自动重新定位元素。
产出 DataRecord(category=news, source=cointelegraph_cn)。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord

logger = logging.getLogger("data_center.collectors.news.cointelegraph_cn")

CT_CN_URL = "https://cn.cointelegraph.com/"

# Cointelegraph 中文首页新闻卡片选择器
_CT_SELECTORS = {
    "item": "article, .post-card, [class*='post-card']",
    "title": "h2 span::text, h3 span::text, .post-card__title span::text",
    "link": "a::attr(href)",
    "summary": "p::text, .post-card__summary::text",
}


class CointelegraphCnCollector(BaseCollector):
    """Cointelegraph 中文采集器（news / cointelegraph_cn）。"""

    source = "cointelegraph_cn"
    category = "news"

    def __init__(self, config: dict | None = None):
        super().__init__(config or {})
        self._url = self.config.get("url", CT_CN_URL)
        self._engine_mode = self.config.get("engine", "stealthy")
        self._adaptive = bool(self.config.get("adaptive", True))

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict | None = None) -> list[DataRecord]:
        params = params or {}
        url = params.get("url", self._url)
        try:
            from data_center.crawler.scrapling_engine import ScraplingEngine
        except Exception:
            return []

        engine = ScraplingEngine()
        html = engine.fetch_html(url, mode=self._engine_mode)
        if not html:
            return []

        site = {
            "selectors": _CT_SELECTORS,
            "adaptive": self._adaptive,
            "source": self.source,
            "sub_category": "news",
        }
        items = engine.parse(html, site)
        if not items:
            return []

        ts = datetime.now(timezone.utc).astimezone().isoformat()
        recs: list[DataRecord] = []
        for item in items:
            title = str(item.get("title", "") or "").strip()
            link = str(item.get("link", "") or "").strip()
            summary = str(item.get("summary", "") or "").strip()
            if not title:
                continue
            if link and not link.startswith("http"):
                link = "https://cn.cointelegraph.com" + link
            recs.append(DataRecord(
                source=self.source,
                category="news",
                sub_category="news",
                timestamp=ts,
                metrics={"title": title, "link": link, "summary": summary[:200]},
                events=[],
                timeseries=[],
                raw={"title": title, "link": link, "summary": summary},
            ))
        return recs
