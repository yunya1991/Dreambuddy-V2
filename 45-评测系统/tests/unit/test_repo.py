# -*- coding: utf-8 -*-
"""
test_repo.py — P0-5 存储层测试
===============================
验收（PLAN P0-5 / SPEC §12）：
- InMemoryRepo 与 PgRepo 同一接口（EvalRepo）：受理、Run、证据链、报告
- 幂等唯一键：idempotency_key 冲突拒绝
- 报告可重建查询：get_report 从规范化行还原 eval_report.v1.json 结构
- DSN 清洗：去除 Prisma ?schema= 参数（认知经验 VM-1791981667092）

PG 集成测试：设置 EVAL_PG_DSN 后执行；未设置自动跳过（本机默认）。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.gateway import CategoriesConfig, Gateway, spec_hash_placeholder  # noqa: E402
from storage.repo import (  # noqa: E402
    EvalItemRecord,
    EvalRunRecord,
    InMemoryRepo,
    clean_dsn,
)

MODULE_ROOT = Path(__file__).resolve().parent.parent.parent
CATEGORIES_PATH = MODULE_ROOT / "config" / "categories.yaml"

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
SPEC_HASH = spec_hash_placeholder("EVS-20261101-0001")

VALID_ENV_MANIFEST = {
    "runtime": "python3.11",
    "endpoints": ["https://object.local/health"],
}


def make_payload(category: str = "finance", object_type: str = "strategy"):
    return {
        "object_ref": "git://repo/strategy@abc123",
        "category": category,
        "object_type": object_type,
        "submitter": "trader-01",
        "purpose": "l0_settle",
        "priority": "normal",
        "spec_id": "EVS-20261101-0001",
        "env_manifest": dict(VALID_ENV_MANIFEST),
    }


def make_run(eval_id: str, attempt: int = 1, run_id: str | None = None) -> EvalRunRecord:
    return EvalRunRecord(
        run_id=run_id or f"RUN-{eval_id.removeprefix('EV-')}-{attempt:02d}",
        eval_id=eval_id,
        evaluator_id="EV-placeholder.empty",
        evaluator_version="0.0.0",
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
    kind: str = "weighted",
    status: str = "PASS",
    score: float | None = 0.8,
    weight: float | None = 0.5,
    n: int | None = 100,
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
def gateway(repo):
    categories = CategoriesConfig.load(CATEGORIES_PATH)
    return Gateway(store=repo, categories=categories, clock=lambda: NOW)


# ---------- DSN 清洗 ----------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("postgresql://u:p@h:5432/db?schema=public", "postgresql://u:p@h:5432/db"),
        (
            "postgresql://u:p@h:5432/db?schema=public&sslmode=require",
            "postgresql://u:p@h:5432/db?sslmode=require",
        ),
        ("postgresql://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
    ],
)
def test_clean_dsn_strips_prisma_schema(raw, expected):
    assert clean_dsn(raw) == expected


# ---------- 受理存储（兼容 Gateway 的 EvalRequestStore 接口） ----------


def test_request_roundtrip(repo, gateway):
    result = gateway.submit(make_payload(), idempotency_key="rk-1")
    by_key = repo.get_by_idempotency_key("rk-1")
    assert by_key is not None
    assert by_key.eval_id == result.eval_id
    assert by_key.status == "queued"
    by_id = repo.get_request(result.eval_id)
    assert by_id == by_key
    assert repo.count_for_day("20261101") == 1
    assert repo.count_for_day("20990101") == 0


def test_duplicate_idempotency_key_rejected(repo, gateway):
    gateway.submit(make_payload(), idempotency_key="dup")
    record = repo.get_by_idempotency_key("dup")
    with pytest.raises(ValueError):
        repo.insert_request(record)


def test_get_request_unknown_returns_none(repo):
    assert repo.get_request("EV-20990101-999999") is None
    assert repo.get_by_idempotency_key("nope") is None


def test_update_status(repo, gateway):
    result = gateway.submit(make_payload(), idempotency_key="st-1")
    assert repo.update_status(result.eval_id, "cancelled") is True
    assert repo.get_request(result.eval_id).status == "cancelled"
    assert repo.update_status("EV-20990101-999999", "cancelled") is False


# ---------- Run / 证据 / 报告 ----------


def test_run_roundtrip(repo, gateway):
    result = gateway.submit(make_payload(), idempotency_key="run-1")
    run = make_run(result.eval_id)
    repo.insert_run(run)
    assert repo.get_run(run.run_id) == run
    assert repo.latest_run_for_eval(result.eval_id) == run
    assert repo.get_run("RUN-nope") is None


def test_latest_run_picks_highest_attempt(repo, gateway):
    result = gateway.submit(make_payload(), idempotency_key="run-2")
    r1 = make_run(result.eval_id, attempt=1)
    r2 = make_run(result.eval_id, attempt=2)
    repo.insert_run(r1)
    repo.insert_run(r2)
    assert repo.latest_run_for_eval(result.eval_id).run_id == r2.run_id


def test_item_roundtrip(repo, gateway):
    result = gateway.submit(make_payload(), idempotency_key="it-1")
    run = make_run(result.eval_id)
    repo.insert_run(run)
    items = [make_item(run.run_id, "F-W1"), make_item(run.run_id, "F-W2")]
    repo.insert_items(items)
    rows = repo.list_items(run.run_id)
    assert [i.name for i in rows] == ["F-W1", "F-W2"]


def test_evidence_chain_helpers(repo, gateway):
    from storage.repo import EvidenceRow

    result = gateway.submit(make_payload(), idempotency_key="ev-1")
    run = make_run(result.eval_id)
    repo.insert_run(run)
    assert repo.latest_evidence_hash(run.run_id) is None
    e1 = EvidenceRow(
        evidence_id=f"EVD-{run.run_id}-01",
        run_id=run.run_id,
        sha256="a" * 64,
        uri=f"local://evidence/EVD-{run.run_id}-01",
        prev_hash=None,
        hash="b" * 64,
        signed_by=None,
        created_at=NOW,
    )
    e2 = EvidenceRow(
        evidence_id=f"EVD-{run.run_id}-02",
        run_id=run.run_id,
        sha256="c" * 64,
        uri=f"local://evidence/EVD-{run.run_id}-02",
        prev_hash="b" * 64,
        hash="d" * 64,
        signed_by=None,
        created_at=NOW + timedelta(seconds=1),
    )
    repo.insert_evidence(e1)
    repo.insert_evidence(e2)
    assert repo.count_evidence(run.run_id) == 2
    assert repo.latest_evidence_hash(run.run_id) == "d" * 64


# ---------- 报告重建 ----------


def _report_dict(eval_id: str, run_id: str) -> dict:
    return {
        "eval_id": eval_id,
        "run_id": run_id,
        "spec_hash": SPEC_HASH,
        "verdict": "INCONCLUSIVE",
        "score": None,
        "n": None,
        "ci": None,
        "items": [],
        "block_reasons": ["no_items: 评测项为空"],
        "evidence": {"uri": "local://evidence/EVD-x", "sha256": "e" * 64},
        "thresholds_version": "TH-2026Q4@1",
        "baseline_run_id": None,
        "baseline_diff": None,
        "sla": None,
        "evaluated_at": "2026-11-01T12:00:00Z",
        "expires_at": "2026-11-08T12:00:00Z",
    }


def test_report_roundtrip(repo, gateway):
    from storage.repo import EvidenceRow

    result = gateway.submit(make_payload(), idempotency_key="rp-1")
    run = make_run(result.eval_id)
    repo.insert_run(run)
    report = _report_dict(result.eval_id, run.run_id)
    # §2.1 Evidence-First：报告必须能挂到真实证据行，否则重建即拒
    repo.insert_evidence(
        EvidenceRow(
            evidence_id=f"EVD-{run.run_id}-01",
            run_id=run.run_id,
            sha256="e" * 64,
            uri="local://evidence/EVD-x",
            prev_hash=None,
            hash="f" * 64,
            signed_by=None,
            created_at=NOW,
        )
    )
    repo.insert_report(report)
    loaded = repo.get_report(result.eval_id)
    assert loaded is not None
    for key in (
        "eval_id",
        "run_id",
        "spec_hash",
        "verdict",
        "score",
        "n",
        "ci",
        "items",
        "block_reasons",
        "thresholds_version",
        "baseline_run_id",
        "sla",
        "evaluated_at",
        "expires_at",
    ):
        assert loaded[key] == report[key], f"字段 {key} 重建不一致"
    assert loaded["evidence"]["sha256"] == report["evidence"]["sha256"]


def test_get_report_unknown_returns_none(repo):
    assert repo.get_report("EV-20990101-999999") is None


# ---------- 列表查询（P0-6 GET /eval 依赖） ----------


def test_list_requests_filters(repo, gateway):
    gateway.submit(make_payload(), idempotency_key="L1")
    r2 = gateway.submit(make_payload("ai", "model"), idempotency_key="L2")
    gateway.submit(make_payload(), idempotency_key="L3")
    run = make_run(r2.eval_id)
    repo.insert_run(run)
    repo.insert_report(_report_dict(r2.eval_id, run.run_id))

    all_rows = repo.list_requests()
    assert len(all_rows) == 3
    assert all(row["verdict"] is None for row in all_rows if row["eval_id"] != r2.eval_id)

    by_cat = repo.list_requests(category="ai")
    assert [row["eval_id"] for row in by_cat] == [r2.eval_id]

    by_verdict = repo.list_requests(verdict="INCONCLUSIVE")
    assert [row["eval_id"] for row in by_verdict] == [r2.eval_id]

    by_submitter = repo.list_requests(submitter="nobody")
    assert by_submitter == []

    limited = repo.list_requests(limit=2)
    assert len(limited) == 2


def test_list_requests_time_window(repo, gateway):
    gateway.submit(make_payload(), idempotency_key="T1")
    rows = repo.list_requests(from_dt=NOW - timedelta(hours=1), to_dt=NOW + timedelta(hours=1))
    assert len(rows) == 1
    assert repo.list_requests(from_dt=NOW + timedelta(hours=2)) == []
    assert repo.list_requests(to_dt=NOW - timedelta(hours=2)) == []


# ---------- InMemory 错误路径（P0-7 覆盖率补齐） ----------


def test_canonical_json_rejects_unserializable():
    from storage.repo import canonical_json

    with pytest.raises(TypeError, match="不可序列化"):
        canonical_json({"bad": object()})


def test_assemble_report_missing_evidence_lookup_error():
    from storage.repo import assemble_report

    with pytest.raises(LookupError, match="缺证据行"):
        assemble_report(
            report_row={"eval_id": "EV-20261101-000001"},
            run_row={},
            item_rows=[],
            evidence_row=None,
        )


def test_get_report_with_ci_reassembled(repo, gateway):
    """ci_lower/upper 非空时重建 ci 字典（method 占位 none）。"""
    result = gateway.submit(make_payload(), idempotency_key="ci-1")
    run = make_run(result.eval_id)
    repo.insert_run(run)
    _insert_evidence(repo, run.run_id)
    report = _report_dict(result.eval_id, run.run_id)
    report["ci"] = {"lower": 0.7, "upper": 0.9, "method": "none"}
    repo.insert_report(report)
    loaded = repo.get_report(result.eval_id)
    assert loaded["ci"] == {"lower": 0.7, "upper": 0.9, "method": "none"}


def test_insert_run_duplicate_rejected(repo, gateway):
    result = gateway.submit(make_payload(), idempotency_key="run-dup")
    run = make_run(result.eval_id)
    repo.insert_run(run)
    with pytest.raises(ValueError, match="run_id 冲突"):
        repo.insert_run(run)


def test_insert_evidence_duplicate_hash_rejected(repo, gateway):
    result = gateway.submit(make_payload(), idempotency_key="ev-dup")
    run = make_run(result.eval_id)
    repo.insert_run(run)
    entry = _insert_evidence(repo, run.run_id)
    with pytest.raises(ValueError, match="证据哈希冲突"):
        repo.insert_evidence(entry)


def test_insert_report_duplicate_rejected(repo, gateway):
    result = gateway.submit(make_payload(), idempotency_key="rep-dup")
    report = _report_dict(result.eval_id, "RUN-x")
    repo.insert_report(report)
    with pytest.raises(ValueError, match="报告已存在"):
        repo.insert_report(report)


def test_get_report_missing_run_lookup_error(repo, gateway):
    result = gateway.submit(make_payload(), idempotency_key="rep-norun")
    repo.insert_report(_report_dict(result.eval_id, "RUN-ghost"))
    with pytest.raises(LookupError, match="缺 Run 行"):
        repo.get_report(result.eval_id)


def _insert_evidence(repo, run_id: str):
    from storage.repo import EvidenceRow

    entry = EvidenceRow(
        evidence_id=f"EVD-{run_id}-01",
        run_id=run_id,
        sha256="a" * 64,
        uri=f"local://evidence/EVD-{run_id}-01",
        prev_hash=None,
        hash="b" * 64,
        signed_by=None,
        created_at=NOW,
    )
    repo.insert_evidence(entry)
    return entry


# ---------- PG 集成测试（可选） ----------


@pytest.mark.skipif(
    not os.environ.get("EVAL_PG_DSN"), reason="EVAL_PG_DSN 未设置，跳过 PG 集成测试"
)
class TestPgRepo:
    """PgRepo 对真实 PG 的全链路往返；结束后 DELETE 清理，不留痕迹。"""

    def test_roundtrip(self):
        psycopg = pytest.importorskip("psycopg")
        from core.registry import ThresholdRegistry
        from core.reporter import Reporter
        from storage.repo import PgRepo

        dsn = clean_dsn(os.environ["EVAL_PG_DSN"])
        migrations = sorted((MODULE_ROOT / "storage" / "migrations").glob("*.sql"))
        repo = PgRepo(dsn)
        categories = CategoriesConfig.load(CATEGORIES_PATH)
        registry = ThresholdRegistry.load(MODULE_ROOT / "config" / "thresholds.yaml")
        gw = Gateway(store=repo, categories=categories, clock=lambda: NOW)
        reporter = Reporter(repo=repo, thresholds=registry, clock=lambda: NOW)

        with psycopg.connect(dsn, autocommit=True) as conn:
            for mig in migrations:
                conn.execute(mig.read_text(encoding="utf-8"))

        eval_ids: list[str] = []
        try:
            result = gw.submit(make_payload(), idempotency_key="pg-it-1")
            eval_ids.append(result.eval_id)
            again = gw.submit(make_payload(), idempotency_key="pg-it-1")
            assert again.eval_id == result.eval_id  # PG 侧幂等

            report = reporter.finalize_empty(result.eval_id)
            assert report["verdict"] == "INCONCLUSIVE"
            loaded = repo.get_report(result.eval_id)
            assert loaded is not None
            assert loaded["verdict"] == "INCONCLUSIVE"
            assert loaded["spec_hash"] == report["spec_hash"]
            assert loaded["evidence"]["sha256"] == report["evidence"]["sha256"]
            assert repo.get_request(result.eval_id).status == "succeeded"
            rows = repo.list_requests(verdict="INCONCLUSIVE")
            assert any(r["eval_id"] == result.eval_id for r in rows)
        finally:
            with psycopg.connect(dsn, autocommit=True) as conn:
                for eid in eval_ids:
                    conn.execute("DELETE FROM eval_requests WHERE eval_id = %s", (eid,))
