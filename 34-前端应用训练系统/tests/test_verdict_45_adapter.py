# -*- coding: utf-8 -*-
"""T3.4: 45 消费 verdict 的统一适配器。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.verdict_45_adapter import (  # noqa: E402
    build_verdict_45_gate,
    merge_gate_decision,
    to_45_verdict,
    to_gate_context,
)


def _uv(verdict="supported", level="U2", refs=None):
    return {
        "level": level,
        "verdict": verdict,
        "evidence_refs": refs if refs is not None else ["backtest:1"],
        "trace_id": "tr-1",
        "confidence": 0.9,
    }


def test_to_45_verdict_mapping():
    assert to_45_verdict(_uv("supported")) == "PASS"
    assert to_45_verdict(_uv("contradicted")) == "BLOCK"
    assert to_45_verdict(_uv("inconclusive")) == "INCONCLUSIVE"
    assert to_45_verdict(_uv("needs_human")) == "INCONCLUSIVE"
    assert to_45_verdict(None) == "INCONCLUSIVE"


def test_context_carries_verdict_and_claims():
    ctx = to_gate_context(
        {
            "ticket_id": "TK-1",
            "trace_id": "tr-1",
            "claims": ["有效"],
            "required_verdict_level": "U2",
        },
        _uv(),
    )
    assert ctx["task_id"] == "TK-1"
    assert ctx["required_verdict_level"] == "U2"
    assert ctx["verdict_45"] == "PASS"
    assert ctx["claims"] == ["有效"]


def test_pass_requires_both_verdict_and_45():
    out = merge_gate_decision(_uv(), "U2", True, {"verdict": "PASS"})
    assert out["allow"] is True
    assert out["decision"] == "PASS"


def test_45_block_wins():
    out = merge_gate_decision(_uv(), "U2", False, {"verdict": "BLOCK"})
    assert out["allow"] is False
    assert out["decision"] == "BLOCK"
    assert "gate_block" in out["reasons"]


def test_missing_verdict_blocks_in_hard_mode():
    out = merge_gate_decision(None, "U2", True, {"verdict": "PASS"})
    assert out["allow"] is False
    assert out["decision"] == "INCONCLUSIVE"
    assert "verdict_missing" in out["reasons"]


def test_level_insufficient_blocks():
    out = merge_gate_decision(_uv(level="U1"), "U2", True, {"verdict": "PASS"})
    assert out["allow"] is False
    assert "verdict_level_insufficient" in out["reasons"]


def test_contradicted_blocks():
    out = merge_gate_decision(_uv("contradicted"), "U1", True, {"verdict": "PASS"})
    assert out["allow"] is False
    assert "verdict_contradicted" in out["reasons"]


def test_inconclusive_does_not_pass():
    out = merge_gate_decision(_uv("inconclusive"), "U1", True, {"verdict": "PASS"})
    assert out["allow"] is False
    assert out["decision"] == "INCONCLUSIVE"


def test_45_timeout_is_inconclusive():
    out = merge_gate_decision(_uv(), "U2", False, {"verdict": "TIMEOUT"})
    assert out["allow"] is False
    assert out["decision"] == "INCONCLUSIVE"
    assert "gate_not_decided" in out["reasons"]


def test_shadow_allows_but_records_would_block():
    out = merge_gate_decision(_uv("contradicted"), "U2", True, {"verdict": "PASS"}, mode="shadow")
    assert out["allow"] is True
    assert out["would_block"] is True
    assert out["decision"] == "BLOCK"


def test_build_gate_wires_provider_and_gate():
    def gate_fn(ctx):
        return True, {"verdict": "PASS", "eval_id": "E1"}

    gate = build_verdict_45_gate(gate_fn, lambda ctx: _uv(), required_level="U2")
    allow, report = gate({"task_id": "TK-1"})
    assert allow is True
    assert report["eval_id"] == "E1"


def test_build_gate_fail_open_on_bad_input():
    assert build_verdict_45_gate(None, None) is None


def test_adapter_never_raises_on_bad_gate_report():
    out = merge_gate_decision(_uv(), "U2", True, "not-a-dict")
    assert out["ok"] is True
    assert out["allow"] is False
