"""RED 测试: T4 forecast 加 regime 参数 + 向后兼容 (NeuralSDE V3c 修复).

问题背景:
  T2 已让 drift_net 支持 regime one-hot, T3 已让 prepare_data 输出 4-tuple.
  推理路径需相应扩展: forecast(history, horizon, n_paths, state, regime) 接收 regime
  标签, 转为 one-hot 后通过 _current_regime 上下文传给 drift_net.

接口变更 (向后兼容):
  旧: forecast(history, horizon, n_paths, state)
  新: forecast(history, horizon, n_paths, state, regime=None)
    - regime=None → drift_net pad zeros (FAIL-OPEN, 兼容旧推理路径)
    - regime=int (0/1/2) → 转 one-hot 后传给 drift_net

TDD 覆盖:
  T4.1 forecast 接受 regime kwarg (向后兼容 regime=None)
  T4.2 regime=int 不抛异常, 返回有限 path
  T4.3 regime=0 (bull) 与 regime=2 (bear) 输出不同 (信号被吸收)
  T4.4 forecast_torchsde / forecast_euler_maruyama 接受 regime 参数

参考:
  - neural_sde_model.py L624 forecast, L491/557 forecast_torchsde/euler_maruyama
  - T2 _PathSignatureDriftNet regime one-hot (本会话)
  - 调研 spec VM-1791190210830 §方案 A 步骤 4
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
# T4.1 forecast 接受 regime kwarg (向后兼容 regime=None)
# ============================================================================


def test_forecast_accepts_regime_kwarg():
    """T4.1: forecast(history, horizon, n_paths, state, regime=None) 不抛异常."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    history = 100.0 + np.cumsum(np.random.randn(64) * 0.5)

    # regime=None 不应抛异常 (向后兼容)
    paths = model.forecast(history, horizon=10, n_paths=8, regime=None)
    assert paths is not None
    assert paths.shape == (8, 11), f"path shape {paths.shape} 应为 (8, 11)"

    # regime=0 (bull) 也不应抛异常
    paths_bull = model.forecast(history, horizon=10, n_paths=8, regime=0)
    assert paths_bull.shape == (8, 11)

    # regime=2 (bear) 也不应抛异常
    paths_bear = model.forecast(history, horizon=10, n_paths=8, regime=2)
    assert paths_bear.shape == (8, 11)


# ============================================================================
# T4.2 regime=int 不抛异常, 返回有限 path
# ============================================================================


def test_forecast_regime_int_finite_paths():
    """T4.2: regime=0/1/2 各自不抛异常, path 应有限."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    history = 100.0 + np.cumsum(np.random.randn(64) * 0.5)

    for regime in (0, 1, 2):
        paths = model.forecast(history, horizon=10, n_paths=8, regime=regime)
        assert paths is not None, f"regime={regime} 返回 None"
        assert np.isfinite(paths).all(), f"regime={regime} path 含 NaN/Inf"


# ============================================================================
# T4.3 regime=0 (bull) 与 regime=2 (bear) 输出不同 (信号被吸收)
# ============================================================================


def test_forecast_different_regimes_give_different_outputs():
    """T4.3: 不同 regime 应让 forecast 输出不同 (drift_net 吸收 regime 信号).

    若输出完全相同 → 推理路径未传 regime 给 drift_net → 实现错误.
    """
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

    torch.manual_seed(42)
    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    # 训练一会, 让 drift_net regime 维度有梯度 (非默认初始化)
    from dreambuddy_evolution.core.neural_sde_model import NeuralSDETrainer
    trainer = NeuralSDETrainer(model=model, seq_len=32, horizon=10, batch_size=8)
    closes = 100.0 + np.cumsum(np.random.randn(200) * 0.5)
    regime_labels = np.arange(200) % 3
    windows = trainer.prepare_data(closes, max_windows=30, regime_labels=regime_labels)
    if windows:
        trainer.train_epoch(windows)

    torch.manual_seed(123)
    history = 100.0 + np.cumsum(np.random.randn(64) * 0.5)
    paths_bull = model.forecast(history, horizon=10, n_paths=16, regime=0)
    paths_bear = model.forecast(history, horizon=10, n_paths=16, regime=2)
    diff = np.abs(paths_bull - paths_bear).mean()
    assert diff > 1e-6, (
        f"regime=0 vs regime=2 输出完全一致 (diff={diff:.2e}), "
        "推理路径未传 regime 给 drift_net"
    )


# ============================================================================
# T4.4 forecast_torchsde / forecast_euler_maruyama 接受 regime 参数
# ============================================================================


def test_forecast_euler_maruyama_accepts_regime():
    """T4.4: forecast_euler_maruyama 接受 regime 参数, 设 _current_regime 上下文."""
    try:
        import torch
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True

    state = np.array([100.0])
    log_sig = np.zeros(model.sig_dim, dtype=np.float32)

    # 不应抛异常
    paths = model.forecast_euler_maruyama(state, horizon=8, n_paths=4, log_sig=log_sig, regime=0)
    assert paths.shape == (4, 9)

    # regime=2 (bear)
    paths_bear = model.forecast_euler_maruyama(state, horizon=8, n_paths=4, log_sig=log_sig, regime=2)
    assert paths_bear.shape == (4, 9)

    # 推理后上下文应被清理
    assert model._current_regime is None, "推理后 _current_regime 应被清理"
