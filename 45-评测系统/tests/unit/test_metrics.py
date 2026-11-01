# -*- coding: utf-8 -*-
"""
test_metrics.py — P1-5 灰度观测指标测试
========================================
验收（PLAN P1-5）：
- 受理量 / 状态分布 / 判定分布 / 分类分布 / 积压（queued+running）
- 成功率（succeeded / (succeeded+failed)）与耗时（created_at → decided_at）
- Runner 执行统计（次数/成功/失败/取消/平均耗时）
- API GET /api/v1/eval/metrics 可查询；非法时间参数 400
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.routes import create_app  # noqa: E402
from core.gateway import CategoriesConfig, Gateway  # noqa: E402
from core.metrics import Metrics  # noqa: E402
from core.registry import ThresholdRegistry  # noqa: E402
from core.reporter import Reporter  # noqa: E402
from core.runner import Runner, RunOutcome  # noqa: E402
from storage.repo import InMemoryRepo  # noqa: E402

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

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
        clock=lambda: NOW,
    )
    reporter = Reporter(repo=repo, thresholds=ThresholdRegistry.load(), clock=lambda: NOW)
    metrics = Metrics(repo=repo, shadow=shadow, clock=lambda: NOW)
    return repo, gateway, reporter, metrics


def submit(gateway, key: str, category: str = "finance", object_type: str = "strategy") -> str:
    payload = {
        "object_ref": "git://repo/strategy@abc123",
        "category": category,
        "object_type": object_type,
        "submitter": "trader-01",
        "purpose": "l0_settle",
        "spec_id": "EVS-20261101-0001",
        "env_manifest": {"endpoints": ["https://object.local/health"]},
    }
    return gateway.submit(payload, idempotency_key=key).eval_id


# ---------- 快照 ----------


def test_empty_snapshot_has_zero_counts():
    _, _, _, metrics = make_stack()
    snap = metrics.snapshot()
    assert snap["accepted"] == 0
    assert snap["backlog"] == 0
    assert snap["success_rate"] is None
    assert snap["latency_ms"] == {"avg": None, "max": None, "samples": 0}
    assert snap["gate_shadow"] is True
    assert snap["generated_at"] == "2026-11-01T12:00:00Z"


def test_snapshot_counts_status_verdict_category():
    repo, gateway, reporter, metrics = make_stack()
    eval_id = submit(gateway, "k-1")
    submit(gateway, "k-2", category="ai", object_type="model")
    cancelled = submit(gateway, "k-3")
    reporter.finalize_empty(eval_id)
    repo.update_status(cancelled, "cancelled")

    snap = metrics.snapshot()
    assert snap["accepted"] == 3
    assert snap["by_status"]["succeeded"] == 1
    assert snap["by_status"]["queued"] == 1
    assert snap["by_status"]["cancelled"] == 1
    assert snap["by_verdict"]["INCONCLUSIVE"] == 1
    assert snap["by_verdict"]["none"] == 2
    assert snap["by_category"] == {"finance": 2, "ai": 1, "engineering": 0}
    assert snap["backlog"] == 1
    assert snap["success_rate"] == 1.0


def test_success_rate_ignores_cancelled():
    repo, gateway, reporter, metrics = make_stack()
    ok = submit(gateway, "k-1")
    bad = submit(gateway, "k-2")
    cancelled = submit(gateway, "k-3")
    reporter.finalize_empty(ok)
    repo.update_status(bad, "failed")
    repo.update_status(cancelled, "cancelled")
    snap = metrics.snapshot()
    assert snap["success_rate"] == 0.5


def test_latency_measured_from_created_to_decided():
    repo, gateway, reporter, metrics = make_stack()
    eval_id = submit(gateway, "k-1")
    reporter.finalize_empty(eval_id)
    snap = metrics.snapshot()
    assert snap["latency_ms"]["samples"] == 1
    assert snap["latency_ms"]["avg"] == 0  # 固定时钟：created == decided
    assert snap["latency_ms"]["max"] == 0


def test_snapshot_time_window_filter():
    repo, gateway, reporter, metrics = make_stack()
    submit(gateway, "k-1")
    snap = metrics.snapshot(from_dt=NOW - timedelta(hours=1), to_dt=NOW + timedelta(hours=1))
    assert snap["accepted"] == 1
    assert metrics.snapshot(from_dt=NOW + timedelta(hours=2))["accepted"] == 0


# ---------- Runner 统计 ----------


def test_record_run_accumulates():
    _, _, _, metrics = make_stack()
    metrics.record_run(RunOutcome("EV-1", "succeeded", 2, "RUN-1", None), elapsed_ms=1200)
    metrics.record_run(RunOutcome("EV-2", "failed", 3, None, "boom"), elapsed_ms=800)
    metrics.record_run(RunOutcome("EV-3", "cancelled", 0, None, "cancel"), elapsed_ms=0)
    snap = metrics.snapshot()
    assert snap["runs"] == {
        "total": 3,
        "succeeded": 1,
        "failed": 1,
        "cancelled": 1,
        "attempts": 5,
        "avg_ms": 667,
    }


def test_runner_records_metrics_snapshot():
    repo, gateway, reporter, metrics = make_stack()
    eval_id = submit(gateway, "k-1")
    runner = Runner(repo=repo, reporter=reporter, metrics=metrics)
    runner.enqueue(eval_id)
    runner.run_once(timeout=0)
    snap = metrics.snapshot()
    assert snap["runs"]["total"] == 1
    assert snap["runs"]["succeeded"] == 1


# ---------- API ----------


def test_api_metrics_endpoint():
    repo, gateway, reporter, metrics = make_stack()
    submit(gateway, "k-1")
    reporter.finalize_empty(repo.list_requests()[0]["eval_id"])
    client = TestClient(create_app(repo=repo, gateway=gateway, reporter=reporter, metrics=metrics))
    resp = client.get("/api/v1/eval/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] == 1
    assert body["by_status"]["succeeded"] == 1
    assert body["gate_shadow"] is True


def test_api_metrics_invalid_time_400():
    repo, gateway, reporter, metrics = make_stack()
    client = TestClient(create_app(repo=repo, gateway=gateway, reporter=reporter, metrics=metrics))
    resp = client.get("/api/v1/eval/metrics", params={"from": "not-a-time"})
    assert resp.status_code == 400
