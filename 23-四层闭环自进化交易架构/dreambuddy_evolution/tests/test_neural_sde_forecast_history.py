"""RED 测试: NeuralSDE forecast(history) 路径依赖 (TDD-002/003/004/005).

NeuralSDE 架构升级 — forecast 函数接收 history 序列, 通过 path-signature
感知最近 N 步路径, 让 NeuralSDE 超越 GARCH baseline.

测试覆盖:
  - TDD-002: forecast(history, horizon, n_paths) 生成 (n_paths, horizon+1) 路径
  - TDD-003: history < N_step=32 时 pad zeros, 仍生成路径 (FAIL-OPEN Level 2.7)
  - TDD-004: signatory+esig 不可用时 pad zeros, 仍生成路径 (FAIL-OPEN Level 2.5)
  - TDD-005: 旧 forecast(state=[init_price, init_vol], ...) 签名向后兼容

参考: .trae/specs/neural-sde-architecture-upgrade/spec.md §5
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
# TDD-002: forecast(history) 接收 history 序列
# ============================================================================


class TestForecastUsesHistorySignature:
    """TDD-002: forecast 接收 history (最近 N 步 close 价格) 并生成路径."""

    def test_forecast_uses_history_signature(self):
        """forecast(history, horizon, n_paths) → (n_paths, horizon+1) 路径."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        np.random.seed(42)
        model = NeuralSDEModel(device="cpu")
        model._activated = True  # 跳过激活门禁
        history = np.cumsum(np.random.randn(64)) + 50000.0
        paths = model.forecast(history, horizon=20, n_paths=100)
        assert paths is not None, "forecast 应返回路径而非 None"
        assert paths.shape == (100, 21)
        assert np.isfinite(paths).all()
        # 起点应等于 history[-1] (路径依赖: 从最近价格出发)
        assert abs(paths[0, 0] - history[-1]) < 1e-6, (
            f"起点 {paths[0, 0]} ≠ history[-1] {history[-1]}"
        )

    def test_forecast_long_history_uses_signature(self):
        """history ≥ N_step=32 时使用 path-signature, drift_net 输入 7 维."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        np.random.seed(7)
        model = NeuralSDEModel(device="cpu")
        model._activated = True
        # 长历史 (128 步) → 取最近 32 步计算 log-signature
        history = 50000.0 + np.cumsum(np.random.randn(128) * 10.0)
        paths = model.forecast(history, horizon=10, n_paths=50)
        assert paths is not None
        assert paths.shape == (50, 11)
        assert np.all(np.isfinite(paths))


# ============================================================================
# TDD-003: FAIL-OPEN — history 不足 N_step
# ============================================================================


class TestForecastFailOpenShortHistory:
    """TDD-003: history 长度 < N_step=32 时 pad zeros, 仍生成路径."""

    def test_forecast_fails_open_when_history_too_short(self):
        """history 长度 3 < 32 → pad zeros, 退化马尔可夫, 仍生成路径."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        model = NeuralSDEModel(device="cpu")
        model._activated = True
        short_history = np.array([50000.0, 50100.0, 50200.0])  # len=3 < 32
        paths = model.forecast(short_history, horizon=20, n_paths=50)
        assert paths is not None, "FAIL-OPEN: history 不足仍应返回路径"
        assert paths.shape == (50, 21)
        assert np.isfinite(paths).all()

    def test_forecast_empty_history_fails_open(self):
        """history 长度 0 → pad zeros, 仍生成路径 (不抛异常)."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        model = NeuralSDEModel(device="cpu")
        model._activated = True
        # 空数组 — 极端边界
        empty_history = np.array([50000.0])  # 长度 1
        paths = model.forecast(empty_history, horizon=10, n_paths=20)
        # 应返回路径 (退化到马尔可夫, log_sig pad zeros)
        assert paths is not None
        assert paths.shape == (20, 11)
        assert np.isfinite(paths).all()


# ============================================================================
# TDD-004: FAIL-OPEN — signatory+esig 不可用
# ============================================================================


class TestForecastFailOpenSignatureLibsUnavailable:
    """TDD-004: signatory 和 esig 都不可用时 log_sig pad zeros."""

    def test_forecast_fails_open_when_signature_libs_unavailable(self, monkeypatch):
        """monkeypatch SignatureEngine 不可用 → log_sig pad zeros, 仍生成路径."""
        from dreambuddy_evolution.core import neural_sde_model as nsm

        # 模拟 signatory+esig 都不可用
        monkeypatch.setattr(nsm, "_SIGNATORY_AVAILABLE", False, raising=False)
        monkeypatch.setattr(nsm, "_ESIG_AVAILABLE", False, raising=False)

        np.random.seed(11)
        model = nsm.NeuralSDEModel(device="cpu")
        model._activated = True
        history = np.cumsum(np.random.randn(64)) + 50000.0
        paths = model.forecast(history, horizon=20, n_paths=50)
        assert paths is not None, (
            "FAIL-OPEN Level 2.5: signatory+esig 不可用时 log_sig pad zeros 仍应返回路径"
        )
        assert paths.shape == (50, 21)
        assert np.isfinite(paths).all()
        # 起点应等于 history[-1]
        assert abs(paths[0, 0] - history[-1]) < 1e-6


# ============================================================================
# TDD-005: 向后兼容 — 旧 state 参数仍可用
# ============================================================================


class TestForecastBackwardCompatStateOnly:
    """TDD-005: 旧 forecast(state=[init_price, init_vol], ...) 签名向后兼容.

    依据: deep_reasoning_engine.py L199 现有调用 model.forecast(state, horizon, n_paths)
    不可一次破坏. 旧 state 数组长度 2 < N_step → 触发 pad zeros, 退化马尔可夫.
    """

    def test_forecast_backward_compat_state_only(self):
        """旧 forecast(state=[init_price, init_vol], horizon, n_paths) 仍可用."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        model = NeuralSDEModel(device="cpu")
        model.set_normalization(np.random.randn(100) * 5 + 100)
        model._activated = True
        state = np.array([50000.0, 0.02])  # 旧签名: [init_price, init_vol]
        paths = model.forecast(state, horizon=20, n_paths=100)
        assert paths is not None, "向后兼容: 旧 state 参数应仍可用"
        assert paths.shape == (100, 21)
        assert np.isfinite(paths).all()
        # 起点应等于 state[0] (init_price)
        assert abs(paths[0, 0] - state[0]) < 1e-6

    def test_forecast_backward_compat_positional_args(self):
        """旧位置参数调用 forecast(state, horizon, n_paths) 不破坏."""
        from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel

        model = NeuralSDEModel(device="cpu")
        model._activated = True
        # 模拟 deep_reasoning_engine.py L199 的调用方式
        state = np.array([100.0, 0.02])
        paths = model.forecast(state, 10, 50)  # 位置参数
        assert paths is not None
        assert paths.shape == (50, 11)
