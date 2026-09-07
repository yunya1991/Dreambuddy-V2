"""TC14 + CBR背离: 阶段依赖性校准器测试。

验证阶段依赖性校准因子 + CBR背离检测。
对应 Spec §三-A Step 3-A-2 RegimeConditionalCalibrator。

adjustment_factor = E[r|event,regime_current] / E[r|event,all_regimes]
  若 |adjustment_factor| < 0.3 → 力向量强度 ×0.5
  若 |adjustment_factor| > 2.0 → 力向量强度 ×1.5
  方向相反（sign不同）→ 调整因子归零（反映冲突，触发 ×0.5 衰减）
  异常 → 1.0（不调整）

CBR背离：当前事件收益与历史同类事件收益方向相反（且历史均值|mean|>0.01，样本>=3）
"""
import pytest
import sys
from pathlib import Path

# 将 memory_l4 注入 sys.path，使 force_vector.* 可导入
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.regime_conditional_calibrator import RegimeConditionalCalibrator


class TestComputeAdjustment:
    """TC14: 阶段依赖性校准因子。"""

    def test_opposite_direction_adjustment_below_threshold(self):
        """E[r|event,regime_current]=+2.3, E[r|event,all]=-1.0 方向相反
        → |adjustment_factor| < 0.3（触发 ×0.5 衰减）。
        """
        cal = RegimeConditionalCalibrator()
        adj = cal.compute_adjustment(e_r_current=2.3, e_r_all=-1.0)
        assert abs(adj) < 0.3

    def test_same_direction_large_ratio_above_threshold(self):
        """同向 + regime 放大：2.3 / 1.0 = 2.3 > 2.0 → 触发 ×1.5 放大。"""
        cal = RegimeConditionalCalibrator()
        adj = cal.compute_adjustment(e_r_current=2.3, e_r_all=1.0)
        assert adj > 2.0

    def test_same_direction_small_ratio_below_threshold(self):
        """同向 + regime 衰减：0.2 / 1.0 = 0.2 < 0.3 → 触发 ×0.5 衰减。"""
        cal = RegimeConditionalCalibrator()
        adj = cal.compute_adjustment(e_r_current=0.2, e_r_all=1.0)
        assert abs(adj) < 0.3

    def test_same_direction_normal_ratio_no_adjustment(self):
        """同向 + 接近1：1.0 / 1.0 = 1.0 → 不触发任何调整（0.3≤|adj|≤2.0）。"""
        cal = RegimeConditionalCalibrator()
        adj = cal.compute_adjustment(e_r_current=1.0, e_r_all=1.0)
        assert 0.3 <= abs(adj) <= 2.0

    def test_negative_same_direction_large_ratio(self):
        """同向（均负）+ regime 放大：-2.3 / -1.0 = 2.3 > 2.0 → ×1.5。"""
        cal = RegimeConditionalCalibrator()
        adj = cal.compute_adjustment(e_r_current=-2.3, e_r_all=-1.0)
        assert abs(adj) > 2.0

    def test_zero_denominator_failopen(self):
        """E[r|event,all]=0（分母为0）→ FAIL-OPEN 返回 1.0（不调整）。"""
        cal = RegimeConditionalCalibrator()
        adj = cal.compute_adjustment(e_r_current=2.3, e_r_all=0.0)
        assert adj == pytest.approx(1.0)

    def test_exception_failopen_returns_one(self):
        """非法输入（None）→ FAIL-OPEN 返回 1.0。"""
        cal = RegimeConditionalCalibrator()
        adj = cal.compute_adjustment(e_r_current=None, e_r_all=1.0)
        assert adj == pytest.approx(1.0)


class TestCBRDivergence:
    """CBR背离检测：当前事件与历史同类事件方向相反。"""

    def test_divergence_detected_opposite_direction(self):
        """current=+0.5, historical=[-0.3,-0.4,-0.2] 均值-0.3 方向相反 → divergence=True。"""
        cal = RegimeConditionalCalibrator()
        result = cal.detect_cbr_divergence(
            current_result=0.5,
            historical_results=[-0.3, -0.4, -0.2],
        )
        assert result is True

    def test_no_divergence_same_direction(self):
        """current=+0.5, historical 均值+0.3 同向 → divergence=False。"""
        cal = RegimeConditionalCalibrator()
        result = cal.detect_cbr_divergence(
            current_result=0.5,
            historical_results=[0.3, 0.4, 0.2],
        )
        assert result is False

    def test_no_divergence_insufficient_samples(self):
        """样本<3 → divergence=False。"""
        cal = RegimeConditionalCalibrator()
        result = cal.detect_cbr_divergence(
            current_result=0.5,
            historical_results=[-0.3, -0.4],  # 仅2个样本
        )
        assert result is False

    def test_no_divergence_when_historical_mean_near_zero(self):
        """历史均值|mean|<0.01 → divergence=False（避免噪声误判）。"""
        cal = RegimeConditionalCalibrator()
        result = cal.detect_cbr_divergence(
            current_result=0.5,
            historical_results=[0.005, -0.003, 0.001],  # 均值≈0.001 < 0.01
        )
        assert result is False

    def test_divergence_negative_current_positive_history(self):
        """current=-0.5, historical 均值+0.3 方向相反 → divergence=True。"""
        cal = RegimeConditionalCalibrator()
        result = cal.detect_cbr_divergence(
            current_result=-0.5,
            historical_results=[0.3, 0.4, 0.2],
        )
        assert result is True

    def test_empty_history_no_divergence(self):
        """空历史 → divergence=False。"""
        cal = RegimeConditionalCalibrator()
        result = cal.detect_cbr_divergence(
            current_result=0.5,
            historical_results=[],
        )
        assert result is False

    def test_exception_failopen_returns_false(self):
        """非法输入 → FAIL-OPEN 返回 False。"""
        cal = RegimeConditionalCalibrator()
        result = cal.detect_cbr_divergence(
            current_result=None,
            historical_results=[0.3, 0.4, 0.2],
        )
        assert result is False
