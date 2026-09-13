"""
GrangerCausalityChecker — 矛盾间因果检验
理论文档: 三维度矛盾论理论框架.md §5

Granger 因果检验: 如果 X 的过去值能改善对 Y 的预测（在 Y 自身历史的条件下），
则 X 是 Y 的 Granger 原因。

核心功能:
  1. 双变量 Granger 因果检验（F 统计量 + p 值）
  2. Per-Regime Granger 因果（分 regime 独立检验）
  3. 因果传导链验证（主矛盾→次矛盾的因果路径）

依赖: statsmodels (grangercausalitytests), numpy
FAIL-OPEN: statsmodels 缺失或数据不足时返回 None
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    from statsmodels.tsa.stattools import grangercausalitytests, adfuller
    _HAS_STATSMODELS = True
except ImportError:
    _HAS_STATSMODELS = False
    logger.warning("statsmodels not available, GrangerCausalityChecker will return None")


class GrangerCausalityChecker:
    """
    矛盾间 Granger 因果检验器.

    Per-Regime Granger: 先分 regime 再做检验——
    矛盾间的因果传导在不同 regime 中可能完全不同.
    """

    def __init__(self, max_lag: int = 5, significance: float = 0.05):
        self._max_lag = max_lag
        self._alpha = significance

    def check(self, cause: list[float] | np.ndarray,
              effect: list[float] | np.ndarray) -> dict[str, Any] | None:
        """
        双变量 Granger 因果检验.

        Args:
            cause: 假设的原因变量时序
            effect: 假设的结果变量时序

        Returns:
            {
                "is_granger_cause": bool,
                "p_value": float,
                "best_lag": int,
                "f_stat": float,
            }
            None if 检验无法执行.
        """
        if not _HAS_STATSMODELS:
            return None

        cause_arr = np.asarray(cause, dtype=float)
        effect_arr = np.asarray(effect, dtype=float)

        # 数据检查
        min_samples = self._max_lag * 3 + 5
        if cause_arr.size < min_samples or effect_arr.size < min_samples:
            return None

        # 去除 NaN
        valid_mask = ~(np.isnan(cause_arr) | np.isnan(effect_arr))
        cause_arr = cause_arr[valid_mask]
        effect_arr = effect_arr[valid_mask]
        if cause_arr.size < min_samples:
            return None

        # ADF 平稳性检验（避免伪回归）
        try:
            adf_result = adfuller(effect_arr, autolag="AIC")
            is_stationary = adf_result[1] < 0.05
        except Exception:
            is_stationary = False  # 无法检验时假设非平稳，但继续检验

        # 一阶差分使序列平稳
        if not is_stationary:
            cause_arr = np.diff(cause_arr)
            effect_arr = np.diff(effect_arr)
            if cause_arr.size < min_samples:
                return None

        # Granger 因果检验
        # grangercausalitytests 需要 2D array: [effect, cause]
        data = np.column_stack([effect_arr, cause_arr])
        try:
            results = grangercausalitytests(data, maxlag=self._max_lag, verbose=False)
        except Exception as e:
            logger.debug("Granger test failed: %s", e)
            return None

        # 找最优 lag（p 值最小）
        best_lag = 1
        best_p = 1.0
        best_f = 0.0
        for lag in range(1, self._max_lag + 1):
            if lag not in results:
                continue
            try:
                # ssr_ftest: F 检验
                test_results = results[lag][0]["ssr_ftest"]
                f_stat = float(test_results[0])
                p_val = float(test_results[1])
                if p_val < best_p:
                    best_p = p_val
                    best_lag = lag
                    best_f = f_stat
            except (KeyError, IndexError, TypeError):
                continue

        return {
            "is_granger_cause": best_p < self._alpha,
            "p_value": best_p,
            "best_lag": best_lag,
            "f_stat": best_f,
            "stationarized": not is_stationary,
        }

    def check_per_regime(self, cause: list[float] | np.ndarray,
                         effect: list[float] | np.ndarray,
                         regimes: list[str] | np.ndarray) -> dict[str, dict[str, Any] | None]:
        """
        Per-Regime Granger 因果检验.

        在每个 regime 内独立检验 Granger 因果性.

        Args:
            cause: 假设的原因变量时序
            effect: 假设的结果变量时序
            regimes: 每个 time step 的 regime 标签

        Returns:
            {regime_name: check() 结果或 None}
        """
        cause_arr = np.asarray(cause, dtype=float)
        effect_arr = np.asarray(effect, dtype=float)
        regimes_arr = np.asarray(regimes)

        if cause_arr.size != effect_arr.size or cause_arr.size != regimes_arr.size:
            return {}

        result = {}
        unique_regimes = np.unique(regimes_arr[~pd_isna(regimes_arr)]) if _HAS_PANDAS else set(regimes_arr)

        for regime in unique_regimes:
            mask = regimes_arr == regime
            regime_cause = cause_arr[mask]
            regime_effect = effect_arr[mask]
            result[str(regime)] = self.check(regime_cause, regime_effect)

        return result

    def verify_causal_chain(self, chain: list[list[float] | np.ndarray]) -> dict[str, Any]:
        """
        验证因果传导链: A→B→C→D.

        Args:
            chain: [A, B, C, D] 各变量的时序数据

        Returns:
            {
                "chain_valid": bool,  # 每环都通过
                "links": [{"from": i, "to": i+1, "result": ...}, ...],
                "weakest_link": int,  # p 值最大的环
            }
        """
        links = []
        all_valid = True
        weakest_p = 0.0
        weakest_idx = 0

        for i in range(len(chain) - 1):
            result = self.check(chain[i], chain[i + 1])
            link = {"from": i, "to": i + 1, "result": result}
            links.append(link)

            if result is None:
                all_valid = False
            elif not result["is_granger_cause"]:
                all_valid = False
                if result["p_value"] > weakest_p:
                    weakest_p = result["p_value"]
                    weakest_idx = i

        return {
            "chain_valid": all_valid,
            "links": links,
            "weakest_link": weakest_idx if not all_valid else None,
        }


# pandas optional import
try:
    import pandas as _pd
    _HAS_PANDAS = True
    def pd_isna(arr):
        return _pd.isna(arr)
except ImportError:
    _HAS_PANDAS = False
    def pd_isna(arr):
        return np.array([x is None or (isinstance(x, float) and np.isnan(x)) for x in arr])
