# -*- coding: utf-8 -*-
"""Router 单轮分派(T-DSH-P0 D1)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-1(Router 常驻但无状态——每次 pass
从输入快照算分派,不持任务状态,可随时重启) + ADR-4(Router 只感知能力标签,
不感知全量工具;Worker 角色→能力标签唯一载体在 47 registry) + SACG_A SPEC
§4.2(dispatch: 并行线→多 Worker,顺序依赖→串行 Ticket)。

定位: 输入 Ticket 草案集(okr_ticket_bridge 产出) + Worker 花名册
{role: [worker_id,...]},单轮输出 {assignments, unassigned, deferred}。
Router 不做业务决策(业务判定在 A 层 verify 与 45 门禁),只做分派。

硬约束:
  无状态(ADR-1): 纯函数,同输入同输出,不改输入,不跨调用记忆
  HC-2 开关 enable_superagent_router 默认 False
  FAIL-OPEN: 非法计划 → None;坏 Ticket 条目跳过;无可用 Worker → unassigned
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

# 模块化开关(默认 False)
ROUTER_SWITCH = "enable_superagent_router"


def is_router_enabled(flags: Optional[Dict[str, Any]] = None) -> bool:
    """模块化开关读取。flags 非 dict / 缺键 → False(默认关)。"""
    try:
        if not isinstance(flags, dict):
            return False
        return bool(flags.get(ROUTER_SWITCH, False))
    except Exception:
        return False


def route_single_round(
    plan: Any,
    workers: Any,
    completed_refs: Optional[Set[str]] = None,
) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """单轮分派: 一个 pass 算完本轮分派计划(ADR-1 无状态)。

    参数:
      plan           okr_ticket_bridge.translate_plan_to_tickets 产出
                     {draft, tickets:[{external_ref, mandate, route_hint}],
                      dispatch:{mode, depends_on}}
      workers        花名册 {role: [worker_id, ...]}(能力标签由 47 registry 承载,
                     Router 只感知角色标签)
      completed_refs 已完成 external_ref 集合(依赖闸判定用;调用方从 L0 快照读)

    返回 {assignments:[{external_ref, role, worker_id, mandate}],
          unassigned:[{external_ref, reason}],   # 无可用 Worker
          deferred:[{external_ref, reason}]}     # 依赖未满足,下轮再派
    非法 plan → None(FAIL-OPEN)。
    """
    try:
        if not isinstance(plan, dict):
            return None
        tickets = plan.get("tickets")
        if not isinstance(tickets, list):
            return None
        if not isinstance(workers, dict):
            workers = {}
        completed = set(completed_refs or set())
        dispatch = plan.get("dispatch") or {}
        depends_on = dispatch.get("depends_on") or {}
        if not isinstance(depends_on, dict):
            depends_on = {}

        known_refs = {
            str(t.get("external_ref"))
            for t in tickets
            if isinstance(t, dict) and t.get("external_ref")
        }

        assignments: List[Dict[str, Any]] = []
        unassigned: List[Dict[str, Any]] = []
        deferred: List[Dict[str, Any]] = []
        role_cursor: Dict[str, int] = {}  # 本轮内轮询游标(单轮局部,非跨轮状态)

        for ticket in tickets:
            if not isinstance(ticket, dict) or not ticket.get("external_ref"):
                continue  # 坏条目跳过(FAIL-OPEN)
            ref = str(ticket["external_ref"])

            # 依赖闸: 仅统计指向本 Ticket 集内的依赖;外部锚点视同已满足
            deps = [d for d in (depends_on.get(ref) or []) if d in known_refs]
            if any(d not in completed for d in deps):
                deferred.append({"external_ref": ref, "reason": "dependency_unmet"})
                continue

            hint = ticket.get("route_hint") or {}
            role = hint.get("role")
            if not role:
                role = next(iter(workers.keys()), None)  # 无角色提示→首个可用角色
            roster = workers.get(role) or []
            if not roster:
                unassigned.append({"external_ref": ref, "reason": "no_worker_for_role"})
                continue

            cursor = role_cursor.get(role, 0)
            worker_id = roster[cursor % len(roster)]
            role_cursor[role] = cursor + 1
            assignments.append(
                {
                    "external_ref": ref,
                    "role": role,
                    "worker_id": worker_id,
                    "mandate": ticket.get("mandate"),
                }
            )

        return {"assignments": assignments, "unassigned": unassigned, "deferred": deferred}
    except Exception:
        return None
