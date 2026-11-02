# -*- coding: utf-8 -*-
"""
runner.py — 受理→排队→执行占位（P1-2）
========================================
职责（PLAN P1-2）：
- 任务队列：InProcessQueue（high/normal 双队列，high 优先；同 eval_id 去重）
- 状态机：queued → running → succeeded / failed / cancelled
- 重试：瞬时失败（ExecutionError）指数退避重试；硬性失败（HardExecutionError）不重试
- 取消：排队中可撤销；执行前检查点发现 cancelled 即不再执行
- 执行占位：默认调用 reporter.finalize_empty（空评测 → INCONCLUSIVE，fail-closed）

边界：
- P1-2b 已落地：跨进程/持久队列见 core/celery_queue.py（CeleryTaskQueue 适配本接口；单机默认仍为 InProcessQueue）
- 长任务执行中的取消检查点由 P2 评测器自行轮询 runner.cancelled(eval_id)
"""

from __future__ import annotations

import logging
import queue as _queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from storage.index_publisher import ReportPublisher
from storage.repo import EvalRepo

from core.callbacks import CallbackDispatcher, ShadowDispatcher
from core.metrics import Metrics
from core.reporter import Reporter

logger = logging.getLogger(__name__)

RUN_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")


class ExecutionError(Exception):
    """瞬时执行失败（网络抖动/依赖超时等）：可指数退避重试。"""


class HardExecutionError(ExecutionError):
    """硬性执行失败（契约不符/确定性错误）：不重试，直接 failed。"""


@dataclass(frozen=True)
class RunOutcome:
    """单次执行结果（一次 run_once 的最终态）。"""

    eval_id: str
    status: str  # succeeded / failed / cancelled
    attempts: int
    run_id: str | None
    error: str | None
    report_uri: str | None = None  # P1-4：落盘/登记后的报告 URI


class TaskQueue(Protocol):
    """任务队列接口：P1 内存实现，P1-2b 可替换为 Celery。"""

    def put(self, eval_id: str, priority: str = "normal") -> bool: ...

    def get(self, timeout: float | None = 0.0) -> str | None: ...

    def discard(self, eval_id: str) -> bool: ...

    def __len__(self) -> int: ...


class InProcessQueue:
    """进程内双队列：high 优先；同 eval_id 去重；discard 采用惰性跳过。"""

    def __init__(self) -> None:
        self._high: _queue.Queue[str] = _queue.Queue()
        self._normal: _queue.Queue[str] = _queue.Queue()
        self._pending: set[str] = set()
        self._discarded: set[str] = set()
        self._lock = threading.Lock()

    def put(self, eval_id: str, priority: str = "normal") -> bool:
        with self._lock:
            if eval_id in self._pending:
                logger.info("eval 已在队列中，忽略重复入队 eval_id=%s", eval_id)
                return False
            self._pending.add(eval_id)
            self._discarded.discard(eval_id)
            target = self._high if priority == "high" else self._normal
            target.put(eval_id)
        return True

    def get(self, timeout: float | None = 0.0) -> str | None:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            item = self._pop_nowait()
            if item is not None:
                return item
            if timeout == 0:
                return None
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(0.005)

    def discard(self, eval_id: str) -> bool:
        with self._lock:
            if eval_id not in self._pending:
                return False
            self._pending.discard(eval_id)
            self._discarded.add(eval_id)
        return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._pending)

    # ---------- 内部 ----------

    def _pop_nowait(self) -> str | None:
        for source in (self._high, self._normal):
            try:
                item = source.get_nowait()
            except _queue.Empty:
                continue
            with self._lock:
                if item in self._discarded:
                    self._discarded.discard(item)
                    continue
                self._pending.discard(item)
            return item
        return None


