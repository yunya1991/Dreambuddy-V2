"""SPEC v0.5 §5.3 P2: TSHTTPTrainingExecutor 扩展测试。

测试 P2.3 新增方法:
  1. trigger_incremental() → POST action=incremental
  2. checkpoint() → POST action=checkpoint
  3. restore(state) → POST action=restore
  4. get_model() → GET /model
  5. FAIL-OPEN: HTTP 不可用时降级返回
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


class TSHTTPTrainingExecutorP2Test(unittest.TestCase):
    """P2: 增量训练/checkpoint/restore/model 方法测试。"""

    def _make_executor(self, layer=TrainingLayer.S):
        return TSHTTPTrainingExecutor(layer, base_url="http://mock:9999")

    # ========================================================
    # P2.3.1: trigger_incremental
    # ========================================================
    def test_trigger_incremental_success(self):
        """trigger_incremental() 成功时返回 TrainingResult(success=True)。"""
        executor = self._make_executor(TrainingLayer.S)
        mock_resp = {
            "success": True,
            "data": {
                "trained": True,
                "bucket_count": 10,
                "bucket_threshold": 50,
                "incrementalStep": 3,
                "weights": {"intent_a": 0.5},
            },
        }
        with patch.object(executor, "_http_post", return_value=mock_resp):
            result = executor.trigger_incremental()

        self.assertTrue(result.success)
        self.assertEqual(result.metrics.get("incremental_step"), 3)
        self.assertIn("weights", result.metrics)

    def test_trigger_incremental_fail_open(self):
        """trigger_incremental() HTTP 失败时返回降级 TrainingResult。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.S, base_url="http://invalid:9999")
        result = executor.trigger_incremental()
        self.assertFalse(result.success)
        self.assertIn("degraded", result.message)

    # ========================================================
    # P2.3.2: checkpoint
    # ========================================================
    def test_checkpoint_success(self):
        """checkpoint() 成功时返回 checkpointed=True + state。"""
        executor = self._make_executor(TrainingLayer.S)
        mock_resp = {
            "success": True,
            "data": {
                "checkpointed": True,
                "state": {
                    "weights": {"intent_a": 0.5},
                    "step": 5,
                    "drift_flag": False,
                },
                "meta": {
                    "id": "ckpt-123",
                    "layer": "S",
                    "step": 5,
                },
            },
        }
        with patch.object(executor, "_http_post", return_value=mock_resp):
            result = executor.checkpoint()

        self.assertTrue(result.get("checkpointed"))
        self.assertEqual(result["state"]["step"], 5)

    def test_checkpoint_fail_open(self):
        """checkpoint() HTTP 失败时返回降级结果。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.S, base_url="http://invalid:9999")
        result = executor.checkpoint()
        self.assertFalse(result.get("checkpointed"))
        self.assertTrue(result.get("degraded"))

    # ========================================================
    # P2.3.3: restore
    # ========================================================
    def test_restore_success(self):
        """restore(state) 成功时返回 restored=True。"""
        executor = self._make_executor(TrainingLayer.S)
        mock_resp = {
            "success": True,
            "data": {"restored": True},
        }
        state = {"weights": {"a": 0.5}, "step": 5, "drift_flag": False}
        with patch.object(executor, "_http_post", return_value=mock_resp):
            result = executor.restore(state)

        self.assertTrue(result.get("restored"))

    def test_restore_fail_open(self):
        """restore(state) HTTP 失败时返回降级结果。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.S, base_url="http://invalid:9999")
        result = executor.restore({"step": 1})
        self.assertFalse(result.get("restored"))
        self.assertTrue(result.get("degraded"))

    # ========================================================
    # P2.3.4: get_model
    # ========================================================
    def test_get_model_success(self):
        """get_model() 成功时返回模型状态 JSON。"""
        executor = self._make_executor(TrainingLayer.S)
        mock_resp = {
            "success": True,
            "data": {
                "weights": {"intent_a": 0.5},
                "step": 5,
                "drift_flag": False,
                "timestamp": 1697000000000,
                "version": "v0.5-20261011",
            },
        }
        with patch.object(executor, "_http_get", return_value=mock_resp):
            result = executor.get_model()

        self.assertEqual(result["step"], 5)
        self.assertIn("weights", result)
        self.assertEqual(result["version"], "v0.5-20261011")

    def test_get_model_fail_open(self):
        """get_model() HTTP 失败时返回降级空字典。"""
        executor = TSHTTPTrainingExecutor(TrainingLayer.S, base_url="http://invalid:9999")
        result = executor.get_model()
        self.assertTrue(result.get("degraded"))
        self.assertEqual(result.get("step"), 0)


if __name__ == "__main__":
    unittest.main()
