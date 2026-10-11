"""演化叙事生成器 — 基于 git 历史合成架构成长故事。

PoE Task 3：检测架构转折点、重构动机推断、技术债累积路径。

Evidence-First 硬约束：每条结论带 Evidence（NFR-1）。
Inference 控制：动机推断必须为 inference 级 + known_gaps 非空（NFR-1a）。
FAIL-OPEN：非 git 仓库/异常时返回 level=unknown Evidence（NFR-7）。
"""
from __future__ import annotations

import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .evidence import Evidence, EvidenceLevel


# 重构动机关键字 → 推断的动机标签
_REFACTOR_MOTIVATIONS = {
    "refactor": "代码重构（结构优化）",
    "split": "模块拆分（解耦）",
    "merge": "模块合并（聚合）",
    "rename": "命名规范化",
    "remove": "废弃清理",
    "cleanup": "技术债清理",
    "migrate": "技术迁移",
    "extract": "提取抽象",
    "introduce": "引入新机制",
}

# 转折点判定关键字
_TURNING_POINT_KEYWORDS = {"refactor", "split", "merge", "migrate", "rewrite", "restructure"}

# 技术债标记
_DEBT_MARKERS = ("TODO", "FIXME", "XXX", "HACK")


# ---------- 数据结构 ----------

@dataclass
class TurningPoint:
    """架构转折点。"""
    commit: str
    message: str
    change_stats: dict[str, int]
    motivation_inference: str = ""
    evidence: Evidence = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "message": self.message,
            "change_stats": self.change_stats,
            "motivation_inference": self.motivation_inference,
            "evidence": self.evidence,
        }


@dataclass
class TechDebtItem:
    """技术债时间线条目。"""
    commit: str
    file: str
    line: int
    marker: str
    comment: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "file": self.file,
            "line": self.line,
            "marker": self.marker,
            "comment": self.comment,
        }


# ---------- 工具函数 ----------

def _run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    """执行 git 子进程（只读）。"""
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


def _is_git_repo(target: str) -> bool:
    if not os.path.isdir(target):
        return False
    rc, out, _ = _run_git(["rev-parse", "--is-inside-work-tree"], target)
    return rc == 0 and out.strip() == "true"


# ---------- 叙事生成器 ----------

