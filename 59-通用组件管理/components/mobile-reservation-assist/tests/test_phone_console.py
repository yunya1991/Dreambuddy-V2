"""CLI 手机操控台测试：动作解析、驱动调用、参数映射与白名单接入（不连真机）。"""

from __future__ import annotations

import argparse
import unittest
from unittest import mock

import _support  # noqa: F401

import brain
import mra
import phone_console


class FakeDriver:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.package = "com.lemon.lv"

    def app_start(self, package: str) -> None:
        self.calls.append(("app_start", package))
        self.package = package

    def app_restart(self, package: str) -> None:
        self.calls.append(("app_restart", package))
        self.package = package

    def current_package(self) -> str:
        return self.package

    def tap(self, text: str, timeout: float = 8.0) -> bool:
        self.calls.append(("tap", text, timeout))
        return True

    def tap_xy(self, x: int, y: int) -> bool:
        self.calls.append(("tap_xy", x, y))
        return True

    def type_text(self, text: str, hint: str = "", clear: bool = False) -> bool:
        self.calls.append(("type", text, hint, clear))
        return True

    def swipe_xy(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> bool:
        self.calls.append(("swipe", x1, y1, x2, y2))
        return True

    def window_size(self) -> tuple[int, int]:
        return (1080, 2400)

    def press(self, key: str) -> bool:
        self.calls.append(("press", key))
        return True

    def page_text(self, limit: int = 1200) -> str:
        return "图文成片\n开始创作"

    def screenshot(self, tag: str = "console") -> str:
        return "/tmp/shot.png"

    def wait(self, text: str, timeout: float = 10.0):
        self.calls.append(("wait", text))
        return object()


class AppAliasTest(unittest.TestCase):
    def test_alias_and_package(self) -> None:
        self.assertEqual(phone_console.resolve_app("jianying"), "com.lemon.lv")
        self.assertEqual(phone_console.resolve_app("小红书"), "com.xingin.xhs")
        self.assertEqual(phone_console.resolve_app("com.example.app"), "com.example.app")

    def test_empty_app_rejected(self) -> None:
        with self.assertRaises(ValueError):
            phone_console.resolve_app("  ")


class ParseLineTest(unittest.TestCase):
    def test_open_alias(self) -> None:
        self.assertEqual(phone_console.parse_line("open jianying"), ("open_app", {"app": "jianying"}))

    def test_tap_text_and_xy(self) -> None:
        self.assertEqual(phone_console.parse_line("tap 图文成片"), ("tap", {"text": "图文成片"}))
        self.assertEqual(phone_console.parse_line("tap x=500 y=1200"), ("tap", {"x": 500, "y": 1200}))

    def test_type_and_swipe(self) -> None:
        self.assertEqual(phone_console.parse_line("type 你好"), ("type", {"text": "你好"}))
        self.assertEqual(phone_console.parse_line("swipe down"), ("swipe", {"direction": "down"}))

    def test_unknown_command(self) -> None:
        with self.assertRaises(ValueError):
            phone_console.parse_line("fly away")


class ConsoleActionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.driver = FakeDriver()
        self.console = phone_console.PhoneConsole(driver=self.driver)

    def test_open_app_resolves_alias(self) -> None:
        result = self.console.execute("open_app", app="jianying")
        self.assertTrue(result["ok"])
        self.assertEqual(result["app"], "com.lemon.lv")
        self.assertEqual(self.driver.calls[0], ("app_start", "com.lemon.lv"))

    def test_open_app_restart(self) -> None:
        self.console.execute("open_app", app="douyin", restart=True)
        self.assertEqual(self.driver.calls[0], ("app_restart", "com.ss.android.ugc.aweme"))

    def test_tap_by_text_and_xy(self) -> None:
        self.assertTrue(self.console.execute("tap", text="开始创作")["ok"])
        self.assertTrue(self.console.execute("tap", x=10, y=20)["ok"])
        self.assertEqual(self.driver.calls, [("tap", "开始创作", 8.0), ("tap_xy", 10, 20)])
        with self.assertRaises(ValueError):
            self.console.execute("tap")

    def test_type_passes_hint_and_clear(self) -> None:
        self.console.execute("type", text="正文", hint="添加作品描述", clear=True)
        self.assertEqual(self.driver.calls[0], ("type", "正文", "添加作品描述", True))

    def test_swipe_direction_uses_screen_size(self) -> None:
        result = self.console.execute("swipe", direction="up")
        self.assertTrue(result["ok"])
        self.assertEqual(self.driver.calls[0], ("swipe", 540, 1800, 540, 600))

    def test_screen_returns_package_and_text(self) -> None:
        result = self.console.execute("screen", limit=200)
        self.assertEqual(result["package"], "com.lemon.lv")
        self.assertIn("图文成片", result["text"])

    def test_key_and_shot_and_wait(self) -> None:
        self.console.execute("key", key="back")
        self.console.execute("shot", tag="t")
        self.assertTrue(self.console.execute("wait", text="导出", timeout=3)["found"])
        self.assertEqual(self.driver.calls[0], ("press", "back"))
        self.assertEqual(self.driver.calls[-1], ("wait", "导出"))

    def test_unknown_action(self) -> None:
        with self.assertRaises(ValueError):
            self.console.execute("pay")


class CliWiringTest(unittest.TestCase):
    def test_parser_phone_subcommands(self) -> None:
        parser = mra.build_parser()
        self.assertEqual(parser.parse_args(["phone", "open", "jianying"]).phone_cmd, "open_app")
        self.assertEqual(parser.parse_args(["phone", "tap", "--xy", "1,2"]).xy, "1,2")
        self.assertEqual(parser.parse_args(["phone", "screen", "--limit", "50"]).limit, 50)
        self.assertEqual(parser.parse_args(["console"]).func, mra.cmd_console)

    def test_phone_params_mapping(self) -> None:
        args = argparse.Namespace(phone_cmd="tap", text="", xy="500,1200", timeout=5.0)
        self.assertEqual(mra._phone_params(args), {"x": 500, "y": 1200, "timeout": 5.0})
        args = argparse.Namespace(phone_cmd="swipe", direction="up", duration=0.2, xy1="1,2", xy2="3,4")
        self.assertEqual(
            mra._phone_params(args),
            {"direction": "up", "duration": 0.2, "x1": 1, "y1": 2, "x2": 3, "y2": 4},
        )

    def test_cmd_phone_uses_console(self) -> None:
        fake = mock.Mock()
        fake.execute.return_value = {"ok": True, "app": "com.lemon.lv"}
        args = argparse.Namespace(phone_cmd="open_app", app="jianying", restart=False)
        with mock.patch.object(phone_console, "PhoneConsole", return_value=fake):
            self.assertEqual(mra.cmd_phone(args), mra.EXIT_OK)
        fake.execute.assert_called_once_with("open_app", app="jianying", restart=False)

    def test_brain_allows_ui_actions(self) -> None:
        for action in ("open_app", "tap", "type", "swipe", "key", "screen", "shot", "wait", "pkg"):
            self.assertIn(action, brain.ALLOWED_ACTIONS)

    def test_precheck_requires_app_and_text(self) -> None:
        self.assertFalse(brain.precheck("open_app", {})["ok"])
        self.assertFalse(brain.precheck("tap", {})["ok"])
        self.assertTrue(brain.precheck("tap", {"text": "导出"})["ok"])
        self.assertTrue(brain.precheck("screen", {})["ok"])


if __name__ == "__main__":
    unittest.main()
