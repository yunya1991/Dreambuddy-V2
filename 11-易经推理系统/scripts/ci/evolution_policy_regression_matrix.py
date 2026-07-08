#!/usr/bin/env python3
import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_decision_gate_module():
    module_path = Path(__file__).parent / "evolution_decision_gate.py"
    spec = importlib.util.spec_from_file_location("evolution_decision_gate", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run evolution policy regression matrix")
    parser.add_argument("--matrix-json", required=True, help="Regression matrix JSON path")
    parser.add_argument("--output-json", required=True, help="Summary output JSON path")
    return parser.parse_args(argv)


def _run_case(case: Dict[str, Any], index: int, matrix_dir: Path) -> Dict[str, Any]:
    gate = _load_decision_gate_module()
    case_id = str(case.get("case_id") or f"case-{index}")
    timestamp = f"2026-05-12T11:{index:02d}:00Z"
    decision_dir = matrix_dir / "outputs" / case_id / "decision"
    rollback_dir = matrix_dir / "outputs" / case_id / "rollback"
    gate_args: List[str] = [
        "--candidate",
        str(case["candidate_path"]),
        "--reports",
        ",".join(str(item) for item in case.get("report_paths", [])),
        "--required-stages",
        str(case.get("required_stages") or "audit,sandbox,stress,scenario,backtest"),
        "--to-version",
        str(case.get("to_version") or "v0.1.2"),
        "--artifacts-dir",
        str(decision_dir),
        "--rollback-dir",
        str(rollback_dir),
        "--timestamp",
        timestamp,
    ]
    policy_path = str(case.get("policy_path") or "").strip()
    if policy_path:
        gate_args.extend(["--stage-policy-json", policy_path])
    policy_version = str(case.get("policy_version") or "").strip()
    if policy_version:
        gate_args.extend(["--policy-version", policy_version])
    policy_library_dir = str(case.get("policy_library_dir") or "").strip()
    if policy_library_dir:
        gate_args.extend(["--policy-library-dir", policy_library_dir])

    rc = gate.main(gate_args)
    ts_name = timestamp.replace("-", "").replace(":", "").replace("Z", "Z").replace(".", "")
    decision_path = decision_dir / f"decision-{ts_name}.json"
    decision_payload = _load_json(decision_path)
    actual_decision = str(decision_payload.get("decision") or "")
    expected_decision = str(case.get("expected_decision") or "")
    passed = actual_decision == expected_decision and (rc == 0) == (expected_decision == "approve")
    return {
        "case_id": case_id,
        "expected_decision": expected_decision,
        "actual_decision": actual_decision,
        "return_code": rc,
        "decision_path": str(decision_path),
        "passed": passed,
    }


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    matrix_path = Path(args.matrix_json)
    matrix = _load_json(matrix_path)
    cases = matrix.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("matrix cases must be a list")

    results: List[Dict[str, Any]] = []
    for index, item in enumerate(cases):
        if not isinstance(item, dict):
            continue
        results.append(_run_case(item, index, matrix_path.parent))

    passed_cases = sum(1 for item in results if item["passed"])
    summary = {
        "matrix_version": str(matrix.get("matrix_version") or ""),
        "run_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_cases": len(results),
        "passed_cases": passed_cases,
        "failed_cases": len(results) - passed_cases,
        "results": results,
    }
    _write_json(Path(args.output_json), summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if passed_cases == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
