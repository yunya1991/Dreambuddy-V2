"""Phase 2 E2E 测试：rea_to_tdr 转换 + 编排器联调。

测试:
  1. rea_to_training_cases 各字段映射正确
  2. REA 为 None 时降级为文本四元组
  3. 编排器工厂创建正确配置的编排器
  4. trigger_passive_training 全链路（mock HTTP）
  5. run_active_training 全链路（mock TDR + HTTP）
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_CORE_DIR = os.path.join(os.path.dirname(_THIS_DIR), "core")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _CORE_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rea_to_tdr_adapter import rea_to_training_cases
from interfaces.rea_parser import REAParseResult
from interfaces.case_evaluator import IngestDecision
from interfaces.training_executor import TrainingLayer


class ReaToTdrConversionTest(unittest.TestCase):
    """测试 rea_to_training_cases 转换逻辑。"""

    def _make_wrapup(self, **kwargs):
        return {
            "intent": "实现登录功能",
            "actions": ["设计数据库", "写API", "写前端"],
            "outcome_text": "登录功能完成",
            "learned": ["需要加盐", "JWT比session好"],
            "quality": "B",
            **kwargs,
        }

    def test_all_fields_mapped(self):
        """REA 结果所有字段应正确映射到对应 layer_tags。"""
        wrapup = self._make_wrapup()
        rea = REAParseResult(
            algorithm_patterns=["recursion", "divide_conquer"],
            call_chain=["login", "authenticate", "check_pw"],
            dependency_graph={"auth": ["db"], "api": ["auth"]},
            known_gaps=["未处理并发请求"],
            observations=[{"result": "密码使用bcrypt"}],
            evidence_level="L1",
            confidence=0.9,
        )
        cases = rea_to_training_cases(wrapup, rea)

        # 应生成 5 个 case（patterns, call_chain, graph, gaps, observations）
        self.assertEqual(len(cases), 5)

        # 验证 layer_tags
        all_tags = []
        for c in cases:
            all_tags.extend(c.layer_tags)
        self.assertIn("DSH", all_tags)
        self.assertIn("C", all_tags)
        self.assertIn("G", all_tags)
        self.assertIn("LLM", all_tags)

        # 验证 algorithm_patterns 映射到 DSH+C
        algo_cases = [c for c in cases if c.source == "rea_algorithm"]
        self.assertEqual(len(algo_cases), 1)
        self.assertIn("DSH", algo_cases[0].layer_tags)
        self.assertIn("C", algo_cases[0].layer_tags)
        self.assertEqual(algo_cases[0].learned, ["recursion", "divide_conquer"])

        # 验证 call_chain 映射到 DSH
        chain_cases = [c for c in cases if c.source == "rea_call_chain"]
        self.assertEqual(len(chain_cases), 1)
        self.assertIn("DSH", chain_cases[0].layer_tags)
        self.assertEqual(chain_cases[0].actions, ["login", "authenticate", "check_pw"])

        # 验证 dependency_graph 映射到 G
        graph_cases = [c for c in cases if c.source == "rea_dependency_graph"]
        self.assertEqual(len(graph_cases), 1)
        self.assertIn("G", graph_cases[0].layer_tags)

        # 验证 known_gaps 映射到 C
        gap_cases = [c for c in cases if c.source == "rea_known_gaps"]
        self.assertEqual(len(gap_cases), 1)
        self.assertIn("C", gap_cases[0].layer_tags)
        self.assertEqual(gap_cases[0].learned, ["未处理并发请求"])
        self.assertEqual(gap_cases[0].quality, "C")

        # 验证 observations 映射到 LLM
        obs_cases = [c for c in cases if c.source == "rea_observations"]
        self.assertEqual(len(obs_cases), 1)
        self.assertIn("LLM", obs_cases[0].layer_tags)

    def test_rea_none_fallback_to_text(self):
        """REA 为 None 时应降级为纯文本四元组。"""
        wrapup = self._make_wrapup()
        cases = rea_to_training_cases(wrapup, None)

        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(case.source, "wrapup_text")
        self.assertEqual(case.intent, "实现登录功能")
        self.assertIn("S", case.layer_tags)
        self.assertIn("DSH", case.layer_tags)
        self.assertIn("C", case.layer_tags)
        self.assertIn("G", case.layer_tags)
        self.assertIn("LLM", case.layer_tags)

    def test_empty_rea_fields_fallback(self):
        """REA 所有字段都空时应降级为文本四元组。"""
        wrapup = self._make_wrapup()
        rea = REAParseResult()  # 所有字段默认为空
        cases = rea_to_training_cases(wrapup, rea)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].source, "wrapup_text")

    def test_quality_from_evidence_level(self):
        """L1→A, L2→B, L3→B, L4→C。"""
        wrapup = self._make_wrapup()
        rea = REAParseResult(
            algorithm_patterns=["recursion"],
            evidence_level="L1",
            confidence=0.9,
        )
        cases = rea_to_training_cases(wrapup, rea)
        algo_case = [c for c in cases if c.source == "rea_algorithm"][0]
        self.assertEqual(algo_case.quality, "A")

    def test_confidence_propagated(self):
        """REA confidence 应传播到 TrainingCase。"""
        wrapup = self._make_wrapup()
        rea = REAParseResult(
            algorithm_patterns=["recursion"],
            confidence=0.85,
        )
        cases = rea_to_training_cases(wrapup, rea)
        algo_case = [c for c in cases if c.source == "rea_algorithm"][0]
        self.assertEqual(algo_case.confidence, 0.85)


class OrchestratorFactoryTest(unittest.TestCase):
    """测试编排器工厂。"""

    def test_factory_creates_orchestrator(self):
        """工厂应创建配置好的编排器。"""
        from orchestrator_factory import create_orchestrator
        orchestrator = create_orchestrator(enable_rea=False)

        self.assertIsNotNone(orchestrator)
        self.assertEqual(len(orchestrator._data_providers), 1)
        self.assertEqual(len(orchestrator._training_executors), 5)
        self.assertIsNotNone(orchestrator._case_evaluator)
        self.assertIsNone(orchestrator._rea_parser)  # enable_rea=False

    def test_factory_with_rea(self):
        """启用 REA 时应创建 REA 解析器。"""
        from orchestrator_factory import create_orchestrator
        orchestrator = create_orchestrator(enable_rea=True)

        self.assertIsNotNone(orchestrator._rea_parser)


class PassiveTrainingE2ETest(unittest.TestCase):
    """测试 trigger_passive_training 全链路（mock）。"""

    def test_passive_training_skip(self):
        """评估为 SKIP 时应跳过训练。"""
        from dual_mode_orchestrator import DualModeTrainingOrchestrator

        evaluator = MagicMock()
        evaluator.evaluate.return_value = MagicMock()
        evaluator.evaluate.return_value.decision = MagicMock()
        evaluator.evaluate.return_value.decision.value = "skip"
        evaluator.evaluate.return_value.reason = "low_value"

        orchestrator = DualModeTrainingOrchestrator(
            data_providers=[],
            training_executors=[],
            case_evaluator=evaluator,
            rea_parser=None,
        )

        result = orchestrator.trigger_passive_training({"intent": "test"})
        self.assertEqual(result["status"], "skipped")

    def test_passive_training_ingest_with_coaching_context(self):
        """INGEST 时应构建辅导上下文。"""
        from dual_mode_orchestrator import DualModeTrainingOrchestrator

        evaluator = MagicMock()
        evaluation = MagicMock()
        evaluation.decision = MagicMock()
        evaluation.decision.value = "ingest"
        evaluation.reason = "high_value"
        evaluator.evaluate.return_value = evaluation

        rea_parser = MagicMock()
        rea_result = MagicMock()
        rea_result.algorithm_patterns = ["recursion"]
        rea_result.call_chain = ["func_a", "func_b"]
        rea_result.known_gaps = ["gap1"]
        rea_parser.trace.return_value = rea_result

        executor = MagicMock()
        executor.get_layer.return_value = TrainingLayer.DSH
        executor.get_bucket_count.return_value = 0
        executor.get_bucket_threshold.return_value = 50
        executor.add_case.return_value = True

        orchestrator = DualModeTrainingOrchestrator(
            data_providers=[],
            training_executors=[executor],
            case_evaluator=evaluator,
            rea_parser=rea_parser,
        )

        wrapup = {
            "intent": "test_feature",
            "outcome": "success",
            "acceptance_level": "full",
            "code_path": "/tmp/test",
            "feature": "feature_a",
        }

        result = orchestrator.trigger_passive_training(wrapup)
        self.assertEqual(result["status"], "coaching_started")
        self.assertIn("coaching_context", result)
        self.assertIn("monitoring_checks", result["coaching_context"])
        self.assertEqual(result["coaching_context"]["algorithm_patterns"], ["recursion"])


class ActiveTrainingE2ETest(unittest.TestCase):
    """测试 run_active_training 全链路（mock）。"""

    def test_active_training_skipped_when_passive_active(self):
        """被动训练进行时应跳过主动训练。"""
        from dual_mode_orchestrator import DualModeTrainingOrchestrator

        orchestrator = DualModeTrainingOrchestrator(
            data_providers=[],
            training_executors=[],
            case_evaluator=MagicMock(),
        )
        orchestrator._passive_training_active = True

        result = orchestrator.run_active_training()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "passive_training_active")

    def test_active_training_with_mock_data(self):
        """mock 数据提供者 + 执行器，验证主动训练流程。"""
        from dual_mode_orchestrator import DualModeTrainingOrchestrator
        from interfaces.training_data_provider import TrainingCase

        # mock 数据提供者返回 2 个案例
        provider = MagicMock()
        provider.fetch_cases.return_value = [
            TrainingCase(
                intent="case1", actions=["a1"], outcome_text="o1",
                learned=["l1"], layer_tags=["S"], quality="B",
            ),
            TrainingCase(
                intent="case2", actions=["a2"], outcome_text="o2",
                learned=["l2"], layer_tags=["DSH"], quality="A",
            ),
        ]

        # mock 执行器：S 层，桶满阈值=1（确保触发训练）
        executor = MagicMock()
        executor.get_layer.return_value = TrainingLayer.S
        executor.get_bucket_threshold.return_value = 1
        executor.get_bucket_count.return_value = 1
        executor.add_case.return_value = True
        executor.train.return_value = MagicMock()
        executor.train.return_value.success = True

        orchestrator = DualModeTrainingOrchestrator(
            data_providers=[provider],
            training_executors=[executor],
            case_evaluator=MagicMock(),
        )

        result = orchestrator.run_active_training(limit=10)
        self.assertEqual(result["status"], "completed")
        # 应触发了训练（bucket_count >= threshold）
        executor.add_case.assert_called()


if __name__ == "__main__":
    unittest.main()
