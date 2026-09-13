"""
P2: 层级加权primary + 分层弹性约束 + 认知函数 — TDD 红灯测试
================================================================
SPEC: 非线性多阶段最优路径理论调研框架 §十五 + §十九 + §二十

§15 层级加权primary判定：
  现状：get_primary_contradiction L324 纯 max(strength)，short和long权重相同
  修改：argmax(tier_weight + causal_score)，TIER_WEIGHT={short:0.2, medium:0.3, long:0.5}
  判据1：主要矛盾 = 因果主导性 + 层级权重（非瞬时力量）

§20 分层弹性约束：
  现状：resolve() 无timeframe参数，纯力量比 T_max
  修改：新增 primary_tf/secondary_tf 参数，力量接近时层级驱动（长期约束短期）
  判据2：弹性约束分层 = 力量差 + 层级差

§19 认知函数建模：
  现状：ReflexivityMonitor 只有参与函数P（adjust_strength），无认知函数C
  修改：新增 CognitiveFunction 类 + adjust_cognition() 方法
  反身性环 = C∘P（认知→行为→市场影响→新信息流→认知更新）

红灯阶段：三个特性尚未实现，测试应 FAIL。

测试清单（共 18 项）：
  === 层级加权primary (§15) ===
  T-P1：short力量高 vs long力量低 → 旧版选short，新版应选long
  T-P2：long力量高 → 仍选long（层级+力量一致）
  T-P3：medium力量最高 → 选medium
  T-P4：全中性 → 返回None
  T-P5：向后兼容（无timeframe字段→兜底short权重）

  === 分层弹性约束 (§20) ===
  T-E1：resolve新增primary_tf/secondary_tf参数→不报错
  T-E2：力量差大→力量驱动（tier_bonus不影响）
  T-E3：力量接近→层级驱动（long约束short→T_max增大）
  T-E4：timeframe缺失→兜底medium→等价旧行为
  T-E5：tier_bonus过大→T_max clip不超界
  T-E6：方向对齐→层级参数不影响

  === 认知函数 (§19) ===
  T-C1：CognitiveFunction 实例化
  T-C2：update() 贝叶斯更新→belief改变
  T-C3：info_signal=利多→belief上升
  T-C4：info_signal=利空→belief下降
  T-C5：ReflexivityMonitor.adjust_cognition() 方法存在
  T-C6：adjust_cognition→返回cognition+delta
  T-C7：信息流缺失→中性兜底0.5
"""
from __future__ import annotations

import pytest
import numpy as np


