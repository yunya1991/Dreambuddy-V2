"""CryptoPanic 新闻情绪采集器 — 免费 tier REST API，需 Key。

数据源: https://cryptopanic.com/api/v1/
- 新闻 + 社区 bullish/bearish 投票
- 免费tier: API key, 每日有限额度
- 补充 GDELT 的 per-coin 新闻情绪

端点：
  GET /api/v1/posts/?auth_token=KEY&kind=news
  GET /api/v1/posts/?auth_token=KEY&currencies=BTC
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_BASE = "https://cryptopanic.com/api/v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class CryptoPanicCollector(BaseCollector):
    """CryptoPanic 新闻 + 社区情绪采集器。"""

    source = "cryptopanic"
    category = "news"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._api_key: str = (
            self.config.get("api_key")
            or os.environ.get("CRYPTOPANIC_API_KEY", "")
        )

    def is_available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, params: dict) -> list[DataRecord]:
        if not self.is_available():
            return []
        currencies = params.get("currencies", "BTC")
        kind = params.get("kind", "news")
        try:
            resp = requests.get(
                f"{_BASE}/posts/",
                params={
                    "auth_token": self._api_key,
                    "kind": kind,
                    "currencies": currencies,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []  # fail-open

        results = data.get("results", [])
        if not results:
            return []

        events: list[dict] = []
        bullish_count = 0
        bearish_count = 0
        important_count = 0
        for post in results[:30]:
            votes = post.get("votes", {})
            if votes.get("liked"):
                bullish_count += 1
            if votes.get("disliked"):
                bearish_count += 1
            if votes.get("important"):
                important_count += 1
            events.append({
                "title": post.get("title", "")[:200],
                "url": post.get("url", ""),
                "published": post.get("published_at", ""),
                "source": post.get("source", {}).get("name", ""),
                "bullish": votes.get("liked", 0),
                "bearish": votes.get("disliked", 0),
            })

        sentiment = "bullish" if bullish_count > bearish_count else "bearish" if bearish_count > bullish_count else "neutral"
        total = bullish_count + bearish_count
        bull_ratio = bullish_count / total if total > 0 else 0

        rec = DataRecord(
            source="cryptopanic",
            category="news",
            sub_category="crypto_sentiment",
            timestamp=_now_iso(),
            metrics={
                "currencies": currencies,
                "news_count": len(results),
                "bullish_count": bullish_count,
                "bearish_count": bearish_count,
                "important_count": important_count,
                "bull_ratio": round(bull_ratio, 4),
                "sentiment": sentiment,
            },
            events=events,
            timeseries=[],
            raw={"source": "cryptopanic.com", "currencies": currencies},
        )
        validate_record(rec)
        return [rec]
