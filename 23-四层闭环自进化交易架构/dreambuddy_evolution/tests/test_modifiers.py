"""
TDD RED Phase 2: 三修饰子测试 (§1.9.4 公式)
R_sentiment 非线性 80/20 + R_capital 资金流方向 + 三角验证①
"""
import pytest
import math


class TestRSentimentModifier:
    """R_sentiment 非线性 80/20 逆向修饰子 (§1.9.4)"""

    def test_extreme_greed_reduces_reflexivity(self):
        """R_sentiment > 0.8 → 逆向减分（巴菲特：别人贪婪我恐慌）"""
        from dreambuddy_evolution.engines.modifiers import apply_sentiment_modifier
        r_refl = 0.70
        result = apply_sentiment_modifier(r_refl, sentiment=0.90, beta=0.2)
        assert result < r_refl  # 极度贪婪 → 减分

    def test_extreme_fear_increases_reflexivity(self):
        """R_sentiment < 0.2 → 逆向加分（巴菲特：别人恐慌我贪婪）"""
        from dreambuddy_evolution.engines.modifiers import apply_sentiment_modifier
        r_refl = 0.50
        result = apply_sentiment_modifier(r_refl, sentiment=0.10, beta=0.2)
        assert result > r_refl  # 极度恐慌 → 加分

    def test_normal_range_follows_sentiment(self):
        """0.2 ≤ sentiment ≤ 0.8 → 顺向增强（偏离中性越远增强越多）"""
        from dreambuddy_evolution.engines.modifiers import apply_sentiment_modifier
        r_refl = 0.50
        # sentiment=0.6 → 偏离0.5=0.1 → 顺向小幅增强
        result = apply_sentiment_modifier(r_refl, sentiment=0.60, beta=0.2)
        assert result >= r_refl  # 正常区间偏热 → 小幅加分

    def test_neutral_sentiment_no_change(self):
        """sentiment=0.5 → 不修饰"""
        from dreambuddy_evolution.engines.modifiers import apply_sentiment_modifier
        r_refl = 0.65
        result = apply_sentiment_modifier(r_refl, sentiment=0.50, beta=0.2)
        assert abs(result - r_refl) < 1e-9

    def test_crash_returns_original(self):
        """sentiment None/crash → 返回原值（不修饰 = 等价 baseline）"""
        from dreambuddy_evolution.engines.modifiers import apply_sentiment_modifier
        r_refl = 0.70
        result = apply_sentiment_modifier(r_refl, sentiment=None, beta=0.2)
        assert abs(result - r_refl) < 1e-9

    def test_clamp_to_unit_interval(self):
        """修饰后结果 ∈ [0, 1]"""
        from dreambuddy_evolution.engines.modifiers import apply_sentiment_modifier
        for s in [0.0, 0.1, 0.5, 0.9, 1.0]:
            result = apply_sentiment_modifier(0.95, sentiment=s, beta=0.2)
            assert 0.0 <= result <= 1.0

    def test_beta_cap_020(self):
        """β 上限 = 0.2（§1.9.6 硬约束）"""
        from dreambuddy_evolution.engines.modifiers import apply_sentiment_modifier
        r_refl = 0.50
        # β=0.2 时最大修饰幅度 = 0.2 × (0.2/0.2) = 0.2 → r_refl ± 0.2
        result_fear = apply_sentiment_modifier(r_refl, sentiment=0.0, beta=0.2)
        result_greed = apply_sentiment_modifier(r_refl, sentiment=1.0, beta=0.2)
        # 最大变化不超过 0.2 × r_refl
        assert abs(result_fear - r_refl) <= 0.2 * r_refl + 0.01
        assert abs(result_greed - r_refl) <= 0.2 * r_refl + 0.01


class TestRCapitalModifier:
    """R_capital 资金流方向修饰子 (§1.9.4)"""

    def test_inflow_reduces_upward_resistance(self):
        """资金净流入 → 降低 R_up（上涨阻力减小）"""
        from dreambuddy_evolution.engines.modifiers import apply_capital_modifier
        r_up = 0.70
        result = apply_capital_modifier(r_up, capital_flow=0.80, gamma=0.2)
        assert result < r_up  # 流入 → 减小上涨阻力

    def test_outflow_reduces_downward_resistance(self):
        """资金净流出 → 降低 R_down（下跌阻力减小）"""
        from dreambuddy_evolution.engines.modifiers import apply_capital_modifier
        r_down = 0.70
        result = apply_capital_modifier(r_down, capital_flow=-0.80, gamma=0.2)
        assert result < r_down  # 流出 → 减小下跌阻力

    def test_neutral_flow_no_change(self):
        """capital_flow=0 → 不修饰"""
        from dreambuddy_evolution.engines.modifiers import apply_capital_modifier
        r_up = 0.65
        result = apply_capital_modifier(r_up, capital_flow=0.0, gamma=0.2)
        assert abs(result - r_up) < 1e-9

    def test_crash_returns_original(self):
        """capital_flow None → 返回原值"""
        from dreambuddy_evolution.engines.modifiers import apply_capital_modifier
        r_up = 0.70
        result = apply_capital_modifier(r_up, capital_flow=None, gamma=0.2)
        assert abs(result - r_up) < 1e-9

    def test_clamp_to_unit_interval(self):
        """修饰后 ∈ [0, 1]"""
        from dreambuddy_evolution.engines.modifiers import apply_capital_modifier
        for cf in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            result = apply_capital_modifier(0.95, capital_flow=cf, gamma=0.2)
            assert 0.0 <= result <= 1.0

    def test_gamma_cap_020(self):
        """γ 上限 = 0.2"""
        from dreambuddy_evolution.engines.modifiers import apply_capital_modifier
        r_up = 0.80
        result = apply_capital_modifier(r_up, capital_flow=1.0, gamma=0.2)
        # 最大减小 = 0.2 × 1.0 = 0.2 → r_up × (1 - 0.2) = 0.64
        assert abs(result - 0.64) < 0.01


