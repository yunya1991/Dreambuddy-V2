"""RED 测试: T2 _PathSignatureDriftNet 加 regime one-hot 输入 (NeuralSDE V3c 修复).

问题背景:
  T1 BTCRegimeDetector 已能输出 3 态 regime (bull/chop/bear).
  现需让 drift_net 接收 regime one-hot 作为输入, 使 SDE drift 函数条件化于 regime:
    dS = fθ(S_t, t, log_sig, regime_onehot)·dt + gφ(S_t, t)·dW

接口变更 (向后兼容):
  旧: _PathSignatureDriftNet(hidden_dim, sig_dim, clip).forward(t, y, log_sig)
  新: _PathSignatureDriftNet(hidden_dim, sig_dim, clip, n_regimes=3).forward(t, y, log_sig, regime=None)
  - n_regimes=3 默认, in_dim = 3 + sig_dim + n_regimes = 21
  - regime=None → pad zeros (FAIL-OPEN, 旧模型行为不变)
  - regime=(B, 3) one-hot → drift 输出受 regime 影响

TDD 覆盖:
  T2.1 __init__ 支持 n_regimes 参数 (默认 3)
  T2.2 in_dim = 3 + sig_dim + n_regimes (=21 默认)
  T2.3 forward 支持 regime kwarg (向后兼容 regime=None)
  T2.4 regime=None 时 drift 输出有限 (FAIL-OPEN)
  T2.5 regime=one-hot 时 drift 输出与 regime=None 不同 (信号被吸收)
  T2.6 save/load 保留 n_regimes (向后兼容旧模型 n_regimes=0)

参考:
  - neural_sde_model.py _PathSignatureDriftNet L116-192
  - T1 BTCRegimeDetector (本会话, 输出 3 态 regime)
  - 调研 spec VM-1791190210830 §方案 A 步骤 2
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
# T2.1 __init__ 支持 n_regimes 参数 (默认 3)
# ============================================================================


def test_drift_net_init_supports_n_regimes():
    """T2.1: _PathSignatureDriftNet.__init__ 应支持 n_regimes 参数, 默认 3."""
    from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

    net = _PathSignatureDriftNet()
    assert getattr(net, "n_regimes", None) == 3, (
        "默认 n_regimes 应为 3 (bull/chop/bear)"
    )

    net_custom = _PathSignatureDriftNet(n_regimes=5)
    assert net_custom.n_regimes == 5


# ============================================================================
# T2.2 in_dim = 3 + sig_dim + n_regimes (=21 默认)
# ============================================================================


def test_drift_net_in_dim_includes_regime():
    """T2.2: drift_net 输入维度应 = 3 + sig_dim + n_regimes.

    旧: 3 + 15 = 18
    新: 3 + 15 + 3 = 21 (含 regime one-hot)
    """
    from dreambuddy_evolution.core.neural_sde_model import (
        _PathSignatureDriftNet,
        DEFAULT_SIG_DIM,
    )

    net = _PathSignatureDriftNet()
    expected_in_dim = 3 + DEFAULT_SIG_DIM + 3
    # 第一个 Linear 层 in_features 应为 expected_in_dim
    first_linear = net.net[0]
    assert first_linear.in_features == expected_in_dim, (
        f"drift_net 第一层 in_features={first_linear.in_features} "
        f"应为 {expected_in_dim} (=3+sig_dim+n_regimes)"
    )


# ============================================================================
# T2.3 forward 支持 regime kwarg (向后兼容 regime=None)
# ============================================================================


def test_drift_net_forward_accepts_regime_kwarg():
    """T2.3: forward(t, y, log_sig, regime=None) 应接受 regime kwarg."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

    net = _PathSignatureDriftNet()
    y = torch.zeros(4, 1)
    log_sig = torch.zeros(4, net.sig_dim)
    regime = torch.zeros(4, 3)
    regime[:, 0] = 1.0  # bull

    # 不应 raise (regime 关键字参数)
    out = net.forward(0.0, y, log_sig, regime=regime)
    assert out.shape == (4, 1), f"输出 shape {out.shape} 应为 (4, 1)"

    # regime=None 也不应 raise (向后兼容)
    out_none = net.forward(0.0, y, log_sig, regime=None)
    assert out_none.shape == (4, 1)

    # 旧调用方式 (不传 regime) 也不应 raise
    out_legacy = net.forward(0.0, y, log_sig)
    assert out_legacy.shape == (4, 1)


