"""BdsmSignalLevelClassifier — BDSM 做多三层置信度递进开仓判定引擎.

SPEC: docs/superpowers/specs/2026-09-18-bdsm-tiered-confidence-open-spec.md v2.0 §2.2/§3
接线: polling_trader._bdsm_independent_open 做多分支消费本分类器实现 L1→L2→L3 递进，
three_factor_long 引擎（ThreeFactorLongDetector）经由 three_factor_signal 参数接入。

铁律（spec §0.2）:
  R1 战略层方向过滤优先 — direction_state 禁多一律不开仓
  R2 置信度递进 = AND 叠加（L2 含 L1 全部条件，L3 含 L2 全部条件）
  R4 FAIL-OPEN — 信号缺失/异常 → 降级到满足的最高层级或 None（不开仓）

安全侧约定: 做多方向 is_trial=False（BDSM 价值建仓非试错）。
仓位/杠杆参数表为 spec §2.2 标定值，供调用方按层级取用；
实际下单金额是否采用层级仓位由调用方风控（_apply_bdsm_scaling）决定。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BdsmSignalLevelResult:
    """做多层级判定结果.

    Attributes:
        level: 层级 ("L1" / "L2" / "L3")
        position_pct: 层级仓位比例 (spec §2.2: 0.05 / 0.08 / 0.12)
        leverage: 层级杠杆 (spec §2.2: 3 / 3 / 5)
        is_trial: 是否试错单（做多恒 False）
    """
    level: str
    position_pct: float
    leverage: int
    is_trial: bool


class BdsmSignalLevelClassifier:
    """BDSM 做多三层置信度递进判定器（纯函数式，无状态）."""

    # R1: 战略层放行的 direction_state 集合
    ALLOWED_LONG_STATES = frozenset({"LONG_ONLY", "LONG_PREFER", "NEUTRAL"})

    # R3: 层级仓位/杠杆参数表（spec §2.2）
    L1_POSITION_PCT = 0.05
    L2_POSITION_PCT = 0.08
    L3_POSITION_PCT = 0.12
    L1_LEVERAGE = 3
    L2_LEVERAGE = 3
    L3_LEVERAGE = 5

    def classify_long(
        self,
        direction_state: str | None,
        bds_score: float | None,
        three_factor_signal: bool | None,
        trend_action: str | dict | None,
    ) -> BdsmSignalLevelResult | None:
        """做多层级判定（L1 → L2 → L3 AND 叠加）.

        Args:
            direction_state: 战略层方向状态（LONG_ONLY/LONG_PREFER/NEUTRAL/
                             SHORT_ONLY/SHORT_PREFER/FREEZE）
            bds_score: BDSM 基本面分数（> 0 为做多基础条件）
            three_factor_signal: 做多三因子共振信号（ThreeFactorLongDetector.detect）
            trend_action: MA200 趋势动作（str 或 coin_entry["trend_stop"] dict；
                          "none" = 未破 MA200，做多 L3 条件）

        Returns:
            BdsmSignalLevelResult（L1/L2/L3）或 None（不开仓，FAIL-OPEN）
        """
        try:
            # R1: 战略层方向过滤（FAIL-OPEN: None/异常 → 不开仓）
            state = str(direction_state or "").strip().upper()
            if not state or state not in self.ALLOWED_LONG_STATES:
                return None

            # L1 基础层: bds_score > 0（FAIL-OPEN: 异常 → 不开仓）
            bds = float(bds_score)
            if bds <= 0.0:
                return None

            # 层级递进（R2: AND 叠加；R4: 信号缺失降级到当前层级）
            level = "L1"
            if bool(three_factor_signal):
                level = "L2"
                # L3 激进层: trend_stop.action == "none"（站稳 MA200）
                if self._trend_action_str(trend_action) == "none":
                    level = "L3"

            return self._result(level)

        except (TypeError, ValueError) as e:
            logger.debug("[FO] BdsmSignalLevelClassifier classify_long fail: %s", e)
            return None
        except Exception as e:
            logger.debug("[FO] BdsmSignalLevelClassifier classify_long crash: %s", e)
            return None

    @staticmethod
    def _trend_action_str(trend_action: str | dict | None) -> str:
        """规范化 trend_action（支持 str / trend_stop dict / None）。"""
        if isinstance(trend_action, dict):
            trend_action = trend_action.get("action")
        return str(trend_action or "").strip().lower()

    def _result(self, level: str) -> BdsmSignalLevelResult:
        params = {
            "L1": (self.L1_POSITION_PCT, self.L1_LEVERAGE),
            "L2": (self.L2_POSITION_PCT, self.L2_LEVERAGE),
            "L3": (self.L3_POSITION_PCT, self.L3_LEVERAGE),
        }[level]
        return BdsmSignalLevelResult(
            level=level,
            position_pct=params[0],
            leverage=params[1],
            is_trial=False,  # 做多方向: 价值建仓非试错（spec §2.2）
        )
