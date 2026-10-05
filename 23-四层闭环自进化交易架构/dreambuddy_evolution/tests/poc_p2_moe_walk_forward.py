"""P2.1-T4 PoC: MoE-SDE walk-forward 2024 OOS 验证.

使用最优超参 (P4) + MoE 架构:
  - loss_type=return_mse, dropout=0.05, weight_decay=1e-4
  - lr=1e-4, epochs=250, patience=10, val_split=0.1
  - use_moe=True, n_regimes=3 (每 regime 独立 expert)

对比:
  - P4 baseline (共享 drift_net): MAE=915.75, ratio=0.9675
  - MoE-SDE: ?
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


def evaluate_on_windows(model, closes, test_starts, regime_labels, n_paths=200, horizon=20):
    """在 12 个月度窗口上评估 SDE vs GARCH."""
    results = []
    for ts in test_starts:
        history = closes[:ts + 1]
        actual = closes[ts + 1:ts + 1 + horizon]
        init_price = float(history[-1])
        returns = np.diff(np.log(history))
        init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02

        # GARCH baseline
        garch = GARCHFallback()
        garch.estimate(returns)
        garch_paths = garch.simulate(n_paths, horizon, init_price, init_vol)
        garch_pred = np.mean(garch_paths[:, 1:], axis=0)
        garch_mae = float(np.mean(np.abs(garch_pred - actual)))

        # NeuralSDE (MoE)
        test_regime = int(regime_labels[ts])
        sde_paths = model.forecast(history, horizon, n_paths, regime=test_regime)
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
    logger.info("加载 BTC 10y 1h close: %d 点", len(closes_full))

    N_TEST_2024 = 24 * 365
    train_end = len(closes_full) - N_TEST_2024
    closes_train = closes_full[:train_end].copy()
    logger.info("Walk-forward: train=%d (2017-2023), test=%d (2024)",
                train_end, N_TEST_2024)

    # Regime detection
    np.random.seed(42)
    detector = BTCRegimeDetector()
    regime_train = detector.detect(closes_train)
    regime_test = detector.detect(closes_full[train_end:])
    regime_full = np.concatenate([regime_train, regime_test])
    counts = np.bincount(regime_train, minlength=3)
    logger.info("训练集 regime 分布: bull=%d (%.1f%%) chop=%d (%.1f%%) bear=%d (%.1f%%)",
                counts[0], 100*counts[0]/len(closes_train),
                counts[1], 100*counts[1]/len(closes_train),
                counts[2], 100*counts[2]/len(closes_train))

    # MoE-SDE with P4 optimal hyperparams
    import torch
    torch.manual_seed(42)
    model = NeuralSDEModel(
        device="cpu", n_regimes=3,
        use_moe=True, moe_routing="hard",
        dropout=0.05,
    )
    if not model.is_available:
        logger.error("torch 不可用")
        return 1

    trainer = NeuralSDETrainer(
        model=model, lr=1e-4, seq_len=64, horizon=20,
        batch_size=64, loss_type="return_mse",
        weight_decay=1e-4,
        patience=10, val_split=0.1,
    )

    t0 = time.time()
    report = trainer.train(
        closes_train, epochs=250,
        regime_labels=regime_train,
        regime_balance="natural",
    )
    train_time = time.time() - t0
    logger.info("训练完成: status=%s, epochs_run=%d, final_loss=%.6f, 耗时=%.1fs",
                report.get("status"), report.get("epochs_run", 250),
                report.get("final_loss", 0.0), train_time)

    if report.get("status") != "ok":
        logger.error("训练未完成: %s", report)
        return 1

    # 12 monthly test windows
    n_test = len(closes_full) - train_end
    monthly_step = max(1, n_test // 12)
    test_starts = [
        train_end + i * monthly_step
        for i in range(12)
        if train_end + i * monthly_step + 20 < len(closes_full)
    ]
    logger.info("测试窗口: %d 个, 间隔=%d points (~月)", len(test_starts), monthly_step)

    results = evaluate_on_windows(
        model=model, closes=closes_full, test_starts=test_starts,
        regime_labels=regime_full, n_paths=200,
    )

    sde_maes = [r["sde_mae"] for r in results]
    garch_maes = [r["garch_mae"] for r in results]
    ratios = [r["ratio"] for r in results]

    logger.info("=" * 60)
    logger.info("=== MoE-SDE Walk-forward 2024 OOS 结果 ===")
    logger.info("NeuralSDE (MoE) MAE: mean=%.2f, median=%.2f",
                np.mean(sde_maes), np.median(sde_maes))
    logger.info("GARCH MAE:          mean=%.2f", np.mean(garch_maes))
    logger.info("ratio (SDE/GARCH):  mean=%.4f (越低越好)", np.mean(ratios))
    logger.info("最差窗口 ratio:     max=%.4f", np.max(ratios))

    # Baseline comparison (P4: MAE=915.75, ratio=0.9675)
    baseline_mae = 915.75
    moe_mae = float(np.mean(sde_maes))
    improvement = (baseline_mae - moe_mae) / baseline_mae * 100
    logger.info("vs P4 baseline (MAE=%.2f): %+.2f%%", baseline_mae, improvement)

    # Gates
    gate_12x = np.mean(ratios) <= 1.2
    gate_strict = np.mean(ratios) < 1.0
    gate_p2 = np.mean(ratios) < 0.9  # P2 target
    logger.info("OOS 闸门 1.2x:   %s", "PASS" if gate_12x else "FAIL")
    logger.info("OOS 闸门 strict: %s", "PASS" if gate_strict else "FAIL")
    logger.info("P2 闸门 <0.9:    %s", "PASS" if gate_p2 else "FAIL")

    out = {
        "tdd": "P2.1-T4-moe-walk-forward",
        "config": {
            "use_moe": True, "moe_routing": "soft",
            "loss_type": "return_mse", "dropout": 0.05,
            "weight_decay": 1e-4, "lr": 1e-4, "epochs": 250,
            "n_regimes": 3, "patience": 10, "val_split": 0.1,
        },
        "mean_sde_mae": round(float(np.mean(sde_maes)), 4),
        "median_sde_mae": round(float(np.median(sde_maes)), 4),
        "mean_garch_mae": round(float(np.mean(garch_maes)), 4),
        "mean_ratio": round(float(np.mean(ratios)), 4),
        "max_ratio": round(float(np.max(ratios)), 4),
        "vs_p4_baseline_pct": round(improvement, 2),
        "gates": {
            "1.2x": bool(gate_12x),
            "strict": bool(gate_strict),
            "p2_0.9": bool(gate_p2),
        },
        "train_time_s": round(train_time, 1),
        "windows": results,
    }
    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p2_moe_walk_forward.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)

    return 0 if gate_strict else 1


if __name__ == "__main__":
    sys.exit(main())
