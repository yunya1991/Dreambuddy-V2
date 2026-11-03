# -*- coding: utf-8 -*-
"""多 Worker 并发调度(T-DSH-P1 P1-3)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P1·并行(多 Worker 并发) + 验收 V3
(3 个 Ticket 同时 live,任一 paused 不占 Worker 槽) + ADR-1(Router 无状态,
每轮从快照算分派) + ADR-3(paused/waitsForPerson 不占槽)。

定位: 组合层——ticket_state(四态) + ticket_router(单轮无状态分派) 之上
引入「槽位」视角: 仅 live 且绑 worker_id 的 Ticket 占槽;占用中的 Worker 从
花名册剔除后再走 P0 单轮分派。本模块仍无状态: active_tickets 快照由编排侧
每轮从 L0 recover(ticket_store),不占槽语义由状态机保证。

硬约束:
  HC-1 FAIL-OPEN: 坏输入 → None/空集,不抛错
  HC-2 开关 enable_worker_pool 默认 False
  不抢占: 占用中的 Worker 不被重复分派(越界即 unassigned)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .ticket_router import route_single_round

# 模块化开关(HC-2,默认 False)
POOL_SWITCH = "enable_worker_pool"

# 占槽状态: 仅 live(ADR-3: paused/waitsForPerson 不占槽;ended 槽由编排侧回收)
_OCCUPYING_STATE = "live"


def is_worker_pool_enabled(flags: Optional[Dict[str, Any]] = None) -> bool:
    """模块化开关读取(HC-2)。flags 非 dict / 缺键 → False(默认关)。"""
    try:
        if not isinstance(flags, dict):
            return False
        return bool(flags.get(POOL_SWITCH, False))
    except Exception:
        return False


def occupied_workers(tickets: Any) -> Set[str]:
    """从 Ticket 快照算占槽 Worker 集: 仅 live 且 worker_id 非空。坏输入 → 空集。"""
    try:
        if not isinstance(tickets, (list, tuple)):
            return set()
        out: Set[str] = set()
        for t in tickets:
            if not isinstance(t, dict):
                continue
            if t.get("state") != _OCCUPYING_STATE:
                continue
            wid = t.get("worker_id")
            if wid:
                out.add(str(wid))
        return out
    except Exception:
        return set()


def free_roster(roster: Any, tickets: Any) -> Dict[str, List[str]]:
    """花名册剔除占槽 Worker → 可分派空闲花名册。坏 roster → {}。"""
    try:
        if not isinstance(roster, dict):
            return {}
        occupied = occupied_workers(tickets)
        free: Dict[str, List[str]] = {}
        for role, workers in roster.items():
            if not isinstance(workers, (list, tuple)):
                continue
            free[str(role)] = [str(w) for w in workers if w and str(w) not in occupied]
        return free
    except Exception:
        return {}


def dispatch_concurrent(
    plan: Any,
    roster: Any,
    active_tickets: Any,
    completed_refs: Optional[Set[str]] = None,
) -> Optional[Dict[str, Any]]:
    """槽位感知的并发分派: 空闲花名册走 P0 单轮分派,附加占槽快照。

    无空闲 Worker 的 Ticket → unassigned(reason=no_free_worker),不抢占。
    非法 plan → None(FAIL-OPEN,与 route_single_round 同契约)。
    """
    try:
        if not isinstance(plan, dict) or not isinstance(plan.get("tickets"), list):
            return None
        tickets = active_tickets if isinstance(active_tickets, (list, tuple)) else []
        free = free_roster(roster, tickets)
        routed = route_single_round(plan, free, completed_refs=completed_refs)
        if routed is None:
            return None
        # 统一无 Worker 原因语义: P0 的 no_worker_for_role 在槽位语境下即无空闲
        for item in routed["unassigned"]:
            if item.get("reason") == "no_worker_for_role":
                item["reason"] = "no_free_worker"
        routed["occupied"] = sorted(occupied_workers(tickets))
        return routed
    except Exception:
        return None
