"""P3 双模式资源管理单元测试。

测试:
  1. ResourceQuota 配置（主动≤30%CPU/2GB，被动≤50%CPU/4GB）
  2. 资源检查：超配额时报False
  3. 被动训练抢占主动训练
  4. 训练队列 + 重试机制（失败后重试）
  5. 训练状态监控
  6. 双模式互不阻塞
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_CORE_DIR = os.path.join(os.path.dirname(_THIS_DIR), "core")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _CORE_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class ResourceQuotaTest(unittest.TestCase):

    def test_active_quota_config(self):
        """主动训练资源配额: CPU≤30%, 内存≤2GB, 超时8h。"""
        from resource_manager import ResourceQuota, ACTIVE_QUOTA

        self.assertEqual(ACTIVE_QUOTA.cpu_percent, 30)
        self.assertEqual(ACTIVE_QUOTA.memory_mb, 2048)
        self.assertEqual(ACTIVE_QUOTA.timeout_hours, 8)

    def test_passive_quota_config(self):
        """被动训练资源配额: CPU≤50%, 内存≤4GB, 超时30min。"""
        from resource_manager import ResourceQuota, PASSIVE_QUOTA

        self.assertEqual(PASSIVE_QUOTA.cpu_percent, 50)
        self.assertEqual(PASSIVE_QUOTA.memory_mb, 4096)
        self.assertEqual(PASSIVE_QUOTA.timeout_minutes, 30)

    def test_check_within_quota(self):
        """资源在配额内返回True。"""
        from resource_manager import ResourceManager, ACTIVE_QUOTA

        mgr = ResourceManager(ACTIVE_QUOTA)
        # 模拟资源使用: CPU 20%, 内存 1GB
        with patch.object(mgr, "_get_current_usage", return_value={"cpu": 20, "memory_mb": 1024}):
            self.assertTrue(mgr.check_available())

    def test_check_over_quota(self):
        """资源超配额返回False。"""
        from resource_manager import ResourceManager, ACTIVE_QUOTA

        mgr = ResourceManager(ACTIVE_QUOTA)
        # 模拟资源使用: CPU 40%(>30%), 内存 1GB
        with patch.object(mgr, "_get_current_usage", return_value={"cpu": 40, "memory_mb": 1024}):
            self.assertFalse(mgr.check_available())


class TrainingQueueTest(unittest.TestCase):

    def test_enqueue_and_dequeue(self):
        """训练队列: 入队+出队按优先级。"""
        from training_queue import TrainingQueue, QueuedTask

        queue = TrainingQueue()
        task1 = QueuedTask(task_id="t1", mode="active", priority=1)
        task2 = QueuedTask(task_id="t2", mode="passive", priority=0)  # 更高优先级

        queue.enqueue(task1)
        queue.enqueue(task2)

        # 被动(优先级0)应先出队
        first = queue.dequeue()
        self.assertEqual(first.task_id, "t2")

    def test_retry_mechanism(self):
        """失败任务重试: 重试次数+1，超过上限标记为failed。"""
        from training_queue import TrainingQueue, QueuedTask

        queue = TrainingQueue(max_retries=3)
        task = QueuedTask(task_id="retry_test", mode="active", priority=1)
        queue.enqueue(task)

        # 模拟失败 → 重入队
        queue.mark_failed("retry_test")
        retried = queue.get_task("retry_test")
        self.assertEqual(retried.retry_count, 1)
        self.assertEqual(retried.status, "retrying")  # 仍可重试

        # 超过重试上限
        queue.mark_failed("retry_test")
        queue.mark_failed("retry_test")
        queue.mark_failed("retry_test")  # 第4次，超过max_retries=3
        failed = queue.get_task("retry_test")
        self.assertEqual(failed.status, "failed")

    def test_queue_size(self):
        """队列大小正确统计。"""
        from training_queue import TrainingQueue, QueuedTask

        queue = TrainingQueue()
        self.assertEqual(queue.size(), 0)

        queue.enqueue(QueuedTask(task_id="t1", mode="active", priority=1))
        queue.enqueue(QueuedTask(task_id="t2", mode="active", priority=1))
        self.assertEqual(queue.size(), 2)

        queue.dequeue()
        self.assertEqual(queue.size(), 1)


class DualModeSchedulingTest(unittest.TestCase):

    def _make_mock_orchestrator(self):
        """创建带资源管理的 mock orchestrator。"""
        from dual_mode_orchestrator import DualModeTrainingOrchestrator

        mock_provider = MagicMock()
        mock_provider.get_source_name.return_value = "test"
        mock_provider.get_quality_threshold.return_value = "B"
        mock_provider.fetch_cases.return_value = []

        mock_executor = MagicMock()
        mock_executor.get_layer.return_value = MagicMock(value="DSH")
        mock_executor.get_bucket_count.return_value = 0
        mock_executor.get_bucket_threshold.return_value = 50

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = MagicMock(
            decision=MagicMock(value="skip"), reason="test"
        )

        return DualModeTrainingOrchestrator(
            data_providers=[mock_provider],
            training_executors=[mock_executor],
            case_evaluator=mock_evaluator,
        )

    def test_passive_preempts_active(self):
        """被动训练进行时，主动训练被暂停。"""
        orch = self._make_mock_orchestrator()

        # 标记被动训练开始
        orch._passive_training_active = True
        result = orch.run_active_training()
        self.assertEqual(result["status"], "skipped")
        self.assertIn("passive", result["reason"])

    def test_get_status(self):
        """get_status 返回双模式运行状态。"""
        orch = self._make_mock_orchestrator()

        status = orch.get_status()
        self.assertIn("active_training", status)
        self.assertIn("passive_training", status)
        self.assertIn("queue_size", status)
        self.assertIn("resource_usage", status)

    def test_active_does_not_block_passive(self):
        """主动训练不阻塞被动训练。"""
        orch = self._make_mock_orchestrator()

        # 主动训练不在运行 → 被动训练可正常触发
        result = orch.trigger_passive_training({"intent": "test"})
        # 返回非 "skipped"（被动训练不需要检查主动训练状态）
        self.assertNotEqual(result.get("status"), "skipped_active")


if __name__ == "__main__":
    unittest.main()
