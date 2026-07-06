#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute evolution candidate priority score")
    parser.add_argument("--candidate-json", required=True)
    parser.add_argument("--decision-json", required=True)
    parser.add_argument("--reports-json", default="")
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def _priority_tier(score: int) -> str:
    if score >= 80:
        return "P0"
    if score >= 60:
        return "P1"
    if score >= 40:
        return "P2"
    return "P3"


def _count_violations(reports_payload: Dict[str, Any]) -> int:
    reports = reports_payload.get("reports", [])
    if not isinstance(reports, list):
        return 0
    total = 0
    for item in reports:
        if not isinstance(item, dict):
            continue
        violations = item.get("violations", [])
        if isinstance(violations, list):
            total += len(violations)
    return total


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    candidate = _load_json(Path(args.candidate_json))
    decision = _load_json(Path(args.decision_json))
    reports_payload = _load_json(Path(args.reports_json)) if str(args.reports_json).strip() else {"reports": []}

    score = 50
    breakdown: Dict[str, int] = {"base": 50}

    decision_value = str(decision.get("decision") or "").strip().lower()
    if decision_value == "approve":
        breakdown["decision"] = 15
    else:
        breakdown["decision"] = -20
    score += breakdown["decision"]

    stage_results = decision.get("stage_results", {})
    stage_bonus = 0
    if isinstance(stage_results, dict):
        for val in stage_results.values():
            stage_bonus += 8 if bool(val) else -12
    breakdown["stages"] = stage_bonus
    score += stage_bonus

    approval = decision.get("approval", {})
    approval_decision = str(approval.get("decision") or "").strip().lower() if isinstance(approval, dict) else ""
    if approval_decision == "approve":
        breakdown["approval"] = 10
    elif approval_decision == "reject":
        breakdown["approval"] = -10
    else:
        breakdown["approval"] = 0
    score += breakdown["approval"]

    risk_level = str(candidate.get("risk_assessment", {}).get("risk_level") or "").strip().lower()
    risk_map = {"low": 10, "medium": 0, "high": -10}
    breakdown["risk"] = int(risk_map.get(risk_level, 0))
    score += breakdown["risk"]

    violations = _count_violations(reports_payload)
    penalty = min(20, violations * 3)
    breakdown["violations"] = -penalty
    score -= penalty

    score = max(0, min(100, int(score)))
    payload = {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "trace_id": str(candidate.get("trace_id") or ""),
        "priority_score": score,
        "priority_tier": _priority_tier(score),
        "breakdown": breakdown,
        "schema_version": "evolution-p2-priority-score-v0.1",
    }
    _write_json(Path(args.output_json), payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
