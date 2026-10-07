"""AttentionAggregator — 将 MultiHeadCrossAttention 的 last_attn_weights 聚合到 3 维度.

设计依据：融合方案 §8.1 + §10.2
- factor_head_mask shape = (n_heads=8, n_factors=36)，每个 head 对应一个 C 子维度
- softmax 后每个 head 的 weights 在该 head 的因子子集内归一化（sum=1）
- head 间的权重比较 = 维度间的力量比较
- head_multipliers 已在 cross_attention.py 中乘到 weights 上，此处直接使用

输出：A_dim ∈ {technical, fundamental, macro}, A_strength ∈ [0,1]
"""
from __future__ import annotations

from typing import Optional

import torch

from dreambuddy_evolution.core.exogenous_data_bridge import get_factor_dimensions

# C1-C8/news → 3 维度映射（融合方案 §6.2）
# 按 CROSS_ATTENTION_FACTOR_METRICS 中首次出现顺序：C1, C2, C3, C4, C6, C7, C8, news
C_DIM_TO_3: dict[str, str] = {
    "C1": "fundamental",
    "C2": "technical",
    "C3": "fundamental",
    "C4": "macro",
    "C6": "fundamental",
    "C7": "technical",
    "C8": "macro",
    "news": "technical",
}

THREE_DIMS = ("technical", "fundamental", "macro")


class AttentionAggregator:
    """按 head-weight 求和聚合 attention weights 到 3 维度."""

    def __init__(self, dimensions: Optional[list[str]] = None) -> None:
        """
        Args:
            dimensions: C 子维度列表，顺序与 factor_head_mask 的 head 顺序一致。
                        None 则从 get_factor_dimensions() 获取。
        """
        if dimensions is None:
            dimensions = get_factor_dimensions()
        self._dimensions = dimensions
        # 校验所有维度都有映射
        missing = [d for d in dimensions if d not in C_DIM_TO_3]
        if missing:
            raise ValueError(f"维度 {missing} 未在 C_DIM_TO_3 中定义映射")

    def collapse(self, attn_weights: torch.Tensor) -> dict:
        """聚合 attention weights 到 3 维度.

        Args:
            attn_weights: shape (B, n_heads, 1, n_factors)，softmax 后的值
                          （已包含 head_multipliers 的影响）

        Returns:
            {
                "A_dim": str,           # 主矛盾维度 ∈ {technical, fundamental, macro}
                "A_strength": float,    # 该维度占比 ∈ [0, 1]
                "dim_strengths": dict,  # {technical: ..., fundamental: ..., macro: ...} 归一化后
            }
        """
        if attn_weights.dim() != 4:
            raise ValueError(
                f"attn_weights 应为 4D (B, n_heads, 1, n_factors)，实际 {attn_weights.dim()}D"
            )
        n_heads = attn_weights.size(1)
        if n_heads != len(self._dimensions):
            raise ValueError(
                f"attn_weights 的 n_heads={n_heads} 与 dimensions 长度 {len(self._dimensions)} 不匹配"
            )

        # 每个 head 的权重求和 → 该 head 的注意力强度 (B, n_heads)
        head_strengths = attn_weights.sum(dim=-1).squeeze(-1)  # (B, n_heads)

        # 取 batch 第一行（单样本场景）
        if head_strengths.size(0) == 1:
            strengths = head_strengths[0].detach().cpu().tolist()
        else:
            # 多样本取平均
            strengths = head_strengths.mean(dim=0).detach().cpu().tolist()

        # 按 C_DIM_TO_3 聚合到 3 维度
        dim_strengths: dict[str, float] = {d: 0.0 for d in THREE_DIMS}
        for head_idx, c_dim in enumerate(self._dimensions):
            target = C_DIM_TO_3[c_dim]
            dim_strengths[target] += strengths[head_idx]

        # 归一化
        total = sum(dim_strengths.values())
        if total > 0:
            dim_strengths = {k: v / total for k, v in dim_strengths.items()}
        else:
            # FAIL-OPEN: 全零权重时均匀分布
            dim_strengths = {k: 1.0 / len(THREE_DIMS) for k in THREE_DIMS}

        a_dim = max(dim_strengths, key=dim_strengths.get)
        a_strength = dim_strengths[a_dim]

        return {
            "A_dim": a_dim,
            "A_strength": a_strength,
            "dim_strengths": dim_strengths,
        }
