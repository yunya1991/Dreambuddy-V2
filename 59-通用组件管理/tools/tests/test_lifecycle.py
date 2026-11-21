"""生命周期状态机的判据测试（P2-1）。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import lifecycle  # noqa: E402

TODAY = date(2026, 11, 21)


class ValidateTest(unittest.TestCase):
    def test_active_component_passes_without_deprecated_block(self):
        manifest = {"lifecycle": "active"}
        self.assertEqual(lifecycle.validate("demo", manifest, set(), TODAY), [])

    def test_unknown_state_is_rejected(self):
        errors = lifecycle.validate("demo", {"lifecycle": "archived"}, set(), TODAY)
        self.assertEqual(len(errors), 1)
        self.assertIn("lifecycle 非法", errors[0])

    def test_deprecated_requires_block(self):
        errors = lifecycle.validate("demo", {"lifecycle": "deprecated"}, set(), TODAY)
        self.assertIn("必须声明 deprecated 块", errors[0])

    def test_deprecated_requires_sunset_after_start(self):
        manifest = {
            "lifecycle": "deprecated",
            "deprecated": {"at": "2026-12-01", "sunset_at": "2026-11-01", "reason": "合并"},
        }
        errors = lifecycle.validate("demo", manifest, set(), TODAY)
        self.assertIn("必须晚于", errors[0])

    def test_deprecated_requires_replacement_or_reason(self):
        manifest = {
            "lifecycle": "deprecated",
            "deprecated": {"at": "2026-11-01", "sunset_at": "2026-12-31"},
        }
        errors = lifecycle.validate("demo", manifest, set(), TODAY)
        self.assertIn("replacement", errors[0])

    def test_deprecated_with_replacement_passes(self):
        manifest = {
            "lifecycle": "deprecated",
            "deprecated": {
                "at": "2026-11-01",
                "sunset_at": "2026-12-31",
                "replacement": "market-data",
            },
        }
        self.assertEqual(lifecycle.validate("demo", manifest, set(), TODAY), [])

    def test_retired_rejects_future_sunset(self):
        manifest = {
            "lifecycle": "retired",
            "deprecated": {"at": "2026-11-01", "sunset_at": "2027-01-01", "reason": "停用"},
        }
        errors = lifecycle.validate("demo", manifest, set(), TODAY)
        self.assertIn("尚未到期", errors[0])

    def test_retired_rejects_product_distribution(self):
        manifest = {
            "lifecycle": "retired",
            "deprecated": {"at": "2025-01-01", "sunset_at": "2025-06-30", "reason": "停用"},
        }
        errors = lifecycle.validate("demo", manifest, {"demo"}, TODAY)
        self.assertIn("仍被 products", errors[0])

    def test_retired_passes_when_due_and_not_distributed(self):
        manifest = {
            "lifecycle": "retired",
            "deprecated": {"at": "2025-01-01", "sunset_at": "2025-06-30", "reason": "停用"},
        }
        self.assertEqual(lifecycle.validate("demo", manifest, {"other"}, TODAY), [])

    def test_bad_date_format_is_reported(self):
        manifest = {
            "lifecycle": "deprecated",
            "deprecated": {"at": "2026/11/01", "sunset_at": "2026-12-31", "reason": "x"},
        }
        errors = lifecycle.validate("demo", manifest, set(), TODAY)
        self.assertIn("YYYY-MM-DD", errors[0])


class TreeTest(unittest.TestCase):
    def _write(self, root: Path, name: str, lifecycle_state: str, extra: str = "") -> None:
        component = root / "components" / name
        component.mkdir(parents=True)
        (component / "component.yaml").write_text(
            "name: {}\nlifecycle: {}\n{}".format(name, lifecycle_state, extra),
            encoding="utf-8",
        )

    def test_check_reads_tree_and_detects_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "good", "active")
            self._write(root, "bad", "deprecated")
            (root / "products").mkdir()
            results = lifecycle.check(root / "components", root / "products", today=TODAY)
            self.assertTrue(results["good"]["ok"])
            self.assertFalse(results["bad"]["ok"])
            self.assertEqual(results["bad"]["lifecycle"], "deprecated")

    def test_plan_reports_missing_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "demo", "deprecated")
            (root / "products").mkdir()
            result = lifecycle.plan(
                "demo", "retired", root / "components", root / "products", TODAY
            )
            self.assertFalse(result["ready"])
            self.assertTrue(result["missing"])

    def test_plan_ready_for_beta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "demo", "draft")
            (root / "products").mkdir()
            result = lifecycle.plan("demo", "beta", root / "components", root / "products", TODAY)
            self.assertTrue(result["ready"])
            self.assertEqual(result["from"], "draft")

    def test_plan_rejects_illegal_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "demo", "active")
            (root / "products").mkdir()
            with self.assertRaises(ValueError):
                lifecycle.plan("demo", "retired", root / "components", root / "products", TODAY)


if __name__ == "__main__":
    unittest.main()
