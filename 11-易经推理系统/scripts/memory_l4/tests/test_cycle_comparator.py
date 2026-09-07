"""TC9: 双窗口周期比对测试。

验证 CycleComparator.compare 6 种共振状态判定 + 强度乘数 + final 合成字段，
以及 FAIL-OPEN 中性默认。
对应 Spec §四 Step 6（7d+30d 双窗口共振校验）。
"""
import pytest
import sys
from pathlib import Path

# 将 memory_l4 加入 sys.path（force_vector 包所在目录）
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.models import CycleComparison
from force_vector.cycle_comparator import CycleComparator


class TestCycleComparatorResonance:
    """TC9: 7d+30d 同向 → resonance，strength_multiplier=1.2。"""

    def test_same_direction_positive_resonance(self):
        """7d=0.5, 30d=0.4 同向（同正）→ resonance, ×1.2。"""
        cc = CycleComparator()
        result = cc.compare(
            direction_7d=0.5, direction_30d=0.4,
            magnitude_7d=0.6, magnitude_30d=0.5,
        )
        assert isinstance(result, CycleComparison)
        assert result.resonance_state == "resonance"
        assert result.strength_multiplier == pytest.approx(1.2, abs=1e-6)

    def test_same_direction_negative_resonance(self):
        """7d=-0.5, 30d=-0.4 同向（同负）→ resonance, ×1.2。"""
        cc = CycleComparator()
        result = cc.compare(
            direction_7d=-0.5, direction_30d=-0.4,
            magnitude_7d=0.6, magnitude_30d=0.5,
        )
        assert result.resonance_state == "resonance"
        assert result.strength_multiplier == pytest.approx(1.2, abs=1e-6)


class TestCycleComparatorDivergence:
    """TC9: 7d+30d 反向 → divergence，×0.6。"""

    def test_opposite_direction_divergence(self):
        """7d=0.5, 30d=-0.4 反向 → divergence, ×0.6。

        短期强逆行（|7d|>=|30d|）判定为背离。
        """
        cc = CycleComparator()
        result = cc.compare(
            direction_7d=0.5, direction_30d=-0.4,
            magnitude_7d=0.6, magnitude_30d=0.5,
        )
        assert result.resonance_state == "divergence"
        assert result.strength_multiplier == pytest.approx(0.6, abs=1e-6)


class TestCycleComparatorObservation:
    """TC9: 双窗口中性 → observation，×0.3。"""

    def test_both_neutral_observation(self):
        """7d=0.0, 30d=0.0 双窗口中性 → observation, ×0.3。"""
        cc = CycleComparator()
        result = cc.compare(
            direction_7d=0.0, direction_30d=0.0,
            magnitude_7d=0.0, magnitude_30d=0.0,
        )
        assert result.resonance_state == "observation"
        assert result.strength_multiplier == pytest.approx(0.3, abs=1e-6)


class TestCycleComparatorOtherStates:
    """其余共振状态：emerging / persistent / turning。"""

    def test_emerging_short_dir_long_neutral(self):
        """7d 有方向 + 30d 中性 → emerging, ×0.9。"""
        cc = CycleComparator()
        result = cc.compare(
            direction_7d=0.5, direction_30d=0.0,
            magnitude_7d=0.6, magnitude_30d=0.5,
        )
        assert result.resonance_state == "emerging"
        assert result.strength_multiplier == pytest.approx(0.9, abs=1e-6)

    def test_persistent_short_neutral_long_dir(self):
        """7d 中性 + 30d 有方向 → persistent, ×1.0。"""
        cc = CycleComparator()
        result = cc.compare(
            direction_7d=0.0, direction_30d=0.5,
            magnitude_7d=0.6, magnitude_30d=0.5,
        )
        assert result.resonance_state == "persistent"
        assert result.strength_multiplier == pytest.approx(1.0, abs=1e-6)

    def test_turning_long_stronger_short_weak_opposite(self):
        """反向且长期更强（|30d|>|7d|）→ turning, ×0.7。

        长趋势仍强、短期刚开始弱转 → 转折信号。
        """
        cc = CycleComparator()
        result = cc.compare(
            direction_7d=-0.2, direction_30d=0.5,
            magnitude_7d=0.3, magnitude_30d=0.7,
        )
        assert result.resonance_state == "turning"
        assert result.strength_multiplier == pytest.approx(0.7, abs=1e-6)


class TestCycleComparatorFinalFields:
    """final_direction / final_magnitude 合成字段。"""

    def test_final_direction_uses_30d(self):
        """final_direction 取 30d 为主。"""
        cc = CycleComparator()
        result = cc.compare(
            direction_7d=0.5, direction_30d=0.4,
            magnitude_7d=0.6, magnitude_30d=0.5,
        )
        assert result.final_direction == pytest.approx(0.4, abs=1e-6)

    def test_final_magnitude_is_30d_times_multiplier(self):
        """final_magnitude = magnitude_30d × strength_multiplier。"""
        cc = CycleComparator()
        result = cc.compare(
            direction_7d=0.5, direction_30d=0.4,
            magnitude_7d=0.6, magnitude_30d=0.5,
        )
        assert result.final_magnitude == pytest.approx(0.5 * 1.2, abs=1e-6)
