"""爆款侦察 / 笔记本 / 多素材链路测试（不访问网络、不连接手机）。"""

from __future__ import annotations

import unittest

import _support  # noqa: F401 - 注入 skill/scripts 到 sys.path

import brain
import executor
import mra
from phone_adapters import CommandError, get_adapter


class ScoutAdapterTest(unittest.TestCase):
    def test_scout_tracks_and_interaction(self) -> None:
        command = get_adapter("xiaohongshu").describe(
            {"mode": "scout", "track": "财经, 经济,时事, AI Agent,数据服务", "limit": 9, "interact": True}
        )
        self.assertEqual(command["mode"], "scout")
        self.assertEqual(command["track"], ["财经", "经济", "时事", "AI Agent", "数据服务"])
        self.assertEqual(command["limit"], 8)  # 读取上限 8；互动另有 5 次硬上限
        self.assertTrue(command["interact"])
        actions = [step["action"] for step in command["steps"]]
        self.assertIn("browse_feed", actions)
        self.assertIn("interact_post", actions)
        self.assertEqual(actions[-1], "stop")

    def test_scout_without_interaction_has_no_interact_step(self) -> None:
        command = get_adapter("xiaohongshu").describe({"mode": "scout", "interact": False})
        actions = [step["action"] for step in command["steps"]]
        self.assertNotIn("interact_post", actions)
        self.assertEqual(command["track"], ["财经", "经济", "时事", "AI Agent", "数据服务"])

    def test_post_mode_is_default(self) -> None:
        command = get_adapter("xiaohongshu").describe({"note": {"title": "t", "body": "b"}})
        self.assertEqual(command["mode"], "post")
        self.assertFalse(command["publish_authorized"])


class NotesAdapterTest(unittest.TestCase):
    def test_append_writes_memo_step(self) -> None:
        command = get_adapter("notes").describe({"mode": "append", "text": "素材A", "tag": "素材"})
        self.assertEqual([step["action"] for step in command["steps"]], ["open_app", "write_memo", "stop"])
        self.assertEqual(command["steps"][1]["text"], "素材A")
        self.assertEqual(command["tag"], "素材")

    def test_list_reads_recent_notes(self) -> None:
        command = get_adapter("notes").describe({"mode": "list", "limit": 3})
        self.assertEqual([step["action"] for step in command["steps"]], ["open_app", "read_memo", "stop"])
        self.assertEqual(command["limit"], 3)

    def test_empty_memo_is_rejected(self) -> None:
        with self.assertRaises(CommandError):
            get_adapter("notes").describe({"mode": "append", "text": ""})


class NewsMultiTest(unittest.TestCase):
    def test_count_is_clamped_and_timeout_scales(self) -> None:
        command = get_adapter("news").describe({"source": "sina", "count": 9})
        self.assertEqual(command["count"], 5)
        self.assertGreaterEqual(command["exec_timeout_ms"], 450000)
        self.assertEqual([step["action"] for step in command["steps"]][:2], ["open_app", "read_article"])

    def test_default_count_is_one(self) -> None:
        command = get_adapter("news").describe({"source": "wallstreetcn"})
        self.assertEqual(command["count"], 1)

    def test_focus_adds_search_step(self) -> None:
        command = get_adapter("news").describe({"source": "sina", "focus": "美联储降息"})
        self.assertEqual(command["focus"], "美联储降息")
        actions = [step["action"] for step in command["steps"]]
        self.assertEqual(actions[:3], ["open_app", "search", "read_article"])
        self.assertEqual(command["steps"][1]["value"], "美联储降息")


