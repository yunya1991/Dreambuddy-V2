"""P1.1 PoC: 熵加权 SDE+GARCH Ensemble 2024 OOS 验证.

目的:
  验证熵加权 ensemble 是否改善 2024 OOS MAE.
  结合 P0.2 (regime_uncertainty) + P1.1 (ensemble).

策略:
  final_pred = w * SDE_pred + (1-w) * GARCH_pred
  w = 1 - entropy / log(n_regimes)

对比:
  - SDE-only (baseline)
  - GARCH-only (baseline)
  - 熵加权 ensemble (P1.1)

输出: dreambuddy_evolution/data/poc_p11_entropy_ensemble.json
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
from dreambuddy_evolution.core.ensemble import (
    ensemble_forecast, compute_sde_weight_from_regime,
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    data_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
    with open(data_path) as f:
        closes_full = np.array(json.load(f), dtype=np.float64)
    logger.info("加载 BTC 10y 1h close: %d 点", len(closes_full))

    N_TEST_2024 = 24 * 365
    train_end = len(closes_full) - N_TEST_2024
    closes_train = closes_full[:train_end].copy()
    closes_test = closes_full[train_end:].copy()
    logger.info("train=%d, 2024=%d", len(closes_train), len(closes_test))

    # regime
    np.random.seed(42)
    detector = BTCRegimeDetector()
    regime_train = detector.detect(closes_train)
    regime_test = detector.detect(closes_test)
    regime_full = np.concatenate([regime_train, regime_test])

    # 估计 Q (全量)
    Q = detector.estimate_transition_matrix(regime_full)
    logger.info("Q 矩阵:\n%s", np.round(Q, 3))

    # 训练模型
    import torch
    torch.manual_seed(42)
    model = NeuralSDEModel(device="cpu")
    trainer = NeuralSDETrainer(model=model, lr=1e-4, seq_len=64, horizon=20,
                               batch_size=64, loss_type="mse")
    t0 = time.time()
    report = trainer.train(closes_train, epochs=100,
                           regime_labels=regime_train, regime_balance="natural")
    logger.info("训练完成: %.1fs, loss=%.6f", time.time() - t0, report.get("final_loss", 0))

    # 12 个测试窗口
    n_test = len(closes_test)
    monthly_step = max(1, n_test // 12)
    test_starts = [
        train_end + i * monthly_step
        for i in range(12)
        if train_end + i * monthly_step + 20 < len(closes_full)
    ]

    horizon = 20
    n_paths = 200
    results = []

    for ts in test_starts:
        history = closes_full[:ts + 1]
        actual = closes_full[ts + 1:ts + 1 + horizon]
        init_price = float(history[-1])
        returns = np.diff(np.log(history))
        init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02

        # GARCH
        garch = GARCHFallback()
        garch.estimate(returns)
        garch_paths = garch.simulate(n_paths, horizon, init_price, init_vol)
        garch_pred = np.mean(garch_paths[:, 1:], axis=0)
        garch_mae = float(np.mean(np.abs(garch_pred - actual)))

        # SDE
        test_regime = int(regime_full[ts])
        sde_paths = model.forecast(history, horizon, n_paths, regime=test_regime)
        if sde_paths is not None:
            sde_pred = np.mean(sde_paths[:, 1:], axis=0)
            sde_mae = float(np.mean(np.abs(sde_pred - actual)))
        else:
            sde_pred = None
            sde_mae = float("inf")

        # 熵加权 ensemble
        sde_weight = compute_sde_weight_from_regime(Q, test_regime, n_regimes=3)
        ensemble_pred = ensemble_forecast(sde_pred, garch_pred, sde_weight=sde_weight)
        ensemble_mae = float(np.mean(np.abs(ensemble_pred - actual)))

        results.append({
            "test_regime": test_regime,
            "sde_weight": round(sde_weight, 4),
            "sde_mae": round(sde_mae, 4),
            "garch_mae": round(garch_mae, 4),
            "ensemble_mae": round(ensemble_mae, 4),
            "ensemble_vs_sde": round(sde_mae - ensemble_mae, 4),
            "ensemble_vs_garch": round(garch_mae - ensemble_mae, 4),
        })
        logger.info("  regime=%d w=%.2f | SDE=%.0f GARCH=%.0f Ensemble=%.0f",
                    test_regime, sde_weight, sde_mae, garch_mae, ensemble_mae)

    # 汇总
    sde_maes = [r["sde_mae"] for r in results]
    garch_maes = [r["garch_mae"] for r in results]
    ens_maes = [r["ensemble_mae"] for r in results]

    mean_sde = float(np.mean(sde_maes))
    mean_garch = float(np.mean(garch_maes))
    mean_ens = float(np.mean(ens_maes))

    ens_vs_sde_pct = round((mean_sde - mean_ens) / mean_sde * 100, 2)
    ens_vs_garch_pct = round((mean_garch - mean_ens) / mean_garch * 100, 2)
    ens_ratio = round(mean_ens / mean_garch, 4)

    p11_pass = ens_vs_sde_pct >= 10  # 目标: 比 SDE-only 改善 ≥10%

    logger.info("=" * 60)
    logger.info("=== P1.1 熵加权 Ensemble 结果 ===")
    logger.info("SDE-only:     MAE=%.2f", mean_sde)
    logger.info("GARCH-only:   MAE=%.2f", mean_garch)
    logger.info("Ensemble:     MAE=%.2f, ratio=%.4f", mean_ens, ens_ratio)
    logger.info("Ensemble vs SDE:   %+.2f%%", ens_vs_sde_pct)
    logger.info("Ensemble vs GARCH: %+.2f%%", ens_vs_garch_pct)
    logger.info("P1.1 闸门 (vs SDE 改善 ≥10%%): %s", "PASS" if p11_pass else "FAIL")

    out = {
        "tdd": "P1.1-entropy-ensemble",
        "config": {"epochs": 100, "n_windows": len(results)},
        "summary": {
            "mean_sde_mae": round(mean_sde, 4),
            "mean_garch_mae": round(mean_garch, 4),
            "mean_ensemble_mae": round(mean_ens, 4),
            "ensemble_vs_sde_pct": ens_vs_sde_pct,
            "ensemble_vs_garch_pct": ens_vs_garch_pct,
            "ensemble_ratio": ens_ratio,
        },
        "windows": results,
        "gates": {"p11_vs_sde_10pct_pass": bool(p11_pass)},
    }
    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p11_entropy_ensemble.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)

    return 0 if p11_pass else 2


if __name__ == "__main__":
    sys.exit(main())
