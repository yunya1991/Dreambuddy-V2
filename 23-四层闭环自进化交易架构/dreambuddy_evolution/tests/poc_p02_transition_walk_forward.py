"""P0.2 PoC: regime-transition walk-forward 对比.

目的:
  验证 transition-aware NeuralSDE (use_transition=True) 相比原 regime-aware 模型
  (use_transition=False) 在 2024 OOS 上的 MAE 改善.

  T7 OOS 根因 3: regime 标签同质化 — 仅 regime one-hot 无法区分同标签不同动态.
  P0.2 解法: drift_net 输入加 transition vector (Q[current_regime]),
  让模型学习 regime 切换动态.

对比设计:
  - Model A (baseline): use_transition=False (T5 v4 配置)
  - Model B (P0.2):     use_transition=True (加 transition vector)
  - 相同训练集 (2017-2023), 相同 epochs, 相同种子
  - 相同 12 个 2024 测试窗口
  - 指标: OOS mean MAE, mean ratio (SDE/GARCH)

输出: dreambuddy_evolution/data/poc_p02_transition_walk_forward.json
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
    regime_labels: np.ndarray,
    Q: np.ndarray | None,
    n_paths: int = 200,
    horizon: int = 20,
) -> list[dict]:
    """在多个测试窗口上评估 MAE.

    Args:
        Q: 转移矩阵 (n_regimes, n_regimes), None → 不传递 transition (baseline)
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
        # P0.2: transition vector = Q[test_regime]
        transition = None
        if Q is not None and test_regime is not None and 0 <= test_regime < Q.shape[0]:
            transition = Q[test_regime]
        sde_paths = model.forecast(
            history, horizon, n_paths,
            regime=test_regime, transition=transition,
        )
        if sde_paths is None:
            sde_mae = float("inf")
        else:
            sde_pred = np.mean(sde_paths[:, 1:], axis=0)
            sde_mae = float(np.mean(np.abs(sde_pred - actual)))

        results.append({
            "test_start_idx": int(ts),
            "test_price_start": round(float(closes[ts]), 2),
            "test_regime": test_regime,
            "sde_mae": round(sde_mae, 4),
            "garch_mae": round(garch_mae, 4),
            "ratio": round(sde_mae / garch_mae, 4) if garch_mae > 0 else float("inf"),
        })
    return results


def train_and_evaluate(
    closes_train: np.ndarray,
    closes_full: np.ndarray,
    regime_labels_train: np.ndarray,
    regime_labels_full: np.ndarray,
    test_starts: list[int],
    use_transition: bool,
    epochs: int = 100,
    seed: int = 42,
) -> dict:
    """训练一个模型并评估."""
    import torch
    torch.manual_seed(seed)
    np.random.seed(seed)

    model = NeuralSDEModel(device="cpu", use_transition=use_transition)
    if not model.is_available:
        return {"status": "skipped", "reason": "torch not available"}

    trainer = NeuralSDETrainer(
        model=model, lr=1e-4, seq_len=64, horizon=20,
        batch_size=64, loss_type="mse",
    )

    t0 = time.time()
    report = trainer.train(
        closes_train, epochs=epochs,
        regime_labels=regime_labels_train,
        regime_balance="natural",
    )
    train_time = time.time() - t0
    logger.info("[%s] 训练完成: n_windows=%d, final_loss=%.6f, 耗时=%.1fs",
                "transition" if use_transition else "baseline",
                report.get("n_windows", 0), report.get("final_loss", 0.0), train_time)

    if report.get("status") != "ok":
        return {"status": "train_failed", "report": report}

    # 估计测试集上的 Q (P0.2)
    Q = None
    if use_transition:
        detector = BTCRegimeDetector(n_regimes=model.n_regimes)
        Q = detector.estimate_transition_matrix(regime_labels_full)
        pi = detector.stationary_distribution(Q)
        logger.info("[transition] 全量 Q 矩阵:\n%s", np.round(Q, 3))
        logger.info("[transition] 平稳分布 π=%s", np.round(pi, 3))

    results = evaluate_on_windows(
        model=model,
        closes=closes_full,
        test_starts=test_starts,
        regime_labels=regime_labels_full,
        Q=Q,
        n_paths=200,
        horizon=20,
    )

    sde_maes = [r["sde_mae"] for r in results]
    garch_maes = [r["garch_mae"] for r in results]
    ratios = [r["ratio"] for r in results if r["ratio"] != float("inf")]

    return {
        "status": "ok",
        "use_transition": use_transition,
        "final_loss": float(report.get("final_loss", 0.0)),
        "n_windows": int(report.get("n_windows", 0)),
        "train_time_sec": round(train_time, 2),
        "windows": results,
        "mean_sde_mae": round(float(np.mean(sde_maes)), 4),
        "mean_garch_mae": round(float(np.mean(garch_maes)), 4),
        "mean_ratio": round(float(np.mean(ratios)), 4) if ratios else float("inf"),
    }


