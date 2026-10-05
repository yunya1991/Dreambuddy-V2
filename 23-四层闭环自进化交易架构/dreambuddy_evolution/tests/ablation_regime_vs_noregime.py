"""T6 Ablation: regime vs no-regime 对照 (量化 regime 贡献).

目的:
  量化 regime-aware 训练对 NeuralSDE MAE 的贡献.
  T5 v4 已 PASS (regime-aware MAE=314.89), 但缺少 no-regime 对照.
  本脚本跑同种子、同数据、同 epochs 的两路实验:
    A. no-regime: regime_labels=None (所有窗口 regime=0, drift_net 收 [1,0,0] 常量)
    B. regime:   regime_labels=actual (每窗口 regime 来自 BTCRegimeDetector)

  两者唯一差异 = drift_net 输入是否携带 regime one-hot 条件信息.
  预期: A 退化 (MAE 接近 v3c 569), B 保持 314.89.
  量化: regime_contribution = MAE_A - MAE_B (正=regime 有效)

输出: dreambuddy_evolution/data/ablation_regime_vs_noregime.json
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


def _train_and_evaluate(
    closes: np.ndarray,
    regime_labels: np.ndarray | None,
    regime_balance: str,
    seed: int,
    epochs: int = 200,
    label: str = "",
) -> dict:
    """训练一个 NeuralSDE 并评估 MAE.

    Args:
        closes: 全量 close 序列
        regime_labels: None=no-regime, ndarray=regime-aware
        regime_balance: "natural" 或 "balanced"
        seed: 随机种子 (保证 A/B 同种子对照)
        epochs: 训练轮数
        label: 实验标签 (用于日志)

    Returns:
        dict with mae, n_windows, final_loss, train_time, test_regime
    """
    np.random.seed(seed)
    import torch
    torch.manual_seed(seed)

    model = NeuralSDEModel(device="cpu")
    if not model.is_available:
        raise RuntimeError("torch 不可用")

    trainer = NeuralSDETrainer(
        model=model, lr=1e-4, seq_len=64, horizon=20,
        batch_size=64, loss_type="mse",
    )

    t0 = time.time()
    report = trainer.train(
        closes, epochs=epochs,
        regime_labels=regime_labels,
        regime_balance=regime_balance,
    )
    train_time = time.time() - t0
    logger.info("[%s] 训练: status=%s, n_windows=%d, final_loss=%.6f, 耗时=%.1fs",
                label, report.get("status"), report.get("n_windows", 0),
                report.get("final_loss", 0.0), train_time)

    if report.get("status") != "ok":
        raise RuntimeError(f"[{label}] 训练未完成: {report}")

    # 评估 MAE (与 PoC v4 一致: 用最后 horizon 步)
    horizon = 20
    n_paths = 200
    n = len(closes)
    test_start = n - horizon - 1
    history = closes[:test_start + 1]
    actual = closes[test_start + 1:test_start + 1 + horizon]

    # regime-aware 模型推理需要 regime 标签; no-regime 模型传 0 (匹配训练分布)
    # 关键: 训练时 regime_labels=None → 所有窗口 regime=0 → drift_net 收 [1,0,0] 常量
    #   测试时必须传 regime=0 (而非 None), 否则 drift_net pad zeros [0,0,0] 造成
    #   train/test 分布失配, MAE 被人为放大, ablation 不公平.
    if regime_labels is not None:
        test_regime = int(regime_labels[test_start])
    else:
        test_regime = 0  # 匹配训练分布 (regime_labels=None → 全 0)

    sde_paths = model.forecast(history, horizon, n_paths, regime=test_regime)
    if sde_paths is None:
        sde_mae = float("inf")
    else:
        sde_pred = np.mean(sde_paths[:, 1:], axis=0)
        sde_mae = float(np.mean(np.abs(sde_pred - actual)))

    return {
        "label": label,
        "mae": sde_mae,
        "n_windows": int(report.get("n_windows", 0)),
        "final_loss": float(report.get("final_loss", 0.0)),
        "train_time_sec": round(train_time, 2),
        "test_regime": test_regime,
    }


def main():
    data_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
    if not data_path.exists():
        logger.error("数据不存在: %s", data_path)
        return 1

    with open(data_path) as f:
        closes = np.array(json.load(f), dtype=np.float64)
    logger.info("加载 BTC 10y 1h close: %d 点, $%.2f → $%.2f",
                len(closes), closes[0], closes[-1])

    # 检测 regime labels
    detector = BTCRegimeDetector()
    regime_labels = detector.detect(closes)
    counts = np.bincount(regime_labels, minlength=3)
    logger.info("regime 分布: bull=%d (%.1f%%) chop=%d (%.1f%%) bear=%d (%.1f%%)",
                counts[0], 100*counts[0]/len(closes),
                counts[1], 100*counts[1]/len(closes),
                counts[2], 100*counts[2]/len(closes))

    # GARCH baseline (固定参照)
    horizon = 20
    n = len(closes)
    test_start = n - horizon - 1
    history = closes[:test_start + 1]
    actual = closes[test_start + 1:test_start + 1 + horizon]
    init_price = float(history[-1])
    returns = np.diff(np.log(history))
    init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02
    garch = GARCHFallback()
    garch.estimate(returns)
    garch_paths = garch.simulate(200, horizon, init_price, init_vol)
    garch_pred = np.mean(garch_paths[:, 1:], axis=0)
    garch_mae = float(np.mean(np.abs(garch_pred - actual)))
    logger.info("GARCH baseline MAE: %.2f", garch_mae)

    SEED = 42
    EPOCHS = 200

    # === 实验 A: no-regime (regime_labels=None) ===
    logger.info("=" * 60)
    logger.info("实验 A: no-regime (regime_labels=None, drift_net 收常量 one-hot)")
    logger.info("=" * 60)
    result_a = _train_and_evaluate(
        closes=closes,
        regime_labels=None,           # ← 关键: 无 regime 信息
        regime_balance="natural",     # 与 B 唯一差异 = 无 regime labels
        seed=SEED,
        epochs=EPOCHS,
        label="A-no-regime",
    )

    # === 实验 B: regime-aware (regime_labels=actual) ===
    logger.info("=" * 60)
    logger.info("实验 B: regime-aware (regime_labels=actual)")
    logger.info("=" * 60)
    result_b = _train_and_evaluate(
        closes=closes,
        regime_labels=regime_labels,  # ← 关键: 实际 regime 标签
        regime_balance="natural",
        seed=SEED,
        epochs=EPOCHS,
        label="B-regime",
    )

    # === 对比报告 ===
    regime_contribution = result_a["mae"] - result_b["mae"]
    improvement_pct = (
        (result_a["mae"] - result_b["mae"]) / max(result_a["mae"], 1e-8) * 100
    )
    # regime 是否有效: A 退化 (MAE_A > MAE_B) 且差异 > 5%
    regime_effective = (regime_contribution > 0) and (improvement_pct > 5.0)

    out = {
        "tdd": "T6-ablation",
        "purpose": "regime vs no-regime 对照, 量化 regime 贡献",
        "config": {
            "data": "btc_close_10y.json",
            "n_points": int(len(closes)),
            "epochs": EPOCHS,
            "seed": SEED,
            "regime_balance": "natural",
            "n_regimes": 3,
            "regime_distribution": {
                "bull": int(counts[0]),
                "chop": int(counts[1]),
                "bear": int(counts[2]),
            },
        },
        "experiment_a_no_regime": result_a,
        "experiment_b_regime": result_b,
        "garch_baseline_mae": garch_mae,
        "comparison": {
            "regime_contribution": round(regime_contribution, 4),
            "improvement_pct": round(improvement_pct, 2),
            "interpretation": (
                f"regime 输入让 MAE 从 {result_a['mae']:.2f} → {result_b['mae']:.2f} "
                f"(改善 {regime_contribution:.2f}, {improvement_pct:.1f}%)"
            ),
            "regime_effective": bool(regime_effective),
            "threshold_pct": 5.0,
        },
        "reference_baselines": {
            "v3c_no_regime_10y": 569,
            "v4_regime_10y_natural": 314.89,
            "v2_no_regime_2y": 269,
        },
    }

    out_path = REPO / "dreambuddy_evolution" / "data" / "ablation_regime_vs_noregime.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info("=== Ablation 对照结果 ===")
    logger.info("实验 A (no-regime):  MAE=%.2f", result_a["mae"])
    logger.info("实验 B (regime):     MAE=%.2f", result_b["mae"])
    logger.info("GARCH baseline:       MAE=%.2f", garch_mae)
    logger.info("regime 贡献:          %.2f (改善 %.1f%%)",
                regime_contribution, improvement_pct)
    logger.info("regime 是否有效:     %s (阈值>5%%)", "YES" if regime_effective else "NO")
    logger.info("报告: %s", out_path)

    # 闸门: regime 必须有效 (MAE_A > MAE_B 且改善 > 5%)
    return 0 if regime_effective else 2


if __name__ == "__main__":
    sys.exit(main())
