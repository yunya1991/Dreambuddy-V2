"""抖音图文链路测试（不访问网络、不连接手机）。"""

from __future__ import annotations

import unittest

import _support  # noqa: F401 - 注入 skill/scripts 到 sys.path

import brain
import executor
import mra
from phone_adapters import get_adapter


class DouyinAdapterTest(unittest.TestCase):
    def test_post_stops_before_publish_by_default(self) -> None:
        command = get_adapter("douyin").describe(
            {"note": {"title": "标题", "body": "正文", "topics": ["#数据", "数据", "AI"], "images": ["a.png"]}}
        )
        self.assertEqual(command["mode"], "post")
        self.assertFalse(command["publish_authorized"])
        self.assertEqual(command["stop_before"], "publish")
        self.assertEqual(command["topics"], ["数据", "AI"])
        self.assertEqual(command["steps"][-1]["action"], "stop")

    def test_title_is_truncated_to_douyin_limit(self) -> None:
        command = get_adapter("douyin").describe({"note": {"title": "标" * 80, "body": "正文"}})
        self.assertEqual(len(command["title"]), 55)

    def test_publish_only_when_authorized(self) -> None:
        command = get_adapter("douyin").describe(
            {"note": {"title": "t", "body": "b"}, "publish_authorized": True}
        )
        self.assertTrue(command["publish_authorized"])

    def test_scout_tracks_and_limit(self) -> None:
        command = get_adapter("douyin").describe(
            {"mode": "scout", "track": "财经, 经济,AI Agent", "limit": 20, "interact": True}
        )
        self.assertEqual(command["mode"], "scout")
        self.assertEqual(command["track"], ["财经", "经济", "AI Agent"])
        self.assertEqual(command["limit"], 8)
        actions = [step["action"] for step in command["steps"]]
        self.assertIn("browse_feed", actions)
        self.assertEqual(actions[-1], "stop")


class DouyinComposeTest(unittest.TestCase):
    def test_normalize_note_cleans_topics_and_pages(self) -> None:
        note = brain.normalize_douyin_note(
            {
                "title": "  美股 AI 交易降温  ",
                "body": "正文",
                "topics": "#AI #数据 AI",
                "pages": [
                    {"heading": "钩子", "points": ["p1", "p2", "p3", "p4", "p5"]},
                    "纯文本页",
                ],
            }
        )
        self.assertEqual(note["title"], "美股 AI 交易降温")
        self.assertEqual(note["topics"], ["AI", "数据"])
        self.assertEqual(len(note["pages"][0]["points"]), 4)
        self.assertEqual(note["pages"][1]["heading"], "纯文本页")

    def test_compose_douyin_parses_model_json(self) -> None:
        original = brain.chat
        brain.chat = lambda messages, **kwargs: (
            '{"title":"数字+反差","body":"正文","topics":["数据"],'
            '"pages":[{"heading":"封面页","points":["要点"]}]}'
        )
        try:
            note = brain.compose_douyin_note({"title": "素材", "body": "内容"})
        finally:
            brain.chat = original
        self.assertEqual(note["title"], "数字+反差")
        self.assertEqual(note["pages"][0]["heading"], "封面页")

    def test_image_prompt_mentions_douyin_and_avoids_codes(self) -> None:
        prompt = brain.douyin_image_prompt({"title": "降息之后"}, "", "第一页")
        self.assertIn("抖音", prompt)
        self.assertIn("股票代码", prompt)


class DouyinChainTest(unittest.TestCase):
    def test_parser_defaults(self) -> None:
        args = mra.build_parser().parse_args(["douyin", "chain", "--count", "2", "--publish"])
        self.assertEqual(args.douyin_cmd, "chain")
        self.assertEqual(args.count, 2)
        self.assertTrue(args.publish)
        self.assertEqual(args.image_count, 1)

    def test_cover_generates_pages_in_reverse_order(self) -> None:
        calls = []

        def fake_generate(prompt: str, timeout: int = 300) -> dict:
            calls.append(prompt)
            return {"state": "done", "materials": ["/sdcard/DCIM/QuarkAI/p{}.jpg".format(len(calls))]}

        original = mra._generate_cover
        mra._generate_cover = fake_generate
        try:
            result = mra._douyin_cover(
                {"title": "标题", "pages": [{"heading": "封面", "points": []}, {"heading": "正文页", "points": []}]},
                "", 2,
            )
        finally:
            mra._generate_cover = original
        self.assertEqual(result["state"], "done")
        self.assertEqual(len(result["materials"]), 2)
        # 先生成正文页、最后生成封面页，保证相册时间倒序首张是封面
        self.assertIn("正文页", calls[0])
        self.assertIn("封面", calls[-1])

    def test_executor_builds_douyin_command(self) -> None:
        job = {"_id": 9, "adapter": "douyin", "note": {"title": "t", "body": "b"}}
        command = executor.build_command(job)
        self.assertEqual(command["adapter"], "douyin")
        self.assertTrue(command["trace_id"])
        self.assertFalse(command["publish_authorized"])


if __name__ == "__main__":
    unittest.main()
