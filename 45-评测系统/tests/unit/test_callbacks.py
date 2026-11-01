# -*- coding: utf-8 -*-
"""
test_callbacks.py — P1-3 只受理不拦截（判定回调路由）测试
==========================================================
验收（PLAN P1-3 / SPEC §13.3）：
- gate.shadow=true：判定只记录 would-dispatch，绝不触发真实回调
- gate.shadow=false：真实回调被调用并留下审计记录
- 回调异常不影响评测结果（fail-soft，仅记录原因）
- Runner 执行成功且产出报告后按 shadow 路由回调；失败/无报告不回调
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.callbacks import (  # noqa: E402
    DispatchRecord,
    RecordingDispatcher,
    ShadowDispatcher,
    build_dispatcher,
)
from core.gateway import CategoriesConfig, Gateway  # noqa: E402
from core.registry import ThresholdRegistry  # noqa: E402
from core.reporter import Reporter  # noqa: E402
from core.runner import ExecutionError, Runner  # noqa: E402
from storage.repo import InMemoryRepo  # noqa: E402

FIXED_NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

MAPPING = {
    "finance": ("strategy", "service"),
    "ai": ("model", "service"),
    "engineering": ("code_artifact", "dataset", "knowledge"),
}


def make_stack(shadow: bool = True):
    repo = InMemoryRepo()
    gateway = Gateway(
        store=repo,
        categories=CategoriesConfig(version="CAT-TEST@1", mapping=MAPPING, gate_shadow=shadow),
        clock=lambda: FIXED_NOW,
    )
    reporter = Reporter(repo=repo, thresholds=ThresholdRegistry.load(), clock=lambda: FIXED_NOW)
    return repo, gateway, reporter


def submit(repo, gateway, key: str = "k-1") -> str:
    payload = {
        "object_ref": "git://repo/strategy@abc123",
        "category": "finance",
        "object_type": "strategy",
        "submitter": "trader-01",
        "purpose": "deploy",
        "spec_id": "EVS-20261101-0001",
        "env_manifest": {"endpoints": ["https://object.local/health"]},
    }
    return gateway.submit(payload, idempotency_key=key).eval_id


# ---------- 影子分发 ----------


def test_shadow_dispatcher_records_without_calling():
    audit: list[DispatchRecord] = []
    dispatcher = ShadowDispatcher(audit=audit, clock=lambda: FIXED_NOW)
    record = dispatcher.dispatch("EV-1", "BLOCK", {"eval_id": "EV-1", "verdict": "BLOCK"})
    assert record.mode == "shadow"
    assert record.dispatched is False
    assert record.verdict == "BLOCK"
    assert audit == [record]
    assert "shadow" in (record.reason or "").lower()


def test_build_dispatcher_shadow_returns_shadow():
    live: list[dict] = []
    dispatcher = build_dispatcher(shadow=True, callback=live.append)
    dispatcher.dispatch("EV-1", "PASS", {})
    assert live == []
    assert isinstance(dispatcher, ShadowDispatcher)


# ---------- 真实分发 ----------


def test_recording_dispatcher_calls_callback():
    payloads: list[dict] = []
    audit: list[DispatchRecord] = []
    dispatcher = RecordingDispatcher(callback=payloads.append, audit=audit, clock=lambda: FIXED_NOW)
    report = {"eval_id": "EV-1", "verdict": "PASS", "score": 0.9}
    record = dispatcher.dispatch("EV-1", "PASS", report)
    assert record.dispatched is True
    assert record.mode == "live"
    assert payloads == [{"eval_id": "EV-1", "verdict": "PASS", "report": report}]
    assert audit == [record]


def test_callback_error_is_fail_soft():
    def boom(_payload: dict) -> None:
        raise RuntimeError("downstream down")

    audit: list[DispatchRecord] = []
    dispatcher = RecordingDispatcher(callback=boom, audit=audit, clock=lambda: FIXED_NOW)
    record = dispatcher.dispatch("EV-1", "PASS", {})
    assert record.dispatched is False
    assert "downstream down" in (record.reason or "")
    assert audit == [record]


def test_build_dispatcher_live_returns_recording():
    live: list[dict] = []
    dispatcher = build_dispatcher(shadow=False, callback=live.append)
    assert isinstance(dispatcher, RecordingDispatcher)
    dispatcher.dispatch("EV-1", "PASS", {"eval_id": "EV-1", "verdict": "PASS"})
    assert len(live) == 1


# ---------- Runner 路由 ----------


def test_runner_shadow_does_not_call_live_callback():
    repo, gateway, reporter = make_stack(shadow=True)
    eval_id = submit(repo, gateway)
    live: list[dict] = []
    audit: list[DispatchRecord] = []
    dispatcher = build_dispatcher(shadow=True, callback=live.append, audit=audit)
    runner = Runner(repo=repo, reporter=reporter, dispatcher=dispatcher)
    runner.enqueue(eval_id)
    outcome = runner.run_once(timeout=0)
    assert outcome.status == "succeeded"
    assert live == []
    assert [r.verdict for r in audit] == ["INCONCLUSIVE"]
    assert audit[0].dispatched is False


def test_runner_live_dispatches_verdict():
    repo, gateway, reporter = make_stack(shadow=False)
    eval_id = submit(repo, gateway)
    live: list[dict] = []
    dispatcher = build_dispatcher(shadow=False, callback=live.append)
    runner = Runner(repo=repo, reporter=reporter, dispatcher=dispatcher)
    runner.enqueue(eval_id)
    runner.run_once(timeout=0)
    assert live[0]["verdict"] == "INCONCLUSIVE"
    assert live[0]["eval_id"] == eval_id


def test_runner_failure_does_not_dispatch():
    repo, gateway, reporter = make_stack(shadow=False)
    eval_id = submit(repo, gateway)

    def boom(_eval_id: str) -> None:
        raise ExecutionError("transient")

    live: list[dict] = []
    dispatcher = build_dispatcher(shadow=False, callback=live.append)
    runner = Runner(
        repo=repo, reporter=reporter, executor=boom, max_attempts=1, dispatcher=dispatcher
    )
    runner.enqueue(eval_id)
    outcome = runner.run_once(timeout=0)
    assert outcome.status == "failed"
    assert live == []


def test_runner_executor_without_report_does_not_dispatch():
    repo, gateway, reporter = make_stack(shadow=False)
    eval_id = submit(repo, gateway)
    live: list[dict] = []
    dispatcher = build_dispatcher(shadow=False, callback=live.append)
    runner = Runner(repo=repo, reporter=reporter, executor=lambda _e: None, dispatcher=dispatcher)
    runner.enqueue(eval_id)
    runner.run_once(timeout=0)
    assert live == []
