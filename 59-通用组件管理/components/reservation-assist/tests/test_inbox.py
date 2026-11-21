"""入站解析与脱敏：只验证纯函数与 Keychain 往返，不发真实请求。"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
)

import inbox  # noqa: E402

FAKE_ID = "110101199001011234"
FAKE_PHONE = "13800138000"


class FakeStore:
    def __init__(self) -> None:
        self.meta: dict[str, str] = {}
        self.events: list[tuple] = []

    def get_meta(self, key: str, default: str = "") -> str:
        return self.meta.get(key, default)

    def set_meta(self, key: str, value: str) -> None:
        self.meta[key] = value

    def add_event(self, level: str, code: str, task_id: str, payload: dict) -> None:
        self.events.append((level, code, task_id, payload))


class ParseTest(unittest.TestCase):
    def test_parse_with_labels(self):
        people = inbox.parse_visitors("姓名 张三 身份证 {} 手机 {}".format(FAKE_ID, FAKE_PHONE))
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0]["name"], "张三")
        self.assertEqual(people[0]["id"], FAKE_ID)
        self.assertEqual(people[0]["phone"], FAKE_PHONE)

    def test_parse_without_name_label(self):
        people = inbox.parse_visitors("李四 {} ".format(FAKE_ID))
        self.assertEqual(people[0]["name"], "李四")

    def test_parse_ignores_text_without_id(self):
        self.assertEqual(inbox.parse_visitors("明天十点放票"), [])

    def test_parse_uppercases_x_suffix(self):
        people = inbox.parse_visitors("王五 11010119900101123x")
        self.assertTrue(people[0]["id"].endswith("X"))


class MaskTest(unittest.TestCase):
    def test_masks(self):
        self.assertEqual(inbox.mask_name("张三"), "张*")
        self.assertEqual(inbox.mask_id(FAKE_ID), "**************" + FAKE_ID[-4:])
        self.assertEqual(inbox.mask_phone(FAKE_PHONE), "138****8000")

    def test_summary_contains_no_full_id(self):
        line = inbox.summarize([{"name": "张三", "id": FAKE_ID, "phone": FAKE_PHONE}])[0]
        self.assertNotIn(FAKE_ID, line)
        self.assertNotIn(FAKE_PHONE, line)


class StorageTest(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        saved: dict[str, str] = {}

        def fake_run(cmd, **kwargs):
            saved["payload"] = cmd[-1]
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with (
            patch("inbox.shutil.which", return_value="/usr/bin/security"),
            patch("inbox.subprocess.run", side_effect=fake_run),
        ):
            self.assertTrue(inbox.save_visitors([{"name": "张三", "id": FAKE_ID}]))
        self.assertIn(FAKE_ID, saved["payload"])

        def fake_read(cmd, **kwargs):
            return type("R", (), {"returncode": 0, "stdout": saved["payload"], "stderr": ""})()

        with (
            patch("inbox.shutil.which", return_value="/usr/bin/security"),
            patch("inbox.subprocess.run", side_effect=fake_read),
        ):
            self.assertEqual(inbox.load_visitors()[0]["id"], FAKE_ID)

    def test_load_visitors_decodes_hex_from_security(self):
        import json as _json

        payload = _json.dumps([{"name": "张三", "id": FAKE_ID}], ensure_ascii=False)
        hexed = payload.encode("utf-8").hex()

        def fake_read(cmd, **kwargs):
            return type("R", (), {"returncode": 0, "stdout": hexed, "stderr": ""})()

        with (
            patch("inbox.shutil.which", return_value="/usr/bin/security"),
            patch("inbox.subprocess.run", side_effect=fake_read),
        ):
            self.assertEqual(inbox.load_visitors()[0]["id"], FAKE_ID)

    def test_decode_value_keeps_plain_text(self):
        self.assertEqual(
            inbox._decode_value("https://open.feishu.cn/x"), "https://open.feishu.cn/x"
        )


class PullTest(unittest.TestCase):
    def test_pull_saves_new_and_moves_cursor(self):
        store = FakeStore()
        messages = [
            {"message_id": "m1", "text": "姓名 张三 {}".format(FAKE_ID), "create_time": 5000},
        ]
        with (
            patch("inbox.fetch_messages", return_value=messages),
            patch("inbox.load_visitors", return_value=[]),
            patch("inbox.save_visitors", return_value=True),
        ):
            result = inbox.pull(store, {"app_id": "x", "chat_id": "oc_1"}, minutes=10)
        self.assertEqual(result["scanned"], 1)
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(store.meta["inbox_cursor"], "5001")
        self.assertTrue(any(event[1] == "inbox_pulled" for event in store.events))

    def test_pull_skips_duplicates(self):
        store = FakeStore()
        messages = [{"message_id": "m1", "text": FAKE_ID, "create_time": 5000}]
        with (
            patch("inbox.fetch_messages", return_value=messages),
            patch("inbox.load_visitors", return_value=[{"id": FAKE_ID, "name": "张三"}]),
            patch("inbox.save_visitors", return_value=True) as save,
        ):
            result = inbox.pull(store, {"app_id": "x", "chat_id": "oc_1"})
        self.assertEqual(len(result["added"]), 0)
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
