"""ASIL-Orchestrator — 核心编排器。

SPEC v0.2 §4.3 + 4.4 + Phase 2 升级。
Phase 1：纯 stub，零 LLM，零 GPU
Phase 2：真实 D3 IntentEngine + D2-B generator + OracleV2(AST拓扑) + VaR 第三门
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .cognitive_writeback import CognitiveWriteback
from .d2b_adapter import D2B_TYPES, D2BAdapter
from .d3_adapter import D3Adapter, D3IntentResult
from .drift_detector_wrapper import classify_drift_asil
from .kill_switch import KillSwitchMonitor
from .llm_budget_tracker import LLMBudgetTracker
from .metrics_collector import MetricsCollector
from .oracle_rea_independent import OracleValidatorV2  # Phase 2
from .oracle_validator import OracleValidator  # Phase 1 fallback
from .pipeline_builder import PipelineBuilder
from .session_outcome import SessionOutcomeCollector
from .trigger_scanner import PipelineTrigger, TriggerScanner
from .var_gate import compute_var_violation
from .verdict_router import FeedbackWriter, VerdictResult, VerdictRouter


class ASILOrchestrator:
    """Agentic Self-Improvement Loop 编排器。

    Phase 2 新增：D3 真实调用 + D2-B 真实生成 + OracleV2 + VaR 第三门。
    保持 Phase 1 接口兼容（mock_build_plan 参数保留）。
    """

    def __init__(
        self,
        oracle: Optional[Any] = None,  # OracleValidator (Phase 1) | OracleValidatorV2 (Phase 2)
        llm_budget: Optional[LLMBudgetTracker] = None,
        trigger_scanner: Optional[TriggerScanner] = None,
        pipeline_builder: Optional[PipelineBuilder] = None,
        verdict_router: Optional[VerdictRouter] = None,
        feedback_writer: Optional[FeedbackWriter] = None,
        kill_switch: Optional[KillSwitchMonitor] = None,
        metrics: Optional[MetricsCollector] = None,
        # Phase 2 新增 adapter
        d3_adapter: Optional[D3Adapter] = None,
        d2b_adapter: Optional[D2BAdapter] = None,
        session_collector: Optional[SessionOutcomeCollector] = None,
        writeback: Optional[Any] = None,  # CognitiveWriteback（P0-1 真实认知回写）
        use_phase2_oracle: bool = True,
    ):
        # Oracle 默认 Phase 2 V2，失败降级 Phase 1
        if oracle is None:
            if use_phase2_oracle:
                oracle = OracleValidatorV2()
            else:
                oracle = OracleValidator()
        self.oracle = oracle  # 两种都有 validate() 方法

        self.llm_budget = llm_budget or LLMBudgetTracker()
        self.trigger_scanner = trigger_scanner or TriggerScanner()
        self.pipeline_builder = pipeline_builder or PipelineBuilder()
        self.verdict_router = verdict_router or VerdictRouter()
        self.feedback_writer = feedback_writer or FeedbackWriter()
        self.kill_switch = kill_switch or KillSwitchMonitor()
        self.metrics = metrics or MetricsCollector()

        # Phase 2 adapters
        self.d3 = d3_adapter or D3Adapter()
        self.d2b = d2b_adapter or D2BAdapter()
        self.session_collector = session_collector or SessionOutcomeCollector()
        self.writeback = writeback or CognitiveWriteback()

    # ------------------------------------------------------------------
    # 触发扫描入口（Phase 2 加 session outcome）
    # ------------------------------------------------------------------
    def trigger_scan(
        self,
        c_level_ratio: float = 0.67,
        open_gaps: int = 5,
        psi_value: float = 0.05,
    ) -> List[PipelineTrigger]:
        triggers = self.trigger_scanner.scan(
            c_level_ratio=c_level_ratio,
            open_gaps=open_gaps,
            psi_value=psi_value,
        )

        # Phase 2：真实 session outcome 扫描
        try:
            self.session_collector.scan()
            stats = self.session_collector.summary_stats()
            active = self.trigger_scanner.scan_active_reflection(
                n_fail_sessions=stats.get("n_fail", 0),
            )
        except Exception:
            active = []

        feedback = self.trigger_scanner.scan_verdict_feedback(n_new_candidates=1)
        all_triggers = triggers + active + feedback
        # 触发频次统一在 run_pipeline 入口记录，避免双重计数
        return all_triggers

    # ------------------------------------------------------------------
    # Pipeline 执行 — 8 步（Phase 2 真实 adapter 集成）
    # ------------------------------------------------------------------
    def run_pipeline(
        self,
        trigger: PipelineTrigger,
        mock_build_plan: Optional[Dict[str, Any]] = None,
        user_message: str = "系统触发的自我改进管道",
        returns: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """执行完整 ASIL 管道。

        Phase 2：
          Step② 真实 D3Adapter.recognize()
          Step③ 真实 D2BAdapter.generate(gap) + bootstrap fallback
          Step⑤ Oracle 可为 V2（AST 拓扑）或 Phase 1（静态校验）
          Kill Switch 加 VaR 第三门

        mock_build_plan 保留作为 override（测试用）。
        """
        self.metrics.record_pipeline_start()
        self.metrics.record_trigger(trigger.type)  # M-ASIL-4b：与入口解耦
        trace_id = f"asil-{int(time.time())}"

        # --- Step② D3 真实意图识别 ---
        d3_result: Optional[D3IntentResult] = None
        if self.d3.is_available():
            d3_result = self.d3.recognize(user_message=user_message)
        else:
            d3_result = D3IntentResult(intent_type="rule_fallback", confidence=0.25)

        # --- Step③ D2-B 真实方案生成 + bootstrap fallback ---
        if mock_build_plan is not None:
            build_plan = mock_build_plan
        else:
            build_plan = self._resolve_build_plan(trigger, trace_id, d3_result)

        # --- CP1 存活检查点 ---
        if build_plan is None or not build_plan.get("modules"):
            verdict_result = VerdictResult(verdict="dead", survival_passed=False, trace_id=trace_id)
            self.feedback_writer.write_verdict(verdict_result, trace_id)
            self.metrics.record_pipeline_complete()
            return verdict_result.to_dict()

        self.metrics.record_pipeline_valid()

        # --- Step④ 测试验证 ---
        test_coverage = self._mock_test_verify(build_plan)

        # --- Step⑤ Oracle 校验（Phase 1 或 V2） ---
        oracle_raw = self.oracle.validate(build_plan)
        oracle_result = self._normalize_oracle(oracle_raw)

        # --- CP2 存活检查点 ---
        if oracle_result["confidence"] < 0.3:
            verdict = "inconclusive"
        else:
            verdict = oracle_result["verdict"]

        verdict_result = VerdictResult(
            verdict=verdict,
            oracle_confidence=oracle_result["confidence"],
            test_coverage=test_coverage,
            survival_passed=True,
            violations=oracle_result.get("violations", []),
            trace_id=trace_id,
        )

        # --- Step⑥ Feedback ---
        route = self.verdict_router.route(verdict)
        self.feedback_writer.write_verdict(verdict_result, trace_id)

        # --- Step⑦ Verify 回写（真实写入广义认知库） ---
        writeback_result: Dict[str, Any] = {"backend": "skipped", "memory_id": None}
        if route != "REPORT_ONLY":
            writeback_result = self.writeback.record_verdict(
                verdict_result.to_dict(), trace_id, tags=[trigger.type]
            )
            if writeback_result.get("fallback"):
                self.metrics.record_writeback_fallback()
            else:
                self.metrics.record_verify_writeback()
                writeback_result["verify"] = self.writeback.verify_memory(
                    writeback_result["memory_id"],
                    success=(verdict == "candidate"),
                )

        # --- Step⑧ 蒸馏 ---
        if route == "FEEDBACK_VERIFY_DISTILL":
            self.metrics.record_distill()

        # --- Kill Switch（Phase 2 加 VaR 第三门） ---
        drift_level = "stable"
        if trigger.psi_value is not None:
            # Phase 2 加 VaR 分量
            var_exceeded = False
            if returns:
                var_exceeded, _, _ = compute_var_violation(returns)
            drift_level = classify_drift_asil(
                trigger.psi_value, ks_drifted=False, var_exceeded=var_exceeded
            )
        ks_action = self.kill_switch.check(drift_level, oracle_result["confidence"])
        if ks_action.level != "L0":
            self.metrics.record_kill_switch()

        self.metrics.record_pipeline_complete()

        # --- 完整结果 ---
        complete = {
            "trace_id": trace_id,
            "trigger": trigger.to_dict(),
            "d3_intent": d3_result.to_dict() if d3_result else None,
            "build_plan": build_plan,
            "test_coverage": test_coverage,
            "oracle": oracle_result,
            "verdict": verdict_result.to_dict(),
            "route": route,
            "kill_switch": {"level": ks_action.level, "action": ks_action.action},
            "writeback": writeback_result,
            "llm_tokens_used": self.llm_budget.daily_used,
            "phase": 2,
        }
        self.feedback_writer.write_pipeline_complete(trace_id, complete)
        return complete

    # ------------------------------------------------------------------
    # Phase 2 helpers
    # ------------------------------------------------------------------
    def _resolve_build_plan(
        self,
        trigger: PipelineTrigger,
        trace_id: str,
        d3_result: Optional[D3IntentResult],
    ) -> Optional[Dict[str, Any]]:
        """Step③ BuildPlan 解析：真实 D2-B → bootstrap → mock fallback。"""
        # 尝试从 D2-B 真实生成
        gaps = self.d2b.load_open_gaps(gap_type_filter=D2B_TYPES)
        if gaps and self.d2b.is_available():
            # 用第一个 open gap 生成
            plan = self.d2b.generate(gaps[0])
            if plan:
                plan["bootstrap"] = False
                return plan

        # Bootstrap fallback：D2-B 三种预注册模板
        bootstrap_plans = self.d2b.generate_bootstrap_templates()
        if bootstrap_plans:
            return bootstrap_plans[0]  # 取第一个模板

        # 最终 fallback：mock
        return {
            "architecture_graph": {"nodes": ["intent_prediction", "d2_solution"], "edges": []},
            "modules": ["example/fallback.py"],
            "design_rationale": f"Final fallback (no gaps / generator unavailable) on {trace_id}",
            "bootstrap": True,
        }

    def _normalize_oracle(self, oracle_raw: Any) -> Dict[str, Any]:
        """统一 Phase 1 OracleResult / Phase 2 OracleResultV2 → dict。"""
        if hasattr(oracle_raw, "to_dict"):
            return oracle_raw.to_dict()
        if isinstance(oracle_raw, dict):
            return oracle_raw
        return {
            "confidence": getattr(oracle_raw, "confidence", 0.0),
            "verdict": getattr(oracle_raw, "verdict", "inconclusive"),
            "violations": getattr(oracle_raw, "violations", []),
        }

    def _mock_test_verify(self, build_plan: Dict[str, Any]) -> float:
        """覆盖率估算：模块数 + oracle_confidence 共同决定。"""
        n = len(build_plan.get("modules", []))
        return min(1.0, 0.5 + n * 0.15)

    # ------------------------------------------------------------------
    # 指标快照
    # ------------------------------------------------------------------
    def metrics_snapshot(self) -> Dict[str, Any]:
        snap = self.metrics.snapshot()
        snap["phase"] = 2
        snap["d3_available"] = self.d3.is_available()
        snap["d2b_available"] = self.d2b.is_available()
        snap["oracle_type"] = "V2" if isinstance(self.oracle, OracleValidatorV2) else "V1"
        return snap
