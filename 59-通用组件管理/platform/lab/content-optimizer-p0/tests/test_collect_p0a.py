"""P0-A 外挂采集器单元测试：只测纯函数与本地落盘，不触碰手机。"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import collect_p0a as p0a  # noqa: E402


class ParseLikesTest(unittest.TestCase):
    def test_plain_and_units(self):
        self.assertEqual(p0a._parse_likes("1234"), 1234)
        self.assertEqual(p0a._parse_likes("1,234"), 1234)
        self.assertEqual(p0a._parse_likes("1.2万"), 12000)
        self.assertEqual(p0a._parse_likes("3w"), 30000)
        self.assertEqual(p0a._parse_likes("1.1亿"), 110000000)
        self.assertIsNone(p0a._parse_likes(""))
        self.assertIsNone(p0a._parse_likes("赞"))


class TitlePatternTest(unittest.TestCase):
    def test_patterns(self):
        self.assertEqual(p0a._title_pattern("3步看懂财报"), "number")
        self.assertEqual(p0a._title_pattern("为什么降息反而跌"), "question")
        self.assertEqual(p0a._title_pattern("A股 vs 港股"), "contrast")
        self.assertEqual(p0a._title_pattern("避坑指南"), "benefit")
        self.assertEqual(p0a._title_pattern("别再追高了"), "emotion")
        self.assertEqual(p0a._title_pattern(""), "unknown")


class NormalizeTest(unittest.TestCase):
    def test_item_maps_without_body_text(self):
        item = {
            "title": "3步看懂财报",
            "author": "某人",
            "likes": "1.2万",
            "keyword": "财经",
            "body": "这里是正文，绝不能写入 samples.csv。",
        }
        row = p0a._normalize_item("xiaohongshu", item, "财经", "2026-11-24T12:00:00+08:00")
        self.assertEqual(row["platform"], "xiaohongshu")
        self.assertEqual(row["source_type"], "public")
        self.assertEqual(row["title"], "3步看懂财报")
        self.assertEqual(row["likes"], 12000)
        self.assertGreater(row["body_len"], 0)
        self.assertNotIn("这里是正文", json.dumps(row, ensure_ascii=False))
        self.assertEqual(row["author_followers_bucket"], "unknown")

    def test_missing_fields_are_null_not_zero(self):
        row = p0a._normalize_item("douyin", {"title": "测试"}, "财经", "2026-11-24T12:00:00+08:00")
        self.assertIsNone(row["saves"])
        self.assertIsNone(row["comments"])
        self.assertIsNone(row["shares"])
        self.assertIn("saves", row["missing_flags"])


class CoverageAndWriteTest(unittest.TestCase):
    def test_coverage_counts_missing(self):
        rows = [
            {"title": "a", "likes": 1},
            {"title": None, "likes": 2},
        ]
        result = p0a._coverage(rows, ["title", "likes"])
        self.assertEqual(result["fields_present_min"], 1)
        self.assertEqual(result["missing_fields"]["title"], 1)
        self.assertEqual(result["missing_fields"]["likes"], 0)

    def test_write_samples_dedupes(self):
        rows = [
            p0a._normalize_item(
                "xiaohongshu",
                {"title": "同一篇", "likes": "10"},
                "财经",
                "2026-11-24T12:00:00+08:00",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            old = p0a.SAMPLES_PATH
            p0a.SAMPLES_PATH = Path(tmp) / "samples.csv"
            try:
                written, skipped = p0a._write_samples(rows)
                self.assertEqual((written, skipped), (1, 0))
                again, dup = p0a._write_samples(rows)
                self.assertEqual((again, dup), (0, 1))
                with p0a.SAMPLES_PATH.open(encoding="utf-8", newline="") as handle:
                    data = list(csv.DictReader(handle))
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["title"], "同一篇")
            finally:
                p0a.SAMPLES_PATH = old


class EventTest(unittest.TestCase):
    def test_event_fail_open_and_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = p0a.EVENTS_PATH
            p0a.EVENTS_PATH = Path(tmp) / "events" / "content_event.jsonl"
            try:
                event = p0a._event(
                    "collect.result",
                    "xhs.scout",
                    trace_id="t1",
                    run_id="r1",
                    status="timeout",
                    error_code="TIMEOUT",
                    duration_ms=60,
                )
                self.assertEqual(event["schema_version"], "content_event.v1")
                self.assertEqual(event["error_code"], "TIMEOUT")
                line = p0a.EVENTS_PATH.read_text(encoding="utf-8").strip()
                self.assertEqual(json.loads(line)["trace_id"], "t1")
            finally:
                p0a.EVENTS_PATH = old


if __name__ == "__main__":
    unittest.main()
