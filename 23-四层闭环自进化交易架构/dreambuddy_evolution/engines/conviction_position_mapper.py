"""
ConvictionPositionMapper — 置信度→仓位/策略映射 (SPEC §4.6.2)

5档参数化映射:
  0.0-0.30  wait          position_scale=0.0  (观望)
  0.30-0.50 range         position_scale=0.3  sl_mult=1.5  (震荡市快进快出)
  0.50-0.70 trend_emerge  position_scale=0.7  (趋势初现)
  0.70-0.85 trend_set     position_scale=1.2  addon=True  (趋势确立+加仓+移动止损)
  0.85-1.0  strong_trend  position_scale=1.5  (强趋势重仓)

FOMC阶段基线置信度 (SPEC §4.6.3):
  expectation_build=0.30 / rise=0.55 / jump=0.75 / digest=0.60 / event=0.40 / repricing=0.50

HC: 开关关断时返回 position_scale=1.0 中性默认
HC: FAIL-OPEN 异常返回中性默认
"""
from __future__ import annotations

import logging
from typing import Any

from dreambuddy_evolution.agi_config import is_enabled

logger = logging.getLogger(__name__)


# SPEC §4.6.2: 5档置信度→仓位映射表
POSITION_TIERS: list[dict[str, Any]] = [
    {
        "range": (0.0, 0.30),
        "tier": "wait",
        "position_scale": 0.0,
        "sl_mult": 1.0,
        "tp_mult": 1.0,
        "trailing_stop": False,
        "addon": False,
        "max_hold": 0,
    },
    {
        "range": (0.30, 0.50),
        "tier": "range",
        "position_scale": 0.3,
        "sl_mult": 1.5,
        "tp_mult": 0.8,
        "trailing_stop": False,
        "addon": False,
        "max_hold": 24,
    },
    {
        "range": (0.50, 0.70),
        "tier": "trend_emerge",
        "position_scale": 0.7,
        "sl_mult": 1.2,
        "tp_mult": 1.0,
        "trailing_stop": True,
        "addon": False,
        "max_hold": 48,
    },
    {
        "range": (0.70, 0.85),
        "tier": "trend_set",
        "position_scale": 1.2,
        "sl_mult": 1.0,
        "tp_mult": 1.2,
        "trailing_stop": True,
        "addon": True,
        "max_hold": 72,
    },
    {
        "range": (0.85, 1.0),
        "tier": "strong_trend",
        "position_scale": 1.5,
        "sl_mult": 1.0,
        "tp_mult": 1.5,
        "trailing_stop": True,
        "addon": True,
        "max_hold": 96,
    },
]

# SPEC §4.6.3: FOMC阶段置信度基线
FOMC_PHASE_CONFIDENCE_BASELINE: dict[str, float] = {
    "expectation_build": 0.30,
    "expectation_rise": 0.55,
    "expectation_jump": 0.75,
    "expectation_digest": 0.60,
    "event": 0.40,
    "repricing": 0.50,
}


# 中性默认（开关关断/FAIL-OPEN时返回）
_NEUTRAL_RESULT = {
    "tier": "neutral",
    "position_scale": 1.0,
    "sl_mult": 1.0,
    "tp_mult": 1.0,
    "trailing_stop": False,
    "addon": False,
    "max_hold": 48,
}


class ConvictionPositionMapper:
    """置信度→仓位/策略映射器 (SPEC §4.6.2)。"""

    def map(self, conviction: float | None, fomc_phase: str | None = None) -> dict[str, Any]:
        """
        将置信度映射到仓位参数。

        Args:
            conviction: 置信度 0.0-1.0
            fomc_phase: FOMC 周期阶段（可选，用于基线提升）

        Returns:
            dict: {tier, position_scale, sl_mult, tp_mult, trailing_stop, addon, max_hold}
        """
        # HC: 开关关断时返回中性默认
        if not is_enabled("enable_contradiction_driven_layer"):
            return dict(_NEUTRAL_RESULT)
        if not is_enabled("enable_conviction_position_mapper"):
            return dict(_NEUTRAL_RESULT)

        # HC: FAIL-OPEN
        try:
            if conviction is None:
                return dict(_NEUTRAL_RESULT)
            conv = float(conviction)
            conv = max(0.0, min(1.0, conv))

            # FOMC 阶段基线提升
            if fomc_phase and fomc_phase in FOMC_PHASE_CONFIDENCE_BASELINE:
                baseline = FOMC_PHASE_CONFIDENCE_BASELINE[fomc_phase]
                conv = max(conv, baseline)

            # 查找对应档位
            for tier_def in POSITION_TIERS:
                low, high = tier_def["range"]
                if low <= conv < high or (high == 1.0 and conv == 1.0):
                    return {
                        "tier": tier_def["tier"],
                        "position_scale": tier_def["position_scale"],
                        "sl_mult": tier_def["sl_mult"],
                        "tp_mult": tier_def["tp_mult"],
                        "trailing_stop": tier_def["trailing_stop"],
                        "addon": tier_def["addon"],
                        "max_hold": tier_def["max_hold"],
                    }

            # 兜底：conviction >= 1.0
            last_tier = POSITION_TIERS[-1]
            return {
                "tier": last_tier["tier"],
                "position_scale": last_tier["position_scale"],
                "sl_mult": last_tier["sl_mult"],
                "tp_mult": last_tier["tp_mult"],
                "trailing_stop": last_tier["trailing_stop"],
                "addon": last_tier["addon"],
                "max_hold": last_tier["max_hold"],
            }
        except Exception as e:
            logger.warning("ConvictionPositionMapper FAIL-OPEN: %s", e, exc_info=False)
            return dict(_NEUTRAL_RESULT)
