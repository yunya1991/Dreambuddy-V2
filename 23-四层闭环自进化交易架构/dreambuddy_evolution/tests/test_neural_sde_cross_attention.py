"""
C3 RED: NeuralSDE Cross-Attention 集成测试

测试 _PathSignatureDriftNet 的 cross_attention 模式：
  1. use_cross_attention=False 时行为与原架构完全一致
  2. use_cross_attention=True 时接受 exogenous_factors (B, N, factor_dim)
  3. exogenous_factors=None 时 FAIL-OPEN（退化为无外生）
  4. 可变因子数 N

RED 阶段：cross_attention 集成尚未实现 → 测试失败
"""
from __future__ import annotations

import pytest
import torch


class TestNeuralSDECrossAttention:
    """测试 NeuralSDE 的 Cross-Attention 外生注入。"""

    def test_cross_attention_mode_flag(self):
        """_PathSignatureDriftNet 支持 use_cross_attention 参数。"""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        net = _PathSignatureDriftNet(
            use_cross_attention=True,
            exogenous_factor_dim=10,
            cross_attn_dim=32,
        )
        assert net.use_cross_attention is True
        assert net.exogenous_factor_dim == 10

    def test_cross_attention_forward(self):
        """use_cross_attention=True 时接受 exogenous_factors 输入。"""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        B, N, sig_dim = 4, 10, 15
        net = _PathSignatureDriftNet(
            sig_dim=sig_dim,
            use_cross_attention=True,
            exogenous_factor_dim=N,
            cross_attn_dim=32,
        )

        t = torch.tensor(0.5)
        y = torch.randn(B, 1)
        log_sig = torch.randn(B, sig_dim)
        regime = torch.zeros(B, 3)
        regime[:, 0] = 1.0
        exogenous_factors = torch.randn(B, N, 1)  # N 个标量因子

        out = net(t, y, log_sig=log_sig, regime=regime, exogenous_factors=exogenous_factors)
        assert out.shape == (B, 1)
        assert not torch.isnan(out).any()

    def test_cross_attention_none_fail_open(self):
        """exogenous_factors=None 时 FAIL-OPEN（context=0）。"""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        B, N, sig_dim = 4, 10, 15
        net = _PathSignatureDriftNet(
            sig_dim=sig_dim,
            use_cross_attention=True,
            exogenous_factor_dim=N,
            cross_attn_dim=32,
        )

        t = torch.tensor(0.5)
        y = torch.randn(B, 1)
        log_sig = torch.randn(B, sig_dim)
        regime = torch.zeros(B, 3)
        regime[:, 0] = 1.0

        # None factors → should not crash, output valid
        out = net(t, y, log_sig=log_sig, regime=regime, exogenous_factors=None)
        assert out.shape == (B, 1)
        assert not torch.isnan(out).any()

    def test_no_cross_attention_backward_compat(self):
        """use_cross_attention=False 时行为与原架构一致（exogenous_dim 拼接）。"""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        B, sig_dim, exo_dim = 4, 15, 9
        net = _PathSignatureDriftNet(
            sig_dim=sig_dim,
            use_cross_attention=False,
            exogenous_dim=exo_dim,
        )

        t = torch.tensor(0.5)
        y = torch.randn(B, 1)
        log_sig = torch.randn(B, sig_dim)
        regime = torch.zeros(B, 3)
        regime[:, 0] = 1.0
        exogenous = torch.randn(B, exo_dim)

        out = net(t, y, log_sig=log_sig, regime=regime, exogenous=exogenous)
        assert out.shape == (B, 1)
        assert not torch.isnan(out).any()

    def test_cross_attention_variable_n(self):
        """Cross-Attention 支持可变因子数 N。"""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        B, sig_dim = 4, 15
        net = _PathSignatureDriftNet(
            sig_dim=sig_dim,
            use_cross_attention=True,
            exogenous_factor_dim=15,  # 最大支持 15 因子
            cross_attn_dim=32,
        )

        t = torch.tensor(0.5)
        y = torch.randn(B, 1)
        log_sig = torch.randn(B, sig_dim)
        regime = torch.zeros(B, 3)
        regime[:, 0] = 1.0

        # N=5
        factors5 = torch.randn(B, 5, 1)
        out5 = net(t, y, log_sig=log_sig, regime=regime, exogenous_factors=factors5)
        assert out5.shape == (B, 1)

        # N=15
        factors15 = torch.randn(B, 15, 1)
        out15 = net(t, y, log_sig=log_sig, regime=regime, exogenous_factors=factors15)
        assert out15.shape == (B, 1)


class TestNeuralSDEModelCrossAttention:
    """测试 NeuralSDEModel 顶层的 cross_attention 支持。"""

    def test_model_accepts_cross_attention_config(self):
        """NeuralSDEModel 支持 use_cross_attention 配置。"""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        model = NeuralSDEModel(
            use_moe=True,
            moe_routing="hard",
            use_cross_attention=True,
            exogenous_factor_dim=10,
            cross_attn_dim=32,
        )
        assert model.use_cross_attention is True

    def test_model_forecast_with_factors(self):
        """forecast() 接受 exogenous_factors 参数。"""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel
        import numpy as np

        model = NeuralSDEModel(
            use_moe=True,
            moe_routing="hard",
            use_cross_attention=True,
            exogenous_factor_dim=10,
            cross_attn_dim=32,
            n_regimes=3,
        )

        closes = np.cumsum(np.random.randn(100) * 10) + 50000
        factors = np.random.randn(10, 1)  # 10 个因子

        result = model.forecast(
            closes=closes,
            horizon=20,
            exogenous_factors=factors,
        )
        assert "forecast" in result
        assert not np.isnan(result["forecast"]).any()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
