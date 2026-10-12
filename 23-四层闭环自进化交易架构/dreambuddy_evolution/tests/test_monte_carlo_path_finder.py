"""
P1-1 RED: MonteCarloPathFinder 组件契约测试
来源: SPEC v0.3 §2.B — 从 deep_reasoning_engine.py 拆出蒙特卡洛+最小阻力路径职责

拆分目标:
- monte_carlo_paths(start_price, horizon, n_paths, volatility)->list[np.ndarray]
- compute_path_resistance(path)->float
- find_min_resistance_path(paths)->dict (含 best_path / best_resistance / backend / converged)
"""
from __future__ import annotations

import numpy as np
import pytest


class TestMonteCarloPathFinderContract:
    """MonteCarloPathFinder 接口契约 — RED 阶段断言模块尚未创建"""

    def test_module_importable(self):
        from dreambuddy_evolution.engines.monte_carlo_path_finder import MonteCarloPathFinder  # noqa: F401

    def test_class_instantiates(self):
        from dreambuddy_evolution.engines.monte_carlo_path_finder import MonteCarloPathFinder
        finder = MonteCarloPathFinder()
        assert finder is not None


class TestMonteCarloPaths:
    """monte_carlo_paths 返回路径列表"""

    def test_returns_list_of_arrays(self):
        from dreambuddy_evolution.engines.monte_carlo_path_finder import MonteCarloPathFinder
        finder = MonteCarloPathFinder()
        paths = finder.monte_carlo_paths(start_price=100.0, horizon=10, n_paths=50, volatility=0.02)
        assert isinstance(paths, list)
        assert len(paths) == 50
        assert all(isinstance(p, np.ndarray) for p in paths)


class TestComputePathResistance:
    """compute_path_resistance 返回 float"""

    def test_returns_float(self):
        from dreambuddy_evolution.engines.monte_carlo_path_finder import MonteCarloPathFinder
        finder = MonteCarloPathFinder()
        path = np.array([100.0, 101.0, 102.0, 103.0])
        resistance = finder.compute_path_resistance(path)
        assert isinstance(resistance, float)


class TestFindMinResistancePath:
    """find_min_resistance_path 返回 dict"""

    def test_returns_dict_with_required_keys(self):
        from dreambuddy_evolution.engines.monte_carlo_path_finder import MonteCarloPathFinder
        finder = MonteCarloPathFinder()
        paths = [np.array([100.0, 101.0, 102.0]), np.array([100.0, 99.0, 98.0])]
        result = finder.find_min_resistance_path(paths)
        assert isinstance(result, dict)
        assert "best_path" in result
        assert "best_resistance" in result
        assert "backend" in result
        assert "converged" in result
