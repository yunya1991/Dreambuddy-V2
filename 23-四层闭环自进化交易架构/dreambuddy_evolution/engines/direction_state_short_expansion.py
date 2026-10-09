"""路径C: direction_state 解锁扩展

SPEC-自进化系统做空能力疏通探讨 §4 路径C：
  当前仅 direction_state == "SHORT_ONLY" 才解除 SHORT_BAN。
  扩展为多状态部分解锁 + 集中度限制。

状态映射（SPEC C.6 基于历史数据修订）:
  - SHORT_ONLY → 全解锁（仓位 1.0x）[现有行为，不依赖 btc_regime]
  - TREND_BEAR (btc_regime == "WEAK") → 部分解锁（仓位 0.5x）[开关 ON]
  - REVERSAL → 不解锁（历史 0% 胜率，负期望，即使开关 ON 也不解锁）
  - 其他状态 → 不解锁

集中度限制: 做空总仓位 / 总仓位 ≤ 30%（探讨值）
  - current_short_ratio >= 30% → 不解锁（已达上限）

安全侧 FAIL-OPEN: 异常/缺失/NaN → 不解锁（维持 SHORT_BAN）
开关: enable_direction_state_short_expansion（默认 False → 回退到仅 SHORT_ONLY 解锁）
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DirectionStateShortResult:
    """方向状态做空扩展结果

    Attributes:
        unlocked: 是否解除 SHORT_BAN
        position_multiplier: 仓位倍数 (0.0 / 0.5 / 1.0)
        state: 判定的状态 (SHORT_ONLY / TREND_BEAR / REVERSAL / OTHER)
        concentration_limit: 做空集中度上限 (0.3 = 30%)
        concentration_exceeded: 当前集中度是否超限
    """
    unlocked: bool
    position_multiplier: float
    state: str
    concentration_limit: float
    concentration_exceeded: bool


class DirectionStateShortExpansion:
    """方向状态做空扩展器

    受 enable_direction_state_short_expansion 开关控制（默认 False）。
    开关关闭时回退到仅 SHORT_ONLY 解锁（现有行为）。
    开关开启时扩展 TREND_BEAR 部分解锁。
    """

    CONCENTRATION_LIMIT = 0.3   # 做空总仓位占比上限 30%
    TREND_BEAR_POSITION = 0.5   # TREND_BEAR 部分解锁仓位
    SHORT_ONLY_POSITION = 1.0   # SHORT_ONLY 全解锁仓位

    def __init__(self) -> None:
        pass

    def evaluate(
        self,
        direction_state: str | None,
        btc_regime: str | None,
        current_short_ratio: float | None,
    ) -> DirectionStateShortResult:
        """方向状态做空扩展检测。

        Args:
            direction_state: 当前方向状态（SHORT_ONLY / REVERSAL / OTHER 等）
            btc_regime: RegimeClassifier 的 regime（STRONG/WEAK/NEUTRAL）
            current_short_ratio: 当前做空总仓位 / 总仓位

        Returns:
            DirectionStateShortResult: 解锁结果
        """
        # 开关检查（FAIL-OPEN: 异常 → 不解锁）
        try:
            from dreambuddy_evolution.agi_config import get_switch
            switch_on = get_switch("enable_direction_state_short_expansion")
        except Exception as e:
            logger.debug("[FO] DirectionStateShortExpansion switch check fail: %s", e)
            return self._not_unlocked("OTHER")

        # direction_state 检查（FAIL-OPEN: None → 不解锁）
        if direction_state is None:
            return self._not_unlocked("OTHER")

        state_upper = str(direction_state).upper()

        # 集中度检查（FAIL-OPEN: 异常 → 不解锁）
        ratio = self._safe_ratio(current_short_ratio)
        if ratio is None:
            return self._not_unlocked("OTHER")

        concentration_exceeded = ratio >= self.CONCENTRATION_LIMIT

        # 状态 1: SHORT_ONLY → 全解锁（不依赖 btc_regime，不依赖开关）
        if state_upper == "SHORT_ONLY":
            if concentration_exceeded:
                return DirectionStateShortResult(
                    unlocked=False,
                    position_multiplier=0.0,
                    state="SHORT_ONLY",
                    concentration_limit=self.CONCENTRATION_LIMIT,
                    concentration_exceeded=True,
                )
            return DirectionStateShortResult(
                unlocked=True,
                position_multiplier=self.SHORT_ONLY_POSITION,
                state="SHORT_ONLY",
                concentration_limit=self.CONCENTRATION_LIMIT,
                concentration_exceeded=False,
            )

        # 状态 2: REVERSAL → 不解锁（历史负期望，即使开关 ON 也不解锁）
        if state_upper == "REVERSAL":
            return self._not_unlocked("REVERSAL", concentration_exceeded)

        # 状态 3: TREND_BEAR → 部分解锁（需开关 ON + btc_regime == WEAK）
        if switch_on and btc_regime is not None:
            regime_upper = str(btc_regime).upper()
            if regime_upper == "WEAK":
                if concentration_exceeded:
                    return DirectionStateShortResult(
                        unlocked=False,
                        position_multiplier=0.0,
                        state="TREND_BEAR",
                        concentration_limit=self.CONCENTRATION_LIMIT,
                        concentration_exceeded=True,
                    )
                return DirectionStateShortResult(
                    unlocked=True,
                    position_multiplier=self.TREND_BEAR_POSITION,
                    state="TREND_BEAR",
                    concentration_limit=self.CONCENTRATION_LIMIT,
                    concentration_exceeded=False,
                )

        # 状态 4: 其他 → 不解锁
        return self._not_unlocked("OTHER", concentration_exceeded)

    def _safe_ratio(self, value: float | None) -> float | None:
        """安全转换集中度比率。返回 None 表示无效（FAIL-OPEN）。"""
        try:
            v = float(value)
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        except (TypeError, ValueError):
            return None

    def _not_unlocked(
        self, state: str, concentration_exceeded: bool = False
    ) -> DirectionStateShortResult:
        """不解锁结果"""
        return DirectionStateShortResult(
            unlocked=False,
            position_multiplier=0.0,
            state=state,
            concentration_limit=self.CONCENTRATION_LIMIT,
            concentration_exceeded=concentration_exceeded,
        )
