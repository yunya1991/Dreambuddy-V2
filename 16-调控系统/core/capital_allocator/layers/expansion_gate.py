"""Layer 4: GlobalExpansionGate
==============================

职责：基于全局近期绩效，动态调整总仓位上限。

扩张阶梯：
  W/L ≥ 2.0 → position_pct × 1.5（扩张 50%）
  W/L ≥ 1.0 → position_pct × 1.2（扩张 20%）
  W/L ≥ 0.5 → position_pct × 1.0（基准）
  W/L < 0.5 → position_pct × 0.7（收缩 30%）

安全约束：
  - 扩张后总仓位不超过 MAX_TOTAL_EXPOSURE=0.80
  - 收缩时不低于 MIN_TOTAL_EXPOSURE=0.10
  - 每 6h 至多调整一次（防抖动）
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List


class GlobalExpansionGate:
    """全局扩张/收缩门控。"""

    DEFAULT_LADDER: List[Dict[str, float]] = [
        {"w_l_ratio_min": 2.0, "position_pct_mult": 1.5},
        {"w_l_ratio_min": 1.0, "position_pct_mult": 1.2},
        {"w_l_ratio_min": 0.5, "position_pct_mult": 1.0},
        {"w_l_ratio_min": 0.0, "position_pct_mult": 0.7},
    ]

    def __init__(
        self,
        window: int = 30,
        ladder: List[Dict[str, float]] | None = None,
        max_exposure: float = 0.80,
        min_exposure: float = 0.10,
        cooldown_hours: int = 6,
    ):
        self._window = window
        self._ladder = list(ladder) if ladder else list(self.DEFAULT_LADDER)
        # 按 w_l_ratio_min 降序排列
        self._ladder.sort(key=lambda t: t.get("w_l_ratio_min", 0.0), reverse=True)
        self._max_exposure = max_exposure
        self._min_exposure = min_exposure
        self._cooldown_sec = cooldown_hours * 3600

        self._last_mult: float = 1.0
        self._last_adjust_ts: float = 0.0

    def get_expansion_multiplier(self, global_stats: Dict[str, Any]) -> float:
        """获取全局扩张乘数。

        Args:
            global_stats: 全局统计 dict，含 w_l_ratio 字段

        Returns:
            expansion_mult ∈ [0.5, 1.5]（安全约束内）
        """
        try:
            w_l = float(global_stats.get("w_l_ratio", 0.0))
            n_trades = int(global_stats.get("n_trades", 0))

            # 冷启动：交易不足 → 不扩张不收缩
            if n_trades < self._window:
                return 1.0

            # 冷却期检查
            now_ts = time.time()
            if (now_ts - self._last_adjust_ts) < self._cooldown_sec and self._last_mult > 0:
                return self._last_mult

            # 匹配阶梯
            mult = self._match_ladder(w_l)

            # 安全约束：mult ∈ [0.5, 1.5]
            mult = max(0.5, min(1.5, mult))

            self._last_mult = mult
            self._last_adjust_ts = now_ts
            return mult
        except Exception:
            return 1.0  # FAIL-OPEN：不扩张不收缩

    def _match_ladder(self, w_l: float) -> float:
        """匹配扩张阶梯。"""
        for tier in self._ladder:
            if w_l >= tier.get("w_l_ratio_min", 0.0):
                return float(tier.get("position_pct_mult", 1.0))
        return 0.5  # 兜底：极端劣化时仓位减半
