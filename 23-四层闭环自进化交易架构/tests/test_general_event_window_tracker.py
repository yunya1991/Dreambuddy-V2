"""GeneralEventWindowTracker 测试 — 通用日程型事件窗口判定（5 阶段）。

SPEC-Phase2 §3.2-3.3:
  - 不依赖 FOMC 概率模型
  - 5 阶段：expectation_build / expectation_rise / expectation_digest / event / post_event
  - 阈值按 half_life 动态伸缩（tech_upgrade τ=1.0, congressional_hearing τ=2.5）

RED 阶段：GeneralEventWindowTracker 类尚未实现，测试应因 ImportError 失败。
"""
from datetime import datetime, timedelta, timezone

import pytest


# 锚定时间，避免 datetime.now() 漂移
NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def tracker():
    from dreambuddy_evolution.core.general_event_window_tracker import GeneralEventWindowTracker
    return GeneralEventWindowTracker()


# ---------- 5 阶段判定（tech_upgrade τ=1.0） ----------

def test_expectation_build_phase(tracker):
    """tech_upgrade 前 2-3 个半衰期 → expectation_build。"""
    event_date = NOW + timedelta(days=2.5)  # 2τ < days_to ≤ 3τ
    ctx = tracker.get_context(event_date=event_date, event_type="tech_upgrade", now=NOW)
    assert ctx["cycle_phase"] == "expectation_build"
    assert ctx["event_window"] == "pre_event"
    assert ctx["in_event_cycle"] is True


def test_expectation_rise_phase(tracker):
    """tech_upgrade 前 1-2 个半衰期 → expectation_rise。"""
    event_date = NOW + timedelta(days=1.5)  # τ < days_to ≤ 2τ
    ctx = tracker.get_context(event_date=event_date, event_type="tech_upgrade", now=NOW)
    assert ctx["cycle_phase"] == "expectation_rise"
    assert ctx["event_window"] == "pre_event"


def test_expectation_digest_phase(tracker):
    """tech_upgrade 前 0-1 个半衰期 → expectation_digest。"""
    event_date = NOW + timedelta(days=0.5)  # 0 < days_to ≤ τ
    ctx = tracker.get_context(event_date=event_date, event_type="tech_upgrade", now=NOW)
    assert ctx["cycle_phase"] == "expectation_digest"
    assert ctx["event_window"] == "pre_event"


def test_event_phase(tracker):
    """tech_upgrade 当天 → event。"""
    event_date = NOW - timedelta(hours=2)  # days_to ≤ 0
    ctx = tracker.get_context(event_date=event_date, event_type="tech_upgrade", now=NOW)
    assert ctx["cycle_phase"] == "event"
    assert ctx["event_window"] == "event"
    assert ctx["in_event_cycle"] is True


def test_post_event_phase(tracker):
    """tech_upgrade 后 0-3 个半衰期 → post_event。"""
    event_date = NOW - timedelta(days=1.5)  # 0 < days_since ≤ 3τ
    ctx = tracker.get_context(event_date=event_date, event_type="tech_upgrade", now=NOW)
    assert ctx["cycle_phase"] == "post_event"
    assert ctx["event_window"] == "post_event"


def test_neutral_outside_window(tracker):
    """tech_upgrade 前 >3 个半衰期 → neutral（窗口外）。"""
    event_date = NOW + timedelta(days=4)  # days_to > 3τ
    ctx = tracker.get_context(event_date=event_date, event_type="tech_upgrade", now=NOW)
    assert ctx["cycle_phase"] == "neutral"
    assert ctx["event_window"] == "none"
    assert ctx["in_event_cycle"] is False


# ---------- half_life 动态伸缩（congressional_hearing τ=2.5） ----------

def test_congressional_hearing_window_scales(tracker):
    """congressional_hearing τ=2.5，窗口边界按 τ 动态伸缩。"""
    # days_to = 3.0 在 (2τ=5.0, 3τ=7.5] 区间内 → expectation_build
    event_date = NOW + timedelta(days=6.0)
    ctx = tracker.get_context(event_date=event_date, event_type="congressional_hearing", now=NOW)
    assert ctx["cycle_phase"] == "expectation_build"

    # days_to = 3.0 对 tech_upgrade (τ=1.0) 已超出窗口 → neutral
    event_date_btc = NOW + timedelta(days=6.0)
    ctx_btc = tracker.get_context(event_date=event_date_btc, event_type="tech_upgrade", now=NOW)
    assert ctx_btc["cycle_phase"] == "neutral"


# ---------- direction 透传 ----------

def test_dominant_direction_from_event_direction(tracker):
    """event_direction 参数透传到 dominant_direction。"""
    event_date = NOW + timedelta(days=1)
    ctx = tracker.get_context(
        event_date=event_date, event_type="tech_upgrade", now=NOW, event_direction="long"
    )
    assert ctx["dominant_direction"] == "long"


def test_dominant_direction_default_neutral(tracker):
    """未传 event_direction 时默认 neutral。"""
    event_date = NOW + timedelta(days=1)
    ctx = tracker.get_context(event_date=event_date, event_type="tech_upgrade", now=NOW)
    assert ctx["dominant_direction"] == "neutral"


# ---------- days_to / days_since 计算 ----------

def test_days_to_event_positive(tracker):
    """事件未发生 → days_to_event > 0, days_since_event = 0。"""
    event_date = NOW + timedelta(days=2)
    ctx = tracker.get_context(event_date=event_date, event_type="tech_upgrade", now=NOW)
    assert ctx["days_to_event"] == 2
    assert ctx["days_since_event"] == 0


def test_days_since_event_positive(tracker):
    """事件已发生 → days_since_event > 0, days_to_event = 0。"""
    event_date = NOW - timedelta(days=1)
    ctx = tracker.get_context(event_date=event_date, event_type="tech_upgrade", now=NOW)
    assert ctx["days_since_event"] == 1
    assert ctx["days_to_event"] == 0


# ---------- FAIL-OPEN ----------

def test_fail_open_no_event_date(tracker):
    """无 event_date → 返回 neutral context。"""
    ctx = tracker.get_context(event_type="tech_upgrade", now=NOW)
    assert ctx["cycle_phase"] == "neutral"
    assert ctx["event_window"] == "none"
    assert ctx["in_event_cycle"] is False


def test_fail_open_unknown_event_type(tracker):
    """未知 event_type → 仍返回中性 context（不抛异常）。"""
    event_date = NOW + timedelta(days=1)
    ctx = tracker.get_context(event_date=event_date, event_type="unknown_type", now=NOW)
    # 至少不应抛异常，返回 dict
    assert isinstance(ctx, dict)
    assert ctx["cycle_phase"] == "neutral"


# ---------- schema 一致性 ----------

def test_output_schema_matches_fomc_tracker(tracker):
    """输出 dict schema 与 FOMCEventWindowTracker 一致。"""
    event_date = NOW + timedelta(days=1)
    ctx = tracker.get_context(event_date=event_date, event_type="tech_upgrade", now=NOW)
    required_keys = {
        "cycle_phase", "event_window", "in_event_cycle",
        "days_to_event", "days_since_event",
        "dominant_direction", "half_life", "raw",
    }
    assert required_keys.issubset(ctx.keys())
