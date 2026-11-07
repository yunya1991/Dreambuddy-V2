"""R0-04 differential harness 测试。"""

from __future__ import annotations

from tools.differential_harness import diff_path_sets


def test_identical_sets_zero_divergence():
    paths = [
        {
            "path_id": "p1",
            "direction": "long",
            "confidence": 0.5,
            "dimension": "D3",
            "horizon": "hours",
            "intent": "trend",
            "continuation_score": 0.25,
        }
    ]
    result = diff_path_sets(paths, paths)
    assert result["divergence_rate"] == 0.0
    assert result["field_diffs"] == []


def test_field_diff_detected():
    control = [
        {
            "path_id": "p1",
            "direction": "long",
            "confidence": 0.5,
            "dimension": "D3",
            "horizon": "hours",
            "intent": "trend",
            "continuation_score": 0.25,
        }
    ]
    treatment = [
        {
            "path_id": "p1",
            "direction": "short",
            "confidence": 0.5,
            "dimension": "D3",
            "horizon": "hours",
            "intent": "trend",
            "continuation_score": 0.25,
        }
    ]
    result = diff_path_sets(control, treatment)
    assert len(result["field_diffs"]) == 1
    assert result["field_diffs"][0]["field"] == "direction"
    assert result["divergence_rate"] == 1.0


def test_only_one_side():
    control = [
        {
            "path_id": "p1",
            "direction": "long",
            "confidence": 0.5,
            "dimension": "D3",
            "horizon": "hours",
            "intent": "trend",
            "continuation_score": 0.25,
        }
    ]
    result = diff_path_sets(control, [])
    assert result["only_control"] == ["p1"]
    assert result["divergence_rate"] == 1.0
