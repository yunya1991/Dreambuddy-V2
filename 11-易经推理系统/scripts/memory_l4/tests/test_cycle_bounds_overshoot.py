"""T6 验收测试：越界信号检测（动作C，T_CB4）

位置: scripts/memory_l4/tests/test_cycle_bounds_overshoot.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_cycle_bounds_overshoot.py -v

对应 Spec §3bis.4.2 动作C + §3bis.9 T_CB4。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2 import morph_cycle_predictor as mcp
from bcrm2.morph_cycle_predictor import MorphCyclePredictor


def _make_predictor() -> MorphCyclePredictor:
    """构造 MorphCyclePredictor 实例（绕过 __init__ 的 storage 依赖）。"""
    return MorphCyclePredictor.__new__(MorphCyclePredictor)


# ================================================================
# T_CB4: 越界信号检测
# ================================================================

class TestOvershootSingleEvent:
    """验证单次越界事件检测。"""

    def test_single_overshoot_up(self):
        """level_hist=[0.0, 0.5, 0.3]，第 2 天越上界 0.1。"""
        p = _make_predictor()
        bounds = {"level_lo": -0.4, "level_hi": 0.4}
        level_hist = [0.0, 0.5, 0.3]
        dates = ["2026-08-17", "2026-08-18", "2026-08-19"]

        events = p._check_overshoot_events(level_hist, dates, bounds)

        assert len(events) == 1
        e = events[0]
        assert e["date"] == "2026-08-18"
        assert abs(e["level"] - 0.5) < 0.001
        assert e["bound"] == [-0.4, 0.4]
        assert e["direction"] == "up"
        assert abs(e["magnitude"] - 0.1) < 0.001
        assert e["need_anchor_correct"] is False  # 连续越界 < 5 天

    def test_single_overshoot_down(self):
        """level_hist=[0.0, -0.5, 0.3]，第 2 天越下界 0.1。"""
        p = _make_predictor()
        bounds = {"level_lo": -0.4, "level_hi": 0.4}
        level_hist = [0.0, -0.5, 0.3]
        dates = ["2026-08-17", "2026-08-18", "2026-08-19"]

        events = p._check_overshoot_events(level_hist, dates, bounds)

        assert len(events) == 1
        e = events[0]
        assert e["direction"] == "down"
        assert abs(e["magnitude"] - 0.1) < 0.001
        assert e["need_anchor_correct"] is False

    def test_overshoot_at_exact_boundary_no_event(self):
        """level=0.4 正好等于上界，不视为越界。"""
        p = _make_predictor()
        bounds = {"level_lo": -0.4, "level_hi": 0.4}
        level_hist = [0.4, -0.4]
        dates = ["2026-08-17", "2026-08-18"]

        events = p._check_overshoot_events(level_hist, dates, bounds)

        assert len(events) == 0


class TestOvershootStreak:
    """验证连续越界触发大调整标记。"""

    def test_streak_5_triggers_anchor_correct(self):
        """连续 5 天越界，最后一个事件 need_anchor_correct=True。"""
        p = _make_predictor()
        bounds = {"level_lo": -0.4, "level_hi": 0.4}
        # 连续 5 天越上界
        level_hist = [0.5, 0.6, 0.7, 0.8, 0.9]
        dates = [f"2026-08-{15 + i}" for i in range(5)]

        events = p._check_overshoot_events(level_hist, dates, bounds)

        assert len(events) == 5
        assert events[-1]["need_anchor_correct"] is True
        # 前 4 个不需要触发大调整
        for e in events[:-1]:
            assert e["need_anchor_correct"] is False

    def test_streak_4_not_triggered(self):
        """连续 4 天越界（< 5），不触发 need_anchor_correct。"""
        p = _make_predictor()
        bounds = {"level_lo": -0.4, "level_hi": 0.4}
        level_hist = [0.5, 0.6, 0.7, 0.8]
        dates = [f"2026-08-{15 + i}" for i in range(4)]

        events = p._check_overshoot_events(level_hist, dates, bounds)

        assert len(events) == 4
        for e in events:
            assert e["need_anchor_correct"] is False

    def test_streak_broken_resets(self):
        """连续 4 天越界 + 1 天未越界 + 1 天越界，不触发大调整。"""
        p = _make_predictor()
        bounds = {"level_lo": -0.4, "level_hi": 0.4}
        level_hist = [0.5, 0.6, 0.7, 0.8, 0.0, 0.5]  # 第 5 天回边界内
        dates = [f"2026-08-{15 + i}" for i in range(6)]

        events = p._check_overshoot_events(level_hist, dates, bounds)

        # 5 个越界事件（第 5 天未越界不算）
        assert len(events) == 5
        for e in events:
            assert e["need_anchor_correct"] is False, \
                "连续越界被打断后应重置计数，不触发大调整"


class TestOvershootNoEvents:
    """验证全部在边界内时返回空列表。"""

    def test_no_events_within_bounds(self):
        """全部在边界内，返回空列表。"""
        p = _make_predictor()
        bounds = {"level_lo": -0.4, "level_hi": 0.4}
        level_hist = [0.0, 0.1, -0.1, 0.3, -0.3]
        dates = [f"2026-08-{15 + i}" for i in range(5)]

        events = p._check_overshoot_events(level_hist, dates, bounds)

        assert events == []

    def test_empty_input(self):
        """空输入返回空列表。"""
        p = _make_predictor()
        bounds = {"level_lo": -0.4, "level_hi": 0.4}

        events = p._check_overshoot_events([], [], bounds)

        assert events == []


class TestOvershootDirection:
    """验证越界方向切换不影响连续计数（方向交替也算连续越界）。"""

    def test_alternating_direction_still_counts(self):
        """越上、越下交替也算连续越界（都是脱离边界）。"""
        p = _make_predictor()
        bounds = {"level_lo": -0.4, "level_hi": 0.4}
        # 第 1 天越上界，第 2 天越下界，第 3 天越上界，第 4 天越下界，第 5 天越上界
        level_hist = [0.5, -0.5, 0.6, -0.6, 0.7]
        dates = [f"2026-08-{15 + i}" for i in range(5)]

        events = p._check_overshoot_events(level_hist, dates, bounds)

        assert len(events) == 5
        assert events[-1]["need_anchor_correct"] is True
