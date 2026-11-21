"""路由基准的夹具与计分单测。"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_bench  # noqa: E402


class FixtureTest(unittest.TestCase):
    def test_fixtures_are_valid(self):
        intents, competitors = run_bench.load_fixtures(
            run_bench.INTENTS_DEFAULT, run_bench.COMPETITORS_DEFAULT
        )
        tools = run_bench.our_tools()
        self.assertEqual(len(intents), 45)
        self.assertEqual(len(competitors), 4)
        self.assertEqual(run_bench.validate(intents, competitors, tools), [])
        covered = [item for item in intents if item.get("expect_tool")]
        self.assertEqual(len(covered), 32)

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


class HistoryTest(unittest.TestCase):
    def _report(self, rate: float, model: str = "qwen-test") -> dict:
        return {
            "generated_at": "2026-11-21T10:00:00",
            "router": "qwen",
            "model": model,
            "catalog_fields": "both",
            "name_style": "current",
            "metrics": {
                "total": 30,
                "coverage_hit_rate": rate,
                "ours_selection_rate": 0.8,
                "wrong_our_tool": 1,
                "false_positive_rate": 0.1,
                "avg_latency_ms": 1200.0,
            },
        }

    def test_archive_appends_one_line_per_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            run_bench.archive(path, self._report(0.5))
            run_bench.archive(path, self._report(0.7))
            records = run_bench.load_history(path)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[-1]["coverage_hit_rate"], 0.7)
            self.assertEqual(records[-1]["model"], "qwen-test")
            self.assertNotIn("results", records[-1])

    def test_load_history_skips_broken_lines_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            path.write_text('{"coverage_hit_rate": 0.4}\nnot-json\n\n', encoding="utf-8")
            self.assertEqual(len(run_bench.load_history(path)), 1)
            self.assertEqual(run_bench.load_history(Path(tmp) / "absent.jsonl"), [])

    def test_trend_prints_recent_records(self):
        records = [
            {"generated_at": "2026-11-20T09:00:00", "model": "m1", "coverage_hit_rate": 0.5},
            {"generated_at": "2026-11-21T09:00:00", "model": "m2", "coverage_hit_rate": 0.6},
        ]
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            run_bench.print_trend(records, limit=1)
        output = buffer.getvalue()
        self.assertIn("2026-11-21T09:00:00", output)
        self.assertIn("m2", output)
        self.assertNotIn("m1", output)

    def test_trend_without_history_is_not_an_error(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            run_bench.print_trend([])
        self.assertIn("暂无历史归档", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
