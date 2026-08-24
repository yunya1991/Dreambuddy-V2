"""RSSHub collector — RSSHub 路由 -> feedparser。

RSSHub 将各类网站转为 RSS feed，本 collector 把 route 映射成完整 URL 后复用 feedparser 采集逻辑。
继承 FeedparserCollector，覆写 source 与 URL 组装方式。
"""
from __future__ import annotations

from data_center.collectors.news.feedparser_collector import FeedparserCollector
from data_center.core.contract import DataRecord

DEFAULT_BASE_URL = "https://rsshub.app"


class RsshubCollector(FeedparserCollector):
    """RSSHub 路由采集器：route -> base_url + route -> feedparser。"""

    source = "rsshub"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._base_url: str = (
            self.config.get("base_url") or DEFAULT_BASE_URL
        ).rstrip("/")

    def fetch(self, params: dict) -> list[DataRecord]:
        route = params.get("route")
        if not route:
            return []

        feed_url = f"{self._base_url}/{route.lstrip('/')}"
        # 组装 feed_url 后交给父类（feedparser）逻辑，但 source 覆写为 rsshub
        child_params = dict(params)
        child_params.pop("route", None)
        child_params["feed_url"] = feed_url
        recs = super().fetch(child_params)
        for r in recs:
            r.source = "rsshub"
        return recs
