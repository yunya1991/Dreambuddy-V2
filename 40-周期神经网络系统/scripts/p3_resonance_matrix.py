#!/usr/bin/env python3
"""P3 宏观共振矩阵（SPEC-M2 §1.2/M1）。

计算标的相对龙头 BTC 的共振系数 R(s)={corr0, lag_profile, beta, down_corr}，
并做 Granger 式检验防公共 beta 伪传导。产出 resonance_matrix.json。

R(s) 分量：
- corr0：同期日收益率 Pearson 相关系数
- lag_profile：滞后 0-5 阶的相关系数序列（用于 t_arrive 估计）
- beta：下游收益对上游收益的 OLS 回归系数（传导强度）
- down_corr：仅取两者同日都下跌样本的相关系数（下跌共振，风控更敏感）

Granger 检验（简化版）：
- 原假设：上游滞后收益对下游未来收益无增量预测力
- 用 OLS 对比受限模型（仅下游自滞后）与无限制模型（+上游滞后）的 RSS，F 检验
- p < 0.05 → 显著，t_arrive 启用；否则 t_arrive 禁用，传导降级为"宏观因子暴露"

fail-open：
- 样本不足（< 60 根）→ corr0=1.0（恒等传导），granger_p=None，degraded=resonance_fallback
- 数据拉取失败 → 该标的跳过，不阻塞全链
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# R-42-04/P1-03：DREAMBUDDY_ROOT 环境变量统一模块根路径
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
OUT = Path(_DREAMBUDDY_ROOT) / "40-周期神经网络系统" / "resonance_matrix.json"

# G10：价格唯一来源（18 统一价格源，禁止本脚本直连交易所）
sys.path.insert(0, os.path.join(_DREAMBUDDY_ROOT, "18-数据获取中心"))
from data_center.market import price_source  # noqa: E402

# 龙头（上游）+ 下游标的清单（与 p3_sector_transmission LAYERS 对齐）
ANCHOR = "BTC/USDT"
SYMBOLS = [
    "BTC/USDT",  # L1_anchor
    "ETH/USDT",
    "SOL/USDT",  # L2_major
    "AVAX/USDT",
    "LINK/USDT",
    "ADA/USDT",  # L3_growth
    "DOGE/USDT",
    "PEPE/USDT",
    "WIF/USDT",  # L4_meme
]

DAY_MS = 86400000
MIN_SAMPLES = 60  # Granger + corr 最少样本
GRANGER_LAGS = 3  # Granger 检验滞后阶数
GRANGER_ALPHA = 0.05


def fetch_daily(symbol, total=180, max_retries=3, base_delay=1.0):
    """日线收盘价（G10 统一价格源：OKX 主源 + Binance 显式 fallback）。"""
    try:
        return price_source.fetch_closes(symbol, days=total)
    except price_source.PriceSourceError as exc:
        print(f"  [fail] {symbol}: {exc}")
        return None


def _returns(closes):
    """日收益率序列（len-1）。"""
    arr = np.asarray(closes, dtype=float)
    if len(arr) < 2:
        return np.array([])
    return np.diff(arr) / arr[:-1]


def compute_resonance(upstream, downstream):
    """计算 R(s)={corr0, lag_profile, beta, down_corr}。

    Args:
        upstream: 上游（BTC）收盘价序列
        downstream: 下游标的收盘价序列

    Returns:
        dict with corr0, lag_profile, beta, down_corr, n_samples
        样本不足时返回 fail-open 值（corr0=1.0, degraded=resonance_fallback）
    """
    r_up = _returns(upstream)
    r_down = _returns(downstream)
    n = min(len(r_up), len(r_down))
    if n < MIN_SAMPLES:
        return {
            "corr0": 1.0,
            "lag_profile": [1.0],
            "beta": 1.0,
            "down_corr": 1.0,
            "n_samples": n,
            "degraded": "resonance_fallback",
        }

    # 对齐尾部
    r_up = r_up[-n:]
    r_down = r_down[-n:]

    # corr0：同期相关
    corr0 = (
        float(np.corrcoef(r_up, r_down)[0, 1]) if np.std(r_up) > 0 and np.std(r_down) > 0 else 0.0
    )

    # lag_profile：滞后 0-5 阶相关
    lag_profile = []
    for lag in range(6):
        if lag == 0:
            lag_profile.append(round(corr0, 6))
        else:
            a = r_up[:-lag] if lag < n else r_up
            b = r_down[lag:] if lag < n else r_down
            m = min(len(a), len(b))
            if m < 10:
                lag_profile.append(0.0)
            else:
                a, b = a[-m:], b[-m:]
                c = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else 0.0
                lag_profile.append(round(c, 6))

    # beta：OLS 回归 beta = cov(r_up, r_down) / var(r_up)
    var_up = np.var(r_up, ddof=1)
    beta = float(np.cov(r_up, r_down, ddof=1)[0, 1] / var_up) if var_up > 0 else 0.0

    # down_corr：仅取两者同日都下跌的样本
    down_mask = (r_up < 0) & (r_down < 0)
    if down_mask.sum() >= 5:
        down_corr = float(np.corrcoef(r_up[down_mask], r_down[down_mask])[0, 1])
    else:
        down_corr = corr0  # 下跌样本不足时回退到全样本 corr0

    return {
        "corr0": round(corr0, 6),
        "lag_profile": lag_profile,
        "beta": round(beta, 6),
        "down_corr": round(down_corr, 6),
        "n_samples": n,
    }


def granger_test(upstream, downstream, lags=GRANGER_LAGS):
    """简化 Granger 检验：上游滞后收益对下游未来收益的增量预测力。

    受限模型：r_down[t] = α + Σ β_i * r_down[t-i]
    无限制模型：r_down[t] = α + Σ β_i * r_down[t-i] + Σ γ_j * r_up[t-j]

    H0: γ_j = 0（上游无增量预测力）
    用 F 统计量：F = ((RSS_r - RSS_u)/q) / (RSS_u/(n-k))
    p 值用 F 分布近似（无 scipy 时用卡方近似 q*F ~ χ²(q)）

    Returns:
        (f_stat, p_value) 或 (None, None) 样本不足
    """
    r_up = _returns(upstream)
    r_down = _returns(downstream)
    n = min(len(r_up), len(r_down))
    if n < max(MIN_SAMPLES, lags * 3 + 5):
        return None, None

    r_up = r_up[-n:]
    r_down = r_down[-n:]

    # 构建滞后矩阵
    def _lag_matrix(series, lag):
        rows = []
        for i in range(lag, len(series)):
            rows.append(series[i - lag : i][::-1])  # [t-1, t-2, ..., t-l]
        return np.array(rows) if rows else np.empty((0, lag))

    y = r_down[lags:]
    X_down = _lag_matrix(r_down, lags)
    X_up = _lag_matrix(r_up, lags)

    if len(y) != len(X_down) or len(X_down) == 0:
        return None, None

    # 受限模型：仅下游自滞后 + 截距
    X_r = np.column_stack([np.ones(len(X_down)), X_down])
    # 无限制模型：+ 上游滞后
    X_u = np.column_stack([X_r, X_up])

    try:
        beta_r = np.linalg.lstsq(X_r, y, rcond=None)[0]
        beta_u = np.linalg.lstsq(X_u, y, rcond=None)[0]
        rss_r = float(np.sum((y - X_r @ beta_r) ** 2))
        rss_u = float(np.sum((y - X_u @ beta_u) ** 2))
    except np.linalg.LinAlgError:
        return None, None

    q = lags  # 约束数
    n_obs = len(y)
    k_u = X_u.shape[1]
    df_u = n_obs - k_u
    if rss_u <= 0 or df_u <= 0:
        return None, None

    f_stat = ((rss_r - rss_u) / q) / (rss_u / df_u)
    # 卡方近似：q * F ~ χ²(q)，p = 1 - CDF
    # 用正则化下不完全伽马函数近似 χ² CDF
    try:
        from scipy.stats import chi2

        p_value = float(1.0 - chi2.cdf(q * max(f_stat, 0.0), q))
    except ImportError:
        # 无 scipy 时用 χ²(1) 近似或保守估计
        p_value = float(math.exp(-0.5 * q * max(f_stat, 0.0))) if f_stat > 0 else 1.0

    return round(f_stat, 6), round(p_value, 6)


def main():
    now = datetime.now(timezone.utc).isoformat()
    print(f"=== p3_resonance_matrix start {now} ===")

    # 1. 拉取所有标的日线
    closes = {}
    for sym in SYMBOLS:
        try:
            c = fetch_daily(sym)
            if c is not None:
                closes[sym] = c
                print(f"  {sym}: {len(c)} bars")
            else:
                print(f"  {sym}: fetch failed (skipped)")
        except Exception as exc:  # noqa: BLE001  fail-open：单标的失败不阻塞
            print(f"  {sym}: ERROR {exc}")

    if ANCHOR not in closes:
        print("[warn] BTC anchor data missing, all R(s) fallback to identity")
        assets = {
            sym: {
                "corr0": 1.0,
                "lag_profile": [1.0],
                "beta": 1.0,
                "down_corr": 1.0,
                "n_samples": 0,
                "granger_f": None,
                "granger_p": None,
                "degraded": "resonance_fallback",
            }
            for sym in SYMBOLS
        }
    else:
        btc = closes[ANCHOR]
        assets = {}
        for sym in SYMBOLS:
            if sym not in closes:
                assets[sym] = {
                    "corr0": 1.0,
                    "lag_profile": [1.0],
                    "beta": 1.0,
                    "down_corr": 1.0,
                    "n_samples": 0,
                    "granger_f": None,
                    "granger_p": None,
                    "degraded": "resonance_fallback",
                }
                continue
            r = compute_resonance(btc, closes[sym])
            f_stat, p_val = granger_test(btc, closes[sym])
            r["granger_f"] = f_stat
            r["granger_p"] = p_val
            assets[sym] = r
            print(
                f"  {sym}: corr0={r['corr0']:.3f} beta={r['beta']:.3f} "
                f"granger_p={p_val} degraded={r.get('degraded')}"
            )

    output = {
        "generated_at": now,
        "anchor": ANCHOR,
        "min_samples": MIN_SAMPLES,
        "granger_lags": GRANGER_LAGS,
        "granger_alpha": GRANGER_ALPHA,
        "assets": assets,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"saved: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
