# -*- coding: utf-8 -*-
"""裁决事件 → Ticket 唤醒桥（P2.5 运行时接线）。

链路：
  前端 / 异步 job 写入 L0 `verdict.updated` 事件
    → 本桥把事件规整为 resume trigger（kind=waiting_verdict）
    → ticket_resume.resume_on_event 命中 paused(waiting_verdict) Ticket
    → paused → live，回写 L0。

硬约束：
  HC-1 FAIL-OPEN：坏输入/非裁决事件 → None/[]，不抛错
  只认 `verdict.updated`；其它事件不在此桥处理
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .ticket_resume import resume_on_event

VERDICT_EVENT_TYPE = "verdict.updated"
WAKE_KIND = "waiting_verdict"


def to_resume_trigger(event: Any) -> Optional[Dict[str, Any]]:
    """`verdict.updated` 事件 → resume trigger；非法/非裁决事件 → None。

    trigger 只按 kind + source 唤醒，不透传 trace_id，避免同 trace 的
    无关事件误唤醒（精确唤醒依赖 Ticket 的 waiting_on.kinds）。
    """
    try:
        if not isinstance(event, dict) or event.get("type") != VERDICT_EVENT_TYPE:
            return None
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return None
        task_id = payload.get("task_id")
        verdict = payload.get("verdict")
        if not task_id or verdict not in (
            "supported",
            "contradicted",
            "inconclusive",
            "needs_human",
        ):
            return None
        verdict_id = payload.get("verdict_id") or "verdict"
        return {
            "trigger_id": str(verdict_id),
            "source": "verdict",
            "kind": WAKE_KIND,
            "payload_ref": "verdict:{}".format(verdict_id),
            "ts": event.get("ts"),
        }
    except Exception:
        return None


def apply_verdict_event(
    store: Any,
    event: Any,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """把一条裁决事件应用到 Ticket 存储；非裁决事件返回 []。"""
    trigger = to_resume_trigger(event)
    if trigger is None:
        return []
    return resume_on_event(store, trigger, now=now)
