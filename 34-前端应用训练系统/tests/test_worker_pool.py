# -*- coding: utf-8 -*-
"""T-DSH-P1 P1-3: 多 Worker 并发调度测试（RED）。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P1·并行(多 Worker 并发) + 验收 V3
(并行度: 3 个 Ticket 同时 live,任一 paused 不占 Worker 槽) + ADR-1
(Router 无状态——每轮从快照算分派) + ADR-3(paused/waitsForPerson 不占槽)。

定位: 组合层——ticket_state(四态) + ticket_router(单轮无状态分派) 之上,
引入「槽位」视角: 只有 live 且已绑 worker_id 的 Ticket 占槽;分派时占用中的
Worker 从花名册剔除,空闲 Worker 才接新 Ticket。本模块仍无状态: 占用情况
每轮从 active_tickets 快照(编排侧从 L0 recover)现算。

验收:
  - occupied_workers: 仅 live+worker_id 占槽;paused/waitsForPerson/ended 不占
  - free_roster: 占用 Worker 剔除,同角色其他 Worker 仍可分派
  - V3 场景: 3 Ticket 并行 live(3 Worker 各占一);其一 paused → 槽释放 →
    新 Ticket 分派到刚释放的 Worker
  - 槽满: 无空闲 Worker 的 Ticket → unassigned(不抢占)
  - FAIL-OPEN: 坏输入 → None/空
  - 开关 enable_worker_pool 默认 False
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.ticket_router import route_single_round  # noqa: E402
from core.ticket_state import create_ticket, transition_ticket  # noqa: E402
from core.worker_pool import (  # noqa: E402
    dispatch_concurrent,
    free_roster,
    is_worker_pool_enabled,
    occupied_workers,
)

_ROSTER = {"research": ["w-res-1", "w-res-2"], "engineer": ["w-eng-1"]}


def _plan(refs, role="research"):
    return {
        "draft": True,
        "tickets": [
            {
                "external_ref": r,
                "mandate": {"goal": "g"},
                "route_hint": {"role": role},
            }
            for r in refs
        ],
        "dispatch": {"mode": "parallel", "depends_on": {}},
    }


class TestSwitch:
    def test_default_off(self):
        assert is_worker_pool_enabled() is False
        assert is_worker_pool_enabled({}) is False
        assert is_worker_pool_enabled(None) is False

    def test_on(self):
        assert is_worker_pool_enabled({"enable_worker_pool": True}) is True


class TestOccupiedWorkers:
    def test_live_occupies_slot(self):
        t = create_ticket("TK-1")
        t["worker_id"] = "w-res-1"
        assert occupied_workers([t]) == {"w-res-1"}

    def test_live_without_worker_not_occupied(self):
        t = create_ticket("TK-1")  # live 但尚未分派
        assert occupied_workers([t]) == set()

    def test_paused_not_occupied(self):
        t = create_ticket("TK-1")
        t["worker_id"] = "w-res-1"
        t = transition_ticket(t, "paused", paused_reason="waiting_job", now=1.0)
        assert t["worker_id"] is None  # 状态机已释放
        assert occupied_workers([t]) == set()

    def test_waits_for_person_not_occupied(self):
        t = create_ticket("TK-1")
        t["worker_id"] = "w-res-1"
        t = transition_ticket(t, "waitsForPerson", now=1.0)
        assert occupied_workers([t]) == set()

    def test_ended_not_occupied(self):
        t = create_ticket("TK-1")
        t["worker_id"] = "w-res-1"
        t = transition_ticket(t, "ended", now=1.0)
        # ended 保留 worker_id 作留痕,但语义上槽已由编排侧回收
        assert occupied_workers([t]) == set()

    def test_fail_open(self):
        assert occupied_workers(None) == set()
        assert occupied_workers([None, "bad", {}]) == set()


class TestFreeRoster:
    def test_excludes_occupied(self):
        t = create_ticket("TK-1")
        t["worker_id"] = "w-res-1"
        free = free_roster(_ROSTER, [t])
        assert free["research"] == ["w-res-2"]
        assert free["engineer"] == ["w-eng-1"]

    def test_all_free_when_no_tickets(self):
        assert free_roster(_ROSTER, []) == _ROSTER

    def test_role_fully_occupied(self):
        t1 = create_ticket("TK-1")
        t1["worker_id"] = "w-res-1"
        t2 = create_ticket("TK-2")
        t2["worker_id"] = "w-res-2"
        free = free_roster(_ROSTER, [t1, t2])
        assert free["research"] == []

    def test_fail_open(self):
        assert free_roster(None, []) == {}
        assert free_roster(_ROSTER, None) == _ROSTER


class TestDispatchConcurrent:
    def test_three_tickets_parallel_live(self):
        """V3 核心: 3 个 Ticket 同时 live 且互不阻塞(各占独立 Worker)。"""
        roster = {"research": ["w-res-1", "w-res-2"], "engineer": ["w-eng-1"]}
        plan = {
            "draft": True,
            "tickets": [
                {"external_ref": "R1", "mandate": {}, "route_hint": {"role": "research"}},
                {"external_ref": "R2", "mandate": {}, "route_hint": {"role": "research"}},
                {"external_ref": "E1", "mandate": {}, "route_hint": {"role": "engineer"}},
            ],
            "dispatch": {"mode": "parallel", "depends_on": {}},
        }
        out = dispatch_concurrent(plan, roster, active_tickets=[])
        assert len(out["assignments"]) == 3
        assert out["unassigned"] == []
        workers = {a["worker_id"] for a in out["assignments"]}
        assert workers == {"w-res-1", "w-res-2", "w-eng-1"}  # 各占一槽,不重叠

    def test_paused_frees_slot_for_new_ticket(self):
        """V3 关键: 任一 paused 不占槽 → 新 Ticket 可派到刚释放的 Worker。"""
        roster = {"research": ["w-res-1"]}  # 单 Worker 角色
        t1 = create_ticket("TK-1")
        t1["worker_id"] = "w-res-1"
        # 槽占满: 新 Ticket 派不出去
        out1 = dispatch_concurrent(_plan(["R-NEW"]), roster, active_tickets=[t1])
        assert out1["assignments"] == []
        assert out1["unassigned"][0]["reason"] == "no_free_worker"
        # t1 paused → 槽释放 → 同一 Worker 可接新 Ticket
        t1 = transition_ticket(t1, "paused", paused_reason="waiting_event", now=10.0)
        out2 = dispatch_concurrent(_plan(["R-NEW"]), roster, active_tickets=[t1])
        assert len(out2["assignments"]) == 1
        assert out2["assignments"][0]["worker_id"] == "w-res-1"

    def test_no_preemption_when_full(self):
        """槽满不抢占: 占用中的 Worker 不会被重复分派。"""
        roster = {"research": ["w-res-1"]}
        t1 = create_ticket("TK-1")
        t1["worker_id"] = "w-res-1"
        out = dispatch_concurrent(_plan(["R1", "R2"]), roster, active_tickets=[t1])
        assert out["assignments"] == []
        assert {u["reason"] for u in out["unassigned"]} == {"no_free_worker"}

    def test_reports_occupied_snapshot(self):
        roster = {"research": ["w-res-1", "w-res-2"]}
        t1 = create_ticket("TK-1")
        t1["worker_id"] = "w-res-1"
        out = dispatch_concurrent(_plan(["R1"]), roster, active_tickets=[t1])
        assert out["assignments"][0]["worker_id"] == "w-res-2"
        assert set(out["occupied"]) == {"w-res-1"}

    def test_dependency_still_deferred(self):
        """与 P0 依赖闸兼容: 依赖未满足仍 deferred(槽位不豁免依赖)。"""
        plan = {
            "draft": True,
            "tickets": [
                {"external_ref": "A", "mandate": {}, "route_hint": {"role": "research"}},
                {"external_ref": "B", "mandate": {}, "route_hint": {"role": "research"}},
            ],
            "dispatch": {"mode": "sequential", "depends_on": {"B": ["A"]}},
        }
        out = dispatch_concurrent(plan, _ROSTER, active_tickets=[], completed_refs=set())
        refs = [a["external_ref"] for a in out["assignments"]]
        assert refs == ["A"]
        assert out["deferred"][0]["external_ref"] == "B"

    def test_fail_open(self):
        assert dispatch_concurrent(None, _ROSTER, []) is None
        assert dispatch_concurrent({"no_tickets": 1}, _ROSTER, []) is None
        out = dispatch_concurrent(_plan(["R1"]), None, [])
        assert out["unassigned"][0]["reason"] == "no_free_worker"

    def test_p0_router_contract_preserved(self):
        """P0 兼容: 无占用时退化为 route_single_round 同结果(字节级等价语义)。"""
        plan = _plan(["R1", "R2"])
        legacy = route_single_round(plan, _ROSTER)
        out = dispatch_concurrent(plan, _ROSTER, active_tickets=[])
        assert out["assignments"] == legacy["assignments"]
        assert out["unassigned"] == legacy["unassigned"]
        assert out["deferred"] == legacy["deferred"]
