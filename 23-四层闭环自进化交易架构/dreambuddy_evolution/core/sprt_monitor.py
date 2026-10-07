"""SPRTMonitor — 序贯概率比检验（Wald 1945），监测单链路一致性.

设计依据：融合方案 §10.11.4a
用于 Q4 单链路降级模式的可靠性监测：当单链路一致率 < 50% 时，
自动切换至完全中性（both_none）降级模式。

H0: p >= p0（一致率可接受，保持单链路降级）
H1: p <= p1（一致率不可接受，切换完全中性）

对数似然比（数值稳定）：
  log Λ = k * log(p1/p0) + (n-k) * log((1-p1)/(1-p0))
决策边界：
  A = (1-β)/α   → 接受 H1
  B = β/(1-α)   → 接受 H0
"""
from __future__ import annotations

import math


class SPRTMonitor:
    """序贯概率比检验监测器."""

    def __init__(
        self,
        p0: float = 0.75,
        p1: float = 0.50,
        alpha: float = 0.05,
        beta: float = 0.10,
    ) -> None:
        """
        Args:
            p0: H0 下的一致率下限（可接受阈值）
            p1: H1 下的一致率上限（不可接受阈值）
            alpha: 第一类错误率（弃真）
            beta: 第二类错误率（取伪）
        """
        if not (0 < p1 < p0 < 1):
            raise ValueError(f"需 0 < p1 < p0 < 1，实际 p0={p0}, p1={p1}")
        if not (0 < alpha < 1 and 0 < beta < 1):
            raise ValueError(f"alpha/beta 需在 (0,1)，实际 alpha={alpha}, beta={beta}")

        self.p0 = p0
        self.p1 = p1
        self.alpha = alpha
        self.beta = beta

        # 决策边界
        self.A = (1.0 - beta) / alpha  # 上界：> A 接受 H1
        self.B = beta / (1.0 - alpha)  # 下界：< B 接受 H0

        # 对数似然比系数
        self._log_p1_p0 = math.log(p1 / p0)
        self._log_1mp1_1mp0 = math.log((1.0 - p1) / (1.0 - p0))

        self.reset()

    def reset(self) -> None:
        """重置计数器."""
        self.n: int = 0
        self.k: int = 0
        self._log_lambda: float = 0.0

    def update(self, is_consistent: bool) -> str:
        """观测一个样本并更新似然比.

        Args:
            is_consistent: 本期单链路输出是否与基准一致

        Returns:
            "accept_h0" | "accept_h1" | "continue"
        """
        self.n += 1
        if is_consistent:
            self.k += 1
            self._log_lambda += self._log_p1_p0
        else:
            self._log_lambda += self._log_1mp1_1mp0

        # 用对数边界比较
        log_A = math.log(self.A)
        log_B = math.log(self.B)

        if self._log_lambda >= log_A:
            return "accept_h1"
        if self._log_lambda <= log_B:
            return "accept_h0"
        return "continue"

    @property
    def consistency_rate(self) -> float:
        """当前观测一致率 k/n."""
        if self.n == 0:
            return 0.0
        return self.k / self.n
