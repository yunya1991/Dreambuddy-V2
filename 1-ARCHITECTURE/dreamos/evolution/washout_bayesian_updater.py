"""BayesianUpdater — 洗盘/真弱势贝叶斯置信度更新器.

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §5.4 / §5.6

W4 阶段落地 (纯新增, 零回归):
  - Beta-Bernoulli 模型: P(washout) ~ Beta(alpha, beta)
  - 先验/后验更新: 观察 k 个 washout + (n-k) 个 weakness →
    posterior ~ Beta(alpha + k, beta + (n-k))
  - reward = tanh(pnl_pct / 0.02) 归一化 [-1, 1] (硬约束)

设计原则 (硬约束):
  - HC-2: KNN/CBR + 贝叶斯闭环 (禁用 LLM, 本文件纯数学无 LLM 依赖)
  - 自进化硬约束: reward = tanh(pnl_pct / 0.02) 归一化 [-1, 1]
  - FAIL-OPEN: 异常 → 返回先验均值, 不抛错

数学:
  先验 P(washout) = alpha / (alpha + beta)
  观察 k 个 washout, m 个 weakness (n = k + m):
    posterior_alpha = alpha + k
    posterior_beta = beta + m
    posterior_mean = posterior_alpha / (posterior_alpha + posterior_beta)
"""
from __future__ import annotations

import logging
import math
import os

__all__ = ["BayesianUpdater"]

logger = logging.getLogger(__name__)


class BayesianUpdater:
    """贝叶斯置信度更新器 (Beta-Bernoulli 模型).

    用法:
        updater = BayesianUpdater(prior_alpha=1.0, prior_beta=1.0)
        prior = updater.prior_mean()  # 0.5
        posterior = updater.update(washout_count=4, weakness_count=1)  # ≈0.714
    """

    def __init__(
        self,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ):
        """初始化 Beta 先验.

        Args:
            prior_alpha: Beta 先验 alpha 参数 (>0, 默认 1.0 = 均匀分布)
            prior_beta: Beta 先验 beta 参数 (>0, 默认 1.0 = 均匀分布)

        默认 alpha=beta=1 → Beta(1,1) = Uniform(0,1), 先验均值 0.5 (无信息先验).
        """
        self.prior_alpha = max(0.001, float(prior_alpha))  # 防止 0
        self.prior_beta = max(0.001, float(prior_beta))

    def prior_mean(self) -> float:
        """返回先验 P(washout) = alpha / (alpha + beta)."""
        total = self.prior_alpha + self.prior_beta
        if total <= 0:
            return 0.5
        return self.prior_alpha / total

    def update(
        self,
        washout_count: int,
        weakness_count: int,
    ) -> float:
        """贝叶斯后验更新.

        Args:
            washout_count: KNN 邻居中 washout 案例数 (k)
            weakness_count: KNN 邻居中 weakness 案例数 (m)

        Returns:
            posterior P(washout | neighbors) = (alpha + k) / (alpha + beta + k + m)

        FAIL-OPEN:
            异常 → 返回先验均值.
        """
        try:
            k = max(0, int(washout_count))
            m = max(0, int(weakness_count))
            alpha_post = self.prior_alpha + k
            beta_post = self.prior_beta + m
            total = alpha_post + beta_post
            if total <= 0:
                return self.prior_mean()
            return alpha_post / total
        except Exception as e:
            logger.debug("BayesianUpdater.update FAIL-OPEN: %s", e)
            return self.prior_mean()

    def update_with_reward(
        self,
        washout_count: int,
        weakness_count: int,
        avg_reward: float,
    ) -> float:
        """带 reward 加权的贝叶斯后验更新 (阶段2: reward 回流闭环).

        公式:
          effective_k = k * (1 + avg_reward) / 2    — 正 reward 放大 washout 证据
          effective_m = m * (1 - avg_reward) / 2  — 负 reward 放大 weakness 证据
          posterior = (alpha + effective_k) / (alpha + beta + effective_k + effective_m)

        开关 (ENABLE_EVOLUTION_EXPLORATION):
          - 关断 (默认): 等同 update(washout_count, weakness_count), 字节等价
          - 开启: 使用 reward 加权公式

        FAIL-OPEN:
            avg_reward 非法 → 返回先验均值.
        """
        try:
            # 开关关断 → 等同原始 update (字节等价)
            if os.environ.get("ENABLE_EVOLUTION_EXPLORATION", "") != "1":
                return self.update(washout_count, weakness_count)

            r = float(avg_reward)
            # 裁剪到 [-1, 1]
            if r < -1.0:
                r = -1.0
            elif r > 1.0:
                r = 1.0

            k = max(0, int(washout_count))
            m = max(0, int(weakness_count))
            effective_k = k * (1.0 + r) / 2.0
            effective_m = m * (1.0 - r) / 2.0

            alpha_post = self.prior_alpha + effective_k
            beta_post = self.prior_beta + effective_m
            total = alpha_post + beta_post
            if total <= 0:
                return self.prior_mean()
            return alpha_post / total
        except Exception as e:
            logger.debug("BayesianUpdater.update_with_reward FAIL-OPEN: %s", e)
            return self.prior_mean()

    @staticmethod
    def compute_reward(pnl_pct: float) -> float:
        """reward = tanh(pnl_pct / 0.02) 归一化到 [-1, 1].

        硬约束: 自进化系统矛盾反馈用真实 PnL 作为 reward 信号.
        - pnl=0.02 → reward ≈ 0.7616 (tanh(1))
        - pnl=-0.02 → reward ≈ -0.7616
        - pnl=0.10 → reward ≈ 0.9999 (饱和)
        - pnl=-0.10 → reward ≈ -0.9999 (饱和)
        """
        try:
            return math.tanh(float(pnl_pct) / 0.02)
        except Exception:
            return 0.0
