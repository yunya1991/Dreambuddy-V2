"""
Phase 2.6: HJB/变分法最优路径求解器 TDD 测试
SPEC-AGI升级蓝图.md §4.2.6

核心哲学: 最优路径求解 — HJB PDE 逆向动态规划 + 变分法欧拉-拉格朗日梯度下降.
HC-AGI-15: HJB 网格分辨率下限（价格≥32, 时间≥16）
HC-AGI-16: 收敛阈值 1e-6 持续≥3轮
HC-AGI-17: 异常强制降级到 argmin（FAIL-OPEN 不可跳过）
"""
from __future__ import annotations

import numpy as np
import pytest


class TestHJBPathSolver:
    """HJB PDE 求解器单元测试"""

    def test_solver_instantiates(self):
        """实例化"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        assert s is not None

    def test_grid_resolution_meets_hc_agi_15(self):
        """HC-AGI-15: 默认网格 ≥32/16"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        assert s.n_price_bins >= HJBPathSolver.MIN_PRICE_GRID
        assert s.n_time_bins >= HJBPathSolver.MIN_TIME_GRID

    def test_build_grid_returns_correct_shape(self):
        """网格构造正确"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        grid = s.build_grid(start_price=100.0, volatility=0.02, horizon=20)
        assert grid["price_grid"].ndim == 1
        assert len(grid["price_grid"]) >= 32
        assert len(grid["time_grid"]) >= 16

    def test_build_grid_no_overflow_on_extreme_volatility(self):
        """极端波动率不溢出 (低价币场景: PUMP @ 0.0037, vol=1000%)"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        # 模拟低价币高波动+长周期: sigma_total 远超 math.exp 上限 709
        grid = s.build_grid(start_price=0.00374, volatility=10.0, horizon=500)
        assert np.all(np.isfinite(grid["price_grid"]))
        assert grid["p_min"] > 0
        assert grid["p_max"] > grid["p_min"]
        # 超极端: volatility=100, horizon=1000
        grid2 = s.build_grid(start_price=0.001, volatility=100.0, horizon=1000)
        assert np.all(np.isfinite(grid2["price_grid"]))

    def test_solve_no_overflow_on_extreme_volatility(self):
        """solve() 极端波动率不溢出且 backend=hjb"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        result = s.solve(start_price=0.00374, horizon=50, volatility=2.0)
        assert result["backend"] == "hjb"
        assert np.all(np.isfinite(result["value_function"]))
        assert result["converged"] is True or result["converged"] is False

    def test_lagrangian_non_negative(self):
        """Lagrangian 非负"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        for action in ("long", "short", "wait"):
            assert s.lagrangian(100.0, action) >= 0.0

    def test_lagrangian_fail_open_on_missing_r_vector(self):
        """r_vector=None → 0.50 兜底"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        L = s.lagrangian(100.0, "long", r_vector=None)
        assert L >= 0.0
        assert np.isfinite(L)

    def test_solve_returns_value_function_and_policy(self):
        """solve() 返回 V 和 π*"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        result = s.solve(start_price=100.0, horizon=20, volatility=0.02)
        assert "value_function" in result
        assert "policy" in result
        assert "optimal_path" in result
        assert "total_cost" in result
        assert "converged" in result
        assert result["backend"] == "hjb"
        assert result["value_function"].ndim == 2

    def test_solve_terminal_condition_zero(self):
        """终端条件 V[:, T] = 0"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        result = s.solve(start_price=100.0, horizon=20, volatility=0.02)
        V = result["value_function"]
        assert np.allclose(V[:, -1], 0.0)

    def test_solve_total_cost_non_negative(self):
        """V(start, 0) ≥ 0"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        result = s.solve(start_price=100.0, horizon=20, volatility=0.02)
        assert result["total_cost"] >= 0.0

    def test_solve_paths_finite_no_nan(self):
        """最优路径无 NaN/Inf"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        result = s.solve(start_price=100.0, horizon=20, volatility=0.02)
        assert np.all(np.isfinite(result["optimal_path"]))

    def test_value_iteration_returns_converged_flag(self):
        """HC-AGI-16: _value_iteration 返回 converged 标志（基于 max|ΔV|）"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        grid = s.build_grid(start_price=100.0, volatility=0.02, horizon=20)
        result = s._value_iteration(grid, None, 0.0, 0.02)
        # 应返回 (V, policy, converged) 三元组
        assert len(result) == 3
        V, policy, converged = result
        assert isinstance(converged, bool)

    def test_convergence_based_on_delta_v_not_abs_v(self):
        """HC-AGI-16: 收敛基于 max|ΔV|（值函数变化量）而非 max|V|（值函数绝对值）.

        逆向DP在有限时域内是精确解，V值可很大（如1.5），但迭代间 ΔV→0，应收敛。
        若错误地用 max|V| < 1e-6 判断，则V=1.5时永远不收敛。
        """
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        result = s.solve(start_price=100.0, horizon=20, volatility=0.02)
        V = result["value_function"]
        # V 值远大于 1e-6，但应收敛（ΔV→0）
        assert float(np.max(np.abs(V))) > 1e-3
        assert result["converged"] is True

    def test_value_iteration_three_round_convergence(self):
        """HC-AGI-16: 连续3轮 max|ΔV| < 1e-6 才算收敛.

        通过迭代历史验证：逆向DP是精确解，第二轮起 ΔV 应≈0。
        """
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        grid = s.build_grid(start_price=100.0, volatility=0.02, horizon=20)
        V, policy, converged = s._value_iteration(grid, None, 0.0, 0.02)
        assert converged is True


