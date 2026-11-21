"""确定性文本证据测试（离线）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[2]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from optimizer import evidence  # noqa: E402

LEXICON = {
    "company": ["贵州茅台", "宁德时代"],
    "ticker": ["AAPL", "NVDA"],
    "form": ["8-K", "10-Q"],
    "index": ["上证", "创业板"],
}


class EvidenceTest(unittest.TestCase):
    def test_match_entities_dedupes_and_keeps_lexicon_order(self) -> None:
        matched = evidence.match_entities("查贵州茅台和宁德时代，再看 AAPL 的 8-K", LEXICON)
        self.assertEqual(matched, ["贵州茅台", "宁德时代", "AAPL", "8-K"])

    def test_ascii_entity_requires_word_boundary(self) -> None:
        self.assertEqual(evidence.match_entities("ANVDAA 不是代码", LEXICON), [])

    def test_bilingual_counts(self) -> None:
        counts = evidence.bilingual_counts(["a股指数", "market-facts"])
        self.assertEqual(counts["cjk_chars"], 3)
        self.assertGreaterEqual(counts["ascii_words"], 1)

    def test_shared_terms_flags_cross_field_duplicates(self) -> None:
        duplicated = evidence.shared_terms(
            {
                "title": "市场事实日报（A股指数·涨跌幅·分位）",
                "subtitle": "A股指数一页数字事实",
                "keywords": ["a股指数", "分位"],
            }
        )
        terms = [item["term"] for item in duplicated]
        self.assertIn("指数", terms)

    def test_shared_terms_respects_whitelist(self) -> None:
        duplicated = evidence.shared_terms(
            {"title": "行情快照", "subtitle": "行情快照说明"},
            whitelist=["行情", "情快", "快照"],
        )
        self.assertEqual(duplicated, [])

    def test_shared_terms_with_lexicon_uses_whole_words(self) -> None:
        duplicated = evidence.shared_terms(
            {
                "title": "数据服务专业版（按次付费）",
                "subtitle": "按次付费的数据服务：美股披露与链上数据",
            },
            lexicon={"market": ["美股", "付费"], "onchain": ["链上"], "event": ["披露"]},
        )
        terms = [item["term"] for item in duplicated]
        # 整词重复要保留
        self.assertIn("付费", terms)
        # 2 字滑窗产生的跨词碎片必须被排除
        self.assertNotIn("据服", terms)
        self.assertNotIn("次付", terms)

    def test_name_tokens(self) -> None:
        self.assertEqual(evidence.name_tokens("a_share_quote"), ["share", "quote"])


if __name__ == "__main__":
    unittest.main()