# ============================================================================
# T2.4 regime=None 时 drift 输出有限 (FAIL-OPEN)
# ============================================================================


def test_drift_net_regime_none_finite_output():
    """T2.4: regime=None 时 drift 输出应有限, 不发散 (FAIL-OPEN 兜底)."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

    net = _PathSignatureDriftNet()
    y = torch.randn(8, 1) * 100
    log_sig = torch.randn(8, net.sig_dim)

    out = net.forward(0.0, y, log_sig, regime=None)
    assert torch.isfinite(out).all(), "regime=None 时输出应有限"
    # tanh 裁剪: |out| <= clip
    assert torch.abs(out).max() <= net.clip + 1e-6


# ============================================================================
# T2.5 regime=one-hot 时 drift 输出与 regime=None 不同 (信号被吸收)
# ============================================================================


def test_drift_net_regime_onehot_changes_output():
    """T2.5: regime=one-hot 时 drift 输出应与 regime=None 不同.

    若两者完全相同 → drift_net 未吸收 regime 信号 → 实现错误.
    闸门: 不同 regime 下输出均值差异 > 1e-6.
    """
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import _PathSignatureDriftNet

    torch.manual_seed(42)
    net = _PathSignatureDriftNet()
    net.eval()  # 关闭 dropout (若有)

    y = torch.zeros(64, 1)
    log_sig = torch.zeros(64, net.sig_dim)

    # regime=None (zeros pad)
    out_none = net.forward(0.0, y, log_sig, regime=None)

    # regime=bull (one-hot [1, 0, 0])
    regime_bull = torch.zeros(64, 3)
    regime_bull[:, 0] = 1.0
    out_bull = net.forward(0.0, y, log_sig, regime=regime_bull)

    # regime=bear (one-hot [0, 0, 1])
    regime_bear = torch.zeros(64, 3)
    regime_bear[:, 2] = 1.0
    out_bear = net.forward(0.0, y, log_sig, regime=regime_bear)

    # bull 与 none 应不同 (除非网络恰好把 regime 维度权重学成 0, 但初始化时不会)
    diff_bull = torch.abs(out_bull - out_none).mean().item()
    diff_bear = torch.abs(out_bear - out_none).mean().item()
    assert diff_bull > 1e-6 or diff_bear > 1e-6, (
        f"regime=one-hot 输出与 regime=None 完全一致 (diff_bull={diff_bull:.2e}, "
        f"diff_bear={diff_bear:.2e}), drift_net 未吸收 regime 信号"
    )


# ============================================================================
# T2.6 save/load 保留 n_regimes (向后兼容旧模型 n_regimes=0)
# ============================================================================


def test_drift_net_save_load_preserves_n_regimes(tmp_path):
    """T2.6: NeuralSDEModel.save/load 应保留 drift_net.n_regimes.

    旧模型 (n_regimes 不存在或 0) 加载到新代码时应默认 n_regimes=3.
    新模型保存后 reload n_regimes 应保持.
    """
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

    # 新模型默认 n_regimes=3
    model = NeuralSDEModel(device="cpu")
    save_path = tmp_path / "test_regime_v4.pt"
    model.save(str(save_path))

    model2 = NeuralSDEModel(device="cpu")
    loaded = model2.load(str(save_path))
    assert loaded, "load 应成功"
    assert getattr(model2.drift_net, "n_regimes", 0) == 3, (
        "load 后 drift_net.n_regimes 应保留为 3"
    )
