"""RED 测试: forecast 统一入口 + EM 路径补 head_multipliers 参数 (FO-AGI-03 修复).

问题背景:
  deep_reasoning_engine.neural_sde_forecast 在 model.use_cross_attention=True 时
  调 model.forecast(..., head_multipliers=...)，但 forecast() 统一入口不接受该参数
  → TypeError → [FO-AGI-03] 降级 GARCH（2026-10-07 21:45 起，日 7200+ 次 CRITICAL）。

  模型内部已就绪:
    - f() 读 _current_head_multipliers 传给 drift_net (L835-848)
    - forecast_torchsde 已接受并设置上下文 (L867/916-931)
  缺口:
    - forecast() 统一入口缺 head_multipliers 形参且未向下传递
    - forecast_euler_maruyama 缺 head_multipliers 形参及上下文设置

TDD 覆盖:
  H1 forecast() 接受 head_multipliers kwarg，不抛 TypeError（线上 crash 复刻）
  H2 forecast() 将 head_multipliers 传递给后端（spy forecast_torchsde 捕获 kwargs）
  H3 forecast_euler_maruyama 接受 head_multipliers，设 _current_head_multipliers
     上下文，推理后清理
  H4 head_multipliers=None 不衰减（FAIL-OPEN，向后兼容）

参考:
  - neural_sde_model.py forecast L1158 / forecast_euler_maruyama L1065 / f L835
  - deep_reasoning_engine.py neural_sde_forecast L181-237
  - test_forecast_regime.py (T4 同款风格)
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
# H1 forecast() 接受 head_multipliers kwarg (线上 crash 复刻)
# ============================================================================


def test_forecast_accepts_head_multipliers_kwarg():
    """H1: forecast(history, ..., head_multipliers=...) 不抛 TypeError."""
    try:
        import torch  # noqa: F401
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    history = 100.0 + np.cumsum(np.random.randn(64) * 0.5)
    head_mult = np.array([1.0, 0.8, 1.2, 0.9], dtype=np.float32)

    # 修复前: TypeError: forecast() got an unexpected keyword argument
    # 'head_multipliers' → [FO-AGI-03] 降级
    paths = model.forecast(history, horizon=10, n_paths=8, head_multipliers=head_mult)
    assert paths is not None
    assert paths.shape == (8, 11), f"path shape {paths.shape} 应为 (8, 11)"
    assert np.isfinite(paths).all(), "path 含 NaN/Inf"


# ============================================================================
# H2 forecast() 将 head_multipliers 传递给后端
# ============================================================================


def test_forecast_passes_head_multipliers_to_backend(monkeypatch):
    """H2: forecast() 应把 head_multipliers 透传给 forecast_torchsde/EM 后端."""
    try:
        import torch  # noqa: F401
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    history = 100.0 + np.cumsum(np.random.randn(64) * 0.5)
    head_mult = np.array([1.0, 0.8, 1.2, 0.9], dtype=np.float32)

    captured: dict = {}
    orig_torchsde = model.forecast_torchsde
    orig_em = model.forecast_euler_maruyama

    def spy_torchsde(state, horizon, n_paths, **kwargs):
        captured.setdefault("torchsde", kwargs)
        return orig_torchsde(state, horizon, n_paths, **kwargs)

    def spy_em(state, horizon, n_paths, **kwargs):
        captured.setdefault("em", kwargs)
        return orig_em(state, horizon, n_paths, **kwargs)

    monkeypatch.setattr(model, "forecast_torchsde", spy_torchsde)
    monkeypatch.setattr(model, "forecast_euler_maruyama", spy_em)

    model.forecast(history, horizon=10, n_paths=8, head_multipliers=head_mult)

    # 至少一个后端收到 head_multipliers，且值一致
    assert captured, "forecast 未调用任何后端"
    received = [
        kw["head_multipliers"]
        for kw in captured.values()
        if "head_multipliers" in kw
    ]
    assert received, f"后端未收到 head_multipliers: {captured.keys()}"
    np.testing.assert_allclose(
        np.asarray(received[0], dtype=np.float64).ravel(),
        head_mult.astype(np.float64),
        rtol=1e-5,
    )


# ============================================================================
# H3 forecast_euler_maruyama 接受 head_multipliers + 上下文清理
# ============================================================================


def test_forecast_euler_maruyama_accepts_head_multipliers():
    """H3: EM 路径接受 head_multipliers，设 _current_head_multipliers，推理后清理."""
    try:
        import torch  # noqa: F401
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True

    state = np.array([100.0])
    log_sig = np.zeros(model.sig_dim, dtype=np.float32)
    head_mult = np.array([1.0, 0.5, 2.0, 1.0], dtype=np.float32)

    # 修复前: TypeError (EM 签名无 head_multipliers)
    paths = model.forecast_euler_maruyama(
        state, horizon=8, n_paths=4, log_sig=log_sig, head_multipliers=head_mult,
    )
    assert paths.shape == (4, 9)
    assert np.isfinite(paths).all()

    # 推理后上下文应被清理
    assert model._current_head_multipliers is None, (
        "推理后 _current_head_multipliers 应被清理"
    )


# ============================================================================
# H4 head_multipliers=None 不衰减 (FAIL-OPEN, 向后兼容)
# ============================================================================


def test_forecast_head_multipliers_none_failopen():
    """H4: head_multipliers=None 向后兼容，路径有限."""
    try:
        import torch  # noqa: F401
    except ImportError:
        pytest.skip("torch not available")

    from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

    np.random.seed(42)
    model = NeuralSDEModel(device="cpu")
    model._activated = True
    history = 100.0 + np.cumsum(np.random.randn(64) * 0.5)

    paths = model.forecast(history, horizon=10, n_paths=8, head_multipliers=None)
    assert paths is not None
    assert paths.shape == (8, 11)
    assert np.isfinite(paths).all()
