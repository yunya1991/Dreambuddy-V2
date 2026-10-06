"""
C2 RED: Cross-Attention 外生注入组件测试

测试 FactorEncoder + MultiHeadCrossAttention 的核心能力：
  1. FactorEncoder: (B, N, factor_dim) → (B, N, d_model)
  2. MultiHeadCrossAttention: Q(price) × KV(factors) → context
  3. FAIL-OPEN: None/缺失输入时的行为

RED 阶段：cross_attention 模块尚不存在 → ModuleNotFoundError
"""
from __future__ import annotations

import pytest
import torch


class TestFactorEncoder:
    """测试因子编码器。"""

    def test_module_importable(self):
        from dreambuddy_evolution.core.cross_attention import FactorEncoder  # noqa: F401

    def test_encode_dimensions(self):
        """FactorEncoder 将 (B, N, factor_dim) 编码为 (B, N, d_model)。"""
        from dreambuddy_evolution.core.cross_attention import FactorEncoder

        B, N, factor_dim, d_model = 4, 5, 1, 32
        encoder = FactorEncoder(factor_dim=factor_dim, d_model=d_model)
        x = torch.randn(B, N, factor_dim)
        out = encoder(x)
        assert out.shape == (B, N, d_model)

    def test_different_n_factors(self):
        """FactorEncoder 支持可变因子数 N。"""
        from dreambuddy_evolution.core.cross_attention import FactorEncoder

        encoder = FactorEncoder(factor_dim=1, d_model=32)
        # N=3
        x3 = torch.randn(2, 3, 1)
        assert encoder(x3).shape == (2, 3, 32)
        # N=10
        x10 = torch.randn(2, 10, 1)
        assert encoder(x10).shape == (2, 10, 32)


class TestMultiHeadCrossAttention:
    """测试多头交叉注意力。"""

    def test_module_importable(self):
        from dreambuddy_evolution.core.cross_attention import MultiHeadCrossAttention  # noqa: F401

    def test_attention_output_shape(self):
        """Q(1, d) × KV(N, d) → context(1, d) → squeeze → (d,)。"""
        from dreambuddy_evolution.core.cross_attention import MultiHeadCrossAttention

        B, N, d_model = 4, 5, 32
        attn = MultiHeadCrossAttention(d_model=d_model, n_heads=4)
        query = torch.randn(B, 1, d_model)  # price as query
        key = torch.randn(B, N, d_model)    # factors as key
        value = torch.randn(B, N, d_model)  # factors as value
        out = attn(query, key, value)
        assert out.shape == (B, d_model)

    def test_attention_weights_sum_to_one(self):
        """注意力权重每行和为 1（softmax 归一化）。"""
        from dreambuddy_evolution.core.cross_attention import MultiHeadCrossAttention

        B, N, d_model = 2, 6, 32
        attn = MultiHeadCrossAttention(d_model=d_model, n_heads=4)
        query = torch.randn(B, 1, d_model)
        key = torch.randn(B, N, d_model)
        value = torch.randn(B, N, d_model)

        # 手动计算注意力权重验证
        q = attn.q_proj(query)
        k = attn.k_proj(key)
        v = attn.v_proj(value)

        # reshape for multi-head
        n_heads = 4
        head_dim = d_model // n_heads
        q = q.view(B, 1, n_heads, head_dim).transpose(1, 2)
        k = k.view(B, N, n_heads, head_dim).transpose(1, 2)
        v = v.view(B, N, n_heads, head_dim).transpose(1, 2)

        scores = torch.matmul(q, k.transpose(-2, -1)) / (head_dim ** 0.5)
        weights = torch.softmax(scores, dim=-1)
        # 每行权重和应为 1
        assert torch.allclose(weights.sum(dim=-1), torch.ones_like(weights.sum(dim=-1)), atol=1e-5)

    def test_different_n_factors(self):
        """注意力支持可变因子数 N。"""
        from dreambuddy_evolution.core.cross_attention import MultiHeadCrossAttention

        B, d_model = 4, 32
        attn = MultiHeadCrossAttention(d_model=d_model, n_heads=4)
        query = torch.randn(B, 1, d_model)
        # N=3
        key3 = torch.randn(B, 3, d_model)
        val3 = torch.randn(B, 3, d_model)
        assert attn(query, key3, val3).shape == (B, d_model)
        # N=10
        key10 = torch.randn(B, 10, d_model)
        val10 = torch.randn(B, 10, d_model)
        assert attn(query, key10, val10).shape == (B, d_model)

    def test_fail_open_single_factor(self):
        """FAIL-OPEN: 只有 1 个因子时也能正常工作（退化为直接投影）。"""
        from dreambuddy_evolution.core.cross_attention import MultiHeadCrossAttention

        B, d_model = 4, 32
        attn = MultiHeadCrossAttention(d_model=d_model, n_heads=4)
        query = torch.randn(B, 1, d_model)
        key = torch.randn(B, 1, d_model)
        value = torch.randn(B, 1, d_model)
        out = attn(query, key, value)
        assert out.shape == (B, d_model)
        assert not torch.isnan(out).any()


