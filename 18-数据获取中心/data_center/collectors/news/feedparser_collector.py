"""Feedparser collector — 通用 RSS 采集。

feedparser 薄封装，parse(url) -> entries -> DataRecord(category=news)。
每条 entry 产出一条 DataRecord，metrics 存扁平字段（title/link/author），events 存 summary。
"""
from __future__ import annotations

from datetime import datetime, timezone

import feedparser

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class FeedparserCollector(BaseCollector):
    """通用 RSS collector，用 feedparser.parse 抓取任意 RSS/Atom feed。"""

    source = "feedparser"
    category = "news"

    def fetch(self, params: dict) -> list[DataRecord]:
        feed_url = params.get("feed_url")
        if not feed_url:
            return []

        max_items = params.get("max_items", 50)
        parsed = feedparser.parse(feed_url)
        feed_meta = parsed.get("feed", {}) if isinstance(parsed, dict) else {}
        entries = parsed.get("entries", []) if isinstance(parsed, dict) else []

        feed_title = feed_meta.get("title") or feed_url
        ts = _now_iso()

        recs: list[DataRecord] = []
        for entry in entries[:max_items]:
            if not isinstance(entry, dict):
                continue
            title = entry.get("title", "")
            link = entry.get("link", "")
            author = entry.get("author", "")
            summary = entry.get("summary", "")
            rec = DataRecord(
                source="feedparser",
                category="news",
                sub_category=feed_title,
                timestamp=ts,
                metrics={
                    "title": title,
                    "link": link,
                    "author": author,
                },
                events=[{"summary": summary}] if summary else [],
                timeseries=[],
                raw=dict(entry),
            )
            validate_record(rec)
            recs.append(rec)
        return recs
