"""news-monitor 组件：归一化、data.v1 外壳与云端错误映射测试（不触网）。"""

from __future__ import annotations

import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

COMPONENT = Path(__file__).resolve().parents[1]
SCRIPTS = COMPONENT / "skill" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import news  # noqa: E402

SNAPSHOT = {
    "module": "news",
    "ts": "2026-11-22T07:51:14+00:00",
    "metrics": {
        "core": {
            "total_articles": 167,
            "positive_count": 38,
            "negative_count": 41,
            "neutral_count": 121,
            "sentiment_score": -0.015,
        },
        "breakdown": {
            "hot_news_top10": [
                {
                    "event_id": "bda9f9e514ef2362",
                    "title": "机构：美国10月PCE通胀料升至3.8%",
                    "topic": "rates_policy",
                    "sentiment": {"label": "利好", "score": 0.9987},
                    "importance": 88.2,
                    "published_at": "2026-11-22T06:10:59Z",
                    "origin": "odaily_newsflash",
                    "source_url": "https://example.com/a",
                    "rank": 1,
                }
            ],
            "hot_news_summary": {"total": 1, "window_h": 24},
            "theme_clusters": [
                {"topic": "other", "label": "其他", "count": 78, "avg_importance": 46}
            ],
        },
    },
    "timeseries_meta": {"quality": "good"},
}

SEARCH = {
    "ok": True,
    "data": {
        "success": True,
        "handled": True,
        "answer": "近 24 小时检索到 1 条相关新闻",
        "data": {
            "window_h": 24,
            "matched": 1,
            "scanned": 1,
            "coverage_note": "榜单口径",
            "unclassified_ratio": 0.5,
            "items": [
                {
                    "ts": "2026-11-22T06:10:59Z",
                    "title": "机构：美国10月PCE通胀料升至3.8%",
                    "topic": "rates_policy",
                    "sentiment": "利好",
                    "importance": 88.2,
                    "origin": "odaily_newsflash",
                    "source_url": "https://example.com/a",
                }
            ],
        },
    },
}

LIST = {
    "schema": "news_items/v1",
    "generated_at": "2026-11-22T08:00:00+00:00",
    "source": "news_digest",
    "source_generated_at": "2026-11-22T07:58:00+00:00",
    "window": "24h",
    "window_hours": 24,
    "total": 282,
    "matched": 2,
    "offset": 0,
    "limit": 2,
    "returned": 2,
    "has_more": True,
    "degraded": False,
    "degraded_reason": "",
    "stats": {"total": 590},
    "items": [
        {
            "event_id": "e1",
            "title": "SEC 就加密监管框架征求意见",
            "topic": "crypto_reg",
            "event_type": "regulatory",
            "sentiment": {"label": "利好", "score": 0.7},
            "importance": 82.1,
            "published_at": "2026-11-22T06:00:00Z",
            "origin": "odaily_newsflash",
            "source_url": "https://example.com/1",
            "source_count": 2,
            "dup_count": 3,
        },
        {
            "id": "e2",
            "title": "交易所公布储备证明",
            "topic": "crypto_reg",
            "event_type": "exchange",
            "sentiment": {"label": "中性", "score": 0.0},
            "importance": 70.5,
            "ts": "2026-11-22T05:00:00Z",
            "origin": "wublock",
            "source_url": "https://example.com/2",
        },
    ],
}


class EnvelopeTest(unittest.TestCase):
    def test_required_fields(self):
        payload = news._envelope("hot", [{"event_id": "x"}], data_date="2026-11-22")
        for key in (
            "skill",
            "version",
            "generated_at",
            "data_date",
            "rows",
            "missing",
            "method_ids",
            "sources",
            "limits",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["data_route"], "cloud")
        self.assertEqual(payload["skill"], "news-monitor")
        self.assertTrue(payload["method_ids"])

    def test_normalize_hot_keeps_event_id(self):
        row = news.normalize_hot(SNAPSHOT["metrics"]["breakdown"]["hot_news_top10"][0])
        self.assertEqual(row["event_id"], "bda9f9e514ef2362")
        self.assertEqual(row["sentiment"], "利好")
        self.assertEqual(row["importance"], 88.2)

    def test_normalize_hot_synthesizes_event_id(self):
        row = news.normalize_hot({"title": "无 id 新闻", "published_at": "2026-11-22T00:00:00Z"})
        self.assertEqual(len(row["event_id"]), 16)

    def test_metrics_rows_have_sample_n(self):
        rows = news.extract_metrics(SNAPSHOT)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("n", row)
            self.assertGreaterEqual(row["n"], 0)
        ratios = [row for row in rows if row["metric"] == "sentiment_score"]
        self.assertEqual(ratios[0]["n"], 167)
        cluster = [row for row in rows if row["metric"] == "theme_cluster"][0]
        self.assertEqual(cluster["n"], 78)

    def test_build_search_message(self):
        self.assertEqual(news.build_search_message("BTC", "24h"), "BTC 最近24小时新闻")
        self.assertEqual(news.build_search_message("BTC", "7d"), "BTC 最近新闻")
        self.assertEqual(news.build_search_message("", "30d"), "最近30天新闻")


