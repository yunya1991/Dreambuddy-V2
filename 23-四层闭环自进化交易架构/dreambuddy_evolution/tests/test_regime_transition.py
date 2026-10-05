"""RED 测试: P0.2 regime-transition 建模 (NeuralSDE OOS 泛化修复).

背景:
  T7 walk-forward 2024 OOS 失败 (MAE=1707 vs GARCH=929, ratio=2.80).
  根因 3: regime 标签同质化 — 2024 "bull" 实际是 ATH 后反弹/下跌中的伪 bull,
  与训练集 bull (2017-2021 上涨 bull) 动态不同. regime one-hot 无法区分.

  解决: 不仅用 regime label, 还建模 regime 切换动态 (Markov transition matrix Q).
  - Q[i,j] = P(regime j at t+1 | regime i at t)
  - 平稳分布 π = 解 πQ = π
  - regime 不确定性 = 预测熵 H(Q[current])

TDD 覆盖:
  P0.2-T1.1 estimate_transition_matrix 存在且返回方阵
  P0.2-T1.2 Q 每行和为 1 (概率分布)
  P0.2-T1.3 Q[i,j] = count(i→j) / count(i) 正确性
  P0.2-T1.4 单 regime 序列 Q 退化为单位阵
  P0.2-T1.5 短序列 (<2) 返回单位阵兜底
  P0.2-T2.1 stationary_distribution 返回长度 n_regimes 的向量
  P0.2-T2.2 平稳分布 πQ = π
  P0.2-T2.3 平稳分布元素非负且和为 1
  P0.2-T2.4 regime_uncertainty 高 = 切换频繁 (熵大)
  P0.2-T2.5 regime_uncertainty 低 = 稳定 (熵小)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ============================================================================
# P0.2-T1: estimate_transition_matrix
# ============================================================================


def test_estimate_transition_matrix_exists():
    """P0.2-T1.1: BTCRegimeDetector.estimate_transition_matrix 存在且返回方阵."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    labels = np.array([0, 0, 1, 1, 2, 2])
    Q = detector.estimate_transition_matrix(labels)
    assert Q.shape == (3, 3), f"Q shape 应为 (3,3), 实际 {Q.shape}"
    assert isinstance(Q, np.ndarray)


def test_transition_matrix_rows_sum_to_one():
    """P0.2-T1.2: Q 每行和为 1 (概率分布), 元素非负."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    labels = np.array([0, 0, 1, 2, 0, 1, 2, 0])
    Q = detector.estimate_transition_matrix(labels)
    row_sums = Q.sum(axis=1)
    np.testing.assert_allclose(row_sums, 1.0, atol=1e-10, err_msg="每行和应为 1")
    assert np.all(Q >= 0), "所有元素应非负"


def test_transition_matrix_correctness():
    """P0.2-T1.3: Q[i,j] = count(i→j) / count(i) 正确性验证.

    构造序列: 0→0→1→2→0→1
    转移: 0→0, 0→1, 1→2, 2→0, 0→1
    从 0 出发 3 次: 0→0 (1次), 0→1 (2次), 0→2 (0次)
    从 1 出发 1 次: 1→2 (1次)
    从 2 出发 1 次: 2→0 (1次)
    Q = [[1/3, 2/3, 0],
         [0,   0,   1],
         [1,   0,   0]]
    """
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    labels = np.array([0, 0, 1, 2, 0, 1])
    Q = detector.estimate_transition_matrix(labels)

    expected = np.array([
        [1/3, 2/3, 0.0],
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
    ])
    np.testing.assert_allclose(Q, expected, atol=1e-10)


def test_transition_matrix_single_regime():
    """P0.2-T1.4: 单 regime 序列 Q 退化为单位阵."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    labels = np.array([0, 0, 0, 0])
    Q = detector.estimate_transition_matrix(labels)
    # 从 0 出发只能到 0
    np.testing.assert_allclose(Q[0], [1.0, 0.0, 0.0], atol=1e-10)
    # 无数据的 regime 行: 兜底为单位阵 (FAIL-OPEN)
    np.testing.assert_allclose(Q[1], [0.0, 1.0, 0.0], atol=1e-10)
    np.testing.assert_allclose(Q[2], [0.0, 0.0, 1.0], atol=1e-10)


def test_transition_matrix_short_sequence():
    """P0.2-T1.5: 短序列 (<2) 返回单位阵兜底 (FAIL-OPEN)."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    labels = np.array([0])
    Q = detector.estimate_transition_matrix(labels)
    np.testing.assert_allclose(Q, np.eye(3), atol=1e-10)


# ============================================================================
# P0.2-T2: stationary_distribution + regime_uncertainty
# ============================================================================


def test_stationary_distribution_shape():
    """P0.2-T2.1: stationary_distribution 返回长度 n_regimes 的向量."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    Q = np.array([
        [0.7, 0.2, 0.1],
        [0.3, 0.5, 0.2],
        [0.1, 0.3, 0.6],
    ])
    pi = detector.stationary_distribution(Q)
    assert pi.shape == (3,), f"pi shape 应为 (3,), 实际 {pi.shape}"


def test_stationary_distribution_satisfies_piQ_eq_pi():
    """P0.2-T2.2: 平稳分布满足 πQ = π."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    Q = np.array([
        [0.7, 0.2, 0.1],
        [0.3, 0.5, 0.2],
        [0.1, 0.3, 0.6],
    ])
    pi = detector.stationary_distribution(Q)
    # πQ = π
    np.testing.assert_allclose(pi @ Q, pi, atol=1e-8)


def test_stationary_distribution_valid_probability():
    """P0.2-T2.3: 平稳分布元素非负且和为 1."""
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    Q = np.array([
        [0.5, 0.3, 0.2],
        [0.2, 0.6, 0.2],
        [0.1, 0.2, 0.7],
    ])
    pi = detector.stationary_distribution(Q)
    assert np.all(pi >= -1e-10), "pi 元素应非负"
    np.testing.assert_allclose(pi.sum(), 1.0, atol=1e-8)


def test_regime_uncertainty_high_for_unstable():
    """P0.2-T2.4: regime 不确定性高 = 切换频繁 (熵大).

    均匀转移 [1/3, 1/3, 1/3] → 熵最大 = log(3) ≈ 1.0986
    """
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    Q_uniform = np.array([
        [1/3, 1/3, 1/3],
        [1/3, 1/3, 1/3],
        [1/3, 1/3, 1/3],
    ])
    entropy = detector.regime_uncertainty(Q_uniform, current_regime=0)
    expected_max = np.log(3)
    np.testing.assert_allclose(entropy, expected_max, atol=1e-8)


def test_regime_uncertainty_low_for_stable():
    """P0.2-T2.5: regime 不确定性低 = 稳定 (熵小).

    自转移 [0.95, 0.03, 0.02] → 熵接近 0
    """
    from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector()
    Q_stable = np.array([
        [0.95, 0.03, 0.02],
        [0.1, 0.85, 0.05],
        [0.05, 0.1, 0.85],
    ])
    entropy = detector.regime_uncertainty(Q_stable, current_regime=0)
    # 熵应远小于最大熵 log(3) ≈ 1.0986
    assert entropy < 0.3, f"稳定 regime 熵应 < 0.3, 实际 {entropy}"