class TestNarrativeModifier:
    """R_narrative 叙事驱动力修饰子 + 三角验证① (§1.9.4)"""

    def test_narrative_with_capital_enhances_flow(self):
        """叙事 + 资金验证 → 增强 R_flow"""
        from dreambuddy_evolution.engines.modifiers import apply_narrative_modifier
        r_flow = 0.50
        result = apply_narrative_modifier(
            r_flow, narrative=0.80, capital=0.70, alpha=0.2
        )
        assert result > r_flow  # 叙事+资金 → 增强

    def test_narrative_without_capital_discounted(self):
        """叙事 + 资金缺失 → 叙事打折（capital_validation=0.3）"""
        from dreambuddy_evolution.engines.modifiers import apply_narrative_modifier
        r_flow = 0.50
        result_with = apply_narrative_modifier(
            r_flow, narrative=0.80, capital=0.70, alpha=0.2
        )
        result_without = apply_narrative_modifier(
            r_flow, narrative=0.80, capital=0.20, alpha=0.2
        )
        assert result_with > result_without  # 有资金验证 > 无资金验证

    def test_no_narrative_no_change(self):
        """narrative=0 → 不修饰"""
        from dreambuddy_evolution.engines.modifiers import apply_narrative_modifier
        r_flow = 0.55
        result = apply_narrative_modifier(r_flow, narrative=0.0, capital=0.5, alpha=0.2)
        assert abs(result - r_flow) < 1e-9

    def test_crash_returns_original(self):
        """narrative None → 返回原值"""
        from dreambuddy_evolution.engines.modifiers import apply_narrative_modifier
        r_flow = 0.60
        result = apply_narrative_modifier(r_flow, narrative=None, capital=0.5, alpha=0.2)
        assert abs(result - r_flow) < 1e-9

    def test_alpha_cap_020(self):
        """α 上限 = 0.2"""
        from dreambuddy_evolution.engines.modifiers import apply_narrative_modifier
        r_flow = 0.50
        result = apply_narrative_modifier(r_flow, narrative=1.0, capital=1.0, alpha=0.2)
        # 最大 = 0.50 × (1 + 0.2 × 1.0 × 1.0) = 0.60
        assert abs(result - 0.60) < 0.01


class TestApplyAllModifiers:
    """三修饰子联合应用测试"""

    def test_all_zero_degrades_to_baseline(self):
        """α=β=γ=0 → 完全退化为 5 维 baseline（零风险回退）"""
        from dreambuddy_evolution.engines.modifiers import apply_all_modifiers
        r_vector = {
            "R_up": 0.60, "R_down": 0.55, "R_smooth": 0.30,
            "R_flow": 0.65, "R_reflexivity": 0.50,
        }
        result = apply_all_modifiers(
            r_vector,
            sentiment=0.8, capital_flow=0.7, narrative=0.9,
            alpha=0.0, beta=0.0, gamma=0.0,
        )
        # 完全不变
        for key in r_vector:
            assert abs(result[key] - r_vector[key]) < 1e-9

    def test_all_active_no_crash(self):
        """三修饰子全部激活 → 不崩溃 + 结果 ∈ [0,1]"""
        from dreambuddy_evolution.engines.modifiers import apply_all_modifiers
        r_vector = {
            "R_up": 0.60, "R_down": 0.55, "R_smooth": 0.30,
            "R_flow": 0.65, "R_reflexivity": 0.50,
        }
        result = apply_all_modifiers(
            r_vector,
            sentiment=0.85, capital_flow=0.8, narrative=0.7,
            alpha=0.2, beta=0.2, gamma=0.2,
        )
        for key in ["R_up", "R_down", "R_smooth", "R_flow", "R_reflexivity"]:
            assert key in result
            assert 0.0 <= result[key] <= 1.0

    def test_smooth_never_modified(self):
        """R_smooth 永远不被修饰（无对应修饰子）"""
        from dreambuddy_evolution.engines.modifiers import apply_all_modifiers
        r_vector = {
            "R_up": 0.60, "R_down": 0.55, "R_smooth": 0.42,
            "R_flow": 0.65, "R_reflexivity": 0.50,
        }
        result = apply_all_modifiers(
            r_vector,
            sentiment=1.0, capital_flow=1.0, narrative=1.0,
            alpha=0.2, beta=0.2, gamma=0.2,
        )
        assert abs(result["R_smooth"] - 0.42) < 1e-9  # 不变
