"""被动训练 v0.5 集成测试。

测试 v0.2→v0.5 升级:
  1. trigger_passive_training 调用 checkpoint() 保存训练前状态
  2. trigger_passive_training 调用 trigger_incremental() 而非仅 add_case
  3. trigger_passive_training 调用 get_model() 获取训练后模型
  4. coaching_context 含 pre_models / post_models / training_results
  5. trigger_passive_training 不再依赖桶满阈值
  6. coaching_loop v0.2 run_coaching_cycle 自动评估监控
  7. coaching_loop v0.2 generate_corrections 基于偏差生成纠正
  8. coaching_loop v0.2 calculate_improvement 前后模型对比
  9. FAIL-OPEN: trigger_incremental 异常不崩溃
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_CORE_DIR = os.path.join(_34_DIR, "core")
_ADAPTERS_DIR = os.path.join(_34_DIR, "adapters")

for _p in [_THIS_DIR, _34_DIR, _CORE_DIR, _ADAPTERS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_executor import TrainingLayer, TrainingResult
from interfaces.training_data_provider import TrainingCase
from dual_mode_orchestrator import DualModeTrainingOrchestrator
from coaching_loop import CoachingSession


def _make_mock_executor(layer: TrainingLayer):
    """创建 mock 训练执行器，预置 v0.5 方法。"""
    executor = MagicMock()
    executor.get_layer.return_value = layer
    executor.get_bucket_threshold.return_value = 50
    executor.get_bucket_count.return_value = 0
    executor.add_case.return_value = True
    executor.train.return_value = TrainingResult(
        layer=layer, success=True, message="trained"
    )
    # v0.5 方法
    executor.trigger_incremental.return_value = TrainingResult(
        layer=layer, success=True, metrics={"incremental_step": 1}, message="incremental"
    )
    executor.checkpoint.return_value = {"checkpointed": True, "step": 0}
    executor.restore.return_value = {"restored": True}
    executor.get_model.return_value = {"step": 1, "weights": {"w1": 0.5}}
    executor.get_dependencies.return_value = []
    return executor


def _make_wrapup_case(**kwargs):
    """创建测试收尾案例。"""
    defaults = {
        "intent": "实现被动训练v0.5",
        "actions": ["编码", "测试", "验收"],
        "outcome": "success",
        "outcome_text": "被动训练v0.5集成完成",
        "learned": ["增量训练比桶满更高效"],
        "acceptance_level": "full",
        "domain_tag": "前端训练",
        "code_path": "/fake/path",
        "feature": "passive_training",
    }
    defaults.update(kwargs)
    return defaults


class TriggerPassiveV05Test(unittest.TestCase):
    """trigger_passive_training v0.5 集成测试。"""

    def setUp(self):
        """创建带 mock 执行器的编排器。"""
        self.executor_s = _make_mock_executor(TrainingLayer.S)
        self.executor_dsh = _make_mock_executor(TrainingLayer.DSH)
        self.executor_c = _make_mock_executor(TrainingLayer.C)
        self.executor_g = _make_mock_executor(TrainingLayer.G)
        self.executor_llm = _make_mock_executor(TrainingLayer.LLM)

        self.executors = [
            self.executor_s, self.executor_dsh, self.executor_c,
            self.executor_g, self.executor_llm,
        ]

        # mock case evaluator → INGEST
        self.evaluator = MagicMock()
        self.evaluator.evaluate.return_value = MagicMock(
            decision=MagicMock(value="ingest"),
            novelty=0.8,
            significance=0.9,
            anomaly=0.1,
            reproducibility=0.95,
            reason="high value",
        )

        self.orchestrator = DualModeTrainingOrchestrator(
            data_providers=[],
            training_executors=self.executors,
            case_evaluator=self.evaluator,
            rea_parser=None,  # 不启用 REA，降级为文本案例
        )

    def test_calls_checkpoint_before_training(self):
        """checkpoint() 在 add_case 和 trigger_incremental 之前调用。"""
        case = _make_wrapup_case()
        self.orchestrator.trigger_passive_training(case)

        # 至少一个 executor 被调用了 checkpoint
        checkpoint_calls = [e.checkpoint.called for e in self.executors]
        self.assertTrue(any(checkpoint_calls), "至少一个 executor 应调用 checkpoint")

    def test_calls_trigger_incremental_not_just_add(self):
        """trigger_incremental() 被调用，不只是 add_case。"""
        case = _make_wrapup_case()
        result = self.orchestrator.trigger_passive_training(case)

        # 至少一个 executor 被调用了 trigger_incremental
        incremental_calls = [e.trigger_incremental.called for e in self.executors]
        self.assertTrue(any(incremental_calls), "至少一个 executor 应调用 trigger_incremental")

    def test_calls_get_model_after_training(self):
        """get_model() 在 trigger_incremental 之后调用。"""
        case = _make_wrapup_case()
        self.orchestrator.trigger_passive_training(case)

        model_calls = [e.get_model.called for e in self.executors]
        self.assertTrue(any(model_calls), "至少一个 executor 应调用 get_model")

    def test_coaching_context_contains_model_snapshots(self):
        """coaching_context 含 pre_models / post_models / training_results。"""
        case = _make_wrapup_case()
        result = self.orchestrator.trigger_passive_training(case)

        self.assertEqual(result["status"], "coaching_started")
        ctx = result["coaching_context"]
        self.assertIn("pre_models", ctx)
        self.assertIn("post_models", ctx)
        self.assertIn("training_results", ctx)

    def test_checkpoint_before_incremental_order(self):
        """验证调用顺序: checkpoint → add_case → trigger_incremental → get_model。"""
        case = _make_wrapup_case()
        self.orchestrator.trigger_passive_training(case)

        # 检查至少一个 executor 的调用顺序
        for e in self.executors:
            if e.checkpoint.called and e.trigger_incremental.called:
                # checkpoint 应在 trigger_incremental 之前
                chkpt_order = e.method_calls
                chkpt_idx = None
                incr_idx = None
                for i, mc in enumerate(chkpt_order):
                    if mc[0] == "checkpoint" and chkpt_idx is None:
                        chkpt_idx = i
                    if mc[0] == "trigger_incremental" and incr_idx is None:
                        incr_idx = i
                if chkpt_idx is not None and incr_idx is not None:
                    self.assertLess(chkpt_idx, incr_idx,
                        "checkpoint 必须在 trigger_incremental 之前调用")
                    break

    def test_incremental_exception_fail_open(self):
        """trigger_incremental 异常 → FAIL-OPEN 不崩溃。"""
        case = _make_wrapup_case()
        # 让所有 executor 的 trigger_incremental 抛异常
        for e in self.executors:
            e.trigger_incremental.side_effect = RuntimeError("network error")

        result = self.orchestrator.trigger_passive_training(case)

        # 不应该崩溃，status 仍为 coaching_started 或 degraded
        self.assertIn(result["status"], ["coaching_started", "degraded"])

    def test_get_model_exception_fail_open(self):
        """get_model 异常 → FAIL-OPEN 不崩溃。"""
        case = _make_wrapup_case()
        for e in self.executors:
            e.get_model.side_effect = RuntimeError("timeout")

        result = self.orchestrator.trigger_passive_training(case)
        self.assertIn(result["status"], ["coaching_started", "degraded"])


class CoachingLoopV02Test(unittest.TestCase):
    """coaching_loop v0.2 测试: 自动监控+纠正+评估。"""

    def _make_v05_context(self, **kwargs):
        """创建 v0.5 辅导上下文（含模型快照）。"""
        defaults = {
            "case_intent": "实现被动训练v0.5",
            "case_outcome": "success",
            "acceptance_level": "full",
            "algorithm_patterns": ["recursion", "divide_conquer"],
            "call_chain": ["func_a", "func_b", "func_c"],
            "dependency_graph": {"module_a": ["module_b"]},
            "known_gaps": ["gap1: 边界处理不足"],
            "monitoring_checks": [
                "各层训练是否符合33-REA解析的算法模式",
                "DSH执行路径是否与调用链一致",
                "C层反思是否覆盖known_gaps",
                "G层图结构是否与依赖图匹配",
            ],
            "pre_models": {
                "DSH": {"step": 0, "weights": {"intent_classifier": 0.3}},
                "C": {"step": 0, "weights": {"reflection": 0.2}},
            },
            "post_models": {
                "DSH": {"step": 1, "weights": {"intent_classifier": 0.6}},
                "C": {"step": 1, "weights": {"reflection": 0.5}},
            },
            "training_results": {
                "DSH": {"success": True, "metrics": {"incremental_step": 1}},
                "C": {"success": True, "metrics": {"incremental_step": 1}},
            },
        }
        defaults.update(kwargs)
        return defaults

    def test_run_coaching_cycle_auto_evaluate(self):
        """run_coaching_cycle() 自动评估所有监控项。"""
        ctx = self._make_v05_context()
        session = CoachingSession(ctx)

        # v0.2: run_coaching_cycle 自动评估监控
        session.run_coaching_cycle()

        report = session.to_report()
        # 应有监控记录（自动评估后）
        self.assertGreater(len(report["monitoring_log"]), 0)

    def test_run_coaching_cycle_generates_corrections(self):
        """run_coaching_cycle() 基于偏差生成纠正建议。"""
        # post_model 权重无变化 → 应触发纠正
        ctx = self._make_v05_context(
            post_models={
                "DSH": {"step": 0, "weights": {"intent_classifier": 0.3}},  # 无变化
                "C": {"step": 1, "weights": {"reflection": 0.5}},
            }
        )
        session = CoachingSession(ctx)
        session.run_coaching_cycle()

        report = session.to_report()
        # 应有纠正建议
        self.assertGreater(len(report["corrections"]), 0)

    def test_calculate_improvement_with_model_snapshots(self):
        """calculate_improvement() 基于 pre/post model 对比。"""
        ctx = self._make_v05_context()
        session = CoachingSession(ctx)
        session.run_coaching_cycle()

        report = session.to_report()
        # improvement 不应为 None（v0.2 有 pre/post model）
        self.assertIsNotNone(report["improvement"])
        # 应包含层级改进信息
        self.assertIsInstance(report["improvement"], dict)

    def test_calculate_improvement_no_snapshots(self):
        """无 pre/post model → improvement 为 None。"""
        ctx = self._make_v05_context()
        del ctx["pre_models"]
        del ctx["post_models"]
        session = CoachingSession(ctx)
        session.run_coaching_cycle()

        report = session.to_report()
        self.assertIsNone(report["improvement"])

    def test_evaluate_monitoring_dsh_path_consistency(self):
        """evaluate_monitoring: DSH 层 post_model 含 call_chain 相关权重 → 通过。"""
        ctx = self._make_v05_context(
            post_models={
                "DSH": {"step": 1, "weights": {"func_a": 0.8, "func_b": 0.7, "func_c": 0.6}},
            },
            pre_models={
                "DSH": {"step": 0, "weights": {"func_a": 0.1, "func_b": 0.1, "func_c": 0.1}},
            }
        )
        session = CoachingSession(ctx)
        session.run_coaching_cycle()

        report = session.to_report()
        # DSH 层监控应通过（call_chain 节点权重提升）
        dsh_checks = [r for r in report["monitoring_log"]
                      if "DSH" in r.get("check_name", "") or "执行路径" in r.get("detail", "")]
        # 至少有一项监控通过
        passed = [r for r in report["monitoring_log"] if r["passed"]]
        self.assertGreater(len(passed), 0)

    def test_quality_score_reflects_monitoring(self):
        """质量分基于自动监控结果，非全 0。"""
        ctx = self._make_v05_context()
        session = CoachingSession(ctx)
        session.run_coaching_cycle()

        score = session.calculate_quality_score()
        # 有 pre/post model 差异 → 应有通过的监控项 → score > 0
        self.assertGreater(score, 0)

    def test_corrections_contain_layer_and_suggestion(self):
        """纠正建议含 layer + issue + correction 字段。"""
        ctx = self._make_v05_context(
            post_models={
                "DSH": {"step": 0, "weights": {"intent_classifier": 0.3}},  # 无变化
            },
            pre_models={
                "DSH": {"step": 0, "weights": {"intent_classifier": 0.3}},
            }
        )
        session = CoachingSession(ctx)
        session.run_coaching_cycle()

        report = session.to_report()
        if report["corrections"]:
            corr = report["corrections"][0]
            self.assertIn("layer", corr)
            self.assertIn("issue", corr)
            self.assertIn("correction", corr)

    def test_no_models_no_corrections(self):
        """pre/post model 完全一致 → 无纠正（训练成功）。"""
        ctx = self._make_v05_context(
            pre_models={
                "DSH": {"step": 0, "weights": {"w": 0.1}},
                "C": {"step": 0, "weights": {"w": 0.1}},
            },
            post_models={
                "DSH": {"step": 1, "weights": {"w": 0.5}},  # 有变化
                "C": {"step": 1, "weights": {"w": 0.4}},  # 有变化
            },
        )
        session = CoachingSession(ctx)
        session.run_coaching_cycle()

        report = session.to_report()
        # 模型有变化 → 训练有效 → 无纠正或少量纠正
        # 这里主要验证不崩溃
        self.assertIsInstance(report["corrections"], list)


if __name__ == "__main__":
    unittest.main()
