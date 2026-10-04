"""N-P0b VerificationRecord + 多阶段 verify 信号测试（RED 阶段）。

验收标准：
- signals=None → 原布尔路径
- 全 abstain → 回退布尔路径（FAIL-OPEN）
- 有 fail → 不升级
- 全 pass ≥ min_quorum → 升级，p=pass/active
- Δconf = clip((p-conf)/4, -0.15, +0.10)
- VerificationRecord append-only（frozen）
"""
import json
import tempfile
from dataclasses import FrozenInstanceError

import pytest


# ---------------------------------------------------------------------------
# RED 起手
# ---------------------------------------------------------------------------

def test_module_importable():
    from verification_record import (
        VerificationSignal, VerificationRecord, VerificationOutcome,
        compute_aggregated_p, compute_fractional_delta,
    )


# ---------------------------------------------------------------------------
# VerificationSignal
# ---------------------------------------------------------------------------

def test_signal_fields():
    from verification_record import VerificationSignal
    s = VerificationSignal(
        stage="cycle_consistency",
        verdict="pass",
        verifier_id="v1",
    )
    assert s.stage == "cycle_consistency"
    assert s.verdict == "pass"
    assert s.verifier_id == "v1"
    assert s.evidence_hash == ""
    assert s.latency_ms == 0.0


def test_signal_verdict_must_be_valid():
    from verification_record import VerificationSignal
    with pytest.raises(ValueError):
        VerificationSignal(stage="x", verdict="bogus", verifier_id="v1")


def test_signal_is_frozen():
    from verification_record import VerificationSignal
    s = VerificationSignal(stage="x", verdict="pass", verifier_id="v1")
    with pytest.raises(FrozenInstanceError):
        s.verdict = "fail"


# ---------------------------------------------------------------------------
# VerificationRecord (append-only)
# ---------------------------------------------------------------------------

def test_record_is_frozen():
    from verification_record import VerificationRecord, VerificationSignal
    s = VerificationSignal(stage="x", verdict="pass", verifier_id="v1")
    r = VerificationRecord(memory_id="VM-1", signals=(s,), weight_version="v1")
    with pytest.raises(FrozenInstanceError):
        r.memory_id = "VM-2"


def test_record_signals_is_tuple():
    from verification_record import VerificationRecord, VerificationSignal
    s = VerificationSignal(stage="x", verdict="pass", verifier_id="v1")
    r = VerificationRecord(memory_id="VM-1", signals=(s,), weight_version="v1")
    assert isinstance(r.signals, tuple)


def test_record_to_dict_and_back():
    from verification_record import VerificationRecord, VerificationSignal
    s = VerificationSignal(stage="cycle_consistency", verdict="pass",
                           verifier_id="v1", evidence_hash="abc", latency_ms=12.5)
    r = VerificationRecord(memory_id="VM-1", signals=(s,), weight_version="v1")
    d = r.to_dict()
    r2 = VerificationRecord.from_dict(d)
    assert r2.memory_id == "VM-1"
    assert r2.signals[0].stage == "cycle_consistency"
    assert r2.signals[0].verdict == "pass"
    assert r2.weight_version == "v1"


# ---------------------------------------------------------------------------
# 聚合 p 计算
# ---------------------------------------------------------------------------

def test_compute_p_all_pass():
    from verification_record import VerificationSignal, compute_aggregated_p
    signals = [
        VerificationSignal(stage="a", verdict="pass", verifier_id="v1"),
        VerificationSignal(stage="b", verdict="pass", verifier_id="v2"),
    ]
    p, n_active = compute_aggregated_p(signals)
    assert p == 1.0
    assert n_active == 2


def test_compute_p_mixed():
    from verification_record import VerificationSignal, compute_aggregated_p
    signals = [
        VerificationSignal(stage="a", verdict="pass", verifier_id="v1"),
        VerificationSignal(stage="b", verdict="fail", verifier_id="v2"),
        VerificationSignal(stage="c", verdict="pass", verifier_id="v3"),
    ]
    p, n_active = compute_aggregated_p(signals)
    assert abs(p - 2.0 / 3.0) < 1e-9
    assert n_active == 3


def test_compute_p_all_abstain_returns_none():
    from verification_record import VerificationSignal, compute_aggregated_p
    signals = [
        VerificationSignal(stage="a", verdict="abstain", verifier_id="v1"),
        VerificationSignal(stage="b", verdict="abstain", verifier_id="v2"),
    ]
    p, n_active = compute_aggregated_p(signals)
    assert p is None  # 全弃权 → 回退布尔路径
    assert n_active == 0


def test_compute_p_with_abstain():
    from verification_record import VerificationSignal, compute_aggregated_p
    signals = [
        VerificationSignal(stage="a", verdict="pass", verifier_id="v1"),
        VerificationSignal(stage="b", verdict="abstain", verifier_id="v2"),
        VerificationSignal(stage="c", verdict="fail", verifier_id="v3"),
    ]
    p, n_active = compute_aggregated_p(signals)
    assert abs(p - 0.5) < 1e-9  # 1 pass / 2 active
    assert n_active == 2


