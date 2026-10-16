# -*- coding: utf-8 -*-
"""SPEC-v1.4 §3.5: S 层能力调用链测试（RED）— 认知经验 → REA 拆解 → 开工调研 → REA 再拆解。

依据: SPEC-v1.4-S-layer-design.md §3.5（用户补充 2026-10-16）。
验收:
  1. 广义认知系统经验注入 plan（top 记忆要点，避免踩坑省去调研）
  2. REA 逆向解析拆解 → engineering_okr 为 A 层提供明确 OKR（默认 A 分解器优先消费）
  3. 前两步不足才开工调研；kickoff_trigger 标注 post_research_rea=True（调研确认后 REA 再拆解）
  4. REA 不可用/异常 → FAIL-OPEN 不影响主流程
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.sacg_orchestrator import SACGOrchestrator, SLayerPlanner  # noqa: E402


def _mems(scores, contents=None):
    mems = []
    for i, s in enumerate(scores):
        content = contents[i] if contents else f"经验{i}:操作要点{i}"
        mems.append(SimpleNamespace(score=s, content=content))
    return mems


def _fake_rea(target, feature=None, entry=None):
    return {
        "evidence": [
            {"evidence_id": "E1", "statement": "入口: core/sufficiency.py"},
            {"evidence_id": "E2", "statement": "依赖图: 12 节点, 30 边"},
        ],
        "known_gaps": ["A 层验收标准缺失"],
        "phases": {"locate": "done", "trace": "done"},
    }


class TestCognitiveExperienceInjection:
    def test_plan_carries_top_experience(self):
        """广义认知系统经验注入 plan：top3 记忆要点（避免踩坑省去调研）"""
        planner = SLayerPlanner()
        mems = _mems([0.9, 0.8, 0.7, 0.6, 0.5],
                     contents=["坑1:勿直接改阈值", "坑2:先跑回归", "流程:TDD",
                               "知识:阈值唯一", "经验5"])
        out = planner("这次FOMC怎么看", "event_analysis", mems)
        exp = out["plan"].get("cognitive_experience")
        assert exp is not None, "plan 应携带认知经验"
        assert len(exp) <= 3
        assert "坑1:勿直接改阈值" in exp  # 按 score 排序取 top

    def test_empty_memories_no_experience_but_proceed(self):
        planner = SLayerPlanner()
        out = planner("任务", "event_analysis", [])
        assert out["action"] == "PROCEED"
        assert out["plan"].get("cognitive_experience") in (None, [])


class TestReaEngineeringOkr:
    def test_rea_breakdown_produces_engineering_okr(self):
        """REA 拆解 → engineering_okr（为 A 层提供明确工程 OKR）"""
        planner = SLayerPlanner(rea_fn=_fake_rea)
        out = planner("这次FOMC怎么看", "event_analysis", [])
        okr = out["plan"].get("engineering_okr")
        assert okr, "REA 可用时应产出 engineering_okr"
        assert any("sufficiency" in str(item) or "E1" in str(item) for item in okr)

    def test_a_decomposer_prefers_engineering_okr(self):
        """默认 A 分解器优先消费 engineering_okr → 更具体的 OKR 节点"""
        orch = SACGOrchestrator(router=None,
                                s_planner=SLayerPlanner(rea_fn=_fake_rea))
        # router=None 会构造真实 CDriveV3Router；改用 fake
        class FakeRouter:
            def run_v3(self, node_id, result, state, signals=None,
                       l1_intent_hint=None):
                return {"action": "CONTINUE", "tier": "Tier1",
                        "effort_level": "light"}

        orch = SACGOrchestrator(router=FakeRouter(),
                                s_planner=SLayerPlanner(rea_fn=_fake_rea))
        out = orch.handle("这次FOMC怎么看", l1_intent_hint="event_analysis",
                          memories=[])
        assert out["plan"].get("engineering_okr")
        node_ids = [n["node_id"] for n in out["nodes"]]
        assert len(node_ids) == len(out["plan"]["engineering_okr"])

    def test_rea_exception_fail_open(self):
        """REA 异常 → FAIL-OPEN：流程继续，无 engineering_okr，记录降级原因"""
        def boom(target, feature=None, entry=None):
            raise RuntimeError("REA down")

        planner = SLayerPlanner(rea_fn=boom)
        out = planner("任务", "event_analysis", [])
        assert out["action"] == "PROCEED"
        assert out["plan"].get("engineering_okr") is None
        assert out["rea_degraded"] is True

    def test_no_rea_fn_no_okr(self):
        """未注入 rea_fn → 无 engineering_okr（向后兼容）"""
        planner = SLayerPlanner()
        out = planner("任务", "event_analysis", [])
        assert out["plan"].get("engineering_okr") is None
        assert out.get("rea_degraded") in (None, False)


class TestKickoffPostResearchRea:
    def test_kickoff_trigger_marks_post_research_rea(self):
        """开工调研确认后应 REA 再拆解：kickoff_trigger 标注 post_research_rea=True"""
        planner = SLayerPlanner(rea_fn=_fake_rea)
        out = planner("这次FOMC怎么看", "event_analysis",
                      _mems([0.2]))
        trigger = out["kickoff_trigger"]
        assert trigger is not None
        assert trigger["post_research_rea"] is True

    def test_kickoff_without_rea_fn_no_flag(self):
        """无 REA 能力时 post_research_rea=False（调研后无法再拆解）"""
        planner = SLayerPlanner()
        out = planner("这次FOMC怎么看", "event_analysis", _mems([0.2]))
        trigger = out["kickoff_trigger"]
        assert trigger is not None
        assert trigger["post_research_rea"] is False
