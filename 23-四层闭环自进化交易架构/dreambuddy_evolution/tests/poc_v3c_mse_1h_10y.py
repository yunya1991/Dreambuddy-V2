"""PoC v3c: 纯 MSE + 1h 10y 数据 (用户决策方案).

诊断总结:
- v2 (mse+17k 1h): MAE=269.51, ratio=0.31 ✅ PASS
- v3 (multitask+88k 30m): MAE=244676, ratio=753.87 ❌ — QLIKE 主导发散
- v3b (mse+88k 30m): MAE=512, ratio=1.54 ❌ — 30m horizon=20=10h 与 v2 1h horizon=20=20h 不可比

用户决策: 保持 1h 间隔 (horizon 时长一致), 下载 10 年 1h K 线 (~87k 点 5x 扩充)
- 1h × horizon=20 = 20h 预测窗口 (与 v2 一致)
- 10 年数据 vs v2 2 年数据 (17k → 87k 点)
- 纯 MSE loss (放弃 multitask, v3 已证失败)
- 期望: MAE < 269.51 (v2 基线), 进一步改善
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
    print("PoC v3c: 纯 MSE + 1h 10y 数据 (用户决策方案)")
    print("=" * 70)

    btc_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
    if not btc_path.exists():
        print(f"[FAIL] 数据未找到: {btc_path} (先跑 download_binance_klines.py --years 10 --interval 1h)")
        return 1
    closes = load_closes(btc_path)
    print(f"[1] 数据: {len(closes)} 点 (1h, 10y) ← {btc_path.name}")
    print(f"    首 3: {closes[:3].tolist()}")
    print(f"    末 3: {closes[-3:].tolist()}")
    print(f"    min={closes.min():.2f}, max={closes.max():.2f}")

    model = NeuralSDEModel(device="cpu")
    if not model.is_available:
        return 1
    # 纯 MSE (放弃 multitask, v3 已证失败)
    trainer = NeuralSDETrainer(
        model, lr=1e-4, seq_len=64, horizon=20, batch_size=64, loss_type="mse",
    )
    print(f"[2] loss_type=mse, sig_dim={model.sig_dim} (与 v2 一致, 仅数据扩充)")

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
    print(f"    NeuralSDE (mse+1h+10y): {mae['neural_sde_mae']:.4f}")
    print(f"    GARCH:                  {mae['garch_mae']:.4f}")
    print(f"    ratio:                  {mae['ratio']}")
    print(f"    [对照] PoC v2 (mse+1h+2y): MAE=269.51, ratio=0.31 ✅")
    print(f"    [对照] PoC v3b (mse+30m+5y): MAE=512, ratio=1.54 ❌")

    threshold = 1.2 * mae["garch_mae"]
    passed = mae["neural_sde_mae"] <= threshold
    improved_vs_v2 = mae["neural_sde_mae"] < 269.51
    print(f"[5] 闸门: {mae['neural_sde_mae']:.4f} <= {threshold:.4f} ? {'PASS' if passed else 'FAIL'}")
    print(f"    vs v2:  {mae['neural_sde_mae']:.4f} < 269.51 ? {'IMPROVED' if improved_vs_v2 else 'NO IMPROVEMENT'}")

    poc_report = {
        "tdd": "TDD-013-v3c",
        "round": "3c",
        "user_decision": "1h K线 10年 (保持 horizon 时长一致)",
        "data_source": "binance_btcusdt_1h_10y",
        "data_size": int(len(closes)),
        "epochs": 200,
        "n_windows": report["n_windows"],
        "final_loss": report["final_loss"],
        "loss_type": "mse",
        "sig_dim": report.get("sig_dim"),
        "mae_comparison": mae,
        "baseline_v2_mse_1h_2y": {"neural_sde_mae": 269.51, "garch_mae": 881.14, "ratio": 0.31},
        "baseline_v3_multitask_30m_5y": {"neural_sde_mae": 244676.63, "ratio": 753.87},
        "baseline_v3b_mse_30m_5y": {"neural_sde_mae": 512.04, "ratio": 1.54},
        "threshold": threshold,
        "passed": passed,
        "improved_vs_v2": improved_vs_v2,
        "elapsed_sec": round(elapsed, 2),
    }
    report_path = REPO / "dreambuddy_evolution" / "data" / "neural_sde_v1_poc_v3c_1h_10y.json"
    report_path.write_text(json.dumps(poc_report, indent=2), encoding="utf-8")
    print(f"[6] 报告 → {report_path}")

    weight_path = REPO / "dreambuddy_evolution" / "data" / "neural_sde_v1_mse_1h_10y_v3c.pt"
    model.save(str(weight_path))
    print(f"[7] 权重 → {weight_path}")

    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
