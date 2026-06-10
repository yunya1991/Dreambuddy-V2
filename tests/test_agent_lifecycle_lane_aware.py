import importlib.util
import unittest
from pathlib import Path


def _load_module(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "AGENT协作工具" / "github-actions"

BUILD = _load_module("build_agent_lifecycle_payload", TOOLS_DIR / "build_agent_lifecycle_payload.py")
CHECK = _load_module("check_agent_lifecycle", TOOLS_DIR / "check_agent_lifecycle.py")


class LaneAwareLifecycleGuardTests(unittest.TestCase):
    def test_fast_lane_allows_single_summary_without_full_protocol(self):
        pr_body = "\n".join(
            [
                "Task Card: https://example.invalid/task-card",
                "Owner Agent: SOLO",
                "Lane: fast",
                "Task ID: task-ui-map-real-data-001",
                "Goal ID: goal-ui-map-001",
            ]
        )
        comments = [
            "\n".join(
                [
                    "[单次总结 / SUMMARY]",
                    "Test: python -m unittest -q",
                    "Status: done",
                ]
            )
        ]
        raw = {
            "branch": "agent/ui-map-real-data-fast",
            "pr_body": pr_body,
            "review_count": 0,
            "comments": comments,
        }

        payload = BUILD.build_payload(raw)
        result = CHECK.evaluate_payload(payload)

        self.assertEqual(result["decision"], "PASS")

    def test_strict_lane_still_requires_full_protocol(self):
        pr_body = "\n".join(
            [
                "Task Card: https://example.invalid/task-card",
                "Owner Agent: SOLO",
                "Lane: strict",
                "Task ID: task-ui-map-real-data-002",
                "Goal ID: goal-ui-map-001",
            ]
        )
        raw = {
            "branch": "milestone/ui-map-real-data-strict",
            "pr_body": pr_body,
            "review_count": 0,
            "comments": [],
        }

        payload = BUILD.build_payload(raw)
        result = CHECK.evaluate_payload(payload)

        self.assertEqual(result["decision"], "BLOCK")
        self.assertIn("RULE_002_DESIGN_REVIEW_REQUIRED", result["reason_codes"])
        self.assertIn("RULE_003_STARTED_REQUIRED", result["reason_codes"])
        self.assertIn("RULE_006_TEST_EVIDENCE_REQUIRED", result["reason_codes"])
        self.assertIn("RULE_008_DONE_REQUIRED", result["reason_codes"])


if __name__ == "__main__":
    unittest.main()

