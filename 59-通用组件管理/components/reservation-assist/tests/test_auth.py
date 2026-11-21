"""登录态：Keychain 读取、Cookie 注入、缺失时不发探测。"""

from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import _support
import security
from adapters import get_adapter


class CookieTest(unittest.TestCase):
    def test_load_cookie_reads_keychain(self):
        with (
            patch("security.shutil.which", return_value="/usr/bin/security"),
            patch(
                "security.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="SESSION=abc\n", stderr=""),
            ) as run,
        ):
            self.assertEqual(security.load_cookie("railway"), "SESSION=abc")
        self.assertIn("find-generic-password", run.call_args.args[0])

    def test_load_cookie_absent_returns_empty(self):
        with (
            patch("security.shutil.which", return_value="/usr/bin/security"),
            patch(
                "security.subprocess.run",
                return_value=SimpleNamespace(returncode=1, stdout="", stderr="not found"),
            ),
        ):
            self.assertEqual(security.load_cookie("railway"), "")

    def test_load_cookie_timeout_returns_empty(self):
        with (
            patch("security.shutil.which", return_value="/usr/bin/security"),
            patch(
                "security.subprocess.run",
                side_effect=subprocess.TimeoutExpired("security", 3),
            ),
        ):
            self.assertEqual(security.load_cookie("railway"), "")

    def test_probe_injects_cookie_header(self):
        adapter = get_adapter("railway")
        adapter.cookie = "SESSION=abc"
        transport = _support.FakeTransport(body='{"trains": []}')
        adapter.probe({"target_id": "G1", "url": "https://example.invalid"}, transport)
        self.assertEqual(transport.requests[0]["headers"]["Cookie"], "SESSION=abc")

    def test_login_state_uses_cookie(self):
        adapter = get_adapter("damai")
        self.assertEqual(adapter.login_state(), "unknown")
        adapter.cookie = "SESSION=abc"
        self.assertEqual(adapter.login_state(), "ok")
        self.assertEqual(adapter.login_state({"logged_in": False}), "unknown")

    def test_store_cookie_writes_keychain(self):
        with (
            patch("security.shutil.which", return_value="/usr/bin/security"),
            patch(
                "security.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ) as run,
        ):
            self.assertTrue(security.store_cookie("railway", "SESSION=abc"))
        argv = run.call_args.args[0]
        self.assertIn("add-generic-password", argv)
        self.assertIn("com.reservation-assist.railway", argv)

    def test_store_cookie_rejects_empty_or_failure(self):
        with (
            patch("security.shutil.which", return_value="/usr/bin/security"),
            patch(
                "security.subprocess.run",
                return_value=SimpleNamespace(returncode=1, stdout="", stderr="denied"),
            ),
        ):
            self.assertFalse(security.store_cookie("railway", "SESSION=abc"))
        self.assertFalse(security.store_cookie("railway", ""))

    def test_delete_cookie(self):
        with (
            patch("security.shutil.which", return_value="/usr/bin/security"),
            patch(
                "security.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ),
        ):
            self.assertTrue(security.delete_cookie("railway"))

    def test_feishu_app_channel_requires_config(self):
        from notify import FeishuAppChannel

        with self.assertRaises(RuntimeError):
            FeishuAppChannel({}).send("x")

    def test_feishu_app_channel_sends(self):
        from notify import FeishuAppChannel

        channel = FeishuAppChannel({"app_id": "cli_x", "app_secret": "s", "chat_id": "oc_1"})
        replies = [{"tenant_access_token": "t"}, {"code": 0}]
        with patch.object(channel, "_post", side_effect=replies) as mocked:
            channel.send("hello")
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(mocked.call_args_list[1].args[1]["receive_id"], "oc_1")

    def test_build_notifier_registers_feishu_app(self):
        from notify import FeishuAppChannel, build_notifier

        notifier = build_notifier("feishu_app")
        self.assertIsInstance(notifier.channels[0], FeishuAppChannel)

    def test_feishu_webhook_from_keychain(self):
        from notify import FeishuChannel

        with (
            patch("notify.shutil.which", return_value="/usr/bin/security"),
            patch(
                "notify.subprocess.run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout="https://open.feishu.cn/open-apis/bot/v2/hook/abc\n",
                    stderr="",
                ),
            ),
            patch.dict("os.environ", {"RA_FEISHU_WEBHOOK": ""}),
        ):
            self.assertEqual(
                FeishuChannel().webhook, "https://open.feishu.cn/open-apis/bot/v2/hook/abc"
            )

    def test_feishu_webhook_missing(self):
        from notify import FeishuChannel

        with (
            patch("notify.shutil.which", return_value="/usr/bin/security"),
            patch(
                "notify.subprocess.run",
                return_value=SimpleNamespace(returncode=1, stdout="", stderr="not found"),
            ),
            patch.dict("os.environ", {"RA_FEISHU_WEBHOOK": ""}),
        ):
            self.assertEqual(FeishuChannel().webhook, "")


if __name__ == "__main__":
    unittest.main()
