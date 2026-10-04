"""N-P1a 多源加权聚合。

设计来源：千问 N-P1a 多源加权聚合方案
核心公式：p = Σ(wᵢ · vᵢ) / Σ(wᵢ)
  - vᵢ: pass=1.0, fail=0.0, abstain 不计入分母
  - wᵢ: 阶段权重，默认 1.0（等权）
  - 权重为 0 的阶段被排除（等价于 abstain）

硬约束：
- 权重非负
- 全 abstain 或总权重 0 → p=None（回退布尔路径）
- 权重缩放不变性（归一化不影响 p）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class StageWeights:
    """验证阶段权重配置。

    缺失 stage 默认权重 1.0（等权）。
    权重为 0 表示该阶段不参与聚合。
    """
    _weights: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for stage, w in self._weights.items():
            if w < 0:
                raise ValueError(f"权重不能为负: {stage}={w}")

    def get(self, stage: str) -> float:
        return self._weights.get(stage, 1.0)

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> "StageWeights":
        return cls(dict(d))

    def to_dict(self) -> Dict[str, float]:
        return dict(self._weights)


def compute_weighted_p(
    signals: List[Any],
    weights: StageWeights,
) -> Tuple[Optional[float], int, float]:
    """计算加权通过率 p = Σ(wᵢ·vᵢ) / Σ(wᵢ)。

    Args:
        signals: VerificationSignal 列表（或含 verdict/stage 的 dict）
        weights: 阶段权重配置

    Returns:
        (p, n_active, total_weight)
        - 全 abstain 或总权重 0 → p=None, n_active=0, total_weight=0
    """
    if not signals:
        return None, 0, 0.0

    weighted_pass = 0.0
    total_weight = 0.0
    n_active = 0

    for s in signals:
        # 兼容 VerificationSignal 对象或 dict
        if isinstance(s, dict):
            verdict = s.get("verdict", "abstain")
            stage = s.get("stage", "")
        else:
            verdict = getattr(s, "verdict", "abstain")
            stage = getattr(s, "stage", "")

        if verdict == "abstain":
            continue

        w = weights.get(stage)
        if w <= 0:
            continue  # 权重 0 排除

        n_active += 1
        total_weight += w
        if verdict == "pass":
            weighted_pass += w

    if total_weight <= 0:
        return None, 0, 0.0

    return weighted_pass / total_weight, n_active, total_weight
