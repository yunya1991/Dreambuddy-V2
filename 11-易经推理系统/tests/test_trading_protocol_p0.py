import importlib.util
from pathlib import Path


REPO_ROOT = Path("/Users/zhangjiangtao/WorkBuddy/dream-multiskill-v2")


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_build_envelope_contains_required_header_fields():
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    envelope = mod.build_envelope(
        source="A1",
        target="A2",
        message_type="REQUEST",
        priority="HIGH",
        loop_type="execution",
        trace_id="trace-p0-1",
        payload={"stage_id": "A1"},
        correlation_id="sig-001",
        timeout_ms=30000,
    )

    header = envelope["header"]
    required = {
        "message_id",
        "timestamp",
        "version",
        "source",
        "target",
        "type",
        "priority",
        "correlation_id",
        "trace_id",
        "loop_type",
        "timeout_ms",
    }
    assert required.issubset(header.keys())
    assert header["loop_type"] == "execution"
    assert envelope["payload"]["stage_id"] == "A1"


def test_ensure_contract_fields_sets_defaults():
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    payload = mod.ensure_contract_fields(
        {"stage_id": "A3", "trace_id": "trace-p0-2"},
        producer="workflows/trading-decision/A3_simulation",
    )
    assert payload["constraint_version"]
    assert payload["schema_version"]
    assert isinstance(payload["memory_refs"], list)
    assert isinstance(payload["evidence_refs"], list)
    assert payload["producer"].startswith("workflows/trading-decision/")

