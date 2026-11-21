"""五维评分与 blocker 聚合测试（离线）。"""

from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[2]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from optimizer import (  # noqa: E402
    cli,
    evidence,
    loaders,
    score,  # noqa: E402
)
from optimizer.loaders import Surface  # noqa: E402


def _good_skill() -> Surface:
    return Surface(
        kind="skill_md",
        surface_id="skill:demo:free",
        path="/tmp/demo/SKILL.md",
        family="demo",
        fields={
            "name": "demo",
            "title": "演示技能",
            "subtitle": "查行情与披露",
            "description": "A 股行情快照：查贵州茅台、宁德时代现价；当用户问股价时使用；不预测涨跌",
            "tags": ["a股", "quote", "行情"],
            "examples": ["用「演示」查贵州茅台现价", "用「演示」查宁德时代涨跌"],
            "output_sample": True,
            "error_codes": True,
            "first_run_cmd": True,
            "license": "MIT",
            "version": "1.0.0",
            "not_for": "不预测涨跌",
        },
    )


def _bad_skill() -> Surface:
    return Surface(
        kind="skill_md",
        surface_id="skill:bad:free",
        path="/tmp/bad/SKILL.md",
        family="bad",
        fields={
            "name": "bad",
            "title": "",
            "subtitle": "",
            "description": "数据服务",
            "tags": [],
            "examples": [],
            "output_sample": False,
            "error_codes": False,
            "first_run_cmd": False,
            "license": "",
            "version": "1",
            "not_for": "",
        },
    )


class ScoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.card = loaders.load_scorecard()

    def test_good_skill_has_no_blocker(self) -> None:
        result = score.score_surface(_good_skill(), self.card)
        self.assertEqual(result["blocker_count"], 0, result["blockers"])
        self.assertGreaterEqual(result["total"], 75)

    def test_bad_skill_hits_entity_blocker(self) -> None:
        result = score.score_surface(_bad_skill(), self.card)
        rule_ids = [item["rule_id"] for item in result["blockers"]]
        self.assertIn("RET001", rule_ids)
        self.assertEqual(result["grade"], "D")

    def test_score_is_deterministic(self) -> None:
        first = json.dumps(score.score_surface(_good_skill(), self.card), sort_keys=True)
        second = json.dumps(score.score_surface(_good_skill(), self.card), sort_keys=True)
        self.assertEqual(first, second)

    def test_score_all_summary_counts(self) -> None:
        payload = score.score_all([_good_skill(), _bad_skill()], self.card, "legacy")
        self.assertEqual(payload["summary"]["count"], 2)
        self.assertGreaterEqual(payload["summary"]["blockers"], 1)
        self.assertTrue(payload["summary"]["below_total_warn"])

    def test_entity_lexicon_covers_market_terms(self) -> None:
        matched = evidence.match_entities(
            "查美股披露与 A股行情，再看财报分位", self.card["entity_lexicon"]
        )
        self.assertIn("美股", matched)
        self.assertIn("A股", matched)
        self.assertIn("财报", matched)
        self.assertIn("分位", matched)


class ScopeTest(unittest.TestCase):
    """CLI 取数口径：--product 优先，--all 默认与发布门禁同口径。"""

    def setUp(self) -> None:
        self.card = loaders.load_scorecard()

    def test_product_flag_wins_over_same_name_component(self) -> None:
        args = argparse.Namespace(
            all=False, product="market-data", component="", include_draft=False
        )
        surfaces = cli._collect(args)
        self.assertEqual({surface.kind for surface in surfaces}, {"product_page", "packaging"})

    def test_all_skips_draft_components_by_default(self) -> None:
        args = argparse.Namespace(all=True, product="", component="", include_draft=False)
        ids = [surface.surface_id for surface in cli._collect(args)]
        drafts = [name for name in loaders.component_names() if loaders.lifecycle(name) != "active"]
        for draft in drafts:
            self.assertFalse(
                any(draft in surface_id for surface_id in ids),
                "draft 组件 {} 不应进入默认评分".format(draft),
            )

    def test_product_page_is_not_graded_by_skill_intent_rule(self) -> None:
        page = next(
            surface
            for surface in loaders.product_surfaces("event-context")
            if surface.kind == "product_page"
        )
        result = score.score_surface(page, self.card)
        rule_ids = [item["rule_id"] for item in result["findings"]]
        self.assertNotIn("RET002", rule_ids)


if __name__ == "__main__":
    unittest.main()
