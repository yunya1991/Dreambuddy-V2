# -*- coding: utf-8 -*-
"""P3-2/P3-3/P3-4 门禁执行器测试（凭证卡点 + 双凭证 + 影子观测）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from core.enforcement import EnforcementError, Enforcer
from core.gate import Gate
from core.gateway import EvalRequestRecord
from core.registry import ThresholdRegistry
from core.reporter import Reporter
from storage.audit import AuditLog
from storage.repo import (
    CREDENTIAL_TTL_DAYS,
    EvalItemRecord,
    EvalRunRecord,
    InMemoryRepo,
    sha256_hex,
    zulu,
)

NOW = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
SPEC_HASH = sha256_hex("spec-p3-enforce")
EVAL_ID = "EV-20261101-0001"


class VarClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def seed(tmp_path, status: str = "PASS", purpose: str = "deploy"):
    repo = InMemoryRepo()
    reporter = Reporter(repo=repo, thresholds=ThresholdRegistry.load(), clock=lambda: NOW)
    repo.insert_request(
        EvalRequestRecord(
            eval_id=EVAL_ID,
            idempotency_key="idem-p3",
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
    reporter.finalize(EVAL_ID, run, [_item(run.run_id, status)])
    audit = AuditLog(path=tmp_path / "enforcement.jsonl", clock=lambda: NOW)
    clock = VarClock()
    gate = Gate(repo=repo, clock=clock)
    return repo, gate, audit, clock


def _item(run_id: str, status: str) -> EvalItemRecord:
    return EvalItemRecord(
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


def build(tmp_path, *, shadow: bool, status: str = "PASS", purpose: str = "deploy", approvals=None):
    repo, gate, audit, clock = seed(tmp_path, status=status, purpose=purpose)
    enforcer = Enforcer(gate=gate, audit=audit, shadow=shadow, approvals=approvals, clock=clock)
    return repo, gate, enforcer, audit, clock


def test_shadow_pass_allows_and_exits_zero(tmp_path):
    _, _, enforcer, audit, _ = build(tmp_path, shadow=True)
    decision = enforcer.enforce("deploy", EVAL_ID)

    assert decision.decision == "PASS"
    assert decision.allowed is True
    assert decision.exit_code == 0
    assert audit.query(eval_id=EVAL_ID)[0]["decision"] == "PASS"


def test_shadow_block_is_observe_only(tmp_path):
    _, _, enforcer, audit, _ = build(tmp_path, shadow=True, status="BLOCK")
    decision = enforcer.enforce("deploy", EVAL_ID)

    assert decision.decision == "SHADOW_WOULD_BLOCK"
    assert decision.allowed is True
    assert decision.exit_code == 0
    assert any("verdict_not_pass" in r for r in decision.reasons)
    assert audit.query(eval_id=EVAL_ID)[0]["mode"] == "shadow"


def test_live_block_rejects(tmp_path):
    _, _, enforcer, _, _ = build(tmp_path, shadow=False, status="BLOCK")
    decision = enforcer.enforce("deploy", EVAL_ID)

    assert decision.decision == "BLOCK"
    assert decision.allowed is False
    assert decision.exit_code == 2


def test_live_pass_allows(tmp_path):
    _, _, enforcer, _, _ = build(tmp_path, shadow=False)
    decision = enforcer.enforce("deploy", EVAL_ID)

    assert decision.decision == "PASS"
    assert decision.allowed is True
    assert decision.exit_code == 0
    assert decision.credential is not None
    assert decision.credential.eval_id == EVAL_ID


def test_live_unknown_eval_rejects(tmp_path):
    _, _, enforcer, _, _ = build(tmp_path, shadow=False)
    decision = enforcer.enforce("deploy", "EV-unknown")

    assert decision.decision == "BLOCK"
    assert any("unknown_eval_id" in r for r in decision.reasons)


def test_live_expired_credential_rejects(tmp_path):
    _, _, enforcer, _, clock = build(tmp_path, shadow=False)
    clock.now = NOW + timedelta(days=CREDENTIAL_TTL_DAYS + 1)
    decision = enforcer.enforce("deploy", EVAL_ID)

    assert decision.decision == "BLOCK"
    assert any("expired" in r for r in decision.reasons)


def test_live_purpose_mismatch_rejects(tmp_path):
    _, _, enforcer, _, _ = build(tmp_path, shadow=False, purpose="deploy")
    decision = enforcer.enforce("l0_settle", EVAL_ID)

    assert decision.decision == "BLOCK"
    assert any("purpose_mismatch" in r for r in decision.reasons)


def test_live_presented_credential_is_verified(tmp_path):
    _, gate, enforcer, _, clock = build(tmp_path, shadow=False)
    credential = gate.issue(EVAL_ID)
    clock.now = NOW + timedelta(days=CREDENTIAL_TTL_DAYS + 1)
    decision = enforcer.enforce("deploy", EVAL_ID, credential=credential)

    assert decision.decision == "BLOCK"
    assert any("expired" in r for r in decision.reasons)


def test_dual_credential_missing_approval_rejects(tmp_path):
    _, _, enforcer, _, _ = build(tmp_path, shadow=False)
    decision = enforcer.enforce("deploy", EVAL_ID, require_approval=True)

    assert decision.decision == "BLOCK"
    assert any("approval_missing" in r for r in decision.reasons)


def test_dual_credential_invalid_approval_rejects(tmp_path):
    _, _, enforcer, _, _ = build(tmp_path, shadow=False, approvals=lambda _aid: False)
    decision = enforcer.enforce("deploy", EVAL_ID, approval_id="AP-1", require_approval=True)

    assert decision.decision == "BLOCK"
    assert any("approval_invalid" in r for r in decision.reasons)


def test_dual_credential_both_ok_passes(tmp_path):
    _, _, enforcer, _, _ = build(tmp_path, shadow=False, approvals=lambda aid: aid == "AP-1")
    decision = enforcer.enforce("deploy", EVAL_ID, approval_id="AP-1", require_approval=True)

    assert decision.decision == "PASS"
    assert decision.approval_id == "AP-1"


def test_dual_credential_shadow_observes(tmp_path):
    _, _, enforcer, _, _ = build(tmp_path, shadow=True, approvals=lambda _aid: False)
    decision = enforcer.enforce("deploy", EVAL_ID, approval_id="AP-1", require_approval=True)

    assert decision.decision == "SHADOW_WOULD_BLOCK"
    assert decision.allowed is True


def test_unknown_kind_rejected(tmp_path):
    _, _, enforcer, _, _ = build(tmp_path, shadow=False)
    with pytest.raises(EnforcementError) as exc:
        enforcer.enforce("deploy_all", EVAL_ID)
    assert exc.value.code == "unknown_kind"


def test_decision_to_dict_is_json_serializable(tmp_path):
    _, _, enforcer, _, _ = build(tmp_path, shadow=True)
    decision = enforcer.enforce("deploy", EVAL_ID)

    payload = decision.to_dict()
    assert payload["kind"] == "deploy"
    assert payload["eval_id"] == EVAL_ID
    assert payload["mode"] == "shadow"
    assert payload["decision"] == "PASS"
    assert json.loads(json.dumps(payload, ensure_ascii=False, default=str))["at"] == zulu(NOW)
