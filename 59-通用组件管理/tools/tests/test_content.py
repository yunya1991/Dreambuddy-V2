"""P1 内容闭环测试：研究文档、博文、社媒物料、效果回流（全部离线）。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import content  # noqa: E402


def sample_facts() -> dict:
    return {
        "skill": "market-facts-daily",
        "version": "1.0.3",
        "generated_at": "2026-11-20T19:13:15",
        "data_date": "2026-11-20",
        "window": 30,
        "rows": [
            {
                "symbol": "sh000001",
                "name": "上证综指",
                "source": "腾讯行情(前复权)",
                "date": "2026-11-20",
                "n": 320,
                "close": 3533.79,
                "d1": -0.01225116138662019,
                "d5": -0.02766932188699489,
                "d20": -0.04245789165636993,
                "pctile": 0.03333333333333333,
                "pctile_n": 30,
                "vol": 0.14520165130037363,
                "mdd": -0.07026567671526973,
                "mdd_n": 30,
                "ma60": -0.06698741137030795,
            }
        ],
        "missing": [],
        "method_ids": ["M01", "M02", "M03", "M04", "M05"],
        "sources": [
            {
                "name": "腾讯行情(前复权)",
                "url": "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            }
        ],
    }


class ContentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.facts_path = self.root / "facts.json"
        self.facts_path.write_text(json.dumps(sample_facts(), ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_render_report_and_claim_map(self) -> None:
        out = self.root / "report.md"
        result = content.render_report(self.facts_path, out)
        self.assertTrue(out.exists())
        claims = json.loads(Path(result["claim_map"]).read_text(encoding="utf-8"))
        self.assertEqual(claims["schema"], "report.claim_map.v1")
        facts = claims["claims"][0]["facts"]
        self.assertTrue(any(item["method_id"] == "M03" for item in facts))
        self.assertIn("-1.23%", out.read_text(encoding="utf-8"))

    def test_unmapped_percentage_is_blocked(self) -> None:
        claims = content.build_claims(content.load_facts(self.facts_path))
        with self.assertRaises(content.ContentError):
            content.validate_report("随便写一个 +9.99%", claims)

    def test_blog_draft_frontmatter(self) -> None:
        report = self.root / "report.md"
        content.render_report(self.facts_path, report)
        out = self.root / "post.md"
        result = content.blog_draft(report, out)
        text = out.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\ntitle:"))
        self.assertIn("date: 2026-11-20", text)
        self.assertIn("tags:", text)
        self.assertFalse(result["published"])

    def test_social_pack_structure(self) -> None:
        report = self.root / "report.md"
        content.render_report(self.facts_path, report)
        out = self.root / "pack.json"
        result = content.social_pack(report, out, facts_path=str(self.facts_path))
        pack = json.loads(Path(result["pack"]).read_text(encoding="utf-8"))
        self.assertEqual(pack["schema"], "content.social_pack.v1")
        self.assertEqual(len(pack["platforms"]["xiaohongshu"]["titles"]), 3)
        self.assertTrue(pack["compliance"]["passed"])

    def test_social_pack_blocks_forbidden_words(self) -> None:
        report = self.root / "bad.md"
        report.write_text("# 标题\n\n目标价 10 元。\n", encoding="utf-8")
        with self.assertRaises(content.ContentError):
            content.social_pack(report, self.root / "pack.json")

    def test_metrics_record_and_summary(self) -> None:
        path = self.root / "metrics.csv"
        content.metrics_record(
            {
                "content_id": "c1",
                "platform": "xiaohongshu",
                "impressions": "100",
                "likes": "8",
            },
            str(path),
        )
        summary = content.metrics_summary(str(path))
        self.assertEqual(summary["rows"], 1)
        self.assertEqual(summary["platforms"]["xiaohongshu"]["likes"], 8)


if __name__ == "__main__":
    unittest.main()
