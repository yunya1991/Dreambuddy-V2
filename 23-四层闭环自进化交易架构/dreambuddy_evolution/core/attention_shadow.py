"""B-03 / DEC-??: Attention A_dim 影子对比（torch-free）.

从最新一次 cross-attention 的 `last_attn_weights` 聚合出 `A_dim_attention`，
与主矛盾识别器的 `A_dim_identifier` 做 shadow 对比。

设计:
  - 不要求在本地安装 torch：支持 nested list / numpy / torch tensor（有 `tolist` 即可）
  - 权重缓存由 `neural_sde_model` 在 cross-attn 后写入；无权重时 `available=False`
  - 只读诊断，不改变生产裁决
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from dreambuddy_evolution.core.dimension_mapping import (
    C_DIM_TO_3,
    DEFAULT_C_DIMENSIONS,
    THREE_DIMS,
    c_dim_to_three,
)

logger = logging.getLogger(__name__)

METHOD_VERSION = "attention-a-dim-shadow-v1"

# 最新一次 cross-attention 权重缓存（单进程）
_LAST_ATTN_WEIGHTS: Any = None


def record_last_attn_weights(weights: Any) -> None:
    """记录最新 attention weights（由 neural_sde_model 在 cross-attn 后调用）."""
    global _LAST_ATTN_WEIGHTS
    _LAST_ATTN_WEIGHTS = weights


def get_last_attn_weights() -> Any:
    return _LAST_ATTN_WEIGHTS


def clear_last_attn_weights() -> None:
    global _LAST_ATTN_WEIGHTS
    _LAST_ATTN_WEIGHTS = None


def _as_nested_list(weights: Any) -> Any:
    if weights is None:
        return None
    if hasattr(weights, "detach"):
        weights = weights.detach()
    if hasattr(weights, "cpu"):
        weights = weights.cpu()
    if hasattr(weights, "tolist"):
        return weights.tolist()
    return weights


def _head_strengths(weights: Any) -> list[float]:
    """把 (B,H,1,N)/(B,H,N)/(H,N)/(H) 归一化为每 head 的强度和."""
    data = _as_nested_list(weights)
    if data is None:
        raise ValueError("attention weights is None")
    if not isinstance(data, (list, tuple)) or not data:
        raise ValueError("attention weights is empty")

    first = data[0]
    # (H,) —— 已是一个样本的 head 强度
    if not isinstance(first, (list, tuple)):
        return [float(value) for value in data]

    # (B,H,N) / (B,H,1,N)
    if isinstance(first[0], (list, tuple)):
        # 取 batch 0；若 batch > 1 则仍取 batch 0，保持与 AttentionAggregator 单样本语义一致
        per_head = data[0]
        strengths = []
        for head in per_head:
            if isinstance(head, (list, tuple)):
                # (1,N) 或 (N,)
                if head and isinstance(head[0], (list, tuple)):
                    values = head[0]
                else:
                    values = head
                strengths.append(sum(float(value) for value in values))
            else:
                strengths.append(float(head))
        return strengths

    # (H,N)
    return [sum(float(value) for value in head) for head in data]


def aggregate_attention(
    weights: Any,
    dimensions: Optional[Iterable[str]] = None,
) -> dict:
    """聚合 attention weights 到 3 维度；FAIL-OPEN 返回 available=False."""
    try:
        if dimensions is None:
            dimensions = DEFAULT_C_DIMENSIONS
        dimensions = list(dimensions)
        strengths = _head_strengths(weights)
        if len(strengths) != len(dimensions):
            raise ValueError(
                f"n_heads={len(strengths)} 与 dimensions 长度 {len(dimensions)} 不匹配"
            )
        dim_strengths = dict.fromkeys(THREE_DIMS, 0.0)
        for head_index, c_dim in enumerate(dimensions):
            target = C_DIM_TO_3.get(c_dim)
            if target:
                dim_strengths[target] += max(0.0, float(strengths[head_index]))
        total = sum(dim_strengths.values())
        if total > 0:
            dim_strengths = {key: value / total for key, value in dim_strengths.items()}
        else:
            dim_strengths = {key: 1.0 / len(THREE_DIMS) for key in THREE_DIMS}
        a_dim = max(dim_strengths, key=dim_strengths.get)
        return {
            "available": True,
            "A_dim": a_dim,
            "A_strength": dim_strengths[a_dim],
            "dim_strengths": dim_strengths,
            "n_heads": len(strengths),
            "method": METHOD_VERSION,
        }
    except Exception as exc:  # noqa: BLE001 — shadow 层 FAIL-OPEN
        return {
            "available": False,
            "A_dim": None,
            "A_strength": 0.0,
            "dim_strengths": dict.fromkeys(THREE_DIMS, 0.0),
            "error": f"{type(exc).__name__}: {exc}",
            "method": METHOD_VERSION,
        }


def compute_a_dim_shadow(
    primary_contradiction: Any,
    *,
    attn_weights: Any = None,
    dimensions: Optional[Iterable[str]] = None,
) -> dict:
    """对比 identifier A_dim 与 attention A_dim；只读、FAIL-OPEN."""
    primary = primary_contradiction if isinstance(primary_contradiction, dict) else {}
    c_dim = primary.get("dimension")
    a_dim_identifier = c_dim_to_three(c_dim)
    weights = attn_weights if attn_weights is not None else get_last_attn_weights()
    agg = aggregate_attention(weights, dimensions=dimensions)
    a_dim_attention = agg.get("A_dim")
    both_available = bool(a_dim_identifier and a_dim_attention)
    return {
        "method": METHOD_VERSION,
        "shadow_only": True,
        "available": bool(agg.get("available")),
        "c_dimension": c_dim,
        "a_dim_identifier": a_dim_identifier,
        "a_dim_attention": a_dim_attention,
        "agreement": (a_dim_identifier == a_dim_attention) if both_available else None,
        "a_strength_attention": agg.get("A_strength", 0.0),
        "dim_strengths": agg.get("dim_strengths", {}),
        "reason": agg.get("error"),
    }
