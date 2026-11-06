"""C→D 矛盾维度影子映射（B-01 / DEC-11）.

生产裁决仍使用 C（路径来源）维度；本模块只提供 D（真实市场维度）影子标签，
用于 shadow 对比，不改变 `dimension` 或任何裁决字段。

映射口径（SPEC §2.6.2）:
  C1 资金面 → D2 资金流
  C2 情绪面 → D4 市场情绪
  C3 技术面 → D3 技术
  C4 宏观   → D1 宏观利率
  C6/C7/C8 保留同名；news → NEWS
"""
from __future__ import annotations

from typing import Any

MAPPING_VERSION = "cd-v1"

C_TO_D_MAP = {
    "C1": "D2",
    "C2": "D4",
    "C3": "D3",
    "C4": "D1",
    "C6": "C6",
    "C7": "C7",
    "C8": "C8",
    "news": "NEWS",
}

D_DIMENSIONS = ("D1", "D2", "D3", "D4", "C6", "C7", "C8", "NEWS")


def map_c_to_d(c_dim: Any) -> str | None:
    """C 维度 → D 维度；未知/非法输入返回 None（FAIL-OPEN）。"""
    if not isinstance(c_dim, str):
        return None
    return C_TO_D_MAP.get(c_dim.strip())


def build_shadow(
    c_dim: Any,
    *,
    direction: Any = None,
    strength: Any = None,
    **extra: Any,
) -> dict:
    """构造影子字段；只读、无副作用。"""
    d_dim = map_c_to_d(c_dim)
    payload = {
        "c_dimension": c_dim if isinstance(c_dim, str) else None,
        "d_dimension": d_dim,
        "mapped": d_dim is not None,
        "mapping_version": MAPPING_VERSION,
        "direction": direction,
        "strength": strength,
    }
    payload.update(extra)
    return payload


def attach_shadow(primary: Any, *, enabled: bool) -> Any:
    """按开关给主矛盾 dict 附加 `dimension_shadow`；不改变 `dimension`。

    enabled=False 或输入非 dict 时原样返回（FAIL-OPEN）。
    """
    if not enabled or not isinstance(primary, dict):
        return primary
    primary["dimension_shadow"] = build_shadow(
        primary.get("dimension"),
        direction=primary.get("direction"),
        strength=primary.get("strength"),
    )
    return primary