"""E7 PoC: P1 外生力量接入 walk-forward 2024 OOS 对比.

方案: 23-四层闭环自进化交易架构/PLAN-exogenous-integration.md §三

对比两个配置 (仅差 exogenous 开关, 其余完全一致):
  - Config A (baseline, ratio=0.963 已落盘 walk_forward_2024_oos.json):
      NeuralSDEModel(n_regimes=3, use_moe=True, moe_routing="hard", dropout=0.05)
      trainer(lr=1e-4, seq_len=64, horizon=20, batch_size=64, loss_type="return_mse",
              weight_decay=1e-4, patience=10, val_split=0.1)
      train(epochs=250, regime_balance="natural")
  - Config B (P1 exogenous 9 维, 本次脚本训练):
      同 A + use_exogenous=True, exogenous_dim=9
      + exogenous_series=build_exogenous_series(closes_train)
      + forecast 时 exogenous_snapshot=full_exo_series[test_start_idx]

闸门: ratio_B < 0.93 (vs A=0.963, 改善 ≥3.4%)
FAIL-OPEN: 若 exo 构建失败或 ratio 恶化, 报告 ratio_B 但不修改 baseline
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
from dreambuddy_evolution.core.exogenous_data_bridge import build_exogenous_series

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def evaluate_on_windows(model, closes, test_starts, regime_labels,
                         full_exo_series, n_paths=200, horizon=20):
    """在 12 个月度窗口上评估 SDE (with exogenous_snapshot) vs GARCH."""
    results = []
    for ts in test_starts:
        history = closes[:ts + 1]
        actual = closes[ts + 1:ts + 1 + horizon]
        init_price = float(history[-1])
        returns = np.diff(np.log(history))
        init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02

        # GARCH baseline (与 Config A 完全一致)
        garch = GARCHFallback()
        garch.estimate(returns)
        garch_paths = garch.simulate(n_paths, horizon, init_price, init_vol)
        garch_pred = np.mean(garch_paths[:, 1:], axis=0)
        garch_mae = float(np.mean(np.abs(garch_pred - actual)))

        # NeuralSDE (MoE + exogenous_snapshot)
        test_regime = int(regime_labels[ts])
        # 取测试起点的外生快照 (9,)
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
    if not data_path.exists():
        logger.error("数据不存在: %s", data_path)
        return 1
    with open(data_path) as f:
        closes_full = np.array(json.load(f), dtype=np.float64)
    logger.info("加载 BTC 10y 1h close: %d 点", len(closes_full))

    N_TEST_2024 = 24 * 365
    train_end = len(closes_full) - N_TEST_2024
    closes_train = closes_full[:train_end].copy()
    logger.info("Walk-forward: train=%d (2017-2023), test=%d (2024)",
                train_end, N_TEST_2024)

    # Regime detection (与 Config A 一致, seed=42)
    np.random.seed(42)
    detector = BTCRegimeDetector()
    regime_train = detector.detect(closes_train)
    regime_test = detector.detect(closes_full[train_end:])
    regime_full = np.concatenate([regime_train, regime_test])
    counts = np.bincount(regime_train, minlength=3)
    logger.info("训练集 regime 分布: bull=%d (%.1f%%) chop=%d (%.1f%%) bear=%d (%.1f%%)",
                counts[0], 100 * counts[0] / len(closes_train),
                counts[1], 100 * counts[1] / len(closes_train),
                counts[2], 100 * counts[2] / len(closes_train))

    # ===== P1 关键步骤: 构建外生力量时序 =====
    # 1) 训练集外生时序 (传给 trainer.train)
    t_exo = time.time()
    logger.info("构建训练集外生时序 (n=%d)...", len(closes_train))
    exo_train = build_exogenous_series(closes_train, bridge=None)
    logger.info("训练集外生时序完成: shape=%s, 耗时=%.1fs",
                exo_train.shape, time.time() - t_exo)

    # 2) 全量外生时序 (用于 test_start 处取 snapshot)
    t_exo2 = time.time()
    logger.info("构建全量外生时序 (n=%d, 用于测试快照)...", len(closes_full))
    exo_full = build_exogenous_series(closes_full, bridge=None)
    logger.info("全量外生时序完成: shape=%s, 耗时=%.1fs",
                exo_full.shape, time.time() - t_exo2)

    # 数据健全性: exo_train 非全 0.5 (至少技术面应有信号)
    non_neutral_train = float(np.mean(np.any(exo_train != 0.5, axis=1)))
    non_neutral_full = float(np.mean(np.any(exo_full != 0.5, axis=1)))
    logger.info("外生时序非中性比例: train=%.3f, full=%.3f (应 >0.0)",
                non_neutral_train, non_neutral_full)

    # ===== 训练 Config B (MoE + exogenous 9 维) =====
    import torch
    torch.manual_seed(42)
    model = NeuralSDEModel(
        device="cpu", n_regimes=3,
        use_moe=True, moe_routing="hard",
        dropout=0.05,
        use_exogenous=True, exogenous_dim=9,  # P1 关键开关
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
        exogenous_series=exo_train,  # P1 关键注入
    )
    train_time = time.time() - t0
    logger.info("Config B 训练完成: status=%s, n_windows=%d, final_loss=%.6f, 耗时=%.1fs",
                report.get("status"), report.get("n_windows", 0),
                report.get("final_loss", 0.0), train_time)

    if report.get("status") != "ok":
        logger.error("Config B 训练未完成: %s", report)
        return 1

    # ===== 在 12 个月度窗口上评估 =====
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
        regime_labels=regime_full, full_exo_series=exo_full,
        n_paths=200,
    )

    sde_maes = [r["sde_mae"] for r in results]
    garch_maes = [r["garch_mae"] for r in results]
    ratios = [r["ratio"] for r in results]

    mean_sde_mae_b = float(np.mean(sde_maes))
    median_sde_mae_b = float(np.median(sde_maes))
    mean_garch_mae = float(np.mean(garch_maes))
    mean_ratio_b = float(np.mean(ratios))
    max_ratio_b = float(np.max(ratios))

    # ===== 加载 Config A baseline =====
    baseline_path = REPO / "dreambuddy_evolution" / "data" / "walk_forward_2024_oos.json"
    baseline_a = {}
    if baseline_path.exists():
        with open(baseline_path) as f:
            baseline_a = json.load(f)
    mean_ratio_a = float(baseline_a.get("summary", {}).get("mean_ratio", 0.963))
    mean_sde_mae_a = float(baseline_a.get("summary", {}).get("mean_sde_mae", 901.98))

    # 改善 (越负越好)
    improvement_ratio = (mean_ratio_b - mean_ratio_a) / mean_ratio_a * 100
    improvement_mae = (mean_sde_mae_b - mean_sde_mae_a) / mean_sde_mae_a * 100

    # ===== 闸门 =====
    gate_p1_target = mean_ratio_b < 0.93          # P1 目标
    gate_improvement = mean_ratio_b < mean_ratio_a  # 至少不恶化
    gate_strict = mean_ratio_b < 1.0              # 优于 GARCH
    gate_1_2x = mean_ratio_b < 1.2                # 不显著差于 GARCH

    logger.info("=" * 60)
    logger.info("=== E7 PoC: P1 外生力量 walk-forward 2024 对比 ===")
    logger.info("Config A (baseline): MAE=%.2f, ratio=%.4f", mean_sde_mae_a, mean_ratio_a)
    logger.info("Config B (exogenous): MAE=%.2f, median=%.2f, ratio=%.4f, max_ratio=%.4f",
                mean_sde_mae_b, median_sde_mae_b, mean_ratio_b, max_ratio_b)
    logger.info("GARCH baseline:       MAE=%.2f", mean_garch_mae)
    logger.info("改善 ratio: %+.2f%% (越负越好)", improvement_ratio)
    logger.info("改善 MAE:   %+.2f%% (越负越好)", improvement_mae)
    logger.info("P1 闸门 <0.93:   %s", "PASS" if gate_p1_target else "FAIL")
    logger.info("至少不恶化:       %s", "PASS" if gate_improvement else "FAIL")
    logger.info("OOS strict <1.0: %s", "PASS" if gate_strict else "FAIL")
    logger.info("OOS 1.2x:        %s", "PASS" if gate_1_2x else "FAIL")

    out = {
        "tdd": "E7-poc-p1-exogenous-walk-forward",
        "purpose": "对比 P1 外生力量接入 (Config B) vs baseline (Config A) 在 2024 OOS 上表现",
        "config": {
            "A_baseline": {
                "mean_sde_mae": mean_sde_mae_a,
                "mean_ratio": mean_ratio_a,
                "source": str(baseline_path),
            },
            "B_exogenous": {
                "use_moe": True, "moe_routing": "hard",
                "use_exogenous": True, "exogenous_dim": 9,
                "loss_type": "return_mse", "dropout": 0.05,
                "weight_decay": 1e-4, "lr": 1e-4, "epochs": 250,
                "n_regimes": 3, "patience": 10, "val_split": 0.1,
                "regime_balance": "natural",
            },
            "exo_data_sanity": {
                "train_non_neutral_ratio": round(non_neutral_train, 4),
                "full_non_neutral_ratio": round(non_neutral_full, 4),
            },
            "data": "btc_close_10y.json",
            "train_points": int(len(closes_train)),
            "test_points_2024": int(N_TEST_2024),
            "seed": 42,
            "horizon": 20,
            "n_paths": 200,
            "n_test_windows": len(results),
        },
        "train_summary_b": {
            "n_windows": int(report.get("n_windows", 0)),
            "final_loss": float(report.get("final_loss", 0.0)),
            "train_time_sec": round(train_time, 2),
            "train_regime_distribution": {
                "bull": int(counts[0]),
                "chop": int(counts[1]),
                "bear": int(counts[2]),
            },
        },
        "summary_b": {
            "mean_sde_mae": round(mean_sde_mae_b, 4),
            "median_sde_mae": round(median_sde_mae_b, 4),
            "mean_garch_mae": round(mean_garch_mae, 4),
            "mean_ratio": round(mean_ratio_b, 4),
            "max_ratio": round(max_ratio_b, 4),
        },
        "comparison": {
            "delta_ratio_pct": round(improvement_ratio, 4),
            "delta_mae_pct": round(improvement_mae, 4),
            "A_ratio": round(mean_ratio_a, 4),
            "B_ratio": round(mean_ratio_b, 4),
        },
        "gates": {
            "p1_target_lt_0.93": bool(gate_p1_target),
            "no_regression_vs_A": bool(gate_improvement),
            "oos_strict_lt_1.0": bool(gate_strict),
            "oos_1_2x": bool(gate_1_2x),
        },
        "windows": results,
    }
    out_path = REPO / "dreambuddy_evolution" / "data" / "poc_p1_exogenous_walk_forward.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    logger.info("报告: %s", out_path)

    # 闸门: P1 目标 ratio<0.93
    return 0 if gate_p1_target else 2


if __name__ == "__main__":
    sys.exit(main())
