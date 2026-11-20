"""路由基准的夹具与计分单测。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_bench  # noqa: E402


class FixtureTest(unittest.TestCase):
    def test_fixtures_are_valid(self):
        intents, competitors = run_bench.load_fixtures(
            run_bench.INTENTS_DEFAULT, run_bench.COMPETITORS_DEFAULT
        )
        tools = run_bench.our_tools()
        self.assertEqual(len(intents), 30)
        self.assertEqual(len(competitors), 4)
        self.assertEqual(run_bench.validate(intents, competitors, tools), [])
        covered = [item for item in intents if item.get("expect_tool")]
        self.assertEqual(len(covered), 22)

    def test_every_intent_has_unique_id(self):
        intents, _ = run_bench.load_fixtures(
            run_bench.INTENTS_DEFAULT, run_bench.COMPETITORS_DEFAULT
        )
        ids = [item["id"] for item in intents]
        self.assertEqual(len(ids), len(set(ids)))


class ScoreTest(unittest.TestCase):
    def test_score_counts_hit_wrong_and_false_positive(self):
        results = [
            {
                "expect_tool": "t1",
                "choice": "t1",
                "category": "c",
                "latency_ms": 10,
                "prompt_chars": 100,
            },
            {
                "expect_tool": "t1",
                "choice": "t2",
                "category": "c",
                "latency_ms": 20,
                "prompt_chars": 100,
            },
            {
                "expect_tool": None,
                "choice": "t1",
                "category": "x",
                "latency_ms": 30,
                "prompt_chars": 100,
            },
            {
                "expect_tool": None,
                "choice": "none",
                "category": "x",
                "latency_ms": 40,
                "prompt_chars": 100,
            },
        ]
        metrics = run_bench.score(results, {"t1", "t2"})
        self.assertEqual(metrics["covered"], 2)
        self.assertEqual(metrics["coverage_hits"], 1)
        self.assertEqual(metrics["coverage_hit_rate"], 0.5)
        self.assertEqual(metrics["wrong_our_tool"], 1)
        self.assertEqual(metrics["false_positive"], 1)
        self.assertEqual(metrics["false_positive_rate"], 0.5)
        self.assertEqual(metrics["ours_selection_rate"], 0.75)

    def test_extract_choice_handles_json_fence_and_none(self):
        self.assertEqual(run_bench.extract_choice('{"choice": "t1", "reason": "x"}'), "t1")
        self.assertEqual(run_bench.extract_choice('```json\n{"choice":"none"}\n```'), "none")
        self.assertEqual(run_bench.extract_choice("choice: NONE"), "none")
        self.assertEqual(run_bench.extract_choice("无法判断"), "none")

    def test_legacy_name_mode_maps_both_directions(self):
        tools = [{"name": "a_share_quote", "description": "x", "owner": "dreambuddy"}]
        catalog = run_bench.build_catalog(tools, [], fields="name", name_style="legacy")
        self.assertEqual(catalog[0]["name"], "market_data_quotes")
        self.assertEqual(
            run_bench.normalize_choice("market_data_quotes", "legacy"), "a_share_quote"
        )

    def test_r2_name_mode_maps_latest_specific_names(self):
        tools = [
            {"name": "sec_filing_reader", "description": "x", "owner": "dreambuddy"},
            {"name": "ticket_reservation", "description": "x", "owner": "dreambuddy"},
        ]
        catalog = run_bench.build_catalog(tools, [], fields="name", name_style="r2")
        self.assertEqual(
            [item["name"] for item in catalog],
            ["us_sec_filings", "reservation_plan"],
        )
        self.assertEqual(run_bench.normalize_choice("us_sec_filings", "r2"), "sec_filing_reader")

    def test_name_only_catalog_has_no_descriptions(self):
        catalog = [
            {"name": "a", "description": "secret", "owner": "dreambuddy"},
            {"name": "b", "description": "hidden", "owner": "competitor"},
        ]
        text = run_bench.format_catalog(catalog, "name")
        self.assertEqual(text, "- a\n- b")

    def test_guidance_catalog_shows_scope_but_not_description(self):
        catalog = [
            {
                "name": "official_fed_sec_event_search",
                "description": "secret",
                "when_to_use": "官方声明",
                "not_for": "宏观序列",
                "owner": "dreambuddy",
            }
        ]
        text = run_bench.format_catalog(catalog, "guidance")
        self.assertIn("适用：官方声明", text)
        self.assertIn("不适用：宏观序列", text)
        self.assertNotIn("secret", text)


if __name__ == "__main__":
    unittest.main()
