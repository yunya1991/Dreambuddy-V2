"""GDELT collector — 全球事件/新闻流。

GDELT DOC 2.0 API 直连（requests），无 Key 需求，query -> articles -> DataRecord(category=news)。
GDELT 是免费开放的全球新闻事件数据库，覆盖全球多语言新闻。
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class GdeltCollector(BaseCollector):
    """GDELT DOC 2.0 新闻采集器。"""

    source = "gdelt"
    category = "news"

    def is_available(self) -> bool:
        # GDELT 免费，无需 Key
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        query = params.get("query")
        if not query:
            return []

        max_records = params.get("max_records", 10)
        resp = requests.get(
            GDELT_DOC_API,
            params={
                "query": query,
                "mode": "artlist",
                "format": "json",
                "maxrecords": max_records,
                "sort": "datedesc",
            },
            timeout=30,
        )

        try:
            data = resp.json()
        except ValueError:
            # GDELT 无匹配时可能返回空 body，静默降级
            return []

        articles = data.get("articles", []) if isinstance(data, dict) else []
        ts = _now_iso()

        recs: list[DataRecord] = []
        for art in articles:
            if not isinstance(art, dict):
                continue
            rec = DataRecord(
                source="gdelt",
                category="news",
                sub_category=query,
                timestamp=ts,
                metrics={
                    "title": art.get("title", ""),
                    "url": art.get("url", ""),
                    "domain": art.get("domain", ""),
                    "sourcecountry": art.get("sourcecountry", ""),
                },
                events=[],
                timeseries=[],
                raw=dict(art),
            )
            validate_record(rec)
            recs.append(rec)
        return recs
