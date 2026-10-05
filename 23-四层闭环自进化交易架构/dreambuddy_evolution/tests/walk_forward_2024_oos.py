"""T7 Walk-forward 2024 OOS 验证.

目的:
  验证 regime-aware NeuralSDE 在 2024 数据上 out-of-sample (OOS) 泛化能力.
  T5 v4 (MAE=314.89) 是 in-sample (训练集末尾), T7 走 true OOS:
    - 训练: 2017-2023 (~9y, 71181 points, 不含 2024)
    - 测试: 2024 (last 8760 points) 多窗口 OOS

  12 个测试窗口 (每月 1 个, horizon=20 1h ~1天) 分布在 2024 全年,
  覆盖不同 regime (bull/chop/bear) 下 OOS 预测能力.

输出: dreambuddy_evolution/data/walk_forward_2024_oos.json
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

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def evaluate_on_windows(
    model: NeuralSDEModel,
    closes: np.ndarray,
    test_starts: list[int],
    regime_labels: np.ndarray | None,
    n_paths: int = 200,
    horizon: int = 20,
) -> list[dict]:
    """在多个测试窗口上评估 MAE.

    Args:
        model: 已训练的 NeuralSDEModel
        closes: 全量 close (训练+测试)
        test_starts: 测试窗口起点列表 (索引)
        regime_labels: 全量 regime labels 或 None
        n_paths: 路径采样数
        horizon: 预测步数

    Returns:
        list of {start, actual_end, sde_mae, garch_mae, regime}
    """
    results = []
    for ts in test_starts:
        if ts + horizon >= len(closes):
            continue
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

        # NeuralSDE
        test_regime = int(regime_labels[ts]) if regime_labels is not None else None
        sde_paths = model.forecast(history, horizon, n_paths, regime=test_regime)
        if sde_paths is None:
            sde_mae = float("inf")
        else:
            sde_pred = np.mean(sde_paths[:, 1:], axis=0)
            sde_mae = float(np.mean(np.abs(sde_pred - actual)))

        results.append({
            "test_start_idx": int(ts),
            "test_price_start": round(float(closes[ts]), 2),
            "test_regime": test_regime,
            "horizon": horizon,
            "sde_mae": round(sde_mae, 4),
            "garch_mae": round(garch_mae, 4),
            "ratio": round(sde_mae / garch_mae, 4) if garch_mae > 0 else float("inf"),
            "improvement": round(garch_mae - sde_mae, 4),
        })
    return results


def main():
    data_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
    if not data_path.exists():
        logger.error("数据不存在: %s", data_path)
        return 1

    with open(data_path) as f:
        closes_full = np.array(json.load(f), dtype=np.float64)
    logger.info("加载 BTC 10y 1h close: %d 点", len(closes_full))

    # Walk-forward 切分
    # 训练集: 前 9y (71181 points, ~2017-2023)
    # 测试集: 2024 (last 8760 points)
    N_TEST_2024 = 24 * 365  # 8760 points
    train_end = len(closes_full) - N_TEST_2024
    closes_train = closes_full[:train_end].copy()
    closes_test = closes_full[train_end:].copy()
    logger.info("Walk-forward 切分: train=%d (2017-2023), test=%d (2024)",
                len(closes_train), len(closes_test))
    logger.info("  train 末尾: $%.2f", closes_train[-1])
    logger.info("  test 首点: $%.2f, 末点: $%.2f", closes_test[0], closes_test[-1])

    # 训练集上检测 regime (训练数据范围)
    np.random.seed(42)
    detector = BTCRegimeDetector()
    regime_labels_train = detector.detect(closes_train)
    counts = np.bincount(regime_labels_train, minlength=3)
    logger.info("训练集 regime 分布: bull=%d (%.1f%%) chop=%d (%.1f%%) bear=%d (%.1f%%)",
                counts[0], 100*counts[0]/len(closes_train),
                counts[1], 100*counts[1]/len(closes_train),
                counts[2], 100*counts[2]/len(closes_train))

    # 训练 NeuralSDE (P2+P4 最优: MoE hard routing + return_mse + dropout0.05 + wd1e-4 + 250ep)
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
        regime_labels=regime_labels_train,
        regime_balance="natural",
    )
    train_time = time.time() - t0
    logger.info("训练完成: status=%s, n_windows=%d, final_loss=%.6f, 耗时=%.1fs",
                report.get("status"), report.get("n_windows", 0),
                report.get("final_loss", 0.0), train_time)

    if report.get("status") != "ok":
        logger.error("训练未完成: %s", report)
        return 1

    # 在 2024 上检测 regime (用相同 detector)
    regime_labels_test = detector.detect(closes_test)
    # 全量 regime labels (训练+测试)
    regime_labels_full = np.concatenate([regime_labels_train, regime_labels_test])

    # 12 个测试窗口: 每月 1 个 (8760 / 12 = 730 间隔)
    n_test = len(closes_test)
    monthly_step = max(1, n_test // 12)
    test_starts = [
        train_end + i * monthly_step
        for i in range(12)
        if train_end + i * monthly_step + 20 < len(closes_full)
    ]
    logger.info("测试窗口: %d 个, 间隔=%d points (~月)", len(test_starts), monthly_step)

    # 在 12 个窗口上评估
    results = evaluate_on_windows(
        model=model,
        closes=closes_full,
        test_starts=test_starts,
        regime_labels=regime_labels_full,
        n_paths=200,
        horizon=20,
    )

    # 汇总
    sde_maes = [r["sde_mae"] for r in results]
    garch_maes = [r["garch_mae"] for r in results]
    ratios = [r["ratio"] for r in results if r["ratio"] != float("inf")]

    mean_sde_mae = float(np.mean(sde_maes))
    median_sde_mae = float(np.median(sde_maes))
    mean_garch_mae = float(np.mean(garch_maes))
    mean_ratio = float(np.mean(ratios)) if ratios else float("inf")
    # OOS 闸门: mean_sde_mae < 1.2 × mean_garch_mae (NeuralSDE 至少不显著差于 GARCH)
    # 更严格: mean_ratio < 1.0 (NeuralSDE 平均优于 GARCH)
    oos_gate_1_2x = mean_sde_mae < 1.2 * mean_garch_mae
    oos_gate_strict = mean_ratio < 1.0

    # regime 分布在测试窗口
    test_regimes = [r["test_regime"] for r in results if r["test_regime"] is not None]
    regime_counts = {
        "bull": int(test_regimes.count(0)),
        "chop": int(test_regimes.count(1)),
        "bear": int(test_regimes.count(2)),
    } if test_regimes else {}

    out = {
        "tdd": "T7-walk-forward",
        "purpose": "2024 OOS walk-forward 验证 regime-aware NeuralSDE 泛化能力",
        "config": {
            "data": "btc_close_10y.json",
            "train_points": int(len(closes_train)),
            "test_points_2024": int(len(closes_test)),
            "train_price_range": [float(closes_train.min()), float(closes_train.max())],
            "test_price_range": [float(closes_test.min()), float(closes_test.max())],
            "epochs": 200,
            "seed": 42,
            "regime_balance": "natural",
            "n_regimes": 3,
            "n_test_windows": len(results),
            "horizon": 20,
            "n_paths": 200,
        },
        "train_summary": {
            "n_windows": int(report.get("n_windows", 0)),
            "final_loss": float(report.get("final_loss", 0.0)),
            "train_time_sec": round(train_time, 2),
            "train_regime_distribution": {
                "bull": int(counts[0]),
                "chop": int(counts[1]),
                "bear": int(counts[2]),
            },
        },
        "windows": results,
        "summary": {
            "mean_sde_mae": round(mean_sde_mae, 4),
            "median_sde_mae": round(median_sde_mae, 4),
            "mean_garch_mae": round(mean_garch_mae, 4),
            "mean_ratio": round(mean_ratio, 4),
            "test_regime_distribution": regime_counts,
        },
        "gates": {
            "oos_not_worse_than_garch_1_2x": bool(oos_gate_1_2x),
            "oos_better_than_garch_strict": bool(oos_gate_strict),
            "threshold_1_2x": 1.2,
            "threshold_strict": 1.0,
        },
        "reference": {
            "v4_insample_mae": 314.89,
            "v3c_insample_mae": 569,
            "v2_insample_mae": 269,
        },
    }

    out_path = REPO / "dreambuddy_evolution" / "data" / "walk_forward_2024_oos.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info("=== Walk-forward 2024 OOS 结果 ===")
    logger.info("测试窗口: %d 个, 覆盖 2024 全年", len(results))
    logger.info("NeuralSDE MAE: mean=%.2f, median=%.2f", mean_sde_mae, median_sde_mae)
    logger.info("GARCH MAE:     mean=%.2f", mean_garch_mae)
    logger.info("ratio:         mean=%.4f (越低越好)", mean_ratio)
    logger.info("测试 regime 分布: %s", regime_counts)
    logger.info("OOS 闸门 1.2x:   %s (NeuralSDE ≤ 1.2×GARCH)",
                "PASS" if oos_gate_1_2x else "FAIL")
    logger.info("OOS 闸门 strict: %s (NeuralSDE < GARCH)",
                "PASS" if oos_gate_strict else "FAIL")
    logger.info("报告: %s", out_path)

    # 闸门: 至少通过 1.2x (不显著差于 GARCH)
    return 0 if oos_gate_1_2x else 2


if __name__ == "__main__":
    sys.exit(main())
