#!/usr/bin/env python3
"""L2 出口宪法门禁运行时封装测试（SPEC-57 §4.3）。"""

from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from l2_output_gate import gate_output, is_degraded, should_block  # noqa: E402


def test_clean_output_allows():
    result = gate_output("l2.debate.core", {"verdict": "多空分歧较大"}, evidence="partial")
    assert result["verdict"] == "allow", result
    assert result["ok"] is True


def test_execution_claim_denied():
    result = gate_output("l2.debate.core", {"verdict": "已买入 100 股"}, evidence="partial")
    assert result["verdict"] == "deny", result
    assert should_block(result) is True


def test_unknown_prompt_fails_open():
    result = gate_output("l2.not_registered.prompt", {"x": 1})
    assert result["verdict"] == "unknown", result
    assert is_degraded(result) is True
    assert "error" in result


def test_intent_evidence_none_is_accepted():
    result = gate_output(
        "l2.intent.router", {"intent": "query_price", "slots": {}}, evidence="none"
    )
    assert result["verdict"] == "allow", result
    assert should_block(result) is False
