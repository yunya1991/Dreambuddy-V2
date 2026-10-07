"""TDD-CV-001: AttentionAggregator — head-weight 求和聚合输出 A_dim.

RED 阶段断言：
- collapse() 返回 dict，包含 A_dim ∈ {technical, fundamental, macro}
- A_strength ∈ [0, 1]
- dim_strengths 的 3 个 key 归一化后 sum ≈ 1.0
- 最大维度 = A_dim
"""
import torch
import pytest


def test_module_importable():
    """AttentionAggregator 模块可导入（RED: ModuleNotFoundError）。"""
    from dreambuddy_evolution.core.attention_aggregator import AttentionAggregator
    assert AttentionAggregator is not None


def test_collapse_returns_3dim():
    """collapse 输出 A_dim ∈ {technical, fundamental, macro}。"""
    from dreambuddy_evolution.core.attention_aggregator import AttentionAggregator

    agg = AttentionAggregator()
    # 8 heads × 36 factors, head 0 (C1→fundamental) 权重最高
    attn = torch.zeros(1, 8, 1, 36)
    attn[0, 0, 0, :7] = 1.0 / 7  # C1 7 个因子
    result = agg.collapse(attn)
    assert result["A_dim"] in ("technical", "fundamental", "macro")
    assert result["A_dim"] == "fundamental"


def test_a_strength_in_range():
    """A_strength ∈ [0, 1]。"""
    from dreambuddy_evolution.core.attention_aggregator import AttentionAggregator

    agg = AttentionAggregator()
    attn = torch.zeros(1, 8, 1, 36)
    attn[0, 3, 0, 21:27] = 1.0 / 6  # C4 (macro)
    result = agg.collapse(attn)
    assert 0.0 <= result["A_strength"] <= 1.0


def test_dim_strengths_normalized():
    """dim_strengths 三 key 归一化后 sum ≈ 1.0。"""
    from dreambuddy_evolution.core.attention_aggregator import AttentionAggregator

    agg = AttentionAggregator()
    attn = torch.rand(1, 8, 1, 36)
    result = agg.collapse(attn)
    total = sum(result["dim_strengths"].values())
    assert abs(total - 1.0) < 1e-5


def test_max_dim_is_a_dim():
    """A_dim 对应 dim_strengths 中值最大的维度。"""
    from dreambuddy_evolution.core.attention_aggregator import AttentionAggregator

    agg = AttentionAggregator()
    attn = torch.zeros(1, 8, 1, 36)
    # C8 (macro, head 6) 权重最高
    attn[0, 6, 0, 33:36] = 1.0 / 3
    result = agg.collapse(attn)
    assert result["A_dim"] == max(result["dim_strengths"], key=result["dim_strengths"].get)


def test_technical_dim_from_c2():
    """C2 (head 1) → technical。"""
    from dreambuddy_evolution.core.attention_aggregator import AttentionAggregator

    agg = AttentionAggregator()
    attn = torch.zeros(1, 8, 1, 36)
    attn[0, 1, 0, 7:12] = 1.0 / 5  # C2 5 个因子
    result = agg.collapse(attn)
    assert result["A_dim"] == "technical"
