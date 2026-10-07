"""GrangerPipelineAdapter — 包装 GrangerCausalityChecker 输出"过去主矛盾维度".

设计依据：融合方案 §10.2 + §8.9
职责：对每个维度的因子序列 vs 收益率做 Granger 因果检验，
      找出最显著的因果维度作为 G_dim（过去主矛盾）。

输出: G_dim ∈ {technical, fundamental, macro, None}, G_confidence ∈ [0,1]
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from dreambuddy_evolution.core.granger_causality_checker import GrangerCausalityChecker

VALID_DIMS = ("technical", "fundamental", "macro")


class GrangerPipelineAdapter:
    """Granger 因果链适配器 — 输出过去主矛盾维度 G_dim."""

    def __init__(self, max_lag: int = 5, significance: float = 0.05) -> None:
        self._checker = GrangerCausalityChecker(max_lag=max_lag, significance=significance)
        self._max_lag = max_lag
        # Bonferroni 校正：3 维度 × max_lag 个 lag 检验
        self._alpha = significance
        self._alpha_corrected = significance / (len(VALID_DIMS) * max_lag)

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
        except Exception:
            pass  # FAIL-OPEN

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

        # 取 p 值最小的维度，需通过 Bonferroni 校正阈值
        g_dim = min(p_values, key=p_values.get)
        min_p = p_values[g_dim]

        if min_p >= self._alpha_corrected:
            return {"G_dim": None, "G_confidence": 0.0, "p_values": p_values}

        g_confidence = max(0.0, 1.0 - min_p / self._alpha_corrected)

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
