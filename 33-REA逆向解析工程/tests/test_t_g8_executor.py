"""T-G8 执行器（备份/沙箱/影子/污染回滚/自动回滚）— RED 测试

SPEC-33-G：
  - §1 G-G8：沙箱三组全绿；影子按 section 达标；回滚 ≤60s 且覆盖记忆污染
  - §2.6 污染回滚（tainted + 降权 ×0.3 + verify 回退）
  - §2.7 沙箱三组 + 隔离（禁写认知库 / 禁 git push / 禁外网）
  - §2.7.1 影子门槛与差异归因
  - §2.11.4 L2-9 / §4 硬约束 8、10、21

RED 契约：core.evolution.executor / core.evolution.pollution 不存在。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from core.evolution.case_ledger import CaseStore
from core.evolution.executor import (
    RollbackBudgetExceeded,
    RollbackExecutor,
    SandboxIsolationError,
    SandboxRunner,
    ShadowEvaluator,
    evaluate_observation,
)
from core.evolution.policy_ledger import PolicyLedger, sha256_text
from core.evolution.pollution import PollutionRollback

# ---------------------------------------------------------------- 沙箱


def test_sandbox_requires_three_green_groups(tmp_path):
    def ok(context):
        return {"status": "pass", "detail": context["change_id"]}

    runner = SandboxRunner({"A": ok, "B": ok, "C": ok}, root=tmp_path)
    report = runner.run("CH-1")
    assert report["overall"] == "pass"
    assert set(report["groups"]) == {"A", "B", "C"}

    failing = SandboxRunner(
        {"A": ok, "B": lambda context: {"status": "fail", "detail": "boom"}, "C": ok},
        root=tmp_path,
    ).run("CH-2")
    assert failing["overall"] == "fail"


def test_sandbox_rejects_non_isolated_settings(tmp_path):
    with pytest.raises(SandboxIsolationError, match="认知库"):
        SandboxRunner({"A": lambda c: "pass"}, root=tmp_path, allow_cognition_write=True)
    with pytest.raises(SandboxIsolationError, match="git push"):
        SandboxRunner({"A": lambda c: "pass"}, root=tmp_path, allow_git_push=True)
    with pytest.raises(SandboxIsolationError, match="外网"):
        SandboxRunner({"A": lambda c: "pass"}, root=tmp_path, allow_network=True)


# ---------------------------------------------------------------- 影子


def _shadow_section(**overrides):
    section = {
        "calls": 20,
        "duration_hours": 24,
        "heldout_before": 0.8,
        "heldout_after": 0.8,
        "degraded": 1,
        "degraded_baseline_7d": 1.0,
        "p95_before_ms": 100.0,
        "p95_after_ms": 120.0,
        "diffs": [{"attributed": True}, {"attributed": True}],
    }
    section.update(overrides)
    return section


def test_shadow_pass_and_per_section_status():
    report = ShadowEvaluator().evaluate({"evolution": _shadow_section()})
    assert report["overall"] == "pass"
    assert report["sections"] == {"evolution": "pass"}


def test_shadow_thresholds_and_attribution():
    evaluator = ShadowEvaluator()
    assert (
        evaluator.evaluate({"evolution": _shadow_section(calls=19)})["sections"]["evolution"]
        == "hold"
    )
    assert (
        evaluator.evaluate({"evolution": _shadow_section(duration_hours=23.0)})["sections"][
            "evolution"
        ]
        == "hold"
    )
    assert (
        evaluator.evaluate({"evolution": _shadow_section(heldout_after=0.7)})["sections"][
            "evolution"
        ]
        == "fail"
    )
    assert (
        evaluator.evaluate({"evolution": _shadow_section(degraded=3)})["sections"]["evolution"]
        == "fail"
    )
    assert (
        evaluator.evaluate({"evolution": _shadow_section(p95_after_ms=125.0)})["sections"][
            "evolution"
        ]
        == "fail"
    )
    out_of_range = _shadow_section(diffs=[{"attributed": True}, {"attributed": False}])
    assert evaluator.evaluate({"evolution": out_of_range})["sections"]["evolution"] == "fail"


# ---------------------------------------------------------------- 污染回滚


def _case(policy_id="P-1", iteration_id="I-1", case_id="C-1"):
    return {
        "case_id": case_id,
        "iteration_id": iteration_id,
        "goal": "x",
        "hypotheses": [{"claim": "c", "falsifier": "f"}],
        "changes": {"files": 1, "loc": 1, "modules": ["m"], "level": "L1"},
        "verification": {"tests": 1, "passed": 1, "duration_s": 1, "gates": []},
        "outcome": {"accepted": True, "reverted": False, "reviewer": "auto"},
        "defects": [],
        "lessons": [],
        "policy_id": policy_id,
        "evidence_refs": [],
        "created_at": "2026-11-11T00:00:00+00:00",
    }


def test_pollution_rollback_taints_only_matching_policy(tmp_path):
    store = CaseStore(tmp_path / "cases.jsonl")
    store.add(_case(policy_id="P-1", iteration_id="I-1"))
    store.add(_case(policy_id="P-2", iteration_id="I-2", case_id="C-2"))

    report = PollutionRollback(case_store=store).rollback(
        policy_id="P-1", report_path=tmp_path / "pollution_report.json"
    )
    assert report["cases_tainted"] == 1
    assert store.get("I-1")["tainted"] is True
    assert "tainted" not in store.get("I-2")
    assert (
        json.loads((tmp_path / "pollution_report.json").read_text(encoding="utf-8"))[
            "cases_tainted"
        ]
        == 1
    )


def test_pollution_recall_weight_and_quality_rollback():
    rollback = PollutionRollback()
    assert rollback.recall_weight({"tainted": True}) == 0.3
    assert rollback.recall_weight({}) == 1.0
    assert rollback.rollback_quality("S") == "A"
    assert rollback.rollback_quality("C") == "D"
    assert rollback.rollback_quality("D") == "D"


# ---------------------------------------------------------------- 回滚执行


def _record_policy(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    rule = workspace / "rea_rules.yaml"
    rule.write_text("rules: [old]\n", encoding="utf-8")
    ledger = PolicyLedger(tmp_path / "policy")
    ledger.record_change(
        "P-1",
        level="L1",
        changes=[{"path": "rea_rules.yaml", "sha256_after": sha256_text("rules: [new]\n")}],
        rollback_point="tag:policy-P-1-pre",
        workspace_root=workspace,
        change={"kind": "rule", "targets": ["rea_rules.yaml"]},
    )
    rule.write_text("rules: [new]\n", encoding="utf-8")
    return ledger, workspace, rule


def test_rollback_restores_files_within_budget(tmp_path):
    ledger, workspace, rule = _record_policy(tmp_path)
    executor = RollbackExecutor(ledger)
    report = executor.rollback_policy("P-1", workspace_root=workspace)

    assert rule.read_text(encoding="utf-8") == "rules: [old]\n"
    assert report["duration_s"] <= 60
    assert ledger.get("P-1")["status"] == "rolled_back"


def test_rollback_budget_is_enforced(tmp_path):
    ledger, workspace, _rule = _record_policy(tmp_path)
    ticks = iter([0.0, 61.0])
    executor = RollbackExecutor(ledger, clock=lambda: next(ticks))
    with pytest.raises(RollbackBudgetExceeded, match="60"):
        executor.rollback_policy("P-1", workspace_root=workspace)


def test_stateful_rollback_requires_state_restore(tmp_path):
    ledger, workspace, _rule = _record_policy(tmp_path)
    executor = RollbackExecutor(ledger)
    with pytest.raises(ValueError, match="状态恢复"):
        executor.rollback_policy("P-1", workspace_root=workspace, stateful=True)

    called = {"restored": False}

    def restore():
        called["restored"] = True

    executor.rollback_policy("P-1", workspace_root=workspace, stateful=True, state_restore=restore)
    assert called["restored"] is True


def test_auto_rollback_decision_from_observation():
    base = datetime(2026, 11, 10, tzinfo=timezone.utc)
    outcomes = [
        {
            "change_id": "CH-1",
            "run_id": "R-1",
            "outcome_seq": i,
            "created_at": (base + timedelta(hours=i)).isoformat(),
            "accepted": True,
            "tests_pass": True,
            "reverted": False,
        }
        for i in range(30)
    ]
    before = {"heldout_recall": 0.8, "error_rate": 0.01}
    good = evaluate_observation(
        before, {"outcomes": outcomes, "heldout_recall": 0.8, "error_rate": 0.01}
    )
    assert good["decision"] == "confirm"

    degraded = evaluate_observation(
        before, {"outcomes": outcomes, "heldout_recall": 0.7, "error_rate": 0.01}
    )
    assert degraded["decision"] == "rollback"

    insufficient = evaluate_observation(before, {"outcomes": outcomes[:5], "heldout_recall": 0.7})
    assert insufficient["decision"] == "continue"
