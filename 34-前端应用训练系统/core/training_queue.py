"""训练队列与重试机制。

管理训练任务的排队、优先级调度和失败重试。

SPEC §2.4:
  - 主动训练: 失败重试(次日重试)
  - 被动训练: 不重试(记录失败)
  - 并发: 单实例(各模式串行)
  - 调度: 被动训练优先级 > 主动训练
"""
import heapq
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class QueuedTask:
    """训练队列中的任务。"""
    task_id: str
    mode: str  # "active" or "passive"
    priority: int  # 0=highest(passive), 1=lower(active)
    retry_count: int = 0
    status: str = "pending"
    created_at: float = field(default_factory=lambda: time.time())
    data: Optional[dict] = None
    last_error: str = ""

    def __lt__(self, other):
        """优先队列比较: priority 小的先出队，同优先级按 created_at 先入先出。"""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at


class TrainingQueue:
    """训练任务队列 + 重试机制。"""

    def __init__(self, max_retries: int = 3):
        self._heap: List[QueuedTask] = []
        self._tasks: Dict[str, QueuedTask] = {}  # task_id → QueuedTask (快速查找)
        self._max_retries = max_retries

    def enqueue(self, task: QueuedTask) -> None:
        """入队（按优先级排序）。"""
        heapq.heappush(self._heap, task)
        self._tasks[task.task_id] = task

    def dequeue(self) -> Optional[QueuedTask]:
        """出队（返回最高优先级任务）。"""
        while self._heap:
            task = heapq.heappop(self._heap)
            if task.status == "pending":
                task.status = "running"
                self._tasks[task.task_id] = task
                return task
        return None

    def mark_failed(self, task_id: str) -> None:
        """标记任务失败，若未超重试上限则重新入队。"""
        task = self._tasks.get(task_id)
        if not task:
            return

        task.retry_count += 1
        task.last_error = f"failed at retry {task.retry_count}"

        if task.retry_count >= self._max_retries:
            task.status = "failed"
        else:
            task.status = "retrying"
            # 重新入队等待重试
            heapq.heappush(self._heap, task)

    def mark_completed(self, task_id: str) -> None:
        """标记任务完成。"""
        task = self._tasks.get(task_id)
        if task:
            task.status = "completed"

    def get_task(self, task_id: str) -> Optional[QueuedTask]:
        """按 ID 查找任务。"""
        return self._tasks.get(task_id)

    def size(self) -> int:
        """队列中待处理任务数。"""
        return sum(1 for t in self._heap if t.status == "pending")

    def get_all_tasks(self) -> List[QueuedTask]:
        """获取所有任务。"""
        return list(self._tasks.values())

    def clear_completed(self) -> int:
        """清理已完成/失败的任务，返回清理数。"""
        before = len(self._tasks)
        self._tasks = {
            tid: t for tid, t in self._tasks.items()
            if t.status in ("pending", "retrying", "running")
        }
        self._heap = [t for t in self._heap if t.status in ("pending", "retrying", "running")]
        heapq.heapify(self._heap)
        return before - len(self._tasks)
