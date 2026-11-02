# -*- coding: utf-8 -*-
"""
test_celery_queue.py — P1-2b Celery 跨进程队列适配测试
=====================================================
验收（PLAN P1-2b）：
- put：pending 去重；按优先级路由 high/normal 队列；投递参数正确
- discard：标记式撤销；未入队返回 False
- get：Celery 模式不适用，返回 None（不抛异常）
- __len__：pending 集合大小
- fail-closed：Celery/Redis 依赖缺失时 RuntimeError，禁止静默降级
- worker 任务：瞬时失败指数退避重试；硬性失败不重试（语义对齐 Runner）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest  # noqa: E402

from core.celery_queue import (  # noqa: E402
    DISCARDED_KEY,
    HIGH_QUEUE,
    NORMAL_QUEUE,
    PENDING_KEY,
    TASK_NAME,
    CeleryTaskQueue,
    InMemorySetStore,
    RedisSetStore,
    build_celery_app,
    register_eval_task,
)
from core.runner import ExecutionError, HardExecutionError  # noqa: E402


class FakeCeleryApp:
    """记录 send_task 调用的假 Celery 应用。"""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_task(self, name: str, args=None, queue: str = "") -> None:
        self.sent.append({"name": name, "args": args, "queue": queue})


class TestCeleryTaskQueue:
    def test_put_routes_normal_priority(self):
        app = FakeCeleryApp()
        q = CeleryTaskQueue(app)
        assert q.put("EV-1") is True
        assert app.sent == [{"name": TASK_NAME, "args": ["EV-1"], "queue": NORMAL_QUEUE}]

    def test_put_routes_high_priority(self):
        app = FakeCeleryApp()
        q = CeleryTaskQueue(app)
        assert q.put("EV-1", priority="high") is True
        assert app.sent[0]["queue"] == HIGH_QUEUE

    def test_put_deduplicates_same_eval(self):
        app = FakeCeleryApp()
        q = CeleryTaskQueue(app)
        assert q.put("EV-1") is True
        assert q.put("EV-1") is False  # 重复入队被忽略
        assert len(app.sent) == 1
        assert len(q) == 1

    def test_discard_marks_and_blocks_requeue(self):
        app = FakeCeleryApp()
        store = InMemorySetStore()
        q = CeleryTaskQueue(app, set_store=store)
        q.put("EV-1")
        assert q.discard("EV-1") is True
        assert store.contains(DISCARDED_KEY, "EV-1") is True
        assert q.discard("EV-1") is False  # 已不在 pending
        assert q.discard("EV-unknown") is False

    def test_get_returns_none_in_celery_mode(self):
        q = CeleryTaskQueue(FakeCeleryApp())
        assert q.get() is None
        assert q.get(timeout=0.5) is None

    def test_len_tracks_pending(self):
        q = CeleryTaskQueue(FakeCeleryApp())
        assert len(q) == 0
        q.put("EV-1")
        q.put("EV-2")
        assert len(q) == 2
        q.discard("EV-1")
        assert len(q) == 1


class TestFailClosed:
    def test_build_celery_app_missing_dependency_raises(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "celery":
                raise ImportError("No module named 'celery'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(RuntimeError, match="Celery 依赖缺失"):
            build_celery_app("redis://127.0.0.1:6379/0")

    def test_redis_set_store_missing_dependency_raises(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "redis":
                raise ImportError("No module named 'redis'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(RuntimeError, match="Redis 依赖缺失"):
            RedisSetStore("redis://127.0.0.1:6379/0")


class TestWorkerTask:
    def _make_task(self, execute, max_retries=3):
        calls: list[str] = []
        registered: dict = {}

        class FakeTask:
            def __init__(self) -> None:
                self.request = type("Req", (), {"retries": 0})()

            def retry(self, exc=None, **kwargs):
                calls.append("retry")
                raise exc

        class FakeApp:
            def task(self, bind=True, name=None, **kwargs):
                def decorator(fn):
                    def wrapper(eval_id):
                        return fn(FakeTask(), eval_id)

                    registered["fn"] = wrapper
                    return wrapper

                return decorator

        app = FakeApp()
        register_eval_task(app, execute, max_retries=max_retries)
        return registered["fn"], calls

    def test_success_returns_ok(self):
        seen: list[str] = []
        fn, _ = self._make_task(lambda eid: seen.append(eid))
        assert fn("EV-1") == {"eval_id": "EV-1", "ok": True}
        assert seen == ["EV-1"]

    def test_hard_error_no_retry(self):
        def boom(eid):
            raise HardExecutionError("契约不符")

        fn, calls = self._make_task(boom)
        with pytest.raises(HardExecutionError):
            fn("EV-1")
        assert calls == []  # 硬性失败不重试

    def test_transient_error_triggers_retry(self):
        def boom(eid):
            raise ExecutionError("网络抖动")

        fn, calls = self._make_task(boom)
        with pytest.raises(ExecutionError):
            fn("EV-1")
        assert calls == ["retry"]  # 瞬时失败走 retry
