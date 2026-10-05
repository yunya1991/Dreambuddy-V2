"""P0.1-T4 PoC: 在线学习 walk-forward 2024 对比.

目的:
  验证在线学习 (每月 fine-tune + EWC) 是否改善 2024 OOS MAE.
  解决 T7 OOS 根因 1: 数据分布漂移.

对比设计:
  - Model A (静态): 2017-2023 训练, 2024 全年不更新
  - Model B (在线): 2017-2023 训练, 每月用最近 2y 数据 fine-tune

输出: dreambuddy_evolution/data/poc_p01_online_learning_walk_forward.json
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
from dreambuddy_evolution.core.online_trainer import NeuralSDEOnlineTrainer

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def evaluate_window(model, closes, ts, horizon, n_paths, regime_labels):
    """评估单个窗口."""
    if ts + horizon >= len(closes):
        return None
    history = closes[:ts + 1]
    actual = closes[ts + 1:ts + 1 + horizon]
    init_price = float(history[-1])
    returns = np.diff(np.log(history))
    init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02

    # GARCH
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

    return {
        "sde_mae": sde_mae,
        "garch_mae": garch_mae,
        "ratio": sde_mae / garch_mae if garch_mae > 0 else float("inf"),
        "regime": test_regime,
    }


def main():
    data_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
    with open(data_path) as f:
        closes_full = np.array(json.load(f), dtype=np.float64)
    logger.info("加载 BTC 10y 1h close: %d 点", len(closes_full))

    # 切分
    N_TEST_2024 = 24 * 365
    train_end = len(closes_full) - N_TEST_2024
    closes_train = closes_full[:train_end].copy()
    closes_2024 = closes_full[train_end:].copy()
    logger.info("train=%d, 2024=%d", len(closes_train), len(closes_2024))

    # regime
    np.random.seed(42)
    detector = BTCRegimeDetector()
    regime_train = detector.detect(closes_train)
    regime_2024 = detector.detect(closes_2024)
    regime_full = np.concatenate([regime_train, regime_2024])

    epochs = 100
    horizon = 20
    n_paths = 200

    # === Model A: 静态模型 ===
    logger.info("=" * 60)
    logger.info("Model A: 静态模型 (2017-2023 训练, 不更新)")
    import torch
    torch.manual_seed(42)
    model_a = NeuralSDEModel(device="cpu")
    trainer_a = NeuralSDETrainer(model=model_a, lr=1e-4, seq_len=64, horizon=20,
                                 batch_size=64, loss_type="mse")
    t0 = time.time()
    report_a = trainer_a.train(closes_train, epochs=epochs,
                               regime_labels=regime_train, regime_balance="natural")
    logger.info("静态模型训练完成: %.1fs, loss=%.6f", time.time() - t0,
                report_a.get("final_loss", 0))

    # === Model B: 在线学习模型 (先相同训练) ===
    logger.info("=" * 60)
    logger.info("Model B: 在线学习模型 (相同初始训练)")
    torch.manual_seed(42)
    model_b = NeuralSDEModel(device="cpu")
    trainer_b = NeuralSDETrainer(model=model_b, lr=1e-4, seq_len=64, horizon=20,
                                 batch_size=64, loss_type="mse")
    trainer_b.train(closes_train, epochs=epochs,
                    regime_labels=regime_train, regime_balance="natural")

    online_trainer = NeuralSDEOnlineTrainer(
        base_model=model_b, fine_tune_lr=1e-5,
        rolling_window=24 * 365 * 2, ewc_lambda=1000.0,
    )
    # 初始化 EWC 状态 (用训练集计算 Fisher)
    online_trainer._fisher = online_trainer._compute_fisher(closes_train, regime_train)
    online_trainer._save_optimal_params()
    online_trainer._backup_full_retrain_state()

    # === Walk-forward: 按月滚动 ===
    # 每月: 用 train_end 到当前月的数据 fine-tune model_b, 然后评估两个模型
    n_months = 12
    monthly_points = len(closes_2024) // n_months
    results_a = []
    results_b = []

    for m in range(n_months):
        ft_end = train_end + (m + 1) * monthly_points
        eval_ts = ft_end  # 评估点 = fine-tune 数据末尾
        if eval_ts + horizon >= len(closes_full):
            continue

        logger.info("--- 月份 %d/%d: fine-tune 到 idx=%d, 评估 idx=%d ---",
                    m + 1, n_months, ft_end, eval_ts)

        # Model B: 用最近 2y 数据 fine-tune
        ft_start = max(0, ft_end - 24 * 365 * 2)
        ft_closes = closes_full[ft_start:ft_end]
        ft_regimes = regime_full[ft_start:ft_end]
        t0 = time.time()
        ft_report = online_trainer.fine_tune(ft_closes, regime_labels=ft_regimes, epochs=10)
        logger.info("  fine-tune: %.1fs, status=%s, loss=%.6f",
                    time.time() - t0, ft_report.get("status"), ft_report.get("final_loss", 0))

        # 评估两个模型
        r_a = evaluate_window(model_a, closes_full, eval_ts, horizon, n_paths, regime_full)
        r_b = evaluate_window(model_b, closes_full, eval_ts, horizon, n_paths, regime_full)
        if r_a and r_b:
            r_a["month"] = m + 1
            r_b["month"] = m + 1
            results_a.append(r_a)
            results_b.append(r_b)
            logger.info("  静态: MAE=%.1f ratio=%.2f | 在线: MAE=%.1f ratio=%.2f",
                        r_a["sde_mae"], r_a["ratio"], r_b["sde_mae"], r_b["ratio"])

    # 汇总
    def summarize(results):
        maes = [r["sde_mae"] for r in results]
        ratios = [r["ratio"] for r in results if r["ratio"] != float("inf")]
        return {
            "mean_mae": round(float(np.mean(maes)), 4),
            "mean_ratio": round(float(np.mean(ratios)), 4) if ratios else float("inf"),
            "n_windows": len(results),
        }

    sum_a = summarize(results_a)
    sum_b = summarize(results_b)
    improvement_pct = round((sum_a["mean_mae"] - sum_b["mean_mae"]) / sum_a["mean_mae"] * 100, 2)
    p01_pass = improvement_pct >= 10

    logger.info("=" * 60)
    logger.info("=== P0.1 在线学习对比结果 ===")
    logger.info("静态模型: MAE=%.2f, ratio=%.4f", sum_a["mean_mae"], sum_a["mean_ratio"])
    logger.info("在线模型: MAE=%.2f, ratio=%.4f", sum_b["mean_mae"], sum_b["mean_ratio"])
    logger.info("MAE 改善: %.2f%%", improvement_pct)
    logger.info("P0.1 闸门 (改善 ≥10%%): %s", "PASS" if p01_pass else "FAIL")

    out = {
        "tdd": "P0.1-online-learning-walk-forward",
        "purpose": "验证在线学习 (fine-tune + EWC) 在 2024 OOS 上的 MAE 改善",
        "config": {"epochs": epochs, "fine_tune_epochs": 10, "rolling_window_y": 2},
        "static": {**sum_a, "windows": results_a},
        "online": {**sum_b, "windows": results_b},
        "comparison": {
            "mae_improvement_pct": improvement_pct,
            "p01_gate_10pct_pass": bool(p01_pass),
        },
    }
    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p01_online_learning_walk_forward.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)

    return 0 if p01_pass else 2


if __name__ == "__main__":
    sys.exit(main())
