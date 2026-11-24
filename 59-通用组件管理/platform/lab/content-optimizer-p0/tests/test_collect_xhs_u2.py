"""小红书只读采集器纯函数单测：不依赖真机。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import collect_xhs_u2 as m  # noqa: E402


def node(
    text: str, x1: int, y1: int, x2: int, y2: int, cls: str = "TextView", desc: str = ""
) -> dict:
    return {"cls": cls, "text": text, "desc": desc, "x1": x1, "y1": y1, "x2": x2, "y2": y2}


class RelativeTimeTest(unittest.TestCase):
    def test_days_and_defaults(self) -> None:
        self.assertEqual(m._relative_time("6天前"), 6)
        self.assertEqual(m._relative_time("2周前"), 14)
        self.assertEqual(m._relative_time("3小时前"), 0)
        self.assertEqual(m._relative_time("刚刚"), 0)
        self.assertIsNone(m._relative_time("abc"))

    def test_month_day(self) -> None:
        days = m._relative_time("11-10")
        self.assertIsNotNone(days)
        self.assertGreaterEqual(days, 0)


class ParseCardsTest(unittest.TestCase):
    def test_pairs_title_author_likes(self) -> None:
        nodes = [
            node("上海财经大学应用统计考研经验", 13, 1305, 534, 1409),
            node("研途小记", 13, 1420, 200, 1460),
            node("11-18", 13, 1465, 90, 1495),
            node("1280", 470, 1465, 534, 1495),
        ]
        cards = m._parse_cards(nodes)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["author"], "研途小记")
        self.assertEqual(cards[0]["likes"], "1280")
        self.assertEqual(cards[0]["relative_time"], "11-18")

    def test_skips_ad_card(self) -> None:
        nodes = [
            node("广告", 546, 900, 600, 930),
            node("这是一条广告笔记的标题内容", 546, 940, 1067, 1040),
        ]
        self.assertEqual(m._parse_cards(nodes), [])

    def test_ignores_short_title(self) -> None:
        nodes = [node("短标题", 13, 1305, 534, 1409)]
        self.assertEqual(m._parse_cards(nodes), [])


class ParseDetailTest(unittest.TestCase):
    def test_counts_and_body(self) -> None:
        nodes = [
            node("作者名", 246, 174, 451, 221),
            node("这是笔记标题一行的文本", 41, 1765, 1039, 1819),
            node("这是正文内容，长度明显比标题更长一些，用于识别正文", 41, 1830, 1039, 1900),
            node("按钮", 20, 2000, 200, 2060, desc="点赞 1.2万"),
            node("按钮", 220, 2000, 400, 2060, desc="收藏 3456"),
            node("按钮", 420, 2000, 600, 2060, desc="评论 78"),
        ]
        detail = m._parse_detail(nodes)
        self.assertEqual(detail["likes"], "1.2万")
        self.assertEqual(detail["saves"], "3456")
        self.assertEqual(detail["comments"], "78")
        self.assertEqual(detail["author"], "作者名")
        self.assertIn("正文内容", detail["body"])
        self.assertEqual(detail["title"], "这是笔记标题一行的文本")


if __name__ == "__main__":
    unittest.main()
