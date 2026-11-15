# -*- coding: utf-8 -*-
"""L1-X 相关性簇敞口（SPEC-54 §4.10 第 12 条 / L1X-04 / V-AC21）。

口径：
  - 簇由 **D-E05 相关矩阵**做确定性并查集聚类（`|ρ| ≥ 0.70` 视为同簇，不调外部库）；
  - 同簇敞口（含新单）不得超过「含新单总敞口」的 `cluster_exposure_cap_pct=0.50`；
  - 越界返回 `reject_reason="cluster_exposure"`，由 `risk` 统一拒单落账。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from . import risk

CLUSTER_THRESHOLD = 0.7
CLUSTER_CAP_PCT = 0.50


def _find(parent: Sequence[int], index: int) -> int:
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def clusters(
    names: Sequence[str],
    matrix: Sequence[Sequence[Optional[float]]],
    *,
    threshold: float = CLUSTER_THRESHOLD,
) -> Dict[str, str]:
    """D-E05 矩阵 → `{symbol: cluster_id}`；簇 ID 按 `names` 首次出现顺序编号 `c1`。"""
    total = len(names)
    if total != len(matrix):
        raise ValueError("names 与 matrix 维度不一致")
    parent = list(range(total))
    for i in range(total):
        row = matrix[i]
        if len(row) != total:
            raise ValueError("matrix 必须是方阵")
        for j in range(i + 1, total):
            rho = row[j]
            if rho is None:
                continue
            if abs(float(rho)) >= float(threshold):
                ri, rj = _find(parent, i), _find(parent, j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)
    labels: Dict[int, str] = {}
    out: Dict[str, str] = {}
    for index, name in enumerate(names):
        root = _find(parent, index)
        if root not in labels:
            labels[root] = f"c{len(labels) + 1}"
        out[str(name)] = labels[root]
    return out


def cluster_exposure(
    symbol: str, exposures: Mapping[str, float], mapping: Mapping[str, str]
) -> float:
    """该标的所在簇的当前敞口合计（未登记映射的标的自成单簇）。"""
    cluster = mapping.get(symbol) or symbol
    total = 0.0
    for name, value in exposures.items():
        if (mapping.get(name) or name) == cluster:
            total += abs(float(value))
    return round(total, 8)


def check_cluster_exposure(
    *,
    symbol: str,
    notional_usdt: float,
    exposures: Mapping[str, float],
    mapping: Mapping[str, str],
    cap_pct: float = CLUSTER_CAP_PCT,
) -> Dict[str, Any]:
    """同簇敞口（含新单）占比闸门；返回 `{allowed, reject_reason, ratio, ...}`。"""
    cluster = mapping.get(symbol) or symbol
    cluster_now = cluster_exposure(symbol, exposures, mapping)
    gross_now = round(sum(abs(float(v)) for v in exposures.values()), 8)
    cluster_after = round(cluster_now + float(notional_usdt), 8)
    gross_after = round(gross_now + float(notional_usdt), 8)
    ratio = cluster_after / gross_after if gross_after > 0 else 0.0
    allowed = ratio <= float(cap_pct) + 1e-9
    return {
        "allowed": allowed,
        "reject_reason": None if allowed else risk.CLUSTER_EXPOSURE,
        "cluster": cluster,
        "cluster_exposure_usdt": cluster_after,
        "gross_exposure_usdt": gross_after,
        "ratio": round(ratio, 6),
        "cap_pct": float(cap_pct),
    }


__all__ = [
    "CLUSTER_CAP_PCT",
    "CLUSTER_THRESHOLD",
    "check_cluster_exposure",
    "cluster_exposure",
    "clusters",
]
