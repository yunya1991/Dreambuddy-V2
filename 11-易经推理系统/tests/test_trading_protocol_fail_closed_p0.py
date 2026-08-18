import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_protocol_fail_closed_when_required_field_missing():
    mod = _load_module("workflows/trading-decision/protocol/message.py")
    with pytest.raises(ValueError):
        mod.require_contract_fields(
            {
                "stage_id": "A1",
                # trace_id is missing on purpose
                "constraint_version": "v0.1",
                "memory_refs": [],
                "evidence_refs": [],
                "producer": "workflows/trading-decision/A1_research",
                "schema_version": "2.0",
            }
        )


def test_a1_entrypoint_fail_closed_when_trace_id_missing(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/A1_research/entrypoint.py")
    with pytest.raises(ValueError):
        mod.run_a1_research({"signals": ["x"], "confidence": 0.5}, output_dir=tmp_path)
