# -*- coding: utf-8 -*-
"""Ticket 四态状态机(T-DSH-P0 D2)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-3 修订——Ticket 状态机收敛为
live / paused / waitsForPerson / ended 四态(官方 8 态合并);paused 子因
(G3 定稿): waiting_event(等外部事件)/waiting_job(等异步工具 submit-poll
完成)/waiting_person(等人)——异步等待必须走事件唤醒,禁止忙轮询。

定位: 纯函数状态机(状态本体落 L0 存储,ADR-2: DSH 内禁第二套权威状态;
本模块只做合法性判定与迁移留痕,不持存储)。

硬约束:
  paused 必须携带合法子因;ended 终态不可转出
  paused/waitsForPerson 释放 worker_id(Worker 不占槽,并行度关键)
  FAIL-OPEN: 非法迁移/坏输入 → None,不改原 Ticket
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

TICKET_STATES = ("live", "paused", "waitsForPerson", "ended")
PAUSED_REASONS = ("waiting_event", "waiting_job", "waiting_person")

# 合法迁移表: from → 允许转入的 to 集合
_TRANSITIONS = {
    "live": {"paused", "waitsForPerson", "ended"},
    "paused": {"live", "ended"},
    "waitsForPerson": {"live", "ended"},
    "ended": set(),  # 终态
}

# 释放 Worker 槽的状态(ADR-3: 无论 paused 还是 waitsForPerson,Worker 不占槽)
_RELEASE_WORKER_STATES = {"paused", "waitsForPerson"}


def create_ticket(ticket_id: Any, trace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """创建 live 态 Ticket 记录。非法 id → None(FAIL-OPEN)。"""
    try:
        if not ticket_id:
            return None
        return {
            "ticket_id": str(ticket_id),
            "state": "live",
            "paused_reason": None,
            "worker_id": None,
            "trace_id": trace_id,
            "history": [],
        }
    except Exception:
        return None


def transition_ticket(
    ticket: Any,
    to_state: Any,
    paused_reason: Optional[str] = None,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Ticket 状态迁移(纯函数,返回新记录,不改原对象)。

    非法迁移(终态转出/paused 缺子因/未知态/坏输入) → None(FAIL-OPEN)。
    合法迁移: history 追加 {from, to, reason, ts};paused/waitsForPerson 释放
    worker_id;回 live 清 paused_reason。
    """
    try:
        if not isinstance(ticket, dict):
            return None
        from_state = ticket.get("state")
        if from_state not in _TRANSITIONS:
            return None
        if to_state not in TICKET_STATES:
            return None
        if to_state not in _TRANSITIONS[from_state]:
            return None
        if to_state == "paused" and paused_reason not in PAUSED_REASONS:
            return None

        out = dict(ticket)
        out["history"] = list(ticket.get("history") or [])
        out["history"].append(
            {
                "from": from_state,
                "to": to_state,
                "reason": paused_reason if to_state == "paused" else None,
                "ts": float(now) if now is not None else time.time(),
            }
        )
        out["state"] = to_state
        out["paused_reason"] = paused_reason if to_state == "paused" else None
        if to_state in _RELEASE_WORKER_STATES:
            out["worker_id"] = None  # 释放 Worker 槽
        return out
    except Exception:
        return None
