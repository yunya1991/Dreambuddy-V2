# -*- coding: utf-8 -*-
"""P0-D3D: 决策派发器。只消费 adopted/未过期/哈希一致的 DecisionRecord。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.decision_record import DecisionRecord, is_consumable


@dataclass(frozen=True)
class ReworkTask:
    task_id: str
    ticket_id: str
    decision_id: str
    task_index: int
    title: str
    source: str = "brainstorm"
    payload: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", dict(self.payload or {}))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "ticket_id": self.ticket_id,
            "decision_id": self.decision_id,
            "task_index": self.task_index,
            "title": self.title,
            "source": self.source,
            "payload": dict(self.payload),
        }

    def to_inbox_record(self) -> Dict[str, Any]:
        """转换为 WorkerLauncher 可消费的 inbox assignment。"""
        payload = dict(self.payload)
        mandate = payload.get("mandate")
        if not isinstance(mandate, dict) or not mandate:
            mandate = {
                "goal": self.title or str(payload.get("objective") or ""),
                "acceptance": str(payload.get("acceptance") or self.title or ""),
            }
        return {
            "ticket_id": self.task_id,
            "external_ref": self.ticket_id,
            "role": str(payload.get("role") or "research"),
            "mandate": mandate,
            "source": self.source,
            "decision_id": self.decision_id,
            "task_index": self.task_index,
        }


def dispatch_tasks(
    decision: Any,
    ticket_id: str,
    tasks: Any,
    now: Optional[float] = None,
) -> Optional[List[ReworkTask]]:
    """只有 adopted 且可消费的记录才能派发；否则返回 None。"""
    if not isinstance(decision, DecisionRecord):
        return None
    if not is_consumable(decision, now=float(now or 0.0)):
        return None
    if not isinstance(tasks, (list, tuple)):
        return None
    out: List[ReworkTask] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            return None
        out.append(
            ReworkTask(
                task_id=f"{decision.decision_id}-T{index + 1}",
                ticket_id=str(ticket_id),
                decision_id=decision.decision_id,
                task_index=index,
                title=str(task.get("title") or ""),
                payload=dict(task),
            )
        )
    return out


def enqueue_tasks(tasks: Any, root: str) -> int:
    """把 ReworkTask 追加到 WorkerLauncher inbox；返回成功条数（FAIL-OPEN）。"""
    if not isinstance(tasks, (list, tuple)):
        return 0
    try:
        from core.router_loop import JsonlInboxSink

        sink = JsonlInboxSink(root)
    except Exception:
        return 0
    count = 0
    for task in tasks:
        if not isinstance(task, ReworkTask):
            continue
        if sink.append(task.to_inbox_record()):
            count += 1
    return count
