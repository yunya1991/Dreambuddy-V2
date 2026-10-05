"""P1.2 PoC: 路径签名降维 (sig_dim 15→3) OOS 对比.

解决 T7 OOS 根因 2: 过拟合 (参数太多).
当前 drift_net in_dim = 3 + 15 + 3 = 21 (sig_dim=15, n_regimes=3)
降维后 in_dim = 3 + 3 + 3 = 9 (sig_dim=3, n_regimes=3)
参数减少 ~57%, 预期减少过拟合.

对比:
  - Model A: sig_dim=15, sig_depth=3 (当前配置)
  - Model B: sig_dim=3, sig_depth=2 (降维)

输出: dreambuddy_evolution/data/poc_p12_sig_dim_reduction.json
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


def train_and_eval(sig_dim, sig_depth, closes_train, regime_train, closes_full,
                   regime_full, test_starts, epochs=100):
    import torch
    torch.manual_seed(42)
    np.random.seed(42)

    model = NeuralSDEModel(device="cpu", sig_dim=sig_dim, sig_depth=sig_depth, n_regimes=3)
    trainer = NeuralSDETrainer(model=model, lr=1e-4, seq_len=64, horizon=20,
                               batch_size=64, loss_type="mse")
    t0 = time.time()
    report = trainer.train(closes_train, epochs=epochs,
                           regime_labels=regime_train, regime_balance="natural")
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
        "sig_dim": sig_dim,
        "sig_depth": sig_depth,
        "in_dim": 3 + sig_dim + 3,
        "final_loss": report.get("final_loss", 0),
        "train_time": round(train_time, 1),
        "mean_sde_mae": round(float(np.mean(sde_maes)), 4),
        "mean_garch_mae": round(float(np.mean(garch_maes)), 4),
        "mean_ratio": round(float(np.mean(ratios)), 4),
        "windows": maes,
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

    epochs = 100

    logger.info("=" * 60)
    logger.info("Model A: sig_dim=15, sig_depth=3 (当前配置)")
    result_a = train_and_eval(15, 3, closes_train, regime_train, closes_full,
                              regime_full, test_starts, epochs)
    logger.info("  MAE=%.2f, ratio=%.4f", result_a["mean_sde_mae"], result_a["mean_ratio"])

    logger.info("=" * 60)
    logger.info("Model B: sig_dim=3, sig_depth=2 (降维)")
    result_b = train_and_eval(3, 2, closes_train, regime_train, closes_full,
                              regime_full, test_starts, epochs)
    logger.info("  MAE=%.2f, ratio=%.4f", result_b["mean_sde_mae"], result_b["mean_ratio"])

    mae_a = result_a["mean_sde_mae"]
    mae_b = result_b["mean_sde_mae"]
    improvement_pct = round((mae_a - mae_b) / mae_a * 100, 2)
    p12_pass = improvement_pct >= 10

    logger.info("=" * 60)
    logger.info("=== P1.2 降维对比结果 ===")
    logger.info("sig_dim=15 (in_dim=%d): MAE=%.2f, ratio=%.4f", result_a["in_dim"], mae_a, result_a["mean_ratio"])
    logger.info("sig_dim=3  (in_dim=%d): MAE=%.2f, ratio=%.4f", result_b["in_dim"], mae_b, result_b["mean_ratio"])
    logger.info("MAE 改善: %.2f%%", improvement_pct)
    logger.info("P1.2 闸门 (改善 ≥10%%): %s", "PASS" if p12_pass else "FAIL")

    out = {
        "tdd": "P1.2-sig-dim-reduction",
        "config": {"epochs": epochs, "n_windows": len(test_starts)},
        "baseline_sig15": result_a,
        "reduced_sig3": result_b,
        "comparison": {
            "mae_improvement_pct": improvement_pct,
            "p12_gate_10pct_pass": bool(p12_pass),
        },
    }
    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p12_sig_dim_reduction.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)

    return 0 if p12_pass else 2


if __name__ == "__main__":
    sys.exit(main())
