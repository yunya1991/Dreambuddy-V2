"""GeneralEventWindowTracker — 通用日程型事件窗口判定（不依赖 FOMC 概率模型）。

SPEC-Phase2 §3.2-3.3:
  5 阶段判定（按 half_life 动态伸缩）:
    expectation_build   (2τ < days_to ≤ 3τ)
    expectation_rise    (τ < days_to ≤ 2τ)
    expectation_digest  (0 < days_to ≤ τ)
    event               (days_to ≤ 0 且 days_since ≤ τ)
    post_event          (τ < days_since ≤ 3τ)
    neutral             (窗口外 / 未知 event_type / 无 event_date)

输出 schema 与 FOMCEventWindowTracker 一致。
FAIL-OPEN: 无 event_date 或未知 event_type 时返回中性 context。
"""
from __future__ import annotations

import logging
from abc import ABC
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class BaseEventWindowTracker(ABC):
    """事件窗口追踪器抽象基类。

    子类:
      - FOMCEventWindowTracker（现有 EventWindowTracker，6 阶段 + 概率模型）
      - GeneralEventWindowTracker（5 阶段，不依赖概率模型）
    """
    pass


class GeneralEventWindowTracker(BaseEventWindowTracker):
    """通用日程型事件窗口追踪器（不依赖 FOMC 概率模型）。"""

    # 按 event_type 的半衰期（天）—— 经验假设 v0，待回测验证后校准（SPEC M4）
    HALF_LIFE = {
        "tech_upgrade": 1.0,           # 硬分叉影响较短（窗口±3天）
        "congressional_hearing": 2.5,  # 听证会影响中等（窗口±7.5天）
    }

    # 窗口倍数（days_to/days_since ≤ half_life × WINDOW_MULT 为窗口内）
    WINDOW_MULT = 3.0

    def get_context(
        self,
        event_date: datetime | None = None,
        event_type: str = "none",
        now: datetime | None = None,
        event_direction: str = "neutral",
    ) -> dict[str, Any]:
        """
        通用事件窗口判定。

        Args:
            event_date: 下次事件时间
            event_type: tech_upgrade / congressional_hearing
            now: 锚定时间（测试用）
            event_direction: collector 预计算的方向（long/short/neutral），写入 dominant_direction

        Returns event_context dict（与 FOMCEventWindowTracker 输出 schema 一致）。
        """
        # FAIL-OPEN: 无 event_date → neutral
        if event_date is None:
            return self._neutral_context(event_type, event_direction, half_life=None)

        half_life = self.HALF_LIFE.get(event_type)
        # FAIL-OPEN: 未知 event_type → neutral
        if half_life is None:
            return self._neutral_context(event_type, event_direction, half_life=None)

        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # normalize event_date to offset-aware UTC
        if event_date.tzinfo is None:
            event_date = event_date.replace(tzinfo=timezone.utc)

        window_days = half_life * self.WINDOW_MULT
        days_to = (event_date - now).total_seconds() / 86400.0
        days_since = (now - event_date).total_seconds() / 86400.0

        cycle_phase = "neutral"
        event_window = "none"
        in_cycle = False
        days_to_event = 0
        days_since_event = 0

        if days_to > 0:
            # 事件未发生
            days_to_event = max(0, int(days_to))
            if days_to <= window_days:
                in_cycle = True
                event_window = "pre_event"
                if days_to <= half_life:
                    cycle_phase = "expectation_digest"
                elif days_to <= half_life * 2:
                    cycle_phase = "expectation_rise"
                else:
                    cycle_phase = "expectation_build"
            # else: 窗口外 → 保持 neutral
        else:
            # 事件已发生
            days_since_event = max(0, int(days_since))
            if days_since <= window_days:
                in_cycle = True
                if days_since <= half_life:
                    # 事件当天附近（days_since ≤ τ）→ event
                    cycle_phase = "event"
                    event_window = "event"
                else:
                    cycle_phase = "post_event"
                    event_window = "post_event"
            # else: 窗口外 → 保持 neutral

        return {
            "cycle_phase": cycle_phase,
            "event_window": event_window,
            "in_event_cycle": in_cycle,
            "days_to_event": days_to_event,
            "days_since_event": days_since_event,
            "dominant_direction": event_direction,
            "half_life": half_life,
            "raw": {
                "event_date": event_date.isoformat() if event_date else None,
                "event_type": event_type,
                "event_direction": event_direction,
            },
        }

    def _neutral_context(
        self, event_type: str, event_direction: str, half_life: float | None
    ) -> dict[str, Any]:
        """返回中性 context（FAIL-OPEN）。"""
        return {
            "cycle_phase": "neutral",
            "event_window": "none",
            "in_event_cycle": False,
            "days_to_event": None,
            "days_since_event": None,
            "dominant_direction": event_direction,
            "half_life": half_life if half_life is not None else 0.0,
            "raw": {
                "event_type": event_type,
                "event_direction": event_direction,
            },
        }
