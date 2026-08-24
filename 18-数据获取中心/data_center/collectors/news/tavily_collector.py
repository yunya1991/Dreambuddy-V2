"""Tavily collector — AI 搜索采集，迁移自 data_collector。

tavily-python 薄封装，TavilyClient.search(query) -> results -> DataRecord(category=news)。
每条 result 产出一条 DataRecord，metrics 存扁平字段，events 存 content。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from tavily import TavilyClient

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class TavilyCollector(BaseCollector):
    """Tavily AI 搜索采集器。"""

    source = "tavily"
    category = "news"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._api_key: str = (
            self.config.get("api_key")
            or os.environ.get("TAVILY_API_KEY", "")
        )

    def is_available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, params: dict) -> list[DataRecord]:
        if not self.is_available():
            return []

        query = params.get("query")
        if not query:
            return []

        max_results = params.get("max_results", 10)
        client = TavilyClient(api_key=self._api_key)
        resp = client.search(query=query, max_results=max_results)
        results = resp.get("results", []) if isinstance(resp, dict) else []

        ts = _now_iso()
        recs: list[DataRecord] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            content = item.get("content", "")
            rec = DataRecord(
                source="tavily",
                category="news",
                sub_category=query,
                timestamp=ts,
                metrics={
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "source": item.get("source", ""),
                },
                events=[{"content": content}] if content else [],
                timeseries=[],
                raw=dict(item),
            )
            validate_record(rec)
            recs.append(rec)
        return recs
