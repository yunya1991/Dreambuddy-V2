"""ExitRewardCalculator — L3 离场奖励组件化

三组件奖励函数 R_total = w_trend×R_trend + w_risk×R_risk + w_pnl×R_pnl

权重硬约束（来自记忆库 VM-1788522224185）：
  - w_pnl ≤ 0.3
  - w_trend ≥ 0.4
  - 三组件独立观测（分别返回 R_trend / R_risk / R_pnl）

组件定义：
  R_trend: 方向正确性
    - CS ≥ 0.7 → +1.0
    - CS ≤ -0.2 → -1.0
    - 否则 → 0.0
  R_risk: 风控合规
    - 止损在预设区间 → +0.5
    - 超范围 → -0.5
  R_pnl: 盈亏
    - pnl_pct ≥ tp_pct_target → +1.0
    - pnl_pct ≤ -sl_pct_target → -1.0
    - 中间按比例缩放

FAIL-OPEN: 任何异常 → R_total=0.0，不阻塞反思回路
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ExitRewardCalculator:
    """L3 离场奖励组件化计算器

    被 ReflectionEngine.apply_reward() 或 EvolutionExitEngine 调用，
    用于计算离场决策的三组件奖励，供 L3 ShadowRL 记录 (s, a, R, s')。
    """

    # 权重硬约束：w_pnl ≤ 0.3, w_trend ≥ 0.4
    W_TREND = 0.4
    W_RISK = 0.3
    W_PNL = 0.3

    # R_trend 阈值
    CS_HIGH_THRESHOLD = 0.7   # CS ≥ 0.7 → +1.0
    CS_LOW_THRESHOLD = -0.2   # CS ≤ -0.2 → -1.0

    # R_risk 奖惩值
    R_RISK_IN_RANGE = 0.5
    R_RISK_OUT_OF_RANGE = -0.5

    # R_pnl 边界值
    R_PNL_TP = 1.0
    R_PNL_SL = -1.0

    def calculate(self, context: Dict[str, Any]) -> Dict[str, float]:
        """计算三组件奖励

        Args:
            context:
              cs: float — CS 一致性得分 [-1.0, 1.0]
              sl_in_range: bool — 止损是否在预设区间
              pnl_pct: float — 实际盈亏比例（如 0.05 = +5%）
              tp_pct_target: float — 目标止盈比例（如 0.06）
              sl_pct_target: float — 目标止损比例（如 0.03，默认 0.03）

        Returns:
            {R_total, R_trend, R_risk, R_pnl, w_trend, w_risk, w_pnl}

        FAIL-OPEN: 任何异常 → 全 0 返回
        """
        try:
            cs = float(context.get("cs", 0.0) or 0.0)
            sl_in_range = bool(context.get("sl_in_range", True))
            pnl_pct = float(context.get("pnl_pct", 0.0) or 0.0)
            tp_pct_target = float(context.get("tp_pct_target", 0.06) or 0.06)
            sl_pct_target = float(context.get("sl_pct_target", 0.03) or 0.03)

            # ── R_trend: 方向正确性 ──
            r_trend = self._calc_r_trend(cs)

            # ── R_risk: 风控合规 ──
            r_risk = self._calc_r_risk(sl_in_range)

            # ── R_pnl: 盈亏 ──
            r_pnl = self._calc_r_pnl(pnl_pct, tp_pct_target, sl_pct_target)

            # ── R_total: 加权求和 ──
            r_total = (
                self.W_TREND * r_trend
                + self.W_RISK * r_risk
                + self.W_PNL * r_pnl
            )

            return {
                "R_total": round(r_total, 4),
                "R_trend": r_trend,
                "R_risk": r_risk,
                "R_pnl": r_pnl,
                "w_trend": self.W_TREND,
                "w_risk": self.W_RISK,
                "w_pnl": self.W_PNL,
            }
        except Exception as exc:
            logger.warning("[ExitRewardCalculator] calculate crash (FAIL-OPEN): %s", exc)
            return {
                "R_total": 0.0,
                "R_trend": 0.0,
                "R_risk": 0.0,
                "R_pnl": 0.0,
                "w_trend": self.W_TREND,
                "w_risk": self.W_RISK,
                "w_pnl": self.W_PNL,
            }

    def _calc_r_trend(self, cs: float) -> float:
        """R_trend: 方向正确性"""
        if cs >= self.CS_HIGH_THRESHOLD:
            return 1.0
        if cs <= self.CS_LOW_THRESHOLD:
            return -1.0
        return 0.0

    def _calc_r_risk(self, sl_in_range: bool) -> float:
        """R_risk: 风控合规"""
        return self.R_RISK_IN_RANGE if sl_in_range else self.R_RISK_OUT_OF_RANGE

    def _calc_r_pnl(self, pnl_pct: float, tp_pct_target: float, sl_pct_target: float) -> float:
        """R_pnl: 盈亏（按比例缩放）"""
        if tp_pct_target <= 0:
            tp_pct_target = 0.06  # 兜底
        if sl_pct_target <= 0:
            sl_pct_target = 0.03  # 兜底

        if pnl_pct >= tp_pct_target:
            return self.R_PNL_TP
        if pnl_pct <= -sl_pct_target:
            return self.R_PNL_SL
        # 中间区域：按比例缩放
        if pnl_pct >= 0:
            # 0 ~ tp 之间：0 ~ +1.0
            return round(pnl_pct / tp_pct_target, 4)
        else:
            # -sl ~ 0 之间：-1.0 ~ 0
            return round(pnl_pct / sl_pct_target, 4)
