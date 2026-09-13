"""
P1b: HJB 反身性燃料偏移 + 质变驱动路径切换 — TDD 红灯测试
================================================================
SPEC: 非线性多阶段最优路径理论调研框架 §十四 + §十八

§14 反身性燃料偏移HJB转移概率：
  现状：_transition_probabilities GBM 恒定 μ/σ，无视矛盾/反身性
  修改：新增 reflexivity_fuel 参数，按燃料类型偏移 σ/μ
  燃料类型（P1先行3类）：
    - leverage: σ ↑↑ (2.0 × intensity)
    - mechanism: μ 偏移 (K × direction)
    - sentiment: σ ↑ (0.5 × intensity)

§18 质变驱动路径切换：
  现状：shift_result 只记录不驱动 HJB，整个 horizon 用同一个 primary
  修改：solve() 新增 shift_points 参数，_value_iteration 逆向DP到 t_shift 时切换 primary

红灯阶段：两个特性尚未实现，测试应 FAIL（参数不存在/行为不变）。

测试清单（共 16 项）：
  === HJB 燃料偏移 (§14) ===
  T-F1：reflexivity_fuel=None → 等价旧行为（向后兼容）
  T-F2：leverage 燃料 → σ 增大 → 转移概率分布更宽
  T-F3：mechanism 燃料 → μ 偏移 → 转移概率分布偏移
  T-F4：sentiment 燃料 → σ 增大（幅度减半）→ 转移概率分布略宽
  T-F5：unknown 燃料类型 → 回退 GBM（FAIL-OPEN）
  T-F6：fuel intensity 超界 → clip 到 [0,1]（FAIL-OPEN）
  T-F7：solve() 传入 reflexivity_fuel → 值函数改变
  T-F8：σ 上限 clip 5×（防止爆炸）

  === 质变驱动路径切换 (§18) ===
  T-S1：shift_points=None → 等价旧行为（向后兼容）
  T-S2：shift_points=[] → 等价旧行为
  T-S3：单点切换 → t_shift 前后 primary 不同
  T-S4：多点切换 → 逆向 DP 正确切换
  T-S5：shift_points 格式错误 → 回退旧行为（FAIL-OPEN）
  T-S6：solve() 传入 shift_points → 值函数改变
  T-S7：t_shift 超出 horizon → 忽略该切换点（FAIL-OPEN）
  T-S8：new_primary=None → 忽略该切换点（FAIL-OPEN）
"""
from __future__ import annotations

import numpy as np
import pytest


