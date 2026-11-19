# -*- coding: utf-8 -*-
"""P0-D3C RED: DSH ↔ Hermes 断路交接协议。

契约:
  HandoffEnvelope / HandoffDecision / HandoffLedger / decide_handoff
  硬规则: 最多 2 次交接、必须有新信息、冷却期、未知触发拒绝。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.hermes_handoff import (  # noqa: E402
    HandoffEnvelope,
    HandoffLedger,
    decide_handoff,
)

NOW = 10_000.0


def _env(ticket_id="TK-1", trigger="no_progress", **kw):
    data = {
        "ticket_id": ticket_id,
        "trace_id": "rp-1",
        "trigger": trigger,
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


def test_valid_envelope_allowed():
    ledger = HandoffLedger()
    decision = decide_handoff(_env(), ledger, now=NOW, cooldown_s=0)
    assert decision.allowed is True
    assert decision.reason == "ok"


def test_unknown_trigger_rejected():
    ledger = HandoffLedger()
    decision = decide_handoff(_env(trigger="bogus"), ledger, now=NOW, cooldown_s=0)
    assert decision.allowed is False
    assert decision.reason == "unknown_trigger"


def test_invalid_envelope_rejected():
    ledger = HandoffLedger()
    env = _env()
    env = HandoffEnvelope(ticket_id="", trace_id="", trigger="no_progress", goal="")
    decision = decide_handoff(env, ledger, now=NOW, cooldown_s=0)
    assert decision.allowed is False
    assert decision.reason == "invalid_envelope"


def test_third_handoff_rejected():
    ledger = HandoffLedger()
    for i in range(2):
        env = _env(attempted_steps=[f"step-{i}"])
        d = decide_handoff(env, ledger, now=NOW + i, cooldown_s=0)
        assert d.allowed is True
        ledger.append(env, now=NOW + i)
    d = decide_handoff(_env(attempted_steps=["step-new"]), ledger, now=NOW + 10, cooldown_s=0)
    assert d.allowed is False
    assert d.reason == "handoff_limit"


def test_same_information_rejected():
    ledger = HandoffLedger()
    env = _env()
    assert decide_handoff(env, ledger, now=NOW, cooldown_s=0).allowed is True
    ledger.append(env, now=NOW)
    again = decide_handoff(_env(), ledger, now=NOW + 100, cooldown_s=0)
    assert again.allowed is False
    assert again.reason == "no_new_information"


def test_cooldown_rejected():
    ledger = HandoffLedger()
    first = _env(attempted_steps=["a"])
    ledger.append(first, now=NOW)
    second = _env(attempted_steps=["b"])
    d = decide_handoff(second, ledger, now=NOW + 10, cooldown_s=60)
    assert d.allowed is False
    assert d.reason == "cooldown"


def test_ledger_persists(tmp_path):
    path = tmp_path / "handoff.jsonl"
    ledger = HandoffLedger(str(path))
    ledger.append(_env(), now=NOW)
    again = HandoffLedger(str(path))
    assert again.handoff_count("TK-1") == 1
    assert again.entries("TK-1")[0]["trigger"] == "no_progress"
