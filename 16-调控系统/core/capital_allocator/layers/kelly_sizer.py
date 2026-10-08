"""Layer 2: KellySizer
=====================

职责：基于收缩后的绩效数据，计算 per-coin 最优仓位。

Kelly 公式：
  f = W - (1-W)/R
  W = 胜率, R = 盈亏比

Half-Kelly：
  f_safe = f * 0.5  （风险减半，降低波动率）

仓位映射：
  f_half ∈ [0, 1] → position_pct ∈ [MIN_PCT, MAX_PCT]
  冷启动（n < cold_start_min_trades）→ DEFAULT_PCT

杠杆联动（传统金融 1-2% 规则）：
  effective_max_pct = min(max_pct, risk_per_trade / (sl_pct × leverage))
  确保单笔最大亏损 ≤ risk_per_trade（默认 2%）
"""

from __future__ import annotations

from typing import Optional


class KellySizer:
    """Kelly 仓位计算器。"""

    def __init__(
        self,
        kelly_fraction: float = 0.5,
        min_pct: float = 0.03,
        max_pct: float = 0.25,
        default_pct: float = 0.10,
        cold_start_min_trades: int = 5,
        risk_per_trade: float = 0.02,
    ):
        self._kelly_fraction = kelly_fraction  # Half-Kelly 系数
        self._min_pct = min_pct
        self._max_pct = max_pct
        self._default_pct = default_pct
        self._cold_start_min = cold_start_min_trades
        self._risk_per_trade = risk_per_trade  # 单笔最大风险占账户比例（2%规则）

    @staticmethod
    def kelly_fraction_fn(win_rate: float, w_l_ratio: float) -> float:
        """Kelly 最优仓位比例。

        f = W - (1-W)/R
        W = 胜率, R = 盈亏比

        Returns:
            f ∈ [0, 1]：Kelly 分数。负值表示不该下注，返回 0。
        """
        if w_l_ratio <= 0:
            return 0.0
        f = win_rate - (1.0 - win_rate) / w_l_ratio
        return max(0.0, f)

    def half_kelly(self, kelly_f: float) -> float:
        """Half-Kelly：风险减半。"""
        return kelly_f * self._kelly_fraction

    def kelly_to_position(
        self,
        half_f: float,
        n_trades: int,
        leverage: float = 1.0,
        sl_pct: float = 0.05,
    ) -> float:
        """Half-Kelly 分数 → position_pct。

        - 冷启动（n < cold_start_min_trades）→ DEFAULT_PCT
        - half_f <= 0 → 0（不开仓）
        - 否则 clamp 到 [MIN_PCT, effective_max_pct]
          effective_max_pct = min(max_pct, risk_per_trade / (sl_pct × leverage))
          确保单笔最大亏损 ≤ risk_per_trade（传统金融 2% 规则）
        """
        if n_trades < self._cold_start_min:
            return self._default_pct
        if half_f <= 0:
            return 0.0
        # 杠杆联动：有效仓位上限 = min(max_pct, risk_per_trade / (sl_pct × leverage))
        if leverage > 0 and sl_pct > 0:
            effective_max = min(self._max_pct, self._risk_per_trade / (sl_pct * leverage))
        else:
            effective_max = self._max_pct
        return min(max(half_f, self._min_pct), effective_max)

    def get_kelly_mult(self, half_f: float) -> float:
        """Half-Kelly → 乘数（供 BDSM 预算动态调整用）。

        映射：half_f ∈ [0, 1] → mult ∈ [0, 2.0]
        """
        return min(2.0, max(0.0, half_f * 2.0))
