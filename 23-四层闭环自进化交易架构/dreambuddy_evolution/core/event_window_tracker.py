"""
EventWindowTracker — FOMC 事件窗口阶段判定

SPEC §3.2: 6 阶段 FOMC 周期
  ① expectation_build  (FOMC 前 4-6 周, 概率 <40%)
  ② expectation_rise   (FOMC 前 2-4 周, 概率 40-70%)
  ③ expectation_jump   (FOMC 前 1-2 周, 概率 >70%)
  ④ expectation_digest (FOMC 前 1 周内, 概率已稳定)
  ⑤ event              (FOMC 当天)
  ⑥ repricing          (FOMC 后 1-3 周)

输出 event_context dict，供策略引擎和 ESE 消费。
FAIL-OPEN: 无 FOMC 数据时返回中性 context。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EventContext:
    """事件上下文快照。"""

    cycle_phase: str = "neutral"
    event_window: str = "none"  # pre_event / event / post_event / none
    in_fomc_cycle: bool = False
    days_to_fomc: int | None = None
    days_since_fomc: int | None = None
    hike_prob: float | None = None
    probability_trend: str = "stable"  # rising / falling / stable
    dominant_direction: str = "neutral"  # long / short / neutral
    repricing_sub_phase: str = "none"  # relief / verification / trend / none
    expected_surprise: float | None = None  # forecast - previous（SPEC §3.2）
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_phase": self.cycle_phase,
            "event_window": self.event_window,
            "in_fomc_cycle": self.in_fomc_cycle,
            "days_to_fomc": self.days_to_fomc,
            "days_since_fomc": self.days_since_fomc,
            "hike_prob": self.hike_prob,
            "probability_trend": self.probability_trend,
            "dominant_direction": self.dominant_direction,
            "repricing_sub_phase": self.repricing_sub_phase,
            "expected_surprise": self.expected_surprise,
            "raw": self.raw,
        }


class EventWindowTracker:
    """FOMC 事件窗口阶段判定器。"""

    # 6 阶段阈值（天数）
    EXPECTATION_BUILD_MAX_DAYS = 42      # 6 周
    EXPECTATION_RISE_MAX_DAYS = 28       # 4 周
    EXPECTATION_JUMP_MAX_DAYS = 14       # 2 周
    EXPECTATION_DIGEST_MAX_DAYS = 7      # 1 周
    EVENT_WINDOW_HOURS = 12              # FOMC 当天 ±12h
    REPRICING_MAX_DAYS = 21              # 3 周

    # repricing 子阶段阈值（SPEC §0.4.4 三阶段动态权衡）
    RELIEF_MAX_DAYS = 5          # Phase A: 0-5 天（不确定性消除+空头回补）
    VERIFICATION_MAX_DAYS = 15   # Phase B: 5-15 天（基本面验证）
    # Phase C: 15-21 天+（债务周期位置主导）

    # 概率阈值
    PROB_LOW = 0.40
    PROB_MID = 0.70

    def get_context(
        self,
        next_fomc: datetime | None = None,
        last_fomc: datetime | None = None,
        hike_prob: float | None = None,
        cut_prob: float | None = None,
        prob_change_7d: float | None = None,
        now: datetime | None = None,
        forecast: float | None = None,
        previous: float | None = None,
    ) -> dict[str, Any]:
        """
        根据当前时间与 FOMC 时间/概率判定阶段。

        Args:
            next_fomc: 下次 FOMC 决议时间
            last_fomc: 上次 FOMC 决议时间
            hike_prob: 当前加息概率 [0,1]
            cut_prob: 当前降息概率 [0,1]
            prob_change_7d: 过去 7 天概率变化（正=上升）
            now: 锚定时间（测试用）
            forecast: 市场预期值（如 CPI 预期），用于计算 expected_surprise
            previous: 前值，用于计算 expected_surprise = forecast - previous

        Returns event_context dict。
        """
        ctx = EventContext(hike_prob=hike_prob)
        # expected_surprise = forecast - previous（SPEC §3.2）
        if forecast is not None and previous is not None:
            try:
                ctx.expected_surprise = round(float(forecast) - float(previous), 6)
            except (TypeError, ValueError):
                ctx.expected_surprise = None
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Normalize next_fomc / last_fomc to offset-aware (UTC) if naive
        if next_fomc is not None and next_fomc.tzinfo is None:
            next_fomc = next_fomc.replace(tzinfo=timezone.utc)
        if last_fomc is not None and last_fomc.tzinfo is None:
            last_fomc = last_fomc.replace(tzinfo=timezone.utc)

        # 概率趋势
        if prob_change_7d is not None:
            if prob_change_7d > 0.05:
                ctx.probability_trend = "rising"
            elif prob_change_7d < -0.05:
                ctx.probability_trend = "falling"

        # 主导方向（基于加息/降息概率）
        if hike_prob is not None and cut_prob is not None:
            if hike_prob > 0.5:
                ctx.dominant_direction = "short"
            elif cut_prob > 0.5:
                ctx.dominant_direction = "long"
        elif hike_prob is not None:
            if hike_prob > 0.5:
                ctx.dominant_direction = "short"
            elif hike_prob < 0.3:
                ctx.dominant_direction = "long"

        # 判定阶段
        # 优先级：如果上次 FOMC 刚发生（在重定价窗口内）且下次 FOMC 较远，
        # 则重定价阶段优先于预期构建阶段。
        days_since = None
        if last_fomc is not None:
            delta_since = now - last_fomc
            days_since = delta_since.total_seconds() / 86400.0
            ctx.days_since_fomc = max(0, int(days_since))

        days_to = None
        if next_fomc is not None:
            delta_to = next_fomc - now
            days_to = delta_to.total_seconds() / 86400.0
            ctx.days_to_fomc = max(0, int(days_to))

        # 重定价窗口内且下次 FOMC 尚远 → repricing 优先
        in_repricing = (
            days_since is not None
            and days_since <= self.REPRICING_MAX_DAYS
            and (days_to is None or days_to > self.EXPECTATION_RISE_MAX_DAYS)
        )

        if in_repricing:
            ctx.cycle_phase = "repricing"
            ctx.event_window = "post_event"
            ctx.in_fomc_cycle = True
            ctx.repricing_sub_phase = self._compute_repricing_sub_phase(days_since)
        elif next_fomc is not None:
            days = days_to
            if days <= (self.EVENT_WINDOW_HOURS / 24.0):
                # FOMC 当天
                ctx.cycle_phase = "event"
                ctx.event_window = "event"
                ctx.in_fomc_cycle = True
            elif days <= self.EXPECTATION_DIGEST_MAX_DAYS:
                ctx.cycle_phase = "expectation_digest"
                ctx.event_window = "pre_event"
                ctx.in_fomc_cycle = True
            elif days <= self.EXPECTATION_JUMP_MAX_DAYS:
                if hike_prob is not None and hike_prob > self.PROB_MID:
                    ctx.cycle_phase = "expectation_jump"
                else:
                    ctx.cycle_phase = "expectation_rise"
                ctx.event_window = "pre_event"
                ctx.in_fomc_cycle = True
            elif days <= self.EXPECTATION_RISE_MAX_DAYS:
                if hike_prob is not None and hike_prob > self.PROB_LOW:
                    ctx.cycle_phase = "expectation_rise"
                else:
                    ctx.cycle_phase = "expectation_build"
                ctx.event_window = "pre_event"
                ctx.in_fomc_cycle = True
            elif days <= self.EXPECTATION_BUILD_MAX_DAYS:
                ctx.cycle_phase = "expectation_build"
                ctx.event_window = "pre_event"
                ctx.in_fomc_cycle = True
            else:
                # FOMC 太远，不在周期内
                ctx.cycle_phase = "neutral"
                ctx.event_window = "none"
                ctx.in_fomc_cycle = False
        elif last_fomc is not None:
            if days_since <= self.REPRICING_MAX_DAYS:
                ctx.cycle_phase = "repricing"
                ctx.event_window = "post_event"
                ctx.in_fomc_cycle = True
                ctx.repricing_sub_phase = self._compute_repricing_sub_phase(days_since)
            else:
                ctx.cycle_phase = "neutral"
                ctx.event_window = "none"
                ctx.in_fomc_cycle = False
        # else: 无 FOMC 信息 → 保持 neutral

        ctx.raw = {
            "next_fomc": next_fomc.isoformat() if next_fomc else None,
            "last_fomc": last_fomc.isoformat() if last_fomc else None,
            "hike_prob": hike_prob,
            "cut_prob": cut_prob,
            "prob_change_7d": prob_change_7d,
            "forecast": forecast,
            "previous": previous,
        }
        return ctx.to_dict()

    def _compute_repricing_sub_phase(self, days_since: float | None) -> str:
        """
        计算 repricing 子阶段（SPEC §0.4.4 三阶段动态权衡）。

          Phase A relief       (0-5 天): 不确定性消除+空头回补主导
          Phase B verification (5-15 天): 基本面验证（通胀/信贷/盈利/空头回补）
          Phase C trend        (15 天+): 债务周期位置主导

        Args:
            days_since: 距上次 FOMC 的天数

        Returns: "relief" / "verification" / "trend" / "none"
        """
        if days_since is None:
            return "none"
        if days_since < self.RELIEF_MAX_DAYS:
            return "relief"
        elif days_since < self.VERIFICATION_MAX_DAYS:
            return "verification"
        else:
            return "trend"
