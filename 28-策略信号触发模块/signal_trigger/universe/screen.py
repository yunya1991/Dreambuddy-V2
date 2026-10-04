"""28-策略信号触发模块 - 代币筛选 API 封装

基于 c1_universe 纯函数提供代币筛选能力：
- 筛选条件：beta 范围、相关性阈值、聚类标签
- 输入：候选币种列表 + 各币种收盘价/收益率序列
- 输出：通过筛选的币种列表 + 元信息

不调用外部数据源（_hl_*），数据由调用方提供。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np

from .universe import (
    _compute_btc_corr_from_closes,
    _universe_beta_from_ret,
    _universe_kmeans_assign,
    _universe_pair_aliases,
    _universe_pearson_corr,
    _universe_spearman_corr,
)


__all__ = [
    "screen_tokens",
    "screen_by_beta",
    "screen_by_correlation",
    "cluster_screen",
]


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        if not math.isfinite(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def screen_tokens(
    candidates: List[Dict[str, Any]],
    *,
    beta_range: Optional[Dict[str, float]] = None,
    corr_threshold: Optional[float] = None,
    corr_method: str = "pearson",
    btc_close: Optional[Dict[int, float]] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """代币筛选主入口。

    Args:
        candidates: 候选币种列表，每项形如：
            {
                "pair": "BTC/USDT",
                "close": {ts: price, ...},      # 收盘价序列
                "ret": np.ndarray,              # 收益率序列（可选，无则从 close 计算）
            }
        beta_range: {"min": 0.5, "max": 1.5}    # beta 范围过滤（可选）
        corr_threshold: 相关系数下限（与 BTC 的相关性，可选）
        corr_method: "pearson" | "spearman"
        btc_close: BTC 收盘价序列（用于计算 beta 和相关性）
        limit: 最大返回数量

    Returns:
        {
            "ok": True,
            "passed": [...],   # 通过筛选的币种
            "rejected": [...],  # 被筛掉的币种 + 原因
            "stats": {"total": n, "passed": m, "rejected": k}
        }
    """
    passed: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    if not candidates:
        return {"ok": True, "passed": [], "rejected": [], "stats": {"total": 0, "passed": 0, "rejected": 0}}

    # 规范化 close 的 key 为 int（JSON 反序列化后 key 为 str）
    def _normalize_close(d: Dict[Any, Any]) -> Dict[int, float]:
        out: Dict[int, float] = {}
        if not isinstance(d, dict):
            return out
        for k, v in d.items():
            try:
                ki = int(k)
                fv = float(v)
                if fv > 0.0 and math.isfinite(fv):
                    out[ki] = fv
            except (TypeError, ValueError):
                continue
        return out

    btc_close_norm = _normalize_close(btc_close) if btc_close else {}

    # 构造 BTC 收益率序列
    btc_ret: Optional[np.ndarray] = None
    if len(btc_close_norm) >= 12:
        ts_sorted = sorted(btc_close_norm.keys())
        btc_rets: List[float] = []
        for t0, t1 in zip(ts_sorted[:-1], ts_sorted[1:]):
            try:
                a = float(btc_close_norm.get(t0) or 0.0)
                b = float(btc_close_norm.get(t1) or 0.0)
                if a > 0.0 and b > 0.0:
                    btc_rets.append(math.log(b / a))
            except Exception:
                continue
        if len(btc_rets) >= 10:
            btc_ret = np.array(btc_rets, dtype=float)

    for item in candidates:
        pair = str(item.get("pair") or "").strip()
        if not pair:
            rejected.append({"pair": "", "reason": "missing_pair"})
            continue
        close = _normalize_close(item.get("close"))
        ret_arr = item.get("ret")
        # 若无 ret，从 close 推导
        if ret_arr is None and len(close) >= 12:
            ts_sorted = sorted(close.keys())
            rets: List[float] = []
            for t0, t1 in zip(ts_sorted[:-1], ts_sorted[1:]):
                try:
                    a = float(close.get(t0) or 0.0)
                    b = float(close.get(t1) or 0.0)
                    if a > 0.0 and b > 0.0:
                        rets.append(math.log(b / a))
                except Exception:
                    continue
            if len(rets) >= 10:
                ret_arr = np.array(rets, dtype=float)

        reasons: List[str] = []
        beta_val: Optional[float] = None
        corr_val: Optional[float] = None

        # beta 过滤
        if beta_range and isinstance(beta_range, dict):
            bmin = _safe_float(beta_range.get("min"), -math.inf)
            bmax = _safe_float(beta_range.get("max"), math.inf)
            if ret_arr is not None and btc_ret is not None:
                beta_val = _universe_beta_from_ret(btc_ret, ret_arr)
                if beta_val is None:
                    reasons.append("beta_unavailable")
                elif beta_val < bmin or beta_val > bmax:
                    reasons.append(f"beta_out_of_range:{beta_val:.3f}")
            else:
                reasons.append("beta_data_insufficient")

        # 相关性过滤（使用规范化后的 close 和 btc_close_norm）
        if corr_threshold is not None and len(btc_close_norm) >= 12:
            n_corr = min(len(close), len(btc_close_norm)) - 2
            if n_corr < 10:
                reasons.append("corr_data_insufficient")
            else:
                corr_result = _compute_btc_corr_from_closes(
                    close, btc_close_norm, method=corr_method, n=n_corr,
                )
                corr_val = corr_result.get("corr")
                if corr_val is None:
                    reasons.append("corr_unavailable")
                elif corr_val < float(corr_threshold):
                    reasons.append(f"corr_below_threshold:{corr_val:.3f}")

        if reasons:
            rejected.append({
                "pair": pair,
                "aliases": _universe_pair_aliases(pair)[:3],
                "beta": beta_val,
                "corr": corr_val,
                "reasons": reasons,
            })
        else:
            passed.append({
                "pair": pair,
                "aliases": _universe_pair_aliases(pair)[:3],
                "beta": (round(beta_val, 4) if beta_val is not None else None),
                "corr": (round(corr_val, 4) if corr_val is not None else None),
            })

    # 限制返回数量
    if len(passed) > int(limit):
        passed = passed[:int(limit)]

    return {
        "ok": True,
        "passed": passed,
        "rejected": rejected,
        "stats": {
            "total": len(candidates),
            "passed": len(passed),
            "rejected": len(rejected),
        },
    }


def screen_by_beta(
    candidates: List[Dict[str, Any]],
    btc_ret: "np.ndarray",
    beta_min: float = 0.5,
    beta_max: float = 1.5,
) -> Dict[str, Any]:
    """按 beta 范围筛选代币。"""
    return screen_tokens(
        candidates,
        beta_range={"min": beta_min, "max": beta_max},
        limit=10000,
    )


def screen_by_correlation(
    candidates: List[Dict[str, Any]],
    btc_close: Dict[int, float],
    threshold: float = 0.6,
    method: str = "pearson",
) -> Dict[str, Any]:
    """按相关性阈值筛选代币。"""
    return screen_tokens(
        candidates,
        corr_threshold=threshold,
        corr_method=method,
        btc_close=btc_close,
        limit=10000,
    )


def cluster_screen(
    candidates: List[Dict[str, Any]],
    k: int = 5,
) -> Dict[str, Any]:
    """对候选币种做 KMeans 聚类，返回聚类结果。

    Args:
        candidates: 每项含 ret (np.ndarray) 字段
        k: 聚类数

    Returns:
        {"ok": True, "labels": [...], "k": k, "n": n}
    """
    if not candidates:
        return {"ok": False, "error": "empty_candidates"}
    features: List[np.ndarray] = []
    pairs: List[str] = []
    for item in candidates:
        ret = item.get("ret")
        if ret is None:
            continue
        try:
            arr = np.array(ret, dtype=float)
            if arr.size >= 10:
                features.append(arr)
                pairs.append(str(item.get("pair") or ""))
        except Exception:
            continue
    if len(features) < k:
        return {"ok": False, "error": f"insufficient_samples:{len(features)}<{k}"}
    # 对齐长度
    min_len = min(arr.size for arr in features)
    X = np.array([arr[:min_len] for arr in features], dtype=float)
    labels = _universe_kmeans_assign(X, k)
    return {
        "ok": True,
        "pairs": pairs,
        "labels": labels.tolist(),
        "k": k,
        "n": len(features),
    }
