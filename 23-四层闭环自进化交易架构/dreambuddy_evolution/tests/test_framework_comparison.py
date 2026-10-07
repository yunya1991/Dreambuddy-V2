"""TDD-CV-004: 5 框架配对 walk-forward 对比验证.

5 个框架:
  F1: v0.7 交叉验证（Granger + Attention + CrossValidationGate）
  F2: 纯 Attention + Bayesian 后验
  F3: 互信息 + 动态权重
  F4: Shapley 值归因
  F5: 单 Granger 因果链

指标: 样本外夏普 / DSR / PBO + Holm-Bonferroni 配对校正
"""
import numpy as np
import pytest


def test_module_importable():
    """FrameworkComparison 可导入。"""
    from dreambuddy_evolution.core.framework_comparison import FrameworkComparison
    assert FrameworkComparison is not None


def test_factor_matrix_shape():
    """价格衍生因子矩阵形状正确。"""
    from dreambuddy_evolution.core.framework_comparison import FrameworkComparison

    prices = np.array([100.0, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110])
    fc = FrameworkComparison(prices)
    factors = fc.build_factors()
    assert factors.ndim == 2
    assert factors.shape[0] == len(prices)
    assert factors.shape[1] >= 5  # 至少 5 个因子


def test_all_frameworks_produce_signals():
    """5 个框架都能产生 -1/0/1 信号。"""
    from dreambuddy_evolution.core.framework_comparison import FrameworkComparison

    rng = np.random.RandomState(42)
    prices = 100 + np.cumsum(rng.randn(500))
    fc = FrameworkComparison(prices)
    signals = fc.generate_all_signals()
    assert len(signals) == 5
    for name, sig in signals.items():
        assert sig.shape[0] == len(prices)
        assert set(np.unique(sig)).issubset({-1.0, 0.0, 1.0})


def test_sharpe_ratio_range():
    """夏普比率在合理范围。"""
    from dreambuddy_evolution.core.framework_comparison import FrameworkComparison

    rng = np.random.RandomState(42)
    prices = 100 + np.cumsum(rng.randn(500))
    fc = FrameworkComparison(prices)
    returns = np.diff(prices) / prices[:-1]
    signals = fc.generate_all_signals()
    for name, sig in signals.items():
        sr = fc.sharpe_ratio(sig[:-1] * returns)
        assert np.isfinite(sr)


def test_walk_forward_returns_dict():
    """walk-forward 返回包含各框架指标的 dict。"""
    from dreambuddy_evolution.core.framework_comparison import FrameworkComparison

    rng = np.random.RandomState(42)
    prices = 100 + np.cumsum(rng.randn(1000))
    fc = FrameworkComparison(prices)
    result = fc.walk_forward(n_folds=3, train_ratio=0.7)
    assert "F1_cross_validation" in result
    assert "oos_sharpe" in result["F1_cross_validation"]
    assert "dsr" in result["F1_cross_validation"]


def test_holm_bonferroni():
    """Holm-Bonferroni 校正返回每个配对的校正 p 值。"""
    from dreambuddy_evolution.core.framework_comparison import holm_bonferroni

    pvals = {"F1_vs_F2": 0.01, "F1_vs_F3": 0.04, "F1_vs_F4": 0.2, "F1_vs_F5": 0.001}
    adjusted = holm_bonferroni(pvals)
    assert len(adjusted) == len(pvals)
    # 校正后 p 值 >= 原始 p 值
    for k in pvals:
        assert adjusted[k] >= pvals[k]
    # 最小的 p 值校正后仍显著
    assert adjusted["F1_vs_F5"] < 0.05


def test_pbo_between_0_1():
    """PBO ∈ [0, 1]。"""
    from dreambuddy_evolution.core.framework_comparison import FrameworkComparison

    rng = np.random.RandomState(42)
    prices = 100 + np.cumsum(rng.randn(800))
    fc = FrameworkComparison(prices)
    signals = fc.generate_all_signals()
    returns = np.diff(prices) / prices[:-1]
    pbo = fc.probability_of_backtest_overfitting(signals, returns, n_splits=5)
    assert 0.0 <= pbo <= 1.0
