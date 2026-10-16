# -*- coding: utf-8 -*-
"""SPEC-v1.4: S 层充分性评估 + 充分性状态机测试（RED）。

依据: SPEC-v1.4-S-layer-design.md §3。
验收:
  S-1 core/sufficiency.py 充分性评估器（入口四态 + 规划四态，复用 0.7/3/0.3 派生，禁新阈值）
  S-2 SLayerPlanner 充分性状态机 S0→S1→S2（替换 _default_s_planner，新契约
      {plan, sufficiency, action, clarification, research_request, kickoff_trigger}）
  S-4 开工 Skill 触发门（depth=deep + NEED_RESEARCH → 异步打桩；显式「开工」关键词直接触发）

阈值硬约束: 只引用 route_confidence/jev_gate 既有常量，禁止第二套数值。
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.sufficiency import (  # noqa: E402
    EARLY_TERMINATE,
    NEED_CLARIFY,
    NEED_DEEPER,
    NEED_PLAN,
    NEED_RESEARCH,
    SUFFICIENT,
    SUFFICIENT_DIRECT,
    evaluate_entry_sufficiency,
    evaluate_plan_sufficiency,
)
from core.jev_gate import JevAntiOscillation  # noqa: E402
from core.sacg_orchestrator import SACGOrchestrator, SLayerPlanner  # noqa: E402


def _mems(scores):
    return [SimpleNamespace(score=s, content=f"m{i}") for i, s in enumerate(scores)]


class FakeRouter:
    def __init__(self, action="CONTINUE"):
        self.calls = []
        self._action = action

    def run_v3(self, node_id, result, state, signals=None, l1_intent_hint=None):
        self.calls.append({"node_id": node_id})
        return {"action": self._action, "tier": "Tier1", "effort_level": "light"}


# ============================================================
# S-1b: jev 终裁接入 — 信号矛盾澄清 + jev 改写 + 抗振荡
# ============================================================

class TestJevFinalArbitration:
    def test_strong_signals_not_overridden(self):
        r = evaluate_entry_sufficiency(_mems([0.9, 0.85, 0.8]), depth="standard")
        assert r.state == NEED_PLAN
        assert r.jev_decision == "CONTINUE"

    def test_signal_contradiction_high_match_low_density(self):
        r = evaluate_entry_sufficiency(_mems([0.8, 0.7]), depth="standard")
        assert r.state == NEED_CLARIFY
        assert "signal_contradiction" in r.reasons

    def test_signal_contradiction_low_match_high_density(self):
        r = evaluate_entry_sufficiency(_mems([0.3] * 5), depth="standard")
        assert r.state == NEED_CLARIFY
        assert "signal_contradiction" in r.reasons

    def test_double_low_still_need_research(self):
        r = evaluate_entry_sufficiency(_mems([0.2]), depth="deep")
        assert r.state == NEED_RESEARCH

    def test_jev_decision_recorded_in_result(self):
        r = evaluate_entry_sufficiency(_mems([0.9, 0.85, 0.8]), depth="standard")
        assert r.jev_decision is not None
        assert r.to_dict()["jev_decision"] == r.jev_decision

    def test_anti_oscillation_instance_accepted(self):
        osc = JevAntiOscillation()
        for _ in range(3):
            r = evaluate_entry_sufficiency(
                _mems([0.9, 0.85, 0.8]), depth="standard", anti_oscillation=osc)
        assert r.state == NEED_PLAN

    def test_plan_sufficient_jev_continue(self):
        r = evaluate_plan_sufficiency(
            {"plan_items": ["a"]}, _mems([0.9, 0.8, 0.85]), depth="standard")
        assert r.state == SUFFICIENT
        assert r.jev_decision == "CONTINUE"

    def test_plan_empty_states_bypass_jev(self):
        r = evaluate_plan_sufficiency({"plan_items": []}, _mems([0.9, 0.8]), depth="deep")
        assert r.state == EARLY_TERMINATE
        assert r.jev_decision is None


# ============================================================
# S-1: 入口充分性（S0）— 四态
# ============================================================

class TestEntrySufficiency:
    def test_empty_memories_need_plan(self):
        """recall 空 → NEED_PLAN（FAIL-OPEN 兜底，保持既有单条计划行为）"""
        r = evaluate_entry_sufficiency([], depth="standard")
        assert r.state == NEED_PLAN
        assert r.match_score == 0.0 and r.case_density == 0

    def test_none_memories_need_plan(self):
        r = evaluate_entry_sufficiency(None, depth=None)
        assert r.state == NEED_PLAN

    def test_light_depth_high_conf_sufficient_direct(self):
        """light 深度 + 高 match + 密度达标 → SUFFICIENT_DIRECT（跳过规划直接答）"""
        r = evaluate_entry_sufficiency(_mems([0.9, 0.85, 0.8]), depth="light")
        assert r.state == SUFFICIENT_DIRECT

    def test_standard_depth_high_conf_still_plans(self):
        """standard/deep 深度即使信号强也必须规划（SUFFICIENT_DIRECT 只对 light 开放）"""
        r = evaluate_entry_sufficiency(_mems([0.9, 0.85, 0.8]), depth="standard")
        assert r.state == NEED_PLAN

    def test_uncertainty_band_need_clarify(self):
        """不确定区间（match∈[0.4,0.7) 且 density<3）→ NEED_CLARIFY 问用户"""
        r = evaluate_entry_sufficiency(_mems([0.5, 0.5]), depth="standard")
        assert r.state == NEED_CLARIFY
        assert 0.4 <= r.match_score < 0.7

    def test_double_low_need_research(self):
        """双低（match<0.4 且 density<3）→ NEED_RESEARCH 触发调研（首版打桩）"""
        r = evaluate_entry_sufficiency(_mems([0.2]), depth="deep")
        assert r.state == NEED_RESEARCH

    def test_cognitive_unavailable_need_plan(self):
        r = evaluate_entry_sufficiency(_mems([0.9] * 5), depth="light",
                                       cognitive_available=False)
        assert r.state == NEED_PLAN
        assert "cognitive_unavailable" in r.reasons

    def test_result_to_dict(self):
        r = evaluate_entry_sufficiency([], depth="light")
        d = r.to_dict()
        assert d["state"] == NEED_PLAN
        assert "route_confidence" in d and "reasons" in d


# ============================================================
# S-1: 规划充分性（S2）— 四态
# ============================================================

class TestPlanSufficiency:
    def test_nonempty_plan_sufficient(self):
        plan = {"plan_items": ["a", "b"]}
        r = evaluate_plan_sufficiency(plan, _mems([0.9, 0.8, 0.85]), depth="standard")
        assert r.state == SUFFICIENT

    def test_empty_plan_light_need_deeper(self):
        """展开为空 + 非最深 → NEED_DEEPER（继续展开 light→standard→deep）"""
        r = evaluate_plan_sufficiency({"plan_items": []}, _mems([0.9, 0.8]), depth="light")
        assert r.state == NEED_DEEPER

    def test_empty_plan_deep_early_terminate(self):
        """展开为空 + 已最深 → EARLY_TERMINATE（不值得做，礼貌退出）"""
        r = evaluate_plan_sufficiency({"plan_items": []}, _mems([0.9, 0.8]), depth="deep")
        assert r.state == EARLY_TERMINATE

    def test_none_plan_need_deeper(self):
        r = evaluate_plan_sufficiency(None, _mems([0.9]), depth=None)
        assert r.state == NEED_DEEPER

    def test_plan_uncertainty_need_clarify(self):
        plan = {"plan_items": ["a"]}
        r = evaluate_plan_sufficiency(plan, _mems([0.5, 0.5]), depth="standard")
        assert r.state == NEED_CLARIFY


# ============================================================
# S-2: SLayerPlanner 状态机 + 编排器集成
# ============================================================

class TestSLayerPlannerContract:
    def test_default_planner_produces_new_contract(self):
        """默认 s_planner 实质化为 SLayerPlanner，返回新契约"""
        planner = SLayerPlanner()
        out = planner("随便一句", None, [])
        for key in ("plan", "sufficiency", "action"):
            assert key in out, key
        assert out["plan"]["plan_items"], "空回忆仍兜底单条计划"
        assert out["action"] == "PROCEED"

    def test_sufficient_direct_minimal_plan(self):
        """light + 强信号 → SUFFICIENT_DIRECT：最小计划（单节点）"""
        planner = SLayerPlanner()
        out = planner("BTC什么价", "price_query", _mems([0.9, 0.85, 0.8]))
        assert out["action"] == SUFFICIENT_DIRECT
        assert len(out["plan"]["plan_items"]) == 1

    def test_need_clarify_produces_options(self):
        """NEED_CLARIFY → 结构化澄清选项（复用现有澄清链路选项词表）"""
        planner = SLayerPlanner()
        out = planner("分析一下", "technical_analysis", _mems([0.5, 0.5]))
        assert out["action"] == NEED_CLARIFY
        options = out["clarification"]["options"]
        assert 2 <= len(options) <= 4

    def test_need_research_stub_and_deep_kickoff(self):
        """depth=deep + NEED_RESEARCH → 调研打桩 + 开工 Skill 异步触发打桩"""
        planner = SLayerPlanner()
        out = planner("这次FOMC怎么看", "event_analysis", _mems([0.2]))
        assert out["action"] == "PROCEED"  # 打桩后继续规划（FAIL-OPEN）
        assert out["research_request"] is not None
        assert out["kickoff_trigger"] is not None
        assert out["kickoff_trigger"]["skill"] == "dream-arch-research-orchestrator"
        assert out["kickoff_trigger"]["mode"] == "async_stub"

    def test_light_depth_never_kickoff(self):
        """决策点 3：light/standard 永不触发开工 Skill"""
        planner = SLayerPlanner()
        out = planner("查个数据", "data_query", _mems([0.2]))
        assert out["research_request"] is not None
        assert out["kickoff_trigger"] is None

    def test_explicit_kickoff_keyword(self):
        """用户显式说「开工」→ 直接触发（无视深度）"""
        planner = SLayerPlanner()
        out = planner("开工：重构调研模块", "data_query", _mems([0.2]))
        assert out["kickoff_trigger"] is not None

    def test_depth_escalation_on_empty_plan(self):
        """NEED_DEEPER → 深度升级一档并补充深化项；到 deep 仍空 → EARLY_TERMINATE"""
        profiles = {"x": {"depth": "light", "plan": []}}
        planner = SLayerPlanner(profiles=profiles)
        out = planner("任务", "x", _mems([0.6, 0.6, 0.6]))
        assert out["action"] == "PROCEED"
        assert out["plan"]["spec"]["depth"] == "standard"  # light→standard 升级
        assert out["plan"]["plan_items"], "升级后补充深化项"

        profiles_deep = {"x": {"depth": "deep", "plan": []}}
        planner2 = SLayerPlanner(profiles=profiles_deep)
        out2 = planner2("任务", "x", _mems([0.6, 0.6, 0.6]))
        assert out2["action"] == EARLY_TERMINATE


class TestOrchestratorSufficiencyIntegration:
    def test_handle_need_clarify_short_circuits(self):
        """NEED_CLARIFY → 挂起问用户：stages 只到 S，不执行 C 节点"""
        router = FakeRouter()
        orch = SACGOrchestrator(router=router)
        out = orch.handle("分析一下", l1_intent_hint="technical_analysis",
                          memories=_mems([0.5, 0.5]))
        assert out["action"] == NEED_CLARIFY
        assert out["stages"] == ["S"]
        assert out["node_results"] == []
        assert router.calls == []
        assert out["clarification"]["options"]

    def test_handle_early_terminate_short_circuits(self):
        """EARLY_TERMINATE → 礼貌退出：stages 只到 S"""
        profiles = {"event_analysis": {"depth": "deep", "plan": []}}
        orch = SACGOrchestrator(router=FakeRouter(),
                                s_planner=SLayerPlanner(profiles=profiles))
        out = orch.handle("任务", l1_intent_hint="event_analysis",
                          memories=_mems([0.6, 0.6, 0.6]))
        assert out["action"] == EARLY_TERMINATE
        assert out["stages"] == ["S"]
        assert out["node_results"] == []

    def test_handle_proceed_includes_sufficiency(self):
        """正常推进 → 输出携带 sufficiency 与 action=PROCEED（不破坏既有字段）"""
        orch = SACGOrchestrator(router=FakeRouter())
        out = orch.handle("这次FOMC怎么看", l1_intent_hint="event_analysis",
                          memories=[])
        assert out["action"] == "PROCEED"
        assert out["sufficiency"]["state"] == NEED_PLAN
        assert out["stages"] == ["S", "A", "C", "G"]
        assert out["research_request"] is None

    def test_handle_research_stub_flow_continues(self):
        """NEED_RESEARCH 打桩不阻断：流程继续走完 S→A→C→G"""
        orch = SACGOrchestrator(router=FakeRouter())
        out = orch.handle("这次FOMC怎么看", l1_intent_hint="event_analysis",
                          memories=_mems([0.2]))
        assert out["action"] == "PROCEED"
        assert out["research_request"] is not None
        assert out["kickoff_trigger"]["skill"] == "dream-arch-research-orchestrator"
        assert out["stages"] == ["S", "A", "C", "G"]

    def test_legacy_s_planner_still_supported(self):
        """旧契约注入（返回裸 plan dict）行为不变"""
        def s_fn(message, hint, memories):
            return {"plan_items": ["a"]}

        orch = SACGOrchestrator(router=FakeRouter(), s_planner=s_fn)
        out = orch.handle("任务", memories=[])
        assert out["stages"] == ["S", "A", "C", "G"]
        assert out["action"] == "PROCEED"
