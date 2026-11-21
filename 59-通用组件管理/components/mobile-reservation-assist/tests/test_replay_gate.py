"""P1 回放兼容门禁：把录制结果固化为基线，平台改版后逐帧比对是否失效。"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import _support
import explore
from test_explore import fixture_snapshots


class BaselineStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_save_get_list_upsert(self) -> None:
        self.db.save_baseline("bilibili", "bilibili", 1, [{"action": "open_app"}], [{"signature": "a"}])
        baseline = self.db.get_baseline("bilibili")
        self.assertEqual(baseline["name"], "bilibili")
        self.assertEqual(len(self.db.list_baselines()), 1)
        self.db.save_baseline("bilibili", "bilibili", 2, [], [{"signature": "b"}])
        updated = self.db.get_baseline("bilibili")
        self.assertEqual(updated["exploration_id"], 2)
        self.assertEqual(len(self.db.list_baselines()), 1)

    def test_unknown_baseline(self) -> None:
        self.assertIsNone(self.db.get_baseline("nope"))


class BuildBaselineTest(unittest.TestCase):
    def test_baseline_from_exploration(self) -> None:
        baseline = explore.build_baseline(
            {"_id": 3, "app": "bilibili", "goal": "买票"}, fixture_snapshots(), "bilibili"
        )
        self.assertEqual(baseline["schema"], "explore.baseline.v1")
        self.assertEqual(baseline["exploration_id"], 3)
        self.assertTrue(baseline["assertions"])
        self.assertTrue(baseline["steps"])


class CompatibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = explore.build_baseline(
            {"_id": 3, "app": "bilibili", "goal": "买票"}, fixture_snapshots(), "bilibili"
        )

    def test_identical_replay_is_compatible(self) -> None:
        result = explore.check_compatibility(self.baseline, fixture_snapshots())
        self.assertTrue(result["compatible"])
        self.assertEqual(result["coverage"], 1.0)
        self.assertEqual(result["step_misses"], [])
        self.assertEqual(result["schema"], "explore.check.v1")

    def test_changed_tier_breaks_gate(self) -> None:
        changed = fixture_snapshots()
        changed[3] = dict(
            changed[3],
            nodes=[
                {"cls": "TextView", "text": "看台 780元", "desc": "", "clickable": True, "bounds": [0, 0, 9, 9]},
                {"cls": "TextView", "text": "内场 1280元", "desc": "", "clickable": True, "bounds": [0, 0, 9, 9]},
            ],
            page_text="看台 780元 内场 1280元",
        )
        result = explore.check_compatibility(self.baseline, changed)
        self.assertFalse(result["compatible"])
        actions = [miss["action"] for miss in result["step_misses"]]
        self.assertIn("select_tier", actions)
        self.assertLess(result["coverage"], 1.0)

    def test_threshold_allows_partial_match(self) -> None:
        baseline = {
            "schema": "explore.baseline.v1",
            "name": "x",
            "app": "x",
            "exploration_id": 1,
            "steps": [],
            "assertions": [
                {"seq": 1, "signature": "s1", "expect": ["甲", "乙"]},
                {"seq": 2, "signature": "s2", "expect": ["丙", "丁"]},
            ],
        }
        snapshots = [
            {"seq": 1, "package": "p", "activity": "a", "nodes": [], "page_text": "甲 乙"},
            {"seq": 2, "package": "p", "activity": "b", "nodes": [], "page_text": "完全不同的页面"},
        ]
        strict = explore.check_compatibility(baseline, snapshots)
        loose = explore.check_compatibility(baseline, snapshots, threshold=0.4)
        self.assertFalse(strict["compatible"])
        self.assertTrue(loose["compatible"])
        self.assertAlmostEqual(loose["coverage"], 0.5, places=2)

    def test_empty_replay_incompatible(self) -> None:
        result = explore.check_compatibility(self.baseline, [])
        self.assertFalse(result["compatible"])
        self.assertEqual(result["coverage"], 0.0)


class GateCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MRA_STATE_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def _seed(self) -> int:
        import mra

        exp_id = mra._explore_start({"app": "bilibili", "goal": "买票"})["exploration"]["_id"]
        for item in fixture_snapshots():
            mra._explore_snapshot(exp_id, item)
        mra._explore_stop({"exploration_id": exp_id})
        return exp_id

    def test_baseline_then_check(self) -> None:
        import mra

        exp_id = self._seed()
        saved = mra._explore_baseline({"exploration_id": exp_id, "name": "bilibili"})
        self.assertEqual(saved["name"], "bilibili")
        checked = mra._explore_check({"name": "bilibili", "exploration_id": exp_id})
        self.assertTrue(checked["compatible"])
        self.assertEqual(checked["coverage"], 1.0)

    def test_check_unknown_baseline(self) -> None:
        import mra

        exp_id = self._seed()
        with self.assertRaises(ValueError):
            mra._explore_check({"name": "nope", "exploration_id": exp_id})

    def test_baseline_requires_snapshots(self) -> None:
        import mra

        exp_id = mra._explore_start({"app": "bilibili", "goal": "买票"})["exploration"]["_id"]
        with self.assertRaises(ValueError):
            mra._explore_baseline({"exploration_id": exp_id, "name": "bilibili"})


if __name__ == "__main__":
    unittest.main()
