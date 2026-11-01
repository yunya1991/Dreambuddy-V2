# -*- coding: utf-8 -*-
"""
test_index_publisher.py — P1-4 报告落盘与 41 索引登记测试
==========================================================
验收（PLAN P1-4）：
- 报告 JSON 落盘到 `<base>/reports/<eval_id>.json`，返回 file:// URI
- 同一报告重放幂等；内容不同即拒（证据不可变）
- 41 索引更新钩子 fail-open：钩子异常不阻断发布
- Runner 装配 publisher 后，成功执行自动落盘并回填 report_uri
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.gateway import CategoriesConfig, Gateway  # noqa: E402
from core.registry import ThresholdRegistry  # noqa: E402
from core.reporter import Reporter  # noqa: E402
from core.runner import Runner  # noqa: E402
from storage.index_publisher import (  # noqa: E402
    FileReportPublisher,
    PublishedReport,
    PublisherError,
)
from storage.repo import InMemoryRepo  # noqa: E402

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

MAPPING = {
    "finance": ("strategy", "service"),
    "ai": ("model", "service"),
    "engineering": ("code_artifact", "dataset", "knowledge"),
}

REPORT = {
    "eval_id": "EV-20261101-000001",
    "run_id": "RUN-20261101-000001-01",
    "verdict": "PASS",
    "score": 0.9,
}


def make_publisher(tmp_path: Path, hook=None) -> FileReportPublisher:
    return FileReportPublisher(base_dir=tmp_path, hook=hook)


# ---------- 落盘 ----------


def test_publish_writes_report_file(tmp_path):
    publisher = make_publisher(tmp_path)
    published = publisher.publish(REPORT)
    assert isinstance(published, PublishedReport)
    path = tmp_path / "reports" / "EV-20261101-000001.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == "PASS"
    assert published.uri == f"file://{path.resolve()}"
    assert published.path == path.resolve()
    assert published.sha256


def test_publish_is_idempotent_for_same_content(tmp_path):
    publisher = make_publisher(tmp_path)
    first = publisher.publish(REPORT)
    second = publisher.publish(dict(REPORT))
    assert first == second


def test_publish_rejects_different_content_for_same_eval(tmp_path):
    publisher = make_publisher(tmp_path)
    publisher.publish(REPORT)
    with pytest.raises(PublisherError):
        publisher.publish({**REPORT, "verdict": "BLOCK"})


def test_publish_requires_eval_id(tmp_path):
    publisher = make_publisher(tmp_path)
    with pytest.raises(PublisherError):
        publisher.publish({"verdict": "PASS"})


# ---------- 41 索引钩子（fail-open） ----------


def test_hook_called_with_uri_and_report(tmp_path):
    calls: list[tuple[str, dict]] = []
    publisher = make_publisher(tmp_path, hook=lambda uri, report: calls.append((uri, report)))
    published = publisher.publish(REPORT)
    assert calls == [(published.uri, REPORT)]


def test_hook_error_is_fail_open(tmp_path):
    def boom(_uri: str, _report: dict) -> None:
        raise RuntimeError("41 index down")

    publisher = make_publisher(tmp_path, hook=boom)
    published = publisher.publish(REPORT)
    assert published.path.is_file()
    assert publisher.hook_errors == 1


# ---------- Runner 接线 ----------


def make_stack():
    repo = InMemoryRepo()
    gateway = Gateway(
        store=repo,
        categories=CategoriesConfig(version="CAT-TEST@1", mapping=MAPPING, gate_shadow=True),
        clock=lambda: NOW,
    )
    reporter = Reporter(repo=repo, thresholds=ThresholdRegistry.load(), clock=lambda: NOW)
    return repo, gateway, reporter


def submit(gateway, key: str = "k-1") -> str:
    payload = {
        "object_ref": "git://repo/strategy@abc123",
        "category": "finance",
        "object_type": "strategy",
        "submitter": "trader-01",
        "purpose": "l0_settle",
        "spec_id": "EVS-20261101-0001",
        "env_manifest": {"endpoints": ["https://object.local/health"]},
    }
    return gateway.submit(payload, idempotency_key=key).eval_id


def test_runner_publishes_report(tmp_path):
    repo, gateway, reporter = make_stack()
    eval_id = submit(gateway)
    publisher = make_publisher(tmp_path)
    runner = Runner(repo=repo, reporter=reporter, publisher=publisher)
    runner.enqueue(eval_id)
    outcome = runner.run_once(timeout=0)
    assert outcome.status == "succeeded"
    path = tmp_path / "reports" / f"{eval_id}.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == "INCONCLUSIVE"
    assert outcome.report_uri == f"file://{path.resolve()}"


def test_runner_without_publisher_has_no_report_uri():
    repo, gateway, reporter = make_stack()
    eval_id = submit(gateway)
    runner = Runner(repo=repo, reporter=reporter)
    runner.enqueue(eval_id)
    outcome = runner.run_once(timeout=0)
    assert outcome.report_uri is None
