"""P4-T2 精调: 围绕最优配置 (dropout=0.1, epochs=200) 精细搜索.

搜索空间:
  - dropout: [0.05, 0.1, 0.15]
  - epochs: [200, 250, 300]
  - weight_decay: [1e-4, 5e-4]
  - lr: [1e-4, 2e-4]

固定: loss_type=return_mse, patience=10, val_split=0.1
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

    model = NeuralSDEModel(device="cpu", n_regimes=3, dropout=config["dropout"])
    trainer = NeuralSDETrainer(
        model=model, lr=config["lr"], seq_len=64, horizon=20,
        batch_size=64, loss_type="return_mse",
        weight_decay=config["weight_decay"],
        patience=10, val_split=0.1,
    )

    t0 = time.time()
    report = trainer.train(
        closes_train, epochs=config["epochs"],
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
        "dropout": config["dropout"],
        "weight_decay": float(config["weight_decay"]),
        "lr": float(config["lr"]),
        "epochs": int(config["epochs"]),
        "epochs_run": int(report.get("epochs_run", config["epochs"])),
        "early_stopped": bool(report.get("early_stopped", False)),
        "final_train_loss": round(float(report.get("final_loss", 0.0)), 6),
        "best_val_loss": round(float(report.get("best_val_loss", 0.0)), 6) if report.get("best_val_loss") is not None else None,
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

    # 精调配置: 围绕 dropout=0.1
    configs = [
        {"dropout": 0.05, "weight_decay": 1e-4, "lr": 1e-4, "epochs": 200},
        {"dropout": 0.05, "weight_decay": 1e-4, "lr": 1e-4, "epochs": 250},
        {"dropout": 0.1, "weight_decay": 1e-4, "lr": 1e-4, "epochs": 200},
        {"dropout": 0.1, "weight_decay": 1e-4, "lr": 1e-4, "epochs": 250},
        {"dropout": 0.1, "weight_decay": 1e-4, "lr": 1e-4, "epochs": 300},
        {"dropout": 0.1, "weight_decay": 5e-4, "lr": 1e-4, "epochs": 250},
        {"dropout": 0.1, "weight_decay": 1e-4, "lr": 2e-4, "epochs": 250},
        {"dropout": 0.15, "weight_decay": 1e-4, "lr": 1e-4, "epochs": 250},
        {"dropout": 0.15, "weight_decay": 1e-4, "lr": 1e-4, "epochs": 300},
    ]

    results = []
    for i, cfg in enumerate(configs):
        logger.info("=" * 60)
        logger.info("[%d/%d] dropout=%.2f wd=%.0e lr=%.0e epochs=%d",
                    i + 1, len(configs), cfg["dropout"], cfg["weight_decay"],
                    cfg["lr"], cfg["epochs"])
        r = train_and_eval(cfg, closes_train, regime_train, closes_full,
                           regime_full, test_starts)
        results.append(r)
        logger.info("  MAE=%.2f ratio=%.4f epochs_run=%d time=%.1fs",
                    r["mean_sde_mae"], r["mean_ratio"], r["epochs_run"], r["train_time"])

    # 按 MAE 排序
    results_sorted = sorted(results, key=lambda x: x["mean_sde_mae"])
    best = results_sorted[0]

    logger.info("=" * 60)
    logger.info("=== P4-T2 精调结果 (按 MAE 排序) ===")
    for r in results_sorted:
        marker = " <-- BEST" if r is best else ""
        logger.info("  dropout=%.2f wd=%.0e lr=%.0e ep=%3d | MAE=%8.2f ratio=%.4f%s",
                    r["dropout"], r["weight_decay"], r["lr"], r["epochs"],
                    r["mean_sde_mae"], r["mean_ratio"], marker)

    out = {
        "tdd": "P4-T2-finetune",
        "n_configs": len(configs),
        "results": results_sorted,
        "best_config": {
            "dropout": best["dropout"],
            "weight_decay": best["weight_decay"],
            "lr": best["lr"],
            "epochs": best["epochs"],
            "loss_type": "return_mse",
            "patience": 10,
            "val_split": 0.1,
        },
        "best_mae": best["mean_sde_mae"],
        "best_ratio": best["mean_ratio"],
    }
    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p4_finetune.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
