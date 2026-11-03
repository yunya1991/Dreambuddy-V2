#!/usr/bin/env python3
"""run_ablation.py — 对云端壳轨迹做 S1 签名消融，产出门禁兼容的 ablation_result.json

SPEC §4.6.13：本地训练→云端感知闭环的中间环节。
输入 trajectories_cloud.jsonl（每行一条壳轨迹 entry），输出 ablation_result.json：
  {f1_pass, f2_pass, mae_baseline, mae_full, improvement_pct, p_value, n_samples, domains, generated_at}

F1: (MAE_baseline - MAE_full) / MAE_baseline >= 10%
F2: 200 次置换签名特征块，真实 full MAE 低于 95% 随机置换分位（p < 0.05）

硬约束：
  T1 零训练——Ridge 闭式解
  T2 无 look-ahead——walk-forward，目标用下一 bin
  T3 FAIL-OPEN——样本/窗口不足 → f1_pass=f2_pass=false，不抛错
  不联网、不读云端，纯本地消费已拉取的轨迹文件
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.temporal_signature_extractor import (  # noqa: E402
    TemporalSignatureExtractor,
)

BIN_MINUTES = 60
WINDOW = 8  # 滚动窗口 bin 数
N_FOLDS = 5
N_PERM = 200
RANDOM_SEED = 20261103
F1_THRESHOLD = 0.10  # 改善 ≥ 10%
F2_ALPHA = 0.05
RIDGE_ALPHA = 1.0
MIN_SAMPLES = 20  # 至少 20 个样本才跑评估

SIGNALS = ("poe_score", "latency_ms")


def _parse_rows(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append(
                {
                    "ts": float(e.get("ts", 0.0) or 0.0),
                    "domain": str(e.get("agent_domain", "") or ""),
                    "poe": float(e.get("poe_score", 0.0) or 0.0),
                    "latency": float((e.get("cost") or {}).get("latency_ms", 0.0) or 0.0),
                }
            )
    return rows


def _build_bins(
    rows: List[Dict[str, Any]],
) -> Tuple[List[float], List[str], np.ndarray, np.ndarray]:
    """按 BIN_MINUTES 对齐各域序列，forward fill（limit=2）。

    返回 (bin_centers, domains, poe_grid[bin, domain], latency_grid[bin, domain])。
    """
    if not rows:
        return [], [], np.array([]), np.array([])
    min_ts = min(r["ts"] for r in rows)
    max_ts = max(r["ts"] for r in rows)
    bin_sec = BIN_MINUTES * 60.0
    start_bin = int(min_ts // bin_sec)
    end_bin = int(max_ts // bin_sec)
    n_bins = end_bin - start_bin + 1
    if n_bins <= 0:
        return [], [], np.array([]), np.array([])
    domains = sorted({r["domain"] for r in rows if r["domain"]})
    if not domains:
        return [], [], np.array([]), np.array([])

    poe_grid = np.full((n_bins, len(domains)), np.nan)
    lat_grid = np.full((n_bins, len(domains)), np.nan)
    for r in rows:
        if not r["domain"]:
            continue
        b = int(r["ts"] // bin_sec) - start_bin
        d = domains.index(r["domain"])
        if 0 <= b < n_bins:
            poe_grid[b, d] = r["poe"]
            lat_grid[b, d] = r["latency"]

    # forward fill limit 2
    def _ffill(grid: np.ndarray) -> np.ndarray:
        out = grid.copy()
        for d in range(grid.shape[1]):
            gap = 0
            last = np.nan
            for b in range(grid.shape[0]):
                v = grid[b, d]
                if np.isfinite(v):
                    last, gap = v, 0
                elif gap < 2 and np.isfinite(last):
                    out[b, d] = last
                    gap += 1
                else:
                    gap += 1
        return out

    poe_grid = _ffill(poe_grid)
    lat_grid = _ffill(lat_grid)
    bin_centers = [(start_bin + i + 0.5) * bin_sec for i in range(n_bins)]
    return bin_centers, domains, poe_grid, lat_grid


def _baseline_features(poe: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """每域 poe/latency 的 mean/std/last/slope/count → D*2*5 维。"""
    feats: List[float] = []
    for d in range(poe.shape[1]):
        for arr in (poe[:, d], lat[:, d]):
            valid = arr[np.isfinite(arr)]
            if valid.size == 0:
                feats.extend([0.0, 0.0, 0.0, 0.0, 0.0])
                continue
            x = np.arange(valid.size, dtype=np.float64)
            if valid.size >= 2:
                slope = float(np.polyfit(x, valid, 1)[0])
            else:
                slope = 0.0
            feats.extend(
                [
                    float(valid.mean()),
                    float(valid.std()) if valid.size > 1 else 0.0,
                    float(valid[-1]),
                    slope,
                    float(valid.size),
                ]
            )
    return np.asarray(feats, dtype=np.float64)


def _ridge_fit_predict(X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray) -> np.ndarray:
    """Ridge 闭式解（带截距）。零训练、无随机。"""
    if X_train.shape[0] < X_train.shape[1] + 1:
        return np.full(X_test.shape[0], float(np.mean(y_train)))
    A = np.hstack([X_train, np.ones((X_train.shape[0], 1))])
    identity = np.eye(A.shape[1])
    identity[-1, -1] = 0.0
    try:
        w = np.linalg.solve(A.T @ A + RIDGE_ALPHA * identity, A.T @ y_train)
    except np.linalg.LinAlgError:
        return np.full(X_test.shape[0], float(np.mean(y_train)))
    Xt = np.hstack([X_test, np.ones((X_test.shape[0], 1))])
    return Xt @ w


def _walk_forward_mae(X: np.ndarray, y: np.ndarray, folds: int) -> float:
    """walk-forward 5 fold：每折前 80% 训练、后 20% 测试，返回全样本 MAE。"""
    n = X.shape[0]
    if n < MIN_SAMPLES:
        return float("nan")
    preds = np.zeros(n)
    fold_size = n // folds
    for k in range(folds):
        end = min(
            n,
            (
                (k + 1) * fold_size + (n - folds * fold_size)
                if k == folds - 1
                else (k + 1) * fold_size
            ),
        )
        start = max(0, end - fold_size)
        train_end = start + int(0.8 * (end - start))
        if train_end <= 0 or end - train_end <= 0:
            continue
        Xtr, ytr = X[start:train_end], y[start:train_end]
        Xte = X[train_end:end]
        preds[train_end:end] = _ridge_fit_predict(Xtr, ytr, Xte)
    mask = np.isfinite(preds) & np.isfinite(y)
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs(preds[mask] - y[mask])))


def _make_windows(
    bin_centers: Sequence[float],
    domains: Sequence[str],
    poe_grid: np.ndarray,
    lat_grid: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """滚动窗口构造样本。返回 (X_base, X_sig, y, n_samples)。"""
    extractor = TemporalSignatureExtractor(min_steps=4)
    n_bins = len(bin_centers)
    n_domains = len(domains)
    expected_sig_dim = extractor.dimension(n_domains)
    X_base: List[np.ndarray] = []
    X_sig: List[np.ndarray] = []
    y: List[float] = []
    for t in range(WINDOW - 1, n_bins - 1):
        poe_win = poe_grid[t - WINDOW + 1 : t + 1]
        lat_win = lat_grid[t - WINDOW + 1 : t + 1]
        # 目标：下一 bin 全系统平均 poe（仅有限值）
        next_poe = poe_grid[t + 1]
        valid_next = next_poe[np.isfinite(next_poe)]
        if valid_next.size == 0:
            continue
        target = float(valid_next.mean())

        base = _baseline_features(poe_win, lat_win)

        # 构造签名提取器输入：{domain: [step, ...]}
        windows: Dict[str, List[Dict[str, Any]]] = {}
        for di, domain in enumerate(domains):
            steps = []
            for b in range(WINDOW):
                p, lat_val = poe_win[b, di], lat_win[b, di]
                if not (np.isfinite(p) and np.isfinite(lat_val)):
                    continue
                steps.append(
                    {
                        "ts": float(bin_centers[t - WINDOW + 1 + b]),
                        "poe_score": float(p),
                        "latency_ms": float(lat_val),
                        "messages_sent": 1.0,
                        "cross_domain_refs": 0.0,
                    }
                )
            if steps:
                windows[domain] = steps
        sig_res = extractor.extract(windows)
        if not sig_res.get("ready"):
            continue
        # 只保留全域就绪的窗口，保证签名向量维度一致
        if int(sig_res.get("dim", 0)) != expected_sig_dim:
            continue
        sig = np.asarray(sig_res["vector"], dtype=np.float64)

        X_base.append(base)
        X_sig.append(sig)
        y.append(target)

    if not X_base:
        return np.array([]), np.array([]), np.array([]), 0
    return (
        np.vstack(X_base),
        np.vstack(X_sig),
        np.asarray(y, dtype=np.float64),
        len(y),
    )


def run_ablation(
    rows: List[Dict[str, Any]],
    f1_threshold: float = F1_THRESHOLD,
    f2_alpha: float = F2_ALPHA,
    n_perm: int = N_PERM,
    seed: int = RANDOM_SEED,
) -> Dict[str, Any]:
    """主入口：rows 是 parse 后的轨迹列表，返回门禁兼容的结果 dict。"""
    result: Dict[str, Any] = {
        "f1_pass": False,
        "f2_pass": False,
        "mae_baseline": 0.0,
        "mae_full": 0.0,
        "improvement_pct": 0.0,
        "p_value": 1.0,
        "n_samples": 0,
        "domains": [],
        "generated_at": int(time.time()),
    }
    if not rows:
        result["reason"] = "no_rows"
        return result

    bin_centers, domains, poe_grid, lat_grid = _build_bins(rows)
    result["domains"] = domains
    if not domains or poe_grid.size == 0:
        result["reason"] = "no_domains_or_bins"
        return result

    X_base, X_sig, y, n = _make_windows(bin_centers, domains, poe_grid, lat_grid)
    result["n_samples"] = n
    if n < MIN_SAMPLES:
        result["reason"] = f"insufficient_samples:{n}<{MIN_SAMPLES}"
        return result

    X_full = np.hstack([X_base, X_sig])
    mae_base = _walk_forward_mae(X_base, y, N_FOLDS)
    mae_full = _walk_forward_mae(X_full, y, N_FOLDS)
    if not (np.isfinite(mae_base) and np.isfinite(mae_full)):
        result["reason"] = "mae_nan"
        return result
    result["mae_baseline"] = round(mae_base, 8)
    result["mae_full"] = round(mae_full, 8)
    improvement = (mae_base - mae_full) / mae_base if mae_base > 0 else 0.0
    result["improvement_pct"] = round(improvement * 100.0, 4)
    result["f1_pass"] = improvement >= f1_threshold

    # F2 置换检验：打乱签名特征块，重算 mae_full
    rng = np.random.default_rng(seed)
    perm_maes: List[float] = []
    for _ in range(n_perm):
        perm_idx = rng.permutation(X_sig.shape[0])
        X_perm = np.hstack([X_base, X_sig[perm_idx]])
        m = _walk_forward_mae(X_perm, y, N_FOLDS)
        if np.isfinite(m):
            perm_maes.append(m)
    if perm_maes:
        p_value = float(np.mean(np.asarray(perm_maes) <= mae_full))
    else:
        p_value = 1.0
    result["p_value"] = round(p_value, 6)
    result["f2_pass"] = p_value < f2_alpha
    result["perm_mae_mean"] = round(float(np.mean(perm_maes)), 8) if perm_maes else 0.0
    return result


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="对云端壳轨迹做 S1 签名消融")
    ap.add_argument(
        "--input",
        default=str(Path(__file__).parent / "data" / "trajectories_cloud.jsonl"),
        help="输入轨迹文件路径",
    )
    ap.add_argument(
        "--output",
        default=str(Path(__file__).parent / "ablation_result.json"),
        help="输出 ablation_result.json 路径",
    )
    ns = ap.parse_args()

    rows = _parse_rows(Path(ns.input))
    result = run_ablation(rows)
    out_path = Path(ns.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
