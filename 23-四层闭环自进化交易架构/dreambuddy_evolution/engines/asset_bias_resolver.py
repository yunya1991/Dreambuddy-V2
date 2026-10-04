"""
AssetBiasResolver — 资产分化方向偏置 (T10f)

SPEC §4.5.3: 不同资产在 FOMC 周期内的差异化方向偏置

资产分化规则:
  gold:
    - hike + pre_event → short_bias (加息前金价承压，实际利率上行)
    - cut → long_bias (降息利好黄金，实际利率下行)
    - hold → neutral
  btc:
    - 30天相关性 < 0.3 → neutral (BTC 独立走势，不走宏观逻辑)
    - hike + corr < 0 + pre_event → short_bias (加息+负相关+预期阶段)
    - cut → long_bias
  semiconductors:
    - AI周期 > 0.7 → neutral (AI 对冲利率压力)
    - hike (无AI对冲) → short_bias
    - cut → long_bias

HC: 开关关断时返回 {"bias": "neutral", "confidence": 0.0}
HC: FAIL-OPEN 异常返回 neutral
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from dreambuddy_evolution.agi_config import is_enabled

logger = logging.getLogger(__name__)


# FOMC 预期阶段集合
_PRE_EVENT_PHASES = {
    "expectation_build", "expectation_rise",
    "expectation_jump", "expectation_digest",
}

# BTC 相关性中性阈值
_BTC_CORR_NEUTRAL_THRESHOLD = 0.3

# AI 周期对冲阈值
_AI_CYCLE_HEDGE_THRESHOLD = 0.7


@dataclass
class AssetBias:
    """资产方向偏置结果。"""

    bias: str = "neutral"  # "long" / "short" / "neutral"
    confidence: float = 0.0  # 0.0-1.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "bias": self.bias,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class AssetBiasResolver:
    """资产分化方向偏置器 (T10f, SPEC §4.5.3)。

    根据资产类型、FOMC 阶段、利率预期输出方向偏置。
    """

    def get_asset_bias(
        self,
        asset: str | None,
        fomc_phase: str | None,
        rate_expectation: str | None,
        corr_30d: float | None = None,
        ai_cycle_score: float | None = None,
    ) -> AssetBias:
        """
        计算资产方向偏置。

        Args:
            asset: 资产类型 ("gold" / "btc" / "semiconductors")
            fomc_phase: FOMC 周期阶段
            rate_expectation: 利率预期 ("hike" / "cut" / "hold")
            corr_30d: BTC 30天相关性（仅 btc 用）
            ai_cycle_score: AI 周期评分（仅 semiconductors 用）

        Returns:
            AssetBias
        """
        # HC: 开关关断时返回中性
        if not is_enabled("enable_contradiction_driven_layer"):
            return AssetBias()
        if not is_enabled("enable_asset_bias_resolver"):
            return AssetBias()

        # HC: FAIL-OPEN
        try:
            if not isinstance(asset, str) or not isinstance(fomc_phase, str):
                return AssetBias()
            if not isinstance(rate_expectation, str):
                return AssetBias()

            if asset == "gold":
                return self._gold_bias(fomc_phase, rate_expectation)
            elif asset == "btc":
                return self._btc_bias(fomc_phase, rate_expectation, corr_30d)
            elif asset == "semiconductors":
                return self._semiconductors_bias(fomc_phase, rate_expectation, ai_cycle_score)
            else:
                return AssetBias(reason="未知资产")
        except Exception as e:
            logger.warning("AssetBiasResolver FAIL-OPEN: %s", e, exc_info=False)
            return AssetBias()

    def _gold_bias(self, fomc_phase: str, rate_expectation: str) -> AssetBias:
        """黄金方向偏置。"""
        is_pre_event = fomc_phase in _PRE_EVENT_PHASES

        if rate_expectation == "hike" and is_pre_event:
            return AssetBias(
                bias="short",
                confidence=0.75,
                reason="加息预期+Pre-event → 实际利率上行 → 金价承压",
            )
        elif rate_expectation == "cut":
            return AssetBias(
                bias="long",
                confidence=0.70,
                reason="降息 → 实际利率下行 → 利好黄金",
            )
        else:
            return AssetBias(bias="neutral", confidence=0.3, reason="hold或post_event，无明确偏置")

    def _btc_bias(
        self,
        fomc_phase: str,
        rate_expectation: str,
        corr_30d: float | None,
    ) -> AssetBias:
        """BTC 方向偏置。"""
        # 低相关性 → BTC 走独立逻辑，不受宏观主导
        if corr_30d is not None:
            try:
                if abs(float(corr_30d)) < _BTC_CORR_NEUTRAL_THRESHOLD:
                    return AssetBias(
                        bias="neutral",
                        confidence=0.4,
                        reason=f"30天相关性 {corr_30d:.2f} < 0.3 → BTC 独立走势",
                    )
            except (TypeError, ValueError):
                pass

        is_pre_event = fomc_phase in _PRE_EVENT_PHASES

        if rate_expectation == "hike" and is_pre_event:
            # 检查负相关性
            if corr_30d is not None:
                try:
                    if float(corr_30d) < 0:
                        return AssetBias(
                            bias="short",
                            confidence=0.65,
                            reason="加息+负相关+Pre-event → BTC 承压",
                        )
                except (TypeError, ValueError):
                    pass
            return AssetBias(
                bias="neutral",
                confidence=0.3,
                reason="加息但相关性不明确，观望",
            )
        elif rate_expectation == "cut":
            return AssetBias(
                bias="long",
                confidence=0.60,
                reason="降息 → 流动性宽松 → 利好 BTC",
            )
        else:
            return AssetBias(bias="neutral", confidence=0.3, reason="hold，无明确偏置")

    def _semiconductors_bias(
        self,
        fomc_phase: str,
        rate_expectation: str,
        ai_cycle_score: float | None,
    ) -> AssetBias:
        """半导体方向偏置。"""
        # AI 周期高景气 → 对冲利率压力
        if ai_cycle_score is not None:
            try:
                if float(ai_cycle_score) >= _AI_CYCLE_HEDGE_THRESHOLD:
                    return AssetBias(
                        bias="neutral",
                        confidence=0.5,
                        reason=f"AI周期 {ai_cycle_score:.2f} > 0.7 → 对冲利率压力",
                    )
            except (TypeError, ValueError):
                pass

        if rate_expectation == "hike":
            return AssetBias(
                bias="short",
                confidence=0.65,
                reason="加息无AI对冲 → 半导体承压",
            )
        elif rate_expectation == "cut":
            return AssetBias(
                bias="long",
                confidence=0.60,
                reason="降息 → 利好半导体",
            )
        else:
            return AssetBias(bias="neutral", confidence=0.3, reason="hold，无明确偏置")
