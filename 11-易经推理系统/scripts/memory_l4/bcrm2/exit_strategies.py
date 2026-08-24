# -*- coding: utf-8 -*-
"""ExitStrategy 子类实现 — 持仓与离场管理层扩展层.

Spec: docs/superpowers/specs/2026-08-20-exit-manager-design.md

策略优先级（数字小先评估）:
  10: P3EarlyExitStrategy         — P3 提前退出（TDA+Ising 双重预警）
  20: SignalReverseStrategy       — 信号反转
  30: EvForceCloseStrategy        — EV 雷达强制离场
  40: TimeoutProfitSwitchStrategy — 超时止盈换仓
  50: RankedTpStrategy           — 排名止盈 A/B/C 三档
  60: EvAdjustStrategy           — EV 雷达调整（移动止盈/收紧止损）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .exit_manager import ExitContext, ExitDecision, ExitStrategy


# ================================================================
# P3EarlyExitStrategy (priority=10)
# 原位置: polling_trader.py L5676-5732
# 触发条件: early_exit_signal + 保护期浮亏阈值 + N次确认
# ================================================================

class P3EarlyExitStrategy(ExitStrategy):
    """P3 提前退出策略。

    触发条件:
      - inference["early_exit_signal"] == True
      - 保护期内需浮亏 >= protected_p3_min_loss_pct
      - 连续 N 次触发才确认（exit_confirm_required）
    """

    name = "p3_early_exit"
    priority = 10

    def __init__(
        self,
        exit_confirm_required: int = 2,
        protected_p3_min_loss_pct: float = -0.08,
    ):
        self.exit_confirm_required = exit_confirm_required
        self.protected_p3_min_loss_pct = protected_p3_min_loss_pct
        # 每币种累计确认计数
        self._confirm_counts: Dict[str, int] = {}

    def evaluate(self, ctx: ExitContext) -> ExitDecision:
        early_exit = ctx.inference.get("early_exit_signal", False)

        if not early_exit:
            # 信号消失：清除累计确认
            self._confirm_counts.pop(ctx.coin, None)
            return ExitDecision.pass_()

        # 保护期内：浮亏未达阈值 → 拦截（假预警直接走）
        upl_ratio = float(ctx.pos_info.get("upl_ratio", 0.0))
        if ctx.in_protection and upl_ratio > self.protected_p3_min_loss_pct:
            return ExitDecision.pass_()

        # 离场确认：需 N 次连续触发
        cnt = self._confirm_counts.get(ctx.coin, 0) + 1
        self._confirm_counts[ctx.coin] = cnt
        if cnt < self.exit_confirm_required:
            return ExitDecision(
                action="hold",
                reason=f"p3_early_exit_pending:{cnt}/{self.exit_confirm_required}",
            )

        # 确认通过 → force_close
        self._confirm_counts.pop(ctx.coin, None)
        return ExitDecision(
            action="force_close",
            reason="p3_early_exit",
        )


# ================================================================
# SignalReverseStrategy (priority=20)
# 原位置: polling_trader.py L5594-5645
# 触发条件: pos_side != direction + 置信度 >= threshold + 2次确认
# ================================================================

class SignalReverseStrategy(ExitStrategy):
    """信号反转策略。

    触发条件:
      - pos_side == "long" and direction == "DOWN"（多→空反转）
      - 或 pos_side == "short" and direction == "UP"（空→多反转）
      - 置信度 >= reverse_threshold
      - 保护期内 threshold = max(base + boost, 0.85)
      - 连续 N 次触发才确认（exit_confirm_required）
    """

    name = "signal_reverse"
    priority = 20

    def __init__(
        self,
        base_threshold: float = 0.7,
        protected_conf_boost: float = 0.12,
        protected_min_threshold: float = 0.85,
        exit_confirm_required: int = 2,
        min_reverse_threshold: float = 0.0,
        reverse_confidence_margin: float = 0.0,
        protected_margin_multiplier: float = 2.0,
    ):
        self.base_threshold = base_threshold
        self.protected_conf_boost = protected_conf_boost
        self.protected_min_threshold = protected_min_threshold
        self.exit_confirm_required = exit_confirm_required
        # ── PUMP事件 (2026-08-23): 新增反向阈值约束 ──
        # 硬下限：无论 effective_threshold 多低（如融合层 thr_mult 压低到 0.6357），
        # 实际阈值不得低于此值。0.0 = 禁用。
        self.min_reverse_threshold = min_reverse_threshold
        # 余量：confidence - effective_threshold ≥ margin 才视作"真满足阈值"，
        # 避免 barely pass（0.65 vs 0.6357，margin仅0.014）就触发平仓。
        self.reverse_confidence_margin = reverse_confidence_margin
        # 保护期余量乘数：保护期内 margin × 此倍率（更严格）
        self.protected_margin_multiplier = protected_margin_multiplier
        self._confirm_counts: Dict[str, int] = {}

    def _reverse_threshold(self, in_protection: bool,
                           effective_threshold: Optional[float] = None) -> float:
        """计算当前反转置信度阈值（含硬下限）。"""
        base = effective_threshold if effective_threshold is not None else self.base_threshold
        # Step 1: 应用保护期抬升（原逻辑）
        if not in_protection:
            thr = base
        else:
            thr = max(
                base + self.protected_conf_boost,
                self.protected_min_threshold,
            )
        # Step 2: [PUMP修复] 硬下限兜底
        if self.min_reverse_threshold and thr < self.min_reverse_threshold:
            thr = self.min_reverse_threshold
        return thr

    def _effective_margin(self, in_protection: bool) -> float:
        """当前生效的余量（保护期×multiplier）。"""
        if in_protection and self.protected_margin_multiplier:
            return self.reverse_confidence_margin * self.protected_margin_multiplier
        return self.reverse_confidence_margin

    def _is_reverse(self, pos_side: str, direction: str,
                    confidence: float, threshold: float,
                    in_protection: bool = False) -> bool:
        """判断是否构成反转信号（含余量检查）。"""
        opposite = (
            (pos_side == "long" and direction == "DOWN")
            or (pos_side == "short" and direction == "UP")
        )
        if not opposite:
            return False
        if confidence < threshold:
            return False
        # [PUMP修复] 余量保护：confidence 必须比阈值超 margin 才算达标
        margin = self._effective_margin(in_protection)
        if margin > 0 and (confidence - threshold) < margin:
            return False
        return True

    def evaluate(self, ctx: ExitContext) -> ExitDecision:
        pos_side = ctx.pos_info.get("pos_side", "")
        direction = ctx.inference.get("direction", "")
        confidence = float(ctx.confidence or 0.0)
        threshold = self._reverse_threshold(
            ctx.in_protection, ctx.effective_threshold)

        if not self._is_reverse(pos_side, direction,
                                confidence, threshold,
                                in_protection=ctx.in_protection):
            # 反转条件不再满足：清除累计确认状态
            self._confirm_counts.pop(ctx.coin, None)
            return ExitDecision.pass_()

        # 离场确认：需 N 次连续触发
        cnt = self._confirm_counts.get(ctx.coin, 0) + 1
        self._confirm_counts[ctx.coin] = cnt
        if cnt < self.exit_confirm_required:
            return ExitDecision(
                action="hold",
                reason=f"signal_reverse_pending:{cnt}/{self.exit_confirm_required}",
            )

        # 确认通过 → force_close
        self._confirm_counts.pop(ctx.coin, None)
        return ExitDecision(
            action="force_close",
            reason="signal_reverse",
        )


# ================================================================
# EvForceCloseStrategy (priority=30)
# 原位置: polling_trader.py L3415-3436
# 触发条件: ev < force_below + 非保护期 + 2次确认
# BCRM2 spec: enabled = S2 (enable_ev_radar)
# ================================================================

class EvForceCloseStrategy(ExitStrategy):
    """EV 雷达强制离场策略。

    触发条件:
      - ev < force_below
      - 非保护期内
      - 连续 N 次触发才确认（exit_confirm_required）
    """

    name = "ev_force_close"
    priority = 30

    def __init__(
        self,
        force_below: float = -0.35,
        exit_confirm_required: int = 2,
        enabled: bool = True,
    ):
        self.force_below = force_below
        self.exit_confirm_required = exit_confirm_required
        self.enabled = enabled
        self._confirm_counts: Dict[str, int] = {}

    def evaluate(self, ctx: ExitContext) -> ExitDecision:
        if not self.enabled:
            return ExitDecision.pass_()
        ev = float(ctx.ev or 0.0)

        # 保护期内或 EV 未达阈值 → 不触发
        if ctx.in_protection or ev >= self.force_below:
            self._confirm_counts.pop(ctx.coin, None)
            return ExitDecision.pass_()

        # 离场确认：需 N 次连续触发
        cnt = self._confirm_counts.get(ctx.coin, 0) + 1
        self._confirm_counts[ctx.coin] = cnt
        if cnt < self.exit_confirm_required:
            return ExitDecision(
                action="hold",
                reason=f"ev_force_close_pending:{cnt}/{self.exit_confirm_required}",
            )

        # 确认通过 → force_close
        self._confirm_counts.pop(ctx.coin, None)
        return ExitDecision(
            action="force_close",
            reason="ev_force_close",
        )


# ================================================================
# TimeoutProfitSwitchStrategy (priority=40)
# 原位置: polling_trader.py L5887-5965
# 触发条件: age > 29h + 盈利 + 有更强信号候选
# ================================================================

class TimeoutProfitSwitchStrategy(ExitStrategy):
    """超时止盈换仓策略。

    触发条件:
      - 持仓时长 > timeout_hours（29h）
      - 盈利（upl > 0）
      - 存在更强信号候选（score 严格大于持仓）
    做空信号打 short_score_discount 折扣（0.95）。
    """

    name = "timeout_profit_switch"
    priority = 40

    def __init__(
        self,
        timeout_hours: float = 29.0,
        short_score_discount: float = 0.95,
        confidence_threshold: float = 0.0,
    ):
        self.timeout_hours = timeout_hours
        self.short_score_discount = short_score_discount
        self.confidence_threshold = confidence_threshold

    def _score(self, confidence: float, direction: str) -> float:
        """计算信号综合得分（做空打折扣）。"""
        mult = self.short_score_discount if direction == "DOWN" else 1.0
        return confidence * mult

    def evaluate(self, ctx: ExitContext) -> ExitDecision:
        # 未超时 → pass
        if ctx.age_hours <= self.timeout_hours:
            return ExitDecision.pass_()

        # 亏损 → pass（走 classic 备用离场）
        upl = float(ctx.pos_info.get("upl", 0.0))
        if upl <= 0:
            return ExitDecision.pass_()

        # 无跨币种数据 → pass
        all_inf = ctx.all_inferences or {}
        if not all_inf:
            return ExitDecision.pass_()

        held_coins = set(ctx.held_coins or [ctx.coin])
        held_conf = float(ctx.inference.get("confidence", 0.0))
        held_dir = ctx.inference.get("direction", "")
        held_score = self._score(held_conf, held_dir)

        # 搜索更强候选（score 严格大于持仓）
        best_candidate = None
        best_score = held_score
        for other_coin, other_inf in all_inf.items():
            if other_coin in held_coins or other_coin == ctx.coin:
                continue
            other_dir = other_inf.get("direction", "")
            if other_dir not in ("UP", "DOWN"):
                continue
            other_conf = float(other_inf.get("confidence", 0.0))
            if other_conf < self.confidence_threshold:
                continue
            other_score = self._score(other_conf, other_dir)
            if other_score > best_score:
                best_candidate = (other_coin, other_dir, other_conf, other_score)
                best_score = other_score

        if best_candidate:
            bc_coin, bc_dir, bc_conf, bc_score = best_candidate
            return ExitDecision(
                action="force_close",
                reason="timeout_profit_switch",
                params={
                    "target_coin": bc_coin,
                    "target_direction": bc_dir,
                    "target_confidence": bc_conf,
                    "target_score": bc_score,
                },
            )

        return ExitDecision.pass_()


# ================================================================
# RankedTpStrategy (priority=50)
# 原位置: polling_trader.py L3758-3866
# 触发条件: A档(gap>=阈值+非保护期) / B档(gap<阈值+age>=12h+盈利) / C档(无动作)
# BCRM2 spec: enabled = S4 (enable_ranked_tp)
# ================================================================

class RankedTpStrategy(ExitStrategy):
    """排名止盈 A/B/C 三档策略。

    A 档（立即止盈换仓）：gap >= gap_threshold + 非保护期 → force_close
    B 档（排队止盈）：gap < gap_threshold + age >= 12h + 盈利 → adjust_sl_tp
    C 档（不参与）：保护期内 / 亏损 / gap 极小 → pass
    """

    name = "ranked_tp"
    priority = 50

    def __init__(
        self,
        gap_threshold: float = 0.70,
        b_tier_age_threshold: float = 12.0,
        enabled: bool = True,
    ):
        self.gap_threshold = gap_threshold
        self.b_tier_age_threshold = b_tier_age_threshold
        self.enabled = enabled

    def evaluate(self, ctx: ExitContext) -> ExitDecision:
        if not self.enabled:
            return ExitDecision.pass_()

        # 非 top1 持仓 → pass
        is_top1 = bool(ctx.pos_info.get("is_top1", False))
        if not is_top1:
            return ExitDecision.pass_()

        gap_ratio = float(ctx.pos_info.get("ranked_tp_gap", 0.0))
        upl = float(ctx.pos_info.get("upl", 0.0))

        # ── A 档：gap 达标 + 非保护期 → force_close ──
        if gap_ratio >= self.gap_threshold and not ctx.in_protection:
            return ExitDecision(
                action="force_close",
                reason="ranked_tp_a",
                params={"gap_ratio": gap_ratio},
            )

        # ── B 档：gap 不够但持仓老 + 有盈利 → 写 reduce_plan ──
        if (not ctx.in_protection and upl > 0
                and ctx.age_hours >= self.b_tier_age_threshold
                and gap_ratio > 0):
            return ExitDecision(
                action="adjust_sl_tp",
                reason="ranked_tp_b",
                params={
                    "reduce_plan": {
                        "type": "ranked_tp",
                        "wait_cycles": 2,
                        "trigger_rank": round(gap_ratio, 4),
                    },
                    "gap_ratio": gap_ratio,
                },
            )

        # ── C 档：无动作 ──
        return ExitDecision.pass_()


# ================================================================
# EvAdjustStrategy (priority=60)
# 原位置: polling_trader.py L3455-3482
# 触发条件: T2 WARN(收紧) / T4 STRONG_HOLD(放宽) / T3 NORMAL(无动作)
# BCRM2 spec: enabled = S2 (enable_ev_radar)
# ================================================================

class EvAdjustStrategy(ExitStrategy):
    """EV 雷达调整（移动止盈）策略。

    四档决策:
      - T2 WARN: warn_lower <= ev < warn_upper → adjust_sl_tp mode=tighten
      - T4 STRONG_HOLD: ev > strong_above → adjust_sl_tp mode=relax
      - T3 NORMAL: warn_upper <= ev <= strong_above → pass
      - 保护期内 ev < warn_upper → pass（T1/T2 禁用，T4 仍可放宽）
    """

    name = "ev_adjust"
    priority = 60

    def __init__(
        self,
        warn_lower: float = -0.35,
        warn_upper: float = -0.10,
        strong_above: float = 0.30,
        enabled: bool = True,
    ):
        self.warn_lower = warn_lower
        self.warn_upper = warn_upper
        self.strong_above = strong_above
        self.enabled = enabled

    def evaluate(self, ctx: ExitContext) -> ExitDecision:
        if not self.enabled:
            return ExitDecision.pass_()

        ev = float(ctx.ev or 0.0)

        # 保护期门禁：ev < warn_upper 时 T1/T2 禁用
        if ctx.in_protection and ev < self.warn_upper:
            return ExitDecision.pass_()

        # T2 WARN: 收紧止损
        if self.warn_lower <= ev < self.warn_upper:
            return ExitDecision(
                action="adjust_sl_tp",
                reason="ev_tighten",
                params={"mode": "tighten", "ev": ev},
            )

        # T4 STRONG_HOLD: 放宽止损/止盈
        if ev > self.strong_above:
            return ExitDecision(
                action="adjust_sl_tp",
                reason="ev_relax",
                params={"mode": "relax", "ev": ev},
            )

        # T3 NORMAL: 按原计划持有
        return ExitDecision.pass_()
