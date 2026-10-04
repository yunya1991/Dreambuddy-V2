"""四方案 voter 实现

A. VCPVoter_A          — 结构化止损（Minervini VCP）
   判定：趋势失效 = 价格跌破 recent_swing_low 或 entry - 2×ATR
B. ATRStandardVoter_B  — ATR 标准化
   判定：|upl_ratio| < 0.3×ATR_daily 才算"无进展"（替代固定 1%）
C. WyckoffSupportVoter_C — 支撑位保护（Wyckoff）
   判定：支撑位上方 → hold + SL 下移；支撑位下方 → force_close
D. MurphyDecayVoter_D  — 时间衰减式（Murphy）
   判定：0-12h 1.5%, 12-24h 1.0%, 24h+ 0.5%

FAIL-OPEN：任何异常 → 返回 None（不投票）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from dreambuddy_evolution.engines.exit_engine.timeout_voters.base_voter import (
    TimeoutVoter,
    VoteTicket,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 方案A: 结构化止损（Minervini VCP）
# ============================================================================

class VCPVoter_A(TimeoutVoter):
    """方案A: 结构化止损

    趋势失效判定：
      - 价格跌破 recent_swing_low → 趋势破位 → force_close
      - 或 current_price < entry_price - 2×ATR → Chandelier 式破位 → force_close
      - 否则 → hold（结构未破）

    理论基础：Mark Minervini VCP（Volatility Contraction Pattern）
    趋势应该随时间收敛波动，破位才是真正的失效信号。
    """

    voter_id = "A"

    # ATR 倍数阈值（Chandelier 风格，与 exit_engine.ATR_SL_MULTIPLIER 对齐）
    ATR_BREAKDOWN_MULT = 2.0

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[VoteTicket]:
        try:
            current_price = float(ctx.get("current_price", 0.0) or 0.0)
            recent_swing_low = ctx.get("recent_swing_low")
            atr_pct = float(ctx.get("atr_pct", 0.0) or 0.0)
            pos_side = str(ctx.get("pos_side", "long")).lower()
            entry_price = float(ctx.get("entry_price", 0.0) or 0.0)

            # 字段缺失 → FAIL-OPEN
            if current_price <= 0 or entry_price <= 0:
                return None

            # swing_low 缺失时只用 ATR 倍数判定
            if recent_swing_low is not None:
                swing_low = float(recent_swing_low)
                if swing_low > 0 and current_price < swing_low:
                    return VoteTicket(
                        action="force_close",
                        confidence=0.75,
                        reason=f"voter_a:vcp_break_below_swing_low_{swing_low:.2f}",
                        voter_id=self.voter_id,
                    )

            # Chandelier 式破位：entry - 2×ATR
            if atr_pct > 0:
                breakdown_threshold = entry_price * (1 - self.ATR_BREAKDOWN_MULT * atr_pct)
                if current_price < breakdown_threshold:
                    return VoteTicket(
                        action="force_close",
                        confidence=0.70,
                        reason=f"voter_a:atr_2x_breakdown_below_{breakdown_threshold:.2f}",
                        voter_id=self.voter_id,
                    )

            # 结构未破 → hold
            return VoteTicket(
                action="hold",
                confidence=0.6,
                reason=f"voter_a:above_swing_low_atr_{atr_pct:.2%}",
                voter_id=self.voter_id,
            )
        except Exception as e:
            logger.debug("[FO] VCPVoter_A evaluate crash: %s", e)
            return None

    def required_fields(self) -> list[str]:
        return [
            "current_price",
            "recent_swing_low",  # 可选，缺失时用 ATR 判定
            "atr_pct",
            "pos_side",
            "entry_price",
        ]


# ============================================================================
# 方案B: ATR 标准化
# ============================================================================

class ATRStandardVoter_B(TimeoutVoter):
    """方案B: ATR 标准化

    用 ATR 倍数替代固定 1% 阈值，适配不同波动率品种：
      - |upl_ratio| < 0.3×ATR_daily → "无进展" → force_close
      - |upl_ratio| ≥ 0.3×ATR_daily → 有波动 → hold

    理论基础：ATR 自适应。低波动品种 24h 内 1% 波动是正常的，
    不应误判为"无进展"。
    """

    voter_id = "B"

    # "无进展"阈值 = 0.3×ATR_daily
    NO_PROGRESS_ATR_MULT = 0.3

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[VoteTicket]:
        try:
            upl_ratio = float(ctx.get("upl_ratio", 0.0) or 0.0)
            atr_daily = ctx.get("atr_daily")

            # atr_daily 缺失时回退 atr_pct × sqrt(6)（4H → 日线近似）
            if atr_daily is None:
                atr_pct = ctx.get("atr_pct", 0.0)
                if not atr_pct:
                    return None
                import math
                atr_daily = float(atr_pct) * math.sqrt(6)
            else:
                atr_daily = float(atr_daily)

            if atr_daily <= 0:
                return None

            abs_upl = abs(upl_ratio)
            no_progress_threshold = self.NO_PROGRESS_ATR_MULT * atr_daily

            if abs_upl < no_progress_threshold:
                return VoteTicket(
                    action="force_close",
                    confidence=0.65,
                    reason=f"voter_b:atr_no_progress_{abs_upl:.4f}_<_{no_progress_threshold:.4f}",
                    voter_id=self.voter_id,
                )

            # 有波动 → hold
            return VoteTicket(
                action="hold",
                confidence=0.60,
                reason=f"voter_b:atr_significant_move_{abs_upl:.4f}_>=_{no_progress_threshold:.4f}",
                voter_id=self.voter_id,
            )
        except Exception as e:
            logger.debug("[FO] ATRStandardVoter_B evaluate crash: %s", e)
            return None

    def required_fields(self) -> list[str]:
        return ["upl_ratio", "atr_daily"]


# ============================================================================
# 方案C: 支撑位保护（Wyckoff）
# ============================================================================

class WyckoffSupportVoter_C(TimeoutVoter):
    """方案C: 支撑位保护

    超时强平前检查价格相对支撑位的位置：
      - current_price > support × 1.02 → 支撑位上方 → hold + SL 下移到 support×0.997
      - current_price ≤ support × 1.02 → 支撑位已破 → force_close

    理论基础：Wyckoff 市场结构。支撑位是需求区，首次回踩是正常趋势波动，
    不应在支撑位上方误强平（amateur mistake）。
    """

    voter_id = "C"

    # 支撑位上方安全缓冲（2%）
    SUPPORT_SAFETY_MULT = 1.02
    # SL 下移到支撑位下方的 buffer（0.3%）
    SL_BUFFER_PCT = 0.003  # SL = support × (1 - 0.003) = support × 0.997

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[VoteTicket]:
        try:
            current_price = float(ctx.get("current_price", 0.0) or 0.0)
            nearest_support_level = ctx.get("nearest_support_level")

            if current_price <= 0 or nearest_support_level is None:
                return None

            support = float(nearest_support_level)
            if support <= 0:
                return None

            support_threshold = support * self.SUPPORT_SAFETY_MULT

            if current_price > support_threshold:
                # 支撑位上方 → hold + SL 下移
                new_sl = support * (1.0 - self.SL_BUFFER_PCT)  # support × 0.997
                return VoteTicket(
                    action="adjust_sl_tp",
                    confidence=0.75,
                    reason=f"voter_c:above_support_{support:.2f}_sl_to_{new_sl:.2f}",
                    voter_id=self.voter_id,
                    sl_px=new_sl,
                )

            # 支撑位已破 → force_close
            return VoteTicket(
                action="force_close",
                confidence=0.70,
                reason=f"voter_c:below_support_{support:.2f}_current_{current_price:.2f}",
                voter_id=self.voter_id,
            )
        except Exception as e:
            logger.debug("[FO] WyckoffSupportVoter_C evaluate crash: %s", e)
            return None

    def required_fields(self) -> list[str]:
        return ["current_price", "nearest_support_level", "pos_side", "entry_price"]


# ============================================================================
# 方案D: 时间衰减式（Murphy）
# ============================================================================

class MurphyDecayVoter_D(TimeoutVoter):
    """方案D: 时间衰减式

    趋势应该随时间收敛波动，容许阈值递减：
      - 0-12h: |upl| > 1.5% → hold（早期容许较大波动）
      - 12-24h: |upl| > 1.0% → hold
      - 24h+: |upl| > 0.5% 或破结构 → hold；否则 force_close

    理论基础：Murphy 趋势交易法则。趋势应该随时间收敛，
    若 24h+ 仍无 0.5% 进展，说明趋势可能失效。
    """

    voter_id = "D"

    # 时间衰减阈值表
    DECAY_THRESHOLDS = [
        (12 * 3600, 0.015),   # 0-12h: 1.5%
        (24 * 3600, 0.010),   # 12-24h: 1.0%
        (float("inf"), 0.005),  # 24h+: 0.5%
    ]

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[VoteTicket]:
        try:
            upl_ratio = float(ctx.get("upl_ratio", 0.0) or 0.0)
            position_age_sec = float(ctx.get("position_age_sec", 0.0) or 0.0)

            if position_age_sec < 0:
                return None

            abs_upl = abs(upl_ratio)

            # 按时间衰减查阈值
            threshold = self.DECAY_THRESHOLDS[-1][1]  # 默认 0.5%
            for age_limit, thr in self.DECAY_THRESHOLDS:
                if position_age_sec < age_limit:
                    threshold = thr
                    break

            if abs_upl > threshold:
                # 有足够波动 → hold
                return VoteTicket(
                    action="hold",
                    confidence=0.60,
                    reason=f"voter_d:decay_age_{int(position_age_sec/3600)}h_upl_{abs_upl:.4f}_>_thr_{threshold:.4f}",
                    voter_id=self.voter_id,
                )

            # 无进展 → force_close
            return VoteTicket(
                action="force_close",
                confidence=0.65,
                reason=f"voter_d:decay_age_{int(position_age_sec/3600)}h_upl_{abs_upl:.4f}_<_thr_{threshold:.4f}",
                voter_id=self.voter_id,
            )
        except Exception as e:
            logger.debug("[FO] MurphyDecayVoter_D evaluate crash: %s", e)
            return None

    def required_fields(self) -> list[str]:
        return ["upl_ratio", "position_age_sec"]
