"""E7-A2 PoC: 用 DAL 真实外生数据做近期窗口 walk-forward 对比.

数据来源: 19-数据访问层/data/dreambuddy_core.db (mm_metrics 表)
  - BTC 价格: btc_basics.market_cap_usd / circulating_supply (反推, 2026-09-21~10-05, ~260 点)
  - 真实时变外生: exchanges_whales.ex_bal_BTC_chg30d_pct (巨鲸余额变化, 链上信号)
  - 快照型外生: cpi.actual, fedwatch.hike_prob, fomc_decision.rate_change, etf_flow.total_flow

对比:
  - Config A: 无外生 (use_exogenous=False)
  - Config B: 有外生 (use_exogenous=True, exogenous_dim=9, 真实 DAL 数据)

窗口: 2026-09-21 ~ 2026-10-05 (~14 天, 约 260 小时点)
  - train: 前 70%
  - test: 后 30% (多个滚动窗口)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# 确保 DAL 在 path
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
from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer  # noqa: E402
from dreambuddy_evolution.core.garch_fallback import GARCHFallback  # noqa: E402
from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector  # noqa: E402
from dreambuddy_evolution.core.exogenous_data_bridge import build_exogenous_series  # noqa: E402


def load_dal_price_and_exogenous():
    """从 DAL 加载 BTC 价格 (反推) + 外生数据时序."""
    repo = get_market_macro_repo(backend="sqlite_unified")
    logger.info("DAL db_path: %s", repo.db_path)

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 12, 31, tzinfo=timezone.utc)

    # --- BTC 价格: market_cap_usd / circulating_supply ---
    cap_rows = repo.query_metric_by_time("btc_basics", "market_cap_usd", start, end)
    if len(cap_rows) < 50:
        logger.error("market_cap_usd 数据不足: %d 点", len(cap_rows))
        return None, None, None
    cap_ts = np.array([r[3].timestamp() for r in cap_rows])
    cap_vals = np.array([float(r[2]) for r in cap_rows])

    # circulating_supply (从 bitcoin 快照取)
    cur_supply = 20_081_181.0
    prices_raw = cap_vals / cur_supply

    # 过滤无效值 (0, NaN, Inf)
    valid = np.isfinite(prices_raw) & (prices_raw > 1000)
    cap_ts = cap_ts[valid]
    prices_raw = prices_raw[valid]
    logger.info("有效价格点: %d, range=%.0f~%.0f", len(prices_raw),
                prices_raw.min(), prices_raw.max())

    # 按小时重采样 (取每小时第一个点, 缺失前向填充)
    hour_ts = np.arange(cap_ts.min(), cap_ts.max() + 1, 3600)
    prices = np.interp(hour_ts, cap_ts, prices_raw)
    logger.info("重采样后小时价格: %d 点", len(prices))

    # --- 外生数据: 时变链上/流动性信号 (覆盖价格窗口) ---
    # 1) stablecoins_top_10.total_circulating_usd_bln → funding_rate 代理 (fundamental short)
    sc_rows = repo.query_metric_by_time(
        "stablecoins_top_10", "total_circulating_usd_bln", start, end)
    sc_ts = np.array([r[3].timestamp() for r in sc_rows])
    sc_vals = np.array([float(r[2]) for r in sc_rows])
    sc_aligned = np.interp(hour_ts, sc_ts, sc_vals,
                           left=sc_vals[0] if len(sc_vals) else 0.0,
                           right=sc_vals[-1] if len(sc_vals) else 0.0)
    # 稳定币供给变化率 → funding_rate 代理 (供给↑=流动性流入≈负funding=看涨)
    sc_pct = np.zeros_like(sc_aligned)
    sc_pct[1:] = (sc_aligned[1:] - sc_aligned[:-1]) / np.maximum(sc_aligned[:-1], 1e-9)
    funding_proxy = -sc_pct * 100.0  # 放大到 ±1% 量级, 负号: 供给↑→funding↓

    # 2) all_protocols.total_tvl_bln → dxy_change 代理 (macro long, 反向)
    tvl_rows = repo.query_metric_by_time(
        "all_protocols", "total_tvl_bln", start, end)
    tvl_ts = np.array([r[3].timestamp() for r in tvl_rows])
    tvl_vals = np.array([float(r[2]) for r in tvl_rows])
    tvl_aligned = np.interp(hour_ts, tvl_ts, tvl_vals,
                            left=tvl_vals[0] if len(tvl_vals) else 0.0,
                            right=tvl_vals[-1] if len(tvl_vals) else 0.0)
    tvl_pct = np.zeros_like(tvl_aligned)
    tvl_pct[1:] = (tvl_aligned[1:] - tvl_aligned[:-1]) / np.maximum(tvl_aligned[:-1], 1e-9)
    dxy_proxy = -tvl_pct  # TVL↑=风险偏好↑≈DXY↓

    # 3) ex_bal_BTC_chg30d_pct → exchange_net_flow (链上巨鲸流向, fundamental medium)
    exbal_rows = repo.query_metric_by_time(
        "exchanges_whales", "ex_bal_BTC_chg30d_pct", start, end)
    exbal_ts = np.array([r[3].timestamp() for r in exbal_rows])
    exbal_vals = np.array([float(r[2]) for r in exbal_rows])
    exbal_aligned = np.interp(hour_ts, exbal_ts, exbal_vals,
                              left=exbal_vals[0] if len(exbal_vals) else 0.0,
                              right=exbal_vals[-1] if len(exbal_vals) else 0.0)

    logger.info("时变外生信号:")
    logger.info("  stablecoin supply: %d 点, pct range=%.4f~%.4f", len(sc_aligned), sc_pct.min(), sc_pct.max())
    logger.info("  TVL: %d 点, pct range=%.4f~%.4f", len(tvl_aligned), tvl_pct.min(), tvl_pct.max())
    logger.info("  ex_bal: %d 点, range=%.3f~%.3f", len(exbal_aligned), exbal_aligned.min(), exbal_aligned.max())

    # --- 快照型外生 (CPI, rate_prob, etf_flow) ---
    snapshot = {}
    for sub, metric, key in [
        ("cpi", "actual", "cpi_actual"),
        ("cpi", "forecast", "cpi_expected"),
        ("fedwatch", "hike_prob", "rate_hike_prob"),
        ("etf_flow", "total_flow", "etf_net_flow"),
    ]:
        row = repo.query_latest_metric(sub, metric)
        if row is not None and row[1] is not None:
            snapshot[key] = float(row[1])

    fomc_row = repo.query_latest_metric("fomc_decision", "rate_change")
    if fomc_row is not None and fomc_row[1] is not None:
        rc = float(fomc_row[1])
        snapshot["monetary_cycle"] = "easing" if rc < 0 else ("tightening" if rc > 0 else "neutral")

    logger.info("快照型外生: %s", {k: v for k, v in snapshot.items()})

    # 构建 per_point_data: 每点 = snapshot + 时变信号
    per_point_data = []
    for i in range(len(prices)):
        d = dict(snapshot)
        # fundamental short: funding_rate 代理 (稳定币供给变化)
        d["funding_rate"] = float(funding_proxy[i])
        # fundamental medium: exchange_net_flow (巨鲸流向)
        d["exchange_net_flow"] = -float(exbal_aligned[i]) * 10.0
        # macro long: dxy_change 代理 (TVL 变化)
        d["dxy_change_pct"] = float(dxy_proxy[i])
        per_point_data.append(d)

    return prices, per_point_data, hour_ts


def evaluate_on_windows(model, closes, test_starts, regime_labels,
                         full_exo_series, n_paths=200, horizon=20):
    results = []
    for ts in test_starts:
        if ts + horizon >= len(closes):
            continue
        history = closes[:ts + 1]
        actual = closes[ts + 1:ts + 1 + horizon]
        init_price = float(history[-1])
        returns = np.diff(np.log(history))
        init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02

        garch = GARCHFallback()
        garch.estimate(returns)
        garch_paths = garch.simulate(n_paths, horizon, init_price, init_vol)
        garch_pred = np.mean(garch_paths[:, 1:], axis=0)
        garch_mae = float(np.mean(np.abs(garch_pred - actual)))

        test_regime = int(regime_labels[ts]) if regime_labels is not None else None
        exo_snap = None
        if full_exo_series is not None and ts < len(full_exo_series):
            exo_snap = np.asarray(full_exo_series[ts], dtype=np.float64).ravel()

        sde_paths = model.forecast(
            history, horizon, n_paths,
            regime=test_regime, exogenous_snapshot=exo_snap,
        )
        if sde_paths is not None:
            sde_pred = np.mean(sde_paths[:, 1:], axis=0)
            sde_mae = float(np.mean(np.abs(sde_pred - actual)))
        else:
            sde_mae = float("inf")

        ratio = sde_mae / garch_mae if garch_mae > 0 else float("inf")
        results.append({
            "start_idx": ts,
            "regime": test_regime,
            "sde_mae": round(sde_mae, 4),
            "garch_mae": round(garch_mae, 4),
            "ratio": round(ratio, 4),
        })
    return results


def train_and_eval(closes, use_exogenous, exo_series, regime_labels,
                   train_end, test_starts):
    import torch
    torch.manual_seed(42)
    model = NeuralSDEModel(
        device="cpu", n_regimes=3,
        use_moe=True, moe_routing="hard",
        dropout=0.05,
        use_exogenous=use_exogenous,
        exogenous_dim=9 if use_exogenous else 0,
    )
    trainer = NeuralSDETrainer(
        model=model, lr=1e-4, seq_len=32, horizon=20,
        batch_size=32, loss_type="return_mse",
        weight_decay=1e-4,
        patience=10, val_split=0.1,
    )
    closes_train = closes[:train_end]
    regime_train = regime_labels[:train_end] if regime_labels is not None else None
    exo_train = exo_series[:train_end] if exo_series is not None else None

    t0 = time.time()
    report = trainer.train(
        closes_train, epochs=150,
        regime_labels=regime_train,
        regime_balance="natural",
        exogenous_series=exo_train,
    )
    train_time = time.time() - t0

    results = evaluate_on_windows(
        model=model, closes=closes, test_starts=test_starts,
        regime_labels=regime_labels, full_exo_series=exo_series,
        n_paths=100, horizon=20,
    )
    return report, train_time, results


def main():
    prices, per_point_data, hour_ts = load_dal_price_and_exogenous()
    if prices is None:
        return 1

    n = len(prices)
    logger.info("=== A2 近期窗口数据 ===")
    logger.info("价格点数: %d, 范围: %.0f ~ %.0f", n, prices.min(), prices.max())
    logger.info("时间范围: %s ~ %s",
                datetime.fromtimestamp(hour_ts[0], tz=timezone.utc).strftime("%Y-%m-%d"),
                datetime.fromtimestamp(hour_ts[-1], tz=timezone.utc).strftime("%Y-%m-%d"))

    # Regime detection
    np.random.seed(42)
    detector = BTCRegimeDetector()
    regime_labels = detector.detect(prices)
    counts = np.bincount(regime_labels, minlength=3)
    logger.info("regime 分布: bull=%d chop=%d bear=%d", counts[0], counts[1], counts[2])

    # 构建外生时序 (用真实 per_point_data)
    t0 = time.time()
    exo_series = build_exogenous_series(prices, bridge=None, per_point_data=per_point_data)
    logger.info("外生时序构建: shape=%s, 耗时=%.1fs", exo_series.shape, time.time() - t0)
    non_neutral = float(np.mean(np.any(exo_series != 0.5, axis=1)))
    logger.info("非中性比例: %.3f", non_neutral)

    # Walk-forward 切分: train 70%, test 30%
    train_end = int(n * 0.7)
    # 测试窗口: 从 train_end 开始, 每 24 点一个窗口 (~每天)
    step = 24
    test_starts = [
        train_end + i * step
        for i in range((n - train_end - 20) // step)
    ]
    logger.info("Walk-forward: train=%d, test_windows=%d", train_end, len(test_starts))

    if len(test_starts) < 2:
        logger.error("测试窗口不足: %d", len(test_starts))
        return 1

    # ===== Config A: 无外生 =====
    logger.info("=== 训练 Config A (无外生) ===")
    report_a, time_a, results_a = train_and_eval(
        prices, use_exogenous=False, exo_series=None,
        regime_labels=regime_labels, train_end=train_end, test_starts=test_starts,
    )

    # ===== Config B: 有外生 =====
    logger.info("=== 训练 Config B (有外生, DAL 真实数据) ===")
    report_b, time_b, results_b = train_and_eval(
        prices, use_exogenous=True, exo_series=exo_series,
        regime_labels=regime_labels, train_end=train_end, test_starts=test_starts,
    )

    # 汇总
    def summarize(results):
        maes = [r["sde_mae"] for r in results]
        garch_maes = [r["garch_mae"] for r in results]
        ratios = [r["ratio"] for r in results]
        return {
            "mean_sde_mae": float(np.mean(maes)),
            "median_sde_mae": float(np.median(maes)),
            "mean_garch_mae": float(np.mean(garch_maes)),
            "mean_ratio": float(np.mean(ratios)),
            "max_ratio": float(np.max(ratios)),
            "n_windows": len(results),
        }

    sum_a = summarize(results_a)
    sum_b = summarize(results_b)

    logger.info("=" * 60)
    logger.info("=== A2 PoC: DAL 真实外生数据 近期窗口对比 ===")
    logger.info("Config A (无外生): MAE=%.2f, ratio=%.4f, max_ratio=%.4f",
                sum_a["mean_sde_mae"], sum_a["mean_ratio"], sum_a["max_ratio"])
    logger.info("Config B (有外生): MAE=%.2f, ratio=%.4f, max_ratio=%.4f",
                sum_b["mean_sde_mae"], sum_b["mean_ratio"], sum_b["max_ratio"])
    logger.info("GARCH:           MAE=%.2f", sum_a["mean_garch_mae"])
    delta_ratio = (sum_b["mean_ratio"] - sum_a["mean_ratio"]) / sum_a["mean_ratio"] * 100
    logger.info("ratio 变化: %+.2f%% (越负越好)", delta_ratio)
    logger.info("A 训练耗时: %.1fs, B 训练耗时: %.1fs", time_a, time_b)

    out = {
        "tdd": "E7-A2-poc-dal-exogenous-recent-window",
        "data": {
            "source": "19-DAL mm_metrics",
            "n_points": n,
            "time_range": [
                datetime.fromtimestamp(hour_ts[0], tz=timezone.utc).isoformat(),
                datetime.fromtimestamp(hour_ts[-1], tz=timezone.utc).isoformat(),
            ],
            "price_range": [float(prices.min()), float(prices.max())],
            "exogenous_signals": {
                "time_varying": ["ex_bal_BTC_chg30d_pct (chain-on whale flow)"],
                "snapshot": list(per_point_data[0].keys()),
            },
            "exo_non_neutral_ratio": round(non_neutral, 4),
        },
        "config_a": {
            "use_exogenous": False,
            "summary": {k: round(v, 4) for k, v in sum_a.items()},
            "train_final_loss": float(report_a.get("final_loss", 0)),
            "train_time_s": round(time_a, 1),
        },
        "config_b": {
            "use_exogenous": True,
            "exogenous_dim": 9,
            "summary": {k: round(v, 4) for k, v in sum_b.items()},
            "train_final_loss": float(report_b.get("final_loss", 0)),
            "train_time_s": round(time_b, 1),
        },
        "comparison": {
            "delta_ratio_pct": round(delta_ratio, 4),
            "a_mean_ratio": round(sum_a["mean_ratio"], 4),
            "b_mean_ratio": round(sum_b["mean_ratio"], 4),
        },
        "windows_a": results_a,
        "windows_b": results_b,
    }
    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p1_exogenous_dal_recent.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)

    return 0 if sum_b["mean_ratio"] < sum_a["mean_ratio"] else 2


if __name__ == "__main__":
    sys.exit(main())
