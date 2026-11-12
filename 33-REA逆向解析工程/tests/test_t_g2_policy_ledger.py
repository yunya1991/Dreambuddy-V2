"""T-G2 Policy 账本 + 八门禁校验器 — RED 测试

SPEC-33-G：
  - §1 G-G2：每次 Policy 变更都有 policy_id / 前后 sha256 / 八门禁逐项结论 / 回滚点
  - §2.8 八门禁；§2.6 备份 manifest；§4 硬约束 15（promotion.json 留痕）
  - §2.11.9 第 2/3/9 条（幂等键、change_id 贯穿、BH-FDR）

RED 契约：core.evolution.policy_ledger 模块不存在。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from core.evolution.policy_ledger import (
    LEVEL_QUOTAS,
    PolicyLedger,
    PolicyLedgerError,
    evaluate_gates,
    sha256_file,
    sha256_text,
)

# ---------------------------------------------------------------- helpers


def _outcomes(section="evolution", n=30, span_hours=25.0):
    base = datetime(2026, 11, 10, tzinfo=timezone.utc)
    step = timedelta(hours=span_hours) / max(1, n - 1)
    return [
        {
            "event_id": f"oe_{i}",
            "change_id": "CH-1",
            "run_id": "R-1",
            "outcome_seq": i,
            "section": section,
            "accepted": True,
            "tests_pass": True,
            "reverted": False,
            "created_at": (base + step * i).isoformat(),
            "receipt_hash": f"h{i}",
        }
        for i in range(n)
    ]


def _gate_kwargs(**overrides):
    kwargs = {
        "level": "L1",
        "change": {"kind": "rule", "targets": ["rea_rules.yaml"], "units": 1},
        "backup": {"verified": True, "reason": ""},
        "sandbox_report": {
            "overall": "pass",
            "groups": {"A": "pass", "B": "pass", "C": "pass"},
        },
        "rollback_drill": {"overall": "pass"},
        "shadow_report": {"overall": "pass", "sections": {"evolution": "pass"}},
        "proposal": {"proposer_model": "model-a", "falsifier": "采纳率不升则失败"},
        "evaluation": {"evaluator_model": "model-b", "verdict": "improve", "confidence": 0.99},
        "outcomes": _outcomes(),
        "section": "evolution",
        "heldout_bucket": 25,
        "concurrent_changes": 1,
        "bh_fdr_q": None,
        "quota": {"used": 0, "limit": LEVEL_QUOTAS["L1"]},
        "breaker": {"open": False},
        "stateful": False,
    }
    kwargs.update(overrides)
    return kwargs


def _gate(report, number):
    return next(item for item in report["gates"] if item["gate"] == number)


# ---------------------------------------------------------------- 账本


def _record_l1(tmp_path, policy_id="P-20261111-01"):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    rule = workspace / "rea_rules.yaml"
    rule.write_text("rules: []\n", encoding="utf-8")
    ledger = PolicyLedger(tmp_path / "policy")
    record = ledger.record_change(
        policy_id,
        level="L1",
        changes=[
            {
                "path": "rea_rules.yaml",
                "sha256_after": sha256_text("rules: [new]\n"),
            }
        ],
        rollback_point="tag:policy-P-20261111-01-pre",
        workspace_root=workspace,
        change={"kind": "rule", "targets": ["rea_rules.yaml"]},
    )
    return ledger, workspace, record


def test_record_change_writes_version_manifest_and_rollback_script(tmp_path):
    ledger, workspace, record = _record_l1(tmp_path)
    version = ledger.get("P-20261111-01")

    assert version["policy_id"] == "P-20261111-01"
    assert version["status"] == "proposed"
    assert version["rollback_point"] == "tag:policy-P-20261111-01-pre"
    assert version["before_sha256"] != version["after_sha256"]
    assert record["before_sha256"] == version["before_sha256"]

    base = tmp_path / "policy" / "versions" / "P-20261111-01"
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entries"][0]["path"] == "rea_rules.yaml"
    assert manifest["entries"][0]["sha256_before"] == sha256_file(workspace / "rea_rules.yaml")

    backup = base / "backup" / "rea_rules.yaml"
    assert backup.read_text(encoding="utf-8") == "rules: []\n"

    script = base / "rollback.sh"
    assert script.exists() and os.access(script, os.X_OK)
    assert "rea_rules.yaml" in script.read_text(encoding="utf-8")

    registry = ledger.registry()
    assert registry["policies"]["P-20261111-01"]["level"] == "L1"


def test_verify_backup_detects_tampering(tmp_path):
    ledger, _workspace, _record = _record_l1(tmp_path)
    assert ledger.verify_backup("P-20261111-01")["verified"] is True

    backup = tmp_path / "policy" / "versions" / "P-20261111-01" / "backup" / "rea_rules.yaml"
    backup.write_text("tampered\n", encoding="utf-8")
    report = ledger.verify_backup("P-20261111-01")
    assert report["verified"] is False
    assert "sha256" in report["reason"]


# ---------------------------------------------------------------- 八门禁


def test_all_eight_gates_pass():
    report = evaluate_gates(**_gate_kwargs())
    assert [item["gate"] for item in report["gates"]] == list(range(1, 9))
    assert report["overall"] == "pass"


def test_gate1_backup_failure():
    report = evaluate_gates(**_gate_kwargs(backup={"verified": False, "reason": "sha256 不匹配"}))
    assert _gate(report, 1)["status"] == "fail"
    assert report["overall"] == "fail"


def test_gate2_requires_three_sandbox_groups():
    report = evaluate_gates(
        **_gate_kwargs(
            sandbox_report={"overall": "pass", "groups": {"A": "pass", "B": "fail", "C": "pass"}}
        )
    )
    assert _gate(report, 2)["status"] == "fail"


def test_gate3_stateful_requires_state_restore_drill():
    report = evaluate_gates(**_gate_kwargs(stateful=True, rollback_drill={"overall": "pass"}))
    assert _gate(report, 3)["status"] == "fail"

    report = evaluate_gates(
        **_gate_kwargs(stateful=True, rollback_drill={"overall": "pass", "state_restore": "pass"})
    )
    assert _gate(report, 3)["status"] == "pass"


def test_gate4_shadow_requires_per_section_pass():
    report = evaluate_gates(**_gate_kwargs(shadow_report={"overall": "pass", "sections": {}}))
    assert _gate(report, 4)["status"] == "hold"

    report = evaluate_gates(
        **_gate_kwargs(shadow_report={"overall": "pass", "sections": {"evolution": "fail"}})
    )
    assert _gate(report, 4)["status"] == "fail"


def test_gate5_separation_and_falsifier():
    same_model = evaluate_gates(
        **_gate_kwargs(
            proposal={"proposer_model": "model-a", "falsifier": "x"},
            evaluation={"evaluator_model": "model-a", "verdict": "improve", "confidence": 1.0},
        )
    )
    assert _gate(same_model, 5)["status"] == "fail"

    no_falsifier = evaluate_gates(
        **_gate_kwargs(proposal={"proposer_model": "model-a", "falsifier": ""})
    )
    assert _gate(no_falsifier, 5)["status"] == "hold"

    rejected = evaluate_gates(
        **_gate_kwargs(
            evaluation={"evaluator_model": "model-b", "verdict": "reject", "confidence": 0.99}
        )
    )
    assert _gate(rejected, 5)["status"] == "fail"


def test_gate6_change_magnitude():
    l1_two_units = evaluate_gates(
        **_gate_kwargs(change={"kind": "rule", "targets": ["a", "b"], "units": 2})
    )
    assert _gate(l1_two_units, 6)["status"] == "fail"

    l2_ok = evaluate_gates(
        **_gate_kwargs(
            level="L2",
            change={"kind": "code", "files": 3, "loc": 200, "modules": ["33-REA"]},
            quota={"used": 0, "limit": LEVEL_QUOTAS["L2"]},
        )
    )
    assert _gate(l2_ok, 6)["status"] == "pass"

    l2_too_many = evaluate_gates(
        **_gate_kwargs(
            level="L2",
            change={"kind": "code", "files": 4, "loc": 10, "modules": ["33-REA"]},
            quota={"used": 0, "limit": LEVEL_QUOTAS["L2"]},
        )
    )
    assert _gate(l2_too_many, 6)["status"] == "fail"

    l3 = evaluate_gates(
        **_gate_kwargs(
            level="L3",
            change={"kind": "architecture", "files": 1, "loc": 1, "modules": ["a", "b"]},
        )
    )
    assert _gate(l3, 6)["status"] == "fail"


def test_gate7_requires_outcome_volume_span_and_heldout():
    few = evaluate_gates(**_gate_kwargs(outcomes=_outcomes(n=29)))
    assert _gate(few, 7)["status"] == "fail"

    short = evaluate_gates(**_gate_kwargs(outcomes=_outcomes(span_hours=23.0)))
    assert _gate(short, 7)["status"] == "fail"

    thin_heldout = evaluate_gates(**_gate_kwargs(heldout_bucket=19))
    assert _gate(thin_heldout, 7)["status"] == "fail"

    untraceable = evaluate_gates(**_gate_kwargs(outcomes=_outcomes(n=5)))
    assert _gate(untraceable, 7)["status"] == "fail"


def test_gate7_multiple_changes_require_bh_fdr():
    missing = evaluate_gates(**_gate_kwargs(concurrent_changes=2, bh_fdr_q=None))
    assert _gate(missing, 7)["status"] == "hold"

    too_loose = evaluate_gates(**_gate_kwargs(concurrent_changes=2, bh_fdr_q=0.2))
    assert _gate(too_loose, 7)["status"] == "fail"

    corrected = evaluate_gates(**_gate_kwargs(concurrent_changes=2, bh_fdr_q=0.05))
    assert _gate(corrected, 7)["status"] == "pass"


def test_gate8_quota_and_breaker():
    exhausted = evaluate_gates(**_gate_kwargs(quota={"used": 1, "limit": 1}))
    assert _gate(exhausted, 8)["status"] == "fail"

    breaker = evaluate_gates(**_gate_kwargs(breaker={"open": True}))
    assert _gate(breaker, 8)["status"] == "fail"

    unconfigured = evaluate_gates(**_gate_kwargs(quota={"used": 0, "limit": 0}))
    assert _gate(unconfigured, 8)["status"] == "fail"


# ---------------------------------------------------------------- 晋级留痕


def _passing_report(ledger, policy_id="P-20261111-01"):
    return ledger.evaluate(
        policy_id,
        sandbox_report={"overall": "pass", "groups": {"A": "pass", "B": "pass", "C": "pass"}},
        rollback_drill={"overall": "pass"},
        shadow_report={"overall": "pass", "sections": {"evolution": "pass"}},
        proposal={"proposer_model": "model-a", "falsifier": "采纳率不升则失败"},
        evaluation={"evaluator_model": "model-b", "verdict": "improve", "confidence": 0.1},
        outcomes=_outcomes(),
        section="evolution",
        heldout_bucket=25,
    )


def test_ledger_evaluate_recomputes_backup_gate(tmp_path):
    ledger, _workspace, _record = _record_l1(tmp_path)
    report = _passing_report(ledger)
    assert report["overall"] == "pass"

    backup = tmp_path / "policy" / "versions" / "P-20261111-01" / "backup" / "rea_rules.yaml"
    backup.write_text("tampered\n", encoding="utf-8")
    tampered = ledger.evaluate(
        "P-20261111-01",
        sandbox_report={"overall": "pass", "groups": {"A": "pass", "B": "pass", "C": "pass"}},
        rollback_drill={"overall": "pass"},
        shadow_report={"overall": "pass", "sections": {"evolution": "pass"}},
        proposal={"proposer_model": "model-a", "falsifier": "x"},
        evaluation={"evaluator_model": "model-b", "verdict": "improve", "confidence": 0.1},
        outcomes=_outcomes(),
        section="evolution",
        heldout_bucket=25,
    )
    assert _gate(tampered, 1)["status"] == "fail"
    assert tampered["overall"] == "fail"


def test_promote_blocked_without_all_gates(tmp_path):
    ledger, _workspace, _record = _record_l1(tmp_path)
    failed = evaluate_gates(**_gate_kwargs(breaker={"open": True}))
    failed["policy_id"] = "P-20261111-01"

    with pytest.raises(PolicyLedgerError, match="门禁"):
        ledger.promote(
            "P-20261111-01",
            gate_report=failed,
            mode="manual",
            stage="S1",
            pollution_count=0,
        )


def test_promote_writes_trace_and_enforces_auto_stage(tmp_path):
    ledger, _workspace, _record = _record_l1(tmp_path)
    report = _passing_report(ledger)

    with pytest.raises(PolicyLedgerError, match="S3"):
        ledger.promote(
            "P-20261111-01",
            gate_report=report,
            mode="auto",
            stage="S2",
            pollution_count=0,
        )

    promotion = ledger.promote(
        "P-20261111-01",
        gate_report=report,
        mode="manual",
        stage="S1",
        pollution_count=2,
    )
    assert promotion["pollution_count"] == 2
    assert len(promotion["gates"]) == 8

    path = tmp_path / "policy" / "versions" / "P-20261111-01" / "promotion.json"
    trace = json.loads(path.read_text(encoding="utf-8"))
    assert trace["mode"] == "manual"
    assert trace["stage"] == "S1"
    assert trace["overall"] == "pass"

    assert ledger.get("P-20261111-01")["status"] == "promoted"
    assert ledger.weekly_usage("L1") == 1


def test_breaker_state_reads_local_file(tmp_path):
    ledger = PolicyLedger(tmp_path / "policy")
    assert ledger.breaker_state() == {"open": False}

    (tmp_path / "policy").mkdir(parents=True, exist_ok=True)
    (tmp_path / "policy" / "breaker.json").write_text(
        json.dumps({"open": True, "reason": "连续 2 次回滚"}), encoding="utf-8"
    )
    assert ledger.breaker_state()["open"] is True
