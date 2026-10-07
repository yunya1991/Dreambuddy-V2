"""TDD-CV-003: head_multipliers 收敛性验证（r=0.15，约 18-20 期回归 [0.95, 1.05]）.

理论：OU 离散过程 m_{n+1} = m_n + (1 - m_n) * r
  收敛公式: m_n = 1 + (m_0 - 1) * (1 - r)^n
  r=0.15 时: (0.85)^18 ≈ 0.0536, (0.85)^20 ≈ 0.0388
  → 从 m=2.0 出发，20 期后 |m - 1.0| < 0.05
"""
import pytest


def test_mean_reversion_from_ceiling():
    """从 ceiling=2.0 回归，20 期后进入 [0.95, 1.05]。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

    gate = CrossValidationGate(
        enable_head_multipliers_mean_reversion=True,
        head_reversion_rate=0.15,
    )
    gate._head_multipliers = {0: 2.0}
    for _ in range(20):
        gate._revert_head_multipliers_to_mean()
    m = gate._head_multipliers[0]
    assert abs(m - 1.0) < 0.05, f"20 期后 m={m:.4f}, 应在 [0.95, 1.05]"


def test_mean_reversion_from_floor():
    """从 floor=0.1 回归，20 期后进入 [0.95, 1.05]。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

    gate = CrossValidationGate(
        enable_head_multipliers_mean_reversion=True,
        head_reversion_rate=0.15,
    )
    gate._head_multipliers = {0: 0.1}
    for _ in range(20):
        gate._revert_head_multipliers_to_mean()
    m = gate._head_multipliers[0]
    assert abs(m - 1.0) < 0.05, f"20 期后 m={m:.4f}, 应在 [0.95, 1.05]"


def test_mean_reversion_18_periods_approx():
    """约 18 期接近 5% 容差（文档声称 ~18 期，实际 18 期 ≈ 1.0536）。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

    gate = CrossValidationGate(
        enable_head_multipliers_mean_reversion=True,
        head_reversion_rate=0.15,
    )
    gate._head_multipliers = {0: 2.0}
    for _ in range(18):
        gate._revert_head_multipliers_to_mean()
    m = gate._head_multipliers[0]
    # 18 期时约 1.0536，略超 5%，但 < 6%
    assert abs(m - 1.0) < 0.06, f"18 期后 m={m:.4f}"


def test_head_adjustment_respects_floor_ceiling():
    """head_adjustment 受 floor/ceiling 约束。"""
    from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

    gate = CrossValidationGate(
        persistence_threshold=1,
        head_boost_rate=5.0,  # 极端 boost 触发 ceiling
        head_decay_rate=5.0,  # 极端 decay 触发 floor
        head_floor=0.1,
        head_ceiling=2.0,
    )
    r = gate.compare(
        G_dim="fundamental", G_conf=0.9,
        A_dim="macro", A_strength=0.7,
        structural_break={},
    )
    for h, v in r["head_adjustment"].items():
        assert 0.1 <= v <= 2.0, f"head {h} 的 multiplier={v} 超出 [0.1, 2.0]"
