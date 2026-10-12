"""
P1-1 RED: SDESolver 组件契约测试
来源: SPEC v0.3 §2.B — 从 deep_reasoning_engine.py 拆出 SDE+TimesFM+GARCH 时序动态建模职责

拆分目标（SDESolver 整合三个预测算法，同属"动态建模"算法域）:
- neural_sde_forecast(seed, horizon, n_paths, exogenous_factors, head_multipliers)->np.ndarray
- timesfm_predict(history, horizon)->np.ndarray
- _statistical_forecast(history, horizon)->np.ndarray
- status()->dict — 后端可用性 (neural_sde + timesfm)
"""
from __future__ import annotations

import numpy as np
import pytest


class TestSDESolverContract:
    """SDESolver 接口契约 — RED 阶段断言模块尚未创建"""

    def test_module_importable(self):
        from dreambuddy_evolution.engines.sde_solver import SDESolver  # noqa: F401

    def test_class_instantiates(self):
        from dreambuddy_evolution.engines.sde_solver import SDESolver
        solver = SDESolver()
        assert solver is not None


class TestNeuralSdeForecast:
    """neural_sde_forecast 返回路径数组"""

    def test_returns_2d_numpy_array(self):
        from dreambuddy_evolution.engines.sde_solver import SDESolver
        solver = SDESolver()
        seed = np.array([100.0, 0.02])
        paths = solver.neural_sde_forecast(seed, horizon=10, n_paths=50)
        assert isinstance(paths, np.ndarray)
        assert paths.ndim == 2

    def test_supports_head_multipliers_param(self):
        """head_multipliers 形参必须保留 — Phase 5 CrossValidationGate 接线"""
        from dreambuddy_evolution.engines.sde_solver import SDESolver
        solver = SDESolver()
        seed = np.array([100.0, 0.02])
        heads = np.array([1.0, 0.9, 0.8])
        paths = solver.neural_sde_forecast(seed, horizon=5, n_paths=10, head_multipliers=heads)
        assert isinstance(paths, np.ndarray)

    def test_supports_exogenous_factors_param(self):
        from dreambuddy_evolution.engines.sde_solver import SDESolver
        solver = SDESolver()
        seed = np.array([100.0, 0.02])
        exo = np.array([[0.1]] * 5)
        paths = solver.neural_sde_forecast(seed, horizon=5, n_paths=10, exogenous_factors=exo)
        assert isinstance(paths, np.ndarray)


class TestTimesFMPredict:
    """timesfm_predict 返回预测数组"""

    def test_returns_1d_numpy_array(self):
        from dreambuddy_evolution.engines.sde_solver import SDESolver
        solver = SDESolver()
        history = np.array([100.0, 101.0, 102.0, 103.0, 104.0] * 4)
        forecast = solver.timesfm_predict(history, horizon=10)
        assert isinstance(forecast, np.ndarray)
        assert forecast.ndim == 1


class TestBackendStatus:
    """status() 返回 neural_sde + timesfm 后端可用性"""

    def test_status_returns_dict_with_keys(self):
        from dreambuddy_evolution.engines.sde_solver import SDESolver
        solver = SDESolver()
        status = solver.status()
        assert isinstance(status, dict)
        assert "neural_sde" in status
        assert "timesfm" in status
        assert isinstance(status["timesfm"], bool)
