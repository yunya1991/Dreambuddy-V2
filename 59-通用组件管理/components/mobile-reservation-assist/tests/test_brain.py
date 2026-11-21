"""大模型接入与白名单执行的离线单测（不访问网络）。"""

from __future__ import annotations

import os
import tempfile
import unittest

import _support  # noqa: F401 - 注入 skill/scripts 到 sys.path

import brain
import mra


class ExtractJsonTest(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(brain.extract_json('{"a": 1}'), {"a": 1})

    def test_fenced(self):
        self.assertEqual(brain.extract_json('```json\n{"a": 2}\n```'), {"a": 2})

    def test_with_prose(self):
        self.assertEqual(brain.extract_json('计划如下：\n{"a": 3}\n请确认'), {"a": 3})

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            brain.extract_json("没有 JSON")


class GuardPlanTest(unittest.TestCase):
    def test_rejects_unknown_and_forbidden(self):
        obj = {
            "intent": "x",
            "steps": [
                {"action": "jobs", "params": {}},
                {"action": "hack", "params": {}},
                {"action": "dispatch", "params": {"target_id": "支付通道", "adapter": "x"}},
            ],
            "note": "",
        }
        guarded = brain.guard_plan(obj)
        self.assertEqual([s["action"] for s in guarded["plan"]["steps"]], ["jobs"])
        self.assertEqual(len(guarded["rejected"]), 2)


class PlanTest(unittest.TestCase):
    def _patch(self, content: str):
        original = brain.chat
        brain.chat = lambda messages, **kwargs: content
        return original

    def test_plan_whitelist(self):
        original = self._patch('{"intent":"查看","steps":[{"action":"jobs","params":{}}],"note":""}')
        try:
            result = brain.plan("看看作业")
        finally:
            brain.chat = original
        self.assertEqual(result["steps"][0]["action"], "jobs")

    def test_parse_dispatch(self):
        original = self._patch(
            '{"adapter":"bilibili","target_id":"周杰伦","session":"2026-12-25",'
            '"price_tier":"内场","max_price":1280}'
        )
        try:
            data = brain.parse_dispatch("12月25日周杰伦内场")
        finally:
            brain.chat = original
        self.assertEqual(data["adapter"], "bilibili")
        self.assertEqual(data["target_id"], "周杰伦")
        self.assertEqual(data["max_price"], 1280)


class NoteTest(unittest.TestCase):
    def test_normalize_note_clamps_and_cleans(self):
        note = brain.normalize_note(
            {"title": "  一个很长很长很长很长很长很长的标题  ", "body": "正文", "topics": ["#宏观", "宏观", " 数据 "]}
        )
        self.assertEqual(note["title"], "一个很长很长很长很长很长很长的标题")
        self.assertLessEqual(len(note["title"]), 20)
        self.assertEqual(note["topics"], ["宏观", "数据"])

    def test_compose_note_includes_market_data(self):
        captured = {}

        def fake_chat(messages, **kwargs):
            captured["payload"] = messages[-1]["content"]
            return '{"title":"标题","body":"正文","topics":["宏观"]}'

        original = brain.chat
        brain.chat = fake_chat
        try:
            note = brain.compose_note(
                {"title": "文章", "body": "内容"}, data={"market": {"价格": 1}}
            )
        finally:
            brain.chat = original
        self.assertEqual(note["title"], "标题")
        self.assertIn("market_data", captured["payload"])
        self.assertIn("价格", captured["payload"])

    def test_image_prompt_is_deterministic(self):
        prompt = brain.image_prompt({"title": "测试主题"})
        self.assertIn("测试主题", prompt)
        self.assertIn("3:4", prompt)


class ExecuteTest(unittest.TestCase):
    def test_unknown_action_fails(self):
        results = mra.execute_steps([{"action": "nope", "params": {}}])
        self.assertFalse(results[0]["ok"])

    def test_dispatch_writes_and_is_idempotent(self):
        tmp = tempfile.TemporaryDirectory()
        os.environ["MRA_STATE_DIR"] = tmp.name
        try:
            params = {
                "adapter": "bilibili",
                "target_id": "周杰伦",
                "session": "2026-12-25",
                "price_tier": "内场",
            }
            first = mra._dispatch(params)
            self.assertTrue(first["enqueued"])
            with mra.open_store() as db:
                self.assertEqual(len(db.list_jobs()), 1)
            second = mra._dispatch(params)
            self.assertFalse(second["enqueued"])
        finally:
            os.environ.pop("MRA_STATE_DIR", None)
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
