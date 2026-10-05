"""RED 测试: P0.2-T3 drift_net 加 transition vector 输入.

背景:
  T7 OOS 根因 3: regime 标签同质化. 仅用 regime one-hot 无法区分
  同标签不同动态 (如 2024 伪 bull vs 训练集上涨 bull).
  解决: drift_net 输入加 transition vector (Q[current_regime]),
  让模型学习 regime 切换动态而非仅 regime 静态标签.

接口变更 (向后兼容):
  _PathSignatureDriftNet.__init__ 加 n_transition=0 参数
    - n_transition=0 (旧模型): in_dim = 3 + sig_dim + n_regimes (不变)
    - n_transition=n_regimes (P0.2): in_dim = 3 + sig_dim + n_regimes + n_regimes
  forward(t, y, log_sig, regime, transition=None):
    - transition=None → pad zeros (向后兼容)
    - transition=(B, n_transition) → 拼接输入

TDD 覆盖:
  P0.2-T3.1 n_transition=0 时 in_dim 不变 (向后兼容)
  P0.2-T3.2 n_transition>0 时 in_dim 增加 n_transition
  P0.2-T3.3 forward 接受 transition 参数且不抛异常
  P0.2-T3.4 transition=None 时 pad zeros (不报错)
  P0.2-T3.5 NeuralSDEModel use_transition=True 时 drift_net 有 transition 输入
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_drift_net_n_transition_zero_backward_compat():
    """P0.2-T3.1: n_transition=0 时 in_dim 不变 (向后兼容旧模型)."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

    # 旧模型: n_regimes=3, n_transition=0
    net = _PathSignatureDriftNet(hidden_dim=8, sig_dim=15, n_regimes=3, n_transition=0)
    # in_dim = 3 + 15 + 3 = 21 (旧模型)
    expected_in = 3 + 15 + 3
    actual_in = net.net[0].in_features
    assert actual_in == expected_in, f"in_dim 应为 {expected_in}, 实际 {actual_in}"


def test_drift_net_n_transition_positive_increases_dim():
    """P0.2-T3.2: n_transition>0 时 in_dim 增加 n_transition."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

    # P0.2: n_regimes=3, n_transition=3
    net = _PathSignatureDriftNet(hidden_dim=8, sig_dim=15, n_regimes=3, n_transition=3)
    # in_dim = 3 + 15 + 3 + 3 = 24
    expected_in = 3 + 15 + 3 + 3
    actual_in = net.net[0].in_features
    assert actual_in == expected_in, f"in_dim 应为 {expected_in}, 实际 {actual_in}"


def test_drift_net_forward_accepts_transition():
    """P0.2-T3.3: forward 接受 transition 参数且不抛异常."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

    net = _PathSignatureDriftNet(hidden_dim=8, sig_dim=15, n_regimes=3, n_transition=3)
    B = 4
    y = torch.randn(B, 1)
    log_sig = torch.randn(B, 15)
    regime = torch.zeros(B, 3)
    transition = torch.randn(B, 3)  # Q[current_regime] vector

    out = net.forward(t=0.5, y=y, log_sig=log_sig, regime=regime, transition=transition)
    assert out.shape == (B, 1)
    assert torch.isfinite(out).all()


def test_drift_net_forward_transition_none_pad_zeros():
    """P0.2-T3.4: transition=None 时 pad zeros (向后兼容, 不报错)."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

    net = _PathSignatureDriftNet(hidden_dim=8, sig_dim=15, n_regimes=3, n_transition=3)
    B = 4
    y = torch.randn(B, 1)
    log_sig = torch.randn(B, 15)
    regime = torch.zeros(B, 3)

    # transition=None 应 pad zeros, 不抛异常
    out = net.forward(t=0.5, y=y, log_sig=log_sig, regime=regime, transition=None)
    assert out.shape == (B, 1)
    assert torch.isfinite(out).all()


def test_model_use_transition_true_has_transition_input():
    """P0.2-T3.5: NeuralSDEModel use_transition=True 时 drift_net 有 transition 输入维度."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

    model = NeuralSDEModel(device="cpu", n_regimes=3, use_transition=True)
    assert model.use_transition is True
    # drift_net in_dim 应包含 n_regimes (transition vector)
    expected_in = 3 + model.sig_dim + 3 + 3
    actual_in = model.drift_net.net[0].in_features
    assert actual_in == expected_in, f"in_dim 应为 {expected_in}, 实际 {actual_in}"


def test_model_use_transition_false_backward_compat():
    """P0.2-T3.6: use_transition=False (默认) 时 drift_net in_dim 不变."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

    model = NeuralSDEModel(device="cpu", n_regimes=3, use_transition=False)
    assert model.use_transition is False
    expected_in = 3 + model.sig_dim + 3  # 无 transition
    actual_in = model.drift_net.net[0].in_features
    assert actual_in == expected_in, f"in_dim 应为 {expected_in}, 实际 {actual_in}"
