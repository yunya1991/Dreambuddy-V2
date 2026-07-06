import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path("/Users/zhangjiangtao/WorkBuddy/dream-multiskill-v2")


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 1. Invalid loop_type rejected
# ---------------------------------------------------------------------------

def test_invalid_loop_type_raises_value_error():
    """loop_type must be one of: execution, intelligence, governance."""
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    with pytest.raises(ValueError):
        mod.build_envelope(
            source="A1",
            target="A2",
            message_type="REQUEST",
            priority="HIGH",
            loop_type="invalid_loop",
            trace_id="trace-test",
            payload={"stage_id": "A1"},
        )


# ---------------------------------------------------------------------------
# 2. Missing contract fields raise ValueError
# ---------------------------------------------------------------------------

def test_require_contract_fields_raises_on_missing_stage_id():
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    with pytest.raises(ValueError, match="missing required contract fields"):
        mod.require_contract_fields({"trace_id": "t1", "constraint_version": "v0.1"})


def test_require_contract_fields_raises_on_empty_trace_id():
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    with pytest.raises(ValueError, match="missing required contract fields"):
        mod.require_contract_fields({"stage_id": "A1", "trace_id": "", "constraint_version": "v0.1"})


def test_require_contract_fields_raises_on_none_memory_refs():
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    with pytest.raises(ValueError, match="missing required contract fields"):
        mod.require_contract_fields({"stage_id": "A1", "trace_id": "t1", "constraint_version": "v0.1", "memory_refs": None})


# ---------------------------------------------------------------------------
# 3. message_id global uniqueness
# ---------------------------------------------------------------------------

def test_consecutive_calls_produce_unique_message_ids():
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    ids = set()
    for _ in range(20):
        env = mod.build_envelope(
            source="A1",
            target="A2",
            message_type="REQUEST",
            priority="HIGH",
            loop_type="execution",
            trace_id="trace-unique",
            payload={"stage_id": "A1"},
        )
        ids.add(env["header"]["message_id"])
    assert len(ids) == 20


# ---------------------------------------------------------------------------
# 4. timeout_ms type safety
# ---------------------------------------------------------------------------

def test_timeout_ms_float_converted_to_int():
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    env = mod.build_envelope(
        source="A1",
        target="A2",
        message_type="REQUEST",
        priority="HIGH",
        loop_type="execution",
        trace_id="trace-test",
        payload={"stage_id": "A1"},
        timeout_ms=30000.5,
    )
    assert isinstance(env["header"]["timeout_ms"], int)


def test_timeout_ms_default_is_30000():
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    env = mod.build_envelope(
        source="A1",
        target="A2",
        message_type="REQUEST",
        priority="HIGH",
        loop_type="execution",
        trace_id="trace-test",
        payload={"stage_id": "A1"},
    )
    assert env["header"]["timeout_ms"] == 30000


# ---------------------------------------------------------------------------
# 5. A0-A9 entrypoint contract enforcement
# ---------------------------------------------------------------------------

def test_all_entrypoints_produce_valid_contract_fields(tmp_path: Path):
    """Every entrypoint should produce output with all required contract fields."""
    required_contract_fields = {
        "stage_id", "trace_id", "constraint_version",
        "memory_refs", "evidence_refs", "producer", "schema_version",
    }

    entrypoints = [
        ("A0_contradiction/entrypoint.py", "run_a0_contradiction_analysis", {"trace_id": "t", "contradictions": []}, False),
        ("A1_research/entrypoint.py", "run_a1_research", {"trace_id": "t"}, True),
        ("A2_first-principles/entrypoint.py", "run_a2_first_principles", {"trace_id": "t"}, True),
        ("A3_simulation/entrypoint.py", "run_a3_simulation", {"trace_id": "t"}, True),
        ("A4_validation/entrypoint.py", "run_a4_validation", {"trace_id": "t", "max_drawdown_pct": 1.0, "position_ratio": 0.3, "stop_loss_pct": 1.5}, True),
        ("A5_execution/entrypoint.py", "run_a5_execution", {"trace_id": "t", "direction": "LONG"}, True),
        ("A6_intelligence/entrypoint.py", "run_a6_intelligence", {"trace_id": "t", "alerts": [], "signal_shift": 0.0}, True),
        ("A7_audit/entrypoint.py", "run_a7_audit", {"trace_id": "t", "violations": []}, True),
        ("A8_theory-practice/entrypoint.py", "run_a8_theory_practice", {"trace_id": "t"}, True),
        ("A9_exit/entrypoint.py", "run_a9_exit", {"trace_id": "t"}, True),
    ]

    for rel_path, fn_name, payload, has_output_dir in entrypoints:
        mod = _load_module(f"workflows/trading-decision/{rel_path}")
        fn = getattr(mod, fn_name)
        if has_output_dir:
            out = fn(payload, output_dir=tmp_path)
        else:
            out = fn(payload)
        body = out.get("payload", out)
        assert required_contract_fields.issubset(body.keys()), f"{rel_path}: missing {required_contract_fields - body.keys()}"


# ---------------------------------------------------------------------------
# 6. envelope_payload extracts inner payload
# ---------------------------------------------------------------------------

def test_envelope_payload_extracts_inner_dict():
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    envelope = mod.build_envelope(
        source="A1",
        target="A2",
        message_type="REQUEST",
        priority="HIGH",
        loop_type="execution",
        trace_id="trace-test",
        payload={"stage_id": "A1", "data": "hello"},
    )
    result = mod.envelope_payload(envelope)
    assert result["stage_id"] == "A1"
    assert result["data"] == "hello"


def test_envelope_payload_returns_as_is_when_no_payload_key():
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    result = mod.envelope_payload({"stage_id": "A1"})
    assert result["stage_id"] == "A1"
