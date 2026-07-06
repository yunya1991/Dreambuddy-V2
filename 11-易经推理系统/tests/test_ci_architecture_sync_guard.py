import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "architecture_sync_guard.py"


def _run_guard(changed_files):
    changed_file_path = REPO_ROOT / ".tmp_changed_files_arch_guard.txt"
    changed_file_path.write_text("\n".join(changed_files) + "\n", encoding="utf-8")
    env = os.environ.copy()
    env["CHANGED_FILES_PATH"] = str(changed_file_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    changed_file_path.unlink(missing_ok=True)
    return result


def test_arch_guard_passes_for_synced_docs_and_specs():
    result = _run_guard(
        [
            "docs/architecture.md",
            "constraints/system-index/engineering-architecture.md",
            "constraints/workflows-spec/memory.md",
            "constraints/workflows-spec/README.md",
        ]
    )
    assert result.returncode == 0, result.stderr


def test_arch_guard_fails_for_unknown_top_level_directory():
    result = _run_guard(["unknown_dir/file.txt"])
    assert result.returncode == 1
    assert "Unknown top-level directory" in result.stderr


def test_arch_guard_allows_workbuddy_top_level_directory():
    result = _run_guard([".workbuddy/memory_l4/schemas/stats.schema.json"])
    assert result.returncode == 0, result.stderr


def test_arch_guard_allows_quoted_paths_for_non_ascii_names():
    result = _run_guard(['"skills/3-SUPPORT/boss-secretary/reports/trading/日报.md"'])
    assert result.returncode == 0, result.stderr


def test_arch_guard_fails_if_docs_architecture_not_synced():
    result = _run_guard(["docs/architecture.md"])
    assert result.returncode == 1
    assert "must be changed together" in result.stderr


def test_arch_guard_fails_if_workflow_changes_without_contract_sync():
    result = _run_guard(["workflows/memory/L1_realtime/new_logic.py"])
    assert result.returncode == 1
    assert "requires contract sync" in result.stderr
