# -*- coding: utf-8 -*-
"""
celery_queue.py — Celery 跨进程队列适配（P1-2b）
================================================
职责（PLAN P1-2b）：
- CeleryTaskQueue：适配 core.runner.TaskQueue 接口的跨进程/持久队列实现
  - put：pending 集合去重 + 按优先级路由到 high/normal 两条 Celery 队列
  - discard：撤销排队任务（worker 侧经 repo 状态检查点跳过，见 Runner.cancelled）
  - get：Celery 模式下由 worker 消费队列，不适用拉取（返回 None 并告警）
  - __len__：pending 集合大小（可观测性：队列积压指标）
- build_celery_app：Celery 应用工厂（broker/result 可配；依赖缺失 fail-closed）
- register_eval_task：worker 任务注册
  - acks_late=True：worker 崩溃后任务可被其他 worker 重取
  - 瞬时失败（ExecutionError）指数退避重试；硬性失败（HardExecutionError）不重试
  - 语义与 core.runner.Runner._execute 对齐

部署形态：
- API 进程：CeleryTaskQueue.put 投递（Redis broker）
- worker 进程：celery -A core.celery_queue:build_celery_app worker 消费执行
- 单机默认仍为 InProcessQueue；引入 Redis 后按部署配置切换

边界：
- 去重集合存储抽象为 SetStore：生产用 RedisSetStore，测试用 InMemorySetStore
- 依赖缺失一律 fail-closed（RuntimeError），禁止静默降级为内存实现
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

from core.runner import ExecutionError, HardExecutionError

logger = logging.getLogger(__name__)

PENDING_KEY = "eval45:queue:pending"
DISCARDED_KEY = "eval45:queue:discarded"
HIGH_QUEUE = "eval.high"
NORMAL_QUEUE = "eval.normal"
TASK_NAME = "eval45.run_eval"


# ---------- 去重集合存储 ----------


class SetStore(Protocol):
    """去重集合存储接口：生产用 Redis，测试用内存实现。"""

    def add(self, key: str, member: str) -> bool: ...

    def discard(self, key: str, member: str) -> bool: ...

    def contains(self, key: str, member: str) -> bool: ...

    def size(self, key: str) -> int: ...


class InMemorySetStore:
    """内存实现：单测与本地空跑用。"""

    def __init__(self) -> None:
        self._sets: dict[str, set[str]] = {}

    def add(self, key: str, member: str) -> bool:
        members = self._sets.setdefault(key, set())
        if member in members:
            return False
        members.add(member)
        return True

    def discard(self, key: str, member: str) -> bool:
        members = self._sets.get(key)
        if not members or member not in members:
            return False
        members.discard(member)
        return True

    def contains(self, key: str, member: str) -> bool:
        return member in self._sets.get(key, set())

    def size(self, key: str) -> int:
        return len(self._sets.get(key, set()))


class RedisSetStore:
    """Redis Set 实现：依赖缺失时 fail-closed（禁止静默降级为内存实现）。"""

    def __init__(self, url: str = "redis://127.0.0.1:6379/0") -> None:
        try:
            import redis  # type: ignore
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise RuntimeError(
                "Redis 依赖缺失：pip install 'celery[redis]'（fail-closed，不降级）"
            ) from exc
        self._redis = redis.Redis.from_url(url)

    def add(self, key: str, member: str) -> bool:
        return bool(self._redis.sadd(key, member))

    def discard(self, key: str, member: str) -> bool:
        return bool(self._redis.srem(key, member))

    def contains(self, key: str, member: str) -> bool:
        return bool(self._redis.sismember(key, member))

    def size(self, key: str) -> int:
        return int(self._redis.scard(key))


# ---------- TaskQueue 的 Celery 适配 ----------


class CeleryTaskQueue:
    """TaskQueue 的 Celery 适配：put 投递到 Celery 队列，由 worker 消费。

    与 InProcessQueue 的差异：
    - 跨进程/持久：API 进程 put，worker 进程消费（Redis broker 中转）
    - get() 不适用：Celery 模式由 worker 主动拉取，Runner 轮询循环不启用
    - discard 为标记式撤销：worker 侧执行前经 repo 状态检查点跳过
    """

    def __init__(
        self,
        app: Any,
        set_store: SetStore | None = None,
        high_queue: str = HIGH_QUEUE,
        normal_queue: str = NORMAL_QUEUE,
    ) -> None:
        self._app = app
        self._store = set_store or InMemorySetStore()
        self._high = high_queue
        self._normal = normal_queue

    def put(self, eval_id: str, priority: str = "normal") -> bool:
        if not self._store.add(PENDING_KEY, eval_id):
            logger.info("eval 已在队列中，忽略重复入队 eval_id=%s", eval_id)
            return False
        self._store.discard(DISCARDED_KEY, eval_id)
        queue = self._high if priority == "high" else self._normal
        self._app.send_task(TASK_NAME, args=[eval_id], queue=queue)
        logger.info("eval 已投递到 Celery 队列 eval_id=%s queue=%s", eval_id, queue)
        return True

    def get(self, timeout: float | None = 0.0) -> str | None:
        logger.warning("Celery 模式由 worker 消费队列，get() 不适用，返回 None")
        return None

    def discard(self, eval_id: str) -> bool:
        if not self._store.contains(PENDING_KEY, eval_id):
            return False
        self._store.discard(PENDING_KEY, eval_id)
        self._store.add(DISCARDED_KEY, eval_id)
        return True

    def __len__(self) -> int:
        return self._store.size(PENDING_KEY)


# ---------- Celery 应用工厂与 worker 任务 ----------


def build_celery_app(broker_url: str, result_backend: str | None = None) -> Any:
    """Celery 应用工厂：依赖缺失 fail-closed。"""
    try:
        from celery import Celery  # type: ignore
    except ImportError as exc:  # pragma: no cover - 依赖缺失路径
        raise RuntimeError(
            "Celery 依赖缺失：pip install 'celery[redis]'（fail-closed，不降级）"
        ) from exc
    app = Celery("eval45", broker=broker_url, backend=result_backend)
    app.conf.update(
        task_acks_late=True,                    # worker 崩溃后任务可被重取
        task_reject_on_worker_lost=True,
        task_default_queue=NORMAL_QUEUE,
        broker_connection_retry_on_startup=True,
    )
    return app


def register_eval_task(
    app: Any,
    execute: Callable[[str], Any],
    max_retries: int = 3,
    backoff_base: float = 1.0,
) -> Any:
    """注册 worker 任务：重试语义与 Runner._execute 对齐。

    - 瞬时失败（ExecutionError）：指数退避重试，backoff_base * 2^retries
    - 硬性失败（HardExecutionError）：不重试，直接抛出
    - execute 内部负责取消检查点（repo 状态轮询，见 Runner.cancelled）
    """

    @app.task(bind=True, name=TASK_NAME, acks_late=True, max_retries=max_retries)
    def run_eval(self, eval_id: str) -> dict[str, Any]:
        try:
            execute(eval_id)
        except HardExecutionError as exc:
            logger.warning("硬性执行失败，不重试 eval_id=%s: %s", eval_id, exc)
            raise
        except ExecutionError as exc:
            retries = self.request.retries
            countdown = backoff_base * (2 ** retries)
            logger.warning(
                "瞬时执行失败 eval_id=%s retry=%d/%d: %s",
                eval_id,
                retries,
                max_retries,
                exc,
            )
            raise self.retry(exc=exc, countdown=countdown)
        return {"eval_id": eval_id, "ok": True}

    return run_eval
