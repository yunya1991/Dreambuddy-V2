"""T-G7 触发引擎 + 双模型提案/评估 — RED 测试

SPEC-33-G：
  - §1 G-G7：6 类触发器；提案模型 ≠ 评估模型；confidence 不作门禁
  - §2.3 rea_evolution.yaml 阈值（v2 含 capability_gap / case_pattern）
  - §2.4 proposal.json / evaluation.json 契约；falsifier 必填，缺失即 hold

RED 契约：core.evolution.triggers / core.evolution.proposal_pipeline 不存在。
"""

from __future__ import annotations

from core.evolution.proposal_pipeline import DualModelPipeline, validate_proposal
from core.evolution.triggers import DEFAULT_CONFIG, TriggerEngine


def _engine(**overrides):
    config = {**DEFAULT_CONFIG, **overrides}
    return TriggerEngine(config)


def _names(triggers):
    return [item["trigger"] for item in triggers]


# ---------------------------------------------------------------- 触发引擎


def test_repeat_failure_fires_at_threshold():
    engine = _engine()
    signals = {
        "failures": [
            {"signature": "budget_exceeded", "section": "evolution"},
            {"signature": "budget_exceeded", "section": "evolution"},
            {"signature": "budget_exceeded", "section": "evolution"},
        ]
    }
    triggers = engine.evaluate(signals)
    fired = [item for item in triggers if item["trigger"] == "repeat_failure"]
    assert len(fired) == 1
    assert fired[0]["key"] == "budget_exceeded"
    assert fired[0]["occurrences"] == 3

    below = engine.evaluate({"failures": signals["failures"][:2]})
    assert "repeat_failure" not in _names(below)


def test_hypothesis_overturned_requires_consecutive():
    engine = _engine()
    signal = {
        "hypotheses": [
            {"hypothesis_id": "H-1", "status": "overturned"},
            {"hypothesis_id": "H-2", "status": "supported"},
            {"hypothesis_id": "H-3", "status": "overturned"},
            {"hypothesis_id": "H-4", "status": "overturned"},
        ]
    }
    triggers = engine.evaluate(signal)
    fired = [item for item in triggers if item["trigger"] == "hypothesis_overturned"]
    assert fired and fired[0]["occurrences"] == 2
    assert set(fired[0]["evidence"]) == {"H-3", "H-4"}


def test_memory_saturation_requires_count_and_idle_days():
    engine = _engine()
    triggers = engine.evaluate({"memories": {"count": 25, "idle_days": 31}})
    assert "memory_saturation" in _names(triggers)

    idle = engine.evaluate({"memories": {"count": 25, "idle_days": 10}})
    assert "memory_saturation" not in _names(idle)


def test_metric_drift_emits_per_metric():
    engine = _engine()
    triggers = engine.evaluate(
        {"metrics": {"cycles_pct": 35, "god_components_pct": 10, "fan_out_pct": 40}}
    )
    drift = [item for item in triggers if item["trigger"] == "metric_drift"]
    assert {item["key"] for item in drift} == {"cycles_pct", "fan_out_pct"}


def test_coverage_gap_and_adoption_drop():
    engine = _engine()
    signals = {
        "coverage": [{"capability": "trace", "occurrences": 6}],
        "adoption": [{"section": "evolution", "previous_rate": 0.5, "current_rate": 0.3}],
    }
    triggers = engine.evaluate(signals)
    assert "coverage_gap" in _names(triggers)
    drop = [item for item in triggers if item["trigger"] == "adoption_drop"]
    assert drop and drop[0]["occurrences"] == 40  # 20 个百分点 = 40% 相对下降

    below = engine.evaluate(
        {"adoption": [{"section": "evolution", "previous_rate": 0.5, "current_rate": 0.45}]}
    )
    assert "adoption_drop" not in _names(below)


def test_capability_gap_requires_references_with_license():
    engine = _engine()
    references = [
        {"capability": "shadow-eval", "stack_fit": 0.8, "license": "MIT"},
        {"capability": "shadow-eval", "stack_fit": 0.7, "license": "Apache-2.0"},
    ]
    triggers = engine.evaluate({"references": references})
    fired = [item for item in triggers if item["trigger"] == "capability_gap"]
    assert fired and fired[0]["key"] == "shadow-eval"

    unknown = [dict(item, license="unknown") for item in references]
    assert "capability_gap" not in _names(engine.evaluate({"references": unknown}))

    low_fit = [dict(item, stack_fit=0.2) for item in references]
    assert "capability_gap" not in _names(engine.evaluate({"references": low_fit}))


def test_case_pattern_requires_distinct_iterations():
    engine = _engine()
    cases = [{"pattern": "flaky_gate", "iteration_id": f"I-{i % 3}"} for i in range(5)]
    triggers = engine.evaluate({"cases": cases})
    fired = [item for item in triggers if item["trigger"] == "case_pattern"]
    assert fired and fired[0]["occurrences"] == 5

    same_iteration = [dict(item, iteration_id="I-0") for item in cases]
    assert "case_pattern" not in _names(engine.evaluate({"cases": same_iteration}))


