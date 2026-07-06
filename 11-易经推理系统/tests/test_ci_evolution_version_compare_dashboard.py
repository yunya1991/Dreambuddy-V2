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


def test_version_dashboard_aggregates_decisions_promotions_and_rollbacks(tmp_path):
    mod = _load_module("scripts/ci/evolution_version_compare_dashboard.py")
    decision_dir = tmp_path / "decision"
    rollback_dir = tmp_path / "rollback"
    output_path = tmp_path / "dashboard.json"

    _write_json(
        decision_dir / "decision-1.json",
        {"candidate_id": "cand-1", "decision": "approve", "reason_codes": [], "timestamp": "2026-05-12T10:00:00Z"},
    )
    _write_json(
        decision_dir / "decision-2.json",
        {"candidate_id": "cand-2", "decision": "reject", "reason_codes": ["APPROVAL_TICKET_REQUIRED"], "timestamp": "2026-05-12T10:05:00Z"},
    )
    _write_json(
        decision_dir / "promotion-1.json",
        {"candidate_id": "cand-1", "from_version": "v0.1", "to_version": "v0.1.2", "timestamp": "2026-05-12T10:01:00Z"},
    )
    _write_json(
        rollback_dir / "rollback-pointer-1.json",
        {"pointer_id": "rp-1", "from_version": "v0.1", "to_version": "v0.1.2", "created_at": "2026-05-12T10:02:00Z"},
    )

    rc = mod.main(
        [
            "--decision-dir",
            str(decision_dir),
            "--rollback-dir",
            str(rollback_dir),
            "--output-json",
            str(output_path),
        ]
    )
    assert rc == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["summary"]["total_decisions"] == 2
    assert payload["summary"]["approved"] == 1
    assert payload["summary"]["rejected"] == 1
    assert payload["summary"]["rollback_pointer_count"] == 1
    assert payload["summary"]["promotion_count"] == 1
    assert payload["summary"]["approval_reject_count"] == 1
