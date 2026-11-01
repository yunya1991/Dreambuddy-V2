# -*- coding: utf-8 -*-
"""P3-2/P3-4/P3-5 CLI 测试：evalctl enforce / audit 退出码与审计。"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from api.cli import EXIT_BLOCK, EXIT_ERROR, EXIT_PASS, main
from core.gateway import EvalRequestRecord
from core.registry import ThresholdRegistry
from core.reporter import Reporter
from storage.audit import AuditLog
from storage.repo import EvalItemRecord, EvalRunRecord, InMemoryRepo, sha256_hex

NOW = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
SPEC_HASH = sha256_hex("spec-cli-p3")
EVAL_ID = "EV-20261101-0001"


def seed(status: str = "PASS", purpose: str = "deploy") -> tuple[InMemoryRepo, AuditLog]:
    repo = InMemoryRepo()
    reporter = Reporter(repo=repo, thresholds=ThresholdRegistry.load(), clock=lambda: NOW)
    repo.insert_request(
        EvalRequestRecord(
            eval_id=EVAL_ID,
            idempotency_key="idem-cli",
            object_ref="git://repo@main",
            category="finance",
            object_type="strategy",
            submitter="alice",
            purpose=purpose,
            priority="normal",
            spec_id="EVS-20261101-0001",
            env_manifest={"endpoints": ["http://localhost:8000"]},
            spec_hash=SPEC_HASH,
            status="queued",
            created_at=NOW,
        )
    )
    run = EvalRunRecord(
        run_id="RUN-20261101-0001-01",
        eval_id=EVAL_ID,
        evaluator_id="EV-finance.backtest",
        evaluator_version="1.2.0",
        scorer_versions=None,
        attempt=1,
        spec_hash=SPEC_HASH,
        code_commit="abc123",
        env_snapshot=None,
        budget_ms=None,
        degraded=False,
        started_at=NOW,
        ended_at=NOW,
        status="succeeded",
    )
    reporter.finalize(
        EVAL_ID,
        run,
        [
            EvalItemRecord(
                item_id=f"{run.run_id}-i1",
                run_id=run.run_id,
                name="F-H6-overfit",
                kind="hard",
                score=None,
                n=None,
                ci_lower=None,
                ci_upper=None,
                weight=None,
                status=status,
                evidence_id=None,
                detail=None,
            )
        ],
    )
    return repo, AuditLog(path=tmp_audit_path(repo), clock=lambda: NOW)


def tmp_audit_path(repo: InMemoryRepo):
    # 测试隔离：每个 repo 实例独立审计文件（不使用仓库内 artifacts）
    import pathlib
    import tempfile

    return pathlib.Path(tempfile.mkdtemp(prefix="eval-audit-")) / "enforcement.jsonl"


def run_cli(argv, repo, audit, **kwargs) -> tuple[int, dict]:
    out = io.StringIO()
    code = main(argv, repo=repo, out=out, audit_log=audit, **kwargs)
    return code, json.loads(out.getvalue())


def test_enforce_shadow_pass_exits_zero():
    repo, audit = seed()
    code, payload = run_cli(
        ["enforce", "--kind", "deploy", "--eval-id", EVAL_ID], repo, audit, shadow=True
    )
    assert code == EXIT_PASS
    assert payload["decision"] == "PASS"
    assert payload["mode"] == "shadow"


def test_enforce_shadow_block_is_observe_only():
    repo, audit = seed(status="BLOCK")
    code, payload = run_cli(
        ["enforce", "--kind", "deploy", "--eval-id", EVAL_ID], repo, audit, shadow=True
    )
    assert code == EXIT_PASS
    assert payload["decision"] == "SHADOW_WOULD_BLOCK"


def test_enforce_live_block_exits_two():
    repo, audit = seed(status="BLOCK")
    code, payload = run_cli(
        ["enforce", "--kind", "deploy", "--eval-id", EVAL_ID], repo, audit, shadow=False
    )
    assert code == EXIT_BLOCK
    assert payload["decision"] == "BLOCK"
    assert any("verdict_not_pass" in r for r in payload["reasons"])


def test_enforce_live_unknown_eval_exits_error():
    repo, audit = seed()
    code, payload = run_cli(
        ["enforce", "--kind", "deploy", "--eval-id", "EV-unknown"], repo, audit, shadow=False
    )
    assert code == EXIT_ERROR
    assert any("unknown_eval_id" in r for r in payload["reasons"])


def test_enforce_live_dual_without_approval_exits_block():
    repo, audit = seed()
    code, payload = run_cli(
        [
            "enforce",
            "--kind",
            "deploy",
            "--eval-id",
            EVAL_ID,
            "--require-approval",
        ],
        repo,
        audit,
        shadow=False,
        approvals=lambda _aid: True,
    )
    assert code == EXIT_BLOCK
    assert any("approval_missing" in r for r in payload["reasons"])


def test_enforce_live_dual_with_approval_passes():
    repo, audit = seed()
    code, payload = run_cli(
        [
            "enforce",
            "--kind",
            "deploy",
            "--eval-id",
            EVAL_ID,
            "--approval-id",
            "AP-1",
            "--require-approval",
        ],
        repo,
        audit,
        shadow=False,
        approvals=lambda aid: aid == "AP-1",
    )
    assert code == EXIT_PASS
    assert payload["approval_id"] == "AP-1"


def test_audit_unknown_eval_exits_error():
    repo, audit = seed()
    code, payload = run_cli(["audit", "--eval-id", "EV-unknown"], repo, audit)
    assert code == EXIT_ERROR
    assert "error" in payload


def test_audit_full_chain_after_enforce():
    repo, audit = seed()
    run_cli(["enforce", "--kind", "deploy", "--eval-id", EVAL_ID], repo, audit, shadow=False)
    code, payload = run_cli(["audit", "--eval-id", EVAL_ID], repo, audit)

    assert code == EXIT_PASS
    assert payload["request"]["purpose"] == "deploy"
    assert payload["run"]["run_id"] == "RUN-20261101-0001-01"
    assert len(payload["items"]) == 1
    assert len(payload["evidence"]) == 1
    assert payload["report"]["verdict"] == "PASS"
    assert payload["enforcements"][0]["decision"] == "PASS"
    assert payload["complete"] is True
    assert payload["cancelled"] is False
