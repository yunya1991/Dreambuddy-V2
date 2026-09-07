"""
L4 BellmanVTracker (§二 L4 最优目标层 · MVP 骨架)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §二, §1.5.1

V(s) ← V(s) + α·(R + γ·V(s') - V(s))  (TD(0) 时序差分更新)
MVP: 纯 numpy 值迭代 + ESS 回馈 ±0.02 硬约束 (§1.6.3)
Phase 3: Bellman 完整 + 摩擦力建模
"""
from typing import Any


class BellmanVTracker:
    """
    L4 价值函数追踪器.
    MVP: TD(0) 简化版 + ESS 调整量输出.
    """

    def __init__(self, alpha: float = 0.1, gamma: float = 0.95,
                 ess_max: float = 0.02, ess_min: float = -0.02):
        self._v: dict[str, float] = {}
        self._alpha = float(alpha)
        self._gamma = float(gamma)
        self._ess_max = float(ess_max)
        self._ess_min = float(ess_min)

    def get_v(self, symbol: str) -> float:
        return self._v.get(symbol, 0.0)

    def td_update(self, symbol: str, reward: float, next_symbol: str = "") -> float:
        """
        V(s) ← V(s) + α·(R + γ·V(s') - V(s))
        返回更新后的 V(s).
        """
        v_s = self._v.get(symbol, 0.0)
        v_sp = self._v.get(next_symbol, 0.0) if next_symbol else 0.0
        td_target = reward + self._gamma * v_sp
        td_error = td_target - v_s
        v_new = v_s + self._alpha * td_error
        self._v[symbol] = v_new
        return v_new

    def get_ess_adjustment(self, symbol: str) -> float:
        """
        V(s) → ESS 调整量 (§1.6.3 硬约束 ±0.02).
        正 V → 正调整（策略有效），负 V → 负调整（策略无效）.
        """
        v = self._v.get(symbol, 0.0)
        # 线性映射: V > 0 → +ess（上限 ess_max），V < 0 → -ess（下限 ess_min）
        # 归一化: 假设 |V| ≤ 0.2 对应满 ess
        normalized = max(-1.0, min(1.0, v / 0.2))
        if normalized >= 0:
            return round(normalized * self._ess_max, 6)
        else:
            return round(normalized * abs(self._ess_min), 6)

    def get_all_v(self) -> dict[str, float]:
        return dict(self._v)
