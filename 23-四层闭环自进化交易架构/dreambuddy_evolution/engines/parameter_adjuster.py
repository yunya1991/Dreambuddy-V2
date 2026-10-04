"""
ParameterAdjuster — 主要矛盾驱动的参数调整矩阵 (T10e)

SPEC §4.5.2: FOMC 主要矛盾驱动的 6 阶段×7 参数调整矩阵
  - 主要矛盾主导阶段 → 自动调整策略参数
  - expectation_jump 是最强窗口（高仓位、宽止损、技术权重低）
  - event 阶段保守（低仓位、紧止损、短持）

6 阶段:
  expectation_build / expectation_rise / expectation_jump
  expectation_digest / event / repricing

7 参数:
  conf_threshold     — 置信度门槛
  position_scale     — 仓位倍数
  sl_distance_mult   — 止损距离倍数
  tp_distance_mult   — 止盈距离倍数
  macro_weight       — 宏观因子权重
  tech_weight        — 技术因子权重
  max_hold_hours     — 最大持仓时长

HC: 开关关断时返回 base_params 不修改，字节等价"模块不存在"
HC: FAIL-OPEN 异常返回 base_params
"""
from __future__ import annotations

import logging
from typing import Any

from dreambuddy_evolution.agi_config import is_enabled

logger = logging.getLogger(__name__)


# SPEC §4.5.2: FOMC 阶段参数覆盖矩阵 (6阶段 × 7参数)
FOMC_PARAM_OVERRIDES: dict[str, dict[str, float]] = {
    "expectation_build": {
        "conf_threshold": 0.65,
        "position_scale": 0.5,
        "sl_distance_mult": 1.5,
        "tp_distance_mult": 1.5,
        "macro_weight": 0.20,
        "tech_weight": 0.55,
        "max_hold_hours": 72,
    },
    "expectation_rise": {
        "conf_threshold": 0.55,
        "position_scale": 1.0,
        "sl_distance_mult": 2.0,
        "tp_distance_mult": 2.0,
        "macro_weight": 0.25,
        "tech_weight": 0.50,
        "max_hold_hours": 48,
    },
    "expectation_jump": {
        # 最强窗口：高仓位 + 宽止损 + 宽止盈 + 宏观权重最高
        "conf_threshold": 0.50,
        "position_scale": 1.5,
        "sl_distance_mult": 2.0,
        "tp_distance_mult": 2.0,
        "macro_weight": 0.35,
        "tech_weight": 0.40,
        "max_hold_hours": 36,
    },
    "expectation_digest": {
        "conf_threshold": 0.60,
        "position_scale": 0.8,
        "sl_distance_mult": 1.5,
        "tp_distance_mult": 1.5,
        "macro_weight": 0.30,
        "tech_weight": 0.45,
        "max_hold_hours": 24,
    },
    "event": {
        # 事件当天保守：低仓位 + 紧止损 + 短持
        "conf_threshold": 0.70,
        "position_scale": 0.5,
        "sl_distance_mult": 1.0,
        "tp_distance_mult": 1.0,
        "macro_weight": 0.40,
        "tech_weight": 0.35,
        "max_hold_hours": 12,
    },
    "repricing": {
        "conf_threshold": 0.58,
        "position_scale": 1.0,
        "sl_distance_mult": 1.5,
        "tp_distance_mult": 1.5,
        "macro_weight": 0.25,
        "tech_weight": 0.50,
        "max_hold_hours": 72,
    },
}


# 参数调整覆盖的字段集合
_ADJUSTED_PARAMS = {
    "conf_threshold", "position_scale", "sl_distance_mult",
    "tp_distance_mult", "macro_weight", "tech_weight", "max_hold_hours",
}


class ParameterAdjuster:
    """主要矛盾驱动的参数调整器 (T10e, SPEC §4.5.2)。

    根据 FOMC 周期阶段自动调整策略参数，实现"主要矛盾主导、次要矛盾退居其次"。
    """

    def adjust(self, fomc_phase: str | None, base_params: dict[str, Any]) -> dict[str, Any]:
        """
        根据 FOMC 阶段调整策略参数。

        Args:
            fomc_phase: FOMC 周期阶段 (expectation_build/rise/jump/digest/event/repricing)
            base_params: 基础参数 dict

        Returns:
            调整后的参数 dict（保留 base_params 中的额外参数）
        """
        # HC: 开关关断时返回 base_params 不修改
        if not is_enabled("enable_contradiction_driven_layer"):
            return dict(base_params) if isinstance(base_params, dict) else {}
        if not is_enabled("enable_parameter_adjuster"):
            return dict(base_params) if isinstance(base_params, dict) else {}

        # HC: FAIL-OPEN — 异常时返回 base_params
        try:
            if not isinstance(base_params, dict):
                return {}
            if not isinstance(fomc_phase, str):
                return dict(base_params)

            # 未知阶段不调整
            overrides = FOMC_PARAM_OVERRIDES.get(fomc_phase)
            if overrides is None:
                return dict(base_params)

            # 复制 base_params + 覆盖调整字段
            result = dict(base_params)
            result.update(overrides)
            return result
        except Exception as e:
            logger.warning("ParameterAdjuster FAIL-OPEN: %s", e, exc_info=False)
            return dict(base_params) if isinstance(base_params, dict) else {}
