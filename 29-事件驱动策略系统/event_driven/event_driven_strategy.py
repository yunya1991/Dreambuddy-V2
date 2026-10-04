"""
EventDrivenStrategy — 宏观事件驱动策略引擎

核心逻辑：买预期，卖事实
  - 预期阶段：市场提前消化利空，金价先跌 → 空头偏向
  - 事件落地：利空出尽，资金反手买入 → 多头偏向
  - 关键驱动：实际利率（名义利率 - 通胀预期）
    通胀涨幅 > 加息速度 → 实际利率下行 → 金价上涨

5 维评分（加权平均 → 0.0-1.0）:
  1. priced_in_score    (25%): 定价充分度（预期阶段=空头，落地后=多头）
  2. real_rate_score    (20%): 实际利率方向（通胀 vs 加息速度）
  3. resilience_score   (20%): 价格在利空下的抗跌性
  4. lower_shadow_score (15%): K线下影线支撑强度
  5. cross_asset_score  (20%): 跨资产同步验证（黄金/美债/美元）

前瞻指引修正：点阵图偏鹰（暗示更多加息）→ 置信度折扣

信号方向:
  - score >= 0.65 → LONG（利空出尽，底部布局）
  - score <= 0.35 → SHORT（利空未出尽，顺势做空）
  - 0.35 < score < 0.65 → NEUTRAL

FAIL-OPEN: 数据缺失时返回中性信号 + 低置信度。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Phase 2: 弹性系数常量（SPEC-事件驱动策略独立化 §六）
ELASTICITY_TREND_FOLLOW = 1.0   # 顺势共振（事件方向 = 趋势方向）
ELASTICITY_MEAN_REVERT = -0.7   # 逆势均值回归（事件方向 ≠ 趋势方向）
ELASTICITY_NONE = 0.0           # 无弹性约束（neutral 事件或无趋势）

VALID_SIGNALS = ("long", "short", "neutral")
VALID_EVENT_TYPES = ("fomc", "nfp", "cpi", "ppi", "none")

# Phase 3: 事件半衰期 τ（天）—— 单点脉冲算法
# 数据来源: 事件研究法事件窗 [-10,+20] + Smales 黄金 VAR-GARCH
EVENT_HALF_LIFE = {
    "fomc": 3.0,   # FOMC 影响最持久（含纪要重定价）
    "cpi": 2.0,    # CPI 影响中等
    "nfp": 1.5,    # 非农影响较短
    "ppi": 1.0,    # PPI 影响最短
    "none": 0.0,
}

# Phase 3: 阶段动态信号阈值（替代固定 0.65/0.35）
PHASE_THRESHOLDS = {
    "pre_event":        {"long": 0.70, "short": 0.30},  # 保守：不确定性高
    "expectation_build": {"long": 0.70, "short": 0.30},
    "expectation_jump": {"long": 0.65, "short": 0.32},  # 跳变期略放宽
    "expectation_digest": {"long": 0.65, "short": 0.32},
    "event":            {"long": 0.55, "short": 0.40},  # 利空出尽，阈值放宽
    "repricing":        {"long": 0.60, "short": 0.35},  # 三阶段权衡
    "neutral":          {"long": 0.65, "short": 0.35},  # 兜底
}

# Phase 3: 阶段仓位乘数
PHASE_POSITION_MULT = {
    "pre_event": 0.8,
    "expectation_build": 0.8,
    "expectation_jump": 1.2,
    "expectation_digest": 1.0,
    "event": 1.5,       # 事件当天仓位最大
    "repricing": 1.0,
    "neutral": 0.0,
}


def compute_impulse(event_type: str, days_since: float, strength: float) -> float:
    """Phase 3: 事件冲击脉冲响应函数。

    impulse(t) = strength × exp(-t / τ)

    Args:
        event_type: fomc/cpi/nfp/ppi/none
        days_since: 距事件落地天数（可为小数）
        strength: 事件冲击强度 [0,1]

    Returns:
        脉冲强度 [0, strength]；t > 3τ 时趋于 0；FAIL-OPEN → 0.0
    """
    tau = EVENT_HALF_LIFE.get(event_type, 1.0)
    if tau <= 0 or days_since < 0:
        return 0.0
    return strength * math.exp(-days_since / tau)


@dataclass(frozen=True)
class EventSignal:
    """Phase 2: 事件-趋势弹性评估器输出契约（替代 EventDrivenSignal）。

    SPEC-事件驱动策略独立化 §六 Phase 2

    核心新增字段:
      - strength: 事件冲击强度（0.0-1.0），用于路径竞争得分
      - elasticity: 弹性系数（-1.0~1.0），事件方向×趋势方向的关系
      - event_type: 事件类型（fomc/nfp/cpi/ppi/none）
      - window_start/window_end: 事件窗口（ISO 日期）
    语义变化:
      - confidence: 数据完整度（0.0-1.0），原 confidence 语义移至 strength
    向后兼容:
      - signal 字段保留（Phase 1 _inject_event_driven_path 无需改）
    """

    signal: str                       # "long" / "short" / "neutral"
    strength: float = 0.0             # 事件冲击强度 [0,1]（路径竞争得分）
    elasticity: float = 0.0           # 弹性系数 [-1,1]
    event_type: str = "none"          # fomc/nfp/cpi/ppi/none
    event_phase: str = "neutral"      # expectation_build/.../neutral
    window_start: Optional[str] = None  # ISO 日期
    window_end: Optional[str] = None    # ISO 日期
    confidence: float = 0.0           # 数据完整度 [0,1]
    scores: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    forward_guidance: str = ""        # hawkish/dovish/neutral
    mode: str = "none"                # priced_in_bottom/expectation_short/none（向后兼容）

    def __post_init__(self) -> None:
        # 枚举校验
        if self.signal not in VALID_SIGNALS:
            raise ValueError(f"signal must be one of {VALID_SIGNALS}, got {self.signal!r}")
        if self.event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"event_type must be one of {VALID_EVENT_TYPES}, got {self.event_type!r}")
        # 边界校验
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"strength must be in [0,1], got {self.strength}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        if not -1.0 <= self.elasticity <= 1.0:
            raise ValueError(f"elasticity must be in [-1,1], got {self.elasticity}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "strength": self.strength,
            "elasticity": self.elasticity,
            "event_type": self.event_type,
            "event_phase": self.event_phase,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "confidence": self.confidence,
            "scores": self.scores,
            "reason": self.reason,
            "forward_guidance": self.forward_guidance,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EventSignal":
        """FAIL-OPEN: 异常返回 neutral_event_signal，不抛异常。"""
        try:
            return cls(
                signal=d.get("signal", "neutral"),
                strength=float(d.get("strength", 0.0)),
                elasticity=float(d.get("elasticity", 0.0)),
                event_type=d.get("event_type", "none"),
                event_phase=d.get("event_phase", "neutral"),
                window_start=d.get("window_start"),
                window_end=d.get("window_end"),
                confidence=float(d.get("confidence", 0.0)),
                scores=dict(d.get("scores", {})),
                reason=d.get("reason", ""),
                forward_guidance=d.get("forward_guidance", ""),
                mode=d.get("mode", "none"),
            )
        except Exception:
            return neutral_event_signal()


def neutral_event_signal() -> EventSignal:
    """中性事件信号工厂（FAIL-OPEN 兜底）。"""
    return EventSignal(
        signal="neutral",
        strength=0.0,
        elasticity=ELASTICITY_NONE,
        event_type="none",
        event_phase="neutral",
        window_start=None,
        window_end=None,
        confidence=0.0,
        scores={},
        reason="",
        forward_guidance="",
        mode="none",
    )


# 向后兼容别名：EventDrivenSignal → EventSignal
EventDrivenSignal = EventSignal


class EventDrivenStrategy:
    """宏观事件驱动策略（买预期卖事实 + 实际利率驱动）。"""

    # 5 维权重
    W_PRICED_IN = 0.25
    W_REAL_RATE = 0.20
    W_RESILIENCE = 0.20
    W_LOWER_SHADOW = 0.15
    W_CROSS_ASSET = 0.20

    # 信号阈值
    LONG_THRESHOLD = 0.65
    SHORT_THRESHOLD = 0.35

    # 前瞻指引折扣
    FG_HAWKISH_DISCOUNT = 0.15  # 点阵图偏鹰 → composite * (1 - 0.15)
    FG_DOVISH_BONUS = 0.10

    # T4 P0 盲区修复（SPEC §3.2.1）：
    # 非农/CPI/PPI 虽不在 FOMC 议息周期，但实质影响加息预期，CESI 触发激活
    CESI_TRIGGER_THRESHOLD = 1.5  # ±1.5σ 触发宏观事件窗口
    MACRO_EVENT_TYPES = ("nfp", "cpi", "ppi")  # 强制激活的事件类型

    def evaluate(self, kline_data: dict[str, Any]) -> EventDrivenSignal:
        """
        评估事件驱动策略信号。

        Args:
            kline_data: data_pipeline.assemble() 输出的完整 dict

        Returns EventDrivenSignal。
        """
        event_ctx = kline_data.get("event_context") or {}
        cycle_phase = event_ctx.get("cycle_phase", "neutral")

        # T4 P0 盲区修复（SPEC §3.2.1）：
        # 解除 in_fomc_cycle 硬限制 — 非农/CPI/PPI 虽不在 FOMC 议息周期，
        # 但实质影响加息预期，必须激活策略。三选一触发：
        #   1. in_fomc_cycle=True（FOMC 议息周期内）
        #   2. CESI ≥ ±1.5σ（数据强超预期，触发宏观事件窗口）
        #   3. event_type in (nfp/cpi/ppi)（事件窗口内强制激活）
        in_fomc = event_ctx.get("in_fomc_cycle", False)
        cesi = kline_data.get("cesi")  # 由 data_pipeline 注入（T7）
        raw_event_type = event_ctx.get("event_type", "")  # nfp/cpi/ppi/fomc
        # Phase 2: 归一化未知 event_type 为 "none"（EventSignal 枚举校验要求）
        event_type = raw_event_type if raw_event_type in VALID_EVENT_TYPES else "none"

        is_macro_event_active = (
            in_fomc
            or (cesi is not None and abs(cesi) >= self.CESI_TRIGGER_THRESHOLD)
            or event_type in self.MACRO_EVENT_TYPES
        )

        if not is_macro_event_active:
            return EventSignal(
                signal="neutral",
                strength=0.0,
                elasticity=ELASTICITY_NONE,
                event_type=event_type or "none",
                event_phase=cycle_phase,
                window_start=event_ctx.get("window_start"),
                window_end=event_ctx.get("window_end"),
                confidence=0.0,
                scores={},
                reason="不在 FOMC 周期且无宏观事件触发",
                forward_guidance="",
                mode="none",
            )

        scores = self._compute_scores(kline_data, event_ctx)

        # 加权平均（Phase 3.1: 6 维，新增 news 10%，cross_asset 20%→10%）
        # surprise 25% + priced_in 20% + real_rate 20% + resilience 15% + cross_asset 10% + news 10%
        composite = (
            scores.get("surprise", 0.5) * 0.25
            + scores.get("priced_in", 0.5) * 0.20
            + scores.get("real_rate", 0.5) * 0.20
            + scores.get("resilience", 0.5) * 0.15
            + scores.get("cross_asset", 0.5) * 0.10
            + scores.get("news", 0.5) * 0.10
        )
        composite = max(0.0, min(1.0, composite))

        # 前瞻指引修正（提前计算，供三阶段权衡使用）
        forward_guidance = self._assess_forward_guidance(kline_data, event_ctx)

        # 买预期卖事实 阶段偏移 + 三阶段动态权衡（SPEC §0.4.4）
        is_post_event = cycle_phase in ("event", "repricing")
        hike_prob = event_ctx.get("hike_prob")
        sub_phase = event_ctx.get("repricing_sub_phase", "none")
        phase_detail = ""

        if not is_post_event and cycle_phase != "neutral" and hike_prob is not None:
            # 预期阶段：bearish bias proportional to hike_prob
            composite *= (1.0 - float(hike_prob) * 0.35)
            composite = max(0.0, min(1.0, composite))
        elif cycle_phase == "event":
            # FOMC 当天：利空出尽，温和看多偏移
            composite = min(1.0, composite * 1.10)
        elif cycle_phase == "repricing" and sub_phase != "none":
            # repricing 三阶段动态权衡
            composite, phase_detail = self._apply_three_phase_weighing(
                composite, kline_data, event_ctx, sub_phase, forward_guidance
            )
        elif is_post_event:
            # 兜底：repricing 无 sub_phase 时保留原逻辑
            composite = min(1.0, composite * 1.10)

        # 前瞻指引修正
        if forward_guidance == "hawkish":
            composite *= (1.0 - self.FG_HAWKISH_DISCOUNT)
            composite = max(0.0, min(1.0, composite))
        elif forward_guidance == "dovish":
            composite = min(1.0, composite + self.FG_DOVISH_BONUS)

        # 判定方向 + 模式
        is_post_event = cycle_phase in ("event", "repricing")
        if composite >= self.LONG_THRESHOLD:
            signal = "long"
            mode = "priced_in_bottom" if is_post_event else "premature_long"
            reason = "利空出尽，5 维评分共振看多"
        elif composite <= self.SHORT_THRESHOLD:
            signal = "short"
            mode = "expectation_short" if not is_post_event else "post_event_weak"
            reason = "买预期阶段，利空未出尽"
        else:
            signal = "neutral"
            mode = "priced_in_bottom"
            reason = "信号不明确，观望"

        # 追加三阶段权衡诊断
        if phase_detail:
            reason = f"{reason} | {phase_detail}"

        # Phase 2 语义拆分:
        #   strength = 事件冲击强度（原 confidence 语义，用于路径竞争得分）
        #   confidence = 数据完整度（仅 data_quality，用于判断是否可信）
        available = sum(1 for v in scores.values() if v is not None)
        # Phase 3.1: 6 维评分，分母从 5.0 改为 6.0
        total_dims = 6.0
        data_quality = available / total_dims
        strength = round(min(1.0, composite * data_quality), 3) if signal != "neutral" else round(data_quality * 0.3, 3)
        confidence = round(min(1.0, data_quality), 3)

        # Phase 2: 弹性系数（事件方向 × 趋势方向）
        elasticity = self._compute_elasticity(signal, kline_data)

        return EventSignal(
            signal=signal,
            strength=strength,
            elasticity=elasticity,
            event_type=event_type or "none",
            event_phase=cycle_phase,
            window_start=event_ctx.get("window_start"),
            window_end=event_ctx.get("window_end"),
            confidence=confidence,
            scores=scores,
            reason=reason,
            forward_guidance=forward_guidance,
            mode=mode,
        )

    def _compute_elasticity(self, signal: str, kline_data: dict[str, Any]) -> float:
        """Phase 2: 计算弹性系数（事件方向 × 趋势方向）。

        SPEC-事件驱动策略独立化 §六

        弹性映射:
          事件long × 趋势long  → +1.0（顺势共振，趋势跟随加仓）
          事件short × 趋势short → +1.0（顺势共振）
          事件long × 趋势short → -0.7（逆势反弹，反弹后做空）
          事件short × 趋势long  → -0.7（逆势回调，回调后做多）
          任一neutral           →  0.0（无弹性约束）

        趋势方向判定优先级:
          1. ess_top_direction（"long"/"short"）
          2. close 序列 20 周期斜率
          3. neutral（兜底）
        """
        if signal not in ("long", "short"):
            return ELASTICITY_NONE

        trend = self._detect_trend_direction(kline_data)
        if trend not in ("long", "short"):
            return ELASTICITY_NONE

        if signal == trend:
            return ELASTICITY_TREND_FOLLOW
        return ELASTICITY_MEAN_REVERT

    def _detect_trend_direction(self, kline_data: dict[str, Any]) -> str:
        """检测趋势方向（优先 ess_top_direction，兜底 close 斜率）。"""
        # 优先级 1: ess_top_direction
        ess_dir = kline_data.get("ess_top_direction", "")
        if ess_dir in ("long", "short"):
            return ess_dir

        # 优先级 2: close 序列 20 周期斜率
        close = kline_data.get("close")
        if close and len(close) >= 20:
            recent = close[-20:]
            # 简单线性回归斜率：取首尾差
            if recent[-1] > recent[0]:
                return "long"
            elif recent[-1] < recent[0]:
                return "short"

        return "neutral"

    # ---------------------------------------------------------- 5 维评分

    def _compute_scores(self, data: dict, event_ctx: dict | None = None) -> dict:
        """Phase 3.1: 计算 6 维评分（含新增 news 维度）。

        Args:
            data: K线/事件数据 dict（含 event_context）
            event_ctx: 事件上下文，为 None 时从 data["event_context"] 自动提取

        Returns dict with keys: surprise, priced_in, real_rate, resilience, cross_asset, news
        """
        if event_ctx is None:
            event_ctx = (data or {}).get("event_context") or {}
        return {
            "surprise": self._score_surprise(data, event_ctx),
            "priced_in": self._score_priced_in(data, event_ctx),
            "real_rate": self._score_real_rate(data, event_ctx),
            "resilience": self._score_resilience(data, event_ctx),
            "cross_asset": self._score_cross_asset(data),
            "news": self._score_news(data, event_ctx),
        }

    def _score_surprise(self, data: dict, event_ctx: dict) -> float:
        """Phase 3 ★新增: 事件惊喜强度。

        Surprise = (actual - expected) / σ_historical
        标准化映射到 [0,1]：正惊喜(利好)→高分，负惊喜(利空)→低分

        借鉴: 事件研究法（Andersen 2003）、Pinchuk 2023（1σ通胀惊喜→BTC跌24bps）
        FAIL-OPEN: actual/expected 缺失 → 0.5
        """
        event_type = event_ctx.get("event_type", "none")
        actual = event_ctx.get("actual")
        expected = event_ctx.get("expected")
        sigma = event_ctx.get("surprise_sigma")

        if actual is None or expected is None:
            return 0.5

        try:
            surprise = float(actual) - float(expected)
            if sigma and float(sigma) > 0:
                surprise = surprise / float(sigma)
            # 方向映射
            if event_type in ("fomc", "cpi", "ppi", "nfp"):
                # 利率/通胀/就业 超预期 → 利空黄金(BTC)
                direction = -1.0 if surprise > 0 else 1.0
            else:
                direction = 1.0
            magnitude = math.tanh(abs(surprise) / 2.0)
            score = 0.5 + direction * magnitude * 0.5
            return round(max(0.0, min(1.0, score)), 3)
        except (TypeError, ValueError):
            return 0.5

    def _score_priced_in(self, data: dict, event_ctx: dict) -> float:
        """
        定价充分度 —— "买预期，卖事实"核心逻辑。

        预期阶段（pre_event）：
          hike_prob 越高 → 利空正在被定价 → 价格仍承压 → 低分（空头偏向）
          这是"买预期"阶段，不急于做多。

        事件落地后（event/repricing）：
          利空已出尽 → 定价充分 → 高分（多头偏向）
          这是"卖事实"阶段，资金反手买入。

        expectation_digest 例外：
          概率趋于稳定 + 阶段接近落地 → 预期消化充分，可提前布局（中等偏上）
        """
        cycle_phase = event_ctx.get("cycle_phase", "")

        # 事件已落地 → 利空已出尽，定价充分（多头）
        if cycle_phase in ("event", "repricing"):
            return 0.85

        hike_prob = event_ctx.get("hike_prob")
        if hike_prob is None:
            return 0.5

        p = float(hike_prob)

        # 预期阶段：hike_prob 越高 → 利空压力越大 → 分数越低（空头偏向）
        # hike_prob=0.9 → 0.1（看空），hike_prob=0.5 → 0.5（中性）
        base = max(0.0, 1.0 - p)

        # expectation_digest 例外：概率稳定 + 接近落地 → 预期消化充分
        if cycle_phase == "expectation_digest":
            prob_trend = event_ctx.get("probability_trend", "stable")
            if prob_trend == "stable":
                base = min(1.0, base + 0.25)  # 稳定 + 接近落地 → 预期消化
            else:
                base = min(1.0, base + 0.10)

        # Phase 3 ✓修订: priced-in 比率量化
        # ratio = 预期阶段累计涨跌 / 历史平均反应幅度
        # ratio > 1 → 已过度定价 → 反向修正（卖事实预期）
        pre_event_return = data.get("pre_event_return_pct")
        avg_reaction = data.get("historical_avg_reaction_pct")
        if pre_event_return is not None and avg_reaction and abs(float(avg_reaction)) > 1e-6:
            try:
                ratio = abs(float(pre_event_return)) / abs(float(avg_reaction))
                if ratio > 1.0:
                    base = min(1.0, base + (ratio - 1.0) * 0.3)
            except (TypeError, ValueError):
                pass

        return round(base, 3)

    def _score_real_rate(self, data: dict, event_ctx: dict) -> float:
        """
        实际利率方向 —— 金价的核心驱动。

        实际利率 = 名义利率 - 通胀预期
          - 通胀涨幅 > 加息速度 → 实际利率下行 → 持有黄金机会成本降低 → 看多
          - 加息速度 > 通胀涨幅 → 实际利率上行 → 持有黄金机会成本上升 → 看空

        预期维度：
          - 预期阶段（pre_event）：市场定价未来加息 → 预期实际利率上升 → 利空
          - 事件落地后（post_event）：加息已发生，看实际利率走向

        代理指标：
          - 通胀 = CPI actual（同比%）
          - 名义利率 = fedwatch.effr（T6: 替代硬编码 BASE_RATE_MIDPOINT）
                       + fomc_decision.rate_change（如有）+ hike_prob * 0.25
          - 实际利率 ≈ 名义利率 - CPI

        无数据时返回 0.5（中性）。
        """
        cpi_actual = data.get("cpi_actual")
        fomc_decision = data.get("fomc_decision", {})
        cycle_phase = event_ctx.get("cycle_phase", "")

        # T6 P0 盲区修复（SPEC §3.2.3）：
        # 优先用 fedwatch.effr 替代硬编码 BASE_RATE_MIDPOINT=3.625
        fedwatch = data.get("fedwatch") or {}
        effr = fedwatch.get("effr")
        BASE_RATE_MIDPOINT = 3.625  # 旧硬编码（fallback）

        nominal_rate = None
        # 优先路径 1: fedwatch.effr（真实有效联邦基金利率）
        if effr is not None:
            try:
                nominal_rate = float(effr)
            except (TypeError, ValueError):
                pass

        # 优先路径 2: fomc_decision.rate_change + BASE_RATE_MIDPOINT（fallback）
        if nominal_rate is None and isinstance(fomc_decision, dict):
            rate_change = fomc_decision.get("rate_change")
            if rate_change is not None:
                try:
                    nominal_rate = BASE_RATE_MIDPOINT + float(rate_change)
                except (TypeError, ValueError):
                    pass

        # 预期阶段：加上预期加息幅度
        hike_prob = event_ctx.get("hike_prob")
        # T6: 优先用 fedwatch.hike_prob 替代 event_ctx.hike_prob
        real_hike_prob = fedwatch.get("hike_prob")
        if real_hike_prob is not None:
            hike_prob = real_hike_prob

        is_pre_event = cycle_phase not in ("event", "repricing", "neutral")
        if is_pre_event and hike_prob is not None and nominal_rate is not None:
            try:
                expected_hike = float(hike_prob) * 0.25  # 预期加息 25bp * 概率
                nominal_rate += expected_hike
            except (TypeError, ValueError):
                pass

        if cpi_actual is None or nominal_rate is None:
            return 0.5

        try:
            real_rate = float(nominal_rate) - float(cpi_actual)
        except (TypeError, ValueError):
            return 0.5

        # 实际利率越低 → 越利好黄金（高分）
        if real_rate < 0:
            level_score = 0.90
        elif real_rate < 1.0:
            level_score = 0.65
        elif real_rate < 2.0:
            level_score = 0.45
        elif real_rate < 3.0:
            level_score = 0.25
        else:
            level_score = 0.10

        # Phase 3 ✓增强: 实际利率变化率（Δreal_rate）
        # 下行趋势比绝对水平更重要
        real_rate_history = data.get("real_rate_history")
        delta_score = level_score  # 无历史数据时回退到水平评分（保持原行为）
        if real_rate_history and hasattr(real_rate_history, "__len__") and len(real_rate_history) >= 3:
            try:
                recent = [float(x) for x in real_rate_history[-3:]]
                delta = recent[-1] - recent[0]
                delta_score = 0.5 + (-delta) * 0.5
                delta_score = max(0.0, min(1.0, delta_score))
            except (TypeError, ValueError):
                delta_score = level_score

        # 水平 60% + 变化率 40%
        return round(level_score * 0.6 + delta_score * 0.4, 3)

    def _score_resilience(self, data: dict, event_ctx: Optional[dict] = None) -> float:
        """
        抗跌性: 价格在利空下是否抗跌。

        Phase 3 ✓通用化: 用 expected_event_drop_pct 替代仅 CPI 判断，通用所有事件类型。
          - expected_drop < 0（预期下跌）时：实际跌幅/预期跌幅 比率
          - ratio < 1 → 抗跌（高分 0.85）
          - ratio < 1.5 → 中等（0.60）
          - ratio >= 1.5 → 超跌（0.20）
          - 无预期跌幅时：用近 3 日跌幅代理
        """
        if event_ctx is None:
            event_ctx = {}
        cpi_surprise = data.get("cpi_surprise")
        close = data.get("close", [])
        expected_drop = data.get("expected_event_drop_pct")

        # 近 3 日涨跌幅
        try:
            if hasattr(close, "__len__") and len(close) >= 4:
                ret_3d = (float(close[-1]) - float(close[-4])) / float(close[-4])
            else:
                ret_3d = 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            ret_3d = 0.0

        # Phase 3: 通用化 — 有预期跌幅时用比率
        if expected_drop is not None and float(expected_drop) < 0:
            try:
                ratio = ret_3d / float(expected_drop)  # 两者都为负
                if ratio < 1.0:
                    return 0.85   # 抗跌
                elif ratio < 1.5:
                    return 0.60
                else:
                    return 0.20
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        if cpi_surprise is not None and cpi_surprise > 0:
            # CPI 超预期但价格没怎么跌 → 强抗跌
            if ret_3d > -0.01:
                return 0.85
            elif ret_3d > -0.03:
                return 0.60
            else:
                return 0.20
        else:
            # 无 CPI 数据，单纯看跌幅
            if ret_3d > -0.02:
                return 0.65
            elif ret_3d > -0.05:
                return 0.40
            else:
                return 0.15

    def _score_lower_shadow(self, data: dict) -> float:
        """
        下影线强度: K线下影线占比。
          下影线长 = 多头承接强（高分）
          用最近 3 根 K线的下影线平均占比。
        """
        try:
            high = data.get("high", [])
            low = data.get("low", [])
            open_ = data.get("open", [])
            close = data.get("close", [])
            if not all(hasattr(x, "__len__") and len(x) >= 3 for x in (high, low, open_, close)):
                return 0.5

            shadows = []
            for i in range(-3, 0):
                h = float(high[i])
                l = float(low[i])
                o = float(open_[i])
                c = float(close[i])
                body = abs(c - o)
                full_range = h - l
                if full_range < 1e-9:
                    shadows.append(0.0)
                    continue
                lower_shadow = min(o, c) - l
                shadows.append(lower_shadow / full_range)

            avg_shadow = sum(shadows) / len(shadows)
            # avg_shadow ∈ [0, 1], 0.5 以上算有支撑
            return round(max(0.0, min(1.0, avg_shadow * 1.5)), 3)
        except Exception:
            return 0.5

    def _score_cross_asset(self, data: dict) -> float:
        """
        跨资产验证: 黄金/美债/美元是否同步企稳。

        Phase 3 ✓标准化: 优先用 *_surprise 字段（tanh 标准化），
        替代硬编码阈值（±5bp/±0.5%）。参考 gs-quant MarketDataShockBasedScenario。
          - gold_surprise 正 → +0.25*tanh(s/2)
          - us10y_yield_surprise 正（收益率上行）→ -0.25*tanh(s/2)
          - dxy_surprise 正（美元走强）→ -0.20*tanh(s/2)
        无 surprise 数据时回退到原硬编码逻辑（向后兼容）。
        无跨资产数据时返回 0.5（中性）。
        """
        # Phase 3: 优先用 surprise 标准化
        has_surprise = any(
            data.get(k) is not None
            for k in ("gold_surprise", "us10y_yield_surprise", "dxy_surprise")
        )
        if has_surprise:
            score = 0.5
            available = 0

            gold_surprise = data.get("gold_surprise")
            if gold_surprise is not None:
                available += 1
                try:
                    score += 0.25 * math.tanh(float(gold_surprise) / 2.0)
                except (TypeError, ValueError):
                    pass

            yield_surprise = data.get("us10y_yield_surprise")
            if yield_surprise is not None:
                available += 1
                try:
                    score -= 0.25 * math.tanh(float(yield_surprise) / 2.0)
                except (TypeError, ValueError):
                    pass

            dxy_surprise = data.get("dxy_surprise")
            if dxy_surprise is not None:
                available += 1
                try:
                    score -= 0.20 * math.tanh(float(dxy_surprise) / 2.0)
                except (TypeError, ValueError):
                    pass

            if available == 0:
                return 0.5
            return round(max(0.0, min(1.0, score)), 3)

        # 回退：原硬编码逻辑（向后兼容）
        score = 0.5
        available = 0

        # 黄金
        gold_ret = data.get("gold_change_pct")
        if gold_ret is not None:
            available += 1
            try:
                r = float(gold_ret)
                if r > 0:
                    score += 0.25
                elif r > -0.01:
                    score += 0.10
                else:
                    score -= 0.15
            except (TypeError, ValueError):
                pass

        # 美债收益率（反向）
        us10y_change = data.get("us10y_change_bp")
        if us10y_change is not None:
            available += 1
            try:
                bp = float(us10y_change)
                if bp < -5:
                    score += 0.25
                elif bp < 0:
                    score += 0.10
                else:
                    score -= 0.10
            except (TypeError, ValueError):
                pass

        # 美元指数（反向）
        dxy_change = data.get("dxy_change_pct")
        if dxy_change is not None:
            available += 1
            try:
                d = float(dxy_change)
                if d < -0.005:
                    score += 0.20
                elif d < 0:
                    score += 0.08
                else:
                    score -= 0.10
            except (TypeError, ValueError):
                pass

        if available == 0:
            return 0.5

        return round(max(0.0, min(1.0, score)), 3)

    def _score_news(self, data: dict, event_ctx: dict | None = None) -> float:
        """Phase 3.1 ★新增: 新闻情感评分（第 6 维）。

        双维度简化版：
          - actionability: 有 news_sentiment_score → 1.0，无 → 0.0
          - verdict: 2×(sentiment-0.5)，将 [0,1] 映射到 [-1,1]
          - news_score = clip(0.5 + 0.5×verdict×actionability, 0, 1)

        调研依据: PEAD.txt(文本惊喜漂移是数字惊喜2倍)、GDELT+FinBERT(Sharpe 5.87)
        FAIL-OPEN: 无新闻数据 → 0.5（中性，不影响信号方向）
        """
        sentiment = data.get("news_sentiment_score")
        if sentiment is None:
            return 0.5  # FAIL-OPEN: 无新闻数据

        try:
            sentiment = float(sentiment)
            # 防御性 clamp 到 [0,1]
            sentiment = max(0.0, min(1.0, sentiment))
            has_news = 1.0  # 有情感分即视为有新闻
            verdict = 2.0 * (sentiment - 0.5)  # [0,1] → [-1,1]
            score = 0.5 + 0.5 * verdict * has_news
            return round(max(0.0, min(1.0, score)), 3)
        except (TypeError, ValueError):
            return 0.5  # FAIL-OPEN

    # ---------------------------------------------------------- 前瞻指引

    def _assess_forward_guidance(self, data: dict, event_ctx: dict) -> str:
        """
        评估前瞻指引方向。

        判断依据（优先级）：
          1. fomc_decision.dot_plot_median — 点阵图中位数（最强信号）
          2. fedwatch.effr — 高利率环境（>=4.5%）→ dovish；
                              低利率环境（<=3.5%）→ hawkish
          3. fedwatch.hike_prob + prob_trend — 真实 CME FedWatch 概率
          4. event_ctx.hike_prob（fallback）

        T6 P0 盲区修复（SPEC §3.2.3）：
        - 优先用 fedwatch 真实概率替代 hike_prob=0 兜底
        - 用 effr 替代硬编码 BASE_RATE_MIDPOINT 判断利率环境
        - 无任何数据时返回 ""（不评估）
        """
        fomc = data.get("fomc_decision", {})
        if isinstance(fomc, dict):
            dot_median = fomc.get("dot_plot_median")
            rate_change = fomc.get("rate_change")
            if dot_median is not None:
                try:
                    dm = float(dot_median)
                    if dm > 0.25:  # 点阵图中位数暗示更多加息
                        return "hawkish"
                    elif dm < -0.25:  # 暗示降息
                        return "dovish"
                except (TypeError, ValueError):
                    pass

        # T6: 优先用 fedwatch 真实数据
        fedwatch = data.get("fedwatch") or {}
        real_hike_prob = fedwatch.get("hike_prob")
        effr = fedwatch.get("effr")

        # 用 effr 判断利率环境（替代硬编码 BASE_RATE_MIDPOINT）
        if effr is not None:
            try:
                e = float(effr)
                if e >= 4.5:  # 高利率环境，加息空间有限 → dovish
                    return "dovish"
                elif e <= 3.5:  # 低利率环境，加息空间大 → hawkish
                    return "hawkish"
            except (TypeError, ValueError):
                pass

        # 用真实 hike_prob 替代 event_ctx.hike_prob
        hike_prob = real_hike_prob if real_hike_prob is not None else event_ctx.get("hike_prob")

        # 无任何数据 → 不评估
        if hike_prob is None and effr is None:
            return ""

        # 降级：用 hike_prob 判断
        # T6: fedwatch 真实概率（来自 CME）单独足够触发，无需 prob_trend 配合
        # event_ctx.hike_prob（占位）仍需 prob_trend 配合，避免 baseline 误触发
        prob_trend = event_ctx.get("probability_trend", "stable")
        if hike_prob is not None:
            try:
                p = float(hike_prob)
                if real_hike_prob is not None:
                    # fedwatch 真实概率路径
                    if p >= 0.7:
                        return "hawkish"
                    elif p <= 0.3:
                        return "dovish"
                else:
                    # event_ctx.hike_prob 占位路径（保留 baseline 行为）
                    if p > 0.7 and prob_trend == "rising":
                        return "hawkish"
                    if p < 0.3 and prob_trend == "falling":
                        return "dovish"
            except (TypeError, ValueError):
                pass

        return "neutral"

    # ---------------------------------------------------------- 三阶段动态权衡（SPEC §0.4.4）

    def _apply_three_phase_weighing(
        self,
        composite: float,
        data: dict,
        event_ctx: dict,
        sub_phase: str,
        forward_guidance: str,
    ) -> tuple[float, str]:
        """
        三阶段动态权衡 —— SPEC §0.4.4 核心创新。

        Phase A relief       (0-5天): 不确定性消除+空头回补主导 → 轻仓试多偏向
        Phase B verification (5-15天): 基本面验证 → 改善升级/恶化反手
        Phase C trend        (15天+): 债务周期位置主导 → 扩张持多/紧缩深层利空主导

        Returns: (adjusted_composite, phase_detail_string)
        """
        if sub_phase == "relief":
            # Phase A: 轻仓试多，温和偏多（不确定性消除+空头回补主导）
            adjusted = min(1.0, composite * 1.05)
            return adjusted, "relief(0-5d):轻仓试多 base×0.5"

        if sub_phase == "verification":
            # Phase B: 基本面验证
            improvement, deterioration, available, details = (
                self._score_fundamental_verification(data, event_ctx)
            )
            deep_bearish, bearish_conds = self._check_deep_bearish(
                data, event_ctx, forward_guidance
            )

            if deep_bearish:
                # 深层利空重新主导 → 反手做空偏向
                adjusted = max(0.0, min(1.0, composite * 0.60))
                cond_str = "+".join(bearish_conds)
                return adjusted, f"verification(5-15d):深层利空[{cond_str}] {improvement}/{available}改善→反手做空"

            if available > 0:
                ratio = improvement / available
                if ratio >= 0.5:
                    # ≥50% 改善 → 升级标准多仓
                    adjusted = min(1.0, composite * 1.15)
                    return adjusted, f"verification(5-15d):{improvement}/{available}改善→升级标准多仓"
                elif deterioration > 0:
                    # 有恶化项 → 减仓观望
                    adjusted = max(0.0, min(1.0, composite * 0.95))
                    return adjusted, f"verification(5-15d):{deterioration}项恶化→减仓观望"
                else:
                    # 0 改善但无恶化 → 中性观望
                    return composite, f"verification(5-15d):{improvement}/{available}改善→观望"
            else:
                # 无可用基本面数据 → 温和偏多（FAIL-OPEN）
                return min(1.0, composite * 1.05), "verification(5-15d):无基本面数据→温和偏多"

        if sub_phase == "trend":
            # Phase C: 债务周期位置主导
            monetary_cycle = data.get("monetary_cycle", "neutral")
            deep_bearish, bearish_conds = self._check_deep_bearish(
                data, event_ctx, forward_guidance
            )

            if deep_bearish:
                adjusted = max(0.0, min(1.0, composite * 0.70))
                cond_str = "+".join(bearish_conds)
                return adjusted, f"trend(15d+):深层利空[{cond_str}]→紧缩深层利空主导"

            if monetary_cycle == "easing":
                adjusted = min(1.0, composite * 1.10)
                return adjusted, "trend(15d+):monetary=easing→扩张期持多"
            elif monetary_cycle == "tightening":
                adjusted = max(0.0, min(1.0, composite * 0.70))
                return adjusted, "trend(15d+):monetary=tightening→紧缩期深层利空主导"
            else:
                return composite, "trend(15d+):monetary=neutral→中性"

        # 兜底
        return composite, ""

    def _score_fundamental_verification(
        self, data: dict, event_ctx: dict
    ) -> tuple[int, int, int, list[str]]:
        """
        基本面验证 —— SPEC §0.4.4 Phase B 检查清单。

        检查 4 项基本面改善：
          1. 通胀是否继续回落 (cpi_actual < cpi_expected)
          2. 信贷是否重新扩张 — 暂无数据（FAIL-OPEN）
          3. 盈利预期是否上修 — 暂无数据（FAIL-OPEN）
          4. 空头回补是否完成 — 暂无数据（FAIL-OPEN）

        当 data_center 新增对应 collector 后自动激活。

        Returns: (improvement_count, deterioration_count, available_count, details)
        """
        improvement = 0
        deterioration = 0
        available = 0
        details: list[str] = []

        # 1. 通胀回落
        cpi_actual = data.get("cpi_actual")
        cpi_expected = data.get("cpi_expected")
        if cpi_actual is not None and cpi_expected is not None:
            available += 1
            try:
                if float(cpi_actual) < float(cpi_expected):
                    improvement += 1
                    details.append("通胀回落✓")
                else:
                    deterioration += 1
                    details.append("通胀未回落✗")
            except (TypeError, ValueError):
                pass

        # 2-4: 信贷扩张/盈利上修/空头回补 — 暂无数据，FAIL-OPEN 跳过
        # 新增 data_center.query_credit_spread() / query_earnings_revision() /
        # query_short_interest() 后在此接入

        return improvement, deterioration, available, details

    def _check_deep_bearish(
        self, data: dict, event_ctx: dict, forward_guidance: str
    ) -> tuple[bool, list[str]]:
        """
        深层利空重新主导 5 条件检测 —— SPEC §0.4.3。

        条件清单（权重）：
          ① higher_for_longer  (高): 点阵图偏鹰/鹰派发言/年内加息预期升温
          ② inflation_sticky   (高): CPI/PPI 超预期
          ③ credit_contraction (中): 信贷标准收紧 — 暂用 monetary_cycle 代理
          ④ earnings_miss      (中): EPS 不及预期 — 暂无数据（FAIL-OPEN）
          ⑤ short_covering_done(中): days-to-cover<2 — 暂无数据（FAIL-OPEN）

        触发规则：≥2 项高权重 或 ≥3 项任意 → relief rally 结束

        Returns: (triggered, conditions_met_list)
        """
        high_weight = 0
        total = 0
        conditions: list[str] = []

        # ① higher_for_longer (高权重)
        if forward_guidance == "hawkish":
            high_weight += 1
            total += 1
            conditions.append("higher_for_longer")

        # ② inflation_sticky (高权重)
        cpi_surprise = data.get("cpi_surprise")
        if cpi_surprise is not None:
            try:
                if float(cpi_surprise) > 0:
                    high_weight += 1
                    total += 1
                    conditions.append("inflation_sticky")
            except (TypeError, ValueError):
                pass

        # ③ credit_contraction (中权重) — 用 monetary_cycle 代理
        monetary_cycle = data.get("monetary_cycle")
        if monetary_cycle == "tightening":
            total += 1
            conditions.append("credit_contraction")

        # ④ earnings_miss — 暂无数据，FAIL-OPEN
        # ⑤ short_covering_done — 暂无数据，FAIL-OPEN

        triggered = high_weight >= 2 or total >= 3
        return triggered, conditions


# ================================================================
# Phase 3: EventDrivenTrader — 独立子交易系统
# ================================================================

class EventDrivenTrader:
    """事件驱动独立子交易系统（Phase 3）。

    职责：
    1. 调用 EventDrivenStrategy.evaluate() 获取 EventSignal
    2. 开仓决策：signal != neutral + strength ≥ 动态阈值 + 无持仓
    3. 仓位计算：基础仓位 × strength × 阶段乘数 × 弹性修正
    4. SL/TP 生成：ATR 自适应 + 事件窗口约束
    5. 离场管理：脉冲衰减平仓 + 事件窗口结束平仓 + SL/TP + 信号反转
    6. 状态持久化：EventSignal 写入 shadow（成熟后供其他子系统消费）

    定位：与 BCRM2.0、BDSM 平级的独立子交易系统，初期独立运行优化，
    成熟后通过 SubSystemBridge 开放 EventSignal 接口。
    """

    def __init__(self, strategy: "EventDrivenStrategy", config: Optional[dict] = None):
        self._strategy = strategy
        self._config = config or {}
        self._position: Optional[dict] = None

    def on_kline_close(self, kline_data: dict) -> EventSignal:
        """主入口：每 K 线调用。返回 EventSignal 并执行交易决策。"""
        signal = self._strategy.evaluate(kline_data) if self._strategy else neutral_event_signal()
        self._write_shadow(signal)

        # 离场检查优先
        if self._position is not None:
            if self._should_exit(signal, kline_data):
                self._close_position()
            return signal

        # 开仓检查
        if self._should_open(signal):
            self._open_position(signal, kline_data)

        return signal

    def _should_open(self, signal: EventSignal) -> bool:
        """开仓条件：信号非中性 + strength ≥ 阶段阈值 + 无持仓 + confidence≥0.5。"""
        if signal.signal == "neutral":
            return False
        if self._position is not None:
            return False
        thresholds = PHASE_THRESHOLDS.get(signal.event_phase, PHASE_THRESHOLDS["neutral"])
        long_th = thresholds["long"]
        short_th = thresholds["short"]
        if signal.signal == "long" and signal.strength < long_th:
            return False
        if signal.signal == "short" and signal.strength < (1.0 - short_th):
            return False
        return signal.confidence >= 0.5

    def _compute_position_size(self, signal: EventSignal) -> float:
        """仓位计算：基础仓位 × strength × 阶段乘数 × 弹性修正。"""
        base = self._config.get("base_position", 250.0)  # USDT 名义
        phase_mult = PHASE_POSITION_MULT.get(signal.event_phase, 1.0)
        elasticity_mult = 1.0 + signal.elasticity * 0.3  # 顺势+30%，逆势-21%
        return base * signal.strength * phase_mult * elasticity_mult

    def _compute_sl_tp(self, signal: EventSignal, kline_data: dict) -> tuple[float, float]:
        """SL/TP：ATR 自适应（SL=max(0.04, 5×ATR/close)），TP=3×SL。"""
        atr = kline_data.get("atr", 0.0)
        close = kline_data.get("close")
        close_price = float(close[-1]) if close and hasattr(close, "__len__") and len(close) > 0 else 0
        if atr is None or float(atr) <= 0 or close_price <= 0:
            return 0.04, 0.12  # FAIL-OPEN：硬编码下限
        try:
            sl_pct = max(0.04, min(0.15, 5.0 * float(atr) / close_price))
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.04, 0.12
        tp_pct = min(0.30, sl_pct * 3.0)
        return sl_pct, tp_pct

    def _days_since_event(self, signal: EventSignal) -> float:
        """计算距事件落地的天数。FAIL-OPEN → 0.0。"""
        if not signal.window_end:
            return 0.0
        try:
            event_end = datetime.fromisoformat(signal.window_end)
            return (datetime.now() - event_end).total_seconds() / 86400.0
        except (ValueError, TypeError):
            return 0.0

    def _should_exit(self, signal: EventSignal, kline_data: dict) -> bool:
        """离场条件：脉冲衰减到阈值 / 信号反转。"""
        if self._position is None:
            return False
        # 脉冲衰减平仓：days_since > 3τ
        days_since = self._days_since_event(signal)
        tau = EVENT_HALF_LIFE.get(signal.event_type, 1.0)
        if tau > 0 and days_since > 3 * tau:
            return True
        # 信号反转
        if signal.signal != "neutral" and signal.signal != self._position.get("direction"):
            return True
        return False

    def apply_pulse_decay(self, composite: float, signal: EventSignal) -> float:
        """对 composite 施加脉冲衰减（弹性修正）。

        顺势（elasticity>0）：脉冲同向增强 composite
        逆势（elasticity<0）：t<τ 时反向（均值回归预期），t>τ 不调整
        """
        if signal.event_type == "none" or not signal.window_end:
            return composite
        days_since = self._days_since_event(signal)
        tau = EVENT_HALF_LIFE.get(signal.event_type, 1.0)
        pulse = compute_impulse(signal.event_type, days_since, signal.strength)
        if tau > 0 and days_since > 3 * tau:
            return composite
        elasticity = signal.elasticity
        if elasticity > 0:
            if signal.signal == "long":
                return min(1.0, composite + pulse * 0.15)
            else:
                return max(0.0, composite - pulse * 0.15)
        elif elasticity < 0:
            if tau > 0 and days_since < tau:
                if signal.signal == "long":
                    return max(0.0, composite - pulse * 0.10)
                else:
                    return min(1.0, composite + pulse * 0.10)
        return composite

    def _open_position(self, signal: EventSignal, kline_data: dict) -> None:
        """开仓（占位实现，实际接入执行层）。"""
        size = self._compute_position_size(signal)
        sl, tp = self._compute_sl_tp(signal, kline_data)
        self._position = {
            "direction": signal.signal,
            "size": size,
            "sl": sl,
            "tp": tp,
            "entry_time": signal.window_end,
            "event_type": signal.event_type,
        }

    def _close_position(self) -> None:
        """平仓（占位实现，实际接入执行层）。"""
        self._position = None

    def _write_shadow(self, signal: EventSignal) -> None:
        """将 EventSignal 写入 trader shadow（成熟后供其他子系统消费）。

        FAIL-OPEN：无 trader 引用时静默跳过。
        """
        try:
            trader = self._config.get("_trader")
            if trader is not None:
                trader._event_signal_shadow = signal.to_dict()
        except Exception as e:
            logger.debug("[FO] event_signal_shadow write fail: %s", e)

    @property
    def position(self) -> Optional[dict]:
        """当前持仓状态（只读）。"""
        return self._position
