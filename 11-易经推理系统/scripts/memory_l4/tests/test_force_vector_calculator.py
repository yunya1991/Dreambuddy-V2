"""TC: 力向量计算器测试。

验证五维统计计算 + Kalman 平滑 + FAIL-OPEN。
对应 Spec §三 五维统计 / §四 Kalman 平滑。
"""
import pytest
import sys
from pathlib import Path

_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.force_vector_calculator import ForceVectorCalculator


class TestDaoDimension:
    """TC2: Z-score 统计计算。"""

    def test_zscore_increasing_data_positive_direction(self):
        """30天递增数据 → direction > 0, magnitude ∈ [0, 2]。"""
        calc = ForceVectorCalculator()
        data = [float(i) for i in range(1, 31)]  # 1..30 递增
        direction, magnitude = calc.compute_dao_dimension(data)
        assert direction > 0
        assert 0.0 <= magnitude <= 2.0

    def test_zscore_decreasing_data_negative_direction(self):
        """递减数据 → direction < 0。"""
        calc = ForceVectorCalculator()
        data = [float(30 - i) for i in range(30)]  # 30..1 递减
        direction, magnitude = calc.compute_dao_dimension(data)
        assert direction < 0

    def test_dao_dimension_failopen_on_short_data(self):
        """样本不足 → 返回中性默认 (0.0, 0.0)。"""
        calc = ForceVectorCalculator()
        direction, magnitude = calc.compute_dao_dimension([1.0])
        assert direction == pytest.approx(0.0)
        assert magnitude == pytest.approx(0.0)


class TestKalmanSmooth:
    """TC3: Kalman 平滑抑制单日跳变。"""

    def test_kalman_smooths_single_day_jump(self):
        """原始 [0.1,0.1,0.1,0.8,0.1,0.1] → kalman 跳变幅度 < 50% 原始。"""
        calc = ForceVectorCalculator()
        raw = [0.1, 0.1, 0.1, 0.8, 0.1, 0.1]
        kalman_dirs, _ = calc.kalman_smooth(raw)
        # 原始跳变：index 2→3 = 0.8 - 0.1 = 0.7
        raw_jump = raw[3] - raw[2]
        kalman_jump = kalman_dirs[3] - kalman_dirs[2]
        assert kalman_jump < 0.5 * raw_jump

    def test_kalman_returns_same_length(self):
        """输出长度与输入一致。"""
        calc = ForceVectorCalculator()
        raw = [0.1, 0.2, 0.3, 0.2, 0.1]
        kalman_dirs, _ = calc.kalman_smooth(raw)
        assert len(kalman_dirs) == len(raw)

    def test_kalman_smooths_magnitudes(self):
        """传入 magnitudes 时也返回平滑后的 magnitudes。"""
        calc = ForceVectorCalculator()
        dirs = [0.1, 0.1, 0.1, 0.8, 0.1, 0.1]
        mags = [0.1, 0.1, 0.1, 0.8, 0.1, 0.1]
        _, kalman_mags = calc.kalman_smooth(dirs, mags)
        assert len(kalman_mags) == len(mags)
        assert kalman_mags[3] < mags[3]

    def test_kalman_failopen_empty(self):
        """空输入 → 返回空列表。"""
        calc = ForceVectorCalculator()
        kalman_dirs, kalman_mags = calc.kalman_smooth([])
        assert kalman_dirs == []


class TestComputeAllFailOpen:
    """TC10: FAIL-OPEN 样本不足 → None。"""

    def test_compute_all_returns_none_when_sample_too_short(self):
        """样本 < 7 天 → compute_all 返回 None。"""
        calc = ForceVectorCalculator()
        short = [1.0, 2.0, 3.0]  # 仅3天
        result = calc.compute_all(
            dao_data=short, tian_data=short, di_data=short,
            jiang_data=short, fa_data=short,
        )
        assert result is None

    def test_compute_all_returns_dict_when_sufficient(self):
        """样本 >= 7 天 → 返回 dict（非 None）。"""
        calc = ForceVectorCalculator()
        data = [float(i) for i in range(1, 11)]  # 10天
        result = calc.compute_all(
            dao_data=data, tian_data=data, di_data=data,
            jiang_data=data, fa_data=data,
        )
        assert result is not None
        assert isinstance(result, dict)


class TestOtherDimensions:
    """验证其余四维方法返回合理 (direction, magnitude)。"""

    def test_tian_dimension_increasing(self):
        calc = ForceVectorCalculator()
        data = [float(i) for i in range(1, 31)]
        direction, magnitude = calc.compute_tian_dimension(data)
        assert -1.0 <= direction <= 1.0
        assert magnitude >= 0.0

    def test_di_dimension_increasing(self):
        calc = ForceVectorCalculator()
        data = [float(i) for i in range(1, 31)]
        direction, magnitude = calc.compute_di_dimension(data)
        assert -1.0 <= direction <= 1.0
        assert magnitude >= 0.0

    def test_jiang_dimension_increasing(self):
        calc = ForceVectorCalculator()
        data = [float(i) for i in range(1, 31)]
        direction, magnitude = calc.compute_jiang_dimension(data)
        assert -1.0 <= direction <= 1.0
        assert magnitude >= 0.0

    def test_fa_dimension(self):
        calc = ForceVectorCalculator()
        data = [float(i) for i in range(1, 31)]
        direction, magnitude = calc.compute_fa_dimension(data)
        assert -1.0 <= direction <= 1.0
        assert magnitude >= 0.0
