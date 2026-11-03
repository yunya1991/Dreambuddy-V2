"""TB1 drift_detector TDD 用例 — SPEC-L0-AGENT-TRAIN-BASE v0.1 §1（12 条）"""

import numpy as np
import pytest
from drift_detector import (
    KILL_SWITCH_TIERS,
    KS_ALPHA,
    PSI_MINOR_DRIFT,
    PSI_STABLE,
    DriftKillSwitchState,
    classify_drift,
    classify_drift_triple,
    compute_psi,
    drift_kill_switch,
    ks_test_drift,
)


# 1-3: classify_drift 三档分类（含边界 epsilon）
def test_classify_drift_stable():
    assert classify_drift(0.0) == "stable"
    assert classify_drift(0.05) == "stable"
    assert classify_drift(0.099999999) == "stable"


def test_classify_drift_minor():
    assert classify_drift(0.1) == "minor_drift"
    assert classify_drift(0.15) == "minor_drift"
    assert classify_drift(0.249999999) == "minor_drift"


def test_classify_drift_severe():
    assert classify_drift(0.25) == "severe_drift"
    assert classify_drift(0.5) == "severe_drift"
    assert classify_drift(1.0) == "severe_drift"


# 4: compute_psi 同分布接近 0；漂移分布显著增大
def test_compute_psi_same_vs_shifted():
    rng = np.random.default_rng(42)
    baseline = rng.normal(0.0, 1.0, 500)
    same = rng.normal(0.0, 1.0, 500)
    shifted = rng.normal(2.0, 1.0, 500)

    psi_same = compute_psi(baseline, same)
    psi_shifted = compute_psi(baseline, shifted)

    assert psi_same < PSI_STABLE
    assert psi_shifted > PSI_MINOR_DRIFT


def test_compute_psi_empty_raises():
    with pytest.raises(ValueError):
        compute_psi([], [1.0, 2.0])
    with pytest.raises(ValueError):
        compute_psi([1.0, 2.0], [])


# 5: ks_test_drift 同分布不检出 / 漂移分布检出
def test_ks_test_drift():
    rng = np.random.default_rng(7)
    baseline = rng.normal(0.0, 1.0, 300)
    same = rng.normal(0.0, 1.0, 300)
    shifted = rng.normal(3.0, 1.0, 300)

    detected_same, p_same = ks_test_drift(baseline, same)
    detected_shift, p_shift = ks_test_drift(baseline, shifted)

    assert detected_same is False
    assert detected_shift is True
    assert p_shift < KS_ALPHA


# 6-8: drift_kill_switch 分层升级（只升不降 + fail-closed）
def test_kill_switch_escalation_ladder():
    state = DriftKillSwitchState()

    # stable → Level 1 log_alert，不升档
    r1 = drift_kill_switch(0.05, state, trace_id="t1")
    assert r1["kill_switch"]["level"] == 1
    assert r1["kill_switch"]["action"] == "log_alert"
    assert state.current_tier is None

    # minor_drift → 升至第 1 档
    r2 = drift_kill_switch(0.15, state, trace_id="t2")
    assert r2["kill_switch"]["level"] == 2
    assert state.current_tier == KILL_SWITCH_TIERS[0]

    # severe_drift → 升至第 2 档
    drift_kill_switch(0.30, state, trace_id="t3")
    assert state.current_tier == KILL_SWITCH_TIERS[1]

    # 回到 stable → 档位只升不降
    drift_kill_switch(0.05, state, trace_id="t4")
    assert state.current_tier == KILL_SWITCH_TIERS[1]


def test_kill_switch_fail_closed_unknown_level():
    state = DriftKillSwitchState()
    action = state.escalate("unknown_level", trace_id="t5")
    # fail-closed：未知等级直接最高档 halt_all
    assert state.current_tier == KILL_SWITCH_TIERS[-1]
    assert action["tier"] == KILL_SWITCH_TIERS[-1]


def test_kill_switch_alert_log_trace():
    state = DriftKillSwitchState()
    drift_kill_switch(0.15, state, trace_id="trace-abc")
    assert state.alert_log[-1]["trace_id"] == "trace-abc"
    assert len(state.alert_log) == 1


def test_classify_drift_triple_escalation():
    """RED 8：PSI + KS 融合，KS 命中升一档。"""
    assert classify_drift_triple(0.05, ks_drifted=False) == "stable"
    assert classify_drift_triple(0.05, ks_drifted=True) == "minor_drift"
    assert classify_drift_triple(0.15, ks_drifted=True) == "severe_drift"
    assert classify_drift_triple(0.30, ks_drifted=True) == "severe_drift"


def test_kill_switch_spec_mode_signature():
    """RED 9：SPEC 形态 drift_kill_switch(level, context)。"""
    out = drift_kill_switch(
        "severe_drift",
        context={"reason": "PSI=0.3, KS=p=0.001", "trace_id": "t1"},
    )
    assert out["action"] == "kill_switch"
    assert out["level"] == 2
    assert out["trace_id"] == "t1"
    assert drift_kill_switch("stable", {})["action"] == "no_op"


# 9: H8 阈值硬编码验证（无 env override 路径）
def test_h8_thresholds_hardcoded(monkeypatch):
    monkeypatch.setenv("PSI_STABLE", "0.9")
    monkeypatch.setenv("PSI_MINOR_DRIFT", "0.99")
    assert PSI_STABLE == 0.1
    assert PSI_MINOR_DRIFT == 0.25
    assert KS_ALPHA == 0.01
    assert classify_drift(0.15) == "minor_drift"
    assert classify_drift(0.3) == "severe_drift"
