"""Git 历史溯源 — 分析文件/函数的变更历史。

使用 git log（只读）和 git blame（只读）提取：
- 作者列表
- 首次/最后提交时间
- 变更次数
- 热点行（变更频繁的行）

每条结论带 Evidence（provenance + confidence + known_gaps）。
"""

from __future__ import annotations

import os
import subprocess
from collections import Counter
from typing import Any

from .evidence import Evidence


def _run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    """执行 git 子进程（只读操作），返回 (returncode, stdout, stderr)。"""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)


def trace_git_history(repo_path: str, target_path: str) -> dict[str, Any]:
    """分析目标文件的 git 历史。

    Args:
        repo_path: git 仓库根目录
        target_path: 要分析的文件路径（相对于 repo_path 或绝对路径）

    Returns:
        {
            "authors": [作者列表],
            "first_commit": str | None (ISO 时间),
            "last_commit": str | None (ISO 时间),
            "change_count": int,
            "hot_lines": [{line, author, commit_count}],
            "evidence": [Evidence],
        }
    """
    result: dict[str, Any] = {
        "authors": [],
        "first_commit": None,
        "last_commit": None,
        "change_count": 0,
        "hot_lines": [],
        "evidence": [],
    }

    # 检查仓库有效性
    rc, out, err = _run_git(["rev-parse", "--is-inside-work-tree"], repo_path)
    if rc != 0 or out.strip() != "true":
        result["evidence"].append(Evidence(
            result=f"非 git 仓库或路径无效: {repo_path}",
            provenance={"repo": repo_path, "stderr": err.strip()},
            confidence=1.0,
            known_gaps=["无法执行 git 操作，目标可能不是 git 仓库"],
            level="observation",
        ))
        return result

    # 检查文件是否存在
    if not os.path.isfile(target_path):
        result["evidence"].append(Evidence(
            result=f"文件不存在: {target_path}",
            provenance={"repo": repo_path, "target": target_path},
            confidence=1.0,
            known_gaps=["文件不存在，无法分析 git 历史"],
            level="observation",
        ))
        return result

    # 相对路径（git 需要相对路径）
    try:
        rel_path = os.path.relpath(target_path, repo_path)
    except ValueError:
        rel_path = target_path

    # git log --follow 获取提交历史
    rc, log_out, log_err = _run_git(
        ["log", "--follow", "--format=%an|%ai|%H", "--", rel_path],
        repo_path,
    )

    commits: list[dict[str, str]] = []
    if rc == 0 and log_out.strip():
        for line in log_out.strip().split("\n"):
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({
                    "author": parts[0],
                    "date": parts[1],
                    "hash": parts[2],
                })

    # 解析结果
    authors_set: set[str] = set()
    for c in commits:
        authors_set.add(c["author"])

    result["authors"] = sorted(authors_set)
    result["change_count"] = len(commits)
    if commits:
        result["first_commit"] = commits[-1]["date"]  # 最旧的在最后
        result["last_commit"] = commits[0]["date"]     # 最新的在第一行

    # git blame 获取行级作者信息
    rc2, blame_out, _ = _run_git(
        ["blame", "--line-porcelain", "--", rel_path],
        repo_path,
    )

    line_authors: list[dict[str, Any]] = []
    if rc2 == 0 and blame_out:
        current_line = 0
        current_author = ""
        current_commit = ""
        for line in blame_out.split("\n"):
            if line.startswith("\t"):
                current_line += 1
                line_authors.append({
                    "line": current_line,
                    "author": current_author,
                    "commit": current_commit[:8],
                })
            elif line.startswith("author "):
                current_author = line[len("author "):]
            elif line.startswith("hash "):
                current_commit = line[len("hash "):]
            elif line.startswith("revision "):
                current_commit = line[len("revision "):]

    # 热点行：按 commit 分组，变更多的 commit 关联的行是热点
    commit_lines: dict[str, list[int]] = {}
    for la in line_authors:
        commit_lines.setdefault(la["commit"], []).append(la["line"])

    # 热点行 = 提交次数最多的 commit 关联的行
    hot_commits = sorted(commit_lines.items(), key=lambda x: len(x[1]), reverse=True)
    hot_lines: list[dict[str, Any]] = []
    for commit_hash, lines in hot_commits[:5]:  # top 5 commits
        for ln in lines:
            # 找对应作者
            author = next(
                (la["author"] for la in line_authors if la["line"] == ln),
                "unknown",
            )
            hot_lines.append({
                "line": ln,
                "author": author,
                "commit": commit_hash,
            })

    result["hot_lines"] = hot_lines

    # 构建 Evidence
    result["evidence"] = _build_evidence(
        result["authors"],
        result["change_count"],
        result["first_commit"],
        result["last_commit"],
        len(hot_lines),
        repo_path,
        target_path,
    )

    return result


def _build_evidence(
    authors: list[str],
    change_count: int,
    first_commit: str | None,
    last_commit: str | None,
    hot_line_count: int,
    repo_path: str,
    target_path: str,
) -> list[Evidence]:
    evidence: list[Evidence] = []

    evidence.append(Evidence(
        result=f"变更历史: {change_count} 次提交, {len(authors)} 位作者",
        provenance={
            "repo": repo_path,
            "target": target_path,
            "analysis": "git_log",
        },
        confidence=1.0,
        known_gaps=[
            "git log --follow 只能追踪文件重命名，不追踪内容拆分/合并",
            "合并提交默认不展开（no --cc/-m 选项）",
        ],
        level="observation",
    ))

    if first_commit and last_commit:
        evidence.append(Evidence(
            result=f"首次提交: {first_commit}, 最后提交: {last_commit}",
            provenance={
                "repo": repo_path,
                "target": target_path,
                "analysis": "git_log_dates",
            },
            confidence=1.0,
            known_gaps=["时区为提交者本地时区，跨时区可能不准确"],
            level="derivation",
        ))

    if authors:
        evidence.append(Evidence(
            result=f"作者: {', '.join(authors)}",
            provenance={
                "repo": repo_path,
                "target": target_path,
                "analysis": "git_log_authors",
            },
            confidence=0.9,
            known_gaps=[
                "作者名取自 git config user.name，可能与真实身份不一致",
                "多人维护的文件作者列表可能不完整（默认无 --all 选项）",
            ],
            level="derivation",
        ))

    if hot_line_count > 0:
        evidence.append(Evidence(
            result=f"热点行: {hot_line_count} 行关联高频变更提交",
            provenance={
                "repo": repo_path,
                "target": target_path,
                "analysis": "git_blame",
            },
            confidence=0.8,
            known_gaps=[
                "git blame 只显示最后一次变更的作者，历史作者被覆盖",
                "行号基于当前 HEAD，文件修改后行号会变化",
                "合并冲突解决的行可能归属不准确",
            ],
            level="inference",
        ))

    return evidence
