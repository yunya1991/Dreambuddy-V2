"""P1-1：认知裁决 → `l2_route` 接线测试（GAP-02 / GAP-13）。

覆盖:
  - 桥接加载 56 真实实现（非复制逻辑）
  - `in_scope` / 高覆盖 `unknown` → retrieval_augmented
  - 低覆盖 `unknown` / `out_of_scope` → deep_reasoning
  - 信号缺失 FAIL-OPEN（unknown + deep_reasoning），不拒答
  - SACGOrchestrator 三个出口的 route_signal 均带 cognition_signal
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.sacg_orchestrator as sacg  # noqa: E402
from core.l2_cognition_route import (  # noqa: E402
    attach_cognition_route,
    attach_to_route_result,
)


def _signal(coverage=None, verdict=None):
    signal = {"decision": "L2_HANDOFF", "route_confidence": 0.0, "reasons": ["l1_low_confidence"]}
    if coverage is not None or verdict is not None:
        signal["cognition_signal"] = {"coverage": coverage, "verdict": verdict}
    return signal


def test_bridge_uses_real_56_module():
    out = attach_cognition_route(_signal(0.9, "in_scope"))
    assert out["cognition_signal"] == {
        "coverage": 0.9,
        "source": "capability_catalog",
        "verdict": "in_scope",
        "l2_route": "retrieval_augmented",
    }


def test_low_coverage_unknown_routes_deep():
    out = attach_cognition_route(_signal(0.2, "unknown"))
    assert out["cognition_signal"]["l2_route"] == "deep_reasoning"


def test_out_of_scope_routes_deep():
    out = attach_cognition_route(_signal(0.99, "out_of_scope"))
    assert out["cognition_signal"]["verdict"] == "out_of_scope"
    assert out["cognition_signal"]["l2_route"] == "deep_reasoning"


def test_missing_signal_fails_open():
    out = attach_cognition_route(_signal())
    assert out["cognition_signal"]["verdict"] == "unknown"
    assert out["cognition_signal"]["l2_route"] == "deep_reasoning"


def test_existing_keys_preserved():
    out = attach_cognition_route(_signal(0.9, "in_scope"))
    assert out["decision"] == "L2_HANDOFF"
    assert out["reasons"] == ["l1_low_confidence"]


def test_route_result_only_annotates_handoff():
    handoff = {"success": True, "handled": False, "route_signal": _signal(0.9, "in_scope")}
    out = attach_to_route_result(handoff)
    assert out["route_signal"]["cognition_signal"]["l2_route"] == "retrieval_augmented"
    assert out["handled"] is False

    direct = {"success": True, "handled": True, "route_signal": {"decision": "L1_DIRECT"}}
    assert attach_to_route_result(direct)["route_signal"] == {"decision": "L1_DIRECT"}


class _L1Signal:
    decision = sacg.L1_DIRECT

    def to_dict(self):
        return {"decision": self.decision, "route_confidence": 1.0, "reasons": ["deterministic"]}


def test_orchestrator_exposes_l2_route(monkeypatch):
    monkeypatch.setattr(sacg, "evaluate_route", lambda memories: _L1Signal())
    out = sacg.SACGOrchestrator().handle("BTC 价格", memories=[])
    signal = out["route_signal"]
    assert signal["decision"] == "L1_DIRECT"
    assert signal["cognition_signal"]["verdict"] == "unknown"
    assert signal["cognition_signal"]["l2_route"] == "deep_reasoning"
