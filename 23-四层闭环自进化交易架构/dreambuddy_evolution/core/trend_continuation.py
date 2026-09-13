"""
Phase 3.2: TrendContinuationScorer — 趋势延续性评分器
SPEC-主要矛盾识别与最小阻力路径设计.md §4.4

理论来源:
  - Minervini SEPA: 8 条件趋势模板 (Stage 2 确认) + VCP 波动率收缩
  - Wyckoff: Cause & Effect (累积期→行情规模) + Effort vs Result (量价背离)

用于 _discover_paths 为每个路径注入:
  - continuation_score: Minervini 趋势模板 × VCP
  - cause_score: Wyckoff 累积期标准化时长
  - effort_result: Wyckoff 量价背离检测

HC-AGI-20: 趋势延续性字段缺失时取 0.5 中性兜底
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TrendContinuationScorer:
    """趋势延续性评分器 (Minervini SEPA + Wyckoff).

    核心量化规则:
      - 趋势模板 8 条件: price > ma150/ma200, ma150 > ma200, ma200 上升,
        ma50 > ma150/ma200, price > ma50, 52周区间
      - VCP: T2/T1 ≤ 0.75, T3/T2 ≤ 0.75 → 1.0
      - Cause: (consolidation_bars - 10) / 50, 20-60 bars → 0.2-1.0
      - Effort/Result: 量价同向 → 0.8, 背离 → 0.3
    """

    # HC-AGI-20: 趋势延续性字段全部缺失时 continuation 取 0.5 中性兜底
    TREND_FIELDS = (
        "price", "ma50", "ma150", "ma200", "ma200_slope",
        "low_52w", "high_52w", "contractions",
    )

    def score(self, market_data: dict | Any, direction: str) -> dict:
        """计算趋势延续性评分.

        Returns:
            {
                "continuation_score": float,  # Minervini 模板 × VCP
                "cause_score": float,         # Wyckoff 因果
                "effort_result": float,       # Wyckoff 量价
            }

        HC-AGI-20: 趋势字段全部缺失时 continuation_score 取 0.5 中性兜底；
                   cause/effort 仍按各自字段独立计算（缺失时各自 0.5）。
        """
        try:
            if not isinstance(market_data, dict):
                return self._neutral_default()

            kline = market_data.get("kline_data", {})
            if not isinstance(kline, dict):
                return self._neutral_default()

            # HC-AGI-20: 趋势延续性字段全部缺失 → continuation 取中性 0.5
            if any(f in kline for f in self.TREND_FIELDS):
                continuation = self._minervini_score(kline, direction)
            else:
                continuation = 0.5

            return {
                "continuation_score": continuation,
                "cause_score": self._wyckoff_cause(kline),
                "effort_result": self._wyckoff_effort_result(kline),
            }
        except Exception as e:  # noqa: BLE001  HC-AGI-20
            logger.debug("[FO-AGI][TrendContinuation] FAIL-OPEN: %s", e)
            return self._neutral_default()

    # ------------------------------------------------------------------
    # Minervini SEPA: 趋势模板 + VCP
    # ------------------------------------------------------------------
    def _minervini_score(self, kline: dict, direction: str) -> float:
        """8 条件趋势模板 (Stage 2 确认) + VCP 收缩比.

        权重: 模板 60% + VCP 40%
        """
        template_score = self._trend_template_score(kline)
        vcp_score = self._vcp_contraction(kline)
        return float(template_score * 0.6 + vcp_score * 0.4)

    def _trend_template_score(self, kline: dict) -> float:
        """Minervini 8 条件趋势模板.

        Stage 2 确认:
          1. price > ma150
          2. price > ma200
          3. ma150 > ma200
          4. ma200 上升 ≥ 22 天 (简化为 slope > 0)
          5. ma50 > ma150 AND ma50 > ma200
          6. price > ma50
          7. price ≥ 52周最低 × 1.25
          8. price ≤ 52周最高 × 1.25
        """
        try:
            price = float(kline.get("price", 0))
            ma50 = float(kline.get("ma50", 0))
            ma150 = float(kline.get("ma150", 0))
            ma200 = float(kline.get("ma200", 0))
            ma200_slope = float(kline.get("ma200_slope", 0))
            low_52w = float(kline.get("low_52w", 0))
            high_52w = float(kline.get("high_52w", 0))

            passed = 0
            if price > 0 and ma150 > 0 and price > ma150:
                passed += 1
            if price > 0 and ma200 > 0 and price > ma200:
                passed += 1
            if ma150 > 0 and ma200 > 0 and ma150 > ma200:
                passed += 1
            if ma200_slope > 0:
                passed += 1
            if ma50 > 0 and ma150 > 0 and ma50 > ma150:
                passed += 1
            if price > 0 and ma50 > 0 and price > ma50:
                passed += 1
            if low_52w > 0 and price >= low_52w * 1.25:
                passed += 1
            if high_52w > 0 and price <= high_52w * 1.25:
                passed += 1

            return float(passed / 8.0)
        except (TypeError, ValueError):
            return 0.5

    def _vcp_contraction(self, kline: dict) -> float:
        """VCP: T2/T1 ≤ 0.75, T3/T2 ≤ 0.75 → 1.0.

        收缩递减规则:
          - ratio = T(i) / T(i-1)
          - ratio ≤ 0.75 → 1.0 (有效收缩)
          - ratio > 0.75 → 线性衰减
          - ratio > 1.75 → 0.0
        """
        contractions = kline.get("contractions", [])
        if not isinstance(contractions, (list, tuple)) or len(contractions) < 2:
            return 0.5  # HC-AGI-20: 数据不足, 中性

        try:
            ratios = []
            for i in range(1, len(contractions)):
                prev = float(contractions[i - 1])
                curr = float(contractions[i])
                if prev > 0:
                    r = curr / prev
                    if r <= 0.75:
                        ratios.append(1.0)
                    else:
                        # 线性衰减: 0.75 → 1.0, 1.75 → 0.0
                        ratios.append(max(0.0, 1.0 - (r - 0.75)))
            return float(sum(ratios) / len(ratios)) if ratios else 0.5
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.5

    # ------------------------------------------------------------------
    # Wyckoff 指标
    # ------------------------------------------------------------------
    def _wyckoff_cause(self, kline: dict) -> float:
        """Cause & Effect: 累积期标准化时长 → 后续行情规模.

        标准化: (consolidation_bars - 10) / 50
          - < 10 bars → 0.0 (累积不足)
          - 10-60 bars → 0.0-1.0 (线性)
          - ≥ 60 bars → 1.0 (充分累积)
        """
        try:
            consolidation_bars = float(kline.get("consolidation_bars", 0))
            return float(min(1.0, max(0.0, (consolidation_bars - 10) / 50)))
        except (TypeError, ValueError):
            return 0.5

    def _wyckoff_effort_result(self, kline: dict) -> float:
        """Effort vs Result: 量价背离检测.

        量价同向 → 0.8 (机构行为一致, 趋势健康)
        量价背离 → 0.3 (机构吸筹/派发, 警惕)
        无价格变动 → 0.5 (中性)
        """
        try:
            vol_change = float(kline.get("volume_change_pct", 0))
            price_change = float(kline.get("price_change_pct", 0))
            if abs(price_change) < 1e-9:
                return 0.5
            if (vol_change > 0) == (price_change > 0):
                return 0.8
            return 0.3
        except (TypeError, ValueError):
            return 0.5

    # ------------------------------------------------------------------
    # FAIL-OPEN 兜底
    # ------------------------------------------------------------------
    def _neutral_default(self) -> dict:
        """HC-AGI-20: 中性兜底."""
        return {
            "continuation_score": 0.5,
            "cause_score": 0.5,
            "effort_result": 0.5,
        }
