# -*- coding: utf-8 -*-
"""
test_runner.py — P1-2 受理→排队→执行占位测试
=============================================
验收（PLAN P1-2）：
- 双队列（high/normal）：high 优先出队；重复入队去重；可撤销排队任务
- 状态机：queued → running → succeeded / failed / cancelled
- 重试：瞬时失败指数退避重试；硬性失败不重试
- 取消：排队中/执行前检查点发现 cancelled 即不再执行
- start/stop：后台线程取出队列任务执行
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.gateway import CategoriesConfig, Gateway  # noqa: E402
from core.registry import ThresholdRegistry  # noqa: E402
from core.reporter import Reporter  # noqa: E402
from core.runner import (  # noqa: E402
    ExecutionError,
    HardExecutionError,
    InProcessQueue,
    Runner,
    RunOutcome,
)
from storage.repo import InMemoryRepo  # noqa: E402

FIXED_NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

MAPPING = {
    "finance": ("strategy", "service"),
    "ai": ("model", "service"),
    "engineering": ("code_artifact", "dataset", "knowledge"),
}


def make_stack():
    repo = InMemoryRepo()
    gateway = Gateway(
        store=repo,
        categories=CategoriesConfig(version="CAT-TEST@1", mapping=MAPPING, gate_shadow=True),
        clock=lambda: FIXED_NOW,
    )
    reporter = Reporter(repo=repo, thresholds=ThresholdRegistry.load(), clock=lambda: FIXED_NOW)
    return repo, gateway, reporter


def submit(repo, gateway, key: str = "k-1", priority: str = "normal") -> str:
    payload = {
        "object_ref": "git://repo/strategy@abc123",
        "category": "finance",
        "object_type": "strategy",
        "submitter": "trader-01",
        "purpose": "l0_settle",
        "priority": priority,
        "spec_id": "EVS-20261101-0001",
        "env_manifest": {"endpoints": ["https://object.local/health"]},
    }
    return gateway.submit(payload, idempotency_key=key).eval_id


class RecordingSleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class FlakyExecutor:
    """前 fail_times 次抛瞬时错误，之后成功并记录调用次数。"""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def __call__(self, _eval_id: str) -> None:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ExecutionError(f"transient #{self.calls}")


# ---------- 队列 ----------


def test_queue_high_priority_first():
    queue = InProcessQueue()
    queue.put("EV-normal-1", "normal")
    queue.put("EV-high-1", "high")
    queue.put("EV-normal-2", "normal")
    assert [queue.get(timeout=0), queue.get(timeout=0), queue.get(timeout=0)] == [
        "EV-high-1",
        "EV-normal-1",
        "EV-normal-2",
    ]


def test_queue_deduplicates_same_eval():
    queue = InProcessQueue()
    queue.put("EV-1", "normal")
    queue.put("EV-1", "normal")
    assert len(queue) == 1
    assert queue.get(timeout=0) == "EV-1"
    assert queue.get(timeout=0) is None


def test_queue_discard_removes_pending():
    queue = InProcessQueue()
    queue.put("EV-1", "normal")
    queue.put("EV-2", "high")
    assert queue.discard("EV-1") is True
    assert queue.discard("EV-1") is False
    assert queue.get(timeout=0) == "EV-2"
    assert queue.get(timeout=0) is None


def test_queue_get_empty_returns_none():
    assert InProcessQueue().get(timeout=0) is None


# ---------- 状态机 ----------


def test_run_once_unknown_eval_returns_none():
    repo, _, reporter = make_stack()
    runner = Runner(repo=repo, reporter=reporter)
    runner.enqueue("EV-20261101-999999")
    assert runner.run_once(timeout=0) is None


def test_run_once_cancelled_before_execution_skips():
    repo, gateway, reporter = make_stack()
    eval_id = submit(repo, gateway)
    repo.update_status(eval_id, "cancelled")
    calls: list[str] = []
    runner = Runner(repo=repo, reporter=reporter, executor=calls.append)
    runner.enqueue(eval_id)
    outcome = runner.run_once(timeout=0)
    assert outcome == RunOutcome(
        eval_id=eval_id,
        status="cancelled",
        attempts=0,
        run_id=None,
        error="cancelled_before_start",
    )
    assert calls == []
    assert repo.get_request(eval_id).status == "cancelled"


def test_run_once_success_finalizes_empty_report():
    repo, gateway, reporter = make_stack()
    eval_id = submit(repo, gateway)
    runner = Runner(repo=repo, reporter=reporter)
    outcome = runner.run_once(timeout=0)  # 空队列 → None
    assert outcome is None
    runner.enqueue(eval_id)
    outcome = runner.run_once(timeout=0)
    assert outcome.status == "succeeded"
    assert outcome.attempts == 1
    assert repo.get_request(eval_id).status == "succeeded"
    report = repo.get_report(eval_id)
    assert report["verdict"] == "INCONCLUSIVE"


def test_transient_failure_retries_with_exponential_backoff():
    repo, gateway, reporter = make_stack()
    eval_id = submit(repo, gateway)
    sleeper = RecordingSleeper()
    executor = FlakyExecutor(fail_times=2)
    runner = Runner(
        repo=repo, reporter=reporter, executor=executor, max_attempts=3, sleeper=sleeper
    )
    runner.enqueue(eval_id)
    outcome = runner.run_once(timeout=0)
    assert outcome.status == "succeeded"
    assert outcome.attempts == 3
    assert sleeper.calls == [1.0, 2.0]
    assert repo.get_request(eval_id).status == "succeeded"


def test_transient_failure_exhausted_marks_failed():
    repo, gateway, reporter = make_stack()
    eval_id = submit(repo, gateway)
    sleeper = RecordingSleeper()
    runner = Runner(
        repo=repo,
        reporter=reporter,
        executor=FlakyExecutor(fail_times=9),
        max_attempts=2,
        sleeper=sleeper,
    )
    runner.enqueue(eval_id)
    outcome = runner.run_once(timeout=0)
    assert outcome.status == "failed"
    assert outcome.attempts == 2
    assert "transient #2" in (outcome.error or "")
    assert sleeper.calls == [1.0]
    assert repo.get_request(eval_id).status == "failed"


def test_hard_failure_does_not_retry():
    def boom(_eval_id: str) -> None:
        raise HardExecutionError("bad spec")

    repo, gateway, reporter = make_stack()
    eval_id = submit(repo, gateway)
    sleeper = RecordingSleeper()
    runner = Runner(repo=repo, reporter=reporter, executor=boom, max_attempts=3, sleeper=sleeper)
    runner.enqueue(eval_id)
    outcome = runner.run_once(timeout=0)
    assert outcome.status == "failed"
    assert outcome.attempts == 1
    assert sleeper.calls == []
    assert repo.get_request(eval_id).status == "failed"


def test_cancel_at_checkpoint_stops_retries():
    repo, gateway, reporter = make_stack()
    eval_id = submit(repo, gateway)
    sleeper = RecordingSleeper()
    holder: dict[str, Runner] = {}

    def executor(_eval_id: str) -> None:
        raise ExecutionError("transient")

    runner = Runner(
        repo=repo, reporter=reporter, executor=executor, max_attempts=3, sleeper=sleeper
    )
    holder["runner"] = runner
    runner.enqueue(eval_id)
    # 在执行前的检查点把状态置为 cancelled：第一次尝试后，退避期前应退出
    original_update = repo.update_status

    def update_with_cancel(target: str, status: str) -> bool:
        result = original_update(target, status)
        if status == "running" and target == eval_id:
            original_update(target, "cancelled")
        return result

    repo.update_status = update_with_cancel  # type: ignore[method-assign]
    outcome = runner.run_once(timeout=0)
    assert outcome.status == "cancelled"
    assert outcome.attempts == 1
    assert sleeper.calls == []
    assert repo.get_request(eval_id).status == "cancelled"


def test_start_stop_processes_queue():
    repo, gateway, reporter = make_stack()
    eval_id = submit(repo, gateway)
    runner = Runner(repo=repo, reporter=reporter, poll_interval=0.01)
    runner.enqueue(eval_id)
    runner.start()
    try:
        deadline = datetime.now(timezone.utc).timestamp() + 2.0
        while repo.get_request(eval_id).status == "queued":
            assert datetime.now(timezone.utc).timestamp() < deadline, "任务未在 2s 内执行"
    finally:
        runner.stop()
    assert repo.get_request(eval_id).status == "succeeded"


def test_stop_without_start_is_noop():
    repo, _, reporter = make_stack()
    Runner(repo=repo, reporter=reporter).stop()
