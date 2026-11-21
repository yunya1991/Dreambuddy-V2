"""P0 结构化回执测试：trace_id / stage / screenshot / page_text / order_id。"""

from __future__ import annotations

import unittest

import _support
import executor


class ReceiptNormalizeTest(unittest.TestCase):
    def test_fills_all_required_keys(self) -> None:
        receipt = executor.normalize_receipt({}, trace_id="tr-1")
        for key in ("trace_id", "stage", "screenshot", "page_text", "order_id"):
            self.assertIn(key, receipt)
        self.assertEqual(receipt["trace_id"], "tr-1")

    def test_keeps_extra_evidence(self) -> None:
        receipt = executor.normalize_receipt({"reason": "captcha", "steps": [1]}, trace_id="tr-1")
        self.assertEqual(receipt["reason"], "captcha")
        self.assertEqual(receipt["steps"], [1])

    def test_page_text_is_truncated(self) -> None:
        receipt = executor.normalize_receipt({"page_text": "x" * 9999})
        self.assertLessEqual(len(receipt["page_text"]), executor.PAGE_TEXT_LIMIT)

    def test_detail_trace_id_wins_over_command(self) -> None:
        receipt = executor.normalize_receipt({"trace_id": "from-phone"}, trace_id="from-command")
        self.assertEqual(receipt["trace_id"], "from-phone")


class CommandTraceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()
        self.db.enqueue_job(_support.sample_hit())
        self.job = self.db.list_jobs()[0]

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_command_carries_trace_and_receipt_contract(self) -> None:
        cmd = executor.build_command(self.job)
        self.assertTrue(cmd["trace_id"])
        self.assertEqual(cmd["receipt"]["schema"], "mra.receipt.v1")
        self.assertIn("stage", cmd["receipt"]["required"])
        self.assertIn("order_id", cmd["receipt"]["required"])

    def test_apply_result_persists_structured_columns(self) -> None:
        detail = {
            "trace_id": "tr-9",
            "stage": "order_confirm",
            "screenshot": "agent_debug/1.png",
            "page_text": "确认订单 实付 380 元",
            "order_id": "B20261225001",
        }
        executor.apply_result(self.db, self.job["_id"], "dev-1", "needs_human", detail)
        row = self.db.latest_result(self.job["_id"])
        self.assertIsNotNone(row)
        self.assertEqual(row["state"], "pending_human")
        self.assertEqual(row["trace_id"], "tr-9")
        self.assertEqual(row["stage"], "order_confirm")
        self.assertEqual(row["screenshot"], "agent_debug/1.png")
        self.assertEqual(row["order_id"], "B20261225001")
        self.assertIn("确认订单", row["detail"]["page_text"])

    def test_error_at_order_stage_marks_order_unknown(self) -> None:
        executor.apply_result(
            self.db, self.job["_id"], "dev-1", "error", {"stage": "cashier", "error": "timeout"}
        )
        self.assertEqual(self.db.get_job(self.job["_id"])["_state"], "order_unknown")

    def test_order_unknown_writes_reconcile_event(self) -> None:
        executor.apply_result(self.db, self.job["_id"], "dev-1", "order_unknown", {"stage": "pay"})
        codes = [event["code"] for event in self.db.list_events()]
        self.assertIn("order_unknown_pending_reconcile", codes)

    def test_duplicate_receipt_is_idempotent(self) -> None:
        detail = {"trace_id": "tr-dup", "stage": "order_confirm"}
        first = executor.apply_result(self.db, self.job["_id"], "dev-1", "needs_human", detail)
        second = executor.apply_result(self.db, self.job["_id"], "dev-1", "needs_human", detail)
        self.assertFalse(first.get("duplicate"))
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(len(self.db.list_results()), 1)


if __name__ == "__main__":
    unittest.main()
