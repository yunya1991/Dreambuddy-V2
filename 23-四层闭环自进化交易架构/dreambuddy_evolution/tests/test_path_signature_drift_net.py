"""RED 测试: Path-Signature Drift Net (TDD-001/004/006/009).

NeuralSDE 架构升级 — 路径依赖 SDE (Path-Signature Drift).

测试覆盖:
  - TDD-001: _PathSignatureDriftNet 接收 [S_t, sin(t), cos(t), log_sig] 7 维输入 → 标量 drift
  - TDD-004 (drift_net 层): log_sig 为 zeros 时 drift_net 仍工作 (FAIL-OPEN)
  - TDD-006: torch.set_num_threads(1) 保持 Apple Silicon 兼容
  - TDD-009: CS 公式输入维度 8 不变 (项目硬约束)

参考: .trae/specs/neural-sde-architecture-upgrade/spec.md §5
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# 确保 REPO 在 sys.path
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ============================================================================
# TDD-001: _PathSignatureDriftNet 数据流
# ============================================================================


class TestPathSignatureDriftNet:
    """TDD-001: drift_net 接收 path-signature 输入."""

    def test_drift_net_accepts_signature_input(self):
        """drift_net 接收 [S_t, sin(t), cos(t), log_sig(4维)] 7维输入 → (1,1) 标量."""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        net = _PathSignatureDriftNet(hidden_dim=64, sig_dim=4)
        S_t = _torch().tensor([[50000.0]])
        t = _torch().tensor(0.5)
        log_sig = _torch().tensor([[0.1, -0.05, 0.02, 0.01]])
        out = net(t, S_t, log_sig)
        assert out.shape == (1, 1)
        assert _torch().isfinite(out).all()

    def test_drift_net_batch_shape(self):
        """batch 维度: (B, 1) S_t + (B, 4) log_sig → (B, 1)."""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        net = _PathSignatureDriftNet(hidden_dim=64, sig_dim=4)
        torch = _torch()
        B = 16
        S_t = torch.randn(B, 1)
        t = torch.tensor(0.3)
        log_sig = torch.randn(B, 4)
        out = net(t, S_t, log_sig)
        assert out.shape == (B, 1)
        assert torch.isfinite(out).all()

    def test_drift_net_tanh_clip_bounds(self):
        """tanh 裁剪防爆炸: 输出在 [-clip, clip] 范围内."""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        clip = 2.0
        net = _PathSignatureDriftNet(hidden_dim=64, sig_dim=4, clip=clip)
        torch = _torch()
        # 极端输入
        S_t = torch.tensor([[1e6, -1e6, 0.0, 1.0]]).T  # (4, 1)
        t = torch.tensor(0.5)
        log_sig = torch.tensor([[1e3, -1e3, 1e3, -1e3]])
        out = net(t, S_t, log_sig)
        assert out.shape == (4, 1)
        assert torch.le(out.abs(), clip + 1e-6).all(), f"输出超出 clip={clip}: {out}"

    def test_drift_net_gradient_flow(self):
        """训练时梯度可流过 log_sig 输入."""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        net = _PathSignatureDriftNet(hidden_dim=64, sig_dim=4)
        torch = _torch()
        S_t = torch.tensor([[50000.0]], requires_grad=True)
        t = torch.tensor(0.5)
        log_sig = torch.tensor([[0.1, -0.05, 0.02, 0.01]], requires_grad=True)
        out = net(t, S_t, log_sig)
        out.backward(torch.ones_like(out))
        # 参数应有梯度
        assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in net.parameters())


# ============================================================================
# TDD-004 (drift_net 层): log_sig zeros 时 drift_net 仍工作 (FAIL-OPEN)
# ============================================================================


class TestPathSignatureDriftNetFailOpen:
    """TDD-004: signatory+esig 不可用时 → log_sig pad zeros, drift_net 仍工作."""

    def test_drift_net_accepts_zero_log_sig(self):
        """log_sig 全 0 时 drift_net 仍能输出有限值 (退化到马尔可夫)."""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        net = _PathSignatureDriftNet(hidden_dim=64, sig_dim=4)
        torch = _torch()
        S_t = torch.tensor([[50000.0]])
        t = torch.tensor(0.5)
        log_sig_zeros = torch.zeros(1, 4)
        out = net(t, S_t, log_sig_zeros)
        assert out.shape == (1, 1)
        assert torch.isfinite(out).all()

    def test_drift_net_log_sig_none_pads_zeros(self):
        """log_sig=None 时自动 pad zeros, 不抛异常."""
        from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

        net = _PathSignatureDriftNet(hidden_dim=64, sig_dim=4)
        torch = _torch()
        S_t = torch.tensor([[50000.0]])
        t = torch.tensor(0.5)
        # log_sig=None 应触发内部 pad zeros
        out = net(t, S_t, log_sig=None)
        assert out.shape == (1, 1)
        assert torch.isfinite(out).all()


# ============================================================================
# TDD-006: torch.set_num_threads(1) 保持 Apple Silicon 兼容
# ============================================================================


class TestTorchSingleThreadPreserved:
    """TDD-006: 升级后仍调用 torch.set_num_threads(1).

    依据: 认知库 VM-1791184649034 (PyTorch OpenMP tanh_kernel 在 Apple Silicon
    多线程下 SIGSEGV, Sleef_tanhf4_u10). 升级不可破坏此修复.
    """

    def test_torch_single_thread_setting_preserved(self):
        """import neural_sde_model 后 torch.get_num_threads() == 1."""
        import torch

        # 触发 neural_sde_model 模块加载 (副作用: set_num_threads(1))
        from dreambuddy_evolution.core import neural_sde_model  # noqa: F401

        if torch is not None:
            assert torch.get_num_threads() == 1, (
                f"torch.get_num_threads()={torch.get_num_threads()} ≠ 1, "
                "Apple Silicon 多线程会 SIGSEGV (VM-1791184649034)"
            )

    def test_neural_sde_model_module_loads(self):
        """模块可无错加载 (确认 _TORCH_AVAILABLE 标志存在)."""
        from dreambuddy_evolution.core import neural_sde_model as nsm

        assert hasattr(nsm, "_TORCH_AVAILABLE")
        assert hasattr(nsm, "NeuralSDEModel")


# ============================================================================
# TDD-009: CS 公式输入维度 8 不变 (项目硬约束)
# ============================================================================


class TestCSInputDimensionUnchanged:
    """TDD-009: 升级不影响 CS 公式输入维度 (仍为 8).

    项目硬约束: CS 维度 8 不可增. 升级路径依赖 SDE 不可破坏此约束.
    """

    def test_cs_input_dimension_unchanged(self):
        """deep_policy_network._MLPPolicyBase.get_cs_input_dimension() == 8."""
        from dreambuddy_evolution.core.deep_policy_network import _MLPPolicyBase

        policy = _MLPPolicyBase()
        assert policy.get_cs_input_dimension() == 8, (
            "CS 公式输入维度应为 8 (项目硬约束), "
            f"实际={policy.get_cs_input_dimension()}"
        )


# ============================================================================
# 辅助
# ============================================================================


def _torch():
    """安全获取 torch (pytest 时 torch 应可用)."""
    import torch
    return torch
