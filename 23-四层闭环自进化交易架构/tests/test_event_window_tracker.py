"""EventWindowTracker 测试 — FOMC 事件窗口阶段判定。

覆盖：6 阶段判定、事件窗口分类、FAIL-OPEN。
"""
from datetime import datetime, timedelta

from dreambuddy_evolution.core.event_window_tracker import EventWindowTracker


def test_expectation_build_phase():
    """FOMC 前 4-6 周，概率 <40% → expectation_build。"""
    tracker = EventWindowTracker()
    next_fomc = datetime.now() + timedelta(days=35)
    ctx = tracker.get_context(next_fomc=next_fomc, hike_prob=0.30)
    assert ctx["cycle_phase"] == "expectation_build"
    assert ctx["event_window"] == "pre_event"


def test_expectation_rise_phase():
    """FOMC 前 2-4 周，概率 40-70% → expectation_rise。"""
    tracker = EventWindowTracker()
    next_fomc = datetime.now() + timedelta(days=20)
    ctx = tracker.get_context(next_fomc=next_fomc, hike_prob=0.55)
    assert ctx["cycle_phase"] == "expectation_rise"
    assert ctx["event_window"] == "pre_event"


def test_expectation_jump_phase():
    """FOMC 前 1-2 周，概率 >70% → expectation_jump。"""
    tracker = EventWindowTracker()
    next_fomc = datetime.now() + timedelta(days=10)
    ctx = tracker.get_context(next_fomc=next_fomc, hike_prob=0.88)
    assert ctx["cycle_phase"] == "expectation_jump"
    assert ctx["event_window"] == "pre_event"


def test_event_phase():
    """FOMC 当天 → event。"""
    tracker = EventWindowTracker()
    next_fomc = datetime.now() + timedelta(hours=2)
    ctx = tracker.get_context(next_fomc=next_fomc, hike_prob=0.93)
    assert ctx["cycle_phase"] == "event"
    assert ctx["event_window"] == "event"


def test_repricing_phase():
    """FOMC 后 1-3 周 → repricing。"""
    tracker = EventWindowTracker()
    last_fomc = datetime.now() - timedelta(days=5)
    ctx = tracker.get_context(last_fomc=last_fomc)
    assert ctx["cycle_phase"] == "repricing"
    assert ctx["event_window"] == "post_event"


def test_no_fomc_returns_neutral():
    """无 FOMC 信息时返回中性。"""
    tracker = EventWindowTracker()
    ctx = tracker.get_context()
    assert ctx["cycle_phase"] == "neutral"
    assert ctx["event_window"] == "none"
    assert ctx["in_fomc_cycle"] is False


def test_in_fomc_cycle_true():
    """FOMC 前 6 周内 → in_fomc_cycle=True。"""
    tracker = EventWindowTracker()
    next_fomc = datetime.now() + timedelta(days=30)
    ctx = tracker.get_context(next_fomc=next_fomc)
    assert ctx["in_fomc_cycle"] is True


def test_probability_trend_rising():
    """概率 7 天变化 >0 → rising。"""
    tracker = EventWindowTracker()
    next_fomc = datetime.now() + timedelta(days=20)
    ctx = tracker.get_context(next_fomc=next_fomc, hike_prob=0.70, prob_change_7d=0.15)
    assert ctx["probability_trend"] == "rising"


def test_probability_trend_falling():
    """概率 7 天变化 <0 → falling。"""
    tracker = EventWindowTracker()
    next_fomc = datetime.now() + timedelta(days=20)
    ctx = tracker.get_context(next_fomc=next_fomc, hike_prob=0.50, prob_change_7d=-0.10)
    assert ctx["probability_trend"] == "falling"


def test_dominant_direction_hike():
    """加息概率 >0.5 → dominant_direction=short（对黄金等资产）。"""
    tracker = EventWindowTracker()
    next_fomc = datetime.now() + timedelta(days=10)
    ctx = tracker.get_context(next_fomc=next_fomc, hike_prob=0.88)
    assert ctx["dominant_direction"] == "short"


def test_dominant_direction_cut():
    """降息概率 >0.5 → dominant_direction=long。"""
    tracker = EventWindowTracker()
    next_fomc = datetime.now() + timedelta(days=10)
    ctx = tracker.get_context(next_fomc=next_fomc, hike_prob=0.10, cut_prob=0.80)
    assert ctx["dominant_direction"] == "long"
