"""
L3 ShadowRLTracker (§二 L3 高频探索层 · MVP 骨架)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §二

Phase 3 stub: 记录 (s,a,R,s') 样本 + Sharpe 计算
真实 RL 探索（Schluter gmax 变异 + Thompson sampling）在 Phase 3 启动.
"""
import numpy as np
from collections import deque
from typing import Any


class ShadowRLTracker:
    """
    L3 影子 RL 追踪器.
    MVP: 仅记录样本 + 计算 stub Sharpe.
    Phase 3: 启动 gmax 变异 + Bayesian 校准.
    """

    def __init__(self, max_samples: int = 10000):
        self._samples: deque = deque(maxlen=max_samples)
        self._phase3_activated = False

    def record(
        self,
        symbol: str,
        state: dict[str, Any],
        action: str,
        reward: float,
        next_state: dict[str, Any] | None = None,
    ) -> None:
        """记录一条 (s, a, R, s') 样本."""
        self._samples.append({
            "symbol": symbol,
            "state": dict(state) if state else {},
            "action": action,
            "reward": float(reward) if reward is not None and not (isinstance(reward, float) and (reward != reward)) else 0.0,
            "next_state": dict(next_state) if next_state else {},
        })

    def sample_count(self) -> int:
        return len(self._samples)

    def get_stats(self) -> dict[str, Any]:
        """计算 Sharpe stub + 样本统计."""
        if not self._samples:
            return {"sharpe": 0.0, "sample_count": 0, "mean_reward": 0.0, "std_reward": 0.0}
        rewards = np.array([s["reward"] for s in self._samples], dtype=np.float64)
        mean_r = float(np.mean(rewards))
        std_r = float(np.std(rewards, ddof=1)) if len(rewards) > 1 else 0.0
        sharpe = mean_r / (std_r + 1e-9) if std_r > 0 else 0.0
        return {
            "sharpe": round(sharpe, 6),
            "sample_count": len(self._samples),
            "mean_reward": round(mean_r, 6),
            "std_reward": round(std_r, 6),
        }

    def is_phase3_activated(self) -> bool:
        return self._phase3_activated

    def activate_phase3(self) -> None:
        """Phase 3 启动后调用（样本≥2000 + PR 评审通过）."""
        self._phase3_activated = True
