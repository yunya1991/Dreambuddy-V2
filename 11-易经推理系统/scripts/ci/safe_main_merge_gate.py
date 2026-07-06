#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple


ALLOWED_BRANCH_PREFIX = (
    "feature/",
    "fix/",
    "hotfix/",
    "docs/",
    "chore/",
    "refactor/",
    "test/",
)


def read_event(event_path: str) -> dict:
    path = Path(event_path)
    if not path.exists():
        raise FileNotFoundError(f"GITHUB_EVENT_PATH not found: {event_path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_changed_files(changed_files_path: str) -> List[str]:
    path = Path(changed_files_path)
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_rules(event: dict, changed_files: List[str]) -> Tuple[List[str], List[str]]:
    violations: List[str] = []
    notes: List[str] = []

    pr = event.get("pull_request", {})
    base_ref = pr.get("base", {}).get("ref", "")
    head_ref = pr.get("head", {}).get("ref", "")
    pr_title = pr.get("title", "")

    notes.append(f"base_ref={base_ref}")
    notes.append(f"head_ref={head_ref}")
    notes.append(f"changed_files={len(changed_files)}")

    if base_ref != "main":
        violations.append("PR base branch must be main.")

    if not head_ref.startswith(ALLOWED_BRANCH_PREFIX):
        allowed = ", ".join(ALLOWED_BRANCH_PREFIX)
        violations.append(f"Branch name must start with one of: {allowed}")

    if not pr_title.strip():
        violations.append("PR title cannot be empty.")

    if not changed_files:
        violations.append("No changed files detected. Check git diff range in workflow.")

    constraints_changed = any(path.startswith("constraints/") for path in changed_files)
    specs_or_index_changed = any(
        path.startswith("constraints/workflows-spec/") or path.startswith("constraints/system-index/")
        for path in changed_files
    )
    if constraints_changed and not specs_or_index_changed:
        violations.append(
            "Changes under constraints/ require updates in constraints/workflows-spec/ or constraints/system-index/."
        )

    trading_runtime_changed = any(
        path.startswith("workflows/trading-decision/orchestrator/")
        or path.startswith("workflows/trading-decision/transports/")
        for path in changed_files
    )
    trading_system_tests_changed = any(
        path.startswith("tests/test_trading_")
        and (
            "system_loop" in path
            or "governance_orchestrator" in path
            or "state_machine" in path
            or "transports" in path
            or "replay" in path
            or "memory_l4_contract" in path
        )
        for path in changed_files
    )
    if trading_runtime_changed and not trading_system_tests_changed:
        violations.append(
            "Trading runtime changes require system-level trading tests updates (test_trading_*)."
        )

    if any(path == "main" for path in changed_files):
        violations.append("Invalid file change detected: main")

    return violations, notes


def write_summary(violations: List[str], notes: List[str], changed_files: List[str]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines = ["## Safe Main Merge Gate", ""]
    lines.append("### Notes")
    for note in notes:
        lines.append(f"- {note}")
    lines.append("")

    lines.append("### Changed Files")
    for path in changed_files[:100]:
        lines.append(f"- `{path}`")
    if len(changed_files) > 100:
        lines.append(f"- ... and {len(changed_files) - 100} more")
    lines.append("")

    if violations:
        lines.append("### Result: FAILED")
        for item in violations:
            lines.append(f"- {item}")
    else:
        lines.append("### Result: PASSED")
        lines.append("- All gate checks passed.")
    lines.append("")

    Path(summary_path).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    changed_files_path = os.getenv("CHANGED_FILES_PATH", "")

    if not event_path:
        print("GITHUB_EVENT_PATH is required.", file=sys.stderr)
        return 2

    event = read_event(event_path)
    changed_files = read_changed_files(changed_files_path) if changed_files_path else []
    violations, notes = check_rules(event, changed_files)
    write_summary(violations, notes, changed_files)

    if violations:
        print("Safe main merge gate failed:", file=sys.stderr)
        for item in violations:
            print(f"- {item}", file=sys.stderr)
        return 1

    print("Safe main merge gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
