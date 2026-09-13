"""
StructuralBreakDetector — 质变检测
理论文档: 三维度矛盾论理论框架.md §8

三类结构性断裂检测:
  1. 波动率制度转换: Markov-Switching GARCH / HMM (低波↔高波)
  2. 相关性结构断裂: CUSUM / Bai-Perron (相关性结构断点)
  3. 市场形态转换: Hurst Exponent (趋势态↔震荡态)

质变 = 矛盾力量排序变化 AND (以上任一结构性断裂)
仅排序变化（无结构性断裂）= 量变，不触发质变流程.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    from statsmodels.tsa.stattools import breaks_cusumolsresid
    _HAS_CUSUM = True
except ImportError:
    _HAS_CUSUM = False

try:
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
    _HAS_HMM = True
except ImportError:
    _HAS_HMM = False
    logger.warning("MarkovRegression not available, volatility regime detection disabled")


class StructuralBreakDetector:
    """
    质变检测器: 三类结构性断裂.

    每种检测方法独立实现，FAIL-OPEN.
    """

    def __init__(self, min_samples: int = 60, significance: float = 0.05):
        self._min_samples = min_samples
        self._alpha = significance

    def detect_all(self, price: np.ndarray, returns: np.ndarray | None = None,
                   benchmark: np.ndarray | None = None) -> dict[str, Any]:
        """
        运行全部三类检测.

        Args:
            price: 价格序列
            returns: 收益率序列（可选，自动计算）
            benchmark: 基准收益率序列（用于相关性检测）

        Returns:
            {
                "volatility_regime_shift": {...} | None,
                "correlation_break": {...} | None,
                "market_form_shift": {...} | None,
                "any_structural_break": bool,
            }
        """
        price = np.asarray(price, dtype=float)
        if returns is None:
            returns = np.diff(np.log(price)) if price.size > 1 else np.array([])
        else:
            returns = np.asarray(returns, dtype=float)

        result = {}
        result["volatility_regime_shift"] = self.detect_volatility_regime(returns)
        result["correlation_break"] = self.detect_correlation_break(returns, benchmark)
        result["market_form_shift"] = self.detect_market_form(price)
        result["any_structural_break"] = any(
            v is not None and v.get("detected", False)
            for v in [result["volatility_regime_shift"],
                      result["correlation_break"],
                      result["market_form_shift"]]
        )
        return result

    def detect_volatility_regime(self, returns: np.ndarray) -> dict[str, Any] | None:
        """
        波动率制度转换: 低波↔高波.

        用 Markov-Regression (2 状态) 检测 regime 转换概率.
        """
        returns = np.asarray(returns, dtype=float)
        valid = returns[~np.isnan(returns)]
        if valid.size < self._min_samples:
            return None

        if not _HAS_HMM:
            # Fallback: 简单波动率阈值法
            return self._fallback_vol_regime(valid)

        try:
            # 拟合 2 状态 HMM: 低波 / 高波
            model = MarkovRegression(valid, k_regimes=2, trend="c")
            result = model.fit(maxiter=100, disp=False)

            # 转换矩阵
            trans_matrix = result.regime_transitions
            if trans_matrix is None:
                return self._fallback_vol_regime(valid)

            # 低波→高波 转换概率
            p_low_to_high = float(trans_matrix[0, 1]) if trans_matrix.shape == (2, 2) else 0.0
            # 高波→低波 转换概率
            p_high_to_low = float(trans_matrix[1, 0]) if trans_matrix.shape == (2, 2) else 0.0

            # 当前 regime
            current_regime = int(result.smoothed_marginal_probabilities[-1].argmax())

            detected = p_low_to_high > 0.15 or p_high_to_low > 0.15

            return {
                "detected": detected,
                "current_regime": "high_vol" if current_regime == 1 else "low_vol",
                "p_low_to_high": p_low_to_high,
                "p_high_to_low": p_high_to_low,
                "method": "markov_regression",
            }
        except Exception as e:
            logger.debug("HMM vol regime detection failed: %s, using fallback", e)
            return self._fallback_vol_regime(valid)

    def _fallback_vol_regime(self, returns: np.ndarray) -> dict[str, Any]:
        """简单波动率阈值法（HMM 不可用时）."""
        try:
            rolling_vol = np.std(returns[-20:]) if returns.size >= 20 else np.std(returns)
            hist_vol = np.std(returns) if returns.size > 1 else 0.0
            if hist_vol < 1e-9:
                return None
            ratio = rolling_vol / hist_vol
            detected = ratio > 1.5 or ratio < 0.67  # 波动率显著偏离

            return {
                "detected": bool(detected),
                "current_regime": "high_vol" if ratio > 1.5 else ("low_vol" if ratio < 0.67 else "normal"),
                "vol_ratio": float(ratio),
                "method": "simple_threshold",
            }
        except Exception:
            return None

    def detect_correlation_break(self, returns: np.ndarray,
                                 benchmark: np.ndarray | None) -> dict[str, Any] | None:
        """
        相关性结构断裂: CUSUM 检验.
        """
        if benchmark is None:
            return None

        returns = np.asarray(returns, dtype=float)
        benchmark = np.asarray(benchmark, dtype=float)

        if returns.size != benchmark.size or returns.size < self._min_samples:
            return None

        # 滚动相关系数
        window = min(60, returns.size // 3)
        if window < 10:
            return None

        rolling_corr = np.array([
            np.corrcoef(returns[i:i+window], benchmark[i:i+window])[0, 1]
            for i in range(returns.size - window + 1)
        ])
        rolling_corr = rolling_corr[~np.isnan(rolling_corr)]
        if rolling_corr.size < 20:
            return None

        if _HAS_CUSUM:
            try:
                cusum_stat, p_value = breaks_cusumolsresid(rolling_corr)
                detected = p_value < self._alpha
                return {
                    "detected": bool(detected),
                    "p_value": float(p_value),
                    "cusum_stat": float(cusum_stat),
                    "method": "cusum_ols",
                }
            except Exception:
                pass

        # Fallback: 滚动相关系数的 z-score 变化
        try:
            first_half = rolling_corr[:rolling_corr.size // 2]
            second_half = rolling_corr[rolling_corr.size // 2:]
            mean_diff = abs(np.mean(second_half) - np.mean(first_half))
            std_all = np.std(rolling_corr)
            if std_all < 1e-9:
                return None
            z_score = mean_diff / std_all
            detected = abs(z_score) > 2.0  # 2σ 显著变化

            return {
                "detected": bool(detected),
                "z_score": float(z_score),
                "method": "rolling_zscore",
            }
        except Exception:
            return None

    def detect_market_form(self, price: np.ndarray) -> dict[str, Any] | None:
        """
        市场形态转换: 趋势态↔震荡态.
        用 Hurst Exponent 检测.
        H > 0.5: 趋势性（持久性）
        H < 0.5: 均值回归（震荡态）
        H ≈ 0.5: 随机游走
        """
        price = np.asarray(price, dtype=float)
        valid = price[~np.isnan(price)]
        if valid.size < self._min_samples:
            return None

        try:
            h_current = self._hurst_exponent(valid[-self._min_samples:])

            if valid.size >= self._min_samples * 2:
                h_prev = self._hurst_exponent(valid[-self._min_samples * 2:-self._min_samples])
            else:
                h_prev = 0.5  # 无前段数据时假设中性

            # 趋势态→震荡态 或 震荡态→趋势态
            was_trend = h_prev > 0.55
            is_trend = h_current > 0.55
            was_revert = h_prev < 0.45
            is_revert = h_current < 0.45

            detected = (was_trend and is_revert) or (was_revert and is_trend)

            return {
                "detected": bool(detected),
                "hurst_current": float(h_current),
                "hurst_prev": float(h_prev),
                "current_form": "trend" if is_trend else ("revert" if is_revert else "random"),
                "method": "hurst_exponent",
            }
        except Exception as e:
            logger.debug("Hurst exponent failed: %s", e)
            return None

    def _hurst_exponent(self, data: np.ndarray) -> float:
        """
        计算 Hurst Exponent (R/S 分析法).

        H > 0.5: 持久性（趋势态）
        H < 0.5: 均值回归（震荡态）
        H ≈ 0.5: 随机游走
        """
        n = data.size
        if n < 20:
            return 0.5

        # 对数收益率
        returns = np.diff(np.log(data))
        returns = returns[~np.isnan(returns)]
        n = returns.size
        if n < 20:
            return 0.5

        # R/S 分析: 多个尺度
        max_k = n // 2
        min_k = max(10, n // 20)
        ks = []
        rs_values = []

        for k in range(min_k, max_k + 1):
            num_blocks = n // k
            if num_blocks < 1:
                continue
            rs_list = []
            for b in range(num_blocks):
                block = returns[b * k: (b + 1) * k]
                if block.size < 2:
                    continue
                mean_block = np.mean(block)
                cumdev = np.cumsum(block - mean_block)
                r = float(np.max(cumdev) - np.min(cumdev))
                s = float(np.std(block))
                if s > 1e-12:
                    rs_list.append(r / s)

            if rs_list:
                ks.append(k)
                rs_values.append(np.mean(rs_list))

        if len(ks) < 3:
            return 0.5

        # log(R/S) = H * log(k) + c
        log_k = np.log(np.array(ks, dtype=float))
        log_rs = np.log(np.array(rs_values, dtype=float))

        # 线性回归
        try:
            h, _ = np.polyfit(log_k, log_rs, 1)
            return float(max(0.0, min(1.0, h)))
        except Exception:
            return 0.5
