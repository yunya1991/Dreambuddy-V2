"""
D6: DistributedBacktest — 分布式回测（借鉴 ds4 TP/PP 分布式推理）

SPEC: SPEC-ds4架构借鉴与系统增强.md §3.2 Dimension 6
哲学: ds4 分布式推理作为 engine backend，不暴露新前端 API。
      Tensor Parallelism: 50/50 分割路由专家；Pipeline Parallelism: 按层范围分割。
映射: 大规模回测/参数搜索跨机器并行，按时间范围或参数空间分割。

设计:
  - split_by_time: 按时间范围均匀分割到 n_workers
  - split_by_params: 参数网格笛卡尔积后均匀分配
  - aggregate: 多 worker 结果汇总（Sharpe 加权平均，回撤取 max）
  - run_distributed: 并发执行，FAIL-OPEN 降级单机

硬约束:
  HC-DS4-07: 分布式回测失败 → 自动降级为单机执行，不阻塞
  HC-DS4-01: 开关关闭时与单机行为 100% 等价
"""
from __future__ import annotations

import itertools
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger(__name__)


class DistributedBacktest:
    """分布式回测调度器（借鉴 ds4 Pipeline Parallelism）.

    按时间范围或参数空间分割到多个 worker，结果汇总。
    FAIL-OPEN: 分布式失败时降级为单机顺序执行。
    """

    def __init__(self, n_workers: int = 2):
        self.n_workers = max(1, n_workers)

    # ---------- 时间分割 ----------
    def split_by_time(self, start: str, end: str, n_workers: int | None = None) -> list[dict]:
        """按时间范围均匀分割.

        Args:
            start: 起始日期 "YYYY-MM-DD"
            end: 结束日期 "YYYY-MM-DD"
            n_workers: worker 数量，默认用 self.n_workers

        Returns:
            list[dict]: [{"start": ..., "end": ...}, ...]
        """
        n = n_workers or self.n_workers
        n = max(1, n)
        if n == 1:
            return [{"start": start, "end": end, "worker_id": 0}]

        fmt = "%Y-%m-%d"
        d_start = datetime.strptime(start, fmt)
        d_end = datetime.strptime(end, fmt)
        total_days = (d_end - d_start).days
        if total_days <= 0:
            return [{"start": start, "end": end, "worker_id": 0}]

        base = total_days // n
        remainder = total_days % n

        tasks = []
        cur = d_start
        for i in range(n):
            chunk = base + (1 if i < remainder else 0)
            task_end = cur + timedelta(days=chunk)
            # 最后一个 worker 到 end
            if i == n - 1:
                task_end = d_end
            tasks.append({
                "start": cur.strftime(fmt),
                "end": task_end.strftime(fmt),
                "worker_id": i,
            })
            cur = task_end
        return tasks

    # ---------- 参数空间分割 ----------
    def split_by_params(self, param_space: dict[str, list], n_workers: int | None = None) -> list[dict]:
        """按参数空间网格分割.

        Args:
            param_space: {param_name: [values], ...}
            n_workers: worker 数量

        Returns:
            list[dict]: [{"worker_id": i, "params": [{...}, ...]}, ...]
        """
        n = n_workers or self.n_workers
        n = max(1, n)

        # 生成参数网格（笛卡尔积）
        keys = list(param_space.keys())
        values = [param_space[k] for k in keys]
        grid = [dict(zip(keys, combo)) for combo in itertools.product(*values)]

        if not grid:
            return []
        if n == 1:
            return [{"worker_id": 0, "params": grid}]

        # 均匀分配
        base = len(grid) // n
        remainder = len(grid) % n
        tasks = []
        idx = 0
        for i in range(n):
            chunk = base + (1 if i < remainder else 0)
            tasks.append({
                "worker_id": i,
                "params": grid[idx:idx + chunk],
            })
            idx += chunk
        return tasks

    # ---------- 结果聚合 ----------
    def aggregate(self, results: list[dict]) -> dict[str, Any]:
        """汇总多 worker 回测结果.

        聚合规则:
          - sharpe: 按 n_trades 加权平均
          - max_drawdown: 取最大值（最保守）
          - n_trades: 累加
          - total_return: 累加

        Args:
            results: 各 worker 的结果 dict 列表

        Returns:
            dict: 汇总结果
        """
        if not results:
            return {
                "sharpe": 0.0,
                "n_trades": 0,
                "max_drawdown": 0.0,
                "total_return": 0.0,
                "degraded": False,
            }

        total_trades = sum(r.get("n_trades", 0) for r in results)
        if total_trades > 0:
            weighted_sharpe = sum(
                r.get("sharpe", 0.0) * r.get("n_trades", 0) for r in results
            ) / total_trades
        else:
            weighted_sharpe = 0.0

        max_dd = max((r.get("max_drawdown", 0.0) for r in results), default=0.0)
        total_return = sum(r.get("total_return", 0.0) for r in results)

        return {
            "sharpe": round(weighted_sharpe, 6),
            "n_trades": total_trades,
            "max_drawdown": max_dd,
            "total_return": round(total_return, 6),
            "degraded": any(r.get("degraded", False) for r in results),
        }

    # ---------- 分布式执行 ----------
    def run_distributed(
        self,
        tasks: list[dict],
        worker_fn: Callable[[dict], dict],
    ) -> dict[str, Any]:
        """分布式执行回测任务.

        尝试并发执行，失败时降级为单机顺序执行（HC-DS4-07）.

        Args:
            tasks: 任务列表
            worker_fn: 单个 worker 的执行函数，接收 task dict，返回结果 dict

        Returns:
            dict: 汇总结果
        """
        if not tasks:
            return self.aggregate([])

        # 尝试并发执行
        results: list[dict] = []
        try:
            results = self._run_concurrent(tasks, worker_fn)
        except Exception as e:
            logger.warning("[DS4-D6] distributed fail, fallback to single: %s", e)
            results = self._run_single(tasks, worker_fn)

        return self.aggregate(results)

    def _run_concurrent(self, tasks: list[dict], worker_fn: Callable) -> list[dict]:
        """并发执行（使用 ThreadPoolExecutor）.

        任何 worker 异常都触发整体降级.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=self.n_workers) as executor:
            futures = {executor.submit(worker_fn, t): i for i, t in enumerate(tasks)}
            for future in as_completed(futures):
                result = future.result()  # 异常会向上抛出，触发降级
                results.append(result)
        return results

    def _run_single(self, tasks: list[dict], worker_fn: Callable) -> list[dict]:
        """单机顺序执行（降级模式）.

        每个 task 独立 try-except，单个失败不影响其他.
        """
        results: list[dict] = []
        for task in tasks:
            try:
                result = worker_fn(task)
                result["degraded"] = True
                results.append(result)
            except Exception as e:
                logger.debug("[DS4-D6] single worker fail: %s", e)
                results.append({
                    "sharpe": 0.0,
                    "n_trades": 0,
                    "max_drawdown": 0.0,
                    "total_return": 0.0,
                    "degraded": True,
                })
        return results
