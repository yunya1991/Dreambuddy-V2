"""P1-1 拆分组件: MonteCarloPathFinder

从 deep_reasoning_engine.py 拆出的蒙特卡洛路径采样 + 最小阻力路径搜索职责。
整合路径生成、阻力计算、最优路径选择三个功能，同属"路径搜索"算法域。

来源: SPEC v0.3 §2.B — deep_reasoning_engine 多算法缝合体拆分
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from dreambuddy_evolution.core.path_integral import PathIntegralEngine

logger = logging.getLogger(__name__)


class MonteCarloPathFinder:
    """蒙特卡洛路径搜索器 — 从 DeepReasoningEngine 拆出的内聚组件.

    职责:
      1. 蒙特卡洛采样 N 条可能路径
      2. 计算路径阻力（交易成本 + 风险 + 不确定性）
      3. 搜索最小阻力路径（最小作用量 = 最优交易路径）

    HC-AGI-17 降级链: HJB → 变分法 → argmin
    """

    def __init__(self, n_paths: int = 1000) -> None:
        self._path_integral = PathIntegralEngine(n_paths=n_paths)

    # ------------------------------------------------------------------
    # 1. 蒙特卡洛多路径采样
    # ------------------------------------------------------------------
    def monte_carlo_paths(
        self,
        start_price: float,
        horizon: int,
        n_paths: int = 1000,
        volatility: float | None = None,
    ) -> list[np.ndarray]:
        """蒙特卡洛采样 N 条可能路径（复用 PathIntegralEngine）."""
        pi = self._path_integral
        pi.n_paths = n_paths
        vol = volatility if volatility is not None else 0.02
        return pi.sample_paths(start_price=start_price, horizon=horizon, volatility=vol)

    # ------------------------------------------------------------------
    # 2. 路径阻力计算
    # ------------------------------------------------------------------
    def compute_path_resistance(self, path: np.ndarray) -> float:
        """计算路径阻力（交易成本 + 风险 + 不确定性）."""
        return self._path_integral.compute_action(path)

    # ------------------------------------------------------------------
    # 3. 最小阻力路径搜索
    # ------------------------------------------------------------------
    def find_min_resistance_path(self, paths: list[np.ndarray]) -> dict[str, Any]:
        """搜索最小阻力路径（最小作用量 = 最优交易路径）.

        HC-AGI-17 降级链: HJB → 变分法 → argmin
        """
        # 1. 优先 HJB/变分法（开关控制 + FAIL-OPEN）
        try:
            from dreambuddy_evolution.agi_config import get_switch
            if get_switch("enable_hjb_solver", True) or get_switch("enable_variational_opt", True):
                from dreambuddy_evolution.core.hjb_solver import solve_optimal_path

                start_price = float(paths[0][0]) if paths and len(paths[0]) > 0 else 100.0
                horizon = max(len(p) for p in paths) - 1 if paths else 10
                # 从 paths 估算 vol
                all_returns = np.concatenate([
                    np.diff(p) / np.maximum(p[:-1], 1e-9) for p in paths
                ]) if paths else np.array([0.02])
                vol = float(np.std(all_returns)) if len(all_returns) > 1 else 0.02

                hjb_result = solve_optimal_path(
                    start_price=start_price,
                    horizon=horizon,
                    volatility=vol,
                    monte_carlo_paths=paths,
                )
                return {
                    "best_index": -1,
                    "best_resistance": hjb_result["total_cost"],
                    "best_path": hjb_result["optimal_path"],
                    "backend": hjb_result["backend"],
                    "converged": hjb_result["converged"],
                    "fallback_chain": hjb_result["fallback_chain"],
                }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] HJB/变分法降级到 argmin: %s", e)

        # 2. 兜底: argmin
        best_idx, best_resistance = self._path_integral.find_least_resistance_path(paths)
        return {
            "best_index": best_idx,
            "best_resistance": float(best_resistance),
            "best_path": paths[best_idx],
            "backend": "argmin",
            "converged": True,
            "fallback_chain": ["argmin"],
        }