class Runner:
    """任务执行器：出队 → 状态机 → 执行（占位）→ 重试/取消。"""

    def __init__(
        self,
        repo: EvalRepo,
        reporter: Reporter,
        task_queue: TaskQueue | None = None,
        executor: Callable[[str], Any] | None = None,
        max_attempts: int = 3,
        backoff_base: float = 1.0,
        sleeper: Callable[[float], None] | None = None,
        poll_interval: float = 0.1,
        dispatcher: CallbackDispatcher | None = None,
        metrics: Metrics | None = None,
        publisher: ReportPublisher | None = None,
    ) -> None:
        self._repo = repo
        self._reporter = reporter
        self._queue = task_queue or InProcessQueue()
        self._executor = executor or self._finalize_empty
        self._max_attempts = max(1, int(max_attempts))
        self._backoff_base = backoff_base
        self._sleeper = sleeper or time.sleep
        self._poll_interval = poll_interval
        # 默认影子分发：未显式装配时绝不触发下游回调（P1-3 安全默认）
        self._dispatcher = dispatcher or ShadowDispatcher()
        self._metrics = metrics
        self._publisher = publisher
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------- 入队 / 取消 ----------

    @property
    def queue(self) -> TaskQueue:
        return self._queue

    def enqueue(self, eval_id: str, priority: str = "normal") -> bool:
        return self._queue.put(eval_id, priority)

    def cancel(self, eval_id: str) -> bool:
        """撤销排队中的任务（running 的取消由 API 改状态 + 检查点退出）。"""
        return self._queue.discard(eval_id)

    def cancelled(self, eval_id: str) -> bool:
        """执行检查点：供长任务轮询（P2 评测器接入）。"""
        request = self._repo.get_request(eval_id)
        return request is not None and request.status == "cancelled"

    # ---------- 执行 ----------

    def run_once(self, timeout: float | None = 0.0) -> RunOutcome | None:
        """取一个任务执行一次（含重试）；队列空返回 None。"""
        eval_id = self._queue.get(timeout=timeout)
        if eval_id is None:
            return None
        started = time.monotonic()
        outcome = self._execute(eval_id)
        if outcome is not None and self._metrics is not None:
            self._metrics.record_run(outcome, int((time.monotonic() - started) * 1000))
        return outcome

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="eval-runner", daemon=True)
        self._thread.start()
        logger.info("runner started poll_interval=%.3fs", self._poll_interval)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.001, self._poll_interval * 4))
            self._thread = None
            logger.info("runner stopped")

    # ---------- 内部 ----------

    def _finalize_empty(self, eval_id: str) -> dict[str, Any]:
        """执行占位：空评测收尾（P2 接入真实评测器后替换）。"""
        return self._reporter.finalize_empty(eval_id)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once(timeout=self._poll_interval)
            except Exception:  # noqa: BLE001 — 循环不许被单个任务异常打断
                logger.exception("runner 循环未捕获异常")

    def _execute(self, eval_id: str) -> RunOutcome | None:
        request = self._repo.get_request(eval_id)
        if request is None:
            logger.warning("队列中的 eval 不存在，跳过 eval_id=%s", eval_id)
            return None
        if request.status == "cancelled":
            return RunOutcome(eval_id, "cancelled", 0, None, "cancelled_before_start")
        if request.status != "queued":
            logger.warning("eval 状态非 queued，跳过 eval_id=%s status=%s", eval_id, request.status)
            return None

        attempts = 0
        last_error: str | None = None
        for attempt in range(1, self._max_attempts + 1):
            self._repo.update_status(eval_id, "running")
            attempts = attempt
            if self.cancelled(eval_id):  # 检查点：取消后不再执行
                return RunOutcome(eval_id, "cancelled", attempts, None, "cancelled_at_checkpoint")
            try:
                result = self._executor(eval_id)
            except HardExecutionError as exc:
                logger.warning("硬性执行失败，不重试 eval_id=%s: %s", eval_id, exc)
                self._repo.update_status(eval_id, "failed")
                return RunOutcome(eval_id, "failed", attempts, None, str(exc))
            except ExecutionError as exc:
                last_error = str(exc)
                logger.warning(
                    "瞬时执行失败 eval_id=%s attempt=%d/%d: %s",
                    eval_id,
                    attempt,
                    self._max_attempts,
                    exc,
                )
                if attempt >= self._max_attempts:
                    break
                if self.cancelled(eval_id):
                    return RunOutcome(
                        eval_id, "cancelled", attempts, None, "cancelled_during_retry"
                    )
                self._sleeper(self._backoff_base * (2 ** (attempt - 1)))
                continue
            else:
                return self._succeeded(eval_id, attempts, result)

        self._repo.update_status(eval_id, "failed")
        return RunOutcome(eval_id, "failed", attempts, None, last_error)

    def _succeeded(self, eval_id: str, attempts: int, result: Any) -> RunOutcome:
        run_id = result.get("run_id") if isinstance(result, dict) else None
        request = self._repo.get_request(eval_id)
        # 自定义执行器未负责状态时兜底：running → succeeded
        if request is not None and request.status == "running":
            self._repo.update_status(eval_id, "succeeded")
        report_uri = self._publish(eval_id, result)
        # 判定回调：影子模式只记录，实盘才真正回调（P1-3）
        if isinstance(result, dict) and result.get("verdict"):
            self._dispatcher.dispatch(eval_id, str(result["verdict"]), result)
        logger.info(
            "eval 执行成功 eval_id=%s attempts=%d run_id=%s report_uri=%s",
            eval_id,
            attempts,
            run_id,
            report_uri,
        )
        return RunOutcome(eval_id, "succeeded", attempts, run_id, None, report_uri)

    def _publish(self, eval_id: str, result: Any) -> str | None:
        """报告落盘 + 41 索引钩子；失败 fail-open（评测结果不受影响）。"""
        if self._publisher is None or not isinstance(result, dict):
            return None
        try:
            return self._publisher.publish(result).uri
        except Exception as exc:  # noqa: BLE001 — 发布失败不得把成功执行改判为失败
            logger.error("报告发布失败（fail-open）eval_id=%s: %s", eval_id, exc)
            return None
