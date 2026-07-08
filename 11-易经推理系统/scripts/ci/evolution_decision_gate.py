#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


REQUIRED_CANDIDATE_FIELDS = [
    "candidate_id",
    "trace_id",
    "constraint_version_base",
    "evidence_refs",
    "schema_version",
]

DEFAULT_REQUIRED_STAGES = ["audit", "sandbox", "stress", "scenario", "backtest"]
DEFAULT_STAGE_POLICY = {
    "require_pass": True,
    "allow_warnings": False,
    "max_violation_count": 0,
    "severity_blocklist": ["high", "critical"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_stage_policy(path: str) -> Dict[str, Dict[str, Any]]:
    if not path:
        return {}
    payload = _load_json(Path(path))
    if not isinstance(payload, dict):
        raise ValueError("stage_policy_json must be a JSON object")
    out: Dict[str, Dict[str, Any]] = {}
    for stage, policy in payload.items():
        if not isinstance(stage, str):
            continue
        if isinstance(policy, dict):
            out[stage] = policy
    return out


def _merged_stage_policy(required_stages: List[str], policy_by_stage: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for stage in required_stages:
        stage_policy = dict(DEFAULT_STAGE_POLICY)
        stage_policy.update(policy_by_stage.get(stage, {}))
        blocklist = stage_policy.get("severity_blocklist", [])
        if not isinstance(blocklist, list):
            blocklist = list(DEFAULT_STAGE_POLICY["severity_blocklist"])
        stage_policy["severity_blocklist"] = [str(item).lower() for item in blocklist if str(item).strip()]
        stage_policy["require_pass"] = bool(stage_policy.get("require_pass", True))
        stage_policy["allow_warnings"] = bool(stage_policy.get("allow_warnings", False))
        stage_policy["max_violation_count"] = int(stage_policy.get("max_violation_count", 0))
        merged[stage] = stage_policy
    return merged


def _collect_violation_severities(violations: Any) -> List[str]:
    if not isinstance(violations, list):
        return []
    severities: List[str] = []
    for item in violations:
        if isinstance(item, dict):
            sev = str(item.get("severity") or "").strip().lower()
            if sev:
                severities.append(sev)
    return severities


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evolution P0 decision gate")
    parser.add_argument("--candidate", required=True, help="Path to Candidate JSON")
    parser.add_argument(
        "--reports",
        required=True,
        help="Comma-separated ValidationReport JSON paths",
    )
    parser.add_argument("--to-version", required=True, help="Target constraint version")
    parser.add_argument("--required-stages", default="audit,sandbox,stress,scenario,backtest")
    parser.add_argument("--stage-policy-json", default="", help="Path to stage policy JSON")
    parser.add_argument("--policy-version", default="", help="Stage policy version identifier")
    parser.add_argument(
        "--policy-library-dir",
        default="artifacts/evolution/policy/templates",
        help="Policy template directory used with --policy-version",
    )
    parser.add_argument("--approval-ticket-json", default="", help="Path to approval ticket JSON")
    parser.add_argument(
        "--require-approval-ticket",
        action="store_true",
        help="Require approval ticket to promote",
    )
    parser.add_argument("--approval-artifacts-dir", default="artifacts/evolution/approval")
    parser.add_argument("--artifacts-dir", default="artifacts/evolution/decision")
    parser.add_argument("--rollback-dir", default="artifacts/evolution/rollback")
    parser.add_argument("--timestamp", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def resolve_stage_policy(
    *,
    stage_policy_json: str,
    policy_version: str,
    policy_library_dir: str,
) -> Dict[str, Any]:
    source = ""
    payload: Dict[str, Any] = {}
    requested_version = str(policy_version or "").strip()
    if stage_policy_json:
        source = str(Path(stage_policy_json))
        payload = _load_json(Path(stage_policy_json))
    elif requested_version:
        source_path = Path(policy_library_dir) / f"{requested_version}.json"
        source = str(source_path)
        payload = _load_json(source_path)

    if payload and not isinstance(payload, dict):
        raise ValueError("stage policy payload must be a JSON object")

    if "stage_policy" in payload and isinstance(payload.get("stage_policy"), dict):
        policy_by_stage = dict(payload.get("stage_policy") or {})
    else:
        policy_by_stage = {k: v for k, v in payload.items() if isinstance(v, dict)}

    file_version = str(payload.get("policy_version") or "").strip()
    if requested_version and file_version and requested_version != file_version:
        raise ValueError(f"policy_version mismatch: requested={requested_version}, file={file_version}")

    resolved_version = requested_version or file_version or "embedded.v0"
    return {
        "policy_version": resolved_version,
        "policy_source": source or "default",
        "policy_by_stage": policy_by_stage,
    }


def validate_candidate(candidate: Dict[str, Any]) -> List[str]:
    reason_codes: List[str] = []
    for key in REQUIRED_CANDIDATE_FIELDS:
        if key not in candidate:
            reason_codes.append("CANDIDATE_INVALID")
            break
    evidence_refs = candidate.get("evidence_refs", [])
    if not isinstance(evidence_refs, list) or len(evidence_refs) == 0:
        reason_codes.append("EVIDENCE_MISSING")
    return reason_codes


def evaluate_decision(
    *,
    candidate: Dict[str, Any],
    reports: List[Dict[str, Any]],
    required_stages: List[str],
    stage_policy: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    reason_codes = validate_candidate(candidate)
    stage_map: Dict[str, Dict[str, Any]] = {}
    stage_results: Dict[str, bool] = {}

    for report in reports:
        stage = str(report.get("stage") or "").strip()
        if stage:
            stage_map[stage] = report

    for stage in required_stages:
        report = stage_map.get(stage)
        policy = stage_policy.get(stage, dict(DEFAULT_STAGE_POLICY))
        if report is None:
            reason_codes.append("REPORT_STAGE_MISSING")
            stage_results[stage] = False
            continue
        pass_flag = bool(report.get("pass"))
        violations = report.get("violations", [])
        violation_count = len(violations) if isinstance(violations, list) else 0
        has_violations = violation_count > 0
        severities = _collect_violation_severities(violations)

        stage_ok = True
        if policy.get("require_pass", True) and not pass_flag:
            reason_codes.append("REPORT_NOT_PASSED")
            stage_ok = False
        if has_violations and violation_count > int(policy.get("max_violation_count", 0)):
            reason_codes.append("REPORT_VIOLATION_COUNT_EXCEEDED")
            stage_ok = False
        blocklist = {str(item).lower() for item in policy.get("severity_blocklist", [])}
        if any(sev in blocklist for sev in severities):
            reason_codes.append("REPORT_SEVERITY_BLOCKED")
            stage_ok = False
        if has_violations and not policy.get("allow_warnings", False):
            reason_codes.append("REPORT_VIOLATION_FOUND")
            stage_ok = False
        stage_results[stage] = stage_ok

    # Keep order stable and deduplicate for deterministic artifacts.
    dedup_codes = list(dict.fromkeys(reason_codes))
    decision = "approve" if len(dedup_codes) == 0 else "reject"
    return {
        "decision": decision,
        "reason_codes": dedup_codes,
        "stage_results": stage_results,
    }


def build_rollback_pointer(
    *,
    candidate: Dict[str, Any],
    from_version: str,
    to_version: str,
    evidence_refs: List[str],
    timestamp: str,
) -> Dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id"))
    pointer_id = f"rp-{candidate_id}-{from_version}-to-{to_version}"
    restore_ref = f"constraints/releases/{from_version}.json"
    return {
        "pointer_id": pointer_id,
        "candidate_id": candidate_id,
        "trace_id": str(candidate.get("trace_id") or ""),
        "from_version": from_version,
        "to_version": to_version,
        "constraint_snapshot_ref": restore_ref,
        "restore_ref": restore_ref,
        "restore_command": (
            "python scripts/ci/constraint_rollback.py "
            f"--restore-ref {restore_ref}"
        ),
        "evidence_refs": evidence_refs,
        "created_at": timestamp,
        "schema_version": "evolution-p0-rollback-pointer-v0.1",
    }


def _parse_iso_utc(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_version_allowed(scope: Any, to_version: str) -> bool:
    if not isinstance(scope, dict):
        return False
    if bool(scope.get("all_versions")):
        return True
    versions = scope.get("to_versions")
    if not isinstance(versions, list):
        return False
    allow_list = {str(item).strip() for item in versions if str(item).strip()}
    return str(to_version).strip() in allow_list


def evaluate_approval_ticket(
    *,
    require_ticket: bool,
    approval_ticket_json: str,
    candidate: Dict[str, Any],
    policy_version: str,
    to_version: str,
    now_ts: str,
) -> Dict[str, Any]:
    source = str(approval_ticket_json or "")
    out: Dict[str, Any] = {
        "required": bool(require_ticket),
        "decision": "skip",
        "reason_codes": [],
        "ticket_id": "",
        "approver": "",
        "approved_at": "",
        "expires_at": "",
        "scope": {},
        "source": source or "none",
    }

    if not approval_ticket_json:
        if require_ticket:
            out["decision"] = "reject"
            out["reason_codes"] = ["APPROVAL_TICKET_REQUIRED"]
        return out

    ticket = _load_json(Path(approval_ticket_json))
    if not isinstance(ticket, dict):
        out["decision"] = "reject"
        out["reason_codes"] = ["APPROVAL_TICKET_INVALID"]
        return out

    out["ticket_id"] = str(ticket.get("ticket_id") or "")
    out["approver"] = str(ticket.get("approver") or "")
    out["approved_at"] = str(ticket.get("approved_at") or "")
    out["expires_at"] = str(ticket.get("expires_at") or "")
    out["scope"] = ticket.get("scope", {})

    reason_codes: List[str] = []
    if str(ticket.get("candidate_id") or "") != str(candidate.get("candidate_id") or ""):
        reason_codes.append("APPROVAL_CANDIDATE_MISMATCH")
    if str(ticket.get("trace_id") or "") != str(candidate.get("trace_id") or ""):
        reason_codes.append("APPROVAL_TRACE_MISMATCH")
    if str(ticket.get("policy_version") or "").strip() != str(policy_version or "").strip():
        reason_codes.append("APPROVAL_POLICY_VERSION_MISMATCH")
    if not _to_version_allowed(ticket.get("scope", {}), str(to_version)):
        reason_codes.append("APPROVAL_SCOPE_MISMATCH")

    now_dt = _parse_iso_utc(now_ts)
    approved_dt = _parse_iso_utc(str(ticket.get("approved_at") or ""))
    expires_dt = _parse_iso_utc(str(ticket.get("expires_at") or ""))
    if now_dt is None or approved_dt is None or expires_dt is None:
        reason_codes.append("APPROVAL_TICKET_INVALID")
    else:
        if now_dt < approved_dt:
            reason_codes.append("APPROVAL_NOT_YET_EFFECTIVE")
        if now_dt > expires_dt:
            reason_codes.append("APPROVAL_EXPIRED")

    dedup = list(dict.fromkeys(reason_codes))
    out["reason_codes"] = dedup
    out["decision"] = "approve" if not dedup else "reject"
    return out


def _run(args: argparse.Namespace) -> int:
    timestamp = args.timestamp or _now_iso()
    ts_name = timestamp.replace("-", "").replace(":", "").replace("Z", "Z").replace(".", "")

    candidate_path = Path(args.candidate)
    report_paths = [Path(item.strip()) for item in str(args.reports).split(",") if item.strip()]
    required_stages = [item.strip() for item in str(args.required_stages).split(",") if item.strip()]
    if not required_stages:
        required_stages = list(DEFAULT_REQUIRED_STAGES)
    policy_meta = resolve_stage_policy(
        stage_policy_json=str(args.stage_policy_json),
        policy_version=str(args.policy_version),
        policy_library_dir=str(args.policy_library_dir),
    )
    stage_policy = _merged_stage_policy(required_stages, policy_meta["policy_by_stage"])

    candidate = _load_json(candidate_path)
    reports = [_load_json(path) for path in report_paths]
    gate_result = evaluate_decision(
        candidate=candidate,
        reports=reports,
        required_stages=required_stages,
        stage_policy=stage_policy,
    )
    approval_result: Dict[str, Any] = {
        "required": bool(args.require_approval_ticket),
        "decision": "skip",
        "reason_codes": [],
        "ticket_id": "",
        "approver": "",
        "approved_at": "",
        "expires_at": "",
        "scope": {},
        "source": "none",
    }
    if gate_result["decision"] == "approve":
        approval_result = evaluate_approval_ticket(
            require_ticket=bool(args.require_approval_ticket),
            approval_ticket_json=str(args.approval_ticket_json),
            candidate=candidate,
            policy_version=policy_meta["policy_version"],
            to_version=str(args.to_version),
            now_ts=timestamp,
        )
        if bool(args.require_approval_ticket) and approval_result["decision"] == "reject":
            gate_result["reason_codes"] = list(dict.fromkeys(gate_result["reason_codes"] + approval_result["reason_codes"]))
            gate_result["decision"] = "reject"

    decision_record: Dict[str, Any] = {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "trace_id": str(candidate.get("trace_id") or ""),
        "decision": gate_result["decision"],
        "reason_codes": gate_result["reason_codes"],
        "policy_version": policy_meta["policy_version"],
        "policy_source": policy_meta["policy_source"],
        "required_stages": required_stages,
        "stage_policy_snapshot": stage_policy,
        "stage_results": gate_result["stage_results"],
        "approval": approval_result,
        "rollback_pointer_id": "",
        "timestamp": timestamp,
        "schema_version": "evolution-p0-decision-record-v0.1",
    }

    promotion_record: Optional[Dict[str, Any]] = None
    rollback_pointer: Optional[Dict[str, Any]] = None

    if gate_result["decision"] == "approve":
        from_version = str(candidate.get("constraint_version_base") or "")
        evidence_refs = [str(item) for item in candidate.get("evidence_refs", []) if str(item).strip()]
        rollback_pointer = build_rollback_pointer(
            candidate=candidate,
            from_version=from_version,
            to_version=str(args.to_version),
            evidence_refs=evidence_refs,
            timestamp=timestamp,
        )
        decision_record["rollback_pointer_id"] = rollback_pointer["pointer_id"]
        promotion_record = {
            "candidate_id": str(candidate.get("candidate_id") or ""),
            "from_version": from_version,
            "to_version": str(args.to_version),
            "decision": "approve",
            "rollback_pointer": f"{args.rollback_dir}/rollback-pointer-{ts_name}.json",
            "evidence_refs": evidence_refs,
            "timestamp": timestamp,
        }

    if not args.dry_run:
        decision_out = Path(args.artifacts_dir) / f"decision-{ts_name}.json"
        _write_json(decision_out, decision_record)
        if rollback_pointer is not None:
            rollback_out = Path(args.rollback_dir) / f"rollback-pointer-{ts_name}.json"
            _write_json(rollback_out, rollback_pointer)
        if promotion_record is not None:
            promotion_out = Path(args.artifacts_dir) / f"promotion-{ts_name}.json"
            _write_json(promotion_out, promotion_record)
        if bool(args.require_approval_ticket) or str(args.approval_ticket_json).strip():
            approval_out = Path(args.approval_artifacts_dir) / f"approval-result-{ts_name}.json"
            _write_json(approval_out, approval_result)

    print(json.dumps(decision_record, ensure_ascii=False))
    return 0 if gate_result["decision"] == "approve" else 1


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
