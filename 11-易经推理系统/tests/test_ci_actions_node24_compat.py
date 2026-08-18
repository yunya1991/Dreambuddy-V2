from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_all_workflows_enable_node24_opt_in():
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    workflow_files = sorted(p for p in workflows_dir.glob("*.yml") if p.name != ".gitkeep")
    assert workflow_files

    missing = []
    for path in workflow_files:
        text = path.read_text(encoding="utf-8")
        if "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" not in text:
            missing.append(path.name)

    assert not missing

