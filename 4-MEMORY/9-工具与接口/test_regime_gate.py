"""TB4 Thompson Sampling regime gate TDD 用例 — SPEC-L0-AGENT-TRAIN-BASE v0.1 §4

RED 1-4 对应 SPEC §4.4。随机过程显式 seed 保证可复现。
"""

import random

import pytest
from regime_gate import REGIME_ARMS, ThompsonSamplingRegimeGate
from scipy import stats


# RED 1: 初始 Beta(1,1) → 四 arm 被选中概率 ≈ 0.25（卡方检验 p > 0.05）
def test_red1_initial_unbiased():
    random.seed(42)
    gate = ThompsonSamplingRegimeGate()
    counts = dict.fromkeys(REGIME_ARMS, 0)
    for _ in range(1000):
        counts[gate.select_regime()] += 1
    _, p_value = stats.chisquare(list(counts.values()))
    assert p_value > 0.05


# RED 2: "risk" 连续 10 次成功 → Beta(11,1) → 选中概率 > 0.75
# 数学上限：Beta(11,1) 采样超过 3 个 Beta(1,1) 的期望 = 11/(11+3) ≈ 0.786
def test_red2_convergence_after_successes():
    random.seed(7)
    gate = ThompsonSamplingRegimeGate()
    for _ in range(10):
        gate.update("risk", 1.0)
    assert gate.alpha["risk"] == pytest.approx(11.0)
    assert gate.beta["risk"] == pytest.approx(1.0)

    hits = sum(gate.select_regime() == "risk" for _ in range(1000))
    assert hits / 1000 > 0.75


# RED 3: drift_detected=True → 所有 arm 重置为 Beta(1,1)
def test_red3_drift_resets_all_arms():
    gate = ThompsonSamplingRegimeGate()
    gate.update("risk", 1.0)
    gate.update("bond", 0.0)
    assert gate.alpha["risk"] == pytest.approx(2.0)

    gate.update("risk", 1.0, drift_detected=True)
    for arm in REGIME_ARMS:
        assert gate.alpha[arm] == pytest.approx(1.0)
        assert gate.beta[arm] == pytest.approx(1.0)


# RED 4: 先 1 次全成功得 Beta(2,1)，再 success_rate=0.5 → Beta(2.5,1.5) → 0.625
def test_red4_partial_success_update():
    gate = ThompsonSamplingRegimeGate()
    gate.update("risk", 1.0)
    gate.update("risk", 0.5)
    assert gate.alpha["risk"] == pytest.approx(2.5)
    assert gate.beta["risk"] == pytest.approx(1.5)
    assert gate.get_confidence("risk") == pytest.approx(0.625)
