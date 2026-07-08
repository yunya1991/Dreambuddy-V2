import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_traceability_guard_passes_for_contract_complete_artifact(tmp_path: Path):
    mod = _load_module("scripts/ci/trading_traceability_guard.py")
    payload = {
        "stage_id": "A5",
        "trace_id": "trace-1",
        "constraint_version": "v0.1",
        "memory_refs": ["mem-1"],
        "evidence_refs": ["artifacts/trading/evi.json"],
        "producer": "workflows/trading-decision/A5",
        "schema_version": "2.0",
    }
    (tmp_path / "a5.json").write_text(json.dumps(payload), encoding="utf-8")
    violations = mod.audit_artifacts(tmp_path, min_files=1)
    assert violations == []


def test_traceability_guard_fails_when_required_field_missing(tmp_path: Path):
    mod = _load_module("scripts/ci/trading_traceability_guard.py")
    payload = {
        "stage_id": "A5",
        "trace_id": "trace-2",
        "constraint_version": "v0.1",
        "memory_refs": [],
        "producer": "workflows/trading-decision/A5",
        "schema_version": "2.0",
    }
    (tmp_path / "a5_bad.json").write_text(json.dumps(payload), encoding="utf-8")
    violations = mod.audit_artifacts(tmp_path, min_files=1)
    assert any("evidence_refs" in v for v in violations)
