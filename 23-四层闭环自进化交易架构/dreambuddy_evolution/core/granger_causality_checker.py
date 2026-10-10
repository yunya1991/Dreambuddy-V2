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

        # statsmodels 可用 → 用 statsmodels; 否则用 numpy 降级实现
        if _HAS_STATSMODELS:
            return self._check_statsmodels(cause_arr, effect_arr)
        return self._check_numpy(cause_arr, effect_arr)

    def _check_statsmodels(self, cause_arr: np.ndarray,
                           effect_arr: np.ndarray) -> dict[str, Any] | None:
        """statsmodels 实现的 Granger 检验."""
        # ADF 平稳性检验（避免伪回归）
        try:
            try:
                adf_result = adfuller(effect_arr, autolag="AIC", result_object=False)
            except TypeError:
                adf_result = adfuller(effect_arr, autolag="AIC")
            is_stationary = adf_result[1] < 0.05
        except Exception:
            is_stationary = False  # 无法检验时假设非平稳，但继续检验

        # 一阶差分使序列平稳
        if not is_stationary:
            cause_arr = np.diff(cause_arr)
            effect_arr = np.diff(effect_arr)
            min_samples = self._max_lag * 3 + 5
            if cause_arr.size < min_samples:
                return None

        # Granger 因果检验
        # grangercausalitytests 需要 2D array: [effect, cause]
        data = np.column_stack([effect_arr, cause_arr])
        try:
            try:
                results = grangercausalitytests(data, maxlag=self._max_lag, verbose=False)
            except TypeError:
                results = grangercausalitytests(data, maxlag=self._max_lag)
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

    def _check_numpy(self, cause_arr: np.ndarray,
                     effect_arr: np.ndarray) -> dict[str, Any] | None:
        """纯 numpy 实现的 Granger 因果检验（statsmodels 不可用时降级）.

        F 检验: 比较受限模型 (仅 effect 滞后) 与非受限模型 (effect+cause 滞后).
        H0: cause 不 Granger-cause effect.
        """
        # 对齐长度
        n = min(len(cause_arr), len(effect_arr))
        cause_arr = cause_arr[:n]
        effect_arr = effect_arr[:n]

        best_lag = 1
        best_p = 1.0
        best_f = 0.0

        for lag in range(1, self._max_lag + 1):
            if n <= lag * 2 + 2:
                continue
            try:
                f_stat, p_val = self._granger_f_test(cause_arr, effect_arr, lag)
                if p_val < best_p:
                    best_p = p_val
                    best_lag = lag
                    best_f = f_stat
            except Exception:
                continue

        return {
            "is_granger_cause": best_p < self._alpha,
            "p_value": best_p,
            "best_lag": best_lag,
            "f_stat": best_f,
            "stationarized": False,
        }

    @staticmethod
    def _granger_f_test(cause: np.ndarray, effect: np.ndarray,
                        lag: int) -> tuple[float, float]:
        """单 lag 的 Granger F 检验.

        受限: Y_t = c + sum_{i=1..lag} a_i Y_{t-i}
        非受限: Y_t = c + sum a_i Y_{t-i} + sum b_j X_{t-j}
        F = ((RSS_r - RSS_u)/lag) / (RSS_u/(n - 2*lag - 1))
        """
        n = len(effect)
        # 构建滞后矩阵
        Y = effect[lag:]  # 因变量
        k = n - lag
        # 受限模型设计矩阵: [1, Y_{t-1}, ..., Y_{t-lag}]
        X_r = np.ones((k, lag + 1))
        for i in range(lag):
            X_r[:, i + 1] = effect[lag - 1 - i: n - 1 - i]
        # 非受限模型设计矩阵: 受限 + [X_{t-1}, ..., X_{t-lag}]
        X_u = np.ones((k, 2 * lag + 1))
        X_u[:, :lag + 1] = X_r
        for i in range(lag):
            X_u[:, lag + 1 + i] = cause[lag - 1 - i: n - 1 - i]

        # OLS: beta = (X^T X)^-1 X^T Y
        beta_r = np.linalg.lstsq(X_r, Y, rcond=None)[0]
        beta_u = np.linalg.lstsq(X_u, Y, rcond=None)[0]
        resid_r = Y - X_r @ beta_r
        resid_u = Y - X_u @ beta_u
        rss_r = float(np.sum(resid_r ** 2))
        rss_u = float(np.sum(resid_u ** 2))

        df_num = lag
        df_den = k - (2 * lag + 1)
        if df_den <= 0 or rss_u <= 0:
            return 0.0, 1.0
        f_stat = ((rss_r - rss_u) / df_num) / (rss_u / df_den)

        # p 值: 优先用 scipy F 分布; 不可用时用 F 统计量阈值近似
        try:
            from scipy import stats as _sp_stats
            p_val = float(1.0 - _sp_stats.f.cdf(f_stat, df_num, df_den))
        except Exception:
            # 降级: F > 3.0 视为显著 (α≈0.05 时 F 临界值约 3.0)
            p_val = 0.01 if f_stat > 3.0 else 0.5
        return f_stat, p_val

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
