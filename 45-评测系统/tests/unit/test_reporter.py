# -*- coding: utf-8 -*-
"""
test_reporter.py — P0-5 报告归档测试
=====================================
验收（PLAN P0-5 / SPEC §2.1/§4/§13.2）：
- 空评测生成报告并可查询（verdict=INCONCLUSIVE，fail-closed）
- 报告符合 eval_report.v1.json 契约（jsonschema 全量校验）
- 判定合成：BLOCK > INCONCLUSIVE > PASS（§4 优先级）
- 证据哈希链：首条 prev_hash=None，hash=sha256(prev||sha256||uri)
- expires_at = evaluated_at + 7 天（§4 凭证默认有效期）
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.gateway import CategoriesConfig, Gateway, spec_hash_placeholder  # noqa: E402
from core.registry import ThresholdRegistry  # noqa: E402
from core.reporter import Reporter, ReporterError  # noqa: E402
from storage.repo import EvalItemRecord, EvalRunRecord, InMemoryRepo  # noqa: E402

MODULE_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_SCHEMA = json.loads(
    (MODULE_ROOT / "contracts" / "schemas" / "eval_report.v1.json").read_text("utf-8")
)
VALIDATOR = Draft202012Validator(REPORT_SCHEMA)

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
SPEC_HASH = spec_hash_placeholder("EVS-20261101-0001")

VALID_ENV_MANIFEST = {
    "runtime": "python3.11",
    "endpoints": ["https://object.local/health"],
}


def make_payload():
    return {
        "object_ref": "git://repo/strategy@abc123",
        "category": "finance",
        "object_type": "strategy",
        "submitter": "trader-01",
        "purpose": "l0_settle",
        "priority": "normal",
        "spec_id": "EVS-20261101-0001",
        "env_manifest": dict(VALID_ENV_MANIFEST),
    }


def make_run(eval_id: str, attempt: int = 1) -> EvalRunRecord:
    return EvalRunRecord(
        run_id=f"RUN-{eval_id.removeprefix('EV-')}-{attempt:02d}",
        eval_id=eval_id,
        evaluator_id="EV-finance.backtest",
        evaluator_version="1.0.0",
        scorer_versions=None,
        attempt=attempt,
        spec_hash=SPEC_HASH,
        code_commit=None,
        env_snapshot=None,
        budget_ms=None,
        degraded=False,
        started_at=NOW,
        ended_at=NOW,
        status="succeeded",
    )


def make_item(
    run_id: str,
    name: str,
    kind: str,
    status: str,
    score: float | None = None,
    weight: float | None = None,
    n: int | None = None,
) -> EvalItemRecord:
    return EvalItemRecord(
        item_id=f"IT-{run_id}-{name}",
        run_id=run_id,
        name=name,
        kind=kind,
        score=score,
        n=n,
        ci_lower=None,
        ci_upper=None,
        weight=weight,
        status=status,
        evidence_id=None,
        detail=None,
    )


@pytest.fixture
def repo():
    return InMemoryRepo()


@pytest.fixture
def eval_id(repo):
    categories = CategoriesConfig.load(MODULE_ROOT / "config" / "categories.yaml")
    gw = Gateway(store=repo, categories=categories, clock=lambda: NOW)
    return gw.submit(make_payload(), idempotency_key="rep-fixture").eval_id


@pytest.fixture
def reporter(repo):
    registry = ThresholdRegistry.load(MODULE_ROOT / "config" / "thresholds.yaml")
    return Reporter(repo=repo, thresholds=registry, clock=lambda: NOW)


def assert_schema_valid(report: dict) -> None:
    errors = list(VALIDATOR.iter_errors(report))
    assert not errors, f"报告违反契约: {[e.message for e in errors][:3]}"


# ---------- 空评测（P0 验收核心） ----------


def test_finalize_empty_eval_inconclusive(reporter, repo, eval_id):
    report = reporter.finalize_empty(eval_id)
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["items"] == []
    assert any("no_items" in r for r in report["block_reasons"])
    assert report["score"] is None and report["n"] is None and report["ci"] is None
    assert_schema_valid(report)


def test_finalize_empty_persisted_and_queryable(reporter, repo, eval_id):
    report = reporter.finalize_empty(eval_id)
    loaded = repo.get_report(eval_id)
    assert loaded is not None
    assert loaded["verdict"] == report["verdict"]
    assert loaded["run_id"] == report["run_id"]
    assert loaded["spec_hash"] == report["spec_hash"]
    assert loaded["evaluated_at"] == report["evaluated_at"]
    assert loaded["expires_at"] == report["expires_at"]
    assert loaded["evidence"] == report["evidence"]
    assert repo.get_request(eval_id).status == "succeeded"


def test_finalize_unknown_eval_rejected(reporter):
    with pytest.raises(ReporterError):
        reporter.finalize_empty("EV-20990101-999999")


# ---------- 判定合成（§4 优先级） ----------


def test_verdict_block_on_hard_item_failure(reporter, eval_id):
    run = make_run(eval_id)
    items = [
        make_item(run.run_id, "F-H1", "hard", "BLOCK"),
        make_item(run.run_id, "F-W1", "weighted", "PASS", score=0.9, weight=1.0, n=100),
    ]
    report = reporter.finalize(eval_id, run, items)
    assert report["verdict"] == "BLOCK"
    assert any("F-H1" in r for r in report["block_reasons"])
    assert_schema_valid(report)


def test_verdict_pass_when_all_items_pass(reporter, eval_id):
    run = make_run(eval_id)
    items = [
        make_item(run.run_id, "F-H1", "hard", "PASS"),
        make_item(run.run_id, "F-W1", "weighted", "PASS", score=0.8, weight=0.5, n=120),
        make_item(run.run_id, "F-W2", "weighted", "PASS", score=0.6, weight=0.5, n=80),
    ]
    report = reporter.finalize(eval_id, run, items)
    assert report["verdict"] == "PASS"
    assert report["score"] == pytest.approx(0.7)
    assert report["n"] == 80  # 保守取加权项最小样本量
    assert report["block_reasons"] == []
    assert_schema_valid(report)


def test_verdict_inconclusive_on_inconclusive_item(reporter, eval_id):
    run = make_run(eval_id)
    items = [
        make_item(run.run_id, "F-H1", "hard", "PASS"),
        make_item(run.run_id, "F-W1", "weighted", "INCONCLUSIVE", n=10),
    ]
    report = reporter.finalize(eval_id, run, items)
    assert report["verdict"] == "INCONCLUSIVE"
    assert any("F-W1" in r for r in report["block_reasons"])
    assert_schema_valid(report)


def test_block_priority_over_inconclusive(reporter, eval_id):
    run = make_run(eval_id)
    items = [
        make_item(run.run_id, "F-W1", "weighted", "INCONCLUSIVE"),
        make_item(run.run_id, "F-H2", "hard", "BLOCK"),
    ]
    report = reporter.finalize(eval_id, run, items)
    assert report["verdict"] == "BLOCK"


def test_all_skipped_items_inconclusive(reporter, eval_id):
    run = make_run(eval_id)
    items = [make_item(run.run_id, "E-W1", "weighted", "SKIPPED")]
    report = reporter.finalize(eval_id, run, items)
    assert report["verdict"] == "INCONCLUSIVE"
    assert any("all_skipped" in r for r in report["block_reasons"])


# ---------- 证据哈希链 ----------


def test_evidence_hash_chain_first_entry(reporter, repo, eval_id):
    report = reporter.finalize_empty(eval_id)
    run = repo.latest_run_for_eval(eval_id)
    entries = repo.list_evidence(run.run_id)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.prev_hash is None
    expected = hashlib.sha256(f"null|{entry.sha256}|{entry.uri}".encode("utf-8")).hexdigest()
    assert entry.hash == expected
    assert report["evidence"] == {"uri": entry.uri, "sha256": entry.sha256}


def test_evidence_content_tamper_detectable(reporter, repo, eval_id):
    """篡改任一字段 → 链哈希不一致（离线验证语义）。"""
    reporter.finalize_empty(eval_id)
    run = repo.latest_run_for_eval(eval_id)
    entry = repo.list_evidence(run.run_id)[0]
    tampered = hashlib.sha256(
        f"null|{entry.sha256}|local://evidence/TAMPERED".encode("utf-8")
    ).hexdigest()
    assert tampered != entry.hash


# ---------- 时间与凭证 ----------


def test_expires_at_is_7_days_after_evaluated_at(reporter, eval_id):
    report = reporter.finalize_empty(eval_id)
    assert report["evaluated_at"] == "2026-11-01T12:00:00Z"
    assert report["expires_at"] == "2026-11-08T12:00:00Z"


def test_thresholds_version_propagated(reporter, eval_id):
    report = reporter.finalize_empty(eval_id)
    assert report["thresholds_version"] == "TH-2026Q4@1"
