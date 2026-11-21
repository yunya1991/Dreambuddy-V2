"""执行器测试：指令构建强制停在支付前、门禁拒绝、回执状态映射。"""

from __future__ import annotations

import unittest

import _support
import executor
from phone_adapters.base import CommandError, assert_no_payment


class ExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()
        self.db.enqueue_job(_support.sample_hit())
        self.job = self.db.list_jobs()[0]

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_build_command_stops_before_payment(self) -> None:
        cmd = executor.build_command(self.job)
        self.assertEqual(cmd["adapter"], "railway")
        self.assertEqual(cmd["stop_before"], "payment")
        self.assertEqual(cmd["steps"][-1]["action"], "stop")
        assert_no_payment(cmd["steps"])  # 不抛即通过

    def test_no_payment_guard_raises(self) -> None:
        with self.assertRaises(CommandError):
            assert_no_payment([{"action": "pay", "amount": 100}])

    def test_ensure_executable_gates(self) -> None:
        with self.assertRaises(executor.GateDenied):
            executor.ensure_executable(self.job, self.db, env={"MRA_ALLOW_EXECUTE": "1"}, paused=True)
        with self.assertRaises(executor.GateDenied):
            executor.ensure_executable(self.job, self.db, env={"MRA_ALLOW_EXECUTE": "0"}, paused=False)
        # 正常放行
        executor.ensure_executable(self.job, self.db, env={"MRA_ALLOW_EXECUTE": "1"}, paused=False)

    def test_apply_result_mapping(self) -> None:
        res = executor.apply_result(self.db, self.job["_id"], "dev-1", "captcha", {})
        self.assertEqual(res["state"], "cooldown")
        self.assertTrue(self.db.has_terminal(self.job["task_id"], self.job["fingerprint"]))


if __name__ == "__main__":
    unittest.main()
