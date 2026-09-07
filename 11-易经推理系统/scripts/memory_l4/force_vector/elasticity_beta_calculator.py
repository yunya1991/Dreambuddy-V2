"""弹性系数β计算器 —— 价格响应衰减/放大检测。

纯 numpy 实现。所有路径 FAIL-OPEN（异常返回中性默认值 β=1.0，信号 False）。
对应 Spec §三-A Step 3-A-1 ElasticityBeta。

β = cov(ΔPrice, ΔForce) / var(ΔForce)   （OLS 回归斜率）
β_7d  = 近7天  β；β_30d = 近30天 β；β_ratio = β_7d / β_30d
  β_ratio < 0.5 持续3天 → decay_signal=True,        decay_days>=3
  β_ratio > 2.0 持续3天 → amplification_signal=True, amplification_days>=3
"""
from __future__ import annotations

import numpy as np

from force_vector.models import ElasticityBeta


class ElasticityBetaCalculator:
    """弹性系数β计算器（价格响应衰减/放大检测）。

    β = OLS 回归斜率 = cov(ΔPrice, ΔForce) / var(ΔForce)。
    var(ΔForce)≈0（力向量无变化）、样本不足、长度不一致 → β=1.0（中性）。
    """

    # 信号阈值与持续天数
    _DECAY_THRESHOLD = 0.5            # β_ratio < 0.5 → 衰减
    _AMPLIFICATION_THRESHOLD = 2.0    # β_ratio > 2.0 → 放大
    _PERSIST_DAYS = 3                 # 持续天数门槛
    _NEUTRAL_BETA = 1.0               # 中性默认 β
    _VAR_EPS = 1e-12                  # var(ΔForce) 小于此阈值视为无变化

    def compute(self, price_changes_7d: list, force_changes_7d: list,
                price_changes_30d: list, force_changes_30d: list,
                decay_history: list = None) -> ElasticityBeta:
        """弹性系数β计算（价格响应衰减/放大检测）。

        β_7d  = cov(ΔPrice_7d,  ΔForce_7d)  / var(ΔForce_7d)
        β_30d = cov(ΔPrice_30d, ΔForce_30d) / var(ΔForce_30d)
        β_ratio = β_7d / β_30d（β_30d≈0 时取中性 1.0，避免发散）

        矛盾转化信号（基于 decay_history 历史 β_ratio 序列，从末尾连续计数）：
          β_ratio < 0.5 持续3天 → decay_signal=True,        decay_days>=3
          β_ratio > 2.0 持续3天 → amplification_signal=True, amplification_days>=3

        decay_history: 历史 β_ratio 列表，用于计算持续天数（按传入序列原样计数）。
        异常时（力向量无变化、数据为空、长度不一致）β=1.0（中性），信号 False。
        """
        try:
            # 计算 7d / 30d 弹性系数（OLS 回归斜率）
            beta_7d = self._ols_beta(price_changes_7d, force_changes_7d)
            beta_30d = self._ols_beta(price_changes_30d, force_changes_30d)

            # β_ratio = β_7d / β_30d（β_30d≈0 时取中性 1.0，避免发散）
            if abs(beta_30d) < self._VAR_EPS:
                beta_ratio = self._NEUTRAL_BETA
            else:
                beta_ratio = beta_7d / beta_30d
            # β_ratio 异常（nan/inf）→ 中性
            if not np.isfinite(beta_ratio):
                beta_ratio = self._NEUTRAL_BETA

            # 信号检测：从 decay_history 末尾连续计数（按传入序列原样）
            history = list(decay_history) if decay_history else []
            decay_days = self._count_trailing(
                history, lambda v: v < self._DECAY_THRESHOLD)
            amplification_days = self._count_trailing(
                history, lambda v: v > self._AMPLIFICATION_THRESHOLD)

            decay_signal = decay_days >= self._PERSIST_DAYS
            amplification_signal = amplification_days >= self._PERSIST_DAYS

            return ElasticityBeta(
                beta_7d=float(beta_7d),
                beta_30d=float(beta_30d),
                beta_ratio=float(beta_ratio),
                decay_signal=bool(decay_signal),
                amplification_signal=bool(amplification_signal),
                decay_days=int(decay_days),
                amplification_days=int(amplification_days),
            )
        except Exception:
            # FAIL-OPEN：异常时全中性，信号 False
            return ElasticityBeta(
                beta_7d=self._NEUTRAL_BETA,
                beta_30d=self._NEUTRAL_BETA,
                beta_ratio=self._NEUTRAL_BETA,
                decay_signal=False,
                amplification_signal=False,
                decay_days=0,
                amplification_days=0,
            )

    def _ols_beta(self, price_changes: list, force_changes: list) -> float:
        """OLS 回归斜率 β = cov(ΔPrice, ΔForce) / var(ΔForce)。

        var(ΔForce)≈0、样本不足（<2）、长度不一致 → 返回中性 1.0。
        ddof 在 cov/var 中同阶，比例中相互抵消，故 ddof 取值不影响 β。
        """
        try:
            if price_changes is None or force_changes is None:
                return self._NEUTRAL_BETA
            n = len(price_changes)
            if n < 2 or n != len(force_changes):
                return self._NEUTRAL_BETA
            x = np.asarray(force_changes, dtype=float)    # ΔForce（自变量）
            y = np.asarray(price_changes, dtype=float)     # ΔPrice（因变量）
            # var(ΔForce)：样本方差（ddof 与 cov 一致，比例中抵消）
            var_x = float(np.var(x, ddof=1))
            if var_x < self._VAR_EPS:
                return self._NEUTRAL_BETA
            cov_xy = float(np.cov(x, y, ddof=1)[0, 1])
            beta = cov_xy / var_x
            if not np.isfinite(beta):
                return self._NEUTRAL_BETA
            return beta
        except Exception:
            return self._NEUTRAL_BETA

    def _count_trailing(self, series: list, predicate) -> int:
        """从序列末尾向前连续满足 predicate 的元素个数。

        遇首个不满足（或异常）即停止。用于「持续 N 天」计数。
        """
        count = 0
        for v in reversed(series):
            try:
                if predicate(v):
                    count += 1
                else:
                    break
            except Exception:
                break
        return count
