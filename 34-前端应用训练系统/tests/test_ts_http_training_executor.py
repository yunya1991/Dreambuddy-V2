"""TSHTTPTrainingExecutor 单元测试。

测试:
  1. _convert_case_to_training_data 各层转换正确
  2. FAIL-OPEN：HTTP 不可用时降级返回
  3. get_bucket_threshold 各层阈值正确
  4. get_dependencies 依赖链正确
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ts_http_training_executor import TSHTTPTrainingExecutor
from interfaces.training_executor import TrainingLayer, TrainingResult
from interfaces.training_data_provider import TrainingCase


class TSHTTPTrainingExecutorTest(unittest.TestCase):

    def _make_case(self, **kwargs):
        """创建测试用 TrainingCase。"""
        defaults = {
            "intent": "test_intent",
            "actions": ["action1", "action2"],
            "outcome_text": "test outcome",
            "learned": ["lesson1"],
            "quality": "B",
            "source": "test",
            "metadata": {"outcome": "success"},
        }
        defaults.update(kwargs)
        return TrainingCase(**defaults)

    def test_convert_s_layer(self):
        """S 层转换：{message, intent_type, entities}。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.S)
        case = self._make_case()
        data = executor._convert_case_to_training_data(case)
        self.assertEqual(data["message"], "test outcome")
        self.assertEqual(data["intent_type"], "test_intent")
        self.assertEqual(data["entities"], [])

    def test_convert_dsh_layer(self):
        """DSH 层转换：{task, node_sequence, outcome}。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.DSH)
        case = self._make_case()
        data = executor._convert_case_to_training_data(case)
        self.assertEqual(data["task"], "test_intent")
        self.assertEqual(data["node_sequence"], ["action1", "action2"])
        self.assertEqual(data["outcome"], "success")

    def test_convert_c_layer(self):
        """C 层转换：{context_summary, action_taken, outcome, expected_decision}。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.C)
        case = self._make_case()
        data = executor._convert_case_to_training_data(case)
        self.assertEqual(data["context_summary"], "test_intent")
        self.assertEqual(data["action_taken"], "action1")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["expected_decision"], "CONTINUE")

    def test_convert_g_layer(self):
        """G 层转换：{decisions, rules}。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.G)
        case = self._make_case(learned=["rule1", "rule2"])
        data = executor._convert_case_to_training_data(case)
        self.assertEqual(data["decisions"], ["test_intent"])
        self.assertEqual(data["rules"], ["rule1", "rule2"])

    def test_convert_llm_layer(self):
        """LLM 层转换：{intent, learned, outcome, prompt_pattern}。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.LLM)
        case = self._make_case()
        data = executor._convert_case_to_training_data(case)
        self.assertEqual(data["intent"], "test_intent")
        self.assertEqual(data["learned"], ["lesson1"])
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["prompt_pattern"], "test outcome")

    def test_bucket_thresholds(self):
        """各层桶满阈值应正确。"""
        executor_s = TSHTTPTrainingExecutor(TrainingLayer.S)
        self.assertEqual(executor_s.get_bucket_threshold(), 50)
        executor_dsh = TSHTTPTrainingExecutor(TrainingLayer.DSH)
        self.assertEqual(executor_dsh.get_bucket_threshold(), 50)
        executor_c = TSHTTPTrainingExecutor(TrainingLayer.C)
        self.assertEqual(executor_c.get_bucket_threshold(), 50)
        executor_g = TSHTTPTrainingExecutor(TrainingLayer.G)
        self.assertEqual(executor_g.get_bucket_threshold(), 60)
        executor_llm = TSHTTPTrainingExecutor(TrainingLayer.LLM)
        self.assertEqual(executor_llm.get_bucket_threshold(), 30)

    def test_dependencies(self):
        """训练依赖链应正确。"""
        executor_dsh = TSHTTPTrainingExecutor(TrainingLayer.DSH)
        deps = executor_dsh.get_dependencies()
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0], TrainingLayer.S)

        executor_c = TSHTTPTrainingExecutor(TrainingLayer.C)
        deps = executor_c.get_dependencies()
        self.assertIn(TrainingLayer.S, deps)
        self.assertIn(TrainingLayer.DSH, deps)

        executor_s = TSHTTPTrainingExecutor(TrainingLayer.S)
        self.assertEqual(executor_s.get_dependencies(), [])

    def test_fail_open_train_http_error(self):
        """train() HTTP 失败时应返回降级 TrainingResult。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.S, base_url="http://invalid:9999")
        result = executor.train()
        self.assertFalse(result.success)
        self.assertIn("degraded", result.message)

    def test_fail_open_add_case_http_error(self):
        """add_case() HTTP 失败时应返回 False。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.S, base_url="http://invalid:9999")
        case = self._make_case()
        result = executor.add_case(case)
        self.assertFalse(result)

    def test_fail_open_get_bucket_count_http_error(self):
        """get_bucket_count() HTTP 失败时应返回缓存值。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.S, base_url="http://invalid:9999")
        executor._cached_bucket_count = 5
        count = executor.get_bucket_count()
        self.assertEqual(count, 5)


if __name__ == "__main__":
    unittest.main()