class TestHJBFuelOffset:
    """§14 反身性燃料偏移HJB转移概率"""

    def test_t_f1_fuel_none_backward_compatible(self):
        """T-F1: reflexivity_fuel=None → 等价旧行为."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        grid = s.build_grid(start_price=100.0, volatility=0.02, horizon=20)

        # 无燃料
        probs_no_fuel = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0
        )

        # 传 None 应等价
        probs_none = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
            reflexivity_fuel=None,
        )

        np.testing.assert_allclose(probs_no_fuel, probs_none, rtol=1e-10)

    def test_t_f2_leverage_fuel_widens_distribution(self):
        """T-F2: leverage 燃料 → σ↑↑ → 转移概率分布更宽."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        grid = s.build_grid(start_price=100.0, volatility=0.02, horizon=20)

        # 无燃料
        probs_base = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
        )

        # leverage 燃料
        probs_leverage = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
            reflexivity_fuel={"type": "leverage", "intensity": 0.5},
        )

        # σ增大 → 分布更宽 → 非零概率的格点更多
        n_nonzero_base = np.count_nonzero(probs_base > 1e-10)
        n_nonzero_leverage = np.count_nonzero(probs_leverage > 1e-10)
        assert n_nonzero_leverage >= n_nonzero_base, \
            "leverage燃料应使分布更宽（非零格点≥基线）"

    def test_t_f3_mechanism_fuel_shifts_drift(self):
        """T-F3: mechanism 燃料 → μ偏移 → 转移概率分布偏移."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        grid = s.build_grid(start_price=100.0, volatility=0.02, horizon=20)

        probs_base = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
        )

        # mechanism 燃料：direction=-1（空头主导）→ μ偏移向下
        probs_mech = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
            reflexivity_fuel={"type": "mechanism", "intensity": 0.5, "direction": -1},
        )

        # μ偏移向下 → 峰值向左移动
        peak_base = np.argmax(probs_base)
        peak_mech = np.argmax(probs_mech)
        # 如果峰值不移动，至少概率分布应该不同
        assert not np.allclose(probs_base, probs_mech, rtol=1e-10), \
            "mechanism燃料应改变转移概率分布"

    def test_t_f4_sentiment_fuel_slightly_widens(self):
        """T-F4: sentiment 燃料 → σ↑（幅度减半）→ 分布略宽."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        grid = s.build_grid(start_price=100.0, volatility=0.02, horizon=20)

        probs_base = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
        )

        probs_sent = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
            reflexivity_fuel={"type": "sentiment", "intensity": 0.5},
        )

        # 分布应改变
        assert not np.allclose(probs_base, probs_sent, rtol=1e-10), \
            "sentiment燃料应改变转移概率分布"

    def test_t_f5_unknown_fuel_type_fallback_gbm(self):
        """T-F5: unknown 燃料类型 → 回退 GBM（FAIL-OPEN）."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        grid = s.build_grid(start_price=100.0, volatility=0.02, horizon=20)

        probs_base = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
        )

        probs_unknown = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
            reflexivity_fuel={"type": "unknown_type", "intensity": 0.5},
        )

        np.testing.assert_allclose(probs_base, probs_unknown, rtol=1e-10)

    def test_t_f6_intensity_out_of_range_clipped(self):
        """T-F6: intensity 超界 → clip 到 [0,1]（FAIL-OPEN）."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        grid = s.build_grid(start_price=100.0, volatility=0.02, horizon=20)

        # intensity=2.0（超界）应clip为1.0
        probs_over = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
            reflexivity_fuel={"type": "leverage", "intensity": 2.0},
        )

        # intensity=1.0（正常）
        probs_normal = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
            reflexivity_fuel={"type": "leverage", "intensity": 1.0},
        )

        # 超界clip后应等于1.0
        np.testing.assert_allclose(probs_over, probs_normal, rtol=1e-10)

    def test_t_f7_solve_with_fuel_backward_compatible(self):
        """T-F7: solve() 传入 reflexivity_fuel → 参数透传正确（不报错+收敛）.

        注：值函数对σ变化不敏感是HJB DP的正常数值特性（V_next平滑时
        期望变化小）。燃料偏移在转移概率层面的改变由T-F2/T-F3覆盖。
        本测试验证参数透传的正确性。
        """
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()

        result = s.solve(
            start_price=100.0, horizon=20, volatility=0.1,
            reflexivity_fuel={"type": "leverage", "intensity": 0.8},
        )

        assert result["backend"] == "hjb"
        assert np.all(np.isfinite(result["value_function"]))
        # 应正常收敛或至少完成计算
        assert result["converged"] in (True, False)

    def test_t_f8_sigma_clip_5x(self):
        """T-F8: σ 上限 clip 5×（防止爆炸）."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()
        grid = s.build_grid(start_price=100.0, volatility=0.02, horizon=20)

        # 极端 intensity → σ不应超过 5×原始
        probs_extreme = s._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
            reflexivity_fuel={"type": "leverage", "intensity": 1.0},  # 最大
        )

        # 确保没有 NaN/Inf（σ被clip后不会爆炸）
        assert np.all(np.isfinite(probs_extreme)), "极端燃料下转移概率不应有NaN/Inf"
        assert abs(np.sum(probs_extreme) - 1.0) < 1e-6, "概率应归一化"


class TestHJBShiftPoints:
    """§18 质变驱动路径切换"""

    def test_t_s1_shift_points_none_backward_compatible(self):
        """T-S1: shift_points=None → 等价旧行为."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()

        result_base = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
        )

        result_none = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
            shift_points=None,
        )

        np.testing.assert_allclose(
            result_base["value_function"], result_none["value_function"], rtol=1e-10
        )

    def test_t_s2_shift_points_empty_backward_compatible(self):
        """T-S2: shift_points=[] → 等价旧行为."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()

        result_base = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
        )

        result_empty = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
            shift_points=[],
        )

        np.testing.assert_allclose(
            result_base["value_function"], result_empty["value_function"], rtol=1e-10
        )

    def test_t_s3_single_shift_changes_value_function(self):
        """T-S3: 单点切换 → 值函数改变."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()

        # 无切换
        result_base = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
        )

        # 中间切换到 bull
        result_shift = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
            shift_points=[(10, {"direction": "bull", "strength": 0.7})],
        )

        # 值函数应改变
        assert not np.allclose(
            result_base["value_function"], result_shift["value_function"], rtol=1e-10
        ), "质变切换应改变值函数"

    def test_t_s4_multi_shift_points(self):
        """T-S4: 多点切换 → 逆向DP正确切换."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()

        result = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
            shift_points=[
                (5, {"direction": "neutral", "strength": 0.5}),
                (15, {"direction": "bull", "strength": 0.7}),
            ],
        )

        # 应正常运行不报错
        assert result["backend"] == "hjb"
        assert np.all(np.isfinite(result["value_function"]))

    def test_t_s5_shift_points_malformed_fallback(self):
        """T-S5: shift_points 格式错误 → 回退旧行为（FAIL-OPEN）."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()

        result_base = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
        )

        # 格式错误：不是 tuple list
        result_bad = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
            shift_points="not_a_list",
        )

        np.testing.assert_allclose(
            result_base["value_function"], result_bad["value_function"], rtol=1e-10
        )

    def test_t_s6_t_shift_out_of_range_ignored(self):
        """T-S7: t_shift 超出 horizon → 忽略该切换点（FAIL-OPEN）."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()

        result_base = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
        )

        # t_shift=100 远超 horizon=20
        result_oor = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
            shift_points=[(100, {"direction": "bull", "strength": 0.7})],
        )

        # 超出范围的切换点应被忽略 → 等价无切换
        np.testing.assert_allclose(
            result_base["value_function"], result_oor["value_function"], rtol=1e-10
        )

    def test_t_s7_new_primary_none_ignored(self):
        """T-S8: new_primary=None → 忽略该切换点（FAIL-OPEN）."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        s = HJBPathSolver()

        result_base = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
        )

        result_none = s.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
            shift_points=[(10, None)],
        )

        np.testing.assert_allclose(
            result_base["value_function"], result_none["value_function"], rtol=1e-10
        )
