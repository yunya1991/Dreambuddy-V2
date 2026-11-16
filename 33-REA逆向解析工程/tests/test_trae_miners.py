"""Trae miners 的最小测试（本地只读）。"""

from __future__ import annotations

import unittest
from pathlib import Path

from trae.bundle_miner import run_bundle_miner
from trae.gap_mapper import build as build_gaps
from trae.gap_mapper import render_markdown as render_gap_markdown
from trae.interaction_miner import ACTION_RULES, _classify, run_interaction_miner
from trae.manifest_miner import _parse_frontmatter, run_manifest_miner
from trae.run_pilot import build_mechanism_cards


class TestClassify(unittest.TestCase):
    def test_edit(self):
        self.assertEqual(_classify("修改 polling_trader.py", ACTION_RULES), "edit_write")

    def test_verify(self):
        self.assertEqual(_classify("运行回归测试并验收", ACTION_RULES), "test_verify")

    def test_other(self):
        self.assertEqual(_classify("整理一下", ACTION_RULES), "other")


class TestFrontmatter(unittest.TestCase):
    def test_parse(self):
        p = Path("/tmp/_trae_skill_test.md")
        p.write_text("---\nname: demo\ndescription: hello\n---\nbody\n", encoding="utf-8")
        meta = _parse_frontmatter(p)
        self.assertEqual(meta.get("name"), "demo")
        self.assertEqual(meta.get("description"), "hello")


class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = run_manifest_miner()
        cls.bundle = run_bundle_miner()
        cls.interaction = run_interaction_miner(limit_sessions=2)

    def test_manifest(self):
        self.assertIn("trae", self.manifest["agent_summary"])
        self.assertGreater(self.manifest["mcp_surface"]["sessions"], 0)
        self.assertGreater(len(self.manifest["user_skills"]), 0)

    def test_interaction(self):
        self.assertGreater(self.interaction["metrics"]["record_count"], 0)
        self.assertTrue(self.interaction["cases"])
        self.assertIn("status", self.interaction["execution"])

    def test_bundle(self):
        self.assertTrue(self.bundle["files"])

    def test_cards(self):
        md = build_mechanism_cards(self.manifest, self.bundle, self.interaction)
        for marker in ("M1", "M2", "M3", "M4", "M5"):
            self.assertIn(marker, md)

    def test_gap_mapping(self):
        result = build_gaps(self.manifest, self.interaction)
        self.assertEqual(len(result["candidates"]), 5)
        ids = {c["gap_id"] for c in result["candidates"]}
        self.assertEqual(ids, {"GAP-T1", "GAP-T2", "GAP-T3", "GAP-T4", "GAP-T5"})
        for c in result["candidates"]:
            self.assertTrue(c["contract_ref"])
            self.assertTrue(c["proposed_check"])
            self.assertTrue(c["evidence_refs"])
        md = render_gap_markdown(result)
        self.assertIn("GAP-T3", md)
        self.assertIn("§1 机制 × 现有 GAP 映射", md)


if __name__ == "__main__":
    unittest.main()
