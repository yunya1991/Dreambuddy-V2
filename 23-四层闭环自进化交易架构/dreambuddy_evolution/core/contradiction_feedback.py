"""
Phase 3.5: ContradictionFeedback — 验证回流闭环
SPEC-主要矛盾识别与最小阻力路径设计.md §4.6

矛盾论 §矛盾转化: 验证失败 → 降低矛盾权重, 验证成功 → 升级
形成"识别→验证→权重更新→再识别"闭环

HC-AGI-22: weight_factor ∈ [0.3, 1.5], 下限 0.3 防止矛盾权重归零

使用场景:
  ShadowRL 验证完成后, 回流调整矛盾权重
  验证成功 (pnl > 0) → 矛盾置信度升级 (Bayesian 更新)
  验证失败 (pnl < 0) → 矛盾转化, 权重降级
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ContradictionFeedback:
    """验证回流闭环: 调整矛盾权重.

    矛盾论 §矛盾转化: 一定条件下相互转化
      - 验证成功 → 矛盾方向置信度升级
      - 验证失败 → 矛盾转化, 权重降级

    HC-AGI-22: weight_factor ∈ [0.3, 1.5]
    """

    WEIGHT_FLOOR = 0.3   # HC-AGI-22: 下限 0.3
    WEIGHT_CEILING = 1.5  # HC-AGI-22: 上限 1.5
    SUCCESS_STEP = 0.1    # 成功步长
    FAILURE_STEP = 0.2   # 失败步长
    SUCCESS_TRIALS_NORMALIZE = 10  # 成功验证次数归一化

    def adjust_weight(
        self,
        primary_contradiction: dict,
        outcome: dict | Any,
    ) -> dict:
        """根据验证结果调整矛盾权重.

        Args:
            primary_contradiction: PrimaryContradictionIdentifier 输出（含 dimension 字段）
            outcome: {success: bool, pnl: float, n_trials: int, fail_streak: int}

        Returns:
            primary_contradiction + {"weight_adjustment": {"weight_factor": float, "dimension": str}}

        Fix 3: 按维度独立调权。dimension 从 primary_contradiction 提取。
        """
        try:
            if not isinstance(primary_contradiction, dict):
                return self._default_result(primary_contradiction)
            if not isinstance(outcome, dict):
                return self._default_result(primary_contradiction)

            success = bool(outcome.get("success", False))
            n_trials = int(outcome.get("n_trials", 0))
            fail_streak = int(outcome.get("fail_streak", 0))

            if success:
                # Bayesian 升级: 验证次数越多, 置信度越高
                trial_factor = min(1.0, n_trials / self.SUCCESS_TRIALS_NORMALIZE)
                weight_factor = 1.0 + self.SUCCESS_STEP * trial_factor
            else:
                # 矛盾转化: 连续失败次数越多, 权重降级越大
                weight_factor = 1.0 - self.FAILURE_STEP * max(1, fail_streak)

            # HC-AGI-22: 截断 [0.3, 1.5]
            weight_factor = max(self.WEIGHT_FLOOR, min(self.WEIGHT_CEILING, weight_factor))

            # Fix 3: 提取维度信息
            dim = primary_contradiction.get("dimension", "unknown")

            return {
                **primary_contradiction,
                "weight_adjustment": {
                    "weight_factor": float(weight_factor),
                    "dimension": dim,
                    "success": success,
                    "n_trials": n_trials,
                    "fail_streak": fail_streak,
                },
            }
        except Exception as e:  # noqa: BLE001
            logger.debug("[FO-AGI][ContradictionFeedback] FAIL-OPEN: %s", e)
            return self._default_result(primary_contradiction)

    def _default_result(self, primary: Any) -> dict:
        """FAIL-OPEN 默认结果."""
        if isinstance(primary, dict):
            return {
                **primary,
                "weight_adjustment": {"weight_factor": 1.0},
            }
        return {
            "direction": "neutral",
            "strength": 0.0,
            "weight_adjustment": {"weight_factor": 1.0},
        }
