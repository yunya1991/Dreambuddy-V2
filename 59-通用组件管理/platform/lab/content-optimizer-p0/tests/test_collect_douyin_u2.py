"""抖音只读滚动采集器纯函数单测：不依赖真机。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import collect_douyin_u2 as m  # noqa: E402


def node(
    text: str, x1: int, y1: int, x2: int, y2: int, cls: str = "TextView", desc: str = ""
) -> dict:
    return {"cls": cls, "text": text, "desc": desc, "x1": x1, "y1": y1, "x2": x2, "y2": y2}


class LikeCountTest(unittest.TestCase):
    def test_like_and_date(self) -> None:
        self.assertTrue(m._is_like_count("12.9万"))
        self.assertTrue(m._is_like_count("1647"))
        self.assertFalse(m._is_like_count("09.05"))
        self.assertFalse(m._is_like_count("11-08"))

    def test_like_from_button_desc(self) -> None:
        self.assertEqual(
            m._like_label(node("", 900, 900, 1000, 960, desc="未点赞，喜欢1647，按钮")), "1647"
        )
        self.assertEqual(m._like_label(node("1.2w", 900, 900, 1000, 960)), "1.2w")


class RankBucketTest(unittest.TestCase):
    def test_boundaries(self) -> None:
        self.assertEqual(m._rank_bucket(1), "1-10")
        self.assertEqual(m._rank_bucket(10), "1-10")
        self.assertEqual(m._rank_bucket(11), "11-30")
        self.assertEqual(m._rank_bucket(30), "11-30")
        self.assertEqual(m._rank_bucket(31), "31-50")
        self.assertEqual(m._rank_bucket(50), "31-50")


class ParseCardsTest(unittest.TestCase):
    def test_pairs_title_and_likes_in_visible_order(self) -> None:
        nodes = [
            node("为什么大多数人在股市里赚不到钱", 40, 700, 1040, 820),
            node("财经老王", 40, 840, 300, 890),
            node("12.9万", 900, 850, 1040, 900),
            node("存款利率又降了普通人该怎么办", 40, 1200, 1040, 1320),
            node("理财小助手", 40, 1340, 300, 1390),
            node("1647", 900, 1350, 1040, 1400),
        ]
        cards = m._parse_cards(nodes)
        self.assertEqual(
            [c["title"] for c in cards],
            ["为什么大多数人在股市里赚不到钱", "存款利率又降了普通人该怎么办"],
        )
        self.assertEqual(cards[0]["likes"], "12.9万")
        self.assertEqual(cards[1]["likes"], "1647")
        self.assertEqual(cards[0]["author"], "财经老王")

    def test_skips_placeholder_title_and_date_like(self) -> None:
        nodes = [
            node("未点赞，喜欢1647，按钮", 900, 700, 1040, 760, cls="Button"),
            node("09.05", 900, 780, 1040, 830),
            node("这是一条正常的抖音搜索卡片标题", 40, 700, 1040, 820),
            node("09.05", 900, 840, 1040, 890),
        ]
        cards = m._parse_cards(nodes)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["title"], "这是一条正常的抖音搜索卡片标题")
        self.assertEqual(cards[0]["likes"], "")

    def test_drops_related_search_suggestions(self) -> None:
        nodes = [
            node("相关搜索", 568, 1532, 992, 1584),
            node("今日股票行情", 590, 1640, 824, 1692),
            node("股票行情最新消息今天", 590, 1916, 980, 1968),
        ]
        self.assertEqual(m._parse_cards(nodes), [])

    def test_ignores_top_and_bottom_offrange(self) -> None:
        nodes = [
            node("搜索框上方的无关长文本内容", 40, 100, 1040, 160),
            node("页面底部导航栏里的长文本内容", 40, 2300, 1040, 2360),
        ]
        self.assertEqual(m._parse_cards(nodes), [])

    def test_two_columns_do_not_steal_each_others_likes(self) -> None:
        nodes = [
            node("左列财经视频标题内容足够长", 33, 509, 512, 606),
            node("右列财经视频标题内容足够长", 568, 509, 1047, 606),
            node("23.2万", 415, 645, 512, 687),
            node("5.8万", 964, 645, 1047, 687),
        ]
        cards = m._parse_cards(nodes)
        self.assertEqual(
            [c["title"] for c in cards],
            ["左列财经视频标题内容足够长", "右列财经视频标题内容足够长"],
        )
        self.assertEqual([c["likes"] for c in cards], ["23.2万", "5.8万"])

    def test_button_desc_and_text_counts_as_one_like(self) -> None:
        nodes = [
            node("左列财经视频标题内容足够长", 33, 509, 512, 606),
            node("", 371, 628, 512, 704, cls="LinearLayout", desc="未点赞，喜欢23.2万，按钮"),
            node("23.2万", 415, 645, 512, 687),
        ]
        cards = m._parse_cards(nodes)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["likes"], "23.2万")

    def test_author_skips_date_lines(self) -> None:
        nodes = [
            node("左列财经视频标题内容足够长", 33, 509, 512, 606),
            node("10.29", 110, 628, 172, 669),
            node("直男财经", 110, 700, 230, 741),
            node("23.2万", 415, 645, 512, 687),
        ]
        cards = m._parse_cards(nodes)
        self.assertEqual(cards[0]["author"], "直男财经")


class HasResultsTest(unittest.TestCase):
    def _card(self, title: str) -> list[dict]:
        return [node(title, 33, 900, 512, 1000), node("1234", 415, 950, 512, 990)]

    def test_hashtag_mention_is_not_search_box(self) -> None:
        self.assertFalse(m._has_results(self._card("某条基金视频标题带 #财经 话题"), "财经"))

    def test_search_box_keyword(self) -> None:
        nodes = [node("财经", 100, 150, 900, 220, cls="EditText")] + self._card(
            "某条搜索结果的标题内容足够长"
        )
        self.assertTrue(m._has_results(nodes, "财经"))


class RowTest(unittest.TestCase):
    def test_rank_bucket_and_collector(self) -> None:
        row = m._row(
            "douyin",
            {"title": "股市避坑指南3步方法", "author": "老王", "likes": "1.2万"},
            "财经",
            "2026-11-24T22:30:00+08:00",
            12,
        )
        self.assertEqual(row["rank_bucket"], "11-30")
        self.assertEqual(row["collector"], "u2-douyin")
        self.assertEqual(row["media_type"], "video")
        self.assertEqual(row["likes"], 12000)
        self.assertEqual(row["hashtag_count"], 0)


if __name__ == "__main__":
    unittest.main()
