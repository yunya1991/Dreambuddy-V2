"""SPEC-33-F T-F07：基于只读 git log 的变更考古，全程无网络。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

from core.evidence import Evidence
from core.git_history import _run_git

_WINDOW_DAYS = 90
_HOTSPOT_LIMIT = 20


def _empty_report(target: str) -> dict[str, Any]:
    return {
        "section": "archaeology",
        "target": target,
        "degraded": True,
        "commit_count": 0,
        "hotspots": [],
        "co_change": [],
        "bus_factor": [],
        "change_radius_90d": [],
        "evidence": [],
        "known_gaps": [],
    }


def _parse_log(stdout: str) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    for chunk in stdout.split("\x1e"):
        lines = chunk.splitlines()
        if not lines:
            continue
        parts = lines[0].split("\x1f")
        if len(parts) != 3:
            continue
        commit_hash, author, date = parts
        files = sorted({line.strip() for line in lines[1:] if line.strip()})
        commits.append({"hash": commit_hash, "author": author, "date": date, "files": files})
    return commits


def _bus_factor(file_commits: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file in sorted(file_commits):
        commits = file_commits[file]
        author_counts = Counter(commit["author"] for commit in commits)
        ranked = sorted(author_counts.items(), key=lambda item: (-item[1], item[0]))
        cumulative = 0
        factor = 0
        for _author, count in ranked:
            cumulative += count
            factor += 1
            if cumulative * 2 >= len(commits):
                break
        rows.append(
            {
                "file": file,
                "factor": factor,
                "commits": len(commits),
                "authors": sorted(author_counts),
                "author_commits": {
                    author: author_counts[author] for author in sorted(author_counts)
                },
            }
        )
    return rows


def scan_archaeology(target: str, *, now: datetime | None = None) -> dict[str, Any]:
    """输出 hotspot Top20、稀疏共变矩阵、bus factor 与 90 天变更半径。"""
    requested = Path(target).expanduser()
    root = requested if requested.is_dir() else requested.parent
    pathspec = "." if requested.is_dir() else requested.name
    report = _empty_report(str(root))
    rc, stdout, stderr = _run_git(
        [
            "-c",
            "core.quotepath=false",
            "log",
            "--relative",
            "--no-merges",
            "--format=%x1e%H%x1f%an%x1f%aI",
            "--name-only",
            "--",
            pathspec,
        ],
        str(root),
    )
    if rc != 0:
        reason = stderr.strip()[:300] or f"git log returned {rc}"
        report["known_gaps"] = [reason]
        report["evidence"] = [
            Evidence(
                result=f"变更考古不可用: {reason}",
                provenance={"analysis": "git_archaeology", "target": str(root)},
                known_gaps=[reason],
                level="unknown",
            ).to_dict()
        ]
        return report

    commits = _parse_log(stdout)
    file_commits: dict[str, list[dict[str, Any]]] = {}
    pair_counts: Counter[tuple[str, str]] = Counter()
    for commit in commits:
        for file in commit["files"]:
            file_commits.setdefault(file, []).append(commit)
        pair_counts.update(combinations(commit["files"], 2))

    hotspots = [
        {
            "file": file,
            "commits": len(items),
            "authors": sorted({commit["author"] for commit in items}),
        }
        for file, items in file_commits.items()
    ]
    hotspots.sort(key=lambda item: (-item["commits"], item["file"]))
    co_change = [
        {"files": [left, right], "count": count}
        for (left, right), count in sorted(
            pair_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]

    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    cutoff = reference - timedelta(days=_WINDOW_DAYS)
    recent_commits: dict[str, list[dict[str, Any]]] = {}
    recent_pairs: dict[str, set[str]] = {}
    for commit in commits:
        try:
            committed_at = datetime.fromisoformat(commit["date"])
        except ValueError:
            continue
        if committed_at < cutoff:
            continue
        for file in commit["files"]:
            recent_commits.setdefault(file, []).append(commit)
            recent_pairs.setdefault(file, set()).update(
                other for other in commit["files"] if other != file
            )
    radius = [
        {
            "file": file,
            "commits_90d": len(items),
            "co_changed_files": sorted(recent_pairs.get(file, set())),
            "radius": len(recent_pairs.get(file, set())),
        }
        for file, items in recent_commits.items()
    ]
    radius.sort(key=lambda item: (-item["commits_90d"], item["file"]))

    report.update(
        {
            "degraded": False,
            "commit_count": len(commits),
            "hotspots": hotspots[:_HOTSPOT_LIMIT],
            "co_change": co_change,
            "bus_factor": _bus_factor(file_commits),
            "change_radius_90d": radius,
            "window_days": _WINDOW_DAYS,
        }
    )
    report["evidence"] = [
        Evidence(
            result=(
                f"变更考古: {len(commits)} 次提交, {len(file_commits)} 个文件, "
                f"{len(co_change)} 对共变关系"
            ),
            provenance={
                "analysis": "git_archaeology",
                "target": str(root),
                "command": "git log --relative --no-merges --name-only",
                "network": False,
            },
            known_gaps=[
                "合并不展开；重命名按 git 当前路径记录，不做内容拆分/合并追踪",
                "bus factor 为覆盖至少 50% 文件提交所需的最少作者数，不等于真实离职风险",
            ],
            level="observation",
        ).to_dict()
    ]
    return report