def main():
    data_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
    if not data_path.exists():
        logger.error("数据不存在: %s", data_path)
        return 1

    with open(data_path) as f:
        closes_full = np.array(json.load(f), dtype=np.float64)
    logger.info("加载 BTC 10y 1h close: %d 点", len(closes_full))

    # Walk-forward 切分 (与 T7 一致)
    N_TEST_2024 = 24 * 365
    train_end = len(closes_full) - N_TEST_2024
    closes_train = closes_full[:train_end].copy()
    closes_test = closes_full[train_end:].copy()
    logger.info("train=%d (2017-2023), test=%d (2024)", len(closes_train), len(closes_test))

    # 训练集 regime
    np.random.seed(42)
    detector = BTCRegimeDetector()
    regime_labels_train = detector.detect(closes_train)

    # 全量 regime (训练+测试)
    regime_labels_test = detector.detect(closes_test)
    regime_labels_full = np.concatenate([regime_labels_train, regime_labels_test])

    # 12 个测试窗口
    n_test = len(closes_test)
    monthly_step = max(1, n_test // 12)
    test_starts = [
        train_end + i * monthly_step
        for i in range(12)
        if train_end + i * monthly_step + 20 < len(closes_full)
    ]
    logger.info("测试窗口: %d 个", len(test_starts))

    epochs = 100  # PoC 快速验证 (T7 用 200)

    # Model A: baseline (use_transition=False)
    logger.info("=" * 60)
    logger.info("Model A: baseline (use_transition=False)")
    result_a = train_and_evaluate(
        closes_train, closes_full, regime_labels_train, regime_labels_full,
        test_starts, use_transition=False, epochs=epochs,
    )

    # Model B: transition-aware (use_transition=True)
    logger.info("=" * 60)
    logger.info("Model B: transition-aware (use_transition=True)")
    result_b = train_and_evaluate(
        closes_train, closes_full, regime_labels_train, regime_labels_full,
        test_starts, use_transition=True, epochs=epochs,
    )

    # 对比汇总
    if result_a.get("status") == "ok" and result_b.get("status") == "ok":
        mae_a = result_a["mean_sde_mae"]
        mae_b = result_b["mean_sde_mae"]
        ratio_a = result_a["mean_ratio"]
        ratio_b = result_b["mean_ratio"]
        improvement_pct = round((mae_a - mae_b) / mae_a * 100, 2) if mae_a > 0 else 0.0
        ratio_improvement = round(ratio_a - ratio_b, 4)

        logger.info("=" * 60)
        logger.info("=== P0.2 对比结果 ===")
        logger.info("Baseline (no transition):  MAE=%.2f, ratio=%.4f", mae_a, ratio_a)
        logger.info("Transition-aware:          MAE=%.2f, ratio=%.4f", mae_b, ratio_b)
        logger.info("MAE 改善: %.2f%% (%.2f → %.2f)", improvement_pct, mae_a, mae_b)
        logger.info("Ratio 改善: %.4f (%.4f → %.4f)", ratio_improvement, ratio_a, ratio_b)
        p02_pass = improvement_pct >= 10  # 目标: ≥10% MAE 改善
        logger.info("P0.2 闸门 (MAE 改善 ≥10%%): %s", "PASS" if p02_pass else "FAIL")
    else:
        improvement_pct = 0.0
        ratio_improvement = 0.0
        p02_pass = False

    out = {
        "tdd": "P0.2-transition-walk-forward",
        "purpose": "验证 transition-aware NeuralSDE 在 2024 OOS 上的 MAE 改善",
        "config": {
            "epochs": epochs,
            "seed": 42,
            "regime_balance": "natural",
            "n_regimes": 3,
            "n_test_windows": len(test_starts),
        },
        "baseline": result_a,
        "transition_aware": result_b,
        "comparison": {
            "mae_improvement_pct": improvement_pct,
            "ratio_improvement": ratio_improvement,
            "p02_gate_10pct_pass": bool(p02_pass),
        },
    }

    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p02_transition_walk_forward.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)

    return 0 if p02_pass else 2


if __name__ == "__main__":
    sys.exit(main())
