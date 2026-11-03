# -*- coding: utf-8 -*-
"""T-DSH-P0 B1: OKR→Ticket Mandate 契约翻译器测试（RED）。

依据: SACG_A_SUPERAGENT_CONNECTION_SPEC v0.2 §4.2 + DESIGN-DSH-ARCH-UPGRADE v0.2。
验收(A2):
  - 3 类 verify 映射正确(evidence_backed/gap_closed/c_action)
  - 空 plan / 异常输入降级返回 None 且不抛错(FAIL-OPEN, HC-1)
  - 开关 enable_superagent_bridge 默认 False(HC-2)
  - evidence_id → mandate.evidence_refs[]; domain=finance_research → 路由提示
  - dependency_graph → 分派计划(并行/串行)
输出为建议性 Mandate 草案(双门之后才创建 Ticket),纯函数无副作用。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.okr_nodes import (  # noqa: E402
    VERIFY_C_ACTION,
    VERIFY_EVIDENCE,
    VERIFY_GAP,
    decompose_okr_nodes,
)
from core.okr_ticket_bridge import (  # noqa: E402
    BRIDGE_SWITCH,
    is_bridge_enabled,
    translate_okr_node,
    translate_plan_to_tickets,
)


class TestBridgeSwitch:
    def test_switch_name(self):
        assert BRIDGE_SWITCH == "enable_superagent_bridge"

    def test_default_off(self):
        assert is_bridge_enabled() is False
        assert is_bridge_enabled({}) is False
        assert is_bridge_enabled(None) is False

    def test_enabled_when_flag_true(self):
        assert is_bridge_enabled({"enable_superagent_bridge": True}) is True

    def test_non_dict_flags_fail_open(self):
        assert is_bridge_enabled("bad") is False
        assert is_bridge_enabled(123) is False


class TestTranslateOkrNode:
    def test_c_action_mapping(self):
        node = {
            "node_id": "N1",
            "objective": "调研",
            "criteria": "调研",
            "source": "plan_item",
            "verify": VERIFY_C_ACTION,
        }
        ticket = translate_okr_node(node)
        assert ticket["external_ref"] == "N1"
        assert ticket["mandate"]["goal"] == "调研"
        assert ticket["mandate"]["acceptance"] == "调研"
        policy = ticket["mandate"]["completion_policy"]
        assert policy["kind"] == "c_action"
        assert "REDO" in policy["forbid_actions"]
        assert "EARLY_TERMINATE" in policy["forbid_actions"]

    def test_evidence_backed_mapping_with_evidence_refs(self):
        node = {
            "node_id": "N1",
            "objective": "拆解入口链",
            "criteria": "拆解入口链",
            "source": "rea_evidence",
            "verify": VERIFY_EVIDENCE,
            "evidence_id": "EV-1",
        }
        ticket = translate_okr_node(node)
        assert ticket["mandate"]["completion_policy"]["kind"] == "evidence_backed"
        assert ticket["mandate"]["evidence_refs"] == ["EV-1"]

    def test_gap_closed_mapping(self):
        node = {
            "node_id": "N2",
            "objective": "补齐: 缺口A",
            "criteria": "补齐: 缺口A",
            "source": "rea_known_gap",
            "verify": VERIFY_GAP,
        }
        ticket = translate_okr_node(node)
        assert ticket["mandate"]["completion_policy"]["kind"] == "gap_closed"
        assert ticket["mandate"]["evidence_refs"] == []

    def test_domain_finance_research_route_hint(self):
        node = {
            "node_id": "N1",
            "objective": "金融调研",
            "criteria": "金融调研",
            "source": "plan_item",
            "verify": VERIFY_C_ACTION,
            "domain": "finance_research",
        }
        ticket = translate_okr_node(node)
        assert ticket["route_hint"]["domain"] == "finance_research"
        assert ticket["route_hint"]["role"] == "research"

    def test_no_domain_no_role_hint(self):
        node = {
            "node_id": "N1",
            "objective": "写代码",
            "criteria": "写代码",
            "source": "plan_item",
            "verify": VERIFY_C_ACTION,
        }
        ticket = translate_okr_node(node)
        assert ticket["route_hint"]["domain"] is None
        assert ticket["route_hint"]["role"] is None

    def test_unknown_verify_falls_back_to_c_action(self):
        node = {
            "node_id": "N1",
            "objective": "x",
            "criteria": "x",
            "source": "mystery",
            "verify": "unknown_verify_kind",
        }
        ticket = translate_okr_node(node)
        assert ticket["mandate"]["completion_policy"]["kind"] == "c_action"

    def test_bad_input_returns_none_no_raise(self):
        assert translate_okr_node(None) is None
        assert translate_okr_node({}) is None
        assert translate_okr_node({"objective": "无 node_id"}) is None
        assert translate_okr_node("not a dict") is None


class TestTranslatePlanToTickets:
    def test_empty_plan_returns_none(self):
        assert translate_plan_to_tickets({}) is None
        assert translate_plan_to_tickets({"plan_items": []}) is None
        assert translate_plan_to_tickets(None) is None

    def test_plan_items_to_tickets(self):
        result = translate_plan_to_tickets({"plan_items": ["调研", "成文"]})
        assert result is not None
        tickets = result["tickets"]
        assert [t["external_ref"] for t in tickets] == ["N1", "N2"]
        assert all(t["mandate"]["completion_policy"]["kind"] == "c_action" for t in tickets)

    def test_engineering_okr_full_mapping(self):
        plan = {
            "engineering_okr": [
                {"okr": "拆解入口链", "evidence_id": "EV-1", "source": "rea_evidence"},
                {"okr": "补齐: 缺口A", "source": "rea_known_gap"},
            ]
        }
        result = translate_plan_to_tickets(plan)
        kinds = [t["mandate"]["completion_policy"]["kind"] for t in result["tickets"]]
        assert kinds == ["evidence_backed", "gap_closed"]
        assert result["tickets"][0]["mandate"]["evidence_refs"] == ["EV-1"]

    def test_dispatch_default_sequential_without_okr_set(self):
        result = translate_plan_to_tickets({"plan_items": ["a", "b"]})
        assert result["dispatch"]["mode"] == "sequential"

    def test_dispatch_parallel_from_okr_set(self):
        okr_set = {"parallel_line_count": 3, "dependency_graph": {}}
        result = translate_plan_to_tickets({"plan_items": ["a", "b", "c"]}, okr_set=okr_set)
        assert result["dispatch"]["mode"] == "parallel"

    def test_dispatch_dependencies_from_dependency_graph(self):
        okr_set = {
            "parallel_line_count": 1,
            "dependency_graph": {"N2": ["N1"], "N3": ["N2"]},
        }
        result = translate_plan_to_tickets({"plan_items": ["a", "b", "c"]}, okr_set=okr_set)
        assert result["dispatch"]["depends_on"] == {"N2": ["N1"], "N3": ["N2"]}

    def test_domain_propagates_from_plan(self):
        plan = {"research_request": "x", "plan_items": ["金融调研"]}
        result = translate_plan_to_tickets(plan)
        assert result["tickets"][0]["route_hint"]["role"] == "research"

    def test_exception_fail_open_returns_none(self):
        class ExplodingDict(dict):
            def get(self, *a, **k):
                raise RuntimeError("boom")

        assert translate_plan_to_tickets(ExplodingDict()) is None

    def test_result_is_pure_suggestion_draft(self):
        """输出为建议性草案: 带 draft 标记, 双门(Policy+S层)后才创建 Ticket。"""
        result = translate_plan_to_tickets({"plan_items": ["a"]})
        assert result["draft"] is True

    def test_consistent_with_decompose_okr_nodes(self):
        plan = {
            "engineering_okr": [
                {"okr": "拆解入口链", "evidence_id": "EV-1", "source": "rea_evidence"},
            ]
        }
        nodes = decompose_okr_nodes(plan)
        result = translate_plan_to_tickets(plan)
        assert result["tickets"][0]["external_ref"] == nodes[0]["node_id"]
        assert result["tickets"][0]["mandate"]["goal"] == nodes[0]["objective"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