def test_compute_p_empty_returns_none():
    from verification_record import compute_aggregated_p
    p, n_active = compute_aggregated_p([])
    assert p is None
    assert n_active == 0


# ---------------------------------------------------------------------------
# 分数化 Δconf 计算
# ---------------------------------------------------------------------------

def test_delta_conf_formula():
    """Δconf = (p - conf) / 4"""
    from verification_record import compute_fractional_delta
    # p=1, conf=0.6 → (1-0.6)/4 = 0.1
    assert abs(compute_fractional_delta(p=1.0, conf=0.6) - 0.1) < 1e-9
    # p=0, conf=0.6 → (0-0.6)/4 = -0.15
    assert abs(compute_fractional_delta(p=0.0, conf=0.6) - (-0.15)) < 1e-9


def test_delta_conf_clipping():
    """clip 到 [-0.15, +0.10]"""
    from verification_record import compute_fractional_delta
    # p=1, conf=0.3 → (1-0.3)/4 = 0.175 → clip to 0.10
    assert abs(compute_fractional_delta(p=1.0, conf=0.3) - 0.10) < 1e-9
    # p=0, conf=0.3 → (0-0.3)/4 = -0.075 → no clip needed
    assert abs(compute_fractional_delta(p=0.0, conf=0.3) - (-0.075)) < 1e-9
    # p=0, conf=0.9 → (0-0.9)/4 = -0.225 → clip to -0.15
    assert abs(compute_fractional_delta(p=0.0, conf=0.9) - (-0.15)) < 1e-9


def test_delta_conf_no_clip_when_in_range():
    from verification_record import compute_fractional_delta
    # p=0.8, conf=0.4 → (0.8-0.4)/4 = 0.1 → within range
    assert abs(compute_fractional_delta(p=0.8, conf=0.4) - 0.1) < 1e-9


# ---------------------------------------------------------------------------
# VerificationOutcome (verify 聚合结果)
# ---------------------------------------------------------------------------

def test_outcome_boolean_path():
    from verification_record import VerificationOutcome
    o = VerificationOutcome(
        memory_id="VM-1",
        path="boolean",
        success=True,
        old_confidence=0.3,
        new_confidence=0.4,
        old_quality="C",
        new_quality="B",
    )
    assert o.path == "boolean"
    assert o.p is None
    assert o.n_active == 0


def test_outcome_fractional_path():
    from verification_record import VerificationOutcome
    o = VerificationOutcome(
        memory_id="VM-1",
        path="fractional",
        success=None,
        p=0.667,
        n_active=3,
        old_confidence=0.3,
        new_confidence=0.4,
        old_quality="C",
        new_quality="B",
    )
    assert o.path == "fractional"
    assert abs(o.p - 0.667) < 1e-3
    assert o.n_active == 3


def test_outcome_fail_gate():
    """有 fail 时 gate=blocked，不升级"""
    from verification_record import VerificationOutcome
    o = VerificationOutcome(
        memory_id="VM-1",
        path="fractional",
        p=0.5,
        n_active=2,
        has_fail=True,
        gate="blocked",
        old_confidence=0.5,
        new_confidence=0.5,  # 不变
        old_quality="B",
        new_quality="B",
    )
    assert o.gate == "blocked"
    assert o.has_fail is True
    assert o.new_confidence == o.old_confidence  # 不升级


# ---------------------------------------------------------------------------
# quorum 判定
# ---------------------------------------------------------------------------

def test_quorum_all_pass_meets():
    from verification_record import resolve_quorum
    signals_verdicts = ["pass", "pass", "pass"]
    result = resolve_quorum(signals_verdicts, min_quorum=1)
    assert result["gate"] == "pass"
    assert result["p"] == 1.0


def test_quorum_has_fail_blocked():
    from verification_record import resolve_quorum
    signals_verdicts = ["pass", "fail", "pass"]
    result = resolve_quorum(signals_verdicts, min_quorum=1)
    assert result["gate"] == "blocked"
    assert result["has_fail"] is True


def test_quorum_all_abstain_fallback():
    from verification_record import resolve_quorum
    signals_verdicts = ["abstain", "abstain"]
    result = resolve_quorum(signals_verdicts, min_quorum=1)
    assert result["gate"] == "fallback"  # 回退布尔路径
    assert result["p"] is None


def test_quorum_below_min_quorum():
    from verification_record import resolve_quorum
    # 1 pass but min_quorum=2 → blocked（生效票不足）
    signals_verdicts = ["pass", "abstain", "abstain"]
    result = resolve_quorum(signals_verdicts, min_quorum=2)
    assert result["gate"] == "blocked"
    assert result["n_active"] == 1
