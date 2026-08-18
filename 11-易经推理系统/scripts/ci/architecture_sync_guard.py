#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from typing import Iterable, List, Set, Tuple


ALLOWED_TOP_LEVEL_DIRS = {
    ".github",
    ".workbuddy",
    "artifacts",
    "constraints",
    "docs",
    "scripts",
    "skills",
    "tests",
    "workflows",
}

ARCH_DOC = "docs/architecture.md"
ENGINEERING_ARCH_DOC = "constraints/system-index/engineering-architecture.md"
COMMUNICATION_CONTRACT = "constraints/workflows-spec/communication-contract-v0.1.md"
WORKFLOW_SPEC_README = "constraints/workflows-spec/README.md"


def read_changed_files(path: str) -> List[str]:
    p = Path(path)
    if not p.exists():
        return []
    files: List[str] = []
    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Git may emit quoted paths for non-ASCII file names when quotePath is enabled.
        # Normalize to avoid false "unknown top-level directory" findings like `"skills`.
        if line.startswith('"') and line.endswith('"'):
            line = line[1:-1]
        files.append(line)
    return files


def starts_with_any(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def evaluate_rules(changed_files: List[str]) -> Tuple[List[str], List[str]]:
    violations: List[str] = []
    notes: List[str] = [f"changed_files={len(changed_files)}"]
    changed_set: Set[str] = set(changed_files)

    top_levels = {path.split("/", 1)[0] for path in changed_files if "/" in path}
    unknown = sorted(top_levels - ALLOWED_TOP_LEVEL_DIRS)
    if unknown:
        violations.append(f"Unknown top-level directory changed: {', '.join(unknown)}")

    if (ARCH_DOC in changed_set) ^ (ENGINEERING_ARCH_DOC in changed_set):
        violations.append(
            f"`{ARCH_DOC}` and `{ENGINEERING_ARCH_DOC}` must be changed together for architecture info sync."
        )

    workflow_changed = starts_with_any(
        path=",".join(changed_files),
        prefixes=("workflows/memory/", "workflows/trading-decision/"),
    ) or any(
        starts_with_any(path, ("workflows/memory/", "workflows/trading-decision/")) for path in changed_files
    )
    if workflow_changed and COMMUNICATION_CONTRACT not in changed_set:
        violations.append(
            f"Changes in memory/trading workflows requires contract sync: `{COMMUNICATION_CONTRACT}`."
        )

    spec_files_changed = any(
        path.startswith("constraints/workflows-spec/")
        and path not in {WORKFLOW_SPEC_README, COMMUNICATION_CONTRACT}
        for path in changed_files
    )
    if spec_files_changed and WORKFLOW_SPEC_README not in changed_set:
        violations.append(
            f"Workflow spec files changed; update index file too: `{WORKFLOW_SPEC_README}`."
        )

    constraints_changed = any(path.startswith("constraints/") for path in changed_files)
    sync_docs_changed = any(
        path.startswith("constraints/system-index/") or path.startswith("constraints/workflows-spec/")
        for path in changed_files
    )
    if constraints_changed and not sync_docs_changed:
        violations.append(
            "Changes under constraints/ require updates in constraints/system-index/ or constraints/workflows-spec/."
        )

    return violations, notes


def write_summary(violations: List[str], notes: List[str], changed_files: List[str]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines: List[str] = ["## Architecture Sync Guard", ""]
    lines.append("### Notes")
    lines.extend([f"- {n}" for n in notes])
    lines.append("")
    lines.append("### Changed Files")
    lines.extend([f"- `{f}`" for f in changed_files[:120]])
    if len(changed_files) > 120:
        lines.append(f"- ... and {len(changed_files) - 120} more")
    lines.append("")

    if violations:
        lines.append("### Result: FAILED")
        lines.extend([f"- {v}" for v in violations])
    else:
        lines.append("### Result: PASSED")
        lines.append("- Architecture consistency and info sync checks passed.")
    lines.append("")

    Path(summary_path).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    changed_files_path = os.getenv("CHANGED_FILES_PATH", "")
    if not changed_files_path:
        print("CHANGED_FILES_PATH is required.", file=sys.stderr)
        return 2

    changed_files = read_changed_files(changed_files_path)
    violations, notes = evaluate_rules(changed_files)
    write_summary(violations, notes, changed_files)

    if violations:
        print("Architecture sync guard failed:", file=sys.stderr)
        for v in violations:
            print(f"- {v}", file=sys.stderr)
        return 1

    print("Architecture sync guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
