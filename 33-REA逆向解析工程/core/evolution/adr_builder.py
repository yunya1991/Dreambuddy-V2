"""ADR Builder — T-G15 模式 → ADR 草案 → L3 评审入口 + L2 任务拆解

SPEC-33-G §2.11.5 / §2.12.3：
  - 模式候选门槛：≥5 条同类 Case 且跨 ≥3 次迭代；背景 Evidence ≥2
  - ADR 必含：背景与触发证据 / 候选方案 ≥2 / PoE 取舍 / 影响面 / 回滚与灰度 / L2 任务清单
  - L3 出口只出 ADR + SPEC 草案，不写代码；L2 任务必须落在 L2 边界
  - 评审入口：AI 评审 + 人终审两步，缺一不得 approved

工程约束：纯标准库；评审队列 append-only 语义 + 原子重写；分级复用 T-G14 分类器。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .research_pipeline import ChangeClassifier

REVIEWERS = ("ai_reviewer", "human_reviewer")
OPEN_STATUSES = {"pending_review", "awaiting_human"}
_ADR_FILE = re.compile(r"^ADR-(\d+)")


class AdrError(ValueError):
    """ADR 契约违约（硬拒绝）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AdrError(message)


def _slugify(title: str) -> str:
    slug = re.sub(r"[\s/\\:*?\"<>|]+", "-", str(title or "").strip())
    slug = slug.strip("-")
    return slug or "untitled"


