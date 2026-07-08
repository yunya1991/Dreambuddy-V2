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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_governance_report_summarizes_decisions_and_rollback_execs(tmp_path):
    mod = _load_module("scripts/ci/evolution_governance_report.py")
    decisions_dir = tmp_path / "decisions"
    rollback_exec_dir = tmp_path / "rollback_exec"
    output_path = tmp_path / "weekly.json"

    _write_json(
        decisions_dir / "decision-1.json",
        {
            "decision": "approve",
            "reason_codes": [],
            "timestamp": "2026-05-12T10:00:00Z",
        },
    )
    _write_json(
        decisions_dir / "decision-2.json",
        {
            "decision": "reject",
            "reason_codes": ["APPROVAL_TICKET_REQUIRED"],
            "timestamp": "2026-05-12T10:05:00Z",
        },
    )
    _write_json(
        rollback_exec_dir / "exec-1.json",
        {
            "status": "applied",
            "rto_seconds": 12,
            "timestamp": "2026-05-12T10:10:00Z",
        },
    )

    rc = mod.main(
        [
            "--decision-glob",
            str(decisions_dir / "*.json"),
            "--rollback-exec-glob",
            str(rollback_exec_dir / "*.json"),
            "--period",
            "week",
            "--output-json",
            str(output_path),
            "--now-iso",
            "2026-05-12T12:00:00Z",
        ]
    )
    assert rc == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["summary"]["total_decisions"] == 2
    assert payload["summary"]["approve_count"] == 1
    assert payload["summary"]["reject_count"] == 1
    assert payload["summary"]["rollback_execution_count"] == 1
    assert payload["summary"]["avg_rto_seconds"] == 12
