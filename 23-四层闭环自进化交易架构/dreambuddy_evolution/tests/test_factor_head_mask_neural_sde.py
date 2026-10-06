"""
M2/M1 RED: factor_head_mask 在 NeuralSDE 中的透传与序列化

测试:
  M2: _PathSignatureDriftNet / _MoEDriftNet 接收并传递 factor_head_mask
  M1: NeuralSDEModel.save()/load() 持久化 factor_head_mask
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import torch


class TestFactorHeadMaskPassthrough:
    """M2: factor_head_mask 透传到 drift_net 的 cross_attn。"""

    def test_path_signature_drift_net_accepts_mask(self):
        """_PathSignatureDriftNet 接受 factor_head_mask 参数。"""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        mask = torch.zeros(2, 6)  # 2 heads, 6 factors
        net = _PathSignatureDriftNet(
            use_cross_attention=True,
            exogenous_factor_dim=6,
            cross_attn_dim=32,
            cross_attn_heads=2,
            factor_head_mask=mask,
        )
        # mask 应注册为 cross_attn 的 buffer
        assert hasattr(net.cross_attn, "factor_head_mask")
        assert net.cross_attn.factor_head_mask is not None

    def test_moe_drift_net_passes_mask_to_experts(self):
        """_MoEDriftNet 将 factor_head_mask 传递给每个 expert。"""
        from dreambuddy_evolution.core.neural_sde_model import _MoEDriftNet

        mask = torch.zeros(2, 6)
        moe = _MoEDriftNet(
            n_experts=3,
            use_cross_attention=True,
            exogenous_factor_dim=6,
            cross_attn_dim=32,
            cross_attn_heads=2,
            factor_head_mask=mask,
        )
        for expert in moe.experts:
            assert hasattr(expert.cross_attn, "factor_head_mask")
            assert expert.cross_attn.factor_head_mask is not None

    def test_mask_applied_in_forward(self):
        """forward 时 mask 生效：被屏蔽因子的 attention weight 为 0。"""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        B, N, sig_dim, n_heads = 2, 6, 15, 2
        # head 0 看因子 0-2, head 1 看因子 3-5
        mask = torch.full((n_heads, N), float("-inf"))
        mask[0, :3] = 0.0
        mask[1, 3:] = 0.0

        net = _PathSignatureDriftNet(
            sig_dim=sig_dim,
            use_cross_attention=True,
            exogenous_factor_dim=N,
            cross_attn_dim=32,
            cross_attn_heads=n_heads,
            factor_head_mask=mask,
        )

        t = torch.tensor(0.5)
        y = torch.randn(B, 1)
        log_sig = torch.randn(B, sig_dim)
        regime = torch.zeros(B, 3)
        regime[:, 0] = 1.0
        exogenous_factors = torch.randn(B, N, 1)

        out = net(t, y, log_sig=log_sig, regime=regime, exogenous_factors=exogenous_factors)
        assert out.shape == (B, 1)

        # 检查 attention weights
        weights = net.cross_attn.last_attn_weights  # (B, n_heads, 1, N)
        assert weights is not None
        # head 0: 因子 3-5 权重应为 0
        assert torch.allclose(weights[:, 0, 0, 3:], torch.zeros(B, 3), atol=1e-6)
        # head 1: 因子 0-2 权重应为 0
        assert torch.allclose(weights[:, 1, 0, :3], torch.zeros(B, 3), atol=1e-6)


class TestFactorHeadMaskCheckpoint:
    """M1: factor_head_mask 的 checkpoint 序列化。"""

    def test_save_includes_mask(self):
        """save() 将 factor_head_mask 写入 checkpoint。"""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        mask = torch.zeros(2, 6)
        model = NeuralSDEModel(
            use_cross_attention=True,
            exogenous_factor_dim=6,
            cross_attn_dim=32,
            cross_attn_heads=2,
            factor_head_mask=mask,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.pt"
            model.save(str(path))
            ckpt = torch.load(str(path), map_location="cpu", weights_only=False)
            assert "factor_head_mask" in ckpt
            assert torch.allclose(ckpt["factor_head_mask"], mask)

    def test_load_restores_mask(self):
        """load() 恢复 factor_head_mask 并应用到 drift_net。"""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        mask = torch.zeros(2, 6)
        model = NeuralSDEModel(
            use_cross_attention=True,
            exogenous_factor_dim=6,
            cross_attn_dim=32,
            cross_attn_heads=2,
            factor_head_mask=mask,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.pt"
            model.save(str(path))

            # 新建模型加载
            model2 = NeuralSDEModel(
                use_cross_attention=True,
                exogenous_factor_dim=6,
                cross_attn_dim=32,
                cross_attn_heads=2,
            )
            loaded = model2.load(str(path))
            assert loaded is True
            # mask 应恢复到 drift_net
            assert hasattr(model2.drift_net.cross_attn, "factor_head_mask")
            assert model2.drift_net.cross_attn.factor_head_mask is not None

    def test_load_old_checkpoint_without_mask_fail_open(self):
        """旧 checkpoint 无 factor_head_mask 时 FAIL-OPEN（不报错，mask=None）。"""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        # 保存一个不带 mask 的模型
        model = NeuralSDEModel(
            use_cross_attention=True,
            exogenous_factor_dim=6,
            cross_attn_dim=32,
            cross_attn_heads=2,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.pt"
            model.save(str(path))

            # 新建模型加载
            model2 = NeuralSDEModel(
                use_cross_attention=True,
                exogenous_factor_dim=6,
                cross_attn_dim=32,
                cross_attn_heads=2,
            )
            loaded = model2.load(str(path))
            assert loaded is True
            # 无 mask 时 cross_attn.factor_head_mask 应为 None
            assert model2.drift_net.cross_attn.factor_head_mask is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