def test_all_six_legacy_triggers_are_covered():
    engine = _engine()
    signals = {
        "failures": [{"signature": "f", "section": "evolution"}] * 3,
        "hypotheses": [{"hypothesis_id": "H", "status": "overturned"}] * 2,
        "memories": {"count": 20, "idle_days": 30},
        "metrics": {"cycles_pct": 30},
        "coverage": [{"capability": "c", "occurrences": 5}],
        "adoption": [{"section": "evolution", "previous_rate": 1.0, "current_rate": 0.7}],
    }
    names = set(_names(engine.evaluate(signals)))
    assert {
        "repeat_failure",
        "hypothesis_overturned",
        "memory_saturation",
        "metric_drift",
        "coverage_gap",
        "adoption_drop",
    } <= names


# ---------------------------------------------------------------- 双模型


def _proposal(**overrides):
    proposal = {
        "proposal_id": "PR-1",
        "level": "L1",
        "trigger": "repeat_failure",
        "claim": "预算阈值应提高",
        "expected_effect": "失败率下降",
        "blast_radius": "evolution",
        "change_draft": {"kind": "param", "target": "budget"},
        "falsifier": "失败率不降则失败",
        "proposer_model": "model-a",
        "created_at": "2026-11-11T00:00:00+00:00",
    }
    proposal.update(overrides)
    return proposal


def test_validate_proposal_requires_falsifier():
    ok, reason = validate_proposal(_proposal())
    assert ok is True and reason == ""

    broken = _proposal()
    broken.pop("falsifier")
    ok, reason = validate_proposal(broken)
    assert ok is False and "falsifier" in reason


def test_pipeline_holds_when_models_not_separated():
    calls = {"evaluator": 0}

    def evaluator(payload):
        calls["evaluator"] += 1
        return {"verdict": "improve", "evaluator_model": "model-a", "confidence": 1.0}

    pipeline = DualModelPipeline(
        proposer=lambda payload: _proposal(),
        evaluator=evaluator,
        proposer_model="model-a",
        evaluator_model="model-a",
    )
    result = pipeline.run({"trigger": "repeat_failure"})
    assert result["status"] == "held"
    assert "模型" in result["reason"]
    assert calls["evaluator"] == 0


def test_pipeline_holds_when_proposal_lacks_falsifier():
    called = {"evaluator": 0}

    def evaluator(payload):
        called["evaluator"] += 1
        return {"verdict": "improve", "evaluator_model": "model-b", "confidence": 0.9}

    broken = _proposal()
    broken.pop("falsifier")
    pipeline = DualModelPipeline(
        proposer=lambda payload: broken,
        evaluator=evaluator,
        proposer_model="model-a",
        evaluator_model="model-b",
    )
    result = pipeline.run({"trigger": "repeat_failure"})
    assert result["status"] == "held"
    assert "falsifier" in result["reason"]
    assert called["evaluator"] == 0


def test_pipeline_ignores_confidence_for_verdict():
    low_confidence = DualModelPipeline(
        proposer=lambda payload: _proposal(),
        evaluator=lambda payload: {
            "verdict": "improve",
            "evaluator_model": "model-b",
            "confidence": 0.0,
        },
        proposer_model="model-a",
        evaluator_model="model-b",
    )
    result = low_confidence.run({"trigger": "repeat_failure"})
    assert result["status"] == "evaluated"
    assert result["evaluation"]["verdict"] == "improve"

    high_confidence = DualModelPipeline(
        proposer=lambda payload: _proposal(),
        evaluator=lambda payload: {
            "verdict": "reject",
            "evaluator_model": "model-b",
            "confidence": 1.0,
        },
        proposer_model="model-a",
        evaluator_model="model-b",
    )
    rejected = high_confidence.run({"trigger": "repeat_failure"})
    assert rejected["evaluation"]["verdict"] == "reject"


def test_pipeline_injects_metadata_and_strips_proposer_reasoning():
    seen = {}

    def proposer(payload):
        return _proposal(
            proposal_id="",
            proposer_reasoning="内部推理不应传给评估模型",
            falsifier="",
        )

    def evaluator(payload):
        seen.update(payload)
        return {"verdict": "improve", "evaluator_model": "model-b", "confidence": 0.5}

    pipeline = DualModelPipeline(
        proposer=proposer,
        evaluator=evaluator,
        proposer_model="model-a",
        evaluator_model="model-b",
    )
    # falsifier 为空 -> held，不调用评估器
    held = pipeline.run({"trigger": "repeat_failure"})
    assert held["status"] == "held"
    assert seen == {}

    def good_proposer(payload):
        return _proposal(
            proposal_id="",
            proposer_reasoning="内部推理不应传给评估模型",
        )

    pipeline = DualModelPipeline(
        proposer=good_proposer,
        evaluator=evaluator,
        proposer_model="model-a",
        evaluator_model="model-b",
    )
    result = pipeline.run({"trigger": "repeat_failure", "evidence": [{"id": "E-1"}]})
    assert result["status"] == "evaluated"
    assert result["proposal"]["proposal_id"].startswith("PR-")
    assert result["evaluation"]["evaluator_version"] == "1"
    assert "proposer_reasoning" not in seen["proposal"]
    assert seen["evidence"] == [{"id": "E-1"}]
