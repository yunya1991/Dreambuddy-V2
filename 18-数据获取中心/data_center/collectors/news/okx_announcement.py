"""OKX 公告 Collector — 通过 Scrapling stealthy 抓取 OKX 支持中心公告列表。

渲染路径（FAIL-OPEN）：
  1. Scrapling StealthyFetcher（Patchright，绕过 OKX 可能的反爬）
  2. Scrapling 内部回退链（stealthy→dynamic→http→static）

产出 DataRecord(category=news, source=okx_announcement)。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord

logger = logging.getLogger("data_center.collectors.news.okx_announcement")

OKX_ANN_URL = "https://www.okx.com/support/hc/zh-cn/sections/360000030652"

# OKX 公告页 CSS 选择器（基于 support/hc 标准 Zendesk 结构）
_OKX_SELECTORS = {
    "item": "li.article-list-item a",
    "title": "::text",
    "link": "::attr(href)",
}


class OkxAnnouncementCollector(BaseCollector):
    """OKX 公告采集器（news / okx_announcement）。"""

    source = "okx_announcement"
    category = "news"

    def __init__(self, config: dict | None = None):
        super().__init__(config or {})
        self._url = self.config.get("url", OKX_ANN_URL)
        self._engine_mode = self.config.get("engine", "stealthy")
        self._adaptive = bool(self.config.get("adaptive", True))

    def is_available(self) -> bool:
        # scrapling 是懒加载，只要 Python 环境存在即认为可用
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

        # 构造 site dict 复用 ScraplingEngine.parse
        site = {
            "selectors": _OKX_SELECTORS,
            "adaptive": self._adaptive,
            "source": self.source,
            "sub_category": "announcement",
        }
        items = engine.parse(html, site)
        if not items:
            return []

        ts = datetime.now(timezone.utc).astimezone().isoformat()
        recs: list[DataRecord] = []
        for item in items:
            title = str(item.get("title", "") or "").strip()
            link = str(item.get("link", "") or "").strip()
            if not title:
                continue
            if link and not link.startswith("http"):
                link = "https://www.okx.com" + link
            recs.append(DataRecord(
                source=self.source,
                category="news",
                sub_category="announcement",
                timestamp=ts,
                metrics={"title": title, "link": link},
                events=[],
                timeseries=[],
                raw={"title": title, "link": link},
            ))
        return recs
