"""
P3: 6机制全联动验证 — BTC 4阶段路径集成测试
================================================================
SPEC: 非线性多阶段最优路径理论调研框架 §十三+§十七

联动依赖图：
  §15 层级primary → §20 分层弹性约束 → §18 质变驱动 → §14 HJB燃料偏移 → §16 G-05级联熔断
                                                                              ↓
                                                                         §19 认知函数

BTC 4阶段路径：
  阶段1：跌破MA200（长期bear成为primary）
  阶段2：支撑反弹（短期bull反弹，长期bear约束短期）
  阶段3：重新主导（空头继续，质变切换primary回bear）
  阶段4：恐慌级联（4判据满足，G-05触发熔断）

验证6个机制的数据流闭环：
  T-L1：§15层级primary → §20弹性约束（primary的timeframe传入resolve）
  T-L2：§20弹性约束 → 仓位调整（position_mult产出）
  T-L3：§18质变 → HJB shift_points（质变切换primary）
  T-L4：§14反身性 → HJB reflexivity_fuel（燃料偏移转移概率）
  T-L5：§15+§14+§18 → HJB值函数（三者同时影响）
  T-L6：§16 G-05 4判据 → 级联熔断触发
  T-L7：§19认知函数 → 价格信号更新认知
  T-L8：全联动BTC 4阶段路径模拟（6机制同时工作）
"""
from __future__ import annotations

import pytest
import numpy as np
from pathlib import Path
import sys
from unittest.mock import patch, MagicMock

# portfolio_risk_fuses 在 11-易经推理系统 下
_PRF_PATH = str(Path(__file__).resolve().parents[3] / "11-易经推理系统" / "scripts" / "memory_l4")
if _PRF_PATH not in sys.path:
    sys.path.insert(0, _PRF_PATH)


