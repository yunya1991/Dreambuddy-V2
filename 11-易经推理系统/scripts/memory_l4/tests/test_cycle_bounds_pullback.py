"""T5 验收测试：预测曲线回拉（动作B，T_CB3）

位置: scripts/memory_l4/tests/test_cycle_bounds_pullback.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_cycle_bounds_pullback.py -v

对应 Spec §3bis.4.2 动作B + §3bis.9 T_CB3。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.morph_cycle_predictor import MorphCyclePredictor


def _make_predictor() -> MorphCyclePredictor:
    """构造 MorphCyclePredictor 实例（绕过 __init__ 的 storage 依赖）。"""
    return MorphCyclePredictor.__new__(MorphCyclePredictor)


# ================================================================
# T_CB3: 预测曲线回拉
# ================================================================

class TestPullbackOvershootUp:
    """验证越上界时被回拉。"""

    def test_single_point_overshoot_up(self):
        """v=4.5 越上界 0.5，回拉后 = 4.0 + 0.5 × 0.30 = 4.15。"""
        p = _make_predictor()
        bounds = {"level_lo": 3.5, "level_hi": 4.0, "decay_strength": 0.30}

        pulled, info = p._pullback_forecast([4.5], bounds)

        assert abs(pulled[0] - 4.15) < 0.01, f"期望 4.15，实际 {pulled[0]}"
        assert info["applied"] is True
        assert info["overshoot_count"] == 1

    def test_multiple_points_overshoot_up(self):
        """多个点越上界，每个都被回拉。"""
        p = _make_predictor()
        bounds = {"level_lo": 3.5, "level_hi": 4.0, "decay_strength": 0.30}

        pulled, info = p._pullback_forecast([4.5, 4.8, 5.0], bounds)

        assert abs(pulled[0] - 4.15) < 0.01
        assert abs(pulled[1] - 4.24) < 0.01   # 4.0 + 0.8 × 0.30
        assert abs(pulled[2] - 4.30) < 0.01   # 4.0 + 1.0 × 0.30
        assert info["overshoot_count"] == 3


class TestPullbackOvershootDown:
    """验证越下界时被回拉。"""

    def test_single_point_overshoot_down(self):
        """v=2.0 越下界 1.5，回拉后 = 3.5 - 1.5 × 0.30 = 3.05。"""
        p = _make_predictor()
        bounds = {"level_lo": 3.5, "level_hi": 4.0, "decay_strength": 0.30}

        pulled, info = p._pullback_forecast([2.0], bounds)

        assert abs(pulled[0] - 3.05) < 0.01, f"期望 3.05，实际 {pulled[0]}"
        assert info["applied"] is True
        assert info["overshoot_count"] == 1

    def test_multiple_points_overshoot_down(self):
        """多个点越下界，每个都被回拉。"""
        p = _make_predictor()
        bounds = {"level_lo": 3.5, "level_hi": 4.0, "decay_strength": 0.30}

        pulled, info = p._pullback_forecast([3.0, 2.0, 1.0], bounds)

        assert abs(pulled[0] - 3.35) < 0.01   # 3.5 - 0.5 × 0.30
        assert abs(pulled[1] - 3.05) < 0.01   # 3.5 - 1.5 × 0.30
        assert abs(pulled[2] - 2.75) < 0.01   # 3.5 - 2.5 × 0.30
        assert info["overshoot_count"] == 3


class TestPullbackNoOvershoot:
    """验证点在边界内时不回拉。"""

    def test_no_pullback_within_bounds(self):
        """v=3.8 在 [3.5, 4.0] 内，不回拉。"""
        p = _make_predictor()
        bounds = {"level_lo": 3.5, "level_hi": 4.0, "decay_strength": 0.30}

        pulled, info = p._pullback_forecast([3.8], bounds)

        assert abs(pulled[0] - 3.8) < 0.001
        assert info["applied"] is False
        assert info["overshoot_count"] == 0

    def test_no_pullback_at_boundary(self):
        """v=3.5 和 v=4.0 正好在边界上，不回拉。"""
        p = _make_predictor()
        bounds = {"level_lo": 3.5, "level_hi": 4.0, "decay_strength": 0.30}

        pulled, info = p._pullback_forecast([3.5, 4.0], bounds)

        assert abs(pulled[0] - 3.5) < 0.001
        assert abs(pulled[1] - 4.0) < 0.001
        assert info["applied"] is False
        assert info["overshoot_count"] == 0


class TestPullbackMixed:
    """验证混合越界和未越界点，只回拉越界点。"""

    def test_mixed_points(self):
        """混合：3.8（内）、4.5（越上）、2.0（越下）、3.9（内）。"""
        p = _make_predictor()
        bounds = {"level_lo": 3.5, "level_hi": 4.0, "decay_strength": 0.30}

        pulled, info = p._pullback_forecast([3.8, 4.5, 2.0, 3.9], bounds)

        assert abs(pulled[0] - 3.8) < 0.001   # 未越界
        assert abs(pulled[1] - 4.15) < 0.01   # 越上界
        assert abs(pulled[2] - 3.05) < 0.01   # 越下界
        assert abs(pulled[3] - 3.9) < 0.001    # 未越界
        assert info["applied"] is True
        assert info["overshoot_count"] == 2

    def test_empty_list(self):
        """空列表返回空，applied=False。"""
        p = _make_predictor()
        bounds = {"level_lo": 3.5, "level_hi": 4.0, "decay_strength": 0.30}

        pulled, info = p._pullback_forecast([], bounds)

        assert pulled == []
        assert info["applied"] is False
        assert info["overshoot_count"] == 0
