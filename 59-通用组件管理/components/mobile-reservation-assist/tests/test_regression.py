"""P2 回归任务集：把「基线 + 录制」固化为可批量执行的兼容性回归用例。"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import _support
import explore
import regression
from test_explore import fixture_snapshots


def seed_exploration(db, app="bilibili", goal="买票", snapshots=None):
    exp_id = db.create_exploration(app, goal, "dev-1")
    for item in snapshots or fixture_snapshots():
        db.add_snapshot(
            exp_id,
            package=item["package"],
            activity=item["activity"],
            page_text=item["page_text"],
            screenshot=item["screenshot"],
            nodes=item["nodes"],
        )
    db.stop_exploration(exp_id)
    return exp_id


def drifted_snapshots():
    snaps = fixture_snapshots()
    snaps[3] = dict(
        snaps[3],
        nodes=[
            {"cls": "TextView", "text": "看台 780元", "desc": "", "clickable": True, "bounds": [0, 0, 9, 9]},
            {"cls": "TextView", "text": "内场 1280元", "desc": "", "clickable": True, "bounds": [0, 0, 9, 9]},
        ],
        page_text="看台 780元 内场 1280元",
    )
    return snaps


def seed_baseline(db, exp_id, name="bilibili"):
    exploration = db.get_exploration(exp_id)
    baseline = explore.build_baseline(exploration, db.list_snapshots(exp_id), name)
    db.save_baseline(name, exploration["app"], exp_id, baseline["steps"], baseline["assertions"])


class CaseStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_add_and_upsert(self) -> None:
        self.db.add_regression_case("c1", "bilibili", 1, True, "smoke")
        self.db.add_regression_case("c1", "bilibili", 2, False, "smoke,nightly")
        cases = self.db.list_regression_cases()
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["exploration_id"], 2)
        self.assertFalse(cases[0]["expect_compatible"])

    def test_filter_by_tag(self) -> None:
        self.db.add_regression_case("c1", "b", 1, True, "smoke")
        self.db.add_regression_case("c2", "b", 2, True, "nightly")
        self.assertEqual(len(self.db.list_regression_cases(tag="smoke")), 1)

    def test_run_history(self) -> None:
        run_id = self.db.save_regression_run({"schema": "regression.v1", "total": 1, "failed": 0})
        self.assertGreater(run_id, 0)
        runs = self.db.list_regression_runs()
        self.assertEqual(runs[0]["_id"], run_id)


class RunSuiteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _support.temp_store()
        self.original = seed_exploration(self.db)
        self.drifted = seed_exploration(self.db, snapshots=drifted_snapshots())
        seed_baseline(self.db, self.original)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_compatible_case_passes(self) -> None:
        self.db.add_regression_case("c1", "bilibili", self.original, True, "smoke")
        report = regression.run_suite(self.db)
        self.assertEqual(report["schema"], "regression.v1")
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["cases"][0]["verdict"], "pass")
        self.assertGreater(report["run_id"], 0)

    def test_expected_incompatible_passes(self) -> None:
        self.db.add_regression_case("c1", "bilibili", self.drifted, False, "drift")
        report = regression.run_suite(self.db)
        self.assertEqual(report["passed"], 1)
        self.assertFalse(report["cases"][0]["compatible"])

    def test_unexpected_drift_fails(self) -> None:
        self.db.add_regression_case("c1", "bilibili", self.drifted, True, "smoke")
        report = regression.run_suite(self.db)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["cases"][0]["verdict"], "fail")
        self.assertTrue(report["cases"][0]["step_misses"])

    def test_tag_filter(self) -> None:
        self.db.add_regression_case("c1", "bilibili", self.original, True, "smoke")
        self.db.add_regression_case("c2", "bilibili", self.drifted, False, "nightly")
        report = regression.run_suite(self.db, tag="nightly")
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["cases"][0]["case_id"], "c2")

    def test_missing_baseline_is_error(self) -> None:
        self.db.add_regression_case("c1", "nope", self.original, True, "")
        report = regression.run_suite(self.db)
        self.assertEqual(report["errors"], 1)
        self.assertFalse(report["ok"])

    def test_empty_suite_not_ok(self) -> None:
        report = regression.run_suite(self.db)
        self.assertEqual(report["total"], 0)
        self.assertFalse(report["ok"])


class RegressionCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MRA_STATE_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_add_list_run_flow(self) -> None:
        import mra

        exp_id = mra._explore_start({"app": "bilibili", "goal": "买票"})["exploration"]["_id"]
        for item in fixture_snapshots():
            mra._explore_snapshot(exp_id, item)
        mra._explore_stop({"exploration_id": exp_id})
        mra._explore_baseline({"exploration_id": exp_id, "name": "bilibili"})

        added = mra._regression_add(
            {"case_id": "c1", "baseline": "bilibili", "exploration_id": exp_id, "expect": "compatible", "tags": "smoke"}
        )
        self.assertEqual(added["case_id"], "c1")
        self.assertEqual(len(mra._regression_list({"tag": ""})["cases"]), 1)
        report = mra._regression_run({"tag": "smoke"})
        self.assertTrue(report["ok"])
        self.assertEqual(report["passed"], 1)

    def test_add_requires_fields(self) -> None:
        import mra

        with self.assertRaises(ValueError):
            mra._regression_add({"case_id": "", "baseline": "b", "exploration_id": 1})


if __name__ == "__main__":
    unittest.main()
