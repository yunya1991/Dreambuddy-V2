"""存储测试：作业去重、认领状态流转、终态查询。"""

from __future__ import annotations

import unittest

import _support  # noqa: F401 - 注册 scripts 到 sys.path


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_enqueue_is_idempotent(self) -> None:
        self.assertTrue(self.db.enqueue_job(_support.sample_hit()))
        self.assertFalse(self.db.enqueue_job(_support.sample_hit()))

    def test_claim_pending_transitions(self) -> None:
        self.db.enqueue_job(_support.sample_hit())
        claimed = self.db.claim_pending("dev-1", limit=10)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["_state"], "dispatched")
        # 再次认领应为空
        self.assertEqual(self.db.claim_pending("dev-1", limit=10), [])

    def test_terminal_state(self) -> None:
        self.db.enqueue_job(_support.sample_hit())
        job = self.db.list_jobs()[0]
        self.assertFalse(self.db.has_terminal(job["task_id"], job["fingerprint"]))
        self.db.set_job_state(job["_id"], "done")
        self.assertTrue(self.db.has_terminal(job["task_id"], job["fingerprint"]))


if __name__ == "__main__":
    unittest.main()
