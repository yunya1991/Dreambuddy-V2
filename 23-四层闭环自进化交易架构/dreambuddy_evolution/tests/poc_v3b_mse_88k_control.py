"""PoC v3b 对照实验: 纯 MSE + 88K 点 (隔离 multitask 影响).

诊断 PoC v3 失败根因: multitask loss vs 数据扩充, 哪个导致 MAE 发散?
- v3b: 纯 MSE + 88K 点 → 若 MAE < 269.51, 则数据扩充有效, multitask 是祸首
- v3b: 若 MAE ≈ 244676, 则 30m K 线噪声本身是问题

只修改 loss_type="mse", 其他参数与 PoC v3 完全一致.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer
from dreambuddy_evolution.core.garch_fallback import GARCHFallback


def load_closes(path: Path) -> np.ndarray:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return np.array(data, dtype=np.float64)
    raise ValueError("无法解析 close 序列")


def evaluate_mae(model, garch, closes, horizon=20, n_paths=200):
    closes = np.asarray(closes, dtype=np.float64).ravel()
    n = len(closes)
    test_start = n - horizon - 1
    history = closes[: test_start + 1]
    actual = closes[test_start + 1 : test_start + 1 + horizon]
    init_price = float(history[-1])
    returns = np.diff(np.log(history))
    init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02

    garch.estimate(returns)
    garch_paths = garch.simulate(n_paths, horizon, init_price, init_vol)
    garch_pred = np.mean(garch_paths[:, 1:], axis=0)
    garch_mae = float(np.mean(np.abs(garch_pred - actual)))

    sde_paths = model.forecast(history, horizon, n_paths)
    sde_mae = float(np.mean(np.abs(np.mean(sde_paths[:, 1:], axis=0) - actual))) if sde_paths is not None else float("inf")

    return {
        "neural_sde_mae": round(sde_mae, 6),
        "garch_mae": round(garch_mae, 6),
        "improvement": round(garch_mae - sde_mae, 6) if sde_mae != float("inf") else 0.0,
        "ratio": round(sde_mae / garch_mae, 4) if garch_mae > 0 and sde_mae != float("inf") else float("inf"),
    }


def main():
    print("=" * 70)
    print("PoC v3b 对照: 纯 MSE + 88K 点 (隔离 multitask 影响)")
    print("=" * 70)

    btc_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_30m.json"
    closes = load_closes(btc_path)
    print(f"[1] 数据: {len(closes)} 点 (30m, 5y)")

    model = NeuralSDEModel(device="cpu")
    if not model.is_available:
        return 1
    # 唯一差异: loss_type="mse" (与 PoC v2 一致, 与 v3 multitask 对照)
    trainer = NeuralSDETrainer(
        model, lr=1e-4, seq_len=64, horizon=20, batch_size=64, loss_type="mse",
    )
    print(f"[2] loss_type=mse (与 PoC v3 唯一差异)")

    t0 = time.time()
    report = trainer.train(closes, epochs=200)
    elapsed = time.time() - t0
    if report["status"] != "ok":
        print(f"[FAIL] {report}")
        return 1
    print(f"[3] 训练: 200ep, final_loss={report['final_loss']:.6f}, n_windows={report['n_windows']}, 耗时={elapsed:.1f}s")

    garch = GARCHFallback()
    mae = evaluate_mae(model, garch, closes, horizon=20, n_paths=200)
    print(f"[4] MAE:")
    print(f"    NeuralSDE (mse+88k): {mae['neural_sde_mae']:.4f}")
    print(f"    GARCH:               {mae['garch_mae']:.4f}")
    print(f"    ratio:               {mae['ratio']}")
    print(f"    [对照] PoC v2 (mse+17k): MAE=269.51, ratio=0.31")
    print(f"    [对照] PoC v3 (multitask+88k): MAE=244676, ratio=753.87")

    threshold = 1.2 * mae["garch_mae"]
    passed = mae["neural_sde_mae"] <= threshold
    print(f"[5] 闸门: {mae['neural_sde_mae']:.4f} <= {threshold:.4f} ? {'PASS' if passed else 'FAIL'}")

    poc_report = {
        "tdd": "TDD-013-v3b-control",
        "round": "3b",
        "purpose": "隔离 multitask 影响 (vs PoC v3)",
        "data_source": "binance_btcusdt_30m_5y",
        "data_size": int(len(closes)),
        "epochs": 200,
        "n_windows": report["n_windows"],
        "final_loss": report["final_loss"],
        "loss_type": "mse",
        "sig_dim": report.get("sig_dim"),
        "mae_comparison": mae,
        "baseline_v2_mse_17k": {"neural_sde_mae": 269.51, "garch_mae": 881.14, "ratio": 0.31},
        "baseline_v3_multitask_88k": {"neural_sde_mae": 244676.63, "garch_mae": 324.56, "ratio": 753.87},
        "threshold": threshold,
        "passed": passed,
        "elapsed_sec": round(elapsed, 2),
    }
    report_path = REPO / "dreambuddy_evolution" / "data" / "neural_sde_v1_poc_v3b_control.json"
    report_path.write_text(json.dumps(poc_report, indent=2), encoding="utf-8")
    print(f"[6] 报告 → {report_path}")

    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
