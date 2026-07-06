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


def test_decision_gate_approve_writes_decision_promotion_and_pointer(tmp_path):
    mod = _load_module("scripts/ci/evolution_decision_gate.py")
    candidate = {
        "candidate_id": "cand-001",
        "trace_id": "trace-001",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/audit/audit_001.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    audit = {"candidate_id": "cand-001", "stage": "audit", "pass": True, "violations": []}
    sandbox = {"candidate_id": "cand-001", "stage": "sandbox", "pass": True, "violations": []}

    candidate_path = tmp_path / "candidate.json"
    audit_path = tmp_path / "audit.json"
    sandbox_path = tmp_path / "sandbox.json"
    _write_json(candidate_path, candidate)
    _write_json(audit_path, audit)
    _write_json(sandbox_path, sandbox)

    decision_dir = tmp_path / "decision"
    rollback_dir = tmp_path / "rollback"
    rc = mod.main(
        [
            "--candidate",
            str(candidate_path),
            "--reports",
            f"{audit_path},{sandbox_path}",
            "--required-stages",
            "audit,sandbox",
            "--to-version",
            "v0.1.1",
            "--artifacts-dir",
            str(decision_dir),
            "--rollback-dir",
            str(rollback_dir),
            "--timestamp",
            "2026-05-12T08:00:00Z",
        ]
    )
    assert rc == 0

    decision_file = decision_dir / "decision-20260512T080000Z.json"
    promotion_file = decision_dir / "promotion-20260512T080000Z.json"
    pointer_file = rollback_dir / "rollback-pointer-20260512T080000Z.json"
    assert decision_file.exists()
    assert promotion_file.exists()
    assert pointer_file.exists()

    decision_payload = json.loads(decision_file.read_text(encoding="utf-8"))
    assert decision_payload["decision"] == "approve"
    assert decision_payload["rollback_pointer_id"].startswith("rp-cand-001-")


def test_decision_gate_rejects_when_required_stage_missing(tmp_path):
    mod = _load_module("scripts/ci/evolution_decision_gate.py")
    candidate = {
        "candidate_id": "cand-002",
        "trace_id": "trace-002",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/audit/audit_002.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    audit = {"candidate_id": "cand-002", "stage": "audit", "pass": True, "violations": []}

    candidate_path = tmp_path / "candidate.json"
    audit_path = tmp_path / "audit.json"
    _write_json(candidate_path, candidate)
    _write_json(audit_path, audit)

    decision_dir = tmp_path / "decision"
    rc = mod.main(
        [
            "--candidate",
            str(candidate_path),
            "--reports",
            str(audit_path),
            "--required-stages",
            "audit,sandbox",
            "--to-version",
            "v0.1.1",
            "--artifacts-dir",
            str(decision_dir),
            "--rollback-dir",
            str(tmp_path / "rollback"),
            "--timestamp",
            "2026-05-12T08:01:00Z",
        ]
    )
    assert rc == 1

    decision_file = decision_dir / "decision-20260512T080100Z.json"
    assert decision_file.exists()
    payload = json.loads(decision_file.read_text(encoding="utf-8"))
    assert payload["decision"] == "reject"
    assert "REPORT_STAGE_MISSING" in payload["reason_codes"]
    assert not (decision_dir / "promotion-20260512T080100Z.json").exists()


def test_decision_gate_rejects_when_report_has_violation(tmp_path):
    mod = _load_module("scripts/ci/evolution_decision_gate.py")
    candidate = {
        "candidate_id": "cand-003",
        "trace_id": "trace-003",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/audit/audit_003.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    audit = {"candidate_id": "cand-003", "stage": "audit", "pass": True, "violations": []}
    sandbox = {
        "candidate_id": "cand-003",
        "stage": "sandbox",
        "pass": True,
        "violations": ["regression-detected"],
    }

    candidate_path = tmp_path / "candidate.json"
    audit_path = tmp_path / "audit.json"
    sandbox_path = tmp_path / "sandbox.json"
    _write_json(candidate_path, candidate)
    _write_json(audit_path, audit)
    _write_json(sandbox_path, sandbox)

    rc = mod.main(
        [
            "--candidate",
            str(candidate_path),
            "--reports",
            f"{audit_path},{sandbox_path}",
            "--required-stages",
            "audit,sandbox",
            "--to-version",
            "v0.1.1",
            "--artifacts-dir",
            str(tmp_path / "decision"),
            "--rollback-dir",
            str(tmp_path / "rollback"),
            "--timestamp",
            "2026-05-12T08:02:00Z",
        ]
    )
    assert rc == 1


def test_decision_gate_stage_policy_allows_warnings_for_selected_stage(tmp_path):
    mod = _load_module("scripts/ci/evolution_decision_gate.py")
    candidate = {
        "candidate_id": "cand-004",
        "trace_id": "trace-004",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/feedback/evidence_pack_004.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    audit = {"candidate_id": "cand-004", "stage": "audit", "pass": True, "violations": []}
    sandbox = {"candidate_id": "cand-004", "stage": "sandbox", "pass": True, "violations": []}
    stress = {"candidate_id": "cand-004", "stage": "stress", "pass": True, "violations": []}
    scenario = {
        "candidate_id": "cand-004",
        "stage": "scenario",
        "pass": True,
        "violations": [{"code": "SCENARIO_WARN", "severity": "medium"}],
    }
    backtest = {"candidate_id": "cand-004", "stage": "backtest", "pass": True, "violations": []}
    stage_policy = {
        "scenario": {
            "require_pass": True,
            "allow_warnings": True,
            "max_violation_count": 1,
            "severity_blocklist": ["high", "critical"],
        }
    }

    candidate_path = tmp_path / "candidate.json"
    report_paths = []
    for name, payload in [
        ("audit", audit),
        ("sandbox", sandbox),
        ("stress", stress),
        ("scenario", scenario),
        ("backtest", backtest),
    ]:
        path = tmp_path / f"{name}.json"
        _write_json(path, payload)
        report_paths.append(path)
    policy_path = tmp_path / "stage_policy.json"
    _write_json(candidate_path, candidate)
    _write_json(policy_path, stage_policy)

    rc = mod.main(
        [
            "--candidate",
            str(candidate_path),
            "--reports",
            ",".join(str(path) for path in report_paths),
            "--required-stages",
            "audit,sandbox,stress,scenario,backtest",
            "--stage-policy-json",
            str(policy_path),
            "--to-version",
            "v0.1.2",
            "--artifacts-dir",
            str(tmp_path / "decision"),
            "--rollback-dir",
            str(tmp_path / "rollback"),
            "--timestamp",
            "2026-05-12T10:00:00Z",
        ]
    )
    assert rc == 0


def test_decision_gate_stage_policy_blocks_high_severity(tmp_path):
    mod = _load_module("scripts/ci/evolution_decision_gate.py")
    candidate = {
        "candidate_id": "cand-005",
        "trace_id": "trace-005",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/feedback/evidence_pack_005.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    audit = {"candidate_id": "cand-005", "stage": "audit", "pass": True, "violations": []}
    sandbox = {"candidate_id": "cand-005", "stage": "sandbox", "pass": True, "violations": []}
    stress = {"candidate_id": "cand-005", "stage": "stress", "pass": True, "violations": []}
    scenario = {"candidate_id": "cand-005", "stage": "scenario", "pass": True, "violations": []}
    backtest = {
        "candidate_id": "cand-005",
        "stage": "backtest",
        "pass": True,
        "violations": [{"code": "TAIL_RISK_SPIKE", "severity": "high"}],
    }
    stage_policy = {
        "backtest": {
            "require_pass": True,
            "allow_warnings": False,
            "max_violation_count": 3,
            "severity_blocklist": ["high", "critical"],
        }
    }

    candidate_path = tmp_path / "candidate.json"
    report_paths = []
    for name, payload in [
        ("audit", audit),
        ("sandbox", sandbox),
        ("stress", stress),
        ("scenario", scenario),
        ("backtest", backtest),
    ]:
        path = tmp_path / f"{name}.json"
        _write_json(path, payload)
        report_paths.append(path)
    policy_path = tmp_path / "stage_policy.json"
    _write_json(candidate_path, candidate)
    _write_json(policy_path, stage_policy)

    rc = mod.main(
        [
            "--candidate",
            str(candidate_path),
            "--reports",
            ",".join(str(path) for path in report_paths),
            "--required-stages",
            "audit,sandbox,stress,scenario,backtest",
            "--stage-policy-json",
            str(policy_path),
            "--to-version",
            "v0.1.2",
            "--artifacts-dir",
            str(tmp_path / "decision"),
            "--rollback-dir",
            str(tmp_path / "rollback"),
            "--timestamp",
            "2026-05-12T10:05:00Z",
        ]
    )
    assert rc == 1
    payload = json.loads((tmp_path / "decision" / "decision-20260512T100500Z.json").read_text(encoding="utf-8"))
    assert "REPORT_SEVERITY_BLOCKED" in payload["reason_codes"]


def test_decision_gate_default_required_stages_include_stress_scenario_backtest(tmp_path):
    mod = _load_module("scripts/ci/evolution_decision_gate.py")
    candidate = {
        "candidate_id": "cand-006",
        "trace_id": "trace-006",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/feedback/evidence_pack_006.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    audit = {"candidate_id": "cand-006", "stage": "audit", "pass": True, "violations": []}
    sandbox = {"candidate_id": "cand-006", "stage": "sandbox", "pass": True, "violations": []}
    candidate_path = tmp_path / "candidate.json"
    audit_path = tmp_path / "audit.json"
    sandbox_path = tmp_path / "sandbox.json"
    _write_json(candidate_path, candidate)
    _write_json(audit_path, audit)
    _write_json(sandbox_path, sandbox)

    rc = mod.main(
        [
            "--candidate",
            str(candidate_path),
            "--reports",
            f"{audit_path},{sandbox_path}",
            "--to-version",
            "v0.1.2",
            "--artifacts-dir",
            str(tmp_path / "decision"),
            "--rollback-dir",
            str(tmp_path / "rollback"),
            "--timestamp",
            "2026-05-12T10:10:00Z",
        ]
    )
    assert rc == 1
    payload = json.loads((tmp_path / "decision" / "decision-20260512T101000Z.json").read_text(encoding="utf-8"))
    assert payload["required_stages"] == ["audit", "sandbox", "stress", "scenario", "backtest"]
    assert "REPORT_STAGE_MISSING" in payload["reason_codes"]


def test_decision_gate_uses_policy_version_from_template_library(tmp_path):
    mod = _load_module("scripts/ci/evolution_decision_gate.py")
    candidate = {
        "candidate_id": "cand-007",
        "trace_id": "trace-007",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/feedback/evidence_pack_007.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    reports = [
        {"candidate_id": "cand-007", "stage": "audit", "pass": True, "violations": []},
        {"candidate_id": "cand-007", "stage": "sandbox", "pass": True, "violations": []},
        {"candidate_id": "cand-007", "stage": "stress", "pass": True, "violations": []},
        {"candidate_id": "cand-007", "stage": "scenario", "pass": True, "violations": []},
        {"candidate_id": "cand-007", "stage": "backtest", "pass": True, "violations": []},
    ]
    candidate_path = tmp_path / "candidate.json"
    _write_json(candidate_path, candidate)
    report_paths = []
    for i, payload in enumerate(reports):
        path = tmp_path / f"r{i}.json"
        _write_json(path, payload)
        report_paths.append(path)

    policy_library_dir = tmp_path / "policies"
    _write_json(
        policy_library_dir / "p1.relaxed-scenario.v1.json",
        {
            "policy_version": "p1.relaxed-scenario.v1",
            "stage_policy": {
                "scenario": {
                    "allow_warnings": True,
                    "max_violation_count": 1,
                    "severity_blocklist": ["high", "critical"],
                }
            },
        },
    )

    rc = mod.main(
        [
            "--candidate",
            str(candidate_path),
            "--reports",
            ",".join(str(path) for path in report_paths),
            "--policy-version",
            "p1.relaxed-scenario.v1",
            "--policy-library-dir",
            str(policy_library_dir),
            "--to-version",
            "v0.1.2",
            "--artifacts-dir",
            str(tmp_path / "decision"),
            "--rollback-dir",
            str(tmp_path / "rollback"),
            "--timestamp",
            "2026-05-12T10:20:00Z",
        ]
    )
    assert rc == 0
    payload = json.loads((tmp_path / "decision" / "decision-20260512T102000Z.json").read_text(encoding="utf-8"))
    assert payload["policy_version"] == "p1.relaxed-scenario.v1"
    assert payload["policy_source"].endswith("p1.relaxed-scenario.v1.json")


def test_decision_gate_rejects_when_policy_version_mismatch(tmp_path):
    mod = _load_module("scripts/ci/evolution_decision_gate.py")
    candidate = {
        "candidate_id": "cand-008",
        "trace_id": "trace-008",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/feedback/evidence_pack_008.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    reports = [
        {"candidate_id": "cand-008", "stage": "audit", "pass": True, "violations": []},
        {"candidate_id": "cand-008", "stage": "sandbox", "pass": True, "violations": []},
        {"candidate_id": "cand-008", "stage": "stress", "pass": True, "violations": []},
        {"candidate_id": "cand-008", "stage": "scenario", "pass": True, "violations": []},
        {"candidate_id": "cand-008", "stage": "backtest", "pass": True, "violations": []},
    ]
    candidate_path = tmp_path / "candidate.json"
    _write_json(candidate_path, candidate)
    report_paths = []
    for i, payload in enumerate(reports):
        path = tmp_path / f"r{i}.json"
        _write_json(path, payload)
        report_paths.append(path)

    policy_path = tmp_path / "stage_policy.json"
    _write_json(
        policy_path,
        {
            "policy_version": "p1.default.v1",
            "stage_policy": {},
        },
    )
    try:
        mod.main(
            [
                "--candidate",
                str(candidate_path),
                "--reports",
                ",".join(str(path) for path in report_paths),
                "--stage-policy-json",
                str(policy_path),
                "--policy-version",
                "p1.relaxed-scenario.v1",
                "--to-version",
                "v0.1.2",
                "--artifacts-dir",
                str(tmp_path / "decision"),
                "--rollback-dir",
                str(tmp_path / "rollback"),
                "--timestamp",
                "2026-05-12T10:25:00Z",
            ]
        )
        assert False, "expected ValueError for policy version mismatch"
    except ValueError as exc:
        assert "policy_version mismatch" in str(exc)


def test_decision_gate_rejects_when_approval_required_but_ticket_missing(tmp_path):
    mod = _load_module("scripts/ci/evolution_decision_gate.py")
    candidate = {
        "candidate_id": "cand-009",
        "trace_id": "trace-009",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/feedback/evidence_pack_009.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    reports = [
        {"candidate_id": "cand-009", "stage": "audit", "pass": True, "violations": []},
        {"candidate_id": "cand-009", "stage": "sandbox", "pass": True, "violations": []},
        {"candidate_id": "cand-009", "stage": "stress", "pass": True, "violations": []},
        {"candidate_id": "cand-009", "stage": "scenario", "pass": True, "violations": []},
        {"candidate_id": "cand-009", "stage": "backtest", "pass": True, "violations": []},
    ]
    candidate_path = tmp_path / "candidate.json"
    _write_json(candidate_path, candidate)
    report_paths = []
    for i, payload in enumerate(reports):
        path = tmp_path / f"r{i}.json"
        _write_json(path, payload)
        report_paths.append(path)

    rc = mod.main(
        [
            "--candidate",
            str(candidate_path),
            "--reports",
            ",".join(str(path) for path in report_paths),
            "--to-version",
            "v0.1.2",
            "--require-approval-ticket",
            "--artifacts-dir",
            str(tmp_path / "decision"),
            "--rollback-dir",
            str(tmp_path / "rollback"),
            "--approval-artifacts-dir",
            str(tmp_path / "approval"),
            "--timestamp",
            "2026-05-12T10:30:00Z",
        ]
    )
    assert rc == 1
    payload = json.loads((tmp_path / "decision" / "decision-20260512T103000Z.json").read_text(encoding="utf-8"))
    assert payload["decision"] == "reject"
    assert "APPROVAL_TICKET_REQUIRED" in payload["reason_codes"]
    assert not (tmp_path / "decision" / "promotion-20260512T103000Z.json").exists()


def test_decision_gate_approves_with_valid_approval_ticket(tmp_path):
    mod = _load_module("scripts/ci/evolution_decision_gate.py")
    candidate = {
        "candidate_id": "cand-010",
        "trace_id": "trace-010",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/feedback/evidence_pack_010.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    reports = [
        {"candidate_id": "cand-010", "stage": "audit", "pass": True, "violations": []},
        {"candidate_id": "cand-010", "stage": "sandbox", "pass": True, "violations": []},
        {"candidate_id": "cand-010", "stage": "stress", "pass": True, "violations": []},
        {"candidate_id": "cand-010", "stage": "scenario", "pass": True, "violations": []},
        {"candidate_id": "cand-010", "stage": "backtest", "pass": True, "violations": []},
    ]
    candidate_path = tmp_path / "candidate.json"
    _write_json(candidate_path, candidate)
    report_paths = []
    for i, payload in enumerate(reports):
        path = tmp_path / f"r{i}.json"
        _write_json(path, payload)
        report_paths.append(path)

    ticket_path = tmp_path / "approval_ticket.json"
    _write_json(
        ticket_path,
        {
            "ticket_id": "appr-010",
            "candidate_id": "cand-010",
            "trace_id": "trace-010",
            "policy_version": "embedded.v0",
            "decision_ref": "artifacts/evolution/decision/decision-20260512T103500Z.json",
            "approver": "risk-committee",
            "approved_at": "2026-05-12T00:00:00Z",
            "expires_at": "2027-05-12T00:00:00Z",
            "scope": {"to_versions": ["v0.1.2"]},
            "schema_version": "evolution-p2-approval-ticket-v0.1",
        },
    )

    rc = mod.main(
        [
            "--candidate",
            str(candidate_path),
            "--reports",
            ",".join(str(path) for path in report_paths),
            "--to-version",
            "v0.1.2",
            "--require-approval-ticket",
            "--approval-ticket-json",
            str(ticket_path),
            "--artifacts-dir",
            str(tmp_path / "decision"),
            "--rollback-dir",
            str(tmp_path / "rollback"),
            "--approval-artifacts-dir",
            str(tmp_path / "approval"),
            "--timestamp",
            "2026-05-12T10:35:00Z",
        ]
    )
    assert rc == 0
    payload = json.loads((tmp_path / "decision" / "decision-20260512T103500Z.json").read_text(encoding="utf-8"))
    assert payload["decision"] == "approve"
    assert payload["approval"]["decision"] == "approve"
    approval_payload = json.loads((tmp_path / "approval" / "approval-result-20260512T103500Z.json").read_text(encoding="utf-8"))
    assert approval_payload["ticket_id"] == "appr-010"


def test_decision_gate_allows_promotion_when_approval_not_required(tmp_path):
    mod = _load_module("scripts/ci/evolution_decision_gate.py")
    candidate = {
        "candidate_id": "cand-011",
        "trace_id": "trace-011",
        "constraint_version_base": "v0.1",
        "evidence_refs": ["artifacts/evolution/feedback/evidence_pack_011.json"],
        "schema_version": "evolution-p0-candidate-v0.1",
    }
    reports = [
        {"candidate_id": "cand-011", "stage": "audit", "pass": True, "violations": []},
        {"candidate_id": "cand-011", "stage": "sandbox", "pass": True, "violations": []},
        {"candidate_id": "cand-011", "stage": "stress", "pass": True, "violations": []},
        {"candidate_id": "cand-011", "stage": "scenario", "pass": True, "violations": []},
        {"candidate_id": "cand-011", "stage": "backtest", "pass": True, "violations": []},
    ]
    candidate_path = tmp_path / "candidate.json"
    _write_json(candidate_path, candidate)
    report_paths = []
    for i, payload in enumerate(reports):
        path = tmp_path / f"r{i}.json"
        _write_json(path, payload)
        report_paths.append(path)

    ticket_path = tmp_path / "approval_ticket.json"
    _write_json(
        ticket_path,
        {
            "ticket_id": "appr-011",
            "candidate_id": "cand-other",
            "trace_id": "trace-other",
            "policy_version": "wrong.v1",
            "approved_at": "2026-05-12T00:00:00Z",
            "expires_at": "2027-05-12T00:00:00Z",
            "scope": {"to_versions": ["v9.9.9"]},
            "schema_version": "evolution-p2-approval-ticket-v0.1",
        },
    )

    rc = mod.main(
        [
            "--candidate",
            str(candidate_path),
            "--reports",
            ",".join(str(path) for path in report_paths),
            "--to-version",
            "v0.1.2",
            "--approval-ticket-json",
            str(ticket_path),
            "--artifacts-dir",
            str(tmp_path / "decision"),
            "--rollback-dir",
            str(tmp_path / "rollback"),
            "--approval-artifacts-dir",
            str(tmp_path / "approval"),
            "--timestamp",
            "2026-05-12T10:40:00Z",
        ]
    )
    assert rc == 0
    payload = json.loads((tmp_path / "decision" / "decision-20260512T104000Z.json").read_text(encoding="utf-8"))
    assert payload["decision"] == "approve"