class TrendAnalysisTest(unittest.TestCase):
    def _patch(self, content: str):
        original = brain.chat
        brain.chat = lambda messages, **kwargs: content
        return original

    def test_normalize_trends_dedupes_and_limits(self) -> None:
        data = {
            "themes": ["数据拆解", "数据拆解", "AI 工具"],
            "formats": "新闻+方法\n对比表",
            "directions": ["d1", "d2"],
            "style_brief": "x" * 900,
            "avoid": ["标题党"],
        }
        trend = brain.normalize_trends(data)
        self.assertEqual(trend["themes"], ["数据拆解", "AI 工具"])
        self.assertEqual(trend["formats"], ["新闻+方法", "对比表"])
        self.assertEqual(len(trend["style_brief"]), 600)

    def test_normalize_trends_new_analysis_fields(self) -> None:
        trend = brain.normalize_trends(
            {
                "titles": {"patterns": ["数字+反差"], "examples": ["示例标题"]},
                "style": {"tone": "克制", "structure": "先结论后证据", "density": "高", "hooks": ["反常识"]},
                "learn": ["开头给可验证数字"],
                "recommend": [{"topic": "降息后的资产定价", "angle": "用一张对比表", "format": "图文", "why": "今天有数据"}],
            }
        )
        self.assertEqual(trend["title_patterns"], ["数字+反差"])
        self.assertEqual(trend["style"]["structure"], "先结论后证据")
        self.assertEqual(trend["learn"], ["开头给可验证数字"])
        self.assertEqual(trend["recommend"][0]["topic"], "降息后的资产定价")

    def test_recommend_accepts_plain_strings(self) -> None:
        trend = brain.normalize_trends({"recommend": ["选题A"]})
        self.assertEqual(trend["recommend"], [{"topic": "选题A", "angle": "", "format": "", "why": ""}])

    def test_analyze_trends_parses_model_json(self) -> None:
        content = (
            '{"themes":["数据拆解"],"formats":["清单"],"directions":["从爆款形式迁移到Agent工具测评"],'
            '"style_brief":"短句+数据","do":["开头给结论"],"avoid":["不荐股"]}'
        )
        original = self._patch(content)
        try:
            trend = brain.analyze_trends([{"title": "t", "keyword": "金融", "likes": "1.2万", "body": "b"}])
        finally:
            brain.chat = original
        self.assertEqual(trend["themes"], ["数据拆解"])
        self.assertIn("Agent", trend["directions"][0])

    def test_compose_note_accepts_multiple_materials_and_trend(self) -> None:
        captured = {}

        def fake_chat(messages, **kwargs):
            captured["prompt"] = messages[-1]["content"]
            return '{"title":"多篇汇总","body":"正文","topics":["数据"]}'

        original = brain.chat
        brain.chat = fake_chat
        try:
            note = brain.compose_note(
                {"title": "第一篇", "body": "A"},
                materials=[{"title": "第一篇", "body": "A"}, {"title": "第二篇", "body": "B"}],
                trend={"style_brief": "短句"},
            )
        finally:
            brain.chat = original
        self.assertEqual(note["title"], "多篇汇总")
        self.assertIn('"articles"', captured["prompt"])
        self.assertIn("第二篇", captured["prompt"])
        self.assertIn("短句", captured["prompt"])


class ChainHelperTest(unittest.TestCase):
    def test_split_counts_distributes_remainder(self) -> None:
        self.assertEqual(mra._split_counts(3, 2), [2, 1])
        self.assertEqual(mra._split_counts(4, 2), [2, 2])
        self.assertEqual(mra._split_counts(1, 2), [1, 0])

    def test_source_and_track_lists(self) -> None:
        self.assertEqual(mra._source_list("sina,wallstreetcn,sina"), ["sina", "wallstreetcn"])
        self.assertEqual(mra._source_list("unknown"), ["wallstreetcn"])
        self.assertEqual(mra._track_list(""), ["财经", "经济", "时事", "AI Agent", "数据服务"])
        self.assertEqual(mra._track_list("财经,财经,数据服务"), ["财经", "数据服务"])

    def test_trend_memo_contains_directions(self) -> None:
        text = mra._trend_memo(
            {"themes": ["a"], "formats": ["b"], "directions": ["c"], "style_brief": "d", "avoid": ["e"]}
        )
        for word in ("主题：a", "形式：b", "可扩展方向", "· c", "风格：d", "避开：e"):
            self.assertIn(word, text)


class ChainCliTest(unittest.TestCase):
    def test_chain_parser_defaults(self) -> None:
        args = mra.build_parser().parse_args(["xhs", "chain", "--count", "4", "--publish"])
        self.assertEqual(args.xhs_cmd, "chain")
        self.assertEqual(args.count, 4)
        self.assertTrue(args.publish)
        self.assertEqual(args.sources, "wallstreetcn,sina")

    def test_compose_accepts_multiple_articles(self) -> None:
        args = mra.build_parser().parse_args(
            ["xhs", "compose", "--article", "a.json", "--article", "b.json", "--trend", "t.json"]
        )
        self.assertEqual(args.article, ["a.json", "b.json"])
        self.assertEqual(args.trend, "t.json")

    def test_memo_and_scout_parsers(self) -> None:
        memo = mra.build_parser().parse_args(["xhs", "memo", "add", "--text", "素材"])
        self.assertEqual(memo.memo_cmd, "add")
        scout = mra.build_parser().parse_args(["xhs", "scout", "--limit", "2"])
        self.assertEqual(scout.limit, 2)
        self.assertFalse(scout.no_interact)


class ExecutorWiringTest(unittest.TestCase):
    def test_notes_and_scout_jobs_build_commands(self) -> None:
        memo = executor.build_command({"adapter": "notes", "mode": "append", "text": "x", "_id": 1})
        self.assertEqual(memo["mode"], "append")
        self.assertEqual(memo["steps"][-1]["action"], "stop")
        scout = executor.build_command({"adapter": "xiaohongshu", "mode": "scout", "_id": 2})
        self.assertEqual(scout["mode"], "scout")
        self.assertTrue(scout["trace_id"])


if __name__ == "__main__":
    unittest.main()
