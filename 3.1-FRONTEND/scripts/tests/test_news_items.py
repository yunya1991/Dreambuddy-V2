"""news_items.py 只读查询测试：分页、过滤、窗口与降级回退。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import news_items  # noqa: E402


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def _digest_payload() -> dict:
    return {
        "generated_at": _iso(0.1),
        "stats": {"total": 3, "dedup_saved": 1},
        "coverage": {"zero_days": 0},
        "items": [
            {
                "id": "a",
                "ts": _iso(1),
                "title": "BTC ETF 单日流入创新高",
                "topic": "crypto_reg",
                "event_type": "flow",
                "sentiment": {"label": "利好", "score": 0.8},
                "importance": 90,
                "origin": "odaily",
                "source_url": "https://example.com/a",
            },
            {
                "id": "b",
                "ts": _iso(72),
                "title": "美联储官员发表讲话",
                "topic": "rates_policy",
                "event_type": "speech",
                "sentiment": {"label": "中性", "score": 0.0},
                "importance": 70,
                "origin": "cls",
                "source_url": "https://example.com/b",
            },
            {
                "id": "c",
                "ts": _iso(240),
                "title": "旧新闻：交易所储备下降",
                "topic": "crypto_reg",
                "event_type": "exchange",
                "sentiment": {"label": "利空", "score": -0.6},
                "importance": 60,
                "origin": "wublock",
                "source_url": "https://example.com/c",
            },
        ],
    }


class NewsItemsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.digest = Path(self.temp.name) / "news_digest.json"
        self.hot = Path(self.temp.name) / "hot_news.json"
        self.digest.write_text(json.dumps(_digest_payload(), ensure_ascii=False), encoding="utf-8")
        self.patches = [
            mock.patch.object(news_items, "DIGEST_PATH", self.digest),
            mock.patch.object(news_items, "HOT_PATH", self.hot),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_window_slices_digest(self):
        self.assertEqual(news_items.query("24h")["total"], 1)
        self.assertEqual(news_items.query("7d")["total"], 2)
        self.assertEqual(news_items.query("30d")["total"], 3)

    def test_filters_and_pagination(self):
        result = news_items.query("30d", topic="crypto_reg", q="btc", min_importance=50)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["items"][0]["event_id"], "a")
        page = news_items.query("30d", limit=1, offset=1)
        self.assertEqual(page["returned"], 1)
        self.assertTrue(page["has_more"])
        self.assertEqual(page["items"][0]["event_id"], "b")

    def test_sentiment_filter(self):
        result = news_items.query("30d", sentiment="利空")
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["items"][0]["event_id"], "c")

    def test_fallback_to_hot(self):
        self.digest.unlink()
        self.hot.write_text(
            json.dumps(
                {
                    "generated_at": _iso(0.2),
                    "stats": {"total": 1},
                    "top": [
                        {
                            "event_id": "h1",
                            "title": "热点新闻",
                            "topic": "macro",
                            "sentiment": {"label": "中性", "score": 0},
                            "importance": 66,
                            "published_at": _iso(1),
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = news_items.query("24h")
        self.assertEqual(result["source"], "hot_news")
        self.assertTrue(result["degraded"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["event_id"], "h1")

    def test_missing_sources_is_degraded_empty(self):
        self.digest.unlink()
        result = news_items.query("24h")
        self.assertTrue(result["degraded"])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["items"], [])


if __name__ == "__main__":
    unittest.main()
