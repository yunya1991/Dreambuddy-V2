# -*- coding: utf-8 -*-
"""认知裁决 → L2 路线测试（SPEC-v1.4 §3.4/§4.1、SPEC-56 GAP-13）。

判定口径：
  - 输出只含 {coverage, source, verdict, l2_route} 四字段（IF-L2-2 禁止自由文本路线）；
  - in_scope → retrieval_augmented；unknown 且 coverage ≥ 0.65 → retrieval_augmented；
    其余（unknown 低覆盖 / out_of_scope）→ deep_reasoning；
  - 信号缺失或非法 → FAIL-OPEN：unknown + deep_reasoning，不得硬性拒答。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.l2_route import COVERAGE_THRESHOLD, decide_cognition_route  # noqa: E402


def _signal(coverage, verdict=None, source="capability_catalog"):
    signal = {"coverage": coverage}
    if verdict is not None:
        signal["verdict"] = verdict
    if source is not None:
        signal["source"] = source
    return {"decision": "L2_HANDOFF", "cognition_signal": signal}


def test_threshold_single_source():
    assert COVERAGE_THRESHOLD == 0.65


def test_in_scope_uses_retrieval():
    out = decide_cognition_route(_signal(0.4, "in_scope"))
    assert out == {
        "coverage": 0.4,
        "source": "capability_catalog",
        "verdict": "in_scope",
        "l2_route": "retrieval_augmented",
    }


def test_unknown_high_coverage_uses_retrieval():
    out = decide_cognition_route(_signal(0.65, "unknown"))
    assert out["l2_route"] == "retrieval_augmented"


def test_unknown_low_coverage_uses_deep_reasoning():
    out = decide_cognition_route(_signal(0.2, "unknown"))
    assert out["verdict"] == "unknown"
    assert out["l2_route"] == "deep_reasoning"


def test_missing_verdict_defaults_to_unknown():
    out = decide_cognition_route(_signal(0.9))
    assert out["verdict"] == "unknown"
    assert out["l2_route"] == "retrieval_augmented"


def test_out_of_scope_uses_deep_reasoning():
    out = decide_cognition_route(_signal(0.99, "out_of_scope"))
    assert out["verdict"] == "out_of_scope"
    assert out["l2_route"] == "deep_reasoning"


def test_missing_signal_fails_open_to_l2():
    out = decide_cognition_route({"decision": "L2_HANDOFF"})
    assert out["verdict"] == "unknown"
    assert out["l2_route"] == "deep_reasoning"
    assert out["coverage"] == 0.0


def test_invalid_coverage_fails_open():
    for bad in (-0.1, 1.5, "0.8", None, True):
        out = decide_cognition_route(_signal(bad, "in_scope"))
        assert out["verdict"] == "unknown", bad
        assert out["l2_route"] == "deep_reasoning", bad


def test_invalid_verdict_fails_open():
    out = decide_cognition_route(_signal(0.9, "maybe"))
    assert out["verdict"] == "unknown"
    assert out["l2_route"] == "deep_reasoning"


def test_output_is_closed_shape():
    out = decide_cognition_route(_signal(0.8, "in_scope", source=None))
    assert set(out) == {"coverage", "source", "verdict", "l2_route"}
    assert out["source"] == "capability_catalog"
