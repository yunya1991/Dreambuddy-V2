# -*- coding: utf-8 -*-
"""H5：InteractionCase 证据门禁（A/B/C），不改既有采集器与 case store。

对齐 56/SPEC-56-H v0.3 §4.5 与 contracts/interaction_case.schema.json v1.0。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.evidence_gate import (
    EvidenceGateError,
    assert_admissible,
    grade_case,
    is_trainable,
)

SCHEMA = (
    Path(__file__).parent.parent.parent
    / "56-L2架构能力聚合层"
    / "contracts"
    / "interaction_case.schema.json"
)

HASH = "sha256:" + "a" * 64


def _case(**overrides):
    case = {
        "case_id": "case-001",
        "session_id": "sess-001",
        "intent": "修复空候选集",
        "actions": ["reproduce", "fix"],
        "outcome": "regression passed",
        "learned": ["空集需 early-return"],
        "refs": [{"type": "span", "id": "sp-001", "hash": HASH}],
        "author_claim": "observation",
    }
    case.update(overrides)
    return case


def test_observation_with_span_and_confirmation_is_A():
    graded = grade_case(
        _case(human_confirmation={"by": "u1", "at": "2026-11-17T10:00:00+00:00", "ref": "pr#1"})
    )

    assert graded["derived"] == {"level": "observation", "admissibility": "A"}
    assert is_trainable(graded) is True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator

    payload = {k: v for k, v in graded.items() if k not in ("poe", "_gate_reason")}
    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert not errors, [e.message for e in errors]


def test_observation_with_checkpoint_and_reproduction_is_A():
    graded = grade_case(
        _case(
            refs=[{"type": "checkpoint", "id": "ckpt-001", "hash": HASH}],
            reproduction={"cmd": "pytest -q", "artifact_hash": HASH},
        )
    )
    assert graded["derived"]["admissibility"] == "A"


def test_file_only_caps_at_B():
    graded = grade_case(
        _case(
            refs=[{"type": "file", "id": "core/x.py", "hash": HASH}],
            human_confirmation={"by": "u1", "at": "2026-11-17T10:00:00+00:00", "ref": "pr#1"},
        )
    )
    assert graded["derived"] == {"level": "observation", "admissibility": "B"}


def test_inference_with_confirmation_is_B():
    graded = grade_case(
        _case(
            author_claim="inference",
            reproduction={"cmd": "pytest -q", "artifact_hash": HASH},
        )
    )
    assert graded["derived"] == {"level": "inference", "admissibility": "B"}


def test_inference_without_confirmation_is_C():
    graded = grade_case(_case(author_claim="inference"))
    assert graded["derived"] == {"level": "inference", "admissibility": "C"}
    assert is_trainable(graded) is False


def test_author_supplied_derived_is_rejected():
    with pytest.raises(EvidenceGateError):
        grade_case(_case(derived={"level": "observation", "admissibility": "A"}))


def test_no_verified_refs_rejected():
    with pytest.raises(EvidenceGateError):
        grade_case(_case(refs=[]))
    with pytest.raises(EvidenceGateError):
        grade_case(_case(refs=[{"type": "span", "id": ""}]))


def test_injected_verifier_filters_unverified_refs():
    # ref 全被过滤 → 拒绝
    with pytest.raises(EvidenceGateError):
        grade_case(
            _case(refs=[{"type": "span", "id": "sp-001", "hash": HASH}]),
            verify_ref=lambda ref: False,
        )


def test_poe_audit_is_reused_not_reimplemented():
    graded = grade_case(
        _case(human_confirmation={"by": "u1", "at": "2026-11-17T10:00:00+00:00", "ref": "pr#1"}),
        poe_audit=lambda case: {"gate_decision": "pass", "poe_score": 0.9},
    )
    assert graded["poe"]["gate_decision"] == "pass"


def test_admissibility_guards():
    a_case = grade_case(
        _case(human_confirmation={"by": "u1", "at": "2026-11-17T10:00:00+00:00", "ref": "pr#1"})
    )
    c_case = grade_case(_case(author_claim="inference"))

    assert_admissible(a_case, purpose="train")
    with pytest.raises(EvidenceGateError):
        assert_admissible(c_case, purpose="train")
    with pytest.raises(EvidenceGateError):
        assert_admissible(c_case, purpose="settled")
    assert_admissible(c_case, purpose="retrieve")
