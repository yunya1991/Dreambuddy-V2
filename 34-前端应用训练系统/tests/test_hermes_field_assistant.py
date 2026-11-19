# -*- coding: utf-8 -*-
"""P0-D3C RED: Hermes 场外助手有界救援。

契约:
  FieldAssistant.rescue(envelope) -> RescueResult
  有界: max_attempts / 成本上限 / 交接拒绝 / 异常升级人工。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.hermes_field_assistant import (  # noqa: E402
    FieldAssistant,
    RescueBudget,
    RescueResult,
)
from core.hermes_handoff import HandoffEnvelope, HandoffLedger  # noqa: E402

NOW = 10_000.0


def _env(ticket_id="TK-1", **kw):
    data = {
        "ticket_id": ticket_id,
        "trace_id": "rp-1",
        "trigger": "no_progress",
        "goal": "完成调研",
        "failure_class": "manual",
        "attempted_steps": ["recall:ok"],
        "evidence_refs": ["artifact:a.md"],
        "allowed_tools": ["recall"],
        "forbidden_tools": ["place_order"],
        "budget": {"max_attempts": 1, "timeout_s": 300, "max_cost_usd": 0.5},
    }
    data.update(kw)
    return HandoffEnvelope.from_dict(data)


def test_resolved_passthrough():
    calls = []

    def runner(env):
        calls.append(env.ticket_id)
        return RescueResult(status="resolved", summary="ok", evidence_refs=("artifact:b.md",))

    assistant = FieldAssistant(runner, budget=RescueBudget(), clock=lambda: NOW)
    result = assistant.rescue(_env())
    assert result.status == "resolved"
    assert result.evidence_refs == ("artifact:b.md",)
    assert calls == ["TK-1"]


def test_rejected_handoff_does_not_run():
    calls = []
    ledger = HandoffLedger()
    assistant = FieldAssistant(
        lambda env: calls.append(1) or RescueResult(status="resolved"),
        ledger=ledger,
        budget=RescueBudget(),
        clock=lambda: NOW,
    )
    result = assistant.rescue(_env(trigger="bogus"))
    assert result.status == "rejected"
    assert calls == []


def test_runner_exception_escalates():
    escalated = []
    assistant = FieldAssistant(
        lambda env: (_ for _ in ()).throw(RuntimeError("boom")),
        budget=RescueBudget(max_attempts=2),
        clock=lambda: NOW,
        escalator=lambda env, res: escalated.append(res.status),
    )
    result = assistant.rescue(_env())
    assert result.status == "needs_human"
    assert escalated == ["needs_human"]


def test_invalid_result_escalates():
    assistant = FieldAssistant(
        lambda env: {"status": "bogus"},
        budget=RescueBudget(max_attempts=1),
        clock=lambda: NOW,
    )
    result = assistant.rescue(_env())
    assert result.status == "needs_human"


def test_cost_over_budget_escalates():
    assistant = FieldAssistant(
        lambda env: RescueResult(status="resolved", cost_usd=9.0),
        budget=RescueBudget(max_attempts=1, max_cost_usd=0.5),
        clock=lambda: NOW,
    )
    result = assistant.rescue(_env())
    assert result.status == "needs_human"
    assert "budget" in (result.error or "")


def test_handoff_is_recorded_once():
    ledger = HandoffLedger()
    assistant = FieldAssistant(
        lambda env: RescueResult(status="partial"),
        ledger=ledger,
        budget=RescueBudget(),
        clock=lambda: NOW,
    )
    assistant.rescue(_env())
    assert ledger.handoff_count("TK-1") == 1
