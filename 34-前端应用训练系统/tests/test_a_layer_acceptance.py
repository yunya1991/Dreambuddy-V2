# -*- coding: utf-8 -*-
"""P3.4: A 层 OKR 验收器测试（RED）— C 层执行结果回传 A 层做节点验收。

依据: SPEC-v1.2-SACG-orchestration.md §2.2（执行结果回传 A 层验收）+ PLAN-L0L1L2 P3.4。
借鉴:
  - dream-acceptance-verify SKILL: 三态判定(pass/degraded/fail)+证据必录+FAIL-OPEN 但必记录+红旗清单
  - CI Quality Gate: 显式规则集 + warning-only 中间档
  - 金融对账: 逐节点双向核对（非总额）+差异分类(result_missing/extras/action_rejected)
粒度区分: Reflector(CDriveV3Router) 管执行内过程决策（单步毫秒级），本模块管节点级结果验收。
约束: 禁新阈值（不复用 0.7/3/0.3 之外的任何数值判定）、全程 FAIL-OPEN。

验收规则（按 verify 类型分派）:
  c_action:        action∉{REDO,EARLY_TERMINATE,FAILED} 且无 error → pass
                   action=REDO 或带 error → degraded
                   action=EARLY_TERMINATE/FAILED 或 result 缺失 → fail
  evidence_backed / gap_closed: 首版不做证据比对 → action 正常时 degraded(evidence_pending)
整体 verdict: any fail → fail；else any degraded/extras → degraded；else pass；空节点 → degraded
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.okr_acceptance import (  # noqa: E402
    FINANCE_DOMAIN,
    VERDICT_DEGRADED,
    VERDICT_FAIL,
    VERDICT_PASS,
    evaluate_nodes,
)
from core.okr_nodes import (  # noqa: E402
    VERIFY_C_ACTION,
    VERIFY_EVIDENCE,
    VERIFY_GAP,
    decompose_okr_nodes,
)
from core.sacg_orchestrator import SACGOrchestrator  # noqa: E402


def _node(node_id="N1", verify=VERIFY_C_ACTION, **kw):
    n = {"node_id": node_id, "objective": "obj", "criteria": "crit",
         "source": "plan_item", "verify": verify}
    n.update(kw)
    return n


def _result(node_id="N1", action="CONTINUE", **kw):
    r = {"node_id": node_id, "action": action, "tier": "Tier1",
         "effort_level": "light", "detail": {}}
    r.update(kw)
    return r


class TestCActionVerdict:
    def test_continue_passes(self):
        out = evaluate_nodes([_node()], [_result()])
        v = out["node_verdicts"][0]
        assert v["verdict"] == VERDICT_PASS
        assert v["node_id"] == "N1"
        assert out["verdict"] == VERDICT_PASS
        assert out["red_flags"] == []

    def test_insert_before_passes(self):
        out = evaluate_nodes([_node()], [_result(action="INSERT_BEFORE")])
        assert out["node_verdicts"][0]["verdict"] == VERDICT_PASS

    def test_redo_is_degraded(self):
        """REDO = 反思门要求重做，结果待定（非硬失败）"""
        out = evaluate_nodes([_node()], [_result(action="REDO")])
        v = out["node_verdicts"][0]
        assert v["verdict"] == VERDICT_DEGRADED
        assert out["verdict"] == VERDICT_DEGRADED
        assert out["red_flags"] == []

    def test_early_terminate_fails(self):
        out = evaluate_nodes([_node()], [_result(action="EARLY_TERMINATE")])
        v = out["node_verdicts"][0]
        assert v["verdict"] == VERDICT_FAIL
        assert out["verdict"] == VERDICT_FAIL
        assert "N1" in out["red_flags"]

    def test_node_failed_fails(self):
        out = evaluate_nodes([_node()], [_result(action="FAILED", error="boom")])
        assert out["node_verdicts"][0]["verdict"] == VERDICT_FAIL
        assert out["verdict"] == VERDICT_FAIL

    def test_error_with_ok_action_is_degraded(self):
        """action 正常但 result 带 error 记录 → degraded（证据必录）"""
        out = evaluate_nodes([_node()], [_result(error="warn")])
        assert out["node_verdicts"][0]["verdict"] == VERDICT_DEGRADED


class TestEvidenceVerifyTypes:
    def test_evidence_backed_pending(self):
        """首版不做证据比对：action 正常 → degraded(evidence_pending)"""
        out = evaluate_nodes(
            [_node(verify=VERIFY_EVIDENCE, evidence_id="EV-1")], [_result()])
        v = out["node_verdicts"][0]
        assert v["verdict"] == VERDICT_DEGRADED
        assert v["reason"] == "evidence_pending"

    def test_gap_closed_pending(self):
        out = evaluate_nodes([_node(verify=VERIFY_GAP)], [_result()])
        assert out["node_verdicts"][0]["verdict"] == VERDICT_DEGRADED
        assert out["node_verdicts"][0]["reason"] == "evidence_pending"

    def test_evidence_type_still_fails_on_bad_action(self):
        out = evaluate_nodes(
            [_node(verify=VERIFY_EVIDENCE)], [_result(action="FAILED")])
        assert out["node_verdicts"][0]["verdict"] == VERDICT_FAIL


class TestReconciliation:
    def test_missing_result_fails(self):
        """对账差异: 节点有、结果无 → fail(result_missing)"""
        out = evaluate_nodes([_node("N1"), _node("N2")], [_result("N1")])
        assert out["node_verdicts"][1]["verdict"] == VERDICT_FAIL
        assert out["node_verdicts"][1]["reason"] == "result_missing"
        assert out["verdict"] == VERDICT_FAIL

    def test_extra_result_recorded_and_caps_overall(self):
        """对账差异: 结果有、节点无 → 记入 extras 且整体封顶 degraded"""
        out = evaluate_nodes([_node("N1")], [_result("N1"), _result("N9")])
        assert out["extras"] == ["N9"]
        assert out["verdict"] == VERDICT_DEGRADED

    def test_counts_and_red_flags(self):
        nodes = [_node("N1"), _node("N2"), _node("N3")]
        results = [_result("N1"), _result("N2", action="REDO"),
                   _result("N3", action="FAILED")]
        out = evaluate_nodes(nodes, results)
        assert out["counts"] == {"pass": 1, "degraded": 1, "fail": 1}
        assert out["red_flags"] == ["N3"]
        assert out["verdict"] == VERDICT_FAIL

    def test_empty_nodes_degraded(self):
        out = evaluate_nodes([], [])
        assert out["verdict"] == VERDICT_DEGRADED

    def test_fail_open_on_malformed_input(self):
        """FAIL-OPEN: 非法输入不抛错"""
        out = evaluate_nodes(None, None)
        assert out["verdict"] == VERDICT_DEGRADED


class FakeRouter:
    def __init__(self, action="CONTINUE"):
        self._action = action

    def run_v3(self, node_id, result, state, signals=None, l1_intent_hint=None):
        return {"action": self._action, "tier": "Tier1", "effort_level": "light"}


class TestOrchestratorAcceptanceIntegration:
    def test_handle_output_has_acceptance(self):
        """C 层结果回传 A 层验收: handle() 输出携带 acceptance 字段"""
        orch = SACGOrchestrator(router=FakeRouter())
        out = orch.handle("这次FOMC怎么看", l1_intent_hint="event_analysis",
                          memories=[])
        assert "acceptance" in out
        acc = out["acceptance"]
        assert acc["verdict"] in (VERDICT_PASS, VERDICT_DEGRADED, VERDICT_FAIL)
        # plan_item 节点 + CONTINUE → 全 pass
        assert acc["verdict"] == VERDICT_PASS
        assert len(acc["node_verdicts"]) == len(out["nodes"])

    def test_acceptance_reflects_failed_node(self):
        orch = SACGOrchestrator(router=FakeRouter(action="EARLY_TERMINATE"))
        out = orch.handle("这次FOMC怎么看", l1_intent_hint="event_analysis",
                          memories=[])
        assert out["acceptance"]["verdict"] == VERDICT_FAIL
        assert out["acceptance"]["red_flags"]

    def test_flow_unchanged(self):
        """验收不阻断主流程: stages/action/node_results 保持原样"""
        orch = SACGOrchestrator(router=FakeRouter(action="FAILED"))
        out = orch.handle("这次FOMC怎么看", l1_intent_hint="event_analysis",
                          memories=[])
        assert out["stages"] == ["S", "A", "C", "G"]
        assert out["action"] == "PROCEED"
        assert out["node_results"]


# ============================================================
# 金融调研探索四维验收（与代码开发验收分流）
# 维度: 实践(广义认知系统实践成果) + 理论支持(金融理论) + 回测验证 + 数据真实(不能造数据)
# 证据载体: result.detail.finance_evidence = {practice, theory, backtest, data_source}
# 规则: 数据造假 → fail(硬门,不能造数据)；数据无来源 → degraded(data_unverified)；
#       实践/理论/回测缺失 → degraded({dim}_pending, 首版规则化)；其余不拓展
# ============================================================

class TestFinanceDomainMarking:
    """节点 domain 标记: item 显式 > plan 级显式 > research_request 推断"""

    def test_research_request_marks_finance_domain(self):
        plan = {"plan_items": ["背景梳理", "影响推演"],
                "research_request": {"message": "x", "mode": "stub"}}
        nodes = decompose_okr_nodes(plan)
        assert all(n["domain"] == FINANCE_DOMAIN for n in nodes)

    def test_plan_level_domain(self):
        plan = {"domain": FINANCE_DOMAIN, "plan_items": ["x"]}
        assert decompose_okr_nodes(plan)[0]["domain"] == FINANCE_DOMAIN

    def test_item_domain_overrides(self):
        plan = {"domain": FINANCE_DOMAIN,
                "plan_items": ["x"],
                "engineering_okr": [{"okr": "y", "source": "rea_evidence",
                                     "domain": "code_dev"}]}
        nodes = decompose_okr_nodes(plan)
        assert nodes[0]["domain"] == "code_dev"

    def test_no_domain_by_default(self):
        nodes = decompose_okr_nodes({"plan_items": ["x"]})
        assert "domain" not in nodes[0]


def _finance_result(node_id="N1", action="CONTINUE", evidence=None):
    detail = {} if evidence is None else {"finance_evidence": evidence}
    return {"node_id": node_id, "action": action, "tier": "Tier1",
            "effort_level": "light", "detail": detail}


_FULL_EVIDENCE = {"practice": "VM-xxx 实践记忆", "theory": "利率平价理论",
                  "backtest": "washout 回测 2024 样本外验证", "data_source": "OKX API"}


class TestFinanceAcceptance:
    def _fin_node(self, node_id="N1"):
        return _node(node_id, domain=FINANCE_DOMAIN)

    def test_full_evidence_passes(self):
        out = evaluate_nodes([self._fin_node()],
                             [_finance_result(evidence=_FULL_EVIDENCE)])
        v = out["node_verdicts"][0]
        assert v["verdict"] == VERDICT_PASS
        assert v["dimensions"] == {"practice": "pass", "theory": "pass",
                                   "backtest": "pass", "data_source": "pass"}

    def test_missing_theory_degraded(self):
        ev = dict(_FULL_EVIDENCE, theory=None)
        out = evaluate_nodes([self._fin_node()], [_finance_result(evidence=ev)])
        v = out["node_verdicts"][0]
        assert v["verdict"] == VERDICT_DEGRADED
        assert v["dimensions"]["theory"] == "degraded"
        assert "theory_pending" in v["reasons"]

    def test_fabricated_data_fails(self):
        """数据真实是硬门: 造假标记 → fail(data_fabricated)，其余维度再好也 fail"""
        for fake in ("fabricated", "synthetic", "mock"):
            ev = dict(_FULL_EVIDENCE, data_source=fake)
            out = evaluate_nodes([self._fin_node()],
                                 [_finance_result(evidence=ev)])
            v = out["node_verdicts"][0]
            assert v["verdict"] == VERDICT_FAIL
            assert v["dimensions"]["data_source"] == "fail"
            assert "data_fabricated" in v["reasons"]

    def test_missing_data_source_degraded(self):
        ev = dict(_FULL_EVIDENCE, data_source=None)
        out = evaluate_nodes([self._fin_node()], [_finance_result(evidence=ev)])
        v = out["node_verdicts"][0]
        assert v["verdict"] == VERDICT_DEGRADED
        assert "data_unverified" in v["reasons"]

    def test_no_evidence_fail_open(self):
        """FAIL-OPEN: 无证据载体 → 全维 degraded 而非 fail"""
        out = evaluate_nodes([self._fin_node()], [_finance_result()])
        v = out["node_verdicts"][0]
        assert v["verdict"] == VERDICT_DEGRADED
        assert out["verdict"] == VERDICT_DEGRADED

    def test_bad_action_still_fails(self):
        """动作硬失败优先于维度评估"""
        out = evaluate_nodes(
            [self._fin_node()],
            [_finance_result(action="FAILED", evidence=_FULL_EVIDENCE)])
        assert out["node_verdicts"][0]["verdict"] == VERDICT_FAIL

    def test_non_finance_node_unchanged(self):
        """无 domain 节点仍走代码开发规则（CONTINUE → pass，无 dimensions）"""
        out = evaluate_nodes([_node()], [_result()])
        v = out["node_verdicts"][0]
        assert v["verdict"] == VERDICT_PASS
        assert "dimensions" not in v

    def test_orchestrator_finance_integration(self):
        """注入金融 domain 节点: 验收走四维分流"""
        def fin_decomposer(plan):
            return [_node("N1", domain=FINANCE_DOMAIN)]
        orch = SACGOrchestrator(router=FakeRouter(), a_decomposer=fin_decomposer)
        out = orch.handle("这次FOMC怎么看", l1_intent_hint="event_analysis",
                          memories=[])
        v = out["acceptance"]["node_verdicts"][0]
        # FakeRouter detail 无 finance_evidence → degraded（FAIL-OPEN）
        assert v["verdict"] == VERDICT_DEGRADED
        assert "dimensions" in v


# ============================================================
# 方案A 维度细分（调研拓展结论，规则化、禁新阈值）:
#   backtest:    含样本外/walk-forward 表述 → pass；仅样本内 → degraded(oos_pending)
#   data_source: 来源具体 → pass；含糊来源（"公开数据"等）→ degraded(source_vague)
# 依据: Bailey & López de Prado 样本外纪律 + FinGround 原子声明可溯源
# ============================================================

class TestFinanceSubRules:
    def _fin_node(self, node_id="N1"):
        return _node(node_id, domain=FINANCE_DOMAIN)

    def test_in_sample_only_backtest_degraded(self):
        """仅样本内回测 → degraded(oos_pending)：样本外才是唯一算数的意见"""
        ev = dict(_FULL_EVIDENCE, backtest="2024 样本内回测")
        out = evaluate_nodes([self._fin_node()], [_finance_result(evidence=ev)])
        v = out["node_verdicts"][0]
        assert v["verdict"] == VERDICT_DEGRADED
        assert v["dimensions"]["backtest"] == "degraded"
        assert "oos_pending" in v["reasons"]

    def test_walkforward_backtest_passes(self):
        for marker in ("walk-forward 2023-2024", "样本外滚动验证",
                       "out-of-sample test"):
            ev = dict(_FULL_EVIDENCE, backtest=marker)
            out = evaluate_nodes([self._fin_node()],
                                 [_finance_result(evidence=ev)])
            v = out["node_verdicts"][0]
            assert v["dimensions"]["backtest"] == "pass", marker
            assert v["verdict"] == VERDICT_PASS

    def test_vague_data_source_degraded(self):
        """来源含糊（"公开数据"/"网络"）→ degraded(source_vague)：不可核验"""
        for vague in ("公开数据", "网络", "公开资料", "网上资料"):
            ev = dict(_FULL_EVIDENCE, data_source=vague)
            out = evaluate_nodes([self._fin_node()],
                                 [_finance_result(evidence=ev)])
            v = out["node_verdicts"][0]
            assert v["dimensions"]["data_source"] == "degraded", vague
            assert "source_vague" in v["reasons"]
            assert v["verdict"] == VERDICT_DEGRADED

    def test_specific_data_source_passes(self):
        """具体来源（含 API/库名）→ pass；含糊词作为修饰不影响具体来源判定"""
        for src in ("OKX API 2024-01~2024-12", "Tushare Pro", "Wind 万得"):
            ev = dict(_FULL_EVIDENCE, data_source=src)
            out = evaluate_nodes([self._fin_node()],
                                 [_finance_result(evidence=ev)])
            assert out["node_verdicts"][0]["dimensions"]["data_source"] == "pass", src

    def test_fabricated_still_hard_fails(self):
        """造假硬门优先于含糊判定"""
        ev = dict(_FULL_EVIDENCE, data_source="fabricated")
        out = evaluate_nodes([self._fin_node()], [_finance_result(evidence=ev)])
        v = out["node_verdicts"][0]
        assert v["verdict"] == VERDICT_FAIL
        assert "data_fabricated" in v["reasons"]

    def test_missing_backtest_still_pending(self):
        """backtest 缺失仍是 backtest_pending（非 oos_pending）"""
        ev = dict(_FULL_EVIDENCE, backtest=None)
        out = evaluate_nodes([self._fin_node()], [_finance_result(evidence=ev)])
        v = out["node_verdicts"][0]
        assert "backtest_pending" in v["reasons"]
        assert "oos_pending" not in v["reasons"]
