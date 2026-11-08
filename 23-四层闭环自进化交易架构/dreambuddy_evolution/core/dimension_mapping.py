"""矛盾维度映射（torch-free）.

C 子维度（C1-C8/news）→ 3 维度（technical/fundamental/macro）。
独立成模块，避免 `attention_aggregator` 的 torch 依赖影响 CV gate / shadow。
"""

from __future__ import annotations

from typing import Any

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

# 与 CROSS_ATTENTION_FACTOR_METRICS 的首次出现顺序保持一致；torch 不可用时作为降级列表。
DEFAULT_C_DIMENSIONS = ("C1", "C2", "C3", "C4", "C6", "C7", "C8", "news")


def c_dim_to_three(c_dim: Any) -> str | None:
    """C 维度 → technical/fundamental/macro；未知输入返回 None（FAIL-OPEN）。"""
    if not isinstance(c_dim, str):
        return None
    return C_DIM_TO_3.get(c_dim.strip())
