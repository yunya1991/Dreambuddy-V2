"""TB3 AlphaPareto 六维奖励 TDD 用例 — SPEC-L0-AGENT-TRAIN-BASE v0.1 §3

RED 1-6 对应 SPEC §3.4。
"""

import pytest
from cognitive_interfaces import BetaState
from training_reward import REWARD_WEIGHTS, compute_reward, pareto_score


def _beta_with_mean(mean: float) -> BetaState:
    """构造均值指定、伪计数总量=1 的 Beta 状态。"""
    return BetaState(alpha=mean, beta=1.0 - mean)


# RED 1: 理想情况（六维均好）→ pareto_score ≥ 0.9
def test_red1_ideal_case():
    reward = compute_reward(
        beta_state=_beta_with_mean(0.9),
        psi_value=0.05,
        recall_hits=10,
        recall_total=10,
        known_gaps_count=0,
        cross_domain_refs=5,
    )
    assert reward.p_verify_success == pytest.approx(0.9)
    assert reward.p_recall_hit == pytest.approx(1.0)
    assert reward.psi_stability == pytest.approx(0.95)
    assert pareto_score(reward) >= 0.9


# RED 2: 差情况（六维均差，含过程奖励/转移平滑度取最差）→ pareto_score ≤ 0.3
def test_red2_worst_case():
    reward = compute_reward(
        beta_state=_beta_with_mean(0.3),
        psi_value=0.5,
        recall_hits=2,
        recall_total=10,
        known_gaps_count=5,
        cross_domain_refs=0,
        process_reward=0.0,
        transition_smoothness=0.0,
    )
    assert pareto_score(reward) <= 0.3


# RED 3: PSI > 1.0 边界 → psi_stability = 0.0（cap 生效）
def test_red3_psi_cap():
    reward = compute_reward(
        beta_state=_beta_with_mean(0.5),
        psi_value=1.5,
        recall_hits=0,
        recall_total=10,
        known_gaps_count=0,
        cross_domain_refs=0,
    )
    assert reward.psi_stability == 0.0


# RED 4: known_gaps > 10 边界 → citation_diversity 下限 0.0（cap 生效）
def test_red4_known_gaps_cap():
    reward = compute_reward(
        beta_state=_beta_with_mean(0.5),
        psi_value=0.1,
        recall_hits=0,
        recall_total=10,
        known_gaps_count=15,
        cross_domain_refs=0,
    )
    assert reward.citation_diversity == 0.0


# RED 5: recall_total=0 边界 → p_recall_hit = 0.0（除零保护）
def test_red5_recall_total_zero():
    reward = compute_reward(
        beta_state=_beta_with_mean(0.5),
        psi_value=0.1,
        recall_hits=0,
        recall_total=0,
        known_gaps_count=0,
        cross_domain_refs=0,
    )
    assert reward.p_recall_hit == 0.0


# RED 6: 权重完整性 — 六维且和为 1.0
def test_red6_reward_weights_integrity():
    assert len(REWARD_WEIGHTS) == 6
    assert sum(REWARD_WEIGHTS) == pytest.approx(1.0, abs=1e-9)
