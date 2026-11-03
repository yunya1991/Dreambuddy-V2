# -*- coding: utf-8 -*-
"""T-DSH-P0 D1: Router 单轮分派测试（RED）。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-1(Router 常驻但无状态,每次 pass
从输入快照算分派,不持任务状态) + ADR-4(Router 只感知能力标签,不感知全量工具)
+ SACG_A SPEC §4.2(dispatch 分派计划: 并行线→多 Worker,顺序依赖→串行)。
验收:
  - 单轮分派: 输入 Ticket 草案集 + Worker 花名册,输出本轮分派计划
  - 角色匹配: route_hint.role → 持有该角色能力标签的 Worker
  - 依赖闸: depends_on 未满足的 Ticket 本轮 deferred(不分派)
  - 无状态: 同一输入两次调用结果一致;Router 不跨调用记忆
  - 无可用 Worker → unassigned(带 reason),不抛错
  - 开关 enable_superagent_router 默认 False;FAIL-OPEN 坏输入 → None
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.ticket_router import (  # noqa: E402
    ROUTER_SWITCH,
    is_router_enabled,
    route_single_round,
)


def _ticket(ref, role="research", deps=None):
    return {
        "external_ref": ref,
        "mandate": {"goal": "g", "acceptance": "a"},
        "route_hint": {"domain": "finance_research", "role": role},
        "_deps": deps or [],
    }


def _plan(tickets, mode="parallel", depends_on=None):
    return {
        "draft": True,
        "tickets": tickets,
        "dispatch": {"mode": mode, "depends_on": depends_on or {}},
    }


_WORKERS = {
    "research": ["w-res-1", "w-res-2"],
    "engineer": ["w-eng-1"],
    "verifier": [],
}


class TestRouterSwitch:
    def test_switch_name(self):
        assert ROUTER_SWITCH == "enable_superagent_router"

    def test_default_off(self):
        assert is_router_enabled() is False
        assert is_router_enabled({}) is False
        assert is_router_enabled(None) is False

    def test_enabled_when_flag_true(self):
        assert is_router_enabled({"enable_superagent_router": True}) is True


class TestSingleRoundDispatch:
    def test_role_match_assignment(self):
        plan = _plan([_ticket("N1"), _ticket("N2")])
        out = route_single_round(plan, _WORKERS)
        assigned = {a["external_ref"]: a for a in out["assignments"]}
        assert assigned["N1"]["role"] == "research"
        assert assigned["N1"]["worker_id"] == "w-res-1"
        assert assigned["N2"]["worker_id"] == "w-res-2"  # 轮询摊派

    def test_round_robin_wraps(self):
        plan = _plan([_ticket("N1"), _ticket("N2"), _ticket("N3")])
        out = route_single_round(plan, _WORKERS)
        workers = [a["worker_id"] for a in out["assignments"]]
        assert workers == ["w-res-1", "w-res-2", "w-res-1"]

    def test_no_role_hint_defaults_to_first_role(self):
        t = _ticket("N1")
        t["route_hint"] = {"domain": None, "role": None}
        out = route_single_round(_plan([t]), _WORKERS)
        assert out["assignments"][0]["worker_id"] is not None

    def test_no_available_worker_unassigned(self):
        t = _ticket("N1", role="verifier")  # verifier 花名册为空
        out = route_single_round(_plan([t]), _WORKERS)
        assert out["assignments"] == []
        assert out["unassigned"][0]["external_ref"] == "N1"
        assert out["unassigned"][0]["reason"] == "no_worker_for_role"

    def test_unknown_role_unassigned(self):
        t = _ticket("N1", role="trader")  # 花名册无此角色(避交易热路径 H5)
        out = route_single_round(_plan([t]), _WORKERS)
        assert out["unassigned"][0]["reason"] == "no_worker_for_role"


class TestDependencyGate:
    def test_dep_unmet_deferred(self):
        plan = _plan(
            [_ticket("N1"), _ticket("N2")],
            depends_on={"N2": ["N1"]},
        )
        out = route_single_round(plan, _WORKERS)
        refs = [a["external_ref"] for a in out["assignments"]]
        assert "N1" in refs
        assert "N2" not in refs
        assert out["deferred"][0]["external_ref"] == "N2"
        assert out["deferred"][0]["reason"] == "dependency_unmet"

    def test_dep_met_by_completed_set(self):
        plan = _plan([_ticket("N2")], depends_on={"N2": ["N1"]})
        out = route_single_round(plan, _WORKERS, completed_refs={"N1"})
        assert [a["external_ref"] for a in out["assignments"]] == ["N2"]

    def test_dep_external_ref_ignored(self):
        # 依赖指向 Ticket 集外锚点(不进入分派计划) → 视同已满足
        plan = _plan([_ticket("N1")], depends_on={"N1": ["EXT-9"]})
        out = route_single_round(plan, _WORKERS)
        assert [a["external_ref"] for a in out["assignments"]] == ["N1"]


class TestStateless:
    def test_same_input_same_output(self):
        plan = _plan([_ticket("N1"), _ticket("N2")])
        out1 = route_single_round(plan, _WORKERS)
        out2 = route_single_round(plan, _WORKERS)
        assert out1 == out2  # 无状态: 不跨调用记忆轮询位置

    def test_does_not_mutate_input(self):
        plan = _plan([_ticket("N1")])
        snapshot = repr(plan)
        route_single_round(plan, _WORKERS)
        assert repr(plan) == snapshot


class TestFailOpen:
    def test_none_plan(self):
        assert route_single_round(None, _WORKERS) is None

    def test_bad_plan_type(self):
        assert route_single_round("bad", _WORKERS) is None

    def test_empty_tickets(self):
        out = route_single_round(_plan([]), _WORKERS)
        assert out["assignments"] == []
        assert out["unassigned"] == []

    def test_bad_workers_type(self):
        out = route_single_round(_plan([_ticket("N1")]), workers="bad")
        assert out["unassigned"][0]["reason"] == "no_worker_for_role"

    def test_broken_ticket_entry_skipped(self):
        plan = _plan([{"no_external_ref": True}, _ticket("N1")])
        out = route_single_round(plan, _WORKERS)
        refs = [a["external_ref"] for a in out["assignments"]]
        assert refs == ["N1"]
