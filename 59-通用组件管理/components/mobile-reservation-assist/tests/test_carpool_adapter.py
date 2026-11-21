"""顺风车抢单适配器：L3 工具登记、授权门禁、平台透传与接单上限。"""

from __future__ import annotations

import unittest

import _support
import executor
from phone_adapters import get_adapter
from phone_adapters.base import CommandError
from phone_tools import TOOLS


def carpool_job(**overrides) -> dict:
    job = {
        "_id": 7,
        "adapter": "carpool",
        "target": {"platform": "didi", "order_id": "D123", "min_price": 35, "price": 40},
        "accept_authorized": True,
        "max_accept": 1,
        "accepted_today": 0,
    }
    job.update(overrides)
    return job


class CarpoolAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = get_adapter("carpool")

    def test_tools_registered(self) -> None:
        for name in ("goto_order_hall", "list_orders", "parse_orders", "accept_order"):
            self.assertIn(name, TOOLS, "未登记 L3 工具：{}".format(name))

    def test_steps_are_registered_tools(self) -> None:
        command = self.adapter.describe(carpool_job())
        self.assertEqual(command["adapter"], "carpool")
        self.assertEqual(command["platform"], "didi")
        self.assertTrue(command["steps"])
        for step in command["steps"]:
            self.assertIn(step["action"], TOOLS)
        self.assertEqual(command["steps"][-1]["action"], "stop")

    def test_unauthorized_never_accepts(self) -> None:
        command = self.adapter.describe(carpool_job(accept_authorized=False))
        actions = [step["action"] for step in command["steps"]]
        self.assertNotIn("accept_order", actions)
        self.assertIn("list_orders", actions)
        self.assertIn("parse_orders", actions)

    def test_missing_order_id_rejected(self) -> None:
        job = carpool_job(target={"platform": "didi", "min_price": 35})
        with self.assertRaises(CommandError):
            self.adapter.describe(job)

    def test_platform_passthrough(self) -> None:
        command = self.adapter.describe(
            carpool_job(target={"platform": "dida", "order_id": "T1", "min_price": 30})
        )
        self.assertEqual(command["platform"], "dida")
        self.assertEqual(command["app"], "com.didapinche.booking")
        hall = [step for step in command["steps"] if step["action"] == "goto_order_hall"][0]
        self.assertEqual(hall["platform"], "dida")

    def test_unknown_platform_rejected(self) -> None:
        with self.assertRaises(CommandError):
            self.adapter.describe(carpool_job(target={"platform": "uber", "order_id": "U1"}))

    def test_daily_accept_limit(self) -> None:
        job = carpool_job(accepted_today=1, max_accept=1)
        with self.assertRaises(CommandError):
            self.adapter.describe(job)

    def test_price_floor(self) -> None:
        job = carpool_job(target={"platform": "didi", "order_id": "D1", "min_price": 35, "price": 20})
        with self.assertRaises(CommandError):
            self.adapter.describe(job)

    def test_executor_treats_accept_as_order_stage(self) -> None:
        self.assertIn("accept", executor.ORDER_STAGES)
        command = executor.build_command(carpool_job())
        self.assertEqual(command["adapter"], "carpool")
        self.assertTrue(command["trace_id"])
        self.assertEqual(command["receipt"]["schema"], executor.RECEIPT_SCHEMA)


if __name__ == "__main__":
    unittest.main()
