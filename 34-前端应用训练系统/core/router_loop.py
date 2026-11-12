# -*- coding: utf-8 -*-
"""Router 常驻循环单轮 pass(T-DSH-P0 D2a)。

依据: DESIGN-P0-D2-ROUTER-LOOP v0.1 §3.2/§4.1 + DESIGN-DSH-ARCH-UPGRADE v0.2
ADR-1(Router 常驻但无状态: 每轮从 L0 读快照、算分派、写回,可随时重启) +
ADR-2(状态单一事实源 = L0) + ADR-3(paused/waitsForPerson 不占槽) +
ADR-7(trace_id 贯穿) + H1/H2(FAIL-OPEN / 开关默认关)。

定位: 编排层。本身不做分派算法——快照读 ticket_store、唤醒走 ticket_resume、
槽位分派走 worker_pool/ticket_router、状态迁移走 ticket_state。本模块只负责
「一次 tick 的执行顺序 + 幂等闸 + shadow 闸 + 观测摘要」。

八步(§3.2): 闸门 → 快照 → 对账(只读) → 事件唤醒 → 物化 → 分派 → 提交 → 观测。

硬约束:
  HC-1 FAIL-OPEN: 任何异常 → {ok:False, degraded:True, reason},绝不抛错
  HC-2 开关 enable_router_loop 默认 False(另需 enable_superagent_router /
       enable_ticket_store);关断时不产生任何读写
  无状态: 不在进程内维护 Ticket 权威副本;每轮 recover_tickets 读 L0
  shadow: True 时只算不写(不物化/不写 L0/不投递),输出 would_assignments
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set

from .thread_affinity import is_affinity_enabled
from .ticket_resume import resume_on_event
from .ticket_router import is_router_enabled, route_single_round
from .ticket_state import create_ticket
from .ticket_store import is_ticket_store_enabled, recover_tickets, save_ticket
from .worker_pool import dispatch_concurrent, is_worker_pool_enabled
from .worker_receipts import apply_receipts

# 模块化开关(HC-2,默认 False)
LOOP_SWITCH = "enable_router_loop"

# 投递箱相对 L0 root 的路径(与 ticket_store 同域)
_INBOX_REL_PATH = os.path.join("34-前端应用训练系统", "dsh_worker_inbox.jsonl")


def is_loop_enabled(flags: Optional[Dict[str, Any]] = None) -> bool:
    """模块化开关读取(HC-2)。flags 非 dict / 缺键 → False(默认关)。"""
    try:
        if not isinstance(flags, dict):
            return False
        return bool(flags.get(LOOP_SWITCH, False))
    except Exception:
        return False


class JsonlInboxSink:
    """worker inbox 投递(append-only jsonl)。写失败 → False(FAIL-OPEN)。"""

    def __init__(self, root: str) -> None:
        self.path = os.path.join(str(root), _INBOX_REL_PATH)

    def __call__(self, assignment: Dict[str, Any]) -> bool:
        return self.append(assignment)

    def append(self, assignment: Dict[str, Any]) -> bool:
        try:
            if not isinstance(assignment, dict):
                return False
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            import json  # 延迟导入: 仅投递时需要

            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(assignment, ensure_ascii=False) + "\n")
            return True
        except Exception:
            return False


class PassStats:
    """进程内 pass 摘要环形缓冲(诊断用,非权威状态,可丢)。"""

    def __init__(self, max_ring: int = 20) -> None:
        try:
            self._max = max(1, int(max_ring))
        except (TypeError, ValueError):
            self._max = 20
        self.passes = 0
        self.degraded_count = 0
        self.consecutive_degraded = 0
        self.last_pass: Optional[Dict[str, Any]] = None
        self._ring: List[Dict[str, Any]] = []

    def record(self, summary: Dict[str, Any]) -> None:
        try:
            self.passes += 1
            self.last_pass = summary
            if summary.get("degraded"):
                self.degraded_count += 1
                self.consecutive_degraded += 1
            else:
                self.consecutive_degraded = 0
            self._ring.append(summary)
            if len(self._ring) > self._max:
                del self._ring[: len(self._ring) - self._max]
        except Exception:
            return

    def snapshot(self) -> Dict[str, Any]:
        try:
            return {
                "passes": self.passes,
                "degraded_count": self.degraded_count,
                "consecutive_degraded": self.consecutive_degraded,
                "last_pass": self.last_pass,
                "ring": list(self._ring),
            }
        except Exception:
            return {"passes": 0, "ring": []}


def _count_states(tickets: Any) -> Dict[str, int]:
    counts = {"total": 0, "live": 0, "paused": 0, "waitsForPerson": 0, "ended": 0}
    try:
        for t in tickets:
            if not isinstance(t, dict):
                continue
            counts["total"] += 1
            state = t.get("state")
            if state in counts:
                counts[state] += 1
    except Exception:
        return counts
    return counts


def _find_drift(tickets: Any) -> List[Dict[str, str]]:
    """对账(只读): live 但未绑 Worker 的漂移项。不改状态(Watchdog 职责在 P2)。"""
    drift: List[Dict[str, str]] = []
    try:
        for t in tickets:
            if not isinstance(t, dict):
                continue
            if t.get("state") == "live" and not t.get("worker_id"):
                drift.append(
                    {"ticket_id": str(t.get("ticket_id")), "reason": "live_without_worker"}
                )
    except Exception:
        return drift
    return drift


def _degraded(
    pass_id: str,
    reason: str,
    stats: Optional[PassStats],
    shadow: bool,
) -> Dict[str, Any]:
    summary = {
        "ok": False,
        "degraded": True,
        "pass_id": pass_id,
        "reason": reason,
        "shadow": bool(shadow),
        "error": reason,
    }
    if stats is not None:
        stats.record(summary)
    return summary


def run_pass(
    store: Any,
    roster: Optional[Dict[str, List[str]]] = None,
    affinity: Optional[Any] = None,
    triggers: Optional[Any] = None,
    plan: Optional[Any] = None,
    completed_refs: Optional[Set[str]] = None,
    sink: Optional[Callable[[Dict[str, Any]], bool]] = None,
    flags: Optional[Dict[str, Any]] = None,
    shadow: bool = True,
    now: Optional[float] = None,
    gate: Optional[Callable[[Dict[str, Any]], bool]] = None,
    stats: Optional[PassStats] = None,
) -> Dict[str, Any]:
    """执行一次 pass(§3.2 八步)。任何异常 → degraded,不抛错。"""
    started = time.time()
    pass_id = "rp-%s" % uuid.uuid4().hex[:12]
    try:
        # ① 闸门(H2 默认关;总闸门由调用方 DSH_ENABLE_UPGRADE 控制)
        if not is_loop_enabled(flags):
            return _degraded(pass_id, "loop_disabled", stats, shadow)
        if not is_router_enabled(flags):
            return _degraded(pass_id, "router_disabled", stats, shadow)
        if not is_ticket_store_enabled(flags):
            return _degraded(pass_id, "store_unavailable", stats, shadow)
        if store is None or not hasattr(store, "read_all"):
            return _degraded(pass_id, "store_unavailable", stats, shadow)

        # ② 快照(ADR-2: 每轮从 L0 读,进程内不持权威副本)
        tickets = recover_tickets(store)  # {ticket_id: record}

        # ②b 回执消费(R14): Worker 结果 → Ticket 状态迁移,是 completed_refs
        # 的可持续来源;shadow 只算不写 → 不消费;异常 FAIL-OPEN(按旧状态继续)
        receipt_result: Dict[str, Any] = {"applied": [], "ignored": 0}
        if not shadow:
            try:
                receipt_result = apply_receipts(tickets, store, now=now)
            except Exception:  # noqa: BLE001
                receipt_result = {"applied": [], "ignored": 0}

        # 物化前快照: external_ref → 已存在 Ticket(幂等闸依据;回执生效后状态)
        pre_ref_tickets = {
            str(t["external_ref"]): t for t in tickets.values() if t.get("external_ref")
        }
        snapshot = _count_states(tickets.values())

        # ③ 对账(只读,不改状态)
        drift = _find_drift(tickets.values())

        # ④ 事件唤醒(paused waiting_event/waiting_job → live)
        resumed: List[Dict[str, Any]] = []
        use_affinity = is_affinity_enabled(flags)
        if triggers:
            trigs = triggers if isinstance(triggers, (list, tuple)) else [triggers]
            for trig in trigs:
                for back in resume_on_event(
                    store, trig, now=now, affinity=affinity if use_affinity else None
                ):
                    resumed.append(
                        {
                            "ticket_id": back.get("ticket_id"),
                            "thread_id": back.get("thread_id"),
                        }
                    )
                    tickets[str(back.get("ticket_id"))] = back

        # ⑤ 物化(草案 → L0 Ticket;双门 + shadow 闸)
        materialized: List[Dict[str, Any]] = []
        plan_tickets = plan.get("tickets") if isinstance(plan, dict) else None
        if isinstance(plan_tickets, list) and not shadow:
            allow = True
            if gate is not None:
                try:
                    allow = bool(gate(plan))
                except Exception:
                    allow = False  # 门异常 → 不物化(FAIL-OPEN 的保守侧)
            if allow:
                ts = float(now) if now is not None else time.time()
                for item in plan_tickets:
                    if not isinstance(item, dict) or not item.get("external_ref"):
                        continue
                    ref = str(item["external_ref"])
                    ticket_id = "TK-%s" % ref
                    if ticket_id in tickets:
                        continue  # 已物化(幂等)
                    ticket = create_ticket(ticket_id, trace_id=pass_id)
                    if ticket is None:
                        continue
                    ticket["external_ref"] = ref
                    if item.get("thread_id"):
                        ticket["thread_id"] = str(item["thread_id"])
                    ticket["materialized_at"] = ts
                    if save_ticket(ticket, store) is None:
                        continue
                    tickets[ticket_id] = ticket
                    materialized.append({"ticket_id": ticket_id, "external_ref": ref})

        # ⑥ 分派(幂等闸 + 依赖闸 + 槽位闸)
        # 幂等闸: external_ref 已有 Ticket(任意状态) → 不重复物化/分派;
        # 状态区分原因: live(占槽中) / paused|waitsForPerson(等唤醒) / ended(已完成)
        _EXISTING_REASON = {
            "live": "already_live",
            "paused": "already_open",
            "waitsForPerson": "already_open",
            "ended": "already_ended",
        }
        skipped: List[Dict[str, str]] = []
        dispatch_tickets: List[Dict[str, Any]] = []
        seen_refs: Set[str] = set()
        if isinstance(plan_tickets, list):
            for item in plan_tickets:
                if not isinstance(item, dict) or not item.get("external_ref"):
                    continue
                ref = str(item["external_ref"])
                existing = pre_ref_tickets.get(ref)
                if existing is not None:
                    state = str(existing.get("state"))
                    # live 但未绑 worker = 上轮物化后被槽位闸挡住(unassigned)，
                    # 本轮允许补派；已占槽/等唤醒/已结束仍幂等跳过(R13)
                    if not (state == "live" and not existing.get("worker_id")):
                        skipped.append(
                            {
                                "external_ref": ref,
                                "reason": _EXISTING_REASON.get(state, "already_exists"),
                            }
                        )
                        continue
                if ref in seen_refs:
                    skipped.append({"external_ref": ref, "reason": "duplicate_in_plan"})
                    continue
                seen_refs.add(ref)
                dispatch_tickets.append(item)

        done: Set[str] = set(completed_refs or set())
        done |= {
            str(t["external_ref"])
            for t in tickets.values()
            if t.get("state") == "ended" and t.get("external_ref")
        }

        # 依赖闸跨轮补强(R15): 已物化但未 ended 的依赖不因不在本批而失效。
        # 底层 route/dispatch 只校验"本批内"依赖;已被幂等闸移出本批的 live
        # 依赖会被当成外部锚点(视同满足)从而提前放行。此处用 L0 快照补齐。
        _dispatch_cfg = plan.get("dispatch") if isinstance(plan, dict) else None
        depends_on = _dispatch_cfg.get("depends_on") if isinstance(_dispatch_cfg, dict) else None
        if not isinstance(depends_on, dict):
            depends_on = {}
        unfinished_refs = {
            str(t["external_ref"])
            for t in tickets.values()
            if t.get("external_ref") and t.get("state") != "ended"
        }
        cross_deferred: List[Dict[str, Any]] = []
        if depends_on and dispatch_tickets:
            kept: List[Dict[str, Any]] = []
            for item in dispatch_tickets:
                ref = str(item.get("external_ref"))
                deps = [str(d) for d in (depends_on.get(ref) or [])]
                if any(d in unfinished_refs and d not in done for d in deps):
                    cross_deferred.append({"external_ref": ref, "reason": "dependency_unmet"})
                else:
                    kept.append(item)
            dispatch_tickets = kept

        routed: Optional[Dict[str, Any]] = {
            "assignments": [],
            "unassigned": [],
            "deferred": [],
        }
        if dispatch_tickets:
            filtered_plan = dict(plan)
            filtered_plan["tickets"] = dispatch_tickets
            active = list(tickets.values())
            if is_worker_pool_enabled(flags):
                routed = dispatch_concurrent(
                    filtered_plan, roster or {}, active, completed_refs=done
                )
            else:
                routed = route_single_round(filtered_plan, roster or {}, completed_refs=done)

        if routed is None:
            # 非法 plan: 本轮不提交(已物化的 Ticket 下一轮按 already_live 幂等跳过)
            routed = {"assignments": [], "unassigned": [], "deferred": []}
            error = "invalid_plan"
        else:
            error = None
        if cross_deferred:
            routed["deferred"] = list(routed.get("deferred") or []) + cross_deferred

        by_ref = {str(t.get("external_ref")): t for t in tickets.values() if t.get("external_ref")}
        assignments: List[Dict[str, Any]] = []
        for a in routed.get("assignments") or []:
            if not isinstance(a, dict):
                continue
            a = dict(a)
            ticket = by_ref.get(str(a.get("external_ref")))
            if ticket is not None:
                a["ticket_id"] = ticket.get("ticket_id")
                a["trace_id"] = ticket.get("trace_id") or pass_id
            else:
                a.setdefault("trace_id", pass_id)
            assignments.append(a)

        # ⑦ 提交(shadow 时全部跳过;只输出 would_assignments)
        would_assignments = assignments if shadow else []
        delivery_failures = 0
        committed = 0
        if not shadow:
            ts = float(now) if now is not None else time.time()
            for a in assignments:
                ticket = by_ref.get(str(a.get("external_ref")))
                if ticket is None:
                    continue
                updated = dict(ticket)
                updated["worker_id"] = a.get("worker_id")
                updated["assigned_at"] = ts
                updated["assigned_by_pass"] = pass_id
                if save_ticket(updated, store) is None:
                    continue
                tickets[str(updated["ticket_id"])] = updated
                committed += 1
                if use_affinity and affinity is not None and updated.get("thread_id"):
                    try:
                        affinity.bind(
                            updated["thread_id"],
                            a.get("worker_id"),
                            updated.get("ticket_id"),
                            now=ts,
                        )
                    except Exception:
                        pass  # 亲和失败不阻塞提交(H1)
                if sink is not None:
                    try:
                        if not sink(a):
                            delivery_failures += 1
                    except Exception:
                        delivery_failures += 1

        # ⑧ 观测摘要
        summary = {
            "ok": error is None,
            "degraded": False,
            "pass_id": pass_id,
            "trace_id": pass_id,
            "shadow": bool(shadow),
            "duration_ms": int((time.time() - started) * 1000),
            "snapshot": snapshot,
            "drift": drift,
            "resumed": resumed,
            "receipts": receipt_result,
            "materialized": materialized,
            "assignments": assignments,
            "would_assignments": would_assignments,
            "skipped": skipped,
            "unassigned": list(routed.get("unassigned") or []),
            "deferred": list(routed.get("deferred") or []),
            "committed": committed,
            "delivery_failures": delivery_failures,
            "error": error,
        }
        if stats is not None:
            stats.record(summary)
        return summary
    except Exception as exc:  # noqa: BLE001
        return _degraded(pass_id, "pass_exception:%s" % type(exc).__name__, stats, shadow)
