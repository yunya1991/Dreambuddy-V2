# -*- coding: utf-8 -*-
"""P3-1 凭证签发与校验测试（SPEC §4 / §13.3）。"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from core.gate import (
    Credential,
    CredentialInvalidError,
    CredentialNotIssuableError,
    Gate,
    GateError,
)
from core.registry import ThresholdRegistry
from core.reporter import Reporter
from storage.repo import (
    CREDENTIAL_TTL_DAYS,
    EvalItemRecord,
    EvalRunRecord,
    InMemoryRepo,
    sha256_hex,
    zulu,
)

NOW = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
SPEC_HASH = sha256_hex("spec-p3-1")
EVAL_ID = "EV-20261101-0001"


def build_gate(clock=None) -> tuple[Gate, InMemoryRepo, Reporter]:
    repo = InMemoryRepo()
    thresholds = ThresholdRegistry.load()
    reporter = Reporter(repo=repo, thresholds=thresholds, clock=lambda: NOW)
    return Gate(repo=repo, clock=clock or (lambda: NOW)), repo, reporter


class VarClock:
    """可推进时钟：同一 Gate 先签发后校验，模拟时间流逝。"""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def seed_request(repo: InMemoryRepo, purpose: str = "deploy") -> None:
    from core.gateway import EvalRequestRecord

    repo.insert_request(
        EvalRequestRecord(
            eval_id=EVAL_ID,
            idempotency_key="idem-p3-1",
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


def make_items(run_id: str, status: str = "PASS") -> list[EvalItemRecord]:
    return [
        EvalItemRecord(
            item_id=f"{run_id}-i1",
            run_id=run_id,
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
    ]


def make_run(eval_id: str = EVAL_ID, run_id: str = "RUN-20261101-0001-01") -> EvalRunRecord:
    return EvalRunRecord(
        run_id=run_id,
        eval_id=eval_id,
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


def seed_report(
    repo: InMemoryRepo, reporter: Reporter, status: str = "PASS", purpose: str = "deploy"
) -> dict:
    seed_request(repo, purpose=purpose)
    run = make_run()
    return reporter.finalize(EVAL_ID, run, make_items(run.run_id, status))


# ---------- issue ----------


def test_issue_pass_binds_run_spec_verdict_thresholds_and_expiry():
    gate, repo, reporter = build_gate()
    report = seed_report(repo, reporter)

    credential = gate.issue(EVAL_ID)

    assert credential.eval_id == EVAL_ID
    assert credential.run_id == report["run_id"]
    assert credential.spec_hash == report["spec_hash"]
    assert credential.verdict == "PASS"
    assert credential.thresholds_version == report["thresholds_version"]
    assert credential.evaluator_id == "EV-finance.backtest"
    assert credential.evaluator_version == "1.2.0"
    assert credential.evidence_sha256 == report["evidence"]["sha256"]
    assert credential.issued_at == zulu(NOW)
    assert credential.expires_at == zulu(NOW + timedelta(days=CREDENTIAL_TTL_DAYS))


def test_issue_block_rejected():
    gate, repo, reporter = build_gate()
    seed_report(repo, reporter, status="BLOCK")

    with pytest.raises(CredentialNotIssuableError) as exc:
        gate.issue(EVAL_ID)
    assert exc.value.code == "verdict_not_pass"
    assert "BLOCK" in exc.value.detail


def test_issue_inconclusive_rejected():
    gate, repo, reporter = build_gate()
    seed_report(repo, reporter, status="INCONCLUSIVE")

    with pytest.raises(CredentialNotIssuableError) as exc:
        gate.issue(EVAL_ID)
    assert exc.value.code == "verdict_not_pass"
    assert "INCONCLUSIVE" in exc.value.detail


def test_issue_unknown_eval_rejected():
    gate, _, _ = build_gate()
    with pytest.raises(CredentialNotIssuableError) as exc:
        gate.issue("EV-unknown")
    assert exc.value.code == "unknown_eval_id"


def test_issue_without_report_rejected():
    gate, repo, _ = build_gate()
    seed_request(repo)
    with pytest.raises(CredentialNotIssuableError) as exc:
        gate.issue(EVAL_ID)
    assert exc.value.code == "no_report"


def test_issue_purpose_mismatch_rejected():
    gate, repo, reporter = build_gate()
    seed_report(repo, reporter, purpose="deploy")
    with pytest.raises(CredentialNotIssuableError) as exc:
        gate.issue(EVAL_ID, purpose="l0_settle")
    assert exc.value.code == "purpose_mismatch"


def test_issue_purpose_uses_request_purpose():
    gate, repo, reporter = build_gate()
    seed_report(repo, reporter, purpose="l0_settle")
    credential = gate.issue(EVAL_ID)
    assert credential.purpose == "l0_settle"


def test_issue_after_expiry_rejected():
    gate, repo, reporter = build_gate(clock=lambda: NOW + timedelta(days=CREDENTIAL_TTL_DAYS + 1))
    seed_report(repo, reporter)
    with pytest.raises(CredentialNotIssuableError) as exc:
        gate.issue(EVAL_ID)
    assert exc.value.code == "expired"


# ---------- verify ----------


def test_verify_valid_credential():
    gate, repo, reporter = build_gate()
    seed_report(repo, reporter)
    credential = gate.issue(EVAL_ID)

    assert gate.verify(credential) == credential
    assert gate.is_valid(credential) is True


def test_verify_expired_credential():
    clock = VarClock()
    gate, repo, reporter = build_gate(clock=clock)
    seed_report(repo, reporter)
    credential = gate.issue(EVAL_ID)
    clock.now = NOW + timedelta(days=CREDENTIAL_TTL_DAYS + 1)

    with pytest.raises(CredentialInvalidError) as exc:
        gate.verify(credential)
    assert exc.value.code == "expired"
    assert gate.is_valid(credential) is False


def test_verify_expiry_boundary_is_closed():
    clock = VarClock()
    gate, repo, reporter = build_gate(clock=clock)
    seed_report(repo, reporter)
    credential = gate.issue(EVAL_ID)
    clock.now = NOW + timedelta(days=CREDENTIAL_TTL_DAYS)

    with pytest.raises(CredentialInvalidError) as exc:
        gate.verify(credential)
    assert exc.value.code == "expired"


def test_verify_tampered_spec_hash_rejected():
    gate, repo, reporter = build_gate()
    seed_report(repo, reporter)
    credential = gate.issue(EVAL_ID)
    tampered = _replace(credential, spec_hash=sha256_hex("tampered"))

    with pytest.raises(CredentialInvalidError) as exc:
        gate.verify(tampered)
    assert exc.value.code == "binding_mismatch"
    assert "spec_hash" in exc.value.detail


def test_verify_tampered_expires_at_rejected():
    gate, repo, reporter = build_gate()
    seed_report(repo, reporter)
    credential = gate.issue(EVAL_ID)
    tampered = _replace(credential, expires_at=zulu(NOW + timedelta(days=365)))

    with pytest.raises(CredentialInvalidError) as exc:
        gate.verify(tampered)
    assert exc.value.code == "binding_mismatch"
    assert "expires_at" in exc.value.detail


def test_verify_block_report_rejected():
    gate, repo, reporter = build_gate()
    report = seed_report(repo, reporter, status="BLOCK")
    run = repo.latest_run_for_eval(EVAL_ID)
    # 伪造一份「看起来 PASS」的凭证，验证时必须以报告为准
    credential = Credential(
        eval_id=EVAL_ID,
        run_id=report["run_id"],
        spec_hash=report["spec_hash"],
        verdict="PASS",
        purpose="deploy",
        thresholds_version=report["thresholds_version"],
        evaluator_id=run.evaluator_id,
        evaluator_version=run.evaluator_version,
        evidence_sha256=report["evidence"]["sha256"],
        issued_at=zulu(NOW),
        expires_at=report["expires_at"],
    )

    with pytest.raises(CredentialInvalidError) as exc:
        gate.verify(credential)
    assert exc.value.code == "verdict_not_pass"


def test_verify_unknown_eval_rejected():
    gate, repo, reporter = build_gate()
    seed_report(repo, reporter)
    credential = _replace(gate.issue(EVAL_ID), eval_id="EV-unknown")

    with pytest.raises(CredentialInvalidError) as exc:
        gate.verify(credential)
    assert exc.value.code == "unknown_eval_id"


def test_verify_purpose_mismatch_rejected():
    gate, repo, reporter = build_gate()
    seed_report(repo, reporter, purpose="deploy")
    credential = gate.issue(EVAL_ID)

    with pytest.raises(CredentialInvalidError) as exc:
        gate.verify(credential, purpose="l0_settle")
    assert exc.value.code == "purpose_mismatch"


def test_verify_tampered_purpose_rejected():
    gate, repo, reporter = build_gate()
    seed_report(repo, reporter, purpose="deploy")
    tampered = _replace(gate.issue(EVAL_ID), purpose="l0_settle")

    with pytest.raises(CredentialInvalidError) as exc:
        gate.verify(tampered)
    assert exc.value.code == "purpose_mismatch"


def test_credential_to_dict_roundtrip():
    gate, repo, reporter = build_gate()
    seed_report(repo, reporter)
    credential = gate.issue(EVAL_ID)

    payload = credential.to_dict()
    assert payload["eval_id"] == EVAL_ID
    assert payload["verdict"] == "PASS"
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_gate_error_is_base():
    assert issubclass(CredentialNotIssuableError, GateError)
    assert issubclass(CredentialInvalidError, GateError)


def _replace(credential: Credential, **kwargs) -> Credential:
    return replace(credential, **kwargs)
