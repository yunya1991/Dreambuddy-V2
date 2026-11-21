"""归一测试：从上游报告/本地 feed 归一命中、入队去重、跳过终态。"""

from __future__ import annotations

import unittest

import _support
import ingest
from _support import FIXTURES


class IngestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_load_from_fixture_and_ingest(self) -> None:
        hits = ingest.load_hits(source="file:" + str(FIXTURES / "feed_basic.json"))
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["adapter"], "railway")
        self.assertEqual(hits[0]["target"]["target_id"], "G1")

        first = ingest.ingest_into(self.db, hits)
        self.assertEqual(first["added"], 1)
        second = ingest.ingest_into(self.db, hits)
        self.assertEqual(second["added"], 0)
        self.assertEqual(second["skipped"], 1)

    def test_skip_terminal_submit(self) -> None:
        report = {
            "hits": [
                {"task_id": "t1", "fingerprint": "fp1", "at": 1, "submit_state": "submitted"},
                {"task_id": "t2", "fingerprint": "fp2", "at": 2, "submit_state": None},
            ]
        }
        hits = ingest.hits_from_report(report, {})
        self.assertEqual([h["fingerprint"] for h in hits], ["fp2"])


if __name__ == "__main__":
    unittest.main()
