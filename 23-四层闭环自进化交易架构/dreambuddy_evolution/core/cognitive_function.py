"""
索罗斯认知函数: 认知→行为.

C = 贝叶斯信念更新
  认知_t = P(预期_t | 信息流_t, 认知_{t-1})

反身性环 = C∘P
  认知 → 仓位(P) → 市场影响 → 新信息流 → 认知更新

SPEC: 非线性多阶段最优路径理论调研框架 §十九
"""
from __future__ import annotations


class CognitiveFunction:
    """索罗斯认知函数: 贝叶斯信念更新.

    简化贝叶斯更新: belief += lr × weight × (signal - belief)
    - signal > belief → belief 上升（利多信息强化认知）
    - signal < belief → belief 下降（利空信息修正认知）
    """

    def __init__(self, prior_strength: float = 0.5, learning_rate: float = 0.1):
        """
        Args:
            prior_strength: 先验信念 [0, 1]，0.5 = 中性
            learning_rate: 学习率 [0.01, 0.5]，越大更新越快
        """
        self._belief = max(0.0, min(1.0, prior_strength))
        self._lr = max(0.01, min(0.5, learning_rate))

    def update(self, info_signal: float, info_weight: float = 1.0) -> float:
        """贝叶斯式信念更新.

        Args:
            info_signal: 信息流信号 [0, 1]（<0.5利空，>0.5利多）
            info_weight: 信息权重 [0, 1]

        Returns:
            更新后的认知状态 [0, 1]
        """
        signal = max(0.0, min(1.0, float(info_signal)))
        weight = max(0.0, min(1.0, float(info_weight)))

        # 简化贝叶斯更新: belief += lr × weight × (signal - belief)
        self._belief += self._lr * weight * (signal - self._belief)
        self._belief = max(0.0, min(1.0, self._belief))
        return self._belief

    def get_cognition(self) -> float:
        """返回当前认知状态."""
        return self._belief

    def reset(self, prior_strength: float = 0.5):
        """重置认知状态."""
        self._belief = max(0.0, min(1.0, prior_strength))