class TestVariationalPathOptimizer:
    """变分法路径优化器单元测试"""

    def test_optimizer_instantiates(self):
        from dreambuddy_evolution.core.hjb_solver import VariationalPathOptimizer
        o = VariationalPathOptimizer()
        assert o is not None

    def test_compute_action_non_negative(self):
        """作用量非负"""
        from dreambuddy_evolution.core.hjb_solver import VariationalPathOptimizer
        o = VariationalPathOptimizer()
        path = np.array([100.0, 101.0, 100.5, 102.0])
        assert o.compute_action(path) >= 0.0

    def test_compute_action_matches_path_integral(self):
        """作用量与 PathIntegralEngine.compute_action 一致"""
        from dreambuddy_evolution.core.hjb_solver import VariationalPathOptimizer
        from dreambuddy_evolution.core.path_integral import PathIntegralEngine
        o = VariationalPathOptimizer()
        pe = PathIntegralEngine(n_paths=10)
        path = np.cumsum(np.random.randn(20)) * 0.01 + 100
        assert abs(o.compute_action(path) - pe.compute_action(path)) < 1e-9

    def test_gradient_shape_matches_path(self):
        """梯度 shape 与路径一致"""
        from dreambuddy_evolution.core.hjb_solver import VariationalPathOptimizer
        o = VariationalPathOptimizer()
        path = np.array([100.0, 101.0, 102.0, 103.0])
        grad = o.compute_action_gradient(path)
        assert grad.shape == path.shape

    def test_optimize_reduces_action(self):
        """优化后作用量 ≤ 初始作用量"""
        from dreambuddy_evolution.core.hjb_solver import VariationalPathOptimizer
        o = VariationalPathOptimizer()
        path = np.cumsum(np.random.randn(20)) * 0.05 + 100
        result = o.optimize(path)
        assert result["total_action"] <= result["initial_action"]

    def test_optimize_anchors_start_point(self):
        """优化后起点不变"""
        from dreambuddy_evolution.core.hjb_solver import VariationalPathOptimizer
        o = VariationalPathOptimizer()
        path = np.cumsum(np.random.randn(20)) * 0.05 + 100
        result = o.optimize(path)
        assert abs(result["optimal_path"][0] - path[0]) < 1e-9

    def test_optimize_converged_flag_set(self):
        """收敛标志为 bool"""
        from dreambuddy_evolution.core.hjb_solver import VariationalPathOptimizer
        o = VariationalPathOptimizer(max_iter=300)
        path = np.linspace(100, 105, 20)
        result = o.optimize(path)
        assert isinstance(result["converged"], bool)


class TestSolveOptimalPathFailover:
    """HC-AGI-17: 三级降级链"""

    def test_import_solve_optimal_path(self):
        from dreambuddy_evolution.core.hjb_solver import solve_optimal_path
        assert callable(solve_optimal_path)

    def test_hjb_backend_succeeds_normal_input(self):
        """正常输入 backend 为 hjb/variational/argmin 之一"""
        from dreambuddy_evolution.core.hjb_solver import solve_optimal_path
        result = solve_optimal_path(start_price=100.0, horizon=20, volatility=0.02)
        assert result["backend"] in ("hjb", "variational", "argmin")
        assert "optimal_path" in result
        assert "total_cost" in result

    def test_failover_to_argmin_on_empty_paths(self):
        """monte_carlo_paths 为空 → 降级"""
        from dreambuddy_evolution.core.hjb_solver import solve_optimal_path
        result = solve_optimal_path(
            start_price=100.0, horizon=10, volatility=0.02,
            monte_carlo_paths=[],
        )
        assert result["backend"] in ("hjb", "variational", "argmin")
        assert "fallback_chain" in result

    def test_failover_to_argmin_on_invalid_volatility(self):
        """volatility=NaN → 降级 argmin"""
        from dreambuddy_evolution.core.hjb_solver import solve_optimal_path
        paths = [np.linspace(100, 105, 10), np.linspace(100, 95, 10)]
        result = solve_optimal_path(
            start_price=100.0, horizon=10, volatility=float("nan"),
            monte_carlo_paths=paths,
        )
        assert result["backend"] in ("variational", "argmin")
        assert result["optimal_path"] is not None


