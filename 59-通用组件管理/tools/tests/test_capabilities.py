"""能力注册表：派生来源、去重、计划翻译的回归测试。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import capabilities  # noqa: E402


class RegistryBuildTest(unittest.TestCase):
    def setUp(self):
        self.caps = capabilities.build(refresh=True)
        self.by_id = {cap["id"]: cap for cap in self.caps}

    def test_ids_are_unique(self):
        self.assertEqual(len(self.by_id), len(self.caps))

    def test_component_actions_are_registered(self):
        for cid in (
            "cogsteward.index",
            "cogsteward.scan",
            "cogsteward.map",
            "cogsteward.pack",
            "market-data.quotes",
        ):
            self.assertIn(cid, self.by_id)
        self.assertEqual(self.by_id["cogsteward.scan"]["safety"], "write")
        self.assertEqual(self.by_id["cogsteward.index"]["safety"], "read")

    def test_data_bridge_is_read_only(self):
        data_caps = [cap for cap in self.caps if cap["kind"] == "data"]
        self.assertTrue(data_caps)
        self.assertTrue(all(cap["safety"] == "read" for cap in data_caps))
        self.assertNotIn("data.data_store_write", self.by_id)

    def test_mobile_read_only_and_alias(self):
        mobile = {cap["command"]: cap for cap in self.caps if cap["kind"] == "mobile"}
        self.assertIn("jobs", mobile)
        self.assertNotIn("dispatch", mobile)
        self.assertTrue(all(cap["safety"] == "read" for cap in mobile.values()))
        self.assertEqual(
            mobile["jobs"]["alias_of"],
            "mobile-reservation-assist.jobs",
        )

    def test_effective_safety_escalates_by_argv(self):
        cap = self.by_id["mobile-reservation-assist.ask"]
        self.assertEqual(capabilities.effective_safety(cap, []), "read")
        self.assertEqual(capabilities.effective_safety(cap, ["--execute"]), "write")
        patrol = self.by_id["mobile-reservation-assist.patrol"]
        self.assertEqual(capabilities.effective_safety(patrol, ["--auto-fix"]), "write")

    def test_workflow_and_schedule_registered(self):
        self.assertIn("workflow.daily-market-brief", self.by_id)
        self.assertIn("schedule.list", self.by_id)

    def test_check_passes(self):
        result = capabilities.check()
        self.assertTrue(result["ok"], result["issues"])
        self.assertEqual(result["total"], len(self.caps))

    def test_sync_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "capabilities.json"
            data = capabilities.sync(target)
            self.assertEqual(data["schema"], capabilities.SCHEMA)
            self.assertTrue(capabilities.verify(target)["ok"])
            broken = json.loads(target.read_text(encoding="utf-8"))
            broken["capabilities"] = broken["capabilities"][:-1]
            target.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
            self.assertFalse(capabilities.verify(target)["ok"])

    def test_verify_skips_missing_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = capabilities.verify(Path(tmp) / "absent.json")
            self.assertTrue(result["ok"])
            self.assertTrue(result["skipped"])


class PlanForTest(unittest.TestCase):
    def test_run_capability_to_plan(self):
        plan = capabilities.plan_for("cogsteward.index", ["--json"])
        self.assertEqual(plan["kind"], "run")
        self.assertEqual((plan["component"], plan["action"]), ("cogsteward", "index"))
        self.assertEqual(plan["args"], ["--json"])

    def test_mobile_capability_to_plan(self):
        plan = capabilities.plan_for("mobile.jobs", ["--state", "pending"])
        self.assertEqual(plan["kind"], "mobile")
        self.assertEqual(plan["command"], "jobs")
        self.assertEqual(plan["args"], ["--state", "pending"])

    def test_data_capability_to_plan(self):
        plan = capabilities.plan_for("data.data_store_read", {"table": "mm_metrics"})
        self.assertEqual(plan["kind"], "data")
        self.assertEqual(plan["tool"], "data_store_read")
        self.assertEqual(plan["args"], {"table": "mm_metrics"})

    def test_workflow_and_schedule_plans(self):
        self.assertEqual(capabilities.plan_for("workflow.daily-market-brief")["kind"], "workflow")
        self.assertEqual(capabilities.plan_for("schedule.list")["kind"], "schedule")

    def test_unknown_capability_raises(self):
        with self.assertRaises(ValueError):
            capabilities.plan_for("nope.nothing")


class LegacyCatalogTest(unittest.TestCase):
    def test_legacy_shape(self):
        catalog = capabilities.legacy_catalog()
        self.assertEqual(
            set(catalog),
            {
                "component_actions",
                "data_read",
                "trading_read",
                "mobile_read",
                "workflows",
                "schedule_read",
            },
        )
        self.assertTrue(any(item["name"] == "get_signal_state" for item in catalog["trading_read"]))
        self.assertIn("jobs", catalog["mobile_read"])
        self.assertNotIn("dispatch", catalog["mobile_read"])
        self.assertIn("daily-market-brief", catalog["workflows"])
        self.assertEqual(catalog["schedule_read"], ["list"])

    def test_prompt_catalog_is_compact(self):
        catalog = capabilities.prompt_catalog()
        item = next(c for c in catalog["capabilities"] if c["id"] == "cogsteward.scan")
        self.assertEqual(item["kind"], "run")
        self.assertEqual(item["safety"], "write")
        self.assertIn("--root", item["params"])


if __name__ == "__main__":
    unittest.main()
