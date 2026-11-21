"""P0 对账测试：订单不确定必须人工/对账收敛，禁止自动重试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import _support
import executor
import mra


class StoreReconcileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()
        self.db.enqueue_job(_support.sample_hit())
        self.job = self.db.list_jobs()[0]
        self.db.set_job_state(self.job["_id"], "order_unknown")

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_list_order_unknown(self) -> None:
        rows = self.db.list_order_unknown()
        self.assertEqual([row["_id"] for row in rows], [self.job["_id"]])

    def test_reconcile_to_done_with_order_id(self) -> None:
        result = self.db.reconcile(self.job["_id"], "done", order_id="B123", note="对账确认已下单")
        self.assertTrue(result["resolved"])
        self.assertEqual(self.db.get_job(self.job["_id"])["_state"], "done")
        codes = [event["code"] for event in self.db.list_events()]
        self.assertIn("order_reconciled", codes)

    def test_reconcile_is_idempotent(self) -> None:
        self.db.reconcile(self.job["_id"], "done", order_id="B123")
        again = self.db.reconcile(self.job["_id"], "done", order_id="B123")
        self.assertFalse(again["resolved"])
        self.assertEqual(again["state"], "done")

    def test_reconcile_rejects_invalid_final_state(self) -> None:
        with self.assertRaises(ValueError):
            self.db.reconcile(self.job["_id"], "pending")

    def test_has_order_evidence(self) -> None:
        executor.apply_result(self.db, self.job["_id"], "dev-1", "order_unknown", {"order_id": "B9"})
        self.assertTrue(self.db.has_order_evidence(self.job["_id"]))


class ResetStuckGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MRA_STATE_DIR": self.tmp.name})
        self.env.start()
        with mra.open_store() as db:
            db.enqueue_job(_support.sample_hit())
            job = db.list_jobs()[0]
            db.set_job_state(job["_id"], "dispatched")
            db.add_result(job["_id"], "dev-1", "dispatched", {"order_id": "B777", "stage": "cashier"})
            self.job_id = job["_id"]

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_stuck_job_with_order_evidence_goes_order_unknown(self) -> None:
        result = mra._reset_stuck(seconds=0)
        self.assertEqual(result["reset"], [])
        self.assertEqual(result["order_unknown"], [self.job_id])
        with mra.open_store() as db:
            self.assertEqual(db.get_job(self.job_id)["_state"], "order_unknown")

    def test_order_unknown_never_reset(self) -> None:
        mra._reset_stuck(seconds=0)
        again = mra._reset_stuck(seconds=0)
        self.assertEqual(again["reset"], [])


class ReconcileActionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MRA_STATE_DIR": self.tmp.name})
        self.env.start()
        with mra.open_store() as db:
            db.enqueue_job(_support.sample_hit())
            job = db.list_jobs()[0]
            db.set_job_state(job["_id"], "order_unknown")
            self.job_id = job["_id"]

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_list_unresolved(self) -> None:
        payload = mra._reconcile({})
        self.assertEqual(len(payload["unresolved"]), 1)

    def test_resolve_via_action(self) -> None:
        payload = mra._reconcile({"job_id": self.job_id, "state": "failed", "note": "确认未下单"})
        self.assertTrue(payload["resolved"])
        with mra.open_store() as db:
            self.assertEqual(db.get_job(self.job_id)["_state"], "failed")


if __name__ == "__main__":
    unittest.main()