class TestCrossAttentionIntegration:
    """测试 FactorEncoder + MultiHeadCrossAttention 端到端集成。"""

    def test_end_to_end(self):
        """价格 Q + 因子 KV → context vector。"""
        from dreambuddy_evolution.core.cross_attention import (
            FactorEncoder,
            MultiHeadCrossAttention,
        )

        B, N, factor_dim, d_model = 8, 10, 1, 32
        encoder = FactorEncoder(factor_dim=factor_dim, d_model=d_model)
        attn = MultiHeadCrossAttention(d_model=d_model, n_heads=4)

        # 价格 signature → Q
        log_sig = torch.randn(B, 15)  # signature dim
        q_proj = torch.nn.Linear(15, d_model)
        query = q_proj(log_sig).unsqueeze(1)  # (B, 1, d_model)

        # 因子 → K, V
        factors = torch.randn(B, N, factor_dim)
        kv = encoder(factors)  # (B, N, d_model)

        # Cross-attention
        context = attn(query, kv, kv)  # (B, d_model)
        assert context.shape == (B, d_model)
        assert not torch.isnan(context).any()

    def test_none_factors_fail_open(self):
        """FAIL-OPEN: factors=None 时 context 应为零向量。"""
        from dreambuddy_evolution.core.cross_attention import (
            FactorEncoder,
            MultiHeadCrossAttention,
        )

        B, d_model = 4, 32
        attn = MultiHeadCrossAttention(d_model=d_model, n_heads=4)
        query = torch.randn(B, 1, d_model)

        # None factors → 零 context
        context = attn(query, None, None)
        assert context.shape == (B, d_model)
        assert torch.allclose(context, torch.zeros(B, d_model), atol=1e-6)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestFactorHeadMask:
    """测试维度对齐 mask：每个 head 只看所属维度因子。"""

    def test_masked_factors_get_zero_attention(self):
        """被 mask 屏蔽的因子，其 attention weight 应为 0。"""
        from dreambuddy_evolution.core.cross_attention import MultiHeadCrossAttention

        B, N, d_model, n_heads = 2, 6, 32, 2
        attn = MultiHeadCrossAttention(d_model=d_model, n_heads=n_heads)

        # mask: head 0 只看因子 0-2, head 1 只看因子 3-5
        mask = torch.full((n_heads, N), float("-inf"))
        mask[0, :3] = 0.0
        mask[1, 3:] = 0.0

        query = torch.randn(B, 1, d_model)
        key = torch.randn(B, N, d_model)
        value = torch.randn(B, N, d_model)

        out = attn(query, key, value, factor_head_mask=mask)
        assert out.shape == (B, d_model)

        # 检查 attention weights: 被屏蔽的因子权重应为 0
        weights = attn.last_attn_weights  # (B, n_heads, 1, N)
        assert weights is not None
        # head 0: 因子 3-5 权重应为 0
        assert torch.allclose(weights[:, 0, 0, 3:], torch.zeros_like(weights[:, 0, 0, 3:]), atol=1e-6)
        # head 1: 因子 0-2 权重应为 0
        assert torch.allclose(weights[:, 1, 0, :3], torch.zeros_like(weights[:, 1, 0, :3]), atol=1e-6)
        # 未屏蔽因子权重和应为 1
        assert torch.allclose(weights[:, 0, 0, :3].sum(dim=-1), torch.ones(B), atol=1e-5)
        assert torch.allclose(weights[:, 1, 0, 3:].sum(dim=-1), torch.ones(B), atol=1e-5)

    def test_mask_none_is_noop(self):
        """mask=None 时不做任何屏蔽，等价于无 mask。"""
        from dreambuddy_evolution.core.cross_attention import MultiHeadCrossAttention

        B, N, d_model, n_heads = 2, 6, 32, 2
        attn = MultiHeadCrossAttention(d_model=d_model, n_heads=n_heads)
        query = torch.randn(B, 1, d_model)
        key = torch.randn(B, N, d_model)
        value = torch.randn(B, N, d_model)

        out = attn(query, key, value, factor_head_mask=None)
        assert out.shape == (B, d_model)
        # 所有权重和应为 1（无屏蔽）
        weights = attn.last_attn_weights
        assert torch.allclose(weights.sum(dim=-1), torch.ones(B, n_heads, 1), atol=1e-5)

    def test_last_attn_weights_shape(self):
        """last_attn_weights 形状应为 (B, n_heads, 1, N)。"""
        from dreambuddy_evolution.core.cross_attention import MultiHeadCrossAttention

        B, N, d_model, n_heads = 3, 8, 32, 4
        attn = MultiHeadCrossAttention(d_model=d_model, n_heads=n_heads)
        query = torch.randn(B, 1, d_model)
        key = torch.randn(B, N, d_model)
        value = torch.randn(B, N, d_model)

        attn(query, key, value)
        weights = attn.last_attn_weights
        assert weights.shape == (B, n_heads, 1, N)

    def test_soft_mask_allows_leakage(self):
        """软 mask（大负值而非 -inf）允许少量跨维度权重。"""
        from dreambuddy_evolution.core.cross_attention import MultiHeadCrossAttention

        B, N, d_model, n_heads = 2, 6, 32, 2
        attn = MultiHeadCrossAttention(d_model=d_model, n_heads=n_heads)

        # 软 mask: 用 -1e9 而非 -inf
        mask = torch.full((n_heads, N), -1e9)
        mask[0, :3] = 0.0
        mask[1, 3:] = 0.0

        query = torch.randn(B, 1, d_model)
        key = torch.randn(B, N, d_model)
        value = torch.randn(B, N, d_model)

        attn(query, key, value, factor_head_mask=mask)
        weights = attn.last_attn_weights
        # 软 mask 下被屏蔽因子权重应接近 0 但可能非严格 0
        assert (weights[:, 0, 0, 3:] < 1e-3).all()
        assert (weights[:, 1, 0, :3] < 1e-3).all()
