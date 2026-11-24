"""GrangerPipelineAdapter — 包装 GrangerCausalityChecker 输出"过去主矛盾维度".

设计依据：融合方案 §10.2 + §8.9
职责：对每个维度的因子序列 vs 收益率做 Granger 因果检验，
      找出最显著的因果维度作为 G_dim（过去主矛盾）。

输出: G_dim ∈ {technical, fundamental, macro, None}, G_confidence ∈ [0,1]
"""

from __future__ import annotations

import logging
import os

import numpy as np

from dreambuddy_evolution.core.granger_causality_checker import GrangerCausalityChecker

logger = logging.getLogger(__name__)

VALID_DIMS = ("technical", "fundamental", "macro")
VALID_CORRECTIONS = ("bonferroni", "per_dim", "none")
DEFAULT_CORRECTION = "per_dim"


class GrangerPipelineAdapter:
    """Granger 因果链适配器 — 输出过去主矛盾维度 G_dim."""

    def __init__(
        self,
        max_lag: int = 5,
        significance: float = 0.05,
        correction: str | None = None,
    ) -> None:
        self._checker = GrangerCausalityChecker(max_lag=max_lag, significance=significance)
        self._max_lag = max_lag
        self._significance = significance
        # 多重比较校正：2026-11-25 用户决策「适当放宽，先让 G 可用率有用」
        # 默认 per_dim（0.05/3≈0.0167）；可用 GRANGER_CORRECTION 覆盖为 bonferroni|per_dim|none
        resolved = (
            correction or os.environ.get("GRANGER_CORRECTION") or DEFAULT_CORRECTION
        ).lower()
        if resolved not in VALID_CORRECTIONS:
            logger.warning("[FO] 未知 GRANGER_CORRECTION=%s，回退 %s", resolved, DEFAULT_CORRECTION)
            resolved = DEFAULT_CORRECTION
        self._correction = resolved
        self._alpha_threshold = self._resolve_alpha(significance, max_lag, resolved)

    @staticmethod
    def _resolve_alpha(significance: float, max_lag: int, correction: str) -> float:
        if correction == "bonferroni":
            return significance / (len(VALID_DIMS) * max_lag)
        if correction == "per_dim":
            return significance / len(VALID_DIMS)
        return significance

    def evaluate(
        self,
        factors_by_dim: dict[str, np.ndarray],
        returns: np.ndarray,
    ) -> dict:
        """对每个维度做 Granger 检验，输出最显著的因果维度.

        Args:
            factors_by_dim: {dim: 1D 因子时序}，dim ∈ {technical, fundamental, macro}
            returns: 收益率时序

        Returns:
            {
                "G_dim": Optional[str],        # 过去主矛盾维度，None 表示无显著因果
                "G_confidence": float,         # 1 - min_p_value ∈ [0, 1]
                "p_values": dict[str, float],  # 各维度最小 p 值
            }
        """
        # enable_granger_causality 开关：关闭时跳过因果检验（G_dim=None）
        try:
            from dreambuddy_evolution.agi_config import get_switch as _gs_gc

            if not _gs_gc("enable_granger_causality", True):
                return {"G_dim": None, "G_confidence": 0.0, "p_values": {}}
        except Exception as e:
            logger.debug("[FO] Granger 开关读取 fail: %s", e)  # FAIL-OPEN

        returns = np.asarray(returns, dtype=float)
        p_values: dict[str, float] = {}

        for dim in VALID_DIMS:
            factor = factors_by_dim.get(dim)
            if factor is None:
                continue
            factor = np.asarray(factor, dtype=float)

            # 对齐长度
            min_len = min(len(factor), len(returns))
            if min_len < self._checker._max_lag * 3 + 5:
                continue

            result = self._checker.check(factor[:min_len], returns[:min_len])
            if result is not None:
                p_values[dim] = result["p_value"]

        if not p_values:
            return {"G_dim": None, "G_confidence": 0.0, "p_values": {}}

        # 取 p 值最小的维度，需通过多重比较校正后的阈值
        g_dim = min(p_values, key=p_values.get)
        min_p = p_values[g_dim]

        if min_p >= self._alpha_threshold:
            return {"G_dim": None, "G_confidence": 0.0, "p_values": p_values}

        g_confidence = max(0.0, 1.0 - min_p / self._alpha_threshold)

        return {
            "G_dim": g_dim,
            "G_confidence": g_confidence,
            "p_values": p_values,
        }

    def reestimate(self, new_main_dim: str, factors_by_dim: dict, returns: np.ndarray) -> dict:
        """质变后重新估计 Granger 因果链（冷却期由 CrossValidationGate 控制）.

        直接复用 evaluate，但允许指定优先验证的维度。
        """
        return self.evaluate(factors_by_dim, returns)