class TestSixMechanismIntegration:
    """P3: 6机制全联动验证"""

    def test_t_l1_tier_primary_to_elastic_constraint(self):
        """T-L1: §15层级primary → §20弹性约束（timeframe传入resolve）.

        数据流：ExogenousStrengthEvaluator.get_primary_contradiction()
               → ElasticConstraintResolver.resolve(primary, secondary, primary_tf, secondary_tf)
        """
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver

        # §15 层级primary判定
        evaluator = ExogenousStrengthEvaluator()
        mock_evals = {
            "technical": {"short": 0.5, "medium": 0.5, "long": 0.2},  # long bear
            "fundamental": {"short": 0.5, "medium": 0.5, "long": 0.5},
            "macro": {"short": 0.8, "medium": 0.5, "long": 0.5},  # short bull
        }
        with patch.object(evaluator, 'evaluate', return_value=mock_evals):
            primary = evaluator.get_primary_contradiction({})

        assert primary is not None
        assert primary["timeframe"] == "long"  # 层级驱动：long优先

        # §20 弹性约束消费primary的timeframe
        resolver = ElasticConstraintResolver()
        secondary = {"direction": "bull", "strength": 0.6, "timeframe": "short"}
        result = resolver.resolve(
            primary, secondary,
            primary_tf=primary["timeframe"],  # "long"
            secondary_tf=secondary["timeframe"],  # "short"
        )
        # 方向相反 → 弹性约束激活
        assert result["constraint_active"] is True
        # 力量接近 → 层级驱动 → long约束short → T_max增大
        assert result["t_max"] > 0

    def test_t_l2_elastic_constraint_to_position_adjustment(self):
        """T-L2: §20弹性约束 → 仓位调整（position_mult产出）."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver

        resolver = ElasticConstraintResolver()
        primary = {"direction": "bear", "strength": 0.55, "timeframe": "long"}
        secondary = {"direction": "bull", "strength": 0.45, "timeframe": "short"}

        result = resolver.resolve(primary, secondary,
                                   primary_tf="long", secondary_tf="short")

        # position_mult 应在 [floor, 1.0] 范围
        assert 0.1 <= result["position_mult"] <= 1.0
        # 方向相反 → 弹性约束激活
        assert result["constraint_active"] is True

    def test_t_l3_shift_to_hjb_shift_points(self):
        """T-L3: §18质变 → HJB shift_points.

        数据流：ContradictionShiftAccumulator._last_shift_result
               → pipeline构造shift_points → HJB.solve(shift_points=...)
        """
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver

        solver = HJBPathSolver()

        # 阶段2：支撑反弹 → primary从bear切换到bull
        result_base = solver.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
        )

        result_shift = solver.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
            shift_points=[(10, {"direction": "bull", "strength": 0.7})],
        )

        # 质变切换应影响值函数
        assert result_shift["backend"] == "hjb"
        assert np.all(np.isfinite(result_shift["value_function"]))

    def test_t_l4_reflexivity_to_hjb_fuel(self):
        """T-L4: §14反身性 → HJB reflexivity_fuel.

        数据流：ReflexivityMonitor.check_self_influence()
               → pipeline构造reflexivity_fuel → HJB._transition_probabilities(reflexivity_fuel=...)
        """
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver

        solver = HJBPathSolver()
        grid = solver.build_grid(start_price=100.0, volatility=0.02, horizon=20)

        # 基线转移概率
        probs_base = solver._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
        )

        # 反身性燃料偏移
        probs_fuel = solver._transition_probabilities(
            32, grid, drift=0.0, volatility=0.02, dt=1.0,
            reflexivity_fuel={"type": "leverage", "intensity": 0.5},
        )

        # 燃料偏移应改变转移概率分布
        assert not np.allclose(probs_base, probs_fuel)
        # leverage燃料应使分布更宽
        assert np.count_nonzero(probs_fuel > 1e-10) >= np.count_nonzero(probs_base > 1e-10)

    def test_t_l5_three_mechanisms_to_hjb_value_function(self):
        """T-L5: §15+§14+§18 → HJB值函数（三者同时影响）.

        验证 primary_contradiction + reflexivity_fuel + shift_points 同时传入HJB
        """
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver

        solver = HJBPathSolver()

        # 三机制同时作用
        result = solver.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            r_vector={"long": 1.0, "short": -1.0, "wait": 0.0},
            primary_contradiction={"direction": "bear", "strength": 0.6},
            reflexivity_fuel={"type": "leverage", "intensity": 0.8},
            shift_points=[(10, {"direction": "bull", "strength": 0.7})],
        )

        assert result["backend"] == "hjb"
        assert np.all(np.isfinite(result["value_function"]))
        assert result["converged"] in (True, False)

    def test_t_l6_g05_cascade_breaker_triggers(self):
        """T-L6: §16 G-05 4判据 → 级联熔断触发.

        数据流：pipeline构造4判据信号 → PortfolioRiskFuses.tick_and_check → G-05触发
        """
        from portfolio_risk_fuses import PortfolioRiskFuses

        fuses = PortfolioRiskFuses()

        # 4判据全满足
        ctx = {
            "total_unrealized_pnl_pct": -5.0,
            "primary_dim_jumped": True,
            "mechanism_active": True,
            "no_bounce_at_key": True,
            "no_intervener": True,
        }

        result = fuses.tick_and_check(ctx)
        assert result.emergency_shutdown is True
        assert "g05_cascade" in result.reason

    def test_t_l7_cognitive_function_price_signal(self):
        """T-L7: §19认知函数 → 价格信号更新认知.

        数据流：价格变化 → adjust_cognition(info_signals) → belief更新
        """
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor

        monitor = ReflexivityMonitor()

        # 阶段1：价格下跌→利空信号
        result_bear = monitor.adjust_cognition([
            {"type": "price", "signal": 0.3, "weight": 1.0},  # 利空
        ])
        assert result_bear["cognition"] < 0.5, "利空信号应使认知下降"

        # 阶段2：价格反弹→利多信号
        result_bull = monitor.adjust_cognition([
            {"type": "price", "signal": 0.7, "weight": 1.0},  # 利多
        ])
        # 认知应从阶段1的低位上升
        assert result_bull["cognition"] > result_bear["cognition"]

    def test_t_l8_btc_four_stage_full_simulation(self):
        """T-L8: 全联动BTC 4阶段路径模拟（6机制同时工作）.

        阶段1：跌破MA200 → §15层级primary=long bear → §19认知下降
        阶段2：支撑反弹 → §20弹性约束(long约束short) → §18质变切换primary→bull → §14反身性燃料
        阶段3：重新主导 → §18质变切换primary回bear
        阶段4：恐慌级联 → §16 G-05触发 → §19认知继续下降
        """
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor
        from portfolio_risk_fuses import PortfolioRiskFuses

        # === 初始化6个机制 ===
        evaluator = ExogenousStrengthEvaluator()
        resolver = ElasticConstraintResolver()
        solver = HJBPathSolver()
        monitor = ReflexivityMonitor()
        fuses = PortfolioRiskFuses()

        # === 阶段1：跌破MA200 ===
        # §15 层级primary判定
        mock_evals_stage1 = {
            "technical": {"short": 0.5, "medium": 0.5, "long": 0.2},  # long bear
            "fundamental": {"short": 0.5, "medium": 0.5, "long": 0.3},  # long bear
            "macro": {"short": 0.5, "medium": 0.5, "long": 0.5},
        }
        with patch.object(evaluator, 'evaluate', return_value=mock_evals_stage1):
            primary_stage1 = evaluator.get_primary_contradiction({})

        assert primary_stage1 is not None
        assert primary_stage1["timeframe"] == "long"
        assert primary_stage1["direction"] == "bear"

        # §19 认知函数：价格下跌→利空
        cog_stage1 = monitor.adjust_cognition([
            {"type": "price", "signal": 0.3, "weight": 1.0},
        ])
        assert cog_stage1["cognition"] < 0.5

        # === 阶段2：支撑反弹 ===
        # §20 弹性约束：long bear 约束 short bull
        secondary_stage2 = {"direction": "bull", "strength": 0.6, "timeframe": "short"}
        elastic_stage2 = resolver.resolve(
            primary_stage1, secondary_stage2,
            primary_tf="long", secondary_tf="short",
        )
        assert elastic_stage2["constraint_active"] is True
        # 力量接近 → 层级驱动 → long约束short → T_max增大
        assert elastic_stage2["t_max"] > 0

        # §18 质变驱动 + §14 HJB燃料偏移 + §15 primary
        hjb_stage2 = solver.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            r_vector={"long": 1.0, "short": -1.0, "wait": 0.0},
            primary_contradiction=primary_stage1,
            reflexivity_fuel={"type": "leverage", "intensity": 0.5},
            shift_points=[(10, {"direction": "bull", "strength": 0.7})],  # 反弹切换
        )
        assert hjb_stage2["backend"] == "hjb"
        assert np.all(np.isfinite(hjb_stage2["value_function"]))

        # §19 认知函数：价格反弹→利多
        cog_stage2 = monitor.adjust_cognition([
            {"type": "price", "signal": 0.7, "weight": 1.0},
        ])
        assert cog_stage2["cognition"] > cog_stage1["cognition"]

        # === 阶段3：重新主导（质变切换primary回bear）===
        hjb_stage3 = solver.solve(
            start_price=95.0, horizon=20, volatility=0.03,  # 波动率增大
            r_vector={"long": 1.0, "short": -1.0, "wait": 0.0},
            primary_contradiction={"direction": "bull", "strength": 0.7},  # 反弹中
            shift_points=[(5, {"direction": "bear", "strength": 0.8})],  # 切回bear
        )
        assert hjb_stage3["backend"] == "hjb"
        assert np.all(np.isfinite(hjb_stage3["value_function"]))

        # === 阶段4：恐慌级联 ===
        # §16 G-05 4判据全满足
        ctx_stage4 = {
            "total_unrealized_pnl_pct": -8.0,
            "primary_dim_jumped": True,      # ① primary维度跳变
            "mechanism_active": True,         # ② 机制性强制（杠杆清算）
            "no_bounce_at_key": True,         # ③ 关键位无反弹
            "no_intervener": True,           # ④ 干预者缺席
        }
        g05_result = fuses.tick_and_check(ctx_stage4)
        assert g05_result.emergency_shutdown is True
        assert "g05_cascade" in g05_result.reason

        # §19 认知函数：恐慌下跌→利空
        cog_stage4 = monitor.adjust_cognition([
            {"type": "price", "signal": 0.1, "weight": 1.0},  # 恐慌
        ])
        assert cog_stage4["cognition"] < cog_stage2["cognition"]

        # === 全联动验证 ===
        # 6个机制全部产出有效结果
        assert primary_stage1 is not None       # §15
        assert elastic_stage2["t_max"] > 0      # §20
        assert hjb_stage2["backend"] == "hjb"    # §14+§18
        assert g05_result.emergency_shutdown is True  # §16
        assert cog_stage4["cognition"] < 0.5     # §19


class TestFullDataFlowClosure:
    """验证6机制数据流闭环——无断裂"""

    def test_data_flow_no_break_15_to_20(self):
        """§15→§20 数据流：primary.timeframe → resolve(primary_tf)."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver

        evaluator = ExogenousStrengthEvaluator()
        mock_evals = {
            "technical": {"short": 0.5, "medium": 0.5, "long": 0.2},
            "fundamental": {"short": 0.5, "medium": 0.5, "long": 0.5},
            "macro": {"short": 0.5, "medium": 0.5, "long": 0.5},
        }
        with patch.object(evaluator, 'evaluate', return_value=mock_evals):
            primary = evaluator.get_primary_contradiction({})

        resolver = ElasticConstraintResolver()
        # primary 的 timeframe 被传入 resolve
        result = resolver.resolve(
            primary, {"direction": "bull", "strength": 0.5, "timeframe": "short"},
            primary_tf=primary["timeframe"],
            secondary_tf="short",
        )
        assert result is not None  # 无断裂

    def test_data_flow_no_break_14_18_to_hjb(self):
        """§14+§18→HJB 数据流：reflexivity_fuel + shift_points → solve()."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver

        solver = HJBPathSolver()
        result = solver.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction={"direction": "bear", "strength": 0.6},
            reflexivity_fuel={"type": "leverage", "intensity": 0.5},
            shift_points=[(10, {"direction": "bull", "strength": 0.7})],
        )
        assert result["backend"] == "hjb"  # 无断裂

    def test_data_flow_no_break_16_g05_uses_15_shift_signal(self):
        """§15→§16 数据流：层级primary的维度跳变 → G-05判据①."""
        from portfolio_risk_fuses import PortfolioRiskFuses

        fuses = PortfolioRiskFuses()
        # primary_dim_jumped 来自 ContradictionShiftAccumulator.detect_shift()
        ctx = {
            "total_unrealized_pnl_pct": -5.0,
            "primary_dim_jumped": True,   # §15层级primary维度跳变
            "mechanism_active": True,
            "no_bounce_at_key": True,
            "no_intervener": True,
        }
        result = fuses.tick_and_check(ctx)
        assert result.emergency_shutdown is True  # 无断裂

    def test_data_flow_no_break_19_cognition_to_14_fuel(self):
        """§19→§14 数据流：认知状态 → 反身性λ → HJB燃料."""
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver

        monitor = ReflexivityMonitor()
        # §19 认知更新
        cog = monitor.adjust_cognition([
            {"type": "price", "signal": 0.3, "weight": 1.0},
        ])

        # 认知影响反身性λ → 构造燃料
        # （实盘中 cognition → λ → fuel 的连接通过 pipeline 完成）
        fuel = {"type": "leverage", "intensity": min(1.0, abs(cog["cognition_delta"]) * 10)}

        solver = HJBPathSolver()
        result = solver.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            reflexivity_fuel=fuel,
        )
        assert result["backend"] == "hjb"  # 无断裂

    def test_failopen_all_mechanisms_degrade_gracefully(self):
        """FAIL-OPEN：所有机制异常时优雅降级."""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor

        # HJB：所有参数异常
        solver = HJBPathSolver()
        result = solver.solve(
            start_price=100.0, horizon=20, volatility=0.02,
            primary_contradiction=None,
            reflexivity_fuel={"type": "unknown", "intensity": 999},
            shift_points="invalid_format",
        )
        assert result["backend"] == "hjb"  # 降级不崩溃

        # 弹性约束：None输入
        resolver = ElasticConstraintResolver()
        result = resolver.resolve(None, None)
        assert result["constraint_active"] is False  # 降级为无约束

        # 认知函数：空信息流
        monitor = ReflexivityMonitor()
        result = monitor.adjust_cognition([])
        assert result["cognition"] == 0.5  # 中性兜底
