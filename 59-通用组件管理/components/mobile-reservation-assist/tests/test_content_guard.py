"""内容风控护栏测试：个股/交易动作/收益承诺必须被拦截。"""

from __future__ import annotations

import unittest

import _support  # noqa: F401

import brain
import content_guard
import mra


class ContentGuardScanTest(unittest.TestCase):
    def test_blocks_stock_code(self) -> None:
        findings = content_guard.scan("关注 605287 的走势")
        self.assertFalse(findings["clean"])
        self.assertIn("个股代码", [item["type"] for item in findings["block"]])

    def test_blocks_trade_actions(self) -> None:
        for word in ("建议买入", "可以加仓", "准备抄底", "满仓持有"):
            findings = content_guard.scan(word)
            self.assertFalse(findings["clean"], word)

    def test_blocks_income_promise(self) -> None:
        findings = content_guard.scan("这个策略稳赚，年化15%")
        types = [item["type"] for item in findings["block"]]
        self.assertIn("收益承诺", types)

    def test_allows_neutral_financial_news(self) -> None:
        text = "美联储维持利率不变，市场关注通胀数据与就业变化，机构认为需要更多证据。"
        findings = content_guard.scan(text)
        self.assertTrue(findings["clean"])
        self.assertEqual(findings["block"], [])

    def test_warn_does_not_block(self) -> None:
        findings = content_guard.scan("这条消息很重磅，市场反应剧烈")
        self.assertTrue(findings["clean"])
        self.assertTrue(findings["warn"])

    def test_scan_note_covers_pages(self) -> None:
        findings = content_guard.scan_note(
            {"title": "新闻", "body": "正文", "pages": [{"heading": "买入时机", "points": []}]}
        )
        self.assertFalse(findings["clean"])


class ContentGuardRewriteTest(unittest.TestCase):
    def test_guard_rewrites_blocked_note(self) -> None:
        original_available = brain.available
        original_rewrite = brain.rewrite_compliant
        brain.available = lambda: True
        brain.rewrite_compliant = lambda note, findings=None, timeout=120: {
            "title": "美联储维持利率不变",
            "body": "市场关注通胀与就业数据。",
            "topics": ["宏观"],
            "pages": [],
        }
        try:
            note, report = mra._guard_note({"title": "买入 605287", "body": "稳赚", "topics": []})
        finally:
            brain.available = original_available
            brain.rewrite_compliant = original_rewrite
        self.assertTrue(report["rewritten"])
        self.assertTrue(report["final"]["clean"])
        self.assertEqual(note["title"], "美联储维持利率不变")

    def test_guard_keeps_original_when_rewrite_still_blocked(self) -> None:
        original_available = brain.available
        original_rewrite = brain.rewrite_compliant
        brain.available = lambda: True
        brain.rewrite_compliant = lambda note, findings=None, timeout=120: {
            "title": "建议买入 605287",
            "body": "稳赚",
            "topics": [],
        }
        try:
            note, report = mra._guard_note({"title": "原稿 605287", "body": "原正文", "topics": []})
        finally:
            brain.available = original_available
            brain.rewrite_compliant = original_rewrite
        self.assertFalse(report["final"]["clean"])
        self.assertEqual(note["title"], "原稿 605287")

    def test_post_rejects_blocked_note(self) -> None:
        with self.assertRaises(mra.ContentGuardError):
            mra._post_note({"title": "推荐买入 605287", "body": "稳赚不赔"}, ["album_first"], False)


if __name__ == "__main__":
    unittest.main()
