"""
DebtCyclePhase — Dalio 短期债务周期判定 (T13b)

SPEC §4.4: 基于信贷增速 vs GDP增速判定债务周期阶段

判定规则:
  信贷增速 > GDP增速 → expansion（扩张期）
  信贷增速 < GDP增速 + 利率上行(tightening) → contraction（收缩期）
  信贷增速 < GDP增速 + 利率下行/中性 → neutral
  无数据 → neutral

数据来源:
  credit_growth: 信贷增速同比%（FredCollector NONREVSL）
  gdp_growth: GDP增速同比%（FredCollector GDP）
  monetary_cycle: 货币周期 easing/tightening/neutral

HC: 开关关断时返回 "neutral"
HC: FAIL-OPEN 异常返回 "neutral"
"""
from __future__ import annotations

import logging
from typing import Any

from dreambuddy_evolution.agi_config import is_enabled

logger = logging.getLogger(__name__)


class DebtCyclePhase:
    """Dalio 短期债务周期判定器 (T13b, SPEC §4.4)。"""

    def phase(self, kline_data: dict[str, Any] | None) -> str:
        """
        判定当前债务周期阶段。

        Args:
            kline_data: 含 credit_growth / gdp_growth / monetary_cycle 的 dict

        Returns:
            "expansion" / "contraction" / "neutral"
        """
        if not is_enabled("enable_contradiction_driven_layer"):
            return "neutral"
        if not is_enabled("enable_debt_cycle_phase"):
            return "neutral"

        try:
            if not isinstance(kline_data, dict):
                return "neutral"
            return self._classify(kline_data)
        except Exception as e:
            logger.warning("DebtCyclePhase FAIL-OPEN: %s", e, exc_info=False)
            return "neutral"

    def phase_with_context(self, kline_data: dict[str, Any] | None) -> dict[str, Any]:
        """
        判定债务周期阶段 + 输出上下文详情。

        Returns:
            dict: {phase, credit_growth, gdp_growth, monetary_cycle, reason}
        """
        if not is_enabled("enable_contradiction_driven_layer") or not is_enabled("enable_debt_cycle_phase"):
            return {"phase": "neutral", "reason": "开关关断"}

        try:
            if not isinstance(kline_data, dict):
                return {"phase": "neutral", "reason": "无数据"}

            credit_growth = kline_data.get("credit_growth")
            gdp_growth = kline_data.get("gdp_growth")
            monetary_cycle = kline_data.get("monetary_cycle", "neutral")

            if credit_growth is None or gdp_growth is None:
                return {
                    "phase": "neutral",
                    "credit_growth": credit_growth,
                    "gdp_growth": gdp_growth,
                    "monetary_cycle": monetary_cycle,
                    "reason": "数据不足",
                }

            phase = self._classify(kline_data)
            return {
                "phase": phase,
                "credit_growth": credit_growth,
                "gdp_growth": gdp_growth,
                "monetary_cycle": monetary_cycle,
                "reason": self._reason(phase, credit_growth, gdp_growth, monetary_cycle),
            }
        except Exception as e:
            logger.warning("DebtCyclePhase FAIL-OPEN: %s", e, exc_info=False)
            return {"phase": "neutral", "reason": f"异常: {e}"}

    def _classify(self, kline_data: dict) -> str:
        """分类逻辑。"""
        credit_growth = kline_data.get("credit_growth")
        gdp_growth = kline_data.get("gdp_growth")
        monetary_cycle = kline_data.get("monetary_cycle", "neutral")

        if credit_growth is None or gdp_growth is None:
            return "neutral"

        try:
            cg = float(credit_growth)
            gg = float(gdp_growth)
        except (TypeError, ValueError):
            return "neutral"

        if cg > gg:
            return "expansion"
        elif cg < gg and monetary_cycle == "tightening":
            return "contraction"
        else:
            return "neutral"

    def _reason(self, phase: str, cg: Any, gg: Any, mc: str) -> str:
        if phase == "expansion":
            return f"信贷增速 {cg} > GDP增速 {gg} → 扩张期"
        elif phase == "contraction":
            return f"信贷增速 {cg} < GDP增速 {gg} + 利率上行 → 收缩期"
        else:
            return f"信贷增速 {cg} vs GDP增速 {gg} + {mc} → 中性"
