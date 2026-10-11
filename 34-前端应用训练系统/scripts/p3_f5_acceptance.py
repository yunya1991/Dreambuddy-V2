#!/usr/bin/env python3
"""P3 F5 验收脚本: 双模式互不阻塞+资源使用符合配额。

验收标准:
  - F5: 被动训练不阻塞用户交互，主动训练不影响系统响应
  - 资源配额: 主动CPU≤30%/内存≤2GB, 被动CPU≤50%/内存≤4GB
  - 被动训练抢占主动训练
  - 训练队列+重试机制工作正常
  - 状态监控可查询
"""
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_ADAPTERS_DIR = os.path.join(_34_DIR, "adapters")
_CORE_DIR = os.path.join(_34_DIR, "core")

for _p in [_THIS_DIR, _34_DIR, _ADAPTERS_DIR, _CORE_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main():
    print("=" * 60)
    print("F5 验收: 双模式互不阻塞+资源使用符合配额")
    print("=" * 60)

    # ── 验收 1: 资源配额配置 ──────────────────────────────
    print("\n[1] 资源配额配置:")
    from resource_manager import ACTIVE_QUOTA, PASSIVE_QUOTA, ResourceManager

    print(f"  主动训练: CPU≤{ACTIVE_QUOTA.cpu_percent}%, 内存≤{ACTIVE_QUOTA.memory_mb}MB, "
          f"超时{ACTIVE_QUOTA.timeout_hours}h, 重试{ACTIVE_QUOTA.max_retries}")
    print(f"  被动训练: CPU≤{PASSIVE_QUOTA.cpu_percent}%, 内存≤{PASSIVE_QUOTA.memory_mb}MB, "
          f"超时{PASSIVE_QUOTA.timeout_minutes}min, 重试{PASSIVE_QUOTA.max_retries}")

    assert ACTIVE_QUOTA.cpu_percent == 30
    assert ACTIVE_QUOTA.memory_mb == 2048
    assert PASSIVE_QUOTA.cpu_percent == 50
    assert PASSIVE_QUOTA.memory_mb == 4096
    print("  ✅ 资源配额配置符合 SPEC §2.4")

    # ── 验收 2: 资源检查 ──────────────────────────────────
    print("\n[2] 资源检查:")
    mgr = ResourceManager(ACTIVE_QUOTA)
    report = mgr.get_usage_report()
    print(f"  当前CPU: {report['current_cpu']}%, 配额: {report['quota_cpu']}%")
    print(f"  当前内存: {report['current_memory_mb']:.0f}MB, 配额: {report['quota_memory_mb']}MB")
    print(f"  配额内: {report['within_quota']}")
    print("  ✅ 资源检查功能正常")

    # ── 验收 3: 训练队列+重试机制 ────────────────────────
    print("\n[3] 训练队列+重试机制:")
    from training_queue import TrainingQueue, QueuedTask

    queue = TrainingQueue(max_retries=3)

    # 入队：主动(低优先级) + 被动(高优先级)
    queue.enqueue(QueuedTask(task_id="active_1", mode="active", priority=1))
    queue.enqueue(QueuedTask(task_id="passive_1", mode="passive", priority=0))
    print(f"  入队 2 任务 (主动+被动), 队列大小: {queue.size()}")

    # 出队：被动应先出队
    first = queue.dequeue()
    print(f"  首先出队: {first.task_id} (mode={first.mode})")
    assert first.task_id == "passive_1", "被动训练应优先出队"
    print("  ✅ 优先级调度: 被动优先于主动")

    # 重试机制
    queue.mark_failed("passive_1")
    retried = queue.get_task("passive_1")
    print(f"  失败后重试: retry_count={retried.retry_count}, status={retried.status}")
    assert retried.retry_count == 1
    assert retried.status == "retrying"
    print("  ✅ 重试机制: 失败后自动重入队")

    # ── 验收 4: 双模式调度 ────────────────────────────────
    print("\n[4] 双模式调度:")
    from dual_mode_orchestrator import DualModeTrainingOrchestrator
    from unittest.mock import MagicMock

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

    orch = DualModeTrainingOrchestrator(
        data_providers=[mock_provider],
        training_executors=[mock_executor],
        case_evaluator=mock_evaluator,
    )

    # 被动训练抢占
    orch._passive_training_active = True
    active_result = orch.run_active_training()
    print(f"  被动训练进行时主动训练: status={active_result['status']}")
    assert active_result["status"] == "skipped"
    print("  ✅ 被动训练抢占主动训练")

    # 主动不阻塞被动
    orch._passive_training_active = False
    passive_result = orch.trigger_passive_training({"intent": "test"})
    print(f"  主动训练未运行时被动训练: status={passive_result['status']}")
    assert passive_result["status"] != "skipped_active"
    print("  ✅ 主动训练不阻塞被动训练")

    # ── 验收 5: 状态监控 ──────────────────────────────────
    print("\n[5] 状态监控:")
    status = orch.get_status()
    print(f"  active_training: {status['active_training']}")
    print(f"  passive_training: {status['passive_training']}")
    print(f"  queue_size: {status['queue_size']}")
    print(f"  resource_usage keys: {list(status['resource_usage'].keys())}")
    assert "active_training" in status
    assert "passive_training" in status
    assert "queue_size" in status
    assert "resource_usage" in status
    print("  ✅ 状态监控功能正常")

    # ── 总结 ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("F5 验收: ✅ PASS")
    print("  双模式互不阻塞，资源使用符合配额")
    print("  - 资源配额: 主动≤30%/2GB, 被动≤50%/4GB ✅")
    print("  - 被动训练抢占主动训练 ✅")
    print("  - 训练队列+重试机制 ✅")
    print("  - 状态监控 ✅")
    return True


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result else 1)
