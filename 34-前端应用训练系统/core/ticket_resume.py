# -*- coding: utf-8 -*-
"""会话级离线续跑(T-DSH-P3 P3-2)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P3·常驻退出判据(重启后 Ticket 可续跑)
+ ADR-3(paused 子因 waiting_event/waiting_job 必须走事件唤醒,禁止忙轮询)
+ ADR-2(权威状态在 L0;本模块不持副本,每次经 ticket_store 读写)
+ ADR-3 修订(续跑后 thread_id 亲和直通锚点可重建) + H1 FAIL-OPEN。

定位: 重启后从 L0 恢复 paused(waiting_event/waiting_job) Ticket,事件到达时
判定唤醒条件(thread_id 直通 或 waiting_on.kinds+source 命中),命中即
paused→live 并回写 L0(latest-wins),可选重建亲和绑定。

唤醒契约: Ticket 挂起时由编排侧写入 ticket["waiting_on"] =
  {"kinds": [kind...], "source": 可选限定来源};ticket["thread_id"] 存在时
  同 thread 事件直接唤醒(直通语义)。

硬约束:
  HC-1 FAIL-OPEN: 坏输入/坏行/IO 异常 → []/False,不抛错
  唤醒即留痕: 经 ticket_state.transition_ticket 迁移,history 可追溯
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .ticket_state import transition_ticket
from .ticket_store import recover_tickets, save_ticket

# 可被事件唤醒的 paused 子因(ADR-3;waiting_person 等人,不走事件唤醒)
RESUMABLE_REASONS = ("waiting_event", "waiting_job")


def recover_resumable(store: Any) -> List[Dict[str, Any]]:
    """从 L0 恢复全部可续跑 Ticket(paused + waiting_event/waiting_job)。"""
    try:
        tickets = recover_tickets(store)
        return [
            t
            for t in tickets.values()
            if t.get("state") == "paused" and t.get("paused_reason") in RESUMABLE_REASONS
        ]
    except Exception:
        return []


def matches_wakeup(ticket: Any, trigger: Any) -> bool:
    """事件是否命中 Ticket 唤醒条件。

    命中路径(任一):
      ① thread 直通: trigger.thread_id == ticket.thread_id(非空)
      ② 等待声明: trigger.kind ∈ ticket.waiting_on.kinds,且 waiting_on.source
         存在时 trigger.source 必须一致
    仅 paused(waiting_event/waiting_job) 可唤醒;坏输入 → False。
    """
    try:
        if not isinstance(ticket, dict) or not isinstance(trigger, dict):
            return False
        if ticket.get("state") != "paused":
            return False
        if ticket.get("paused_reason") not in RESUMABLE_REASONS:
            return False
        thread_id = ticket.get("thread_id")
        if thread_id and trigger.get("thread_id") == thread_id:
            return True
        waiting_on = ticket.get("waiting_on") or {}
        kinds = waiting_on.get("kinds") or []
        if trigger.get("kind") and trigger["kind"] in kinds:
            source = waiting_on.get("source")
            if source is None or trigger.get("source") == source:
                return True
        return False
    except Exception:
        return False


def resume_on_event(
    store: Any,
    trigger: Any,
    now: Optional[float] = None,
    affinity: Optional[Any] = None,
    worker_id: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """事件唤醒: 从 L0 找命中的可续跑 Ticket → paused→live → 回写 L0。

    affinity + worker_id 同给时重建直通锚点(ADR-3 修订);仅 affinity 无
    worker 不绑(空槽直通无意义)。返回被唤醒的 Ticket 列表;坏输入 → []。
    """
    try:
        if store is None or not isinstance(trigger, dict):
            return []
        resumed: List[Dict[str, Any]] = []
        for ticket in recover_resumable(store):
            if not matches_wakeup(ticket, trigger):
                continue
            back = transition_ticket(ticket, "live", now=now)
            if back is None:
                continue
            if worker_id:
                back["worker_id"] = str(worker_id)
            if save_ticket(back, store) is None:
                continue
            if affinity is not None and worker_id and back.get("thread_id"):
                try:
                    affinity.bind(back["thread_id"], worker_id, back["ticket_id"], now=now)
                except Exception:
                    pass  # 亲和重建失败不阻塞续跑(H1)
            resumed.append(back)
        return resumed
    except Exception:
        return []
