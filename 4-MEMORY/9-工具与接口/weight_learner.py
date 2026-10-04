"""N-P1a 权重学习 — Bradley-Terry 模型 + 同源降权。

文档要求：权重由数据驱动（Bradley-Terry），不能手工设定。

核心机制：
1. 冷启动：所有验证器强度 θ=1.0（等权）
2. 在线迭代：pass 的验证器 θ 上升，fail 的下降
3. 同源降权：高度正相关的验证器对被降权（避免同源信号重复计权）
4. 权重版本：每次更新递增版本号，保留历史
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class WeightVersion:
    """权重版本记录。"""
    version_id: int
    weights: Dict[str, float]
    ts: float = field(default_factory=time.time)
    reason: str = ""


class BradleyTerryLearner:
    """Bradley-Terry 在线权重学习器。

    每个验证器有强度 θ_i，权重 = θ_i / Σθ_j。
    pass → θ 上升；fail → θ 下降；abstain → 不变。
    """

    def __init__(
        self,
        stages: List[str],
        learning_rate: float = 0.1,
        min_strength: float = 0.01,
    ):
        self._stages = list(stages)
        self._lr = learning_rate
        self._min_strength = min_strength
        self._strength: Dict[str, float] = {s: 1.0 for s in stages}
        self._version_id = 0
        self._history: List[WeightVersion] = [
            WeightVersion(version_id=0, weights=self.get_weights(), reason="init")
        ]
        # 记录 verdict 历史（用于相关性计算）
        self._history_verdicts: Dict[str, List[int]] = {s: [] for s in stages}

    @property
    def version(self) -> WeightVersion:
        return self._history[-1]

    def get_weights(self) -> Dict[str, float]:
        """返回归一化权重（和为 len(stages)，均值为 1）。"""
        total = sum(self._strength.values())
        if total <= 0:
            return {s: 1.0 for s in self._stages}
        n = len(self._stages)
        return {s: (self._strength[s] / total) * n for s in self._stages}

    def update(self, verdicts: Dict[str, str]) -> None:
        """根据一次 verify 结果更新强度。

        verdicts: {stage: "pass"/"fail"/"abstain"}
        """
        changed = False
        for stage, verdict in verdicts.items():
            if stage not in self._strength:
                continue
            if verdict == "abstain":
                self._history_verdicts[stage].append(0)  # abstain = 0
                continue
            elif verdict == "pass":
                self._strength[stage] *= (1.0 + self._lr)
                self._history_verdicts[stage].append(1)
                changed = True
            elif verdict == "fail":
                self._strength[stage] = max(
                    self._min_strength,
                    self._strength[stage] * (1.0 - self._lr),
                )
                self._history_verdicts[stage].append(-1)
                changed = True

        if changed:
            self._bump_version(reason="online_update")

    def apply_correlation_downweighting(
        self,
        correlation_threshold: float = 0.7,
        downweight_factor: float = 0.5,
    ) -> None:
        """同源降权：对高度正相关的验证器对降权。

        correlation_threshold: 相关系数阈值（默认 0.7）
        downweight_factor: 降权系数（默认 0.5，即相关对各乘 0.5）
        """
        stages = list(self._strength.keys())
        # 计算 Pearson 相关系数矩阵
        correlations: Dict[str, Dict[str, float]] = {}
        for i, s1 in enumerate(stages):
            correlations[s1] = {}
            for s2 in stages:
                if s1 == s2:
                    correlations[s1][s2] = 1.0
                    continue
                correlations[s1][s2] = self._pearson(s1, s2)

        # 找出高度正相关的验证器
        downweighted: set = set()
        for i, s1 in enumerate(stages):
            for s2 in stages[i + 1:]:
                if correlations[s1].get(s2, 0.0) >= correlation_threshold:
                    downweighted.add(s1)
                    downweighted.add(s2)

        if not downweighted:
            return

        for s in downweighted:
            self._strength[s] *= downweight_factor

        self._bump_version(reason=f"correlation_downweight({correlation_threshold})")

    def _pearson(self, s1: str, s2: str) -> float:
        """计算两个验证器 verdict 历史的 Pearson 相关系数。"""
        h1 = self._history_verdicts.get(s1, [])
        h2 = self._history_verdicts.get(s2, [])
        n = min(len(h1), len(h2))
        if n < 2:
            return 0.0
        h1 = h1[-n:]
        h2 = h2[-n:]
        mean1 = sum(h1) / n
        mean2 = sum(h2) / n
        cov = sum((a - mean1) * (b - mean2) for a, b in zip(h1, h2)) / n
        std1 = (sum((a - mean1) ** 2 for a in h1) / n) ** 0.5
        std2 = (sum((b - mean2) ** 2 for b in h2) / n) ** 0.5
        if std1 == 0 or std2 == 0:
            return 0.0
        return cov / (std1 * std2)

    def _bump_version(self, reason: str = "") -> None:
        self._version_id += 1
        self._history.append(WeightVersion(
            version_id=self._version_id,
            weights=self.get_weights(),
            reason=reason,
        ))

    def version_history(self) -> List[WeightVersion]:
        return list(self._history)

    def export_params(self) -> Dict[str, Any]:
        return {
            "stages": self._stages,
            "strength": dict(self._strength),
            "learning_rate": self._lr,
            "min_strength": self._min_strength,
            "version_id": self._version_id,
        }

    def import_params(self, params: Dict[str, Any]) -> None:
        self._stages = list(params.get("stages", self._stages))
        self._strength = {s: float(v) for s, v in params.get("strength", {}).items()}
        self._lr = float(params.get("learning_rate", self._lr))
        self._min_strength = float(params.get("min_strength", self._min_strength))
        self._version_id = int(params.get("version_id", 0))
