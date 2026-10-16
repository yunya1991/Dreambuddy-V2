# -*- coding: utf-8 -*-
"""P3.1: SACG 编排骨架测试 — C-drive 作为 S→A→C→G 全程调度入口。

依据: SPEC-v1.2-SACG-orchestration.md §3 + PLAN-L0L1L2 P3.1。
验收: 请求入口 → route_confidence 门（L1_DIRECT 不编排 / L2_HANDOFF 进编排）
      → S(规划) → A(OKR 节点) → C(节点执行，复用 CDriveV3Router 决策门) → G(收尾)。
P3.1 只落骨架与流转；S/A/C/G 各层实质内容由 P3.2-P3.5 接入。
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.sacg_orchestrator import (  # noqa: E402
    STAGE_A,
    STAGE_C,
    STAGE_G,
    STAGE_S,
    SACGOrchestrator,
)


def _mems(scores):
    return [SimpleNamespace(score=s, content=f"m{i}") for i, s in enumerate(scores)]


class FakeRouter:
    """记录调用的 C-drive 节点决策门（替身 CDriveV3Router）。"""

    def __init__(self, action="CONTINUE"):
        self.calls = []
        self._action = action

    def run_v3(self, node_id, result, state, signals=None,
               l1_intent_hint=None):
        self.calls.append({"node_id": node_id, "confidence": result.confidence})
        return {
            "action": self._action,
            "reason": f"fake {node_id}",
            "confidence": result.confidence,
            "steps_executed": ["recall", "route:TIER1", f"decision:{self._action}"],
            "match_score": 0.9,
            "case_density": 3,
            "tier": "Tier1",
            "jev_final": self._action,
            "effort_level": "light",
        }


class TestModuleImport:
    def test_constants_and_class(self):
        assert (STAGE_S, STAGE_A, STAGE_C, STAGE_G) == ("S", "A", "C", "G")
        assert callable(SACGOrchestrator)


class TestRouteGate:
    def test_l1_direct_short_circuits_without_orchestration(self):
        router = FakeRouter()
        orch = SACGOrchestrator(router=router)
        out = orch.handle("BTC什么价", l1_intent_hint="price_query",
                          memories=_mems([0.95] * 5))
        assert out["route"] == "L1_DIRECT"
        assert out["orchestrated"] is False
        assert out["stages"] == []
        assert router.calls == []  # L1 直答不进任何 SACG 节点

    def test_l2_handoff_enters_orchestration(self):
        orch = SACGOrchestrator(router=FakeRouter())
        out = orch.handle("帮我做深度架构调研", l1_intent_hint=None, memories=[])
        assert out["route"] == "L2_HANDOFF"
        assert out["orchestrated"] is True
        assert out["route_signal"]["decision"] == "L2_HANDOFF"


class TestSACGFlow:
    def test_full_s_a_c_g_flow_order(self):
        flow = []

        def s_fn(message, hint, memories):
            flow.append("S")
            return {"intent_hint": hint, "plan_items": ["调研", "成文"]}

        def a_fn(plan):
            flow.append("A")
            return [{"node_id": "N1", "criteria": plan["plan_items"][0]},
                    {"node_id": "N2", "criteria": plan["plan_items"][1]}]

        def g_fn(plan, node_results):
            flow.append("G")
            return {"compressed": True, "settled": True}

        router = FakeRouter()
        orch = SACGOrchestrator(
            router=router, s_planner=s_fn, a_decomposer=a_fn, g_closer=g_fn)
        out = orch.handle("深度任务", l1_intent_hint="research", memories=[])

        # C 阶段在 A 之后、G 之前由编排器内部驱动（flow 中显式标记 S/A/G，C 见节点结果）
        assert flow[0] == "S" and flow[1] == "A" and flow[-1] == "G"
        assert out["stages"] == ["S", "A", "C", "G"]
        # C: 每个 OKR 节点都经 C-drive 节点决策门
        assert [r["node_id"] for r in out["node_results"]] == ["N1", "N2"]
        assert [c["node_id"] for c in router.calls] == ["N1", "N2"]
        assert all(r["action"] == "CONTINUE" for r in out["node_results"])
        assert out["closure"] == {"compressed": True, "settled": True}

    def test_intent_hint_reaches_s_planner(self):
        seen = {}

        def s_fn(message, hint, memories):
            seen["hint"] = hint
            return {"plan_items": [message]}

        orch = SACGOrchestrator(router=FakeRouter(), s_planner=s_fn)
        orch.handle("任务", l1_intent_hint="technical_analysis", memories=[])
        assert seen["hint"] == "technical_analysis"

    def test_default_skeleton_produces_single_node_plan(self):
        orch = SACGOrchestrator(router=FakeRouter())
        out = orch.handle("只有一句话的任务", memories=[])
        assert out["stages"] == ["S", "A", "C", "G"]
        assert len(out["plan"]["plan_items"]) == 1
        assert len(out["nodes"]) == 1
        assert out["node_results"][0]["node_id"] == "N1"
        # G 骨架默认标记（真实收尾联动属 P3.5）
        assert out["closure"]["compressed"] is True

    def test_c_node_action_propagated(self):
        orch = SACGOrchestrator(router=FakeRouter(action="REDO"))
        out = orch.handle("需要重做的任务", memories=[])
        assert out["node_results"][0]["action"] == "REDO"


class TestFailOpen:
    def test_s_planner_exception_degrades_but_flow_continues(self):
        def boom(message, hint, memories):
            raise RuntimeError("S down")

        router = FakeRouter()
        orch = SACGOrchestrator(router=router, s_planner=boom)
        out = orch.handle("任务", memories=[])
        # S 失败 → 空计划兜底，A/C/G 仍走完（FAIL-OPEN，不抛出）
        assert out["stages"] == ["S", "A", "C", "G"]
        assert out["degraded"] is True
        assert any("S" in e for e in out["errors"])
        assert router.calls == []  # 空计划无节点

    def test_c_node_exception_isolated(self):
        class PartialBoomRouter(FakeRouter):
            def run_v3(self, node_id, result, state, signals=None,
               l1_intent_hint=None):
                if node_id == "N2":
                    raise RuntimeError("node exec failed")
                return super().run_v3(node_id, result, state, signals)

        def s_fn(message, hint, memories):
            return {"plan_items": ["a", "b"]}

        def a_fn(plan):
            return [{"node_id": "N1", "criteria": "a"},
                    {"node_id": "N2", "criteria": "b"}]

        orch = SACGOrchestrator(router=PartialBoomRouter(),
                                s_planner=s_fn, a_decomposer=a_fn)
        out = orch.handle("任务", memories=[])
        assert out["stages"] == ["S", "A", "C", "G"]
        assert out["degraded"] is True
        # N1 成功、N2 失败被隔离，G 仍执行
        assert out["node_results"][0]["action"] == "CONTINUE"
        assert out["node_results"][1]["action"] == "FAILED"
        assert any("N2" in e for e in out["errors"])

    def test_g_closer_exception_fail_open(self):
        def boom(plan, node_results):
            raise RuntimeError("G down")

        orch = SACGOrchestrator(router=FakeRouter(), g_closer=boom)
        out = orch.handle("任务", memories=[])
        assert out["stages"] == ["S", "A", "C", "G"]
        assert out["degraded"] is True
        assert out["closure"].get("settled") is False


class TestSLayerHintDeepening:
    """P3.2: S 层 l1_intent_hint 深化消费 —— 意图档案驱动规划展开 + Spec 草案产出。"""

    def test_registered_hint_expands_plan_with_spec(self):
        """命中档案的 hint → plan_items 按模板展开（多步）+ spec 草案"""
        orch = SACGOrchestrator(router=FakeRouter())
        out = orch.handle("这次FOMC怎么看", l1_intent_hint="event_analysis",
                          memories=[])
        plan = out["plan"]
        assert plan["intent_hint"] == "event_analysis"
        spec = plan["spec"]
        assert spec is not None
        assert spec["intent"] == "event_analysis"
        assert spec["source"] == "l1_intent_hint"
        assert spec["depth"] in ("light", "standard", "deep")
        assert len(plan["plan_items"]) > 1  # 模板展开，非单条兜底
        # A 层按展开后的 plan_items 分解出等数 OKR 节点
        assert len(out["nodes"]) == len(plan["plan_items"])

    def test_unregistered_hint_falls_back_to_single_item(self):
        orch = SACGOrchestrator(router=FakeRouter())
        out = orch.handle("随便一句", l1_intent_hint="not_registered",
                          memories=[])
        assert len(out["plan"]["plan_items"]) == 1
        assert out["plan"]["spec"] is None

    def test_no_hint_falls_back_to_single_item(self):
        orch = SACGOrchestrator(router=FakeRouter())
        out = orch.handle("随便一句", memories=[])
        assert len(out["plan"]["plan_items"]) == 1
        assert out["plan"]["spec"] is None

    def test_hint_reaches_c_layer_router(self):
        """S 层消费的 hint 必须透传到 C 层节点决策门（c_drive_v3_router）"""

        class HintCapturingRouter(FakeRouter):
            def run_v3(self, node_id, result, state, signals=None,
                       l1_intent_hint=None):
                self.calls.append({"node_id": node_id,
                                   "l1_intent_hint": l1_intent_hint})
                return {
                    "action": "CONTINUE", "reason": "cap",
                    "confidence": result.confidence,
                    "steps_executed": [], "match_score": 0.9,
                    "case_density": 3, "tier": "Tier1",
                    "jev_final": "CONTINUE", "effort_level": "light",
                }

        router = HintCapturingRouter()
        orch = SACGOrchestrator(router=router)
        out = orch.handle("查持仓风控", l1_intent_hint="risk_control",
                          memories=[])
        assert out["orchestrated"] is True
        assert router.calls, "C 层应至少执行一个节点"
        assert all(c["l1_intent_hint"] == "risk_control" for c in router.calls)

    def test_all_ten_intents_have_profiles(self):
        """L1 十意图全部有 S 层档案（与 l1-intent-registry 对齐）"""
        from core.sacg_orchestrator import S_LAYER_INTENT_PROFILES

        for name in ("data_query", "data_insight", "contradiction_insight",
                     "path_insight", "technical_analysis", "fundamental_valuation",
                     "asset_class_trend", "event_analysis", "risk_control",
                     "price_query"):
            profile = S_LAYER_INTENT_PROFILES[name]
            assert profile["plan"], name
            assert profile["depth"] in ("light", "standard", "deep"), name
