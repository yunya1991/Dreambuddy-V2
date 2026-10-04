"""Universe API 兼容层。

承接单体 universe 路由的核心计算签名，委托给 classic_pipeline.c1_universe 纯函数。
路由的 I/O（请求解析、缓存、响应格式化）保留在单体中。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from classic_pipeline.c1_universe.universe import (
    _compute_btc_corr_from_closes,
    _universe_beta_from_ret,
    _universe_pearson_corr,
    _universe_spearman_corr,
    _universe_kmeans_assign,
    _universe_ari_nmi,
)


def compute_btc_corr(
    a_close: Dict[int, float],
    b_close: Dict[int, float],
    method: str = "pearson",
    n: int = 72,
) -> Dict[str, Any]:
    """计算两个币种的 BTC 相关性。

    委托给 c1_universe._compute_btc_corr_from_closes。
    签名与单体 _universe_btc_corr_custom 的纯计算部分一致。

    Args:
        a_close: 币种 A 的收盘价 {timestamp: price}
        b_close: 币种 B 的收盘价 {timestamp: price}
        method: "pearson" 或 "spearman"
        n: 窗口大小

    Returns:
        {"corr": float | None}
    """
    return _compute_btc_corr_from_closes(a_close, b_close, method, n)


def compute_beta(x: List[float], y: List[float]) -> Optional[float]:
    """计算 Beta。"""
    import numpy as np
    return _universe_beta_from_ret(np.array(x), np.array(y))


def compute_corr(xs: List[float], ys: List[float], method: str = "pearson") -> Optional[float]:
    """计算相关性。"""
    if method == "spearman":
        return _universe_spearman_corr(xs, ys)
    return _universe_pearson_corr(xs, ys)


def kmeans_cluster(X: List[List[float]], k: int) -> List[int]:
    """K-Means 聚类。"""
    import numpy as np
    return _universe_kmeans_assign(np.array(X), k).tolist()


def ari_nmi(old_labels: List[int], new_labels: List[int]) -> Dict[str, Optional[float]]:
    """计算 ARI 和 NMI。"""
    return _universe_ari_nmi(old_labels, new_labels)
