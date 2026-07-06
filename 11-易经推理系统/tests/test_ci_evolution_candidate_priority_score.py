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


def test_priority_score_outputs_tier_and_breakdown(tmp_path):
    mod = _load_module("scripts/ci/evolution_candidate_priority_score.py")
    candidate_path = tmp_path / "candidate.json"
    decision_path = tmp_path / "decision.json"
    reports_path = tmp_path / "reports.json"
    output_path = tmp_path / "score.json"

    _write_json(
        candidate_path,
        {
            "candidate_id": "cand-001",
            "trace_id": "trace-001",
            "risk_assessment": {"risk_level": "low"},
        },
    )
    _write_json(
        decision_path,
        {
            "decision": "approve",
            "stage_results": {"audit": True, "sandbox": True, "stress": True, "scenario": True, "backtest": True},
            "approval": {"decision": "approve"},
        },
    )
    _write_json(
        reports_path,
        {
            "reports": [
                {"stage": "audit", "violations": []},
                {"stage": "backtest", "violations": []},
            ]
        },
    )

    rc = mod.main(
        [
            "--candidate-json",
            str(candidate_path),
            "--decision-json",
            str(decision_path),
            "--reports-json",
            str(reports_path),
            "--output-json",
            str(output_path),
        ]
    )
    assert rc == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["candidate_id"] == "cand-001"
    assert payload["priority_tier"] in {"P0", "P1", "P2", "P3"}
    assert isinstance(payload["priority_score"], int)
    assert payload["priority_score"] >= 0
    assert "breakdown" in payload


def test_priority_score_penalizes_reject_and_violations(tmp_path):
    mod = _load_module("scripts/ci/evolution_candidate_priority_score.py")
    candidate_path = tmp_path / "candidate.json"
    decision_path = tmp_path / "decision.json"
    reports_path = tmp_path / "reports.json"
    output_path = tmp_path / "score.json"

    _write_json(candidate_path, {"candidate_id": "cand-002", "trace_id": "trace-002", "risk_assessment": {"risk_level": "high"}})
    _write_json(
        decision_path,
        {
            "decision": "reject",
            "stage_results": {"audit": True, "sandbox": True, "stress": False, "scenario": False, "backtest": False},
            "approval": {"decision": "reject"},
        },
    )
    _write_json(
        reports_path,
        {
            "reports": [
                {"stage": "stress", "violations": [{"code": "X"}]},
                {"stage": "scenario", "violations": [{"code": "Y"}]},
                {"stage": "backtest", "violations": [{"code": "Z"}]},
            ]
        },
    )

    rc = mod.main(
        [
            "--candidate-json",
            str(candidate_path),
            "--decision-json",
            str(decision_path),
            "--reports-json",
            str(reports_path),
            "--output-json",
            str(output_path),
        ]
    )
    assert rc == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["priority_tier"] in {"P2", "P3"}
