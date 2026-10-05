"""E7 PoC (A1 真实 DAL 历史外生数据): 2024 walk-forward 有/无外生对比.

数据:
  - 价格: btc_close_10y.json (2015-11 ~ 2024-12, 79941 小时点)
  - 外生: 19-DAL 历史数据 (FRED CPI/FEDFUNDS/M2, yfinance DXY, blockchain.info 链上)
    通过 ExogenousDataBridge.fetch_historical_aligned() 时序对齐到小时级

对比:
  - Config A: 无外生 (use_exogenous=False) — baseline, ratio=0.963
  - Config B: 有外生 (use_exogenous=True, exogenous_dim=9, 真实 DAL 时序对齐)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
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

from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer  # noqa: E402
from dreambuddy_evolution.core.garch_fallback import GARCHFallback  # noqa: E402
from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector  # noqa: E402
from dreambuddy_evolution.core.exogenous_data_bridge import (  # noqa: E402
    ExogenousDataBridge, build_exogenous_series,
)


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


def main():
    data_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
    with open(data_path) as f:
        closes_full = np.array(json.load(f), dtype=np.float64)
    n = len(closes_full)
    logger.info("加载 BTC 10y 1h close: %d 点", n)

    # 生成时间戳 (1h 间隔, 末尾 = 2024-12-31 23:00 UTC)
    end_ts = datetime(2024, 12, 31, 23, 0, tzinfo=timezone.utc)
    timestamps = [end_ts - timedelta(hours=n - 1 - i) for i in range(n)]
    logger.info("时间范围: %s ~ %s", timestamps[0].date(), timestamps[-1].date())

    # Walk-forward 切分: train 前 71181 点 (2015-2023), test 后 8760 点 (2024)
    N_TEST_2024 = 24 * 365
    train_end = n - N_TEST_2024
    closes_train = closes_full[:train_end].copy()
    logger.info("Walk-forward: train=%d (2015-2023), test=%d (2024)", train_end, N_TEST_2024)

    # Regime detection
    np.random.seed(42)
    detector = BTCRegimeDetector()
    regime_train = detector.detect(closes_train)
    regime_test = detector.detect(closes_full[train_end:])
    regime_full = np.concatenate([regime_train, regime_test])
    counts = np.bincount(regime_train, minlength=3)
    logger.info("训练集 regime: bull=%d chop=%d bear=%d", counts[0], counts[1], counts[2])

    # ===== 构建真实 DAL 历史外生时序 =====
    bridge = ExogenousDataBridge()
    t0 = time.time()
    logger.info("从 19-DAL 加载历史外生数据并时序对齐 (n=%d)...", n)
    per_point_data = bridge.fetch_historical_aligned(timestamps)
    logger.info("外生数据加载完成, 耗时=%.1fs", time.time() - t0)

    # 统计数据覆盖率
    field_counts = {}
    for d in per_point_data:
        for k in d:
            field_counts[k] = field_counts.get(k, 0) + 1
    logger.info("外生字段覆盖率:")
    for k, cnt in sorted(field_counts.items(), key=lambda x: -x[1]):
        logger.info("  %s: %.1f%% (%d/%d)", k, 100 * cnt / n, cnt, n)

    # 构建 9 维外生力量时序
    t1 = time.time()
    exo_series = build_exogenous_series(closes_full, bridge=None, per_point_data=per_point_data)
    logger.info("外生力量时序构建: shape=%s, 耗时=%.1fs", exo_series.shape, time.time() - t1)
    non_neutral = float(np.mean(np.any(exo_series != 0.5, axis=1)))
    logger.info("非中性比例: %.3f", non_neutral)

    # 12 个月度测试窗口
    monthly_step = max(1, N_TEST_2024 // 12)
    test_starts = [
        train_end + i * monthly_step
        for i in range(12)
        if train_end + i * monthly_step + 20 < n
    ]
    logger.info("测试窗口: %d 个", len(test_starts))

    # ===== Config A: 无外生 =====
    logger.info("=== 训练 Config A (无外生) ===")
    import torch
    torch.manual_seed(42)
    model_a = NeuralSDEModel(
        device="cpu", n_regimes=3,
        use_moe=True, moe_routing="hard",
        dropout=0.05,
    )
    trainer_a = NeuralSDETrainer(
        model=model_a, lr=1e-4, seq_len=64, horizon=20,
        batch_size=64, loss_type="return_mse",
        weight_decay=1e-4, patience=10, val_split=0.1,
    )
    t0 = time.time()
    report_a = trainer_a.train(
        closes_train, epochs=250,
        regime_labels=regime_train,
        regime_balance="natural",
    )
    time_a = time.time() - t0
    logger.info("Config A 训练完成: final_loss=%.6f, 耗时=%.1fs",
                report_a.get("final_loss", 0), time_a)

    results_a = evaluate_on_windows(
        model=model_a, closes=closes_full, test_starts=test_starts,
        regime_labels=regime_full, full_exo_series=None,
    )

    # ===== Config B: 有外生 (真实 DAL) =====
    logger.info("=== 训练 Config B (有外生, DAL 真实时序) ===")
    torch.manual_seed(42)
    model_b = NeuralSDEModel(
        device="cpu", n_regimes=3,
        use_moe=True, moe_routing="hard",
        dropout=0.05,
        use_exogenous=True, exogenous_dim=9,
    )
    trainer_b = NeuralSDETrainer(
        model=model_b, lr=1e-4, seq_len=64, horizon=20,
        batch_size=64, loss_type="return_mse",
        weight_decay=1e-4, patience=10, val_split=0.1,
    )
    exo_train = exo_series[:train_end]
    t0 = time.time()
    report_b = trainer_b.train(
        closes_train, epochs=250,
        regime_labels=regime_train,
        regime_balance="natural",
        exogenous_series=exo_train,
    )
    time_b = time.time() - t0
    logger.info("Config B 训练完成: final_loss=%.6f, 耗时=%.1fs",
                report_b.get("final_loss", 0), time_b)

    results_b = evaluate_on_windows(
        model=model_b, closes=closes_full, test_starts=test_starts,
        regime_labels=regime_full, full_exo_series=exo_series,
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
        }

    sum_a = summarize(results_a)
    sum_b = summarize(results_b)
    delta_ratio = (sum_b["mean_ratio"] - sum_a["mean_ratio"]) / sum_a["mean_ratio"] * 100

    logger.info("=" * 60)
    logger.info("=== E7 PoC (A1 真实 DAL 历史外生) 对比结果 ===")
    logger.info("Config A (无外生):    MAE=%.2f, ratio=%.4f, max_ratio=%.4f",
                sum_a["mean_sde_mae"], sum_a["mean_ratio"], sum_a["max_ratio"])
    logger.info("Config B (DAL 外生):  MAE=%.2f, ratio=%.4f, max_ratio=%.4f",
                sum_b["mean_sde_mae"], sum_b["mean_ratio"], sum_b["max_ratio"])
    logger.info("GARCH baseline:       MAE=%.2f", sum_a["mean_garch_mae"])
    logger.info("ratio 变化: %+.2f%% (越负越好)", delta_ratio)
    logger.info("P1 目标 <0.93: %s", "PASS" if sum_b["mean_ratio"] < 0.93 else "FAIL")
    logger.info("不恶化 (B<A): %s", "PASS" if sum_b["mean_ratio"] < sum_a["mean_ratio"] else "FAIL")

    out = {
        "tdd": "E7-poc-p1-exogenous-dal-historical",
        "data": {
            "source": "19-DAL historical (FRED + yfinance + blockchain.info)",
            "exo_field_coverage": {k: round(v / n, 4) for k, v in field_counts.items()},
            "exo_non_neutral_ratio": round(non_neutral, 4),
        },
        "config_a": {"summary": {k: round(v, 4) for k, v in sum_a.items()}},
        "config_b": {"summary": {k: round(v, 4) for k, v in sum_b.items()}},
        "comparison": {"delta_ratio_pct": round(delta_ratio, 4)},
        "gates": {
            "p1_target_lt_0.93": bool(sum_b["mean_ratio"] < 0.93),
            "no_regression": bool(sum_b["mean_ratio"] < sum_a["mean_ratio"]),
        },
        "windows_a": results_a,
        "windows_b": results_b,
    }
    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p1_exogenous_dal_historical.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)

    return 0 if sum_b["mean_ratio"] < sum_a["mean_ratio"] else 2


if __name__ == "__main__":
    sys.exit(main())
