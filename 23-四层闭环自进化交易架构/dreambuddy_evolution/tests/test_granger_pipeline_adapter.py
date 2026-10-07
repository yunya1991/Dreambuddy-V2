"""TDD-CV-002b: GrangerPipelineAdapter — 包装 GrangerCausalityChecker 输出 G_dim.

设计依据：融合方案 §10.2 + §8.9
输入: 按 3 维度分组的因子序列 + 收益率
输出: G_dim ∈ {technical, fundamental, macro, none}, G_confidence ∈ [0,1]
"""
import numpy as np
import pytest


def test_module_importable():
    """GrangerPipelineAdapter 可导入。"""
    from dreambuddy_evolution.core.granger_pipeline_adapter import GrangerPipelineAdapter
    assert GrangerPipelineAdapter is not None


def test_evaluate_returns_g_dim():
    """evaluate 返回 G_dim ∈ {technical, fundamental, macro, None}。"""
    from dreambuddy_evolution.core.granger_pipeline_adapter import GrangerPipelineAdapter

    rng = np.random.RandomState(42)
    n = 120
    returns = rng.randn(n) * 0.01
    # technical 因子与收益有因果关系（滞后一期）
    tech_factor = np.zeros(n)
    tech_factor[1:] = returns[:-1] * 0.8 + rng.randn(n - 1) * 0.001
    factors_by_dim = {
        "technical": tech_factor,
        "fundamental": rng.randn(n) * 0.01,
        "macro": rng.randn(n) * 0.01,
    }
    adapter = GrangerPipelineAdapter()
    result = adapter.evaluate(factors_by_dim, returns)
    assert result["G_dim"] in (None, "technical", "fundamental", "macro")
    assert 0.0 <= result["G_confidence"] <= 1.0


def test_granger_cause_detected():
    """当某维度因子 Granger-cause 收益时，G_dim 为该维度。"""
    from dreambuddy_evolution.core.granger_pipeline_adapter import GrangerPipelineAdapter

    rng = np.random.RandomState(123)
    n = 200
    returns = np.zeros(n)
    returns[0] = rng.randn() * 0.01
    macro_factor = rng.randn(n) * 0.02
    # macro_factor 滞后 2 期驱动收益
    for i in range(2, n):
        returns[i] = macro_factor[i - 2] * 0.5 + rng.randn() * 0.005
    factors_by_dim = {
        "technical": rng.randn(n) * 0.01,
        "fundamental": rng.randn(n) * 0.01,
        "macro": macro_factor,
    }
    adapter = GrangerPipelineAdapter()
    result = adapter.evaluate(factors_by_dim, returns)
    assert result["G_dim"] == "macro"
    assert result["G_confidence"] > 0.5


def test_no_cause_returns_none():
    """无显著因果时 G_dim=None。"""
    from dreambuddy_evolution.core.granger_pipeline_adapter import GrangerPipelineAdapter

    rng = np.random.RandomState(999)
    n = 100
    factors_by_dim = {
        "technical": rng.randn(n),
        "fundamental": rng.randn(n),
        "macro": rng.randn(n),
    }
    returns = rng.randn(n)
    adapter = GrangerPipelineAdapter()
    result = adapter.evaluate(factors_by_dim, returns)
    # 纯随机数据无因果，G_dim 应为 None 或低置信
    if result["G_dim"] is not None:
        assert result["G_confidence"] < 0.5


def test_insufficient_data_returns_none():
    """数据不足时返回 None。"""
    from dreambuddy_evolution.core.granger_pipeline_adapter import GrangerPipelineAdapter

    factors_by_dim = {"technical": np.array([1.0, 2.0, 3.0])}
    returns = np.array([0.01, -0.02, 0.01])
    adapter = GrangerPipelineAdapter()
    result = adapter.evaluate(factors_by_dim, returns)
    assert result["G_dim"] is None
    assert result["G_confidence"] == 0.0
