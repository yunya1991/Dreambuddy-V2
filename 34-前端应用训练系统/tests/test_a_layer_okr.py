# -*- coding: utf-8 -*-
"""P3.3: A 层 OKR 验收体系测试（RED）— Spec/Plan → OKR 节点 + 每节点验收标准。

依据: SPEC-v1.2-SACG-orchestration.md §2.2（A 层从工具组合器升级为验收体系，
      每个 OKR 节点有明确验收标准）+ PLAN-L0L1L2 P3.3。
验收: Plan → OKR 节点集；节点携带 {node_id, objective, criteria(验收标准), source, verify}；
      engineering_okr 优先于 plan_items；verify 按来源分派（rea_evidence→evidence_backed /
      rea_known_gap→gap_closed / plan_item→c_action）；node_id+criteria 键向后兼容 C 层。
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.okr_nodes import (  # noqa: E402
    VERIFY_C_ACTION,
    VERIFY_EVIDENCE,
    VERIFY_GAP,
    decompose_okr_nodes,
)
from core.sacg_orchestrator import SACGOrchestrator  # noqa: E402


class TestDecomposeOkrNodes:
    def test_empty_plan_returns_empty(self):
        assert decompose_okr_nodes({}) == []
        assert decompose_okr_nodes({"plan_items": []}) == []

    def test_plan_items_become_okr_nodes(self):
        nodes = decompose_okr_nodes({"plan_items": ["调研", "成文"]})
        assert [n["node_id"] for n in nodes] == ["N1", "N2"]
        assert nodes[0]["objective"] == "调研"
        assert nodes[0]["criteria"] == "调研"  # 验收标准（P3.4 回传比对依据）
        assert nodes[0]["source"] == "plan_item"
        assert nodes[0]["verify"] == VERIFY_C_ACTION

    def test_engineering_okr_preferred_over_plan_items(self):
        plan = {
            "plan_items": ["不应被消费"],
            "engineering_okr": [
                {"okr": "拆解入口链", "evidence_id": "EV-1", "source": "rea_evidence"},
                {"okr": "补齐: 缺口A", "source": "rea_known_gap"},
            ],
        }
        nodes = decompose_okr_nodes(plan)
        assert len(nodes) == 2
        assert nodes[0]["objective"] == "拆解入口链"

    def test_rea_evidence_node_verify_and_evidence_id(self):
        plan = {"engineering_okr": [
            {"okr": "拆解入口链", "evidence_id": "EV-1", "source": "rea_evidence"}]}
        node = decompose_okr_nodes(plan)[0]
        assert node["verify"] == VERIFY_EVIDENCE
        assert node["evidence_id"] == "EV-1"
        assert node["source"] == "rea_evidence"
        assert node["criteria"] == "拆解入口链"

    def test_rea_known_gap_node_verify(self):
        plan = {"engineering_okr": [{"okr": "补齐: 缺口A", "source": "rea_known_gap"}]}
        node = decompose_okr_nodes(plan)[0]
        assert node["verify"] == VERIFY_GAP
        assert "evidence_id" not in node

    def test_criteria_is_string_not_dict(self):
        """验收标准必须是字符串（C 层/日志消费友好，禁止裸 dict 透传）"""
        plan = {"engineering_okr": [
            {"okr": "拆解入口链", "evidence_id": "EV-1", "source": "rea_evidence"}]}
        node = decompose_okr_nodes(plan)[0]
        assert isinstance(node["criteria"], str)

    def test_backward_compat_keys(self):
        """node_id + criteria 键保持（C 层 _run_node 与既有测试消费）"""
        nodes = decompose_okr_nodes({"plan_items": ["x"]})
        assert "node_id" in nodes[0] and "criteria" in nodes[0]


class FakeRouter:
    def run_v3(self, node_id, result, state, signals=None, l1_intent_hint=None):
        return {"action": "CONTINUE", "tier": "Tier1", "effort_level": "light"}


class TestOrchestratorAIntegration:
    def test_default_a_decomposer_produces_okr_nodes(self):
        """默认 A 分解器实质化为 OKR 验收节点：nodes 携带 verify 字段，流程不变"""
        orch = SACGOrchestrator(router=FakeRouter())
        out = orch.handle("这次FOMC怎么看", l1_intent_hint="event_analysis",
                          memories=[])
        assert out["action"] == "PROCEED"
        assert out["stages"] == ["S", "A", "C", "G"]
        assert out["nodes"], "A 层应产出 OKR 节点"
        for node in out["nodes"]:
            assert node["verify"] in (VERIFY_C_ACTION, VERIFY_EVIDENCE, VERIFY_GAP)
            assert node["objective"]
        # C 层仍按 node_id 消费（向后兼容）
        assert [r["node_id"] for r in out["node_results"]] == \
               [n["node_id"] for n in out["nodes"]]
