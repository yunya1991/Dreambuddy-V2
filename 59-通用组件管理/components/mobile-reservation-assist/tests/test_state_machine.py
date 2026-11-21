"""P0 状态机测试：待人工 / 人工接管 / 订单未知，以及禁止「不确定就重试」。"""

from __future__ import annotations

import unittest

import _support  # noqa: F401 - 注册 scripts 到 sys.path

import executor
import store as store_mod


class StateConstantsTest(unittest.TestCase):
    def test_new_states_registered(self) -> None:
        for state in ("pending_human", "takeover", "order_unknown"):
            self.assertIn(state, store_mod.STATES)

    def test_human_and_unknown_states_block_reenqueue(self) -> None:
        # 这些状态都意味着「同一 fingerprint 不得再次自动入队」，避免重复下单
        for state in ("pending_human", "takeover", "order_unknown"):
            self.assertIn(state, store_mod.BLOCKING_STATES)

    def test_terminal_states_exclude_human_waiting(self) -> None:
        self.assertNotIn("pending_human", store_mod.TERMINAL_STATES)
        self.assertNotIn("order_unknown", store_mod.TERMINAL_STATES)


class ResultMappingTest(unittest.TestCase):
    def test_needs_human_maps_to_pending_human(self) -> None:
        self.assertEqual(executor.normalize_result_state("needs_human", {}), "pending_human")

    def test_takeover_and_login_map_to_takeover(self) -> None:
        self.assertEqual(executor.normalize_result_state("takeover", {}), "takeover")
        self.assertEqual(executor.normalize_result_state("needs_login", {}), "takeover")

    def test_order_unknown_passthrough(self) -> None:
        self.assertEqual(executor.normalize_result_state("order_unknown", {}), "order_unknown")

    def test_error_in_order_stage_becomes_order_unknown(self) -> None:
        for stage in ("order_confirm", "cashier", "submit", "pay"):
            with self.subTest(stage=stage):
                self.assertEqual(
                    executor.normalize_result_state("error", {"stage": stage}), "order_unknown"
                )

    def test_error_before_order_stays_failed(self) -> None:
        self.assertEqual(executor.normalize_result_state("error", {"stage": "search"}), "failed")

    def test_captcha_still_cooldown(self) -> None:
        self.assertEqual(executor.normalize_result_state("captcha", {}), "cooldown")


class TransitionGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()
        self.db.enqueue_job(_support.sample_hit())
        self.job = self.db.list_jobs()[0]

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_order_unknown_cannot_go_back_to_pending(self) -> None:
        self.db.set_job_state(self.job["_id"], "order_unknown")
        with self.assertRaises(ValueError):
            self.db.set_job_state(self.job["_id"], "pending")
        with self.assertRaises(ValueError):
            self.db.set_job_state(self.job["_id"], "dispatched")

    def test_pending_human_cannot_be_redispatched(self) -> None:
        self.db.set_job_state(self.job["_id"], "pending_human")
        with self.assertRaises(ValueError):
            self.db.set_job_state(self.job["_id"], "dispatched")

    def test_unknown_state_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.db.set_job_state(self.job["_id"], "not_a_state")

    def test_blocks_reenqueue_uses_all_blocking_states(self) -> None:
        self.db.set_job_state(self.job["_id"], "order_unknown")
        self.assertTrue(self.db.blocks_reenqueue(self.job["task_id"], self.job["fingerprint"]))
        self.assertFalse(self.db.blocks_reenqueue("other", "fp-other"))

    def test_human_state_not_reset_by_acceptance(self) -> None:
        # dispatched 可复位为 pending；pending_human / order_unknown 不得被复位
        self.db.set_job_state(self.job["_id"], "pending_human")
        stuck = self.db.list_stuck(0)
        self.assertEqual(stuck, [])


if __name__ == "__main__":
    unittest.main()
