# -*- coding: utf-8 -*-
"""L2Envelope 契约测试（SPEC-56 §4.3 IF-3 / GAP-01）。

判定口径：
  - 结构冻结：ok / result / meta / trace / quality 五段齐全；
  - 计量同源：tokens_used 与 budget_remaining 只能来自同一个预算快照；
  - model=none ⇒ tokens_used=0；
  - 失败必须 ok=false + error_code，不得用 HTTP 200 掩盖；
  - 缺 trace 一律 fail-closed（构造即抛 EnvelopeError）。
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.l2_envelope import (  # noqa: E402
    BudgetSnapshot,
    EnvelopeError,
    build_envelope,
    build_envelope_parts,
    validate_envelope,
    validate_envelope_parts,
)


def _budget(tokens=0, remaining=1000, source="dreamos.global_budget"):
    return BudgetSnapshot(source=source, tokens_used=tokens, budget_remaining=remaining)


def _build(**overrides):
    kwargs = {
        "result": {"answer": "ok"},
        "capability_id": "l2.dreamos",
        "run_id": "run-20261119-001",
        "model": "qwen-max",
        "budget": _budget(),
        "route": "L2_HANDOFF",
        "reasons": ["semantic_intent_match"],
        "sagc": {"S": "done", "A": "done", "C": "done", "G": "skipped"},
        "nodes": [],
        "latency_ms": 12,
        "quality": {"evidence": "partial"},
    }
    kwargs.update(overrides)
    return build_envelope(**kwargs)


def test_build_returns_frozen_shape():
    env = _build()
    assert env["ok"] is True
    assert set(env) == {"ok", "result", "meta", "trace", "quality"}
    assert env["meta"]["layer"] == "L2"
    assert env["meta"]["capability_id"] == "l2.dreamos"
    assert env["meta"]["run_id"] == "run-20261119-001"
    assert env["meta"]["model"] == "qwen-max"
    assert env["trace"]["route"] == "L2_HANDOFF"
    assert env["trace"]["sagc"]["G"] == "skipped"
    assert env["quality"]["evidence"] == "partial"
    assert env["quality"]["caveat"]
    assert validate_envelope(env) == []


def test_budget_fields_come_from_single_snapshot():
    env = _build(budget=_budget(tokens=321, remaining=679))
    assert env["meta"]["tokens_used"] == 321
    assert env["meta"]["budget_remaining"] == 679


def test_budget_must_declare_source():
    with pytest.raises(EnvelopeError):
        _build(budget=_budget(source=""))


def test_negative_tokens_rejected():
    with pytest.raises(EnvelopeError):
        _build(budget=_budget(tokens=-1))


def test_no_model_requires_zero_tokens():
    with pytest.raises(EnvelopeError):
        _build(model="none", budget=_budget(tokens=10))
    env = _build(model="none", budget=_budget(tokens=0))
    assert env["meta"]["tokens_used"] == 0


def test_missing_trace_route_fails_closed():
    with pytest.raises(EnvelopeError):
        _build(route="")
    with pytest.raises(EnvelopeError):
        _build(route="SOMEWHERE")


def test_invalid_sagc_stage_fails_closed():
    with pytest.raises(EnvelopeError):
        _build(sagc={"S": "done", "A": "done", "C": "done"})


def test_error_path_requires_error_code():
    env = _build(error_code="budget_exhausted", degraded=True)
    assert env["ok"] is False
    assert env["error_code"] == "budget_exhausted"
    assert validate_envelope(env) == []

    broken = _build()
    broken["ok"] = False
    assert any("error_code" in err for err in validate_envelope(broken))


def test_ok_true_must_not_carry_error_code():
    env = _build()
    env["error_code"] = "timeout"
    assert any("error_code" in err for err in validate_envelope(env))


def test_degraded_keeps_ok_true():
    env = _build(degraded=True)
    assert env["ok"] is True
    assert env["meta"]["degraded"] is True


def test_quality_evidence_enum():
    with pytest.raises(EnvelopeError):
        _build(quality={"evidence": "guess"})


def test_validator_catches_tampered_meta():
    env = _build()
    env["meta"]["tokens_used"] = 5
    env["meta"]["model"] = "none"
    errors = validate_envelope(env)
    assert any("tokens_used" in err for err in errors)


def test_parts_mode_is_additive():
    parts = build_envelope_parts(
        capability_id="l2.dreamos",
        run_id="run-20261119-002",
        model="none",
        budget=_budget(),
        route="L1_DIRECT",
        quality={"evidence": "full"},
    )
    assert set(parts) == {"meta", "trace", "quality"}
    assert parts["meta"]["tokens_used"] == 0
    assert validate_envelope_parts(parts) == []


def test_parts_mode_keeps_same_constraints():
    with pytest.raises(EnvelopeError):
        build_envelope_parts(
            capability_id="l2.dreamos",
            run_id="run-20261119-003",
            model="none",
            budget=_budget(tokens=3),
            route="L1_DIRECT",
        )
