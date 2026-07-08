import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_classify_pr_empty_diff_returns_auto_close():
    mod = _load_module("scripts/ci/branch_lifecycle_bot.py")
    pr = {"number": 5, "state": "open", "updated_at": "2026-05-01T00:00:00Z"}
    result = mod.classify_pull_request(
        pr=pr,
        changed_files=[],
        has_merge_base=True,
        stale_days=7,
        now_ts="2026-05-11T00:00:00Z",
    )
    assert result["risk_level"] == "L1"
    assert result["labels"] == ["branch-bot/empty-diff"]
    assert result["actions"] == ["close_pr"]


def test_classify_pr_no_merge_base_returns_manual_review():
    mod = _load_module("scripts/ci/branch_lifecycle_bot.py")
    pr = {"number": 8, "state": "open", "updated_at": "2026-05-10T00:00:00Z"}
    result = mod.classify_pull_request(
        pr=pr,
        changed_files=["scripts/ci/x.py"],
        has_merge_base=False,
        stale_days=7,
        now_ts="2026-05-11T00:00:00Z",
    )
    assert result["risk_level"] == "L2"
    assert "branch-bot/no-merge-base" in result["labels"]
    assert "open_issue" in result["actions"]


def test_classify_branch_never_mutates_protected():
    mod = _load_module("scripts/ci/branch_lifecycle_bot.py")
    branch = {"name": "main", "protected": True, "is_merged": True, "age_days": 30}
    result = mod.classify_branch(branch=branch, retention_days=7)
    assert result["risk_level"] == "L3"
    assert result["actions"] == []


def test_execute_actions_dry_run_has_no_remote_calls():
    mod = _load_module("scripts/ci/branch_lifecycle_bot.py")
    calls = []

    def fake_call(method, path, payload=None):
        calls.append((method, path, payload))
        return {"ok": True}

    res = mod.execute_actions(
        repo="yunya1991/dream-multiskill-v2",
        target={"type": "pr", "number": 5},
        actions=["close_pr", "add_label"],
        labels=["branch-bot/empty-diff"],
        dry_run=True,
        api_call=fake_call,
    )
    assert res["executed"] == []
    assert len(calls) == 0


def test_execute_actions_close_pr_and_label():
    mod = _load_module("scripts/ci/branch_lifecycle_bot.py")
    calls = []

    def fake_call(method, path, payload=None):
        calls.append((method, path, payload))
        return {"ok": True}

    res = mod.execute_actions(
        repo="yunya1991/dream-multiskill-v2",
        target={"type": "pr", "number": 5},
        actions=["close_pr", "add_label"],
        labels=["branch-bot/auto-closed"],
        dry_run=False,
        api_call=fake_call,
    )
    assert "close_pr" in res["executed"]
    assert "add_label" in res["executed"]
    assert len(calls) == 2


def test_parse_args_defaults():
    mod = _load_module("scripts/ci/branch_lifecycle_bot.py")
    args = mod.parse_args([])
    assert args.repo == "yunya1991/dream-multiskill-v2"
    assert args.dry_run is False
    assert args.stale_days == 7
    assert args.retention_days == 14


def test_write_artifacts_creates_three_json_files(tmp_path: Path):
    mod = _load_module("scripts/ci/branch_lifecycle_bot.py")
    out = mod.write_artifacts(
        base_dir=tmp_path,
        scan={"prs": 1, "branches": 2},
        actions={"executed": ["close_pr"]},
        summary={"run_id": "r1", "errors": 0},
        timestamp="20260511T120000Z",
    )
    assert out["scan"].name.startswith("scan-")
    assert out["actions"].exists()
    assert out["summary"].exists()
