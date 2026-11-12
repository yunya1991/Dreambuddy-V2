"""T-G9 双模晋级控制器（状态机 + 三段式 + 飞书告警）— RED 测试

SPEC-33-G：
  - §2.5 状态机 proposed→evaluated→sandboxed→shadowed→qualified→promoted→observing→confirmed/rolled_back
  - §2.8 双模晋级：无 AI 模式 qualified→notified + 飞书告警 + 人工批准
  - §2.8.1 三段式：S1 manual 不启影子 / S2 manual+shadow / S3 auto（前 3 次 24h 否决）
  - §2.8.2 断路器：连续 2 次 auto 观察期回滚 → open + 冻结 auto + 阶段回落 S2
  - §2.10 防退化五原则；§1 G-G9

RED 契约：core.evolution.controller 不存在。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from core.evolution.controller import ControllerError, EvolutionController
from core.evolution.policy_ledger import PolicyLedger

BASE = datetime(2026, 11, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------- 工具


def _make_ledger(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "rea_rules.yaml").write_text("rules: []\n", encoding="utf-8")
    ledger = PolicyLedger(tmp_path / "policy")
    return ledger, workspace


def _make_policy(ledger, workspace, policy_id="P-1"):
    return ledger.record_change(
        policy_id,
        level="L1",
        changes=[{"path": "rea_rules.yaml"}],
        rollback_point=f"tag-policy-{policy_id}-pre",
        workspace_root=workspace,
        change={"kind": "rule", "targets": ["rea_rules.yaml"]},
    )


def _gates(policy_id, status="pass"):
    return {
        "policy_id": policy_id,
        "overall": status,
        "gates": [
            {"gate": i, "name": f"gate-{i}", "status": status, "reason": ""} for i in range(1, 9)
        ],
    }


def _sandbox_pass():
    return {
        "overall": "pass",
        "groups": {name: {"status": "pass", "detail": ""} for name in ("A", "B", "C")},
    }


def _shadow_pass(section="evolution"):
    return {"overall": "pass", "sections": {section: "pass"}}


def _outcomes(count=30, hours=26, section="evolution"):
    rows = []
    for index in range(count):
        rows.append(
            {
                "change_id": "CH-1",
                "run_id": f"R-{index}",
                "outcome_seq": index,
                "section": section,
                "created_at": (
                    BASE + timedelta(minutes=int(index * hours * 60 / count))
                ).isoformat(),
            }
        )
    return rows


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, event):
        self.events.append(event)
        return True


def _controller(tmp_path, stage=None, notifier=None):
    ledger, workspace = _make_ledger(tmp_path)
    ctrl = EvolutionController(ledger, notifier=notifier or Recorder())
    if stage is not None:
        _force_stage(ctrl, stage)
    return ctrl, ledger, workspace


def _force_stage(ctrl, target):
    """按 SPEC 退出条件逐级升级（不走后门，直接调用公开 API）。"""
    if target in ("S2", "S3"):
        ctrl.advance_stage(
            "S2", reason="S1 数据积累达标", evidence={"section_outcomes": 30, "hours": 24}
        )
    if target == "S3":
        ctrl.advance_stage("S3", reason="S2 一致率达标", evidence={"consecutive_agreements": 5})


def _to_sandboxed(ctrl, policy_id="P-1"):
    ctrl.on_evaluated(policy_id, verdict="improve")
    ctrl.on_sandboxed(policy_id, _sandbox_pass())


def _to_qualified(ctrl, policy_id="P-1", stage="S3"):
    _to_sandboxed(ctrl, policy_id)
    if stage in ("S2", "S3"):
        ctrl.on_shadowed(policy_id, _shadow_pass())
    return ctrl.qualify(policy_id, _gates(policy_id))


# ---------------------------------------------------------------- 三段式


def test_s1_is_manual_and_never_runs_shadow(tmp_path):
    ctrl, ledger, workspace = _controller(tmp_path)
    _make_policy(ledger, workspace)

    assert ctrl.stage() == "S1"
    with pytest.raises(ControllerError, match="S1"):
        ctrl.on_shadowed("P-1", _shadow_pass())

    record = _to_qualified(ctrl, "P-1", stage="S1")
    assert record["decision"] == "manual"
    assert ctrl.state("P-1") == "notified"
    assert ledger.get("P-1")["status"] == "proposed"


def test_stage_upgrade_needs_exit_evidence_and_downgrade_is_immediate(tmp_path):
    ctrl, _, _ = _controller(tmp_path)

    with pytest.raises(ControllerError, match="S3"):
        ctrl.advance_stage("S3", reason="skip", evidence={"consecutive_agreements": 5})
    with pytest.raises(ControllerError, match="30"):
        ctrl.advance_stage("S2", reason="no evidence", evidence={"section_outcomes": 3})
    ctrl.advance_stage("S2", reason="达标", evidence={"section_outcomes": 30, "hours": 24})
    with pytest.raises(ControllerError, match="5"):
        ctrl.advance_stage("S3", reason="一致率不足", evidence={"consecutive_agreements": 4})
    ctrl.advance_stage("S3", reason="一致率达标", evidence={"consecutive_agreements": 5})
    assert ctrl.stage() == "S3"

    ctrl.downgrade_stage("S2", reason="人工回退")
    assert ctrl.stage() == "S2"
    with pytest.raises(ControllerError):
        ctrl.downgrade_stage("S3", reason="不允许通过 downgrade 升级")


# ---------------------------------------------------------------- 状态机


def test_state_machine_rejects_out_of_order_events(tmp_path):
    ctrl, ledger, workspace = _controller(tmp_path)
    _make_policy(ledger, workspace)

    with pytest.raises(ControllerError, match="evaluated"):
        ctrl.on_sandboxed("P-1", _sandbox_pass())
    with pytest.raises(ControllerError, match="evaluated"):
        ctrl.qualify("P-1", _gates("P-1"))


def test_shadow_failure_is_terminal_for_auto_path(tmp_path):
    ctrl, ledger, workspace = _controller(tmp_path, stage="S2")
    _make_policy(ledger, workspace)
    _to_sandboxed(ctrl)

    ctrl.on_shadowed("P-1", {"overall": "fail", "sections": {"evolution": "fail"}})
    assert ctrl.state("P-1") == "shadow_failed"
    with pytest.raises(ControllerError, match="shadow_failed"):
        ctrl.qualify("P-1", _gates("P-1"))
    assert ledger.get("P-1")["status"] == "proposed"


def test_failed_gates_block_any_promotion(tmp_path):
    ctrl, ledger, workspace = _controller(tmp_path, stage="S3")
    _make_policy(ledger, workspace)
    _to_sandboxed(ctrl)
    ctrl.on_shadowed("P-1", _shadow_pass())

    result = ctrl.qualify("P-1", _gates("P-1", status="hold"))
    assert result["decision"] == "blocked"
    assert ctrl.state("P-1") in ("hold", "quota_exceeded", "breaker_open")
    assert ledger.get("P-1")["status"] == "proposed"


# ---------------------------------------------------------------- 双模


def test_s3_auto_promotes_only_with_eight_green_gates(tmp_path):
    notifier = Recorder()
    ctrl, ledger, workspace = _controller(tmp_path, stage="S3", notifier=notifier)
    _make_policy(ledger, workspace)

    result = _to_qualified(ctrl, "P-1", stage="S3")
    assert result["decision"] == "auto"
    assert result["mode"] == "auto"
    assert ctrl.state("P-1") == "observing"

    record = ledger.get("P-1")
    assert record["status"] == "promoted"
    promotion = json.loads(
        (ledger.bundle_dir("P-1") / "promotion.json").read_text(encoding="utf-8")
    )
    assert promotion["mode"] == "auto"
    assert promotion["stage"] == "S3"

    # 前 3 次 auto 晋级保留 24h 否决窗口
    assert result["veto_until"] is not None
    kinds = {event["event"] for event in notifier.events}
    assert "auto_notice" in kinds
    assert "manual_required" not in kinds


def test_manual_mode_alerts_and_never_auto_promotes(tmp_path):
    notifier = Recorder()
    ctrl, ledger, workspace = _controller(tmp_path, stage="S2", notifier=notifier)
    _make_policy(ledger, workspace)

    result = _to_qualified(ctrl, "P-1", stage="S2")
    assert result["decision"] == "manual"
    assert ctrl.state("P-1") == "notified"
    assert ledger.get("P-1")["status"] == "proposed"
    assert [event["event"] for event in notifier.events] == ["manual_required"]

    approved = ctrl.approve("P-1", actor="operator", reason="人工复核通过")
    assert approved["mode"] == "manual"
    assert ctrl.state("P-1") == "observing"
    assert ledger.get("P-1")["status"] == "promoted"


def test_breaker_open_forces_manual_even_at_s3(tmp_path):
    notifier = Recorder()
    ctrl, ledger, workspace = _controller(tmp_path, stage="S3", notifier=notifier)
    _make_policy(ledger, workspace)
    (ledger.root / "breaker.json").write_text(
        json.dumps({"open": True, "reason": "manual test"}), encoding="utf-8"
    )

    result = _to_qualified(ctrl, "P-1", stage="S3")
    assert result["decision"] == "manual"
    assert result["reason"] == "breaker_open"
    assert ctrl.state("P-1") == "notified"
    assert ledger.get("P-1")["status"] == "proposed"
    assert "manual_required" in {event["event"] for event in notifier.events}


# ---------------------------------------------------------------- 观察期与断路器


def test_observe_confirms_after_30_outcomes_over_24h(tmp_path):
    ctrl, ledger, workspace = _controller(tmp_path, stage="S3")
    _make_policy(ledger, workspace)
    _to_qualified(ctrl, "P-1", stage="S3")

    before = {"heldout_recall": 0.8, "error_rate": 0.10}
    after = {
        "outcomes": _outcomes(),
        "heldout_recall": 0.8,
        "error_rate": 0.10,
    }
    result = ctrl.observe("P-1", before=before, after=after)
    assert result["decision"] == "confirm"
    assert ctrl.state("P-1") == "confirmed"


def test_observe_needs_enough_outcomes_before_deciding(tmp_path):
    ctrl, ledger, workspace = _controller(tmp_path, stage="S3")
    _make_policy(ledger, workspace)
    _to_qualified(ctrl, "P-1", stage="S3")

    result = ctrl.observe(
        "P-1",
        before={"heldout_recall": 0.8},
        after={"outcomes": _outcomes(count=5), "heldout_recall": 0.8},
    )
    assert result["decision"] == "continue"
    assert ctrl.state("P-1") == "observing"


def test_veto_window_rolls_back_without_touching_breaker(tmp_path):
    ctrl, ledger, workspace = _controller(tmp_path, stage="S3")
    _make_policy(ledger, workspace)
    _to_qualified(ctrl, "P-1", stage="S3")

    result = ctrl.veto("P-1", actor="operator", reason="人工否决")
    assert result["state"] == "rolled_back"
    assert ledger.get("P-1")["status"] == "rolled_back"
    assert ctrl.breaker()["consecutive_auto_rollbacks"] == 0
    assert ctrl.breaker()["open"] is False


def test_two_auto_rollbacks_open_breaker_and_downgrade_stage(tmp_path):
    notifier = Recorder()
    ctrl, ledger, workspace = _controller(tmp_path, stage="S3", notifier=notifier)

    before = {"heldout_recall": 0.8, "error_rate": 0.10}
    after = {"outcomes": _outcomes(), "heldout_recall": 0.5, "error_rate": 0.10}

    for policy_id in ("P-1", "P-2"):
        _make_policy(ledger, workspace, policy_id)
        _to_qualified(ctrl, policy_id, stage="S3")
        decision = ctrl.observe(policy_id, before=before, after=after)
        assert decision["decision"] == "rollback"
        assert ctrl.state(policy_id) == "rolled_back"

    breaker = ctrl.breaker()
    assert breaker["open"] is True
    assert breaker["consecutive_auto_rollbacks"] == 2
    assert ctrl.stage() == "S2"
    assert "breaker_open" in {event["event"] for event in notifier.events}

    reset = ctrl.reset_breaker(actor="operator", reason="故障已排查")
    assert reset["open"] is False
    assert ctrl.breaker()["consecutive_auto_rollbacks"] == 0


def test_reset_breaker_requires_reason(tmp_path):
    ctrl, _, _ = _controller(tmp_path)
    with pytest.raises(ControllerError, match="原因"):
        ctrl.reset_breaker(actor="operator", reason="")
