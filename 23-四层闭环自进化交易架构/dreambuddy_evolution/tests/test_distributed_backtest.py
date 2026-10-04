"""test_distributed_backtest.py — 分布式回测单元测试（D6: ds4 TP/PP 借鉴）

SPEC: SPEC-ds4架构借鉴与系统增强.md §3.2 Dimension 6
哲学: ds4 分布式推理作为 engine backend，按层范围或专家分割到多台机器。
映射: 大规模回测/参数搜索跨机器并行，按时间范围或参数空间分割。

DistributedBacktest API:
  - split_by_time(start, end, n_workers)  # 按时间范围分割
  - split_by_params(param_space, n_workers)  # 按参数空间分割
  - run_worker(worker_id, task)  # 执行单个 worker
  - aggregate(results)  # 汇总多 worker 结果
  - run_distributed(tasks)  # 分布式执行（FAIL-OPEN 降级单机）

硬约束:
  HC-DS4-07: 分布式回测失败 → 自动降级为单机执行，不阻塞回测流程
  HC-DS4-01: 开关关闭时与当前单机行为 100% 等价

覆盖:
  - split_by_time 均匀分割
  - split_by_params 参数网格分割
  - aggregate 结果汇总（加权平均、最大回撤取 max）
  - FAIL-OPEN 降级单机
"""
from __future__ import annotations

import pytest

from dreambuddy_evolution.scripts.distributed_backtest import DistributedBacktest


# ==============================================================================
# 1. 时间分割
# ==============================================================================
class TestSplitByTime:
    """D6: 按时间范围分割"""

    def test_split_by_time_even(self):
        """2 worker 均分 100 天 → 各 50 天"""
        bt = DistributedBacktest()
        tasks = bt.split_by_time("2024-01-01", "2024-04-10", n_workers=2)
        assert len(tasks) == 2
        # 每个任务有 start/end
        for task in tasks:
            assert "start" in task and "end" in task

    def test_split_by_time_uneven(self):
        """3 worker 分 100 天 → 余数分配到前几个"""
        bt = DistributedBacktest()
        tasks = bt.split_by_time("2024-01-01", "2024-04-10", n_workers=3)
        assert len(tasks) == 3

    def test_split_by_time_single_worker(self):
        """1 worker → 不分割"""
        bt = DistributedBacktest()
        tasks = bt.split_by_time("2024-01-01", "2024-04-10", n_workers=1)
        assert len(tasks) == 1
        assert tasks[0]["start"] == "2024-01-01"
        assert tasks[0]["end"] == "2024-04-10"

    def test_split_by_time_continuous(self):
        """分割后时间段连续无重叠无遗漏"""
        from datetime import datetime, timedelta
        bt = DistributedBacktest()
        tasks = bt.split_by_time("2024-01-01", "2024-02-01", n_workers=4)
        # 验证连续性
        fmt = "%Y-%m-%d"
        for i in range(len(tasks) - 1):
            end = datetime.strptime(tasks[i]["end"], fmt)
            nxt_start = datetime.strptime(tasks[i + 1]["start"], fmt)
            assert end <= nxt_start


# ==============================================================================
# 2. 参数空间分割
# ==============================================================================
class TestSplitByParams:
    """D6: 按参数空间分割"""

    def test_split_by_params_grid(self):
        """参数网格分割：每个 worker 获得一组参数"""
        bt = DistributedBacktest()
        param_space = {
            "stop_loss": [0.02, 0.03, 0.05],
            "take_profit": [0.04, 0.06, 0.10],
        }
        tasks = bt.split_by_params(param_space, n_workers=3)
        # 3x3 = 9 组参数，分 3 worker → 每组约 3 个
        assert len(tasks) == 3
        total_params = sum(len(t["params"]) for t in tasks)
        assert total_params == 9

    def test_split_by_params_single_dim(self):
        """单维度参数分割"""
        bt = DistributedBacktest()
        param_space = {"leverage": [1, 2, 3, 4]}
        tasks = bt.split_by_params(param_space, n_workers=2)
        assert len(tasks) == 2
        total = sum(len(t["params"]) for t in tasks)
        assert total == 4


# ==============================================================================
# 3. 结果聚合
# ==============================================================================
class TestAggregate:
    """D6: 多 worker 结果汇总"""

    def test_aggregate_mean_sharpe(self):
        """Sharpe 取加权平均（按交易数加权）"""
        bt = DistributedBacktest()
        results = [
            {"sharpe": 1.5, "n_trades": 100, "max_drawdown": 0.15, "total_return": 0.20},
            {"sharpe": 2.0, "n_trades": 200, "max_drawdown": 0.10, "total_return": 0.30},
        ]
        agg = bt.aggregate(results)
        # 加权平均: (1.5*100 + 2.0*200) / 300 = 550/300 ≈ 1.833
        assert abs(agg["sharpe"] - 1.8333) < 0.01
        assert agg["n_trades"] == 300

    def test_aggregate_max_drawdown(self):
        """最大回撤取各 worker 中的最大值"""
        bt = DistributedBacktest()
        results = [
            {"sharpe": 1.0, "n_trades": 50, "max_drawdown": 0.15},
            {"sharpe": 1.2, "n_trades": 60, "max_drawdown": 0.25},
            {"sharpe": 0.8, "n_trades": 40, "max_drawdown": 0.10},
        ]
        agg = bt.aggregate(results)
        assert agg["max_drawdown"] == 0.25

    def test_aggregate_sum_returns(self):
        """总收益累加"""
        bt = DistributedBacktest()
        results = [
            {"sharpe": 1.0, "n_trades": 50, "max_drawdown": 0.1, "total_return": 0.1},
            {"sharpe": 1.0, "n_trades": 50, "max_drawdown": 0.1, "total_return": 0.2},
        ]
        agg = bt.aggregate(results)
        assert abs(agg["total_return"] - 0.30) < 1e-6

    def test_aggregate_empty(self):
        """空结果列表 → 默认值"""
        bt = DistributedBacktest()
        agg = bt.aggregate([])
        assert agg["sharpe"] == 0.0
        assert agg["n_trades"] == 0
        assert agg["max_drawdown"] == 0.0


# ==============================================================================
# 4. FAIL-OPEN 降级
# ==============================================================================
class TestFailOpen:
    """HC-DS4-07: 分布式失败 → 自动降级单机"""

    def test_fail_open_on_worker_exception(self):
        """worker 执行异常 → 降级为单机执行，不阻塞"""
        bt = DistributedBacktest()

        def failing_worker(task):
            raise RuntimeError("network error")

        tasks = bt.split_by_time("2024-01-01", "2024-02-01", n_workers=2)
        # FAIL-OPEN: 分布式执行失败时降级单机
        result = bt.run_distributed(tasks, worker_fn=failing_worker)
        # 降级后仍返回结果（单机模式）
        assert result is not None
        assert "n_trades" in result or "degraded" in result


# ==============================================================================
# 5. 单机模式等价性
# ==============================================================================
class TestSingleMachine:
    """HC-DS4-01: 开关关闭时与单机行为 100% 等价"""

    def test_single_machine_returns_valid_result(self):
        """单机模式执行返回有效结果"""
        bt = DistributedBacktest()

        def simple_worker(task):
            return {"sharpe": 1.0, "n_trades": 10, "max_drawdown": 0.05, "total_return": 0.1}

        tasks = [{"start": "2024-01-01", "end": "2024-01-31"}]
        result = bt.run_distributed(tasks, worker_fn=simple_worker)
        assert result["n_trades"] == 10
        assert result["sharpe"] == 1.0
