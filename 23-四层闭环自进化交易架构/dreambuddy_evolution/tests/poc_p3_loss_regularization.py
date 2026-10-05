"""P3-T3 PoC: 损失函数 + 正则化 OOS 对比.

对比配置 (2024 walk-forward):
  - baseline: mse, dropout=0, wd=0, epochs=100
  - huber:    huber loss
  - return:   return_mse loss
  - drop:     dropout=0.2
  - wd:       weight_decay=1e-4 (AdamW)
  - es:       early stopping (patience=10, val_split=0.1)
  - combo:    return_mse + dropout=0.2 + weight_decay=1e-4 + early stopping

输出: dreambuddy_evolution/data/poc_p3_loss_regularization.json
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer
from dreambuddy_evolution.core.garch_fallback import GARCHFallback
from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def train_and_eval(config, closes_train, regime_train, closes_full, regime_full, test_starts):
    import torch
    torch.manual_seed(42)
    np.random.seed(42)

    model = NeuralSDEModel(
        device="cpu", n_regimes=3,
        dropout=config.get("dropout", 0.0),
    )
    trainer = NeuralSDETrainer(
        model=model, lr=1e-4, seq_len=64, horizon=20,
        batch_size=64, loss_type=config["loss_type"],
        weight_decay=config.get("weight_decay", 0.0),
        patience=config.get("patience"),
        val_split=config.get("val_split", 0.0),
    )

    t0 = time.time()
    report = trainer.train(
        closes_train, epochs=config.get("epochs", 100),
        regime_labels=regime_train, regime_balance="natural",
    )
    train_time = time.time() - t0

    horizon = 20
    n_paths = 200
    maes = []
    for ts in test_starts:
        history = closes_full[:ts + 1]
        actual = closes_full[ts + 1:ts + 1 + horizon]
        init_price = float(history[-1])
        returns = np.diff(np.log(history))
        init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02

        garch = GARCHFallback()
        garch.estimate(returns)
        garch_paths = garch.simulate(n_paths, horizon, init_price, init_vol)
        garch_pred = np.mean(garch_paths[:, 1:], axis=0)
        garch_mae = float(np.mean(np.abs(garch_pred - actual)))

        test_regime = int(regime_full[ts])
        sde_paths = model.forecast(history, horizon, n_paths, regime=test_regime)
        if sde_paths is not None:
            sde_pred = np.mean(sde_paths[:, 1:], axis=0)
            sde_mae = float(np.mean(np.abs(sde_pred - actual)))
        else:
            sde_mae = float("inf")
        maes.append({"sde_mae": sde_mae, "garch_mae": garch_mae})

    sde_maes = [m["sde_mae"] for m in maes]
    garch_maes = [m["garch_mae"] for m in maes]
    ratios = [s / g for s, g in zip(sde_maes, garch_maes) if g > 0]

    return {
        "config": config["name"],
        "loss_type": config["loss_type"],
        "dropout": config.get("dropout", 0.0),
        "weight_decay": config.get("weight_decay", 0.0),
        "patience": config.get("patience"),
        "final_loss": report.get("final_loss", 0),
        "epochs_run": report.get("epochs_run", config.get("epochs", 100)),
        "early_stopped": report.get("early_stopped", False),
        "train_time": round(train_time, 1),
        "mean_sde_mae": round(float(np.mean(sde_maes)), 4),
        "mean_garch_mae": round(float(np.mean(garch_maes)), 4),
        "mean_ratio": round(float(np.mean(ratios)), 4),
    }


def main():
    data_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
    with open(data_path) as f:
        closes_full = np.array(json.load(f), dtype=np.float64)
    logger.info("加载 BTC 10y 1h close: %d 点", len(closes_full))

    N_TEST_2024 = 24 * 365
    train_end = len(closes_full) - N_TEST_2024
    closes_train = closes_full[:train_end].copy()

    np.random.seed(42)
    detector = BTCRegimeDetector()
    regime_train = detector.detect(closes_train)
    regime_test = detector.detect(closes_full[train_end:])
    regime_full = np.concatenate([regime_train, regime_test])

    n_test = len(closes_full) - train_end
    monthly_step = n_test // 12
    test_starts = [train_end + i * monthly_step for i in range(12)
                   if train_end + i * monthly_step + 20 < len(closes_full)]

    configs = [
        {"name": "baseline_mse", "loss_type": "mse", "epochs": 100},
        {"name": "huber", "loss_type": "huber", "epochs": 100},
        {"name": "return_mse", "loss_type": "return_mse", "epochs": 100},
        {"name": "dropout02", "loss_type": "mse", "dropout": 0.2, "epochs": 100},
        {"name": "wd1e4", "loss_type": "mse", "weight_decay": 1e-4, "epochs": 100},
        {"name": "early_stop", "loss_type": "mse", "patience": 10, "val_split": 0.1, "epochs": 200},
        {
            "name": "combo", "loss_type": "return_mse",
            "dropout": 0.2, "weight_decay": 1e-4,
            "patience": 10, "val_split": 0.1, "epochs": 200,
        },
    ]

    results = []
    baseline_mae = None
    for cfg in configs:
        logger.info("=" * 60)
        logger.info("配置: %s", cfg["name"])
        r = train_and_eval(cfg, closes_train, regime_train, closes_full,
                           regime_full, test_starts)
        results.append(r)
        if cfg["name"] == "baseline_mse":
            baseline_mae = r["mean_sde_mae"]
        logger.info("  MAE=%.2f, ratio=%.4f, epochs=%d, time=%.1fs",
                    r["mean_sde_mae"], r["mean_ratio"], r["epochs_run"], r["train_time"])

    # 汇总对比
    logger.info("=" * 60)
    logger.info("=== P3 损失函数+正则化对比结果 ===")
    best_result = None
    for r in results:
        improvement = round((baseline_mae - r["mean_sde_mae"]) / baseline_mae * 100, 2) if baseline_mae else 0
        r["vs_baseline_pct"] = improvement
        marker = ""
        if best_result is None or r["mean_sde_mae"] < best_result["mean_sde_mae"]:
            best_result = r
            marker = " <-- BEST"
        logger.info("  %-15s MAE=%8.2f ratio=%.4f vs_baseline=%+6.2f%%%s",
                    r["config"], r["mean_sde_mae"], r["mean_ratio"], improvement, marker)

    p3_pass = best_result["vs_baseline_pct"] >= 10 if baseline_mae else False
    logger.info("P3 闸门 (最佳配置 vs baseline 改善 ≥10%%): %s", "PASS" if p3_pass else "FAIL")

    out = {
        "tdd": "P3-loss-regularization",
        "config": {"epochs": 100, "n_windows": len(test_starts)},
        "baseline_mae": baseline_mae,
        "results": results,
        "best_config": best_result["config"],
        "best_mae": best_result["mean_sde_mae"],
        "p3_gate_10pct_pass": bool(p3_pass),
    }
    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p3_loss_regularization.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)

    return 0 if p3_pass else 2


if __name__ == "__main__":
    sys.exit(main())
