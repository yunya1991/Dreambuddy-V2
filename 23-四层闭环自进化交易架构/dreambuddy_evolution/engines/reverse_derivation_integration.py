"""ReverseDerivationIntegration — 逆向推导数据源集成层。

将 PrimaryContradictionIdentifier 的 paths 和 cross_attention 的 last_attn_weights
转换为 ReverseDeriver 所需的 dimension_predictions 和 attention_weights。

SPEC §3.1 数据来源:
- dimension_predictions: 从 identify() 输入 paths 提取每路径 direction，
  经 SOURCE_DIM_MAP 映射到维度
- attention_weights: 来自 cross_attention 的 last_attn_weights
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 路径来源 → 矛盾维度映射（与 PrimaryContradictionIdentifier.SOURCE_DIM_MAP 一致）
SOURCE_DIM_MAP = {
    "bdsm": "C1",
    "trend_following": "C2",
    "grid_trading": "C2",
    "bcrm": "C3",
    "strategic": "C4",
    "deep_reasoning": "C6",
    "synthesized": "C7",
    "l2_gene": "C8",
}


def extract_dimension_predictions(paths: Any) -> dict[str, str]:
    """从 PrimaryContradictionIdentifier.identify() 的输入 paths 提取每维度方向。

    每个 path 须含 source(或 name) 和 direction 字段。
    同一维度多个路径时，取最后一个 path 的 direction。

    Args:
        paths: list[dict]，如 [{"source": "bdsm", "direction": "long"}, ...]

    Returns:
        {维度: 方向}，如 {"C1": "long", "C3": "short"}
        无效输入时 FAIL-OPEN 返回 {}
    """
    try:
        if not isinstance(paths, (list, tuple)):
            return {}

        dim_predictions: dict[str, str] = {}
        for path in paths:
            if not isinstance(path, dict):
                continue
            source = path.get("source") or path.get("name")
            direction = path.get("direction")
            if not source or not direction:
                continue
            dim = SOURCE_DIM_MAP.get(str(source).lower())
            if dim:
                dim_predictions[dim] = str(direction).lower()
        return dim_predictions
    except Exception as e:
        logger.warning("[FO] extract_dimension_predictions fail: %s", e)
        return {}


def extract_attention_weights(last_attn_weights: Any) -> list[float]:
    """从 MultiHeadCrossAttention.last_attn_weights 提取维度注意力权重。

    last_attn_weights shape: (B, n_heads, 1, N)，N=因子数。
    跨 batch 和 head 平均，得到每因子的平均注意力权重。

    Args:
        last_attn_weights: torch.Tensor 或 None 或 list

    Returns:
        list[float]，长度为 N；无效输入时 FAIL-OPEN 返回 []
    """
    try:
        if last_attn_weights is None:
            return []

        # 已经是 list → 直接返回
        if isinstance(last_attn_weights, list):
            return [float(w) for w in last_attn_weights]

        # torch.Tensor → 跨 batch 和 head 平均
        if hasattr(last_attn_weights, "dim"):
            tensor = last_attn_weights
            # squeeze 掉 query 维度 (B, n_heads, 1, N) → (B, n_heads, N)
            if tensor.dim() == 4:
                tensor = tensor.squeeze(2)
            # 跨 batch(dim=0) 和 head(dim=1) 平均 → (N,)
            mean_weights = tensor.mean(dim=(0, 1))
            return [round(float(w), 6) for w in mean_weights.tolist()]

        return []
    except Exception as e:
        logger.warning("[FO] extract_attention_weights fail: %s", e)
        return []
