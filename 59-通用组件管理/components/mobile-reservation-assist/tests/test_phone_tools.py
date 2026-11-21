"""P0 工具分层测试：L3 语义工具注册表 + L4 平台编排只允许调用已登记工具。"""

from __future__ import annotations

import unittest

import _support  # noqa: F401 - 注册 scripts 到 sys.path

import phone_adapters
import phone_tools
from phone_adapters.base import CommandError


class RegistryTest(unittest.TestCase):
    def test_core_tools_registered(self) -> None:
        for name in ("open_app", "goto", "search", "select_session", "select_tier", "goto_order_page", "stop"):
            self.assertIn(name, phone_tools.TOOLS)

    def test_evidence_tools_registered_as_readonly(self) -> None:
        for name in ("capture_screenshot", "read_page_text", "read_order_status"):
            self.assertEqual(phone_tools.TOOLS[name].side_effect, "read")

    def test_payment_tools_forbidden(self) -> None:
        for name in ("pay", "submit_order", "lock_seat"):
            self.assertTrue(phone_tools.TOOLS[name].forbidden)

    def test_build_step_rejects_unknown_tool(self) -> None:
        with self.assertRaises(CommandError):
            phone_tools.build_step("hack_screen")

    def test_build_step_rejects_forbidden_tool(self) -> None:
        with self.assertRaises(CommandError):
            phone_tools.build_step("pay", channel="alipay")

    def test_build_step_requires_params(self) -> None:
        with self.assertRaises(CommandError):
            phone_tools.build_step("open_app")

    def test_build_step_ok(self) -> None:
        step = phone_tools.build_step("open_app", app="com.example")
        self.assertEqual(step, {"action": "open_app", "app": "com.example"})

    def test_validate_steps_rejects_foreign_action(self) -> None:
        with self.assertRaises(CommandError):
            phone_tools.validate_steps([{"action": "unknown_action"}])

    def test_tool_specs_have_risk_level(self) -> None:
        for name, spec in phone_tools.TOOLS.items():
            self.assertIn(spec.risk, ("low", "medium", "high"), name)
            self.assertIn(spec.side_effect, ("read", "ui", "irreversible"), name)


class AdapterLayeringTest(unittest.TestCase):
    def test_all_adapter_steps_use_registered_tools(self) -> None:
        job = {
            "_id": 1,
            "target": {"target_id": "G1", "session": "2026-12-01", "price_tier": "二等座"},
            "max_price": 600,
        }
        for name in phone_adapters.ADAPTERS:
            command = phone_adapters.get_adapter(name).describe(job)
            for step in command.get("steps") or []:
                self.assertIn(step["action"], phone_tools.TOOLS, "{} 使用了未登记工具".format(name))

    def test_adapter_never_emits_forbidden_tool(self) -> None:
        job = {"_id": 1, "target": {"target_id": "x", "session": "s", "price_tier": "t"}}
        for name in phone_adapters.ADAPTERS:
            command = phone_adapters.get_adapter(name).describe(job)
            for step in command.get("steps") or []:
                self.assertFalse(phone_tools.TOOLS[step["action"]].forbidden)

    def test_l3_has_no_platform_tokens(self) -> None:
        from _support import SCRIPTS

        for path in (SCRIPTS / "phone_tools").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in ("12306", "cn.damai", "tv.danmaku.bili", "com.MobileTicket", "会员购"):
                self.assertNotIn(token, text, "{} 出现平台词 {}".format(path.name, token))


if __name__ == "__main__":
    unittest.main()