class AdrBuilder:
    def __init__(
        self,
        root: str | Path,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        classifier: Optional[ChangeClassifier] = None,
        min_cases: int = 5,
        min_iterations: int = 3,
        min_evidence: int = 2,
    ):
        self.root = Path(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.classifier = classifier or ChangeClassifier()
        self.min_cases = int(min_cases)
        self.min_iterations = int(min_iterations)
        self.min_evidence = int(min_evidence)

    # ---------------------------------------------------------------- 构建

    def build(
        self,
        *,
        pattern: Dict[str, Any],
        title: str,
        options: List[Dict[str, Any]],
        impact: str,
        rollback: str,
        l2_tasks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        pattern = dict(pattern or {})
        self._validate_pattern(pattern)

        options = list(options or [])
        _require(
            len(options) >= 2,
            f"ADR 候选方案必须 ≥2（当前 {len(options)}），来自双链脑暴",
        )
        for option in options:
            _require(
                bool(str(option.get("name") or "").strip())
                and bool(str(option.get("description") or "").strip()),
                "候选方案必须包含 name 与 description",
            )

        _require(bool(str(impact or "").strip()), "ADR 必须声明影响面")
        _require(bool(str(rollback or "").strip()), "ADR 必须声明回滚与灰度策略")

        tasks = [self._validate_task(task) for task in (l2_tasks or [])]
        _require(bool(tasks), "ADR 必须拆出 ≥1 个 L2 任务（L2 任务拆解）")

        adr_id = self._next_adr_id()
        path = self.root / f"{adr_id}-{_slugify(title)}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self._render(
                adr_id=adr_id,
                title=title,
                pattern=pattern,
                options=options,
                impact=impact,
                rollback=rollback,
                tasks=tasks,
            ),
            encoding="utf-8",
        )

        entry = {
            "adr_id": adr_id,
            "title": title,
            "path": str(path),
            "status": "pending_review",
            "required_reviewers": list(REVIEWERS),
            "reviews": [],
            "created_at": self._now().isoformat(),
        }
        self._append_entry(entry)
        return {
            "adr_id": adr_id,
            "title": title,
            "path": str(path),
            "status": entry["status"],
            "review_entry": entry,
            "l2_tasks": tasks,
        }

    # ---------------------------------------------------------------- 评审

    def record_review(
        self,
        adr_id: str,
        *,
        reviewer: str,
        decision: str,
        notes: str = "",
    ) -> Dict[str, Any]:
        _require(reviewer in REVIEWERS, f"未知评审角色 {reviewer}（仅 {list(REVIEWERS)}）")
        _require(
            str(decision or "").strip() in {"approve", "reject"},
            "decision 必须是 approve/reject",
        )
        entries = self._read_entries()
        target = next((item for item in entries if item.get("adr_id") == adr_id), None)
        _require(target is not None, f"ADR {adr_id} 不在评审队列")
        status = str(target.get("status") or "")
        _require(status in OPEN_STATUSES, f"ADR {adr_id} 已终结（{status}），不可重复评审")

        reviews = list(target.get("reviews") or [])
        if reviewer == "human_reviewer":
            _require(
                any(
                    item.get("reviewer") == "ai_reviewer" and item.get("decision") == "approve"
                    for item in reviews
                ),
                "L3 评审必须 AI 评审通过后再人终审，不得跳过 AI 评审",
            )

        reviews.append(
            {
                "reviewer": reviewer,
                "decision": decision,
                "notes": notes or "",
                "reviewed_at": self._now().isoformat(),
            }
        )
        target["reviews"] = reviews

        if decision == "reject":
            target["status"] = "rejected"
        elif reviewer == "ai_reviewer":
            target["status"] = "awaiting_human"
        else:
            target["status"] = "approved"

        self._write_entries(entries)
        return dict(target)

    def pending_reviews(self) -> List[Dict[str, Any]]:
        return [item for item in self._read_entries() if item.get("status") in OPEN_STATUSES]

    # ---------------------------------------------------------------- 校验

    def _validate_pattern(self, pattern: Dict[str, Any]) -> None:
        cases = list(pattern.get("cases") or [])
        _require(
            len(cases) >= self.min_cases,
            f"模式候选需 ≥{self.min_cases} 条同类 Case（当前 {len(cases)}）",
        )
        iterations = {
            str(case.get("iteration_id") or "").strip()
            for case in cases
            if str(case.get("iteration_id") or "").strip()
        }
        _require(
            len(iterations) >= self.min_iterations,
            f"模式候选需跨 ≥{self.min_iterations} 次迭代（当前 {len(iterations)}）",
        )
        evidence = [ref for ref in (pattern.get("evidence_refs") or []) if str(ref).strip()]
        _require(
            len(evidence) >= self.min_evidence,
            f"ADR 背景 Evidence 不足：需 ≥{self.min_evidence} 条（当前 {len(evidence)}）",
        )
        _require(bool(str(pattern.get("pattern_id") or "").strip()), "pattern_id is required")

    def _validate_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task = dict(task or {})
        task_id = str(task.get("task_id") or "").strip()
        _require(bool(task_id), "L2 任务缺 task_id")
        _require(bool(str(task.get("title") or "").strip()), f"L2 任务 {task_id} 缺 title")
        _require(
            bool(str(task.get("acceptance") or "").strip()),
            f"L2 任务 {task_id} 缺 acceptance（验收）",
        )
        files = [str(path).strip() for path in (task.get("files") or []) if str(path).strip()]
        _require(bool(files), f"L2 任务 {task_id} 缺 files")

        classified = self.classifier.classify(
            files=files,
            lines_changed=task.get("lines_changed") or 0,
            changes_contract=bool(task.get("changes_contract")),
            changes_schema=bool(task.get("changes_schema")),
            changes_dependency_direction=bool(task.get("changes_dependency_direction")),
            adds_dependency=bool(task.get("adds_dependency")),
            stateful=bool(task.get("stateful")),
        )
        _require(
            classified["level"] == "L2",
            f"L2 任务 {task_id} 超出 L2 边界（判定 {classified['level']}："
            f"{'；'.join(classified['reasons']) or '非单模块小改'}），须继续拆分",
        )
        declared_module = str(task.get("module") or "").strip()
        if declared_module:
            _require(
                declared_module == classified["module"],
                f"L2 任务 {task_id} 模块声明 {declared_module} 与文件模块 {classified['module']} 不一致",
            )
        task["files"] = files
        task["module"] = classified["module"]
        return task

    # ---------------------------------------------------------------- 渲染

    def _render(
        self,
        *,
        adr_id: str,
        title: str,
        pattern: Dict[str, Any],
        options: List[Dict[str, Any]],
        impact: str,
        rollback: str,
        tasks: List[Dict[str, Any]],
    ) -> str:
        evidence = [str(ref) for ref in (pattern.get("evidence_refs") or []) if str(ref).strip()]
        cases = list(pattern.get("cases") or [])
        lines = [
            f"# {adr_id}: {title}",
            "",
            f"> 状态：proposed ｜ 日期：{self._now().date().isoformat()} ｜ 来源模式：{pattern.get('pattern_id')}",
            "> 归属：SPEC-33-G §2.11.5（L3 只出 ADR + SPEC 草案）",
            "",
            "## 1 背景与触发证据",
            "",
            f"- 模式摘要：{pattern.get('summary') or '-'}",
            f"- 模块：{pattern.get('module') or '-'} ｜ 变更类型：{pattern.get('change_type') or '-'}"
            f" ｜ 缺陷类型：{pattern.get('defect_type') or '-'}",
            f"- 案例数：{len(cases)}（跨迭代 {len({str(c.get('iteration_id')) for c in cases})} 次）",
            f"- Evidence：{', '.join(evidence)}",
            "",
            "## 2 候选方案（≥2）",
            "",
            "| 方案 | 说明 |",
            "|---|---|",
        ]
        for option in options:
            lines.append(f"| {option.get('name')} | {option.get('description')} |")

        lines.extend(["", "## 3 取舍理由与 PoE 评分", "", "| 方案 | PoE 评分 |", "|---|---|"])
        for option in options:
            score = option.get("poe_score")
            lines.append(f"| {option.get('name')} | {score if score is not None else '未评分'} |")

        lines.extend(
            [
                "",
                "## 4 影响面",
                "",
                str(impact),
                "",
                "## 5 回滚与灰度策略",
                "",
                str(rollback),
                "",
                "## 6 需要拆成的 L2 任务清单",
                "",
                "| 任务 | 标题 | 模块 | 文件 | 行数 | 验收 |",
                "|---|---|---|---|---|---|",
            ]
        )
        for task in tasks:
            lines.append(
                f"| {task.get('task_id')} | {task.get('title')} | {task.get('module')} | "
                f"{', '.join(task.get('files') or [])} | {task.get('lines_changed') or 0} | "
                f"{task.get('acceptance')} |"
            )
        lines.append("")
        return "\n".join(lines)

    # ---------------------------------------------------------------- 存储

    def _next_adr_id(self) -> str:
        numbers = [0]
        if self.root.is_dir():
            for path in self.root.glob("ADR-*.md"):
                matched = _ADR_FILE.match(path.name)
                if matched:
                    numbers.append(int(matched.group(1)))
        return f"ADR-{max(numbers) + 1:03d}"

    def _queue_path(self) -> Path:
        return self.root / "review_queue.jsonl"

    def _append_entry(self, entry: Dict[str, Any]) -> None:
        path = self._queue_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    def _read_entries(self) -> List[Dict[str, Any]]:
        path = self._queue_path()
        if not path.is_file():
            return []
        entries: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                entries.append(item)
        return entries

    def _write_entries(self, entries: List[Dict[str, Any]]) -> None:
        path = self._queue_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        body = "".join(
            json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n" for entry in entries
        )
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)

    def _now(self) -> datetime:
        return self.clock()
