# -*- coding: utf-8 -*-
"""P3.5: G 层收尾联动测试（RED）— acceptance 结果四分流沉淀路由。

依据: SPEC-v1.2-SACG-orchestration.md §2.4（G 层四分流：案例/认知/流程/文档）
     + PLAN-L0L1L2 P3.5（收尾 Skill 与四分流沉淀对接，Skill 化封装）。
约束:
  - 规则化路由，禁新阈值（不引入 0.7/3/0.3 及 CASE_VALUE_THRESHOLD=0.6 之外数值判定）
  - 全程 FAIL-OPEN：acceptance=None 退化为只走认知分流，不抛错
  - sediments 为 async_stub 描述符打桩（与 S 层 kickoff_trigger 同款模式）；
    真实触发归会话级收尾 Skill，G 层不直接调案例库/skill 系统

四分流路由:
  认知分流（必走）: 委托 cognitive_loop.close_loop；
    outcome 映射 pass→success / degraded→partial / fail→failure
  案例分流: verdict==pass 且有节点 → {type:"case", nodes}
  流程分流: red_flags 非空 → {type:"skill", red_flags}
  文档分流: 存在 degraded 节点 → {type:"doc", pending:[node_ids]}
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.sacg_orchestrator import SACGOrchestrator  # noqa: E402


# ------------------------------------------------------------
# 构造工具
# ------------------------------------------------------------

def _node(node_id="N1"):
    return {"node_id": node_id, "objective": "obj", "criteria": "crit",
            "source": "plan_item", "verify": "c_action"}


def _result(node_id="N1", action="CONTINUE", **kw):
    r = {"node_id": node_id, "action": action, "tier": "Tier1",
         "effort_level": "light", "detail": {}}
    r.update(kw)
    return r


def _acceptance(verdict, node_verdicts=None, red_flags=None):
    return {
        "verdict": verdict,
        "node_verdicts": node_verdicts or [],
        "red_flags": red_flags or [],
        "counts": {"pass": 0, "degraded": 0, "fail": 0},
        "extras": [],
    }


class _FakeCognitive:
    """注入的 record/verify/limiter 假实现（避免真实 MCP 调用）。"""

    def __init__(self):
        self.records = []
        self.verifies = []

    def record(self, content, quality_level="B", tags=""):
        self.records.append({"content": content, "quality_level": quality_level,
                             "tags": tags})
        return {"memory_id": "VM-fake-001"}

    def verify(self, memory_id, success):
        self.verifies.append({"memory_id": memory_id, "success": success})
        return {}


def _make_orchestrator(fake, **kw):
    return SACGOrchestrator(
        record_fn=fake.record, verify_fn=fake.verify, **kw)


def _pass_acceptance(node_ids=("N1",)):
    return _acceptance(
        "pass",
        node_verdicts=[{"node_id": nid, "verify": "c_action",
                        "action": "CONTINUE", "verdict": "pass",
                        "reason": "action_ok"} for nid in node_ids],
    )


def _call_default_closer(orch, plan, results, acceptance):
    return orch._default_g_closer(plan, results, acceptance)


# ------------------------------------------------------------
# 四分流路由（单元级：直接调 _default_g_closer）
# ------------------------------------------------------------

class TestCognitiveSedimentAlways:
    """认知分流必走：无论 verdict 如何都调 close_loop（record+verify）。"""

    def test_pass_outcome_success(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        closure = _call_default_closer(
            orch, {"plan_items": ["x"]}, [_result()], _pass_acceptance())
        cog = closure["cognitive"]
        assert cog["memory_id"] == "VM-fake-001"
        assert fake.records, "认知分流必须 record"
        assert fake.verifies == [{"memory_id": "VM-fake-001", "success": True}]

    def test_degraded_outcome_partial(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        acc = _acceptance(
            "degraded",
            node_verdicts=[{"node_id": "N1", "verify": "c_action",
                            "action": "REDO", "verdict": "degraded",
                            "reason": "action_redo"}])
        closure = _call_default_closer(orch, {}, [_result(action="REDO")], acc)
        # partial → verify(success=False)
        assert fake.verifies == [{"memory_id": "VM-fake-001", "success": False}]
        assert closure["cognitive"]["memory_id"] == "VM-fake-001"

    def test_fail_outcome_failure(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        acc = _acceptance(
            "fail",
            node_verdicts=[{"node_id": "N1", "verify": "c_action",
                            "action": "FAILED", "verdict": "fail",
                            "reason": "action_rejected"}],
            red_flags=["N1"])
        closure = _call_default_closer(orch, {}, [_result(action="FAILED")], acc)
        assert fake.verifies == [{"memory_id": "VM-fake-001", "success": False}]


class TestCaseSediment:
    """案例分流：verdict==pass 且有节点 → case 描述符。"""

    def test_pass_with_nodes_emits_case(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        results = [_result("N1"), _result("N2")]
        closure = _call_default_closer(
            orch, {}, results, _pass_acceptance(("N1", "N2")))
        cases = [s for s in closure["sediments"] if s["type"] == "case"]
        assert len(cases) == 1
        assert cases[0]["nodes"] == ["N1", "N2"]
        assert cases[0]["mode"] == "async_stub"

    def test_non_pass_no_case(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        acc = _acceptance(
            "degraded",
            node_verdicts=[{"node_id": "N1", "verify": "c_action",
                            "action": "REDO", "verdict": "degraded",
                            "reason": "action_redo"}])
        closure = _call_default_closer(orch, {}, [_result(action="REDO")], acc)
        assert not [s for s in closure["sediments"] if s["type"] == "case"]


class TestSkillSediment:
    """流程分流：red_flags 非空 → skill 描述符。"""

    def test_red_flags_emit_skill(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        acc = _acceptance(
            "fail",
            node_verdicts=[{"node_id": "N1", "verify": "c_action",
                            "action": "FAILED", "verdict": "fail",
                            "reason": "action_rejected"}],
            red_flags=["N1"])
        closure = _call_default_closer(orch, {}, [_result(action="FAILED")], acc)
        skills = [s for s in closure["sediments"] if s["type"] == "skill"]
        assert len(skills) == 1
        assert skills[0]["red_flags"] == ["N1"]
        assert skills[0]["mode"] == "async_stub"

    def test_no_red_flags_no_skill(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        closure = _call_default_closer(
            orch, {}, [_result()], _pass_acceptance())
        assert not [s for s in closure["sediments"] if s["type"] == "skill"]


class TestDocSediment:
    """文档分流：存在 degraded 节点 → doc 描述符 pending=[node_ids]。"""

    def test_degraded_nodes_emit_doc(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        acc = _acceptance(
            "degraded",
            node_verdicts=[
                {"node_id": "N1", "verify": "c_action", "action": "CONTINUE",
                 "verdict": "pass", "reason": "action_ok"},
                {"node_id": "N2", "verify": "evidence_backed",
                 "action": "CONTINUE", "verdict": "degraded",
                 "reason": "evidence_pending"},
            ])
        results = [_result("N1"), _result("N2")]
        closure = _call_default_closer(orch, {}, results, acc)
        docs = [s for s in closure["sediments"] if s["type"] == "doc"]
        assert len(docs) == 1
        assert docs[0]["pending"] == ["N2"]
        assert docs[0]["mode"] == "async_stub"

    def test_all_pass_no_doc(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        closure = _call_default_closer(
            orch, {}, [_result()], _pass_acceptance())
        assert not [s for s in closure["sediments"] if s["type"] == "doc"]


class TestFailOpen:
    """FAIL-OPEN：acceptance=None 退化为只走认知分流；非法输入不抛错。"""

    def test_none_acceptance_only_cognitive(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        closure = _call_default_closer(orch, {}, [_result()], None)
        assert closure["sediments"] == []
        assert closure["settled"] is True
        assert closure["compressed"] is True
        assert fake.records, "acceptance=None 仍须走认知分流"
        assert closure["cognitive"]["memory_id"] == "VM-fake-001"

    def test_malformed_acceptance_no_raise(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        closure = _call_default_closer(orch, {}, [], {"verdict": None})
        assert closure["settled"] is True
        assert isinstance(closure["sediments"], list)


# ------------------------------------------------------------
# 编排集成：handle() 输出 closure 含 sediments + cognitive
# ------------------------------------------------------------

class TestOrchestratorIntegration:
    """端到端：C 层结果 → A 层验收 → G 层四分流。"""

    def _run(self, fake, action="CONTINUE"):
        orch = _make_orchestrator(
            fake,
            c_executor=lambda router, node: {"action": action},
        )
        return orch.handle("分析一下市场情绪", memories=[])

    def test_handle_closure_has_sediments_and_cognitive(self):
        fake = _FakeCognitive()
        out = self._run(fake)
        closure = out["closure"]
        assert closure["settled"] is True
        assert closure["compressed"] is True
        assert "sediments" in closure
        assert "cognitive" in closure
        assert closure["cognitive"]["memory_id"] == "VM-fake-001"
        # 单节点 CONTINUE → pass → 案例分流出现
        assert any(s["type"] == "case" for s in closure["sediments"])

    def test_handle_fail_node_emits_skill_sediment(self):
        fake = _FakeCognitive()
        out = self._run(fake, action="FAILED")
        closure = out["closure"]
        assert any(s["type"] == "skill" for s in closure["sediments"])
        assert fake.verifies and fake.verifies[0]["success"] is False

    def test_handle_l1_direct_no_closure(self):
        fake = _FakeCognitive()
        orch = _make_orchestrator(fake)
        # 高置信+高密度记忆 → L1_DIRECT 不编排
        from types import SimpleNamespace
        mems = [SimpleNamespace(score=0.95, content="x") for _ in range(5)]
        out = orch.handle("test", memories=mems)
        assert out["route"] == "L1_DIRECT"
        assert out["closure"] is None
        assert not fake.records