class ActionTest(unittest.TestCase):
    def test_hot_action(self):
        buffer = StringIO()
        with mock.patch.object(news, "_http_json", return_value=SNAPSHOT), redirect_stdout(buffer):
            code = news.main(["hot", "--limit", "5"])
        self.assertEqual(code, 0)
        body = json.loads(buffer.getvalue())
        self.assertEqual(body["command"], "hot")
        self.assertEqual(len(body["rows"]), 1)
        self.assertEqual(body["data_route"], "cloud")

    def test_search_action_posts_message(self):
        captured = {}

        def fake_http(method, path, params=None, body=None, timeout=news.TIMEOUT):
            captured.update({"method": method, "path": path, "body": body})
            return SEARCH

        with (
            mock.patch.object(news, "_http_json", side_effect=fake_http),
            redirect_stdout(StringIO()),
        ):
            code = news.main(["search", "--keyword", "BTC", "--window", "24h"])
        self.assertEqual(code, 0)
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], news.SEARCH_PATH)
        self.assertEqual(captured["body"], {"message": "BTC 最近24小时新闻"})

    def test_local_endpoint_rejected(self):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = news.main(["hot", "--endpoint", "local"])
        self.assertEqual(code, 2)
        body = json.loads(buffer.getvalue())
        self.assertFalse(body["ok"])
        self.assertEqual(body["missing"][0]["code"], "E_INPUT")

    def test_network_error_maps_to_missing(self):
        buffer = StringIO()
        with (
            mock.patch.object(news, "_http_json", side_effect=news.NewsError("E_NET", "timed out")),
            redirect_stdout(buffer),
        ):
            code = news.main(["hot"])
        self.assertEqual(code, 1)
        body = json.loads(buffer.getvalue())
        self.assertEqual(body["missing"][0]["code"], "E_NET")
        self.assertTrue(body["missing"][0]["detail"])


class ListActionTest(unittest.TestCase):
    def test_list_requires_local_token(self):
        buffer = StringIO()
        with mock.patch.object(news, "_local_token", return_value=""), redirect_stdout(buffer):
            code = news.main(["list"])
        self.assertEqual(code, 2)
        body = json.loads(buffer.getvalue())
        self.assertFalse(body["ok"])
        self.assertEqual(body["missing"][0]["code"], "E_INPUT")

    def test_list_calls_local_gateway(self):
        captured = {}

        def fake_http(
            method,
            path,
            params=None,
            body=None,
            timeout=news.TIMEOUT,
            extra_headers=None,
        ):
            captured.update(
                {
                    "method": method,
                    "path": path,
                    "params": params,
                    "extra_headers": extra_headers,
                }
            )
            return LIST

        buffer = StringIO()
        with (
            mock.patch.object(news, "_local_token", return_value="secret"),
            mock.patch.object(news, "_http_json", side_effect=fake_http),
            redirect_stdout(buffer),
        ):
            code = news.main(
                [
                    "list",
                    "--window",
                    "24h",
                    "--limit",
                    "2",
                    "--topic",
                    "crypto_reg",
                    "--min-importance",
                    "60",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["path"], news.ITEMS_PATH)
        self.assertEqual(captured["extra_headers"], {news.TOKEN_HEADER: "secret"})
        self.assertEqual(captured["params"]["topic"], "crypto_reg")
        self.assertEqual(captured["params"]["min_importance"], 60.0)
        body = json.loads(buffer.getvalue())
        self.assertEqual(len(body["rows"]), 2)
        self.assertEqual(body["rows"][0]["event_id"], "e1")
        self.assertEqual(body["rows"][1]["event_id"], "e2")
        self.assertEqual(body["detail"]["matched"], 2)
        self.assertTrue(body["ok"])

    def test_list_degraded_marks_missing(self):
        degraded = dict(LIST, degraded=True, degraded_reason="digest missing", items=[])
        buffer = StringIO()
        with (
            mock.patch.object(news, "_local_token", return_value="secret"),
            mock.patch.object(news, "_http_json", return_value=degraded),
            redirect_stdout(buffer),
        ):
            code = news.main(["list"])
        self.assertEqual(code, 0)
        body = json.loads(buffer.getvalue())
        self.assertFalse(body["ok"])
        self.assertEqual(body["missing"][0]["code"], "E_EMPTY")


if __name__ == "__main__":
    unittest.main()
