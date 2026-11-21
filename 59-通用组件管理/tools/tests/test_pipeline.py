"""P0-2 ~ P0-5 内核测试：plan / workflow / jobs / release（全部离线）。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import jobs  # noqa: E402
import plan  # noqa: E402
import release_ledger  # noqa: E402
import workflow  # noqa: E402


class PipelineTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old = {
            "DREAMBUDDY_STATE_DIR": os.environ.get("DREAMBUDDY_STATE_DIR"),
            "DREAMBUDDY_JOBS_DB": os.environ.get("DREAMBUDDY_JOBS_DB"),
            "DREAMBUDDY_RELEASES": os.environ.get("DREAMBUDDY_RELEASES"),
        }
        os.environ["DREAMBUDDY_STATE_DIR"] = str(self.root / "state")
        os.environ["DREAMBUDDY_JOBS_DB"] = str(self.root / "jobs.db")
        os.environ["DREAMBUDDY_RELEASES"] = str(self.root / "releases.jsonl")

    def tearDown(self) -> None:
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()


class PlanTest(PipelineTestBase):
    def test_requires_principal_and_validates_ttl_hash(self) -> None:
        with self.assertRaises(ValueError):
            plan.create("mobile-reservation-assist", "dispatch", ["x"])
        item = plan.create(
            "mobile-reservation-assist", "dispatch", ["x"], principal="tester", ttl=60
        )
        self.assertEqual(
            item["args_hash"], plan.args_hash("mobile-reservation-assist", "dispatch", ["x"])
        )
        with self.assertRaises(ValueError):
            plan.approve(item["plan_id"], principal="someone-else")
        approved = plan.approve(item["plan_id"], principal="tester")
        self.assertEqual(approved["plan_id"], item["plan_id"])

        expired = plan.create(
            "mobile-reservation-assist", "dispatch", ["y"], principal="tester", ttl=-1
        )
        with self.assertRaises(ValueError):
            plan.approve(expired["plan_id"], principal="tester")

    def test_hash_changes_when_args_change(self) -> None:
        first = plan.args_hash("c", "a", ["--x", "1"])
        second = plan.args_hash("c", "a", ["--x", "2"])
        self.assertNotEqual(first, second)


class WorkflowTest(PipelineTestBase):
    def setUp(self) -> None:
        super().setUp()
        self._old_wf = workflow.WORKFLOWS_DIR

    def tearDown(self) -> None:
        workflow.WORKFLOWS_DIR = self._old_wf
        super().tearDown()

    def _workflow_dir(self) -> Path:
        wf_dir = self.root / "workflows"
        wf_dir.mkdir(exist_ok=True)
        workflow.WORKFLOWS_DIR = wf_dir
        return wf_dir

    def test_dry_run_plans_component_steps_and_marks_builtins(self) -> None:
        code = workflow.run("daily-market-brief", dry_run=True)
        self.assertEqual(code, 0)
        runs = list((self.root / "state" / "workflows").glob("*/run.json"))
        self.assertEqual(len(runs), 1)
        state = json.loads(runs[0].read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["steps"]["facts"]["status"], "planned")
        self.assertEqual(state["steps"]["report"]["status"], "planned")
        self.assertEqual(state["steps"]["report"]["command"], "builtin:research.render")
        self.assertFalse((self.root / "state" / "workflows" / "artifacts").exists())

    def test_builtin_research_step_executes(self) -> None:
        wf_dir = self._workflow_dir()
        facts_path = self.root / "facts.json"
        facts_path.write_text(
            json.dumps(
                {
                    "data_date": "2026-11-20",
                    "window": 30,
                    "generated_at": "2026-11-20T19:13:15",
                    "rows": [
                        {
                            "symbol": "sh000001",
                            "name": "上证综指",
                            "n": 320,
                            "close": 3533.79,
                            "d1": -0.0122,
                            "d5": -0.0276,
                            "d20": -0.0424,
                            "pctile": 0.0333,
                            "vol": 0.1452,
                            "mdd": -0.0702,
                            "ma60": -0.0669,
                        }
                    ],
                    "missing": [],
                    "sources": [{"name": "fixture"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (wf_dir / "builtin-content.yaml").write_text(
            "id: builtin-content\nversion: 1\nsteps:\n"
            "  - id: report\n    use: research.render\n"
            "    params: {facts: '%s'}\n    out: report.md\n" % facts_path,
            encoding="utf-8",
        )
        self.assertEqual(workflow.run("builtin-content"), 0)
        runs = sorted((self.root / "state" / "workflows").glob("*/run.json"))
        state = json.loads(runs[-1].read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["steps"]["report"]["status"], "done")
        self.assertTrue(Path(state["steps"]["report"]["out"]).exists())

    def test_human_gate_blocks_until_approved(self) -> None:
        wf_dir = self._workflow_dir()
        (wf_dir / "gated.yaml").write_text(
            "id: gated\nversion: 1\nsteps:\n"
            "  - id: gated\n    use: research.render\n    human_gate: A\n",
            encoding="utf-8",
        )
        code = workflow.run("gated")
        self.assertEqual(code, 0)
        runs = sorted((self.root / "state" / "workflows").glob("*/run.json"))
        state = json.loads(runs[-1].read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "awaiting_approval")
        self.assertEqual(state["steps"]["gated"]["status"], "awaiting_approval")


class JobsTest(PipelineTestBase):
    def _workflow(self) -> None:
        wf_dir = self.root / "workflows"
        wf_dir.mkdir()
        (wf_dir / "builtin.yaml").write_text(
            "id: builtin\nversion: 1\nsteps:\n  - id: only\n    use: ops.metrics_record\n",
            encoding="utf-8",
        )
        self._old_wf = workflow.WORKFLOWS_DIR
        workflow.WORKFLOWS_DIR = wf_dir

    def tearDown(self) -> None:
        if hasattr(self, "_old_wf"):
            workflow.WORKFLOWS_DIR = self._old_wf
        super().tearDown()

    def test_run_due_is_idempotent_and_advances(self) -> None:
        self._workflow()
        created = jobs.add("daily", "builtin", "0 8 * * *")
        scheduled = datetime.fromisoformat(created["next_run_at"])
        results = jobs.run_due(now=scheduled)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "done")
        again = jobs.run_due(now=scheduled)
        self.assertEqual(again, [])
        row = jobs.list_jobs()[0]
        self.assertGreater(datetime.fromisoformat(row["next_run_at"]), scheduled)

    def test_pause_and_resume(self) -> None:
        self._workflow()
        jobs.add("daily", "builtin", "0 8 * * *")
        self.assertEqual(jobs.set_enabled("daily", False), 0)
        self.assertEqual(jobs.run_due(now=datetime.now(timezone.utc) + timedelta(days=2)), [])
        self.assertEqual(jobs.set_enabled("daily", True), 0)

    def test_cron_next_run(self) -> None:
        cron = jobs.Cron("30 8 * * 1-5")
        start = datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)  # 周六
        self.assertEqual(cron.next_run(start), datetime(2026, 11, 23, 8, 30, tzinfo=timezone.utc))


class ReleaseTest(PipelineTestBase):
    def test_record_and_rollback(self) -> None:
        release_ledger.record("market-data-pro", "1.0.0", "skillhub", "published")
        release_ledger.record("market-data-pro", "1.1.0", "skillhub", "published")
        result = release_ledger.rollback("market-data-pro")
        self.assertEqual(result["target"]["version"], "1.0.0")
        self.assertIn("rollback_requested", [e["status"] for e in release_ledger.entries()])

    def test_rejects_unknown_status(self) -> None:
        with self.assertRaises(ValueError):
            release_ledger.record("x", "1.0.0", "skillhub", "whatever")


if __name__ == "__main__":
    unittest.main()
