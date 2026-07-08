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


def test_policy_regression_matrix_runner_reports_all_cases(tmp_path):
    mod = _load_module("scripts/ci/evolution_policy_regression_matrix.py")
    candidate = {
        "candidate_id": "cand-matrix-001",
        "trace_id": "trace-matrix-001",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/feedback/evidence_pack_matrix.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    candidate_path = tmp_path / "candidate.json"
    _write_json(candidate_path, candidate)

    reports_approve = []
    for i, stage in enumerate(["audit", "sandbox", "stress", "scenario", "backtest"]):
        path = tmp_path / f"approve-{stage}.json"
        _write_json(path, {"candidate_id": "cand-matrix-001", "stage": stage, "pass": True, "violations": []})
        reports_approve.append(path)

    reports_reject = []
    for i, stage in enumerate(["audit", "sandbox", "stress", "scenario"]):
        path = tmp_path / f"reject-{stage}.json"
        _write_json(path, {"candidate_id": "cand-matrix-001", "stage": stage, "pass": True, "violations": []})
        reports_reject.append(path)
    backtest_reject = tmp_path / "reject-backtest.json"
    _write_json(
        backtest_reject,
        {
            "candidate_id": "cand-matrix-001",
            "stage": "backtest",
            "pass": True,
            "violations": [{"code": "TAIL_RISK", "severity": "high"}],
        },
    )
    reports_reject.append(backtest_reject)

    policy_path = tmp_path / "policy.json"
    _write_json(
        policy_path,
        {
            "policy_version": "p1.default.v1",
            "stage_policy": {},
        },
    )

    matrix_path = tmp_path / "matrix.json"
    _write_json(
        matrix_path,
        {
            "matrix_version": "p1.5-regression-v1",
            "cases": [
                {
                    "case_id": "approve_all_green",
                    "expected_decision": "approve",
                    "candidate_path": str(candidate_path),
                    "report_paths": [str(p) for p in reports_approve],
                    "policy_version": "p1.default.v1",
                    "policy_path": str(policy_path),
                },
                {
                    "case_id": "reject_high_severity",
                    "expected_decision": "reject",
                    "candidate_path": str(candidate_path),
                    "report_paths": [str(p) for p in reports_reject],
                    "policy_version": "p1.default.v1",
                    "policy_path": str(policy_path),
                },
            ],
        },
    )

    output_path = tmp_path / "summary.json"
    rc = mod.main(
        [
            "--matrix-json",
            str(matrix_path),
            "--output-json",
            str(output_path),
        ]
    )
    assert rc == 0
    summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert summary["total_cases"] == 2
    assert summary["passed_cases"] == 2
