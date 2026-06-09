import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "drift-guard.yml"
VENDORED_ACTION_DIR = REPO_ROOT / ".github" / "actions" / "drift-guard"
EXPECTED_USES = (
    "uses: yunya1991/DREAM-AGENT/.github/workflows/"
    "reusable-drift-guard.yml@drift-guard/v0.1.2"
)
EXPECTED_SOURCE_REF = "source_ref: drift-guard/v0.1.2"


class DriftGuardReuseWorkflowTests(unittest.TestCase):
    def test_workflow_uses_pinned_reusable_workflow(self):
        workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn(EXPECTED_USES, workflow_text)
        self.assertIn(EXPECTED_SOURCE_REF, workflow_text)
        self.assertNotIn("uses: ./.github/actions/drift-guard", workflow_text)

    def test_vendored_drift_guard_action_is_removed(self):
        self.assertFalse(VENDORED_ACTION_DIR.exists())


if __name__ == "__main__":
    unittest.main()
