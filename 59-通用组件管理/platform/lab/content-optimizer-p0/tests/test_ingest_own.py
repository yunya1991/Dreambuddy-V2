"""S2 回流单测：台账 + metrics → own 样本的映射、幂等与 public 保留。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ingest_own as io_  # noqa: E402

CN_TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 24, 23, 0, 0, tzinfo=CN_TZ)


def ts_of(dt: datetime) -> int:
    return int(dt.timestamp())


def ledger_row(rid="R1", title="3步看懂降息", topics=None, channels=None, ts=None):
    return {
        "run_id": rid,
        "profile": "finance",
        "scope": "domestic",
        "title": title,
        "topics": ["理财", "降息"] if topics is None else topics,
        "channels": {"xiaohongshu": "done"} if channels is None else channels,
        "ts": ts_of(NOW - timedelta(days=1)) if ts is None else ts,
    }


def public_row(sample_id="pub1", platform="xiaohongshu"):
    row = io_._blank_row()
    row.update(
        {
            "sample_id": sample_id,
            "platform": platform,
            "source_type": "public",
            "collected_at": "2026-11-24T21:00:00+08:00",
            "title": "公开样本",
            "likes": 100,
        }
    )
    return row


class MappingTest(unittest.TestCase):
    def test_xiaohongshu_mapping(self):
        metrics = {
            "3步看懂降息": {
                "likes": 120,
                "collects": 30,
                "comments": 8,
                "views": 900,
                "updated_at": "2026-11-24T22:00:00+08:00",
            }
        }
        rows, stats = io_.ingest([ledger_row()], metrics, [], now=NOW)
        self.assertEqual(stats["added"], 1)
        row = rows[0]
        self.assertTrue(row["sample_id"].startswith("own-"))
        self.assertEqual(len(row["sample_id"]), 16)
        self.assertEqual(row["platform"], "xiaohongshu")
        self.assertEqual(row["source_type"], "own")
        self.assertEqual(row["collector"], "creator_export")
        self.assertEqual(row["media_type"], "image")
        self.assertEqual(row["rank_bucket"], "unknown")
        self.assertEqual(row["title_len"], len("3步看懂降息"))
        self.assertEqual(row["title_pattern"], "number")
        self.assertEqual(row["topic_count"], 2)
        self.assertEqual(row["hashtag_count"], 2)
        self.assertEqual(row["likes"], 120)
        self.assertEqual(row["saves"], 30)  # collects → saves
        self.assertEqual(row["comments"], 8)
        self.assertEqual(row["views"], 900)
        self.assertEqual(row["metrics_at"], "2026-11-24T22:00:00+08:00")
        self.assertIsNone(row["shares"])
        self.assertEqual(row["publish_hour"], 23)
        self.assertEqual(row["weekday"], 1)  # 2026-11-23 是周一
        self.assertEqual(row["outlier_flags"], "")

    def test_douyin_and_multi_channel(self):
        metrics = {"3步看懂降息": {"likes": 5, "collects": 1, "comments": 0}}
        row = ledger_row(channels={"xiaohongshu": "done", "douyin": "done", "wechat": "done"})
        rows, stats = io_.ingest([row], metrics, [], now=NOW)
        self.assertEqual(stats["added"], 2)
        platforms = {r["platform"]: r for r in rows}
        self.assertEqual(set(platforms), {"xiaohongshu", "douyin"})
        self.assertEqual(platforms["douyin"]["media_type"], "video")
        self.assertEqual(platforms["douyin"]["comments"], 0)  # 0 是有效值，不转 null
        self.assertNotEqual(platforms["douyin"]["sample_id"], platforms["xiaohongshu"]["sample_id"])

    def test_no_done_channel_is_skipped(self):
        rows, stats = io_.ingest([ledger_row(channels={"xiaohongshu": "failed"})], {}, [], now=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(stats["added"], 0)
        self.assertEqual(stats["skipped"], 1)

    def test_missing_metrics_null_and_flags(self):
        rows, _ = io_.ingest([ledger_row()], {}, [], now=NOW)
        row = rows[0]
        self.assertIsNone(row["likes"])
        self.assertIsNone(row["saves"])
        self.assertIsNone(row["metrics_at"])
        flags = row["missing_flags"].split(";")
        for key in ("likes", "collects", "comments", "views"):
            self.assertIn(key, flags)

    def test_empty_topics_flagged(self):
        rows, _ = io_.ingest([ledger_row(topics=[])], {}, [], now=NOW)
        self.assertEqual(rows[0]["topic_count"], 0)
        self.assertIn("topics", rows[0]["missing_flags"].split(";"))


class CensorTest(unittest.TestCase):
    def test_within_seven_days_is_censored(self):
        row = ledger_row(ts=ts_of(NOW - timedelta(days=2)))
        rows, _ = io_.ingest([row], {}, [], now=NOW)
        self.assertTrue(rows[0]["is_censored"])

    def test_older_than_seven_days_is_not_censored(self):
        row = ledger_row(ts=ts_of(NOW - timedelta(days=9)))
        rows, _ = io_.ingest([row], {}, [], now=NOW)
        self.assertFalse(rows[0]["is_censored"])


class IdempotentTest(unittest.TestCase):
    def test_latest_ts_wins_for_same_run(self):
        old = ledger_row(ts=ts_of(NOW - timedelta(days=5)))
        new = ledger_row(ts=ts_of(NOW - timedelta(days=1)))
        rows, stats = io_.ingest([old, new], {}, [], now=NOW)
        self.assertEqual(stats["added"], 1)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(rows[0]["published_at"][:10], "2026-11-23")

    def test_public_rows_kept_and_rerun_stable(self):
        ledger = [ledger_row()]
        metrics = {"3步看懂降息": {"likes": 10, "collects": 2, "comments": 1}}
        first, stats1 = io_.ingest(ledger, metrics, [public_row()], now=NOW)
        self.assertEqual(stats1["replaced"], 0)
        second, stats2 = io_.ingest(ledger, metrics, first, now=NOW)
        self.assertEqual(stats2["replaced"], 1)
        self.assertEqual(len(second), 2)
        self.assertEqual(
            json.dumps(second, ensure_ascii=False), json.dumps(first, ensure_ascii=False)
        )
        self.assertEqual(second[0]["sample_id"], "pub1")

    def test_rerun_preserves_existing_public_rows(self):
        rows, stats = io_.ingest([], {}, [public_row("pub1"), public_row("pub2")], now=NOW)
        self.assertEqual(stats["own_total"], 0)
        self.assertEqual([r["sample_id"] for r in rows], ["pub1", "pub2"])


class CliTest(unittest.TestCase):
    def test_write_and_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            fixed = state / "fixed"
            fixed.mkdir(parents=True)
            (fixed / "published.jsonl").write_text(
                json.dumps(ledger_row(), ensure_ascii=False) + "\n", encoding="utf-8"
            )
            (fixed / "metrics.json").write_text(
                json.dumps({"3步看懂降息": {"likes": 7, "collects": 3, "comments": 2}}),
                encoding="utf-8",
            )
            samples = Path(tmp) / "samples.csv"

            io_.main(["--state-dir", str(state), "--samples", str(samples), "--dry-run"])
            self.assertFalse(samples.exists())

            io_.main(["--state-dir", str(state), "--samples", str(samples)])
            existing, columns = io_.read_csv_rows(str(samples))
            self.assertEqual(columns, io_.COLUMNS)
            self.assertEqual(len(existing), 1)
            self.assertEqual(existing[0]["source_type"], "own")
            self.assertEqual(existing[0]["likes"], "7")
            self.assertEqual(existing[0]["is_censored"], "true")

            io_.main(["--state-dir", str(state), "--samples", str(samples)])
            again, _ = io_.read_csv_rows(str(samples))
            self.assertEqual(len(again), 1)
            self.assertEqual(again[0]["sample_id"], existing[0]["sample_id"])


if __name__ == "__main__":
    unittest.main()
