"""TC11/TC12: 弹性系数β计算器测试。

验证弹性系数β计算（价格响应衰减/放大检测）+ FAIL-OPEN。
对应 Spec §三-A Step 3-A-1 ElasticityBeta。

β = cov(ΔPrice, ΔForce) / var(ΔForce)   （OLS 回归斜率）
β_ratio = β_7d / β_30d
  β_ratio < 0.5 持续3天 → decay_signal=True, decay_days>=3
  β_ratio > 2.0 持续3天 → amplification_signal=True, amplification_days>=3
"""
import pytest
import sys
from pathlib import Path

# 将 memory_l4 注入 sys.path，使 force_vector.* 可导入
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.elasticity_beta_calculator import ElasticityBetaCalculator
from force_vector.models import ElasticityBeta


class TestElasticityBetaDecay:
    """TC11: β衰减检测。"""

    def test_decay_signal_triggered_when_beta_ratio_below_threshold_3_days(self):
        """β_7d/β_30d < 0.5 持续3天 → decay_signal=True, decay_days>=3。

        构造：
          price_7d  小（[0.01,0.005,0.002]，递减）
          force_7d  大（[0.10,0.08,0.06]，同向递减）→ β_7d = cov/var ~ 0.2
          price_30d 大（[0.04,0.03,0.02]*10）
          force_30d 小（[0.01]*30，恒定）→ var~0 → β_30d = 1.0（中性）
          β_ratio = 0.2 / 1.0 = 0.2 < 0.5
          decay_history = [0.3, 0.4, 0.45]  # 连续3天 <0.5
        """
        calc = ElasticityBetaCalculator()
        result = calc.compute(
            price_changes_7d=[0.01, 0.005, 0.002],
            force_changes_7d=[0.10, 0.08, 0.06],
            price_changes_30d=[0.04, 0.03, 0.02] * 10,
            force_changes_30d=[0.01] * 30,
            decay_history=[0.3, 0.4, 0.45],
        )

        assert isinstance(result, ElasticityBeta)
        # β_7d 为小值，β_30d 因力恒定为中性 1.0
        assert result.beta_7d < 0.5
        assert result.beta_30d == pytest.approx(1.0, rel=1e-6)
        # β_ratio < 0.5 → 衰减
        assert result.beta_ratio < 0.5
        assert result.decay_signal is True
        assert result.decay_days >= 3
        # 不应同时触发放大
        assert result.amplification_signal is False

    def test_decay_not_triggered_when_history_short(self):
        """历史不足3天 <0.5 → decay_signal=False。"""
        calc = ElasticityBetaCalculator()
        result = calc.compute(
            price_changes_7d=[0.01, 0.005, 0.002],
            force_changes_7d=[0.10, 0.08, 0.06],
            price_changes_30d=[0.04, 0.03, 0.02] * 10,
            force_changes_30d=[0.01] * 30,
            decay_history=[0.3, 0.4],  # 仅2天 <0.5
        )
        assert result.beta_ratio < 0.5
        assert result.decay_signal is False
        assert result.decay_days < 3


class TestElasticityBetaAmplification:
    """TC12: β放大检测（对称构造）。"""

    def test_amplification_signal_triggered_when_beta_ratio_above_threshold_3_days(self):
        """β_7d/β_30d > 2.0 持续3天 → amplification_signal=True。

        对称构造：
          price_7d  大（[0.04,0.03,0.02]，递减）
          force_7d  小（[0.01,0.008,0.006]，同向递减）→ β_7d ~ 5.0
          price_30d 小（[0.01,0.005,0.002]*10）
          force_30d 大（[0.01]*30，恒定）→ β_30d = 1.0（中性）
          β_ratio = 5.0 / 1.0 = 5.0 > 2.0
          decay_history = [2.5, 2.4, 2.3]  # 连续3天 >2.0
        """
        calc = ElasticityBetaCalculator()
        result = calc.compute(
            price_changes_7d=[0.04, 0.03, 0.02],
            force_changes_7d=[0.01, 0.008, 0.006],
            price_changes_30d=[0.01, 0.005, 0.002] * 10,
            force_changes_30d=[0.01] * 30,
            decay_history=[2.5, 2.4, 2.3],
        )

        assert isinstance(result, ElasticityBeta)
        # β_7d 为大值，β_30d 中性 1.0
        assert result.beta_7d > 2.0
        assert result.beta_30d == pytest.approx(1.0, rel=1e-6)
        # β_ratio > 2.0 → 放大
        assert result.beta_ratio > 2.0
        assert result.amplification_signal is True
        assert result.amplification_days >= 3
        # 不应同时触发衰减
        assert result.decay_signal is False


class TestElasticityBetaFailOpen:
    """FAIL-OPEN：异常时β=1.0（中性），decay_signal=False。"""

    def test_empty_inputs_return_neutral_beta(self):
        """空数据 → β=1.0，信号为False。"""
        calc = ElasticityBetaCalculator()
        result = calc.compute(
            price_changes_7d=[],
            force_changes_7d=[],
            price_changes_30d=[],
            force_changes_30d=[],
        )
        assert result.beta_7d == pytest.approx(1.0)
        assert result.beta_30d == pytest.approx(1.0)
        assert result.beta_ratio == pytest.approx(1.0)
        assert result.decay_signal is False
        assert result.amplification_signal is False

    def test_constant_force_returns_neutral_beta(self):
        """力向量无变化（var(ΔForce)~0）→ β=1.0。"""
        calc = ElasticityBetaCalculator()
        result = calc.compute(
            price_changes_7d=[0.01, 0.02, 0.03],
            force_changes_7d=[0.05, 0.05, 0.05],  # 恒定 → var~0
            price_changes_30d=[0.01] * 30,
            force_changes_30d=[0.05] * 30,        # 恒定 → var~0
        )
        assert result.beta_7d == pytest.approx(1.0)
        assert result.beta_30d == pytest.approx(1.0)
        assert result.beta_ratio == pytest.approx(1.0)
        assert result.decay_signal is False
        assert result.amplification_signal is False

    def test_mismatched_lengths_failopen(self):
        """价格与力序列长度不一致 → 该窗口 FAIL-OPEN β=1.0。"""
        calc = ElasticityBetaCalculator()
        result = calc.compute(
            price_changes_7d=[0.01, 0.02, 0.03],
            force_changes_7d=[0.05, 0.06],  # 长度不一致
            price_changes_30d=[0.01] * 30,
            force_changes_30d=[0.02] * 30,
        )
        assert result.beta_7d == pytest.approx(1.0)
        assert result.decay_signal is False

    def test_none_history_no_signal(self):
        """decay_history=None → 不产生信号，β正常计算。"""
        calc = ElasticityBetaCalculator()
        result = calc.compute(
            price_changes_7d=[0.01, 0.005, 0.002],
            force_changes_7d=[0.10, 0.08, 0.06],
            price_changes_30d=[0.04, 0.03, 0.02] * 10,
            force_changes_30d=[0.01] * 30,
            decay_history=None,
        )
        # β_ratio 仍 <0.5，但历史不足3天 → 无信号
        assert result.beta_ratio < 0.5
        assert result.decay_signal is False
        assert result.decay_days == 0
