import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "review_policy_guard.py"
SPEC = importlib.util.spec_from_file_location("review_policy_guard", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
review_policy_check = MODULE.review_policy_check


def test_owner_can_merge_without_approval():
    ok, reason = review_policy_check(
        author_login="yunya1991",
        owner_login="yunya1991",
        review_states=[],
    )
    assert ok is True
    assert "owner bypass" in reason


def test_non_owner_needs_approval():
    ok, reason = review_policy_check(
        author_login="contributor-a",
        owner_login="yunya1991",
        review_states=["COMMENTED", "CHANGES_REQUESTED"],
    )
    assert ok is False
    assert "requires at least one APPROVED review" in reason


def test_non_owner_passes_with_approval():
    ok, reason = review_policy_check(
        author_login="contributor-a",
        owner_login="yunya1991",
        review_states=["COMMENTED", "APPROVED"],
    )
    assert ok is True
    assert "approved reviews=1" in reason
