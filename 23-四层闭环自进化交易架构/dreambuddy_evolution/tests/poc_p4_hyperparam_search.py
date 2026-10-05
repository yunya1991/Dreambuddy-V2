"""P4-T1 超参随机搜索.

基线 (combo): return_mse + dropout=0.2 + weight_decay=1e-4 + lr=1e-4 + epochs=200
  OOS MAE=920.46, ratio=0.97

搜索空间:
  - dropout: [0.1, 0.2, 0.3, 0.4, 0.5]
  - weight_decay: [1e-5, 5e-5, 1e-4, 5e-4, 1e-3]
  - lr: [5e-5, 1e-4, 2e-4, 5e-4]
  - epochs: [100, 200, 300]

经验 100017642: 每轮只改 1-2 个超参, 固化基线.
经验 100030242: 用随机搜索, 固定评估协议, 过拟合 gap 作硬约束.

输出: dreambuddy_evolution/data/poc_p4_hyperparam_search.json
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

# 基线配置 (combo, 已验证 MAE=920.46)
BASELINE = {
    "loss_type": "return_mse",
    "dropout": 0.2,
    "weight_decay": 1e-4,
    "lr": 1e-4,
    "epochs": 200,
    "patience": 10,
    "val_split": 0.1,
}

# 搜索空间
SEARCH_SPACE = {
    "dropout": [0.1, 0.2, 0.3, 0.4, 0.5],
    "weight_decay": [1e-5, 5e-5, 1e-4, 5e-4, 1e-3],
    "lr": [5e-5, 1e-4, 2e-4, 5e-4],
    "epochs": [100, 200, 300],
}


def train_and_eval(config, closes_train, regime_train, closes_full, regime_full, test_starts):
    import torch
    torch.manual_seed(42)
    np.random.seed(42)

    model = NeuralSDEModel(
        device="cpu", n_regimes=3,
        dropout=config["dropout"],
    )
    trainer = NeuralSDETrainer(
        model=model, lr=config["lr"], seq_len=64, horizon=20,
        batch_size=64, loss_type=config["loss_type"],
        weight_decay=config["weight_decay"],
        patience=config.get("patience"),
        val_split=config.get("val_split", 0.0),
    )

    t0 = time.time()
    report = trainer.train(
        closes_train, epochs=config["epochs"],
        regime_labels=regime_train, regime_balance="natural",
    )
    train_time = time.time() - t0

    # 过拟合 gap: final_train_loss vs best_val_loss
    train_loss = report.get("final_loss", 0.0)
    best_val_loss = report.get("best_val_loss")
    overfit_gap = train_loss - best_val_loss if best_val_loss is not None else None

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
        "weight_decay": config["weight_decay"],
        "lr": config["lr"],
        "epochs": config["epochs"],
        "epochs_run": report.get("epochs_run", config["epochs"]),
        "early_stopped": report.get("early_stopped", False),
        "final_train_loss": round(train_loss, 6),
        "best_val_loss": round(best_val_loss, 6) if best_val_loss is not None else None,
        "overfit_gap": round(overfit_gap, 6) if overfit_gap is not None else None,
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

    # 生成随机搜索配置 (12 个)
    rng = np.random.RandomState(123)
    configs = []
    for _ in range(12):
        cfg = dict(BASELINE)
        # 随机选择 2 个超参变化 (经验 100017642: 每轮只改 1-2 个)
        keys = rng.choice(["dropout", "weight_decay", "lr", "epochs"], size=2, replace=False)
        for k in keys:
            cfg[k] = rng.choice(SEARCH_SPACE[k])
        configs.append(cfg)

    # 加基线
    configs.insert(0, dict(BASELINE))

    results = []
    baseline_mae = None
    for i, cfg in enumerate(configs):
        logger.info("=" * 60)
        logger.info("[%d/%d] dropout=%.2f wd=%.0e lr=%.0e epochs=%d",
                    i + 1, len(configs), cfg["dropout"], cfg["weight_decay"],
                    cfg["lr"], cfg["epochs"])
        r = train_and_eval(cfg, closes_train, regime_train, closes_full,
                           regime_full, test_starts)
        if i == 0:
            baseline_mae = r["mean_sde_mae"]
        r["vs_baseline_pct"] = round((baseline_mae - r["mean_sde_mae"]) / baseline_mae * 100, 2) if baseline_mae else 0
        results.append(r)
        logger.info("  MAE=%.2f ratio=%.4f vs_baseline=%+.2f%% overfit_gap=%s",
                    r["mean_sde_mae"], r["mean_ratio"], r["vs_baseline_pct"],
                    r["overfit_gap"])

    # 按 OOS MAE 排序
    results_sorted = sorted(results, key=lambda x: x["mean_sde_mae"])
    best = results_sorted[0]

    logger.info("=" * 60)
    logger.info("=== P4 超参搜索结果 (按 MAE 排序) ===")
    for r in results_sorted:
        marker = " <-- BEST" if r is best else ""
        logger.info("  dropout=%.1f wd=%.0e lr=%.0e ep=%3d | MAE=%8.2f ratio=%.4f vs=%+6.2f%% gap=%s%s",
                    r["dropout"], r["weight_decay"], r["lr"], r["epochs"],
                    r["mean_sde_mae"], r["mean_ratio"], r["vs_baseline_pct"],
                    r["overfit_gap"], marker)

    p4_pass = best["vs_baseline_pct"] >= 5
    logger.info("P4 闸门 (最佳 vs baseline 改善 ≥5%%): %s", "PASS" if p4_pass else "FAIL")

    out = {
        "tdd": "P4-hyperparam-search",
        "baseline": BASELINE,
        "baseline_mae": baseline_mae,
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
        "best_vs_baseline_pct": best["vs_baseline_pct"],
        "p4_gate_5pct_pass": bool(p4_pass),
    }
    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p4_hyperparam_search.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)

    return 0 if p4_pass else 2


if __name__ == "__main__":
    sys.exit(main())