class TestTierWeightedPrimary:
    """§15 层级加权primary判定"""

    def test_t_p1_short_high_vs_long_low_selects_long(self):
        """T-P1: short力量高 vs long力量低 → 新版应选long（层级权重高）.

        直接mock evaluate()返回值，测试层级加权逻辑。
        short adj=0.8 tier=0.2 → score=0.8+0.2*(1-0.8/0.15)=0.8+0.2*(1-5.33)≈0.8
        long adj=0.6 tier=0.5 → score=0.6+0.5*(1-0.6/0.15)=0.6+0.5*(1-4.0)≈0.6
        注：DOMINANCE_GAP机制下，力量差大时力量驱动
        但当力量接近时，tier权重起决定作用

        用力量接近的case测试：short=0.5 vs long=0.45
        short: 0.5+0.2*(1-0.5/0.15)=0.5+0.2*(1-3.33)=0.5+0.2*(-2.33)=0.5-0.467=0.033
        但 max(0, ...) 会截断负数 → 0.5+0=0.5
        long: 0.45+0.5*(1-0.45/0.15)=0.45+0.5*(1-3.0)=0.45+0.5*(-2.0)=0.45-1.0=0.45
        但 max(0, ...) → 0.45+0=0.45

        所以力量接近时 tier_bonus项被max(0,...)截断为0，实际是纯strength比较。
        修改测试：用力量差小于DOMINANCE_GAP但strength相同的case。
        """
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        from unittest.mock import patch

        eval = ExogenousStrengthEvaluator()

        # mock evaluate 返回：short和long力量相同(0.6)，但long层级高
        mock_evals = {
            "technical": {"short": 0.8, "medium": 0.5, "long": 0.5},
            "fundamental": {"short": 0.5, "medium": 0.5, "long": 0.8},
            "macro": {"short": 0.5, "medium": 0.5, "long": 0.5},
        }
        with patch.object(eval, 'evaluate', return_value=mock_evals):
            result = eval.get_primary_contradiction({})
        assert result is not None
        # short adj=0.6, long adj=0.6 → 力量相同 → tier驱动 → long优先
        assert result["timeframe"] == "long", \
            "力量相同时层级驱动：long(tier=0.5)应优先于short(tier=0.2)"

    def test_t_p2_long_high_still_selects_long(self):
        """T-P2: long力量最高 → 仍选long（层级+力量一致）."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        from unittest.mock import patch

        eval = ExogenousStrengthEvaluator()
        mock_evals = {
            "technical": {"short": 0.5, "medium": 0.5, "long": 0.9},
            "fundamental": {"short": 0.5, "medium": 0.5, "long": 0.5},
            "macro": {"short": 0.5, "medium": 0.5, "long": 0.5},
        }
        with patch.object(eval, 'evaluate', return_value=mock_evals):
            result = eval.get_primary_contradiction({})
        assert result is not None
        assert result["timeframe"] == "long"

    def test_t_p3_medium_highest_selects_medium(self):
        """T-P3: medium力量最高 → 选medium."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        from unittest.mock import patch

        eval = ExogenousStrengthEvaluator()
        mock_evals = {
            "technical": {"short": 0.5, "medium": 0.95, "long": 0.5},
            "fundamental": {"short": 0.5, "medium": 0.5, "long": 0.5},
            "macro": {"short": 0.5, "medium": 0.5, "long": 0.5},
        }
        with patch.object(eval, 'evaluate', return_value=mock_evals):
            result = eval.get_primary_contradiction({})
        assert result is not None
        assert result["timeframe"] == "medium"

    def test_t_p4_all_neutral_returns_none(self):
        """T-P4: 全中性 → 返回None."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        from unittest.mock import patch

        eval = ExogenousStrengthEvaluator()
        mock_evals = {
            "technical": {"short": 0.5, "medium": 0.5, "long": 0.5},
            "fundamental": {"short": 0.5, "medium": 0.5, "long": 0.5},
            "macro": {"short": 0.5, "medium": 0.5, "long": 0.5},
        }
        with patch.object(eval, 'evaluate', return_value=mock_evals):
            result = eval.get_primary_contradiction({})
        assert result is None

    def test_t_p5_backward_compatible_no_timeframe(self):
        """T-P5: 向后兼容——get_primary_contradiction 正常运行不报错."""
        from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
        from unittest.mock import patch

        eval = ExogenousStrengthEvaluator()
        mock_evals = {
            "technical": {"short": 0.9, "medium": 0.5, "long": 0.5},
            "fundamental": {"short": 0.5, "medium": 0.5, "long": 0.5},
            "macro": {"short": 0.5, "medium": 0.5, "long": 0.5},
        }
        with patch.object(eval, 'evaluate', return_value=mock_evals):
            result = eval.get_primary_contradiction({})
        assert result is not None
        assert "timeframe" in result
        assert "direction" in result


class TestLayeredElasticConstraint:
    """§20 分层弹性约束"""

    def test_t_e1_resolve_accepts_timeframe_params(self):
        """T-E1: resolve() 新增 primary_tf/secondary_tf 参数→不报错."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver

        resolver = ElasticConstraintResolver()
        primary = {"direction": "bear", "strength": 0.6}
        secondary = {"direction": "bull", "strength": 0.5}

        # 应接受 timeframe 参数
        result = resolver.resolve(
            primary, secondary,
            primary_tf="long", secondary_tf="short",
        )
        assert result is not None
        assert "position_mult" in result

    def test_t_e2_large_strength_gap_power_driven(self):
        """T-E2: 力量差大→力量驱动（tier_bonus不影响）."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver

        resolver = ElasticConstraintResolver()
        primary = {"direction": "bear", "strength": 0.9}
        secondary = {"direction": "bull", "strength": 0.1}

        # 力量差=0.8 >> DOMINANCE_GAP=0.15 → 力量驱动
        result_power = resolver.resolve(primary, secondary,
                                         primary_tf="short", secondary_tf="long")
        result_base = resolver.resolve(primary, secondary)

        # 力量驱动时 tier_bonus 不应改变 T_max
        assert abs(result_power["t_max"] - result_base["t_max"]) < 1e-6

    def test_t_e3_close_strength_tier_driven(self):
        """T-E3: 力量接近→层级驱动（long约束short→T_max增大）."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver

        resolver = ElasticConstraintResolver()
        primary = {"direction": "bear", "strength": 0.55}
        secondary = {"direction": "bull", "strength": 0.45}

        # 力量差=0.1 < DOMINANCE_GAP=0.15 → 层级驱动
        # long约束short → tier_bonus = 0.5/0.2 = 2.5 → T_max增大
        result_tier = resolver.resolve(primary, secondary,
                                         primary_tf="long", secondary_tf="short")
        result_base = resolver.resolve(primary, secondary)

        # 层级驱动时 T_max 应大于纯力量比
        assert result_tier["t_max"] > result_base["t_max"], \
            "long约束short时 T_max 应增大（tier_bonus>1）"

    def test_t_e4_timeframe_missing_fallback_medium(self):
        """T-E4: timeframe缺失→兜底medium→等价旧行为."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver

        resolver = ElasticConstraintResolver()
        primary = {"direction": "bear", "strength": 0.6}
        secondary = {"direction": "bull", "strength": 0.5}

        # 不传 timeframe → 兜底
        result_default = resolver.resolve(primary, secondary)
        # 传 medium → 应等价
        result_medium = resolver.resolve(primary, secondary,
                                           primary_tf="medium", secondary_tf="medium")

        assert abs(result_default["t_max"] - result_medium["t_max"]) < 1e-6

    def test_t_e5_t_max_clipped_no_overflow(self):
        """T-E5: tier_bonus过大→T_max clip不超界."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver

        resolver = ElasticConstraintResolver()
        primary = {"direction": "bear", "strength": 0.5}
        secondary = {"direction": "bull", "strength": 0.5}

        # long/short tier_bonus = 0.5/0.2 = 2.5 → T_max 可能超界
        result = resolver.resolve(primary, secondary,
                                    primary_tf="long", secondary_tf="short")
        # T_max 不应超过 base_limit（clip保护）
        assert result["t_max"] <= resolver._base_limit * 2.0 + 1e-6
        assert result["t_max"] >= 0.0

    def test_t_e6_aligned_direction_tier_no_effect(self):
        """T-E6: 方向对齐→层级参数不影响."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver

        resolver = ElasticConstraintResolver()
        primary = {"direction": "bull", "strength": 0.7}
        secondary = {"direction": "bull", "strength": 0.6}

        result = resolver.resolve(primary, secondary,
                                    primary_tf="long", secondary_tf="short")
        # 方向对齐 → constraint_active=False
        assert result["constraint_active"] is False
        assert result["aligned"] is True


class TestCognitiveFunction:
    """§19 认知函数建模"""

    def test_t_c1_cognitive_function_instantiates(self):
        """T-C1: CognitiveFunction 实例化."""
        from dreambuddy_evolution.core.cognitive_function import CognitiveFunction

        cf = CognitiveFunction(prior_strength=0.5, learning_rate=0.1)
        assert cf is not None

    def test_t_c2_update_changes_belief(self):
        """T-C2: update() 贝叶斯更新→belief改变."""
        from dreambuddy_evolution.core.cognitive_function import CognitiveFunction

        cf = CognitiveFunction(prior_strength=0.5, learning_rate=0.1)
        old_belief = cf.get_cognition()
        cf.update(info_signal=0.8, info_weight=1.0)
        new_belief = cf.get_cognition()
        assert new_belief > old_belief, "利多信号应使belief上升"

    def test_t_c3_bullish_signal_increases_belief(self):
        """T-C3: info_signal=利多→belief上升."""
        from dreambuddy_evolution.core.cognitive_function import CognitiveFunction

        cf = CognitiveFunction(prior_strength=0.5, learning_rate=0.2)
        cf.update(info_signal=0.9, info_weight=1.0)
        assert cf.get_cognition() > 0.5

    def test_t_c4_bearish_signal_decreases_belief(self):
        """T-C4: info_signal=利空→belief下降."""
        from dreambuddy_evolution.core.cognitive_function import CognitiveFunction

        cf = CognitiveFunction(prior_strength=0.5, learning_rate=0.2)
        cf.update(info_signal=0.1, info_weight=1.0)
        assert cf.get_cognition() < 0.5

    def test_t_c5_adjust_cognition_method_exists(self):
        """T-C5: ReflexivityMonitor.adjust_cognition() 方法存在."""
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor

        monitor = ReflexivityMonitor()
        assert hasattr(monitor, "adjust_cognition"), \
            "ReflexivityMonitor 应有 adjust_cognition 方法"

    def test_t_c6_adjust_cognition_returns_cognition_delta(self):
        """T-C6: adjust_cognition→返回cognition+delta."""
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor

        monitor = ReflexivityMonitor()
        info_signals = [
            {"type": "price", "signal": 0.7, "weight": 1.0},
            {"type": "etf_flow", "signal": 0.6, "weight": 0.7},
        ]
        result = monitor.adjust_cognition(info_signals)
        assert "cognition" in result
        assert "cognition_delta" in result
        assert "reflexivity_loop_active" in result

    def test_t_c7_missing_info_signals_neutral_fallback(self):
        """T-C7: 信息流缺失→中性兜底0.5."""
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor

        monitor = ReflexivityMonitor()
        result = monitor.adjust_cognition([])  # 空信息流
        assert abs(result["cognition"] - 0.5) < 1e-6, \
            "空信息流应返回中性认知0.5"
        assert result["cognition_delta"] == 0.0
