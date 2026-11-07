#!/usr/bin/env python3
"""Local vs origin/main consistency tracker.

Read-only. Compares the current HEAD with origin/main and summarizes
worktree differences by category. Writes a JSON report for tracking.

Usage:
  python 49-交易框架协议/scripts/check_git_consistency.py
  python 49-交易框架协议/scripts/check_git_consistency.py --json-only
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "49-交易框架协议" / "runtime" / "git_consistency.json"
CODE_EXTS = {".py", ".yaml", ".yml", ".sh", ".toml", ".js", ".ts", ".tsx", ".vue"}
DOC_EXTS = {".md", ".json"}  # json 多为运行期数据，单独统计
INTENTIONAL_DOC_PATHS = {
    "49-交易框架协议/SPEC.md",
    "49-交易框架协议/docs/adr/ADR-0002-dual-decision-chain.md",
    "50-NN主矛盾评估器/SPEC.md",
    "42-神经网络交易协调层/SPEC.md",
    "42-神经网络交易协调层/docs/INTEGRATION-50-v0.1.md",
    "48-涌现架构/docs/tech/SPEC-EMERGENCE-EVOLUTION-v0.1.md",
    "48-涌现架构/docs/tech/SPEC-NN-FEEDBACK-GATEWAY-v0.1.md",
}


def git(*args: str) -> str:
    env = {"GIT_NO_LAZY_FETCH": "1"}
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env={**__import__("os").environ, **env},
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    head = git("rev-parse", "HEAD")
    origin_main = git("rev-parse", "origin/main")
    counts = git("rev-list", "--left-right", "--count", "HEAD...origin/main")
    ahead, behind = (int(x) for x in counts.split()) if counts else (0, 0)

    status_lines = git("-c", "core.quotepath=false", "status", "--porcelain=v1").splitlines()
    by_state: Counter[str] = Counter()
    by_top: dict[str, Counter[str]] = defaultdict(Counter)
    code_diffs: dict[str, list[str]] = {"modified": [], "deleted": [], "added": []}
    intentional: list[str] = []
    other: list[str] = []

    for line in status_lines:
        if len(line) < 4:
            continue
        state = line[:2].strip()
        path = line[3:].strip().strip('"')
        by_state[state] += 1
        top = path.split("/", 1)[0]
        by_top[top][state] += 1
        suffix = Path(path).suffix.lower()
        if path in INTENTIONAL_DOC_PATHS:
            intentional.append(path)
        elif suffix in CODE_EXTS:
            key = {"M": "modified", "D": "deleted", "A": "added", "??": "added"}.get(state)
            if key:
                code_diffs[key].append(path)
        elif suffix in DOC_EXTS:
            other.append(path)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "head": head,
        "origin_main": origin_main,
        "commit_in_sync": head == origin_main,
        "ahead": ahead,
        "behind": behind,
        "dirty": {
            "added": by_state.get("A", 0) + by_state.get("??", 0),
            "modified": by_state.get("M", 0),
            "deleted": by_state.get("D", 0),
            "untracked": by_state.get("??", 0),
            "total": sum(by_state.values()),
        },
        "by_top_dir": {k: dict(v) for k, v in sorted(by_top.items())},
        "code_diffs": {k: sorted(v) for k, v in code_diffs.items()},
        "intentional_docs": sorted(intentional),
        "other_docs_or_data": sorted(other),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.json_only:
        print(f"HEAD={head[:8]} origin/main={origin_main[:8]} in_sync={report['commit_in_sync']}")
        print(f"ahead={ahead} behind={behind}")
        print(
            "dirty: "
            f"added={report['dirty']['added']} "
            f"modified={report['dirty']['modified']} "
            f"deleted={report['dirty']['deleted']} "
            f"untracked={report['dirty']['untracked']}"
        )
        code_total = sum(len(v) for v in code_diffs.values())
        print(f"code diffs={code_total} intentional_docs={len(intentional)}")
        print(f"report={REPORT}")
        if not report["commit_in_sync"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())