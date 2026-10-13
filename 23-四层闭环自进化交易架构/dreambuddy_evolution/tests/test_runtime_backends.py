"""T3/T4: torch/SDE 后端可观测性契约测试（RED）.

SPEC-本地远端双写分叉治理与torch可用性 §2.2③④ / PLAN 阶段1 T3+T4。

治理目标：消除"有/无 torch、有/无 torchsde"的隐性静默降级，
启动时可观测后端状态（_TORCH_AVAILABLE / _TORCHSDE_AVAILABLE / status / backend）。
"""
from __future__ import annotations

import logging
import types

import numpy as np
import pytest


class TestStatusExposesTorchsde:
    """status() 必须显式暴露 torchsde 可用性（不再只看 torch）。"""

    def test_status_exposes_torchsde_flag(self):
        from dreambuddy_evolution.engines.sde_solver import SDESolver

        status = SDESolver().status()
        assert "torchsde" in status
        assert isinstance(status["torchsde"], bool)

    def test_status_flags_match_module_probe(self):
        from dreambuddy_evolution.engines import sde_solver as m

        status = m.SDESolver().status()
        assert status["neural_sde"] is m._TORCH_AVAILABLE
        assert status["torchsde"] is m._TORCHSDE_AVAILABLE


class TestLogRuntimeBackends:
    """log_runtime_backends() 是唯一可观测入口，供启动处调用。"""

    def test_function_exists_and_returns_dict(self):
        from dreambuddy_evolution.engines.sde_solver import log_runtime_backends

        info = log_runtime_backends()
        assert isinstance(info, dict)
        for key in ("torch_available", "torchsde_available", "sde_backend", "degraded"):
            assert key in info, f"缺少可观测字段: {key}"

    def test_reflects_module_flags(self):
        from dreambuddy_evolution.engines import sde_solver as m

        info = m.log_runtime_backends()
        assert info["torch_available"] is m._TORCH_AVAILABLE
        assert info["torchsde_available"] is m._TORCHSDE_AVAILABLE
        # degraded 等价于缺 torch 或缺 torchsde
        assert info["degraded"] is (not m._TORCH_AVAILABLE or not m._TORCHSDE_AVAILABLE)

    def test_emits_log_record(self, caplog):
        from dreambuddy_evolution.engines import sde_solver as m

        with caplog.at_level(logging.INFO, logger=m.__name__):
            m.log_runtime_backends()
        assert any("backend" in r.getMessage().lower() for r in caplog.records)


class TestBackendSelectionTorchsde:
    """torch+torchsde 可用 + 模型已激活 → Level 1 后端 == torchsde。"""

    def test_backend_torchsde_when_available(self, monkeypatch):
        from dreambuddy_evolution.engines import sde_solver as m

        if not (m._TORCH_AVAILABLE and m._TORCHSDE_AVAILABLE):
            pytest.skip("torch/torchsde 不可用，无法验证 Level 1")
        from dreambuddy_evolution.agi_config import set_switch

        set_switch("enable_neural_sde", True)
        fake_model = types.SimpleNamespace(
            is_activated=True,
            torchsde_available=True,
            use_cross_attention=False,
            forecast=lambda state, horizon, n_paths, **kw: np.zeros((n_paths, horizon + 1)),
        )
        solver = m.SDESolver()
        monkeypatch.setattr(solver, "_get_neural_sde_model", lambda: fake_model)
        solver.neural_sde_forecast(np.array([100.0, 0.02]), horizon=5, n_paths=5)
        assert solver._sde_backend_used == "torchsde"
