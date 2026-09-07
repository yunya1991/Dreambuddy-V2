"""Docs consistency rubric (TR-11.4, threshold ≥ 4/5).

Rule: for every task listed in spec tasks.md (11 numbered tasks) we give
+ 1 point if (status == completed) AND (a matching test_task*.py file
exists in the tests dir). Scale = 0 → 5. score = completed_match_count
/ total_tasks * 5 (ceil to 5 if everything perfect). Minimum 4.0 required.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


_TASK_ID_RE = re.compile(r"##\s*Task\s*(?P<id>\d+)")
_STATUS_RE = re.compile(r"-\s*\*\*Status\*\*\s*:\s*`(?P<s>[^`]+)`")


def _parse_tasks(tasks_md_path: str | Path) -> List[Dict[str, Any]]:
    """Return list of {id, status_line, status} ordered by task id."""
    text = Path(tasks_md_path).read_text(encoding="utf-8")
    # Split by "## Task " lines.
    parts: List[tuple[int, str]] = []  # (task_id, chunk)
    for m in _TASK_ID_RE.finditer(text):
        task_id = int(m.group("id"))
        parts.append((task_id, text[m.end():]))
    # For each chunk, find the first Status line (the "- **Status**:" one
    # that appears at the beginning of each block).
    result: List[Dict[str, Any]] = []
    for idx, (task_id, chunk) in enumerate(parts):
        end_next = parts[idx + 1][1] if idx + 1 < len(parts) else None
        block = chunk
        if end_next is not None:
            # The original text has "## Task X" before end_next; find the
            # boundary offset relative to our start point.
            # Simpler: just use the first occurrence of "## Task " inside
            # chunk if present, to end the block early.
            stop = chunk.find("\n## Task ")
            if stop > 0:
                block = chunk[:stop]
        status_match = _STATUS_RE.search(block)
        status = status_match.group("s") if status_match else "pending"
        result.append({"id": task_id, "status": status.lower()})
    return result


def _find_test_file_for(tests_dir: str | Path, task_id: int) -> Optional[Path]:
    td = Path(tests_dir)
    # Expected name: test_task{id}_xxx.py.
    for f in sorted(td.glob(f"test_task{task_id}_*.py")):
        if f.is_file():
            return f
    return None


def score_report_spec_vs_tests(
    *,
    tasks_md_path: str | Path,
    tests_dir: str | Path,
) -> Dict[str, Any]:
    """Compute docs-consistency 0-5 score.

    Score rules: for each declared task in spec:
      +1 if status == "completed" AND matching test file exists.
      +0.5 if status == "in_progress" AND a test file exists.
      0 otherwise (pending, missing test file, inconsistent status).
    Score = total_points / total_tasks * 5. Capped at 5. Threshold ≥ 4.
    """
    tasks = _parse_tasks(tasks_md_path)
    total = len(tasks)
    if total == 0:
        return {"score_0_to_5": 0.0, "summary_by_task_id": {},
                 "total_tasks": 0, "errors": ["no tasks found"]}
    points = 0.0
    summary_by_task_id: Dict[int, Dict[str, Any]] = {}
    for t in tasks:
        tid = t["id"]
        status = t["status"]
        test_file = _find_test_file_for(tests_dir, tid)
        subtask = 0.0
        reasons = []
        if status == "completed":
            if test_file:
                subtask = 1.0
                reasons.append("completed+test_file")
            else:
                reasons.append("completed_MISSING_test_file")
        elif status == "in_progress":
            if test_file:
                subtask = 0.5
                reasons.append("in_progress+test_file_present")
            else:
                reasons.append("in_progress_NO_test_yet")
        else:
            if test_file:
                reasons.append("pending_BUT_test_file_exists_(ok_expected_after_green)")
            else:
                reasons.append("pending_without_test_(expected_pre_red)")
        points += subtask
        summary_by_task_id[tid] = {
            "status": status,
            "test_file": str(test_file.name) if test_file else None,
            "points_awarded": subtask,
            "reasons": reasons,
        }
    score_0_to_5 = round(min(5.0, points / total * 5.0), 3)
    return {
        "score_0_to_5": score_0_to_5,
        "threshold_required_ge": 4.0,
        "pass": bool(score_0_to_5 >= 4.0),
        "total_tasks": total,
        "completed_count": sum(
            1 for t in tasks if t["status"] == "completed"
        ),
        "test_files_found_count": sum(
            1 for tid in summary_by_task_id
            if summary_by_task_id[tid]["test_file"]
        ),
        "points_total_max": total,
        "points_achieved": round(points, 3),
        "summary_by_task_id": {k: summary_by_task_id[k]
                                for k in sorted(summary_by_task_id)},
    }


def run_cli(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Docs consistency rubric.")
    p.add_argument("--tasks-md", required=True,
                   help="Path to spec tasks.md (from spec mode).")
    p.add_argument("--tests-dir", required=True,
                   help="Path to TEE tests/ directory.")
    args = p.parse_args(argv)
    out = score_report_spec_vs_tests(
        tasks_md_path=args.tasks_md, tests_dir=args.tests_dir)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["pass"] else 2


if __name__ == "__main__":
    sys.exit(run_cli())