class EvolutionNarrator:
    """演化叙事生成器。

    生成策略：
    1. git log --stat 获取每个 commit 的变更统计
    2. 关键字匹配 + 变更规模 → 识别转折点
    3. 对转折点 commit message 推断动机（inference 级）
    4. git log -S "TODO" 追踪技术债引入/消亡
    """

    def generate(self, target: str) -> dict[str, Any]:
        """生成演化叙事。

        Args:
            target: git 仓库根路径

        Returns:
            {
                "target": str,
                "turning_points": [TurningPoint.to_dict()...],
                "tech_debt_timeline": [TechDebtItem.to_dict()...],
                "evidence": [Evidence...],
            }
        """
        if not _is_git_repo(target):
            return self._failopen_unknown(target, f"非 git 仓库或路径不存在: {target}")

        # 1. 获取 commit log + stat
        commits = self._get_commit_log_with_stats(target)
        if not commits:
            return self._failopen_unknown(target, "git 仓库无 commit 记录")

        # 2. 识别转折点
        turning_points: list[TurningPoint] = []
        all_evidence: list[Evidence] = []

        for c in commits:
            is_turning = self._is_turning_point(c)
            if is_turning:
                motivation = self._infer_motivation(c["message"])
                ev = Evidence(
                    result=f"架构转折点: commit {c['hash'][:8]} - {c['message'][:80]}",
                    level=EvidenceLevel.DERIVATION,
                    provenance={
                        "repo": target,
                        "commit": c["hash"],
                        "message": c["message"],
                        "files_changed": c["files_changed"],
                        "insertions": c["insertions"],
                        "deletions": c["deletions"],
                        "analysis": "turning_point_detection",
                    },
                    confidence=0.75,
                    known_gaps=[
                        "转折点判定基于 commit message 关键字 + 变更规模，可能漏检无关键字的转折",
                        "变更统计不含语义层面的架构变化",
                    ],
                )
                tp = TurningPoint(
                    commit=c["hash"],
                    message=c["message"],
                    change_stats={
                        "files_changed": c["files_changed"],
                        "insertions": c["insertions"],
                        "deletions": c["deletions"],
                    },
                    motivation_inference=motivation,
                    evidence=ev,
                )
                turning_points.append(tp)
                all_evidence.append(ev)

        # 3. 技术债时间线
        debt_items = self._trace_tech_debt(target)
        for item in debt_items:
            ev = Evidence(
                result=f"技术债标记 {item.marker}: {item.comment[:100]}",
                level=EvidenceLevel.OBSERVATION,
                provenance={
                    "repo": target,
                    "commit": item.commit,
                    "file": item.file,
                    "line": item.line,
                    "marker": item.marker,
                    "analysis": "tech_debt_tracking",
                },
                confidence=0.9,
                known_gaps=["注释仅是间接证据，需结合代码上下文确认债务性质"],
            )
            all_evidence.append(ev)

        # 概览 Evidence
        all_evidence.insert(0, Evidence(
            result=f"仓库演化叙事: {len(commits)} 次 commit, {len(turning_points)} 个转折点, {len(debt_items)} 条技术债",
            level=EvidenceLevel.DERIVATION,
            provenance={
                "repo": target,
                "analysis": "evolution_narrative_summary",
                "commit_count": len(commits),
            },
            confidence=0.9,
            known_gaps=[
                "叙事仅基于 git 静态分析，不含运行时行为变化",
                "无 --cc 选项，合并提交内容未展开",
            ],
        ))

        return {
            "target": target,
            "turning_points": [tp.to_dict() for tp in turning_points],
            "tech_debt_timeline": [d.to_dict() for d in debt_items],
            "evidence": all_evidence,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_commit_log_with_stats(self, repo: str) -> list[dict[str, Any]]:
        """获取 commit log + --stat 摘要。"""
        # 格式：hash|message|files_changed|insertions|deletions
        fmt = "%H%x01%s%x01"
        rc, out, _ = _run_git(
            ["log", "--no-merges", f"--format={fmt}", "--stat", "--", repo],
            repo,
        )
        if rc != 0 or not out:
            # 退化：仅取 hash + message
            rc, out, _ = _run_git(["log", "--no-merges", f"--format=%H%x01%s"], repo)
            if rc != 0 or not out:
                return []
            commits = []
            for line in out.strip().split("\n"):
                parts = line.split("\x01")
                if len(parts) >= 2:
                    commits.append({
                        "hash": parts[0],
                        "message": parts[1],
                        "files_changed": 0,
                        "insertions": 0,
                        "deletions": 0,
                    })
            return commits

        commits = []
        # 输出格式: 每个提交多行，第一行是 hash|message，后续是 stat 行
        blocks = re.split(r"(?m)^(?=[0-9a-f]{40}\x01)", out)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.split("\n")
            first = lines[0]
            parts = first.split("\x01")
            if len(parts) < 2:
                continue
            commit_hash = parts[0]
            message = parts[1] if len(parts) > 1 else ""

            # 解析 stat 行（最后一行通常是 " N files changed, M insertions(+), K deletions(-)"）
            files_changed = 0
            insertions = 0
            deletions = 0
            for line in lines[1:]:
                m = re.search(r"(\d+) files? changed", line)
                if m:
                    files_changed = int(m.group(1))
                m = re.search(r"(\d+) insertions?\(\+\)", line)
                if m:
                    insertions = int(m.group(1))
                m = re.search(r"(\d+) deletions?\(-\)", line)
                if m:
                    deletions = int(m.group(1))

            commits.append({
                "hash": commit_hash,
                "message": message,
                "files_changed": files_changed,
                "insertions": insertions,
                "deletions": deletions,
            })

        return commits

    @staticmethod
    def _is_turning_point(commit: dict[str, Any]) -> bool:
        """判断是否为转折点：commit message 含关键字 OR 变更规模大。"""
        msg_lower = commit["message"].lower()
        # 关键字匹配
        for kw in _TURNING_POINT_KEYWORDS:
            if kw in msg_lower:
                return True
        # 大规模变更：≥ 5 文件 或 ≥ 50 行增删
        if commit["files_changed"] >= 5 or (commit["insertions"] + commit["deletions"]) >= 50:
            return True
        return False

    @staticmethod
    def _infer_motivation(message: str) -> str:
        """从 commit message 推断重构动机（inference 级）。"""
        msg_lower = message.lower()
        for kw, label in _REFACTOR_MOTIVATIONS.items():
            if kw in msg_lower:
                return label
        return "未明确标注（可能为常规迭代）"

    def _trace_tech_debt(self, repo: str) -> list[TechDebtItem]:
        """追踪技术债（TODO/FIXME/XXX/HACK）在 HEAD 上的位置。"""
        items: list[TechDebtItem] = []
        # git grep 扫描当前 HEAD 上所有 TODO/FIXME 等
        for marker in _DEBT_MARKERS:
            rc, out, _ = _run_git(
                ["grep", "-n", "--line-number", "-I", "-e", marker, "HEAD"],
                repo,
            )
            if rc != 0 or not out:
                continue
            for line in out.strip().split("\n"):
                # 格式：file:line:content
                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue
                file_path = parts[0]
                try:
                    line_no = int(parts[1])
                except ValueError:
                    continue
                content = parts[2]

                # 获取该文件最后一次变更的 commit
                rc2, blame_out, _ = _run_git(
                    ["log", "-1", "--format=%H", "--", file_path],
                    repo,
                )
                commit_hash = blame_out.strip() if rc2 == 0 else "unknown"

                items.append(TechDebtItem(
                    commit=commit_hash,
                    file=file_path,
                    line=line_no,
                    marker=marker,
                    comment=content.strip()[:200],
                ))

        return items

    def _failopen_unknown(self, target: str, result: str) -> dict[str, Any]:
        ev = Evidence(
            result=result,
            level=EvidenceLevel.UNKNOWN,
            provenance={"target": target, "analysis": "evolution_narrative"},
            confidence=0.0,
            known_gaps=[
                "目标路径不是 git 仓库或不存在，无法生成演化叙事",
                "可改为对纯目录做结构分析，但当前实现仅支持 git 仓库",
            ],
        )
        return {
            "target": target,
            "turning_points": [],
            "tech_debt_timeline": [],
            "evidence": [ev],
        }


# ---------- 模块级入口 ----------

def generate_narrative(target: str) -> dict[str, Any]:
    """演化叙事生成的模块级入口。

    Args:
        target: git 仓库根路径

    Returns:
        见 EvolutionNarrator.generate
    """
    narrator = EvolutionNarrator()
    return narrator.generate(target)
