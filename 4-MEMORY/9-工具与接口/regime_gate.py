"""TB4 Thompson Sampling regime gate — SPEC-L0-AGENT-TRAIN-BASE v0.1 §4

美林时钟四段 = 四 arm，每 arm 维持 Beta(α, β)；
regime shift（TB1 PSI 漂移）→ 所有 arm Bayesian reset 为 Beta(1,1)。
"""

from __future__ import annotations

import random
from typing import List

# 美林时钟四段 = 四 arm
REGIME_ARMS: List[str] = ["defensive", "commodity", "bond", "risk"]


class ThompsonSamplingRegimeGate:
    """Thompson Sampling regime gate（美林时钟四段 = 四 arm）。

    α = 该 regime 下策略成功累计；β = 失败累计。
    选择：对每个 arm 做 Beta 采样，取采样值最高者。
    """

    def __init__(self, arms: List[str] = REGIME_ARMS):
        self.arms = list(arms)
        # 每个 arm 的无信息先验 Beta(1, 1)
        self.alpha = dict.fromkeys(self.arms, 1.0)
        self.beta = dict.fromkeys(self.arms, 1.0)

    def select_regime(self) -> str:
        """Thompson Sampling 选最优 regime（O(arm 数)）。"""
        samples = {arm: random.betavariate(self.alpha[arm], self.beta[arm]) for arm in self.arms}
        return max(samples, key=samples.get)

    def update(
        self,
        arm: str,
        success_rate: float,
        drift_detected: bool = False,
        _principal: Optional[dict] = None,  # D2：Mandate 感知，port 层硬门禁消费  # noqa: F821
    ) -> None:
        """更新 arm 的 Beta 分布。

        Args:
            arm: 被选中的 regime
            success_rate: [0, 1] 部分成功率
            drift_detected: TB1 PSI 漂移 → 所有 arm 重置先验
        """
        if drift_detected:
            for a in self.arms:
                self.alpha[a] = 1.0
                self.beta[a] = 1.0
            return

        rate = min(1.0, max(0.0, float(success_rate)))
        self.alpha[arm] += rate
        self.beta[arm] += 1.0 - rate

    def get_confidence(self, arm: str) -> float:
        """arm 置信度 = Beta mean（TB2 依赖）。"""
        return self.alpha[arm] / (self.alpha[arm] + self.beta[arm])
