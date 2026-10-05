"""E7-A2 信号有效性检验: 外生特征对短期收益的预测增量.

数据: 19-DAL 2026-09-21 ~ 2026-10-05 (328 小时点)
  - 价格: market_cap_usd / circulating_supply
  - 外生: stablecoin supply 变化(funding代理), TVL变化(dxy代理),
          ex_bal(exchange_net_flow), CPI/rate_prob/etf_flow(快照)

方法: 滚动窗口 MLP 回归, 对比
  - Model A: 仅价格特征 (滞后收益, 波动率, ma)
  - Model B: 价格特征 + 9 维外生力量

指标: MAE, out-of-sample R², 有/无外生的差异
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
DAL_DIR = REPO.parent / "19-数据访问层"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(DAL_DIR) not in sys.path:
    sys.path.insert(0, str(DAL_DIR))
os.environ.setdefault("DATA_DIR", str(DAL_DIR / "data"))

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from dreambuddy_dal import get_market_macro_repo  # noqa: E402
from dreambuddy_evolution.core.exogenous_data_bridge import build_exogenous_series  # noqa: E402


def load_data():
    repo = get_market_macro_repo(backend="sqlite_unified")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 12, 31, tzinfo=timezone.utc)

    cap_rows = repo.query_metric_by_time("btc_basics", "market_cap_usd", start, end)
    cap_ts = np.array([r[3].timestamp() for r in cap_rows])
    cap_vals = np.array([float(r[2]) for r in cap_rows])
    cur_supply = 20_081_181.0
    prices_raw = cap_vals / cur_supply
    valid = np.isfinite(prices_raw) & (prices_raw > 1000)
    cap_ts, prices_raw = cap_ts[valid], prices_raw[valid]
    hour_ts = np.arange(cap_ts.min(), cap_ts.max() + 1, 3600)
    prices = np.interp(hour_ts, cap_ts, prices_raw)

    # 时变外生
    sc_rows = repo.query_metric_by_time("stablecoins_top_10", "total_circulating_usd_bln", start, end)
    sc_ts = np.array([r[3].timestamp() for r in sc_rows])
    sc_vals = np.array([float(r[2]) for r in sc_rows])
    sc_aligned = np.interp(hour_ts, sc_ts, sc_vals, left=sc_vals[0], right=sc_vals[-1])
    sc_pct = np.zeros_like(sc_aligned)
    sc_pct[1:] = (sc_aligned[1:] - sc_aligned[:-1]) / np.maximum(sc_aligned[:-1], 1e-9)
    funding_proxy = -sc_pct * 100.0

    tvl_rows = repo.query_metric_by_time("all_protocols", "total_tvl_bln", start, end)
    tvl_ts = np.array([r[3].timestamp() for r in tvl_rows])
    tvl_vals = np.array([float(r[2]) for r in tvl_rows])
    tvl_aligned = np.interp(hour_ts, tvl_ts, tvl_vals, left=tvl_vals[0], right=tvl_vals[-1])
    tvl_pct = np.zeros_like(tvl_aligned)
    tvl_pct[1:] = (tvl_aligned[1:] - tvl_aligned[:-1]) / np.maximum(tvl_aligned[:-1], 1e-9)
    dxy_proxy = -tvl_pct

    exbal_rows = repo.query_metric_by_time("exchanges_whales", "ex_bal_BTC_chg30d_pct", start, end)
    exbal_ts = np.array([r[3].timestamp() for r in exbal_rows])
    exbal_vals = np.array([float(r[2]) for r in exbal_rows])
    exbal_aligned = np.interp(hour_ts, exbal_ts, exbal_vals, left=exbal_vals[0], right=exbal_vals[-1])

    snapshot = {}
    for sub, metric, key in [("cpi", "actual", "cpi_actual"), ("cpi", "forecast", "cpi_expected"),
                              ("fedwatch", "hike_prob", "rate_hike_prob"), ("etf_flow", "total_flow", "etf_net_flow")]:
        row = repo.query_latest_metric(sub, metric)
        if row is not None and row[1] is not None:
            snapshot[key] = float(row[1])
    fomc = repo.query_latest_metric("fomc_decision", "rate_change")
    if fomc is not None and fomc[1] is not None:
        rc = float(fomc[1])
        snapshot["monetary_cycle"] = "easing" if rc < 0 else ("tightening" if rc > 0 else "neutral")

    per_point_data = []
    for i in range(len(prices)):
        d = dict(snapshot)
        d["funding_rate"] = float(funding_proxy[i])
        d["exchange_net_flow"] = -float(exbal_aligned[i]) * 10.0
        d["dxy_change_pct"] = float(dxy_proxy[i])
        per_point_data.append(d)

    return prices, per_point_data, hour_ts


def build_price_features(prices, lookback=10):
    """构建价格特征: 滞后收益, 波动率, ma偏离."""
    n = len(prices)
    rets = np.diff(np.log(prices))
    feats = np.zeros((n, lookback + 2))
    for i in range(lookback, n):
        for j in range(lookback):
            feats[i, j] = rets[i - j - 1] if i - j - 1 >= 0 else 0.0
        feats[i, lookback] = np.std(rets[max(0, i - 10):i]) if i > 0 else 0.0
        ma = np.mean(prices[max(0, i - 20):i + 1])
        feats[i, lookback + 1] = (prices[i] - ma) / ma if ma > 0 else 0.0
    return feats


def rolling_mlp_eval(X, y, train_ratio=0.7, n_trials=5):
    """滚动训练 MLP, 返回 OOS MAE 和 R²."""
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler

    n = len(X)
    train_end = int(n * train_ratio)
    maes, r2s = [], []
    for trial in range(n_trials):
        rng = np.random.RandomState(42 + trial)
        perm = rng.permutation(train_end)
        Xtr, ytr = X[:train_end][perm], y[:train_end][perm]
        Xte, yte = X[train_end:], y[train_end:]

        scaler = StandardScaler()
        Xtr_s = scaler.fit_transform(Xtr)
        Xte_s = scaler.transform(Xte)

        model = MLPRegressor(
            hidden_layer_sizes=(16, 8), activation="relu",
            alpha=0.01, max_iter=500, random_state=42 + trial,
            early_stopping=True, validation_fraction=0.1,
        )
        model.fit(Xtr_s, ytr)
        pred = model.predict(Xte_s)
        mae = float(np.mean(np.abs(pred - yte)))
        ss_res = float(np.sum((yte - pred) ** 2))
        ss_tot = float(np.sum((yte - np.mean(yte)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        maes.append(mae)
        r2s.append(r2)
    return float(np.mean(maes)), float(np.mean(r2s))


def main():
    prices, per_point_data, hour_ts = load_data()
    n = len(prices)
    logger.info("数据: %d 点, 价格范围 %.0f~%.0f, 时间 %s~%s",
                n, prices.min(), prices.max(),
                datetime.fromtimestamp(hour_ts[0], tz=timezone.utc).strftime("%Y-%m-%d"),
                datetime.fromtimestamp(hour_ts[-1], tz=timezone.utc).strftime("%Y-%m-%d"))

    # 目标: 下一期收益
    rets = np.zeros(n)
    rets[1:] = np.diff(np.log(prices))
    y = rets.copy()

    # 价格特征
    X_price = build_price_features(prices, lookback=10)

    # 外生特征 (9 维)
    exo = build_exogenous_series(prices, bridge=None, per_point_data=per_point_data)
    logger.info("外生特征 shape: %s", exo.shape)

    # 合并
    X_full = np.hstack([X_price, exo])

    # 对齐 (去掉前 lookback 个无效点)
    valid_start = 10
    X_p = X_price[valid_start:]
    X_f = X_full[valid_start:]
    y_v = y[valid_start:]

    logger.info("有效样本: %d", len(y_v))
    logger.info("目标收益 std: %.6f", np.std(y_v))

    # Model A: 仅价格特征
    mae_a, r2_a = rolling_mlp_eval(X_p, y_v)
    logger.info("Model A (仅价格): MAE=%.6f, R²=%.4f", mae_a, r2_a)

    # Model B: 价格 + 外生
    mae_b, r2_b = rolling_mlp_eval(X_f, y_v)
    logger.info("Model B (价格+外生): MAE=%.6f, R²=%.4f", mae_b, r2_b)

    delta_mae = (mae_b - mae_a) / mae_a * 100
    delta_r2 = r2_b - r2_a

    logger.info("=" * 60)
    logger.info("=== A2 信号有效性检验 ===")
    logger.info("Model A (仅价格):    MAE=%.6f, R²=%.4f", mae_a, r2_a)
    logger.info("Model B (价格+外生):  MAE=%.6f, R²=%.4f", mae_b, r2_b)
    logger.info("MAE 变化: %+.2f%%", delta_mae)
    logger.info("R² 变化:  %+.4f", delta_r2)
    if delta_mae < -1.0:
        logger.info("结论: 外生特征有正向贡献 (MAE 降低 >1%%)")
    elif delta_mae > 1.0:
        logger.info("结论: 外生特征有负向贡献 (MAE 升高 >1%%)")
    else:
        logger.info("结论: 外生特征贡献不显著 (|MAE 变化| ≤ 1%%)")

    out = {
        "tdd": "E7-A2-signal-validity-test",
        "data": {
            "n_points": n,
            "time_range": [
                datetime.fromtimestamp(hour_ts[0], tz=timezone.utc).isoformat(),
                datetime.fromtimestamp(hour_ts[-1], tz=timezone.utc).isoformat(),
            ],
            "price_range": [float(prices.min()), float(prices.max())],
            "target_std": float(np.std(y_v)),
        },
        "model_a": {"mae": round(mae_a, 6), "r2": round(r2_a, 4), "features": "price only (12)"},
        "model_b": {"mae": round(mae_b, 6), "r2": round(r2_b, 4), "features": "price + exogenous 9 (21)"},
        "comparison": {
            "delta_mae_pct": round(delta_mae, 4),
            "delta_r2": round(delta_r2, 4),
        },
    }
    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p1_exogenous_signal_validity.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
