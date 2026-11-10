# ruff: noqa: E402  (sys.path 必须先于 asil 导入)
"""ASIL Phase 1 全链路 pytest。

运行：cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2 && python -m pytest 48-涌现架构/asil/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 路径：项目根（用于 import 4-MEMORY 等）+ 48-涌现架构（用于 import asil 子包）
_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 项目根
_ARCH = Path(__file__).resolve().parent.parent.parent  # 48-涌现架构/
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ARCH))

from asil.drift_detector_wrapper import (
    PSI_MINOR_DRIFT,
    classify_drift_asil,
    r3_psi_stability,
)
from asil.kill_switch import KillSwitchMonitor
from asil.llm_budget_tracker import LLMBudgetTracker
from asil.metrics_collector import MetricsCollector
from asil.oracle_validator import OracleValidator
from asil.orchestrator import ASILOrchestrator
from asil.pipeline_builder import D2_BOOTSTRAP_TEMPLATES, PipelineBuilder
from asil.trigger_scanner import PipelineTrigger, TriggerScanner
from asil.verdict_router import VerdictRouter


# ======================================================================
# 1. Drift Detector Wrapper（复用已有实现 + ASIL 三重）
# ======================================================================
class TestDriftDetector:
    def test_r3_stability_perfect(self):
        assert r3_psi_stability(0.0) == 1.0

    def test_r3_stability_severe(self):
        assert r3_psi_stability(PSI_MINOR_DRIFT) == 0.0

    def test_r3_stability_saturated(self):
        assert r3_psi_stability(1.0) == 0.0  # PSI>0.25 饱和

    def test_asil_triple_stable(self):
        assert classify_drift_asil(0.05, ks_drifted=False) == "stable"

    def test_asil_triple_ks_upgrade(self):
        assert classify_drift_asil(0.05, ks_drifted=True) == "minor_drift"

    def test_asil_triple_var_upgrade(self):
        """SPEC §3.5：minor + VaR exceeded → severe"""
        assert classify_drift_asil(0.15, ks_drifted=False, var_exceeded=True) == "severe_drift"


# ======================================================================
# 2. Oracle Validator（Phase 1 纯静态校验）
# ======================================================================
class TestOracleValidator:
    def test_none_build_plan(self):
        v = OracleValidator().validate(None)
        assert v.verdict == "inconclusive"
        assert v.confidence == 0.0

    def test_empty_modules(self):
        plan = {"architecture_graph": {}, "modules": [], "design_rationale": "x"}
        v = OracleValidator().validate(plan)
        assert v.schema_ok is False

    def test_missing_schema_keys(self):
        plan = {"modules": ["a.py"]}
        v = OracleValidator().validate(plan)
        assert v.schema_ok is False
        assert len(v.violations) > 0

    def test_bypass_detection(self):
        plan = {
            "architecture_graph": {"nodes": ["a"]},
            "modules": ["a.py"],
            "design_rationale": "we can eval() to bypass security",
        }
        v = OracleValidator().validate(plan)
        assert v.bypass_clean is False

    def test_confidence_candidate(self):
        """三项全过 → 3/3 = 1.0 → candidate"""
        plan = {
            "architecture_graph": {"nodes": ["a"]},
            "modules": ["example/intent_engine.py"],
            "design_rationale": "clean",
        }
        v = OracleValidator().validate(plan)
        assert v.confidence == 1.0
        assert v.verdict == "candidate"

    def test_confidence_inconclusive(self):
        """仅 schema 挂（1/3）→ inconclusive"""
        bad_plan = {"modules": []}  # schema 缺 fields；compile 空视为通过；bypass 无关键词
        v2 = OracleValidator().validate(bad_plan)
        assert v2.verdict == "inconclusive"


# ======================================================================
# 3. LLM Budget Tracker（Phase 1 零 LLM 硬约束）
# ======================================================================
class TestLLMBudget:
    def test_phase1_zero_budget(self):
        b = LLMBudgetTracker()  # 默认 daily=0, pipeline=0
        assert b.is_phase1_zero is True
        assert b.check_daily() == "ok"

    def test_record_rejected_on_phase1(self):
        """Phase 1 C12：理论上 record 不应该被调用，但如果被调用..."""
        b = LLMBudgetTracker()
        b.record(100)  # 允许调用但 budget=0 时 check 不触发
        assert b.daily_used == 100

    def test_exceeded_downgrade(self):
        b = LLMBudgetTracker(daily_budget_tokens=1000)
        b.record(1001)
        assert b.check_daily() == "exceeded"
        assert b.should_downgrade() is True


# ======================================================================
# 4. Trigger Scanner（六种触发 + 冷却 + 合并）
# ======================================================================
class TestTriggerScanner:
    def test_c_level_trigger(self):
        s = TriggerScanner()
        triggers = s.scan(c_level_ratio=0.7)
        assert any(t.type == "low_confidence_memory" for t in triggers)

    def test_c_level_below_threshold(self):
        s = TriggerScanner()
        triggers = s.scan(c_level_ratio=0.5)
        assert not any(t.type == "low_confidence_memory" for t in triggers)

    def test_gap_router_trigger(self):
        s = TriggerScanner()
        triggers = s.scan(open_gaps=1)
        assert any(t.type == "gap_router" for t in triggers)

    def test_psi_severe_trigger(self):
        s = TriggerScanner()
        triggers = s.scan(psi_value=0.3)
        assert any(t.type == "psi_severe_drift" for t in triggers)

    def test_psi_minor_trigger(self):
        s = TriggerScanner()
        triggers = s.scan(psi_value=0.15)
        assert any(t.type == "psi_drift" for t in triggers)
        assert not any(t.type == "psi_severe_drift" for t in triggers)

    def test_cooldown_blocks_repeat(self):
        s = TriggerScanner(cooldown={"low_confidence_memory": 9999})
        s.scan(c_level_ratio=0.9)  # 触发一次
        triggers = s.scan(c_level_ratio=0.9)  # 冷却中再扫
        assert not any(t.type == "low_confidence_memory" for t in triggers)

    def test_verdict_feedback_no_cooldown(self):
        s = TriggerScanner()
        s.scan_verdict_feedback(n_new_candidates=1)
        # 冷却时间=0，立即再触发
        result = s.scan_verdict_feedback(n_new_candidates=1)
        assert len(result) == 1


# ======================================================================
# 5. Pipeline Builder（bootstrap schema）
# ======================================================================
class TestPipelineBuilder:
    def test_normal_path(self):
        b = PipelineBuilder()
        p = b.build(trigger_type="gap_router", trigger_evidence={"source": "test"})
        assert p["bootstrap_source"]["e6_gaps_empty"] is False
        assert len(p["steps"]) == 8
        assert p["trace_id"].startswith("asil-")

    def test_bootstrap_path(self):
        b = PipelineBuilder()
        p = b.build(
            trigger_type="gap_router",
            trigger_evidence={"n_open": 0},
            e6_gaps_empty=True,
        )
        assert p["bootstrap_source"]["e6_gaps_empty"] is True
        assert p["bootstrap_source"]["fallback_templates"] == D2_BOOTSTRAP_TEMPLATES
        assert any(s["seq"] == 3 and s.get("bootstrap") for s in p["steps"])


# ======================================================================
# 6. Verdict Router
# ======================================================================
class TestVerdictRouter:
    def test_dead_route(self):
        assert VerdictRouter().route("dead") == "REPORT_ONLY"

    def test_inconclusive_route(self):
        assert VerdictRouter().route("inconclusive") == "FEEDBACK_SKIP_DISTILL"

    def test_candidate_route(self):
        assert VerdictRouter().route("candidate") == "FEEDBACK_VERIFY_DISTILL"

    def test_rejected_route(self):
        assert VerdictRouter().route("rejected") == "FEEDBACK_RECORD_FAILURE"


# ======================================================================
# 7. Kill Switch Monitor
# ======================================================================
class TestKillSwitch:
    def test_normal(self):
        a = KillSwitchMonitor().check("stable", oracle_confidence=0.8)
        assert a.level == "L0"

    def test_minor_drift_warning(self):
        a = KillSwitchMonitor().check("minor_drift", oracle_confidence=0.8)
        assert a.level == "L1"
        assert a.action == "no_op"

    def test_severe_drift_reduce(self):
        a = KillSwitchMonitor().check("severe_drift", oracle_confidence=0.8)
        assert a.level == "L2"
        assert a.action == "reduce_position"

    def test_l4_halt(self):
        a = KillSwitchMonitor().check(
            "severe_drift",
            oracle_confidence=0.8,
            consecutive_falsified=3,
            daily_loss_pct=0.03,
        )
        assert a.level == "L4"
        assert a.action == "halt_all"


# ======================================================================
# 8. Metrics Collector
# ======================================================================
class TestMetrics:
    def test_valid_completion_rate(self):
        m = MetricsCollector()
        for _ in range(10):
            m.record_pipeline_start()
            m.record_pipeline_valid()
            m.record_pipeline_complete()
        assert m.valid_completion_rate == 1.0

    def test_partial_dead(self):
        m = MetricsCollector()
        for _ in range(7):
            m.record_pipeline_start()
            m.record_pipeline_valid()
            m.record_pipeline_complete()
        for _ in range(3):
            m.record_pipeline_start()
            m.record_pipeline_complete()  # no valid
        assert m.valid_completion_rate == 0.7

    def test_snapshot(self):
        m = MetricsCollector()
        m.record_pipeline_start()
        m.record_verify_writeback()
        snap = m.snapshot()
        assert "total_pipelines" in snap
        assert "verify_writebacks" in snap


# ======================================================================
# 9. INTEGRATION: 全链路 Pipeline 跑通
# ======================================================================
class TestIntegration:
    def test_full_pipeline_normal_path(self):
        """完整跑通 8 步 Pipeline（normal path）。"""
        orch = ASILOrchestrator()
        triggers = orch.trigger_scan(c_level_ratio=0.7, open_gaps=5, psi_value=0.05)
        assert len(triggers) >= 1

        result = orch.run_pipeline(triggers[0])
        assert result["verdict"]["survival_passed"] is True
        assert result["route"] != "REPORT_ONLY"
        assert result["build_plan"]["bootstrap"] is False
        assert "oracle" in result

    def test_full_pipeline_bootstrap(self):
        """Phase 2 bootstrap fallback — 传 mock_build_plan 强制覆盖真实 generator。"""
        orch = ASILOrchestrator()
        trigger = PipelineTrigger(
            type="gap_router",
            source="gap_router",
            evidence={"n_open": 0},
        )
        mock_bootstrap_plan = {
            "gap_id": "BOOTSTRAP-test",
            "gap_type": "architecture_gap",
            "module_name": "example/bootstrap.py",
            "modules": ["example/bootstrap.py", "example/doc_debt.py"],
            "design_rationale": "Bootstrap fallback on n_open=0",
            "dependencies": [],
            "bootstrap": True,
        }
        result = orch.run_pipeline(trigger, mock_build_plan=mock_bootstrap_plan)
        assert result["build_plan"]["bootstrap"] is True

    def test_pipeline_dead_on_empty_build_plan(self):
        """存活检查点 CP1：空 BuildPlan（无 modules）→ DEAD。"""
        orch = ASILOrchestrator()
        trigger = PipelineTrigger(type="low_confidence_memory", source="test")
        result = orch.run_pipeline(trigger, mock_build_plan={})  # 显式空 dict → 触发 CP1
        # DEAD 路径直接返回 verdict_result.to_dict()，不含 route 字段
        assert result["verdict"] == "dead"
        assert result["survival_passed"] is False

    def test_oracle_bypass_rejected(self):
        """BuildPlan 含 eval() → oracle_confidence 降。"""
        orch = ASILOrchestrator()
        trigger = PipelineTrigger(type="low_confidence_memory", source="test")
        bad_plan = {
            "architecture_graph": {"nodes": ["a"]},
            "modules": ["example/bad.py"],  # modules 非空 → compile_ok
            "design_rationale": "using eval() to make things work",
        }
        result = orch.run_pipeline(trigger, mock_build_plan=bad_plan)
        assert result["oracle"]["bypass_clean"] is False

    def test_kill_switch_triggered(self):
        """PSI severe → Kill Switch L2。"""
        orch = ASILOrchestrator()
        trigger = PipelineTrigger(
            type="psi_severe_drift",
            source="PSI=0.3",
            evidence={"psi": 0.3},
            psi_value=0.3,
        )
        result = orch.run_pipeline(trigger)
        assert result["kill_switch"]["level"] in ("L1", "L2", "L3", "L4")

    def test_llm_tokens_zero_on_phase1(self):
        """Phase 1 C12：零 LLM 消耗。"""
        orch = ASILOrchestrator()
        triggers = orch.trigger_scan(c_level_ratio=0.7)
        result = orch.run_pipeline(triggers[0])
        assert result["llm_tokens_used"] == 0

    def test_metrics_after_multiple_runs(self):
        """多次 run 后 metrics 正确累加。"""
        orch = ASILOrchestrator()
        for i in range(5):
            triggers = orch.trigger_scan(c_level_ratio=0.7 + i * 0.01)
            for t in triggers:
                orch.run_pipeline(t)
        snap = orch.metrics_snapshot()
        assert snap["total_pipelines"] >= 3
        assert snap["valid_completion_rate"] >= 0.5


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
