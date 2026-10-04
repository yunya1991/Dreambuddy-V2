"""
AiCycleScorer — AI 资本开支周期评分 (T13c)

SPEC §0.5.2: HBM 需求 / 资本开支 / 半导体景气度 → 0.0-1.0

3 因子加权:
  1. sox_change_30d         (40%): SOX 指数 30 天涨幅（半导体景气度代理）
  2. semiconductor_capex_yoy (35%): 半导体资本开支同比%（AI capex 周期）
  3. hbm_demand_index       (25%): HBM 需求指数 0.0-1.0

归一化:
  sox_change_30d: 使用 tanh(change/10) 映射到 0-1
  capex_yoy: 使用 tanh(yoy/15) 映射到 0-1
  hbm: 直接使用 0-1

>0.7 → 半导体不做空（AI 周期对冲利率压力）

HC: 开关关断时返回 0.5（中性）
HC: FAIL-OPEN 异常返回 0.5
"""
from __future__ import annotations

import logging
import math
from typing import Any

from dreambuddy_evolution.agi_config import is_enabled

logger = logging.getLogger(__name__)


class AiCycleScorer:
    """AI 资本开支周期评分器 (T13c, SPEC §0.5.2)。"""

    W_SOX = 0.40
    W_CAPEX = 0.35
    W_HBM = 0.25

    def score(self, kline_data: dict[str, Any] | None) -> float:
        """
        计算 AI 周期评分。

        Args:
            kline_data: 含 sox_change_30d / semiconductor_capex_yoy / hbm_demand_index 的 dict

        Returns:
            0.0-1.0 评分
        """
        if not is_enabled("enable_contradiction_driven_layer"):
            return 0.5
        if not is_enabled("enable_ai_cycle_scorer"):
            return 0.5

        try:
            if not isinstance(kline_data, dict):
                return 0.5

            sox = self._norm_sox(kline_data.get("sox_change_30d"))
            capex = self._norm_capex(kline_data.get("semiconductor_capex_yoy"))
            hbm = self._norm_hbm(kline_data.get("hbm_demand_index"))

            # 如果所有因子都无数据 → 中性
            if sox is None and capex is None and hbm is None:
                return 0.5

            # 加权平均（跳过 None 因子，重新归一化权重）
            scores = []
            weights = []
            if sox is not None:
                scores.append(sox * self.W_SOX)
                weights.append(self.W_SOX)
            if capex is not None:
                scores.append(capex * self.W_CAPEX)
                weights.append(self.W_CAPEX)
            if hbm is not None:
                scores.append(hbm * self.W_HBM)
                weights.append(self.W_HBM)

            if not weights:
                return 0.5

            total = sum(scores) / sum(weights)
            return round(max(0.0, min(1.0, total)), 3)
        except Exception as e:
            logger.warning("AiCycleScorer FAIL-OPEN: %s", e, exc_info=False)
            return 0.5

    def _norm_sox(self, sox_change: Any) -> float | None:
        """SOX 30天涨幅归一化: tanh(change/10) 映射到 0-1"""
        if sox_change is None:
            return None
        try:
            return (math.tanh(float(sox_change) / 10.0) + 1.0) / 2.0
        except (TypeError, ValueError):
            return None

    def _norm_capex(self, capex_yoy: Any) -> float | None:
        """资本开支同比归一化: tanh(yoy/15) 映射到 0-1"""
        if capex_yoy is None:
            return None
        try:
            return (math.tanh(float(capex_yoy) / 15.0) + 1.0) / 2.0
        except (TypeError, ValueError):
            return None

    def _norm_hbm(self, hbm_index: Any) -> float | None:
        """HBM 需求指数归一化: 直接 0-1"""
        if hbm_index is None:
            return None
        try:
            return max(0.0, min(1.0, float(hbm_index)))
        except (TypeError, ValueError):
            return None