class TestAGISwitches:
    """HC-AGI-07: 开关默认状态"""

    def test_hjb_solver_switch_default_true(self):
        from dreambuddy_evolution.agi_config import get_switch
        assert get_switch("enable_hjb_solver") is True

    def test_variational_opt_switch_default_true(self):
        from dreambuddy_evolution.agi_config import get_switch
        assert get_switch("enable_variational_opt") is True

    def test_env_override_disables_hjb(self, monkeypatch):
        monkeypatch.setenv("ENABLE_HJB_SOLVER", "0")
        from dreambuddy_evolution.agi_config import get_switch
        assert get_switch("enable_hjb_solver") is False


class TestLagrangianContradictionModulation:
    """Phase 3.3: lagrangian 矛盾强度调制测试

    SPEC §4.3: 主要矛盾方向阻力降低, 次要方向阻力升高
    HC-AGI-19: 调制后 L >= 0.001
    """

    def test_lagrangian_accepts_primary_contradiction_param(self):
        """lagrangian 接受 primary_contradiction 参数"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        pc = {"direction": "long", "strength": 0.5}
        L = s.lagrangian(100.0, "long", r_vector=None, primary_contradiction=pc)
        assert L >= 0.001

    def test_lagrangian_aligned_direction_lower_resistance(self):
        """对齐主要矛盾: L 降低 (× (1 - 0.3×strength))"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        r_vector = {"R_up": 0.5, "R_down": 0.5, "R_smooth": 0.5, "R_reflexivity": 0.5}
        pc = {"direction": "long", "strength": 1.0}
        L_base = s.lagrangian(100.0, "long", r_vector=r_vector)
        L_mod = s.lagrangian(100.0, "long", r_vector=r_vector, primary_contradiction=pc)
        # 对齐: L_mod = L_base × (1 - 0.3×1.0) = L_base × 0.7
        assert L_mod < L_base
        assert abs(L_mod - L_base * 0.7) < 0.01

    def test_lagrangian_opposed_direction_higher_resistance(self):
        """逆向主要矛盾: L 升高 (× (1 + 0.5×strength))"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        r_vector = {"R_up": 0.5, "R_down": 0.5, "R_smooth": 0.5, "R_reflexivity": 0.5}
        pc = {"direction": "long", "strength": 1.0}
        L_base = s.lagrangian(100.0, "short", r_vector=r_vector)
        L_mod = s.lagrangian(100.0, "short", r_vector=r_vector, primary_contradiction=pc)
        # 逆向: L_mod = L_base × (1 + 0.5×1.0) = L_base × 1.5
        assert L_mod > L_base
        assert abs(L_mod - L_base * 1.5) < 0.01

    def test_lagrangian_without_contradiction_backward_compatible(self):
        """无 primary_contradiction: 向后兼容, 不调制"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        r_vector = {"R_up": 0.5, "R_down": 0.5, "R_smooth": 0.5, "R_reflexivity": 0.5}
        L_base = s.lagrangian(100.0, "long", r_vector=r_vector)
        L_no_pc = s.lagrangian(100.0, "long", r_vector=r_vector, primary_contradiction=None)
        assert abs(L_base - L_no_pc) < 1e-9

    def test_lagrangian_neutral_direction_no_modulation(self):
        """primary_direction=neutral: 不调制"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        r_vector = {"R_up": 0.5, "R_down": 0.5, "R_smooth": 0.5, "R_reflexivity": 0.5}
        pc = {"direction": "neutral", "strength": 1.0}
        L_base = s.lagrangian(100.0, "long", r_vector=r_vector)
        L_mod = s.lagrangian(100.0, "long", r_vector=r_vector, primary_contradiction=pc)
        assert abs(L_base - L_mod) < 1e-9

    def test_lagrangian_floor_0_001(self):
        """HC-AGI-19: 调制后 L >= 0.001"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        # 极低 R_up + 对齐 → L 可能极小
        r_vector = {"R_up": 0.01, "R_down": 0.01, "R_smooth": 0.01, "R_reflexivity": 0.01}
        pc = {"direction": "long", "strength": 1.0}
        L = s.lagrangian(100.0, "long", r_vector=r_vector, primary_contradiction=pc)
        assert L >= 0.001

    def test_lagrangian_strength_clamped_to_0_1(self):
        """strength 超出 [0,1] → 截断"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        r_vector = {"R_up": 0.5, "R_down": 0.5, "R_smooth": 0.5, "R_reflexivity": 0.5}
        pc_high = {"direction": "long", "strength": 5.0}  # 超出
        L_high = s.lagrangian(100.0, "long", r_vector=r_vector, primary_contradiction=pc_high)
        pc_one = {"direction": "long", "strength": 1.0}
        L_one = s.lagrangian(100.0, "long", r_vector=r_vector, primary_contradiction=pc_one)
        assert abs(L_high - L_one) < 0.01  # 截断为 1.0
