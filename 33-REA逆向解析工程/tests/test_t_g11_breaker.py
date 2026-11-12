"""T-G11 断路器 + 阶段回落 + 恢复审计 — RED 测试

SPEC-33-G §2.8.2：
  - 连续 2 次 auto 晋级在观察期回滚 → `breaker.json` open=true
  - 冻结 auto 7 天；阶段立即回落 S2
  - 恢复：人工 `reset_breaker.py`（必须填原因，写 audit log）
  - 可演练：open → 回落 → manual → reset → 补证据升级 → auto 恢复

RED 契约：controller 无 is_auto_frozen/breaker_audit；scripts/reset_breaker.py 不存在。
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.evolution.controller import EvolutionController
from core.evolution.policy_ledger import PolicyLedger

BASE = datetime(2026, 11, 1, tzinfo=timezone.utc)
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reset_breaker.py"


def _setup(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "rea_rules.yaml").write_text("rules: []\n", encoding="utf-8")
    ledger = PolicyLedger(tmp_path / "policy")
    ctrl = EvolutionController(ledger)
    ctrl.advance_stage("S2", reason="达标", evidence={"section_outcomes": 30, "hours": 24})
    ctrl.advance_stage("S3", reason="一致", evidence={"consecutive_agreements": 5})
    return ctrl, ledger, workspace


def _policy(ledger, workspace, policy_id):
    ledger.record_change(
        policy_id,
        level="L1",
        changes=[{"path": "rea_rules.yaml"}],
        rollback_point=f"tag-{policy_id}",
        workspace_root=workspace,
        change={"kind": "rule", "targets": ["rea_rules.yaml"]},
    )


def _gates(policy_id):
    return {
        "policy_id": policy_id,
        "overall": "pass",
        "gates": [
            {"gate": i, "name": f"g{i}", "status": "pass", "reason": ""} for i in range(1, 9)
        ],
    }


def _sandbox():
    return {"overall": "pass", "groups": {name: {"status": "pass"} for name in ("A", "B", "C")}}


def _shadow():
    return {"overall": "pass", "sections": {"evolution": "pass"}}


def _outcomes(count=30, hours=26):
    return [
        {
            "change_id": "CH-1",
            "run_id": f"R-{i}",
            "outcome_seq": i,
            "section": "evolution",
            "created_at": (BASE + timedelta(minutes=int(i * hours * 60 / count))).isoformat(),
        }
        for i in range(count)
    ]


def _auto_then_rollback(ctrl, ledger, workspace, policy_id):
    _policy(ledger, workspace, policy_id)
    ctrl.on_evaluated(policy_id, verdict="improve")
    ctrl.on_sandboxed(policy_id, _sandbox())
    ctrl.on_shadowed(policy_id, _shadow())
    assert ctrl.qualify(policy_id, _gates(policy_id))["decision"] == "auto"
    result = ctrl.observe(
        policy_id,
        before={"heldout_recall": 0.8},
        after={"outcomes": _outcomes(), "heldout_recall": 0.5},
    )
    assert result["decision"] == "rollback"


def test_breaker_open_falls_back_to_s2_and_freezes_auto(tmp_path):
    ctrl, ledger, workspace = _setup(tmp_path)
    _auto_then_rollback(ctrl, ledger, workspace, "P-1")
    _auto_then_rollback(ctrl, ledger, workspace, "P-2")

    breaker = ctrl.breaker()
    assert breaker["open"] is True
    assert ctrl.stage() == "S2"
    assert ctrl.is_auto_frozen() is True

    opened = datetime.fromisoformat(breaker["opened_at"])
    freeze_until = datetime.fromisoformat(breaker["freeze_until"])
    assert freeze_until - opened == timedelta(days=7)


def test_breaker_audit_records_open_and_reset(tmp_path):
    ctrl, ledger, workspace = _setup(tmp_path)
    _auto_then_rollback(ctrl, ledger, workspace, "P-1")
    _auto_then_rollback(ctrl, ledger, workspace, "P-2")

    audit = ctrl.breaker_audit()
    assert [item["event"] for item in audit] == ["breaker_open"]
    assert audit[0]["reason"]

    ctrl.reset_breaker(actor="operator", reason="故障已排查")
    audit = ctrl.breaker_audit()
    assert [item["event"] for item in audit] == ["breaker_open", "breaker_reset"]
    assert audit[1]["reason"] == "故障已排查"
    assert audit[1]["actor"] == "operator"
    assert ctrl.is_auto_frozen() is False
    assert audit[0]["reason"] in json.dumps(audit[1]["previous"], ensure_ascii=False)


def test_breaker_fallback_is_safe_when_already_at_s2(tmp_path):
    ctrl, ledger, workspace = _setup(tmp_path)
    _auto_then_rollback(ctrl, ledger, workspace, "P-1")
    ctrl.downgrade_stage("S2", reason="人工先降级")
    ctrl.open_breaker(reason="演练：阶段已在 S2")

    assert ctrl.breaker()["open"] is True
    assert ctrl.stage() == "S2"


def test_drill_recovery_needs_evidence_before_auto_resumes(tmp_path):
    ctrl, ledger, workspace = _setup(tmp_path)
    _auto_then_rollback(ctrl, ledger, workspace, "P-1")
    _auto_then_rollback(ctrl, ledger, workspace, "P-2")
    ctrl.reset_breaker(actor="operator", reason="演练恢复")

    # reset 不自动升阶段：仍在 S2，下一次晋级必须人工
    assert ctrl.stage() == "S2"
    _policy(ledger, workspace, "P-3")
    ctrl.on_evaluated("P-3", verdict="improve")
    ctrl.on_sandboxed("P-3", _sandbox())
    ctrl.on_shadowed("P-3", _shadow())
    assert ctrl.qualify("P-3", _gates("P-3"))["decision"] == "manual"
    ctrl.approve("P-3", actor="operator", reason="人工批准")

    # 补足 S2→S3 证据后才能回到 auto
    ctrl.advance_stage("S3", reason="恢复一致率", evidence={"consecutive_agreements": 5})
    _policy(ledger, workspace, "P-4")
    ctrl.on_evaluated("P-4", verdict="improve")
    ctrl.on_sandboxed("P-4", _sandbox())
    ctrl.on_shadowed("P-4", _shadow())
    assert ctrl.qualify("P-4", _gates("P-4"))["decision"] == "auto"


def test_reset_breaker_cli(tmp_path):
    ctrl, ledger, workspace = _setup(tmp_path)
    _auto_then_rollback(ctrl, ledger, workspace, "P-1")
    _auto_then_rollback(ctrl, ledger, workspace, "P-2")
    root = str(tmp_path / "policy")

    ok = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", root, "--reason", "CLI 恢复", "--actor", "oncall"],
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stderr
    payload = json.loads(ok.stdout)
    assert payload["ok"] is True
    assert payload["breaker"]["open"] is False
    assert payload["stage"] == "S2"

    audit_path = tmp_path / "policy" / "audit" / "breaker_audit.jsonl"
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert [item["event"] for item in events] == ["breaker_open", "breaker_reset"]
    assert events[-1]["actor"] == "oncall"

    missing = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", root], capture_output=True, text=True
    )
    assert missing.returncode != 0
