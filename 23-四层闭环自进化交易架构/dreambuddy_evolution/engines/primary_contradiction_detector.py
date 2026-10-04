"""
PrimaryContradictionDetector — 主要矛盾识别器 (T10d)

SPEC §4.5.1: 事件驱动系统的核心创新 — 识别当前事件驱动阶段的主要矛盾类型、强度、周期阶段

4 种主要矛盾:
  fomc_rate_decision  — FOMC 利率决议主导（加息/降息预期）
  inflation_shock     — 通胀超预期/不及预期冲击
  credit_event        — 信贷收缩/扩张事件
  ai_capex_cycle      — AI 资本开支周期（半导体景气度）

intensity 公式 (SPEC §4.5.1):
  intensity = min(fomc_prob * 0.6 + abs(prob_trend_value) * 0.4, 0.95)
  prob_trend_value: rising=+0.3, falling=-0.3, stable=0.0

HC: 模块化开关 enable_primary_contradiction_detector 关断时返回中性默认
HC: 异常必须 FAIL-OPEN，返回 unknown + intensity=0.0
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from dreambuddy_evolution.agi_config import is_enabled

logger = logging.getLogger(__name__)


# probability_trend → 数值映射（用于 intensity 计算）
_PROB_TREND_VALUE = {
    "rising": 0.3,
    "falling": -0.3,
    "stable": 0.0,
}

# 各矛盾类型默认影响的资产
_AFFECTED_ASSETS = {
    "fomc_rate_decision": ["gold", "btc", "us10y", "dxy"],
    "inflation_shock": ["gold", "btc", "us10y"],
    "credit_event": ["btc", "gold", "us10y"],
    "ai_capex_cycle": ["semiconductors", "btc", "gold"],
    "unknown": [],
}


@dataclass
class ContradictionInfo:
    """主要矛盾识别结果。"""

    primary: str = "unknown"  # fomc_rate_decision / inflation_shock / credit_event / ai_capex_cycle / unknown
    intensity: float = 0.0  # 0.0-0.95
    cycle_phase: str = "neutral"  # expectation_build/rise/jump/digest/event/repricing/neutral
    probability: float | None = None  # FedWatch 加息概率
    probability_trend: str = "stable"  # rising / falling / stable
    affected_assets: list[str] = field(default_factory=list)
    secondary: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary,
            "intensity": self.intensity,
            "cycle_phase": self.cycle_phase,
            "probability": self.probability,
            "probability_trend": self.probability_trend,
            "affected_assets": list(self.affected_assets),
            "secondary": list(self.secondary),
        }


class PrimaryContradictionDetector:
    """主要矛盾识别器 (T10d, SPEC §4.5.1)。

    识别当前事件驱动阶段的主要矛盾类型，并输出强度、周期阶段、受影响资产。
    在 FOMC 周期内优先识别 fomc_rate_decision，否则识别通胀/信贷/AI 周期矛盾。
    """

    # CPI 超预期阈值（同比%差值）
    CPI_SURPRISE_THRESHOLD = 0.5

    # 信贷收缩阈值（同比%为负）
    CREDIT_CONTRACTION_THRESHOLD = 0.0

    # AI 周期评分阈值
    AI_CYCLE_HIGH_THRESHOLD = 0.7

    # T5 P0 盲区修复（SPEC §3.2.2）：
    # 非农/CPI/PPI 虽不在 FOMC 议息周期，但实质影响加息预期，CESI 触发激活
    CESI_TRIGGER_THRESHOLD = 1.5  # ±1.5σ 触发宏观利率矛盾
    MACRO_EVENT_TYPES = ("nfp", "cpi", "ppi")  # 强制激活的事件类型
    CESI_AMPLIFIER_DIVISOR = 3.0  # cesi_amplifier = min(|cesi|/3.0, 0.3)
    CESI_AMPLIFIER_CAP = 0.3  # CESI 放大上限

    def detect(self, kline_data: dict[str, Any] | None) -> ContradictionInfo:
        """
        识别当前主要矛盾。

        Args:
            kline_data: data_pipeline.assemble() 输出的完整 dict

        Returns:
            ContradictionInfo
        """
        # HC: 开关关断时返回中性默认（字节等价"模块不存在"）
        # 需要同时启用总开关 + 层开关 + 模块开关
        if not is_enabled("enable_contradiction_driven_layer"):
            return ContradictionInfo()
        if not is_enabled("enable_primary_contradiction_detector"):
            return ContradictionInfo()

        # HC: FAIL-OPEN — 数据异常时返回中性默认
        try:
            if not isinstance(kline_data, dict):
                return ContradictionInfo()
            return self._detect_safe(kline_data)
        except Exception as e:
            logger.warning(
                "PrimaryContradictionDetector FAIL-OPEN: %s", e, exc_info=False
            )
            return ContradictionInfo()

    def _detect_safe(self, kline_data: dict) -> ContradictionInfo:
        """安全路径：识别主要矛盾 + 次要矛盾。"""
        event_ctx = kline_data.get("event_context") or {}
        cycle_phase = event_ctx.get("cycle_phase", "neutral")
        hike_prob = event_ctx.get("hike_prob")
        prob_trend = event_ctx.get("probability_trend", "stable")

        # 优先级 1: FOMC 周期内 + 有加息概率 → fomc_rate_decision
        primary, intensity = self._classify_primary(
            kline_data, event_ctx, hike_prob, prob_trend
        )

        # 计算次要矛盾
        secondary = self._classify_secondary(kline_data, primary)

        info = ContradictionInfo(
            primary=primary,
            intensity=intensity,
            cycle_phase=cycle_phase,
            probability=hike_prob if isinstance(hike_prob, (int, float)) else None,
            probability_trend=prob_trend,
            affected_assets=list(_AFFECTED_ASSETS.get(primary, [])),
            secondary=secondary,
        )
        return info

    def _classify_primary(
        self,
        kline_data: dict,
        event_ctx: dict,
        hike_prob: float | None,
        prob_trend: str,
    ) -> tuple[str, float]:
        """判定主要矛盾类型 + 强度。"""
        in_fomc = event_ctx.get("in_fomc_cycle", False)
        # T5 P0 盲区修复（SPEC §3.2.2）：
        # 解除 in_fomc 硬限制 — 非农/CPI/PPI 虽不在 FOMC 议息周期，
        # 但实质影响加息预期，CESI 触发同样识别为 fomc_rate_decision。
        cesi = kline_data.get("cesi")
        event_type = event_ctx.get("event_type", "")

        # 优先级 1: FOMC 周期 OR CESI 触发的加息预期变化
        macro_rate_triggered = (
            in_fomc
            or (
                cesi is not None
                and abs(cesi) >= self.CESI_TRIGGER_THRESHOLD
                and event_type in self.MACRO_EVENT_TYPES
            )
        )

        if macro_rate_triggered and hike_prob is not None:
            p = float(hike_prob)
            trend_val = _PROB_TREND_VALUE.get(prob_trend, 0.0)
            # CESI 放大 intensity：|cesi| 越大，矛盾强度越高
            if cesi is not None:
                cesi_amplifier = min(
                    abs(float(cesi)) / self.CESI_AMPLIFIER_DIVISOR,
                    self.CESI_AMPLIFIER_CAP,
                )
            else:
                cesi_amplifier = 0.0
            # intensity = min(p*0.6 + abs(trend_val)*0.4 + cesi_amplifier, 0.95)
            intensity = min(
                p * 0.6 + abs(trend_val) * 0.4 + cesi_amplifier, 0.95
            )
            return "fomc_rate_decision", round(intensity, 3)

        # 优先级 2: 通胀冲击
        cpi_actual = kline_data.get("cpi_actual")
        cpi_expected = kline_data.get("cpi_expected")
        if cpi_actual is not None and cpi_expected is not None:
            try:
                surprise = float(cpi_actual) - float(cpi_expected)
                if abs(surprise) >= self.CPI_SURPRISE_THRESHOLD:
                    # CPI 超预期幅度映射到 0.3-0.9
                    intensity = min(0.3 + abs(surprise) * 0.15, 0.9)
                    return "inflation_shock", round(intensity, 3)
            except (TypeError, ValueError):
                pass

        # 优先级 3: 信贷事件
        credit_growth = kline_data.get("credit_growth")
        gdp_growth = kline_data.get("gdp_growth")
        if credit_growth is not None:
            try:
                cg = float(credit_growth)
                if cg < self.CREDIT_CONTRACTION_THRESHOLD:
                    # 信贷收缩强度
                    intensity = min(0.3 + abs(cg) * 0.1, 0.85)
                    return "credit_event", round(intensity, 3)
            except (TypeError, ValueError):
                pass

        # 优先级 4: AI 资本开支周期
        ai_cycle_score = kline_data.get("ai_cycle_score")
        if ai_cycle_score is not None:
            try:
                ai_score = float(ai_cycle_score)
                if ai_score >= self.AI_CYCLE_HIGH_THRESHOLD:
                    return "ai_capex_cycle", round(ai_score * 0.85, 3)
            except (TypeError, ValueError):
                pass

        # 无主要矛盾
        return "unknown", 0.0

    def _classify_secondary(self, kline_data: dict, primary: str) -> list[str]:
        """识别次要矛盾（除主要矛盾外的其他显著矛盾）。"""
        secondary: list[str] = []

        # 检查通胀
        if primary != "inflation_shock":
            cpi_actual = kline_data.get("cpi_actual")
            cpi_expected = kline_data.get("cpi_expected")
            if cpi_actual is not None and cpi_expected is not None:
                try:
                    if abs(float(cpi_actual) - float(cpi_expected)) >= self.CPI_SURPRISE_THRESHOLD:
                        secondary.append("inflation_shock")
                except (TypeError, ValueError):
                    pass

        # 检查信贷
        if primary != "credit_event":
            credit_growth = kline_data.get("credit_growth")
            if credit_growth is not None:
                try:
                    if float(credit_growth) < self.CREDIT_CONTRACTION_THRESHOLD:
                        secondary.append("credit_event")
                except (TypeError, ValueError):
                    pass

        # 检查 AI 周期
        if primary != "ai_capex_cycle":
            ai_cycle_score = kline_data.get("ai_cycle_score")
            if ai_cycle_score is not None:
                try:
                    if float(ai_cycle_score) >= self.AI_CYCLE_HIGH_THRESHOLD:
                        secondary.append("ai_capex_cycle")
                except (TypeError, ValueError):
                    pass

        return secondary
