"""TDD-007 PoC 风险闸门: 30 ep 训练 + MAE ≤ 1.2× GARCH.

验证路径依赖 SDE 升级后, 30 epochs 训练的 NeuralSDE MAE 是否进入 GARCH 同水平.
- 用 btc_close.json 真实数据训练
- forecast(history, ...) 调用使用 path-signature
- 对比 GARCH baseline MAE
- 闸门: neural_sde_mae <= 1.2 * garch_mae (≤ 1000)

通过 → 可推进 TDD-008 (200 ep 完整训练)
失败 → 回滚到马尔可夫 MLP 架构
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
    if isinstance(data, dict) and "close" in data:
        return np.array(data["close"], dtype=np.float64)
    raise ValueError("无法解析 close 序列")


def evaluate_mae_path_dependent(
    model: NeuralSDEModel,
    garch: GARCHFallback,
    closes: np.ndarray,
    horizon: int = 20,
    n_paths: int = 200,
) -> dict[str, float]:
    """对比 Neural SDE (路径依赖) vs GARCH 的预测 MAE.

    关键: 用 forecast(history, ...) 调用, 让模型使用 path-signature.
    """
    closes = np.asarray(closes, dtype=np.float64).ravel()
    n = len(closes)
    if n < horizon + 100:
        return {"neural_sde_mae": 0.0, "garch_mae": 0.0, "improvement": 0.0}

    test_start = n - horizon - 1
    history = closes[: test_start + 1]
    actual = closes[test_start + 1 : test_start + 1 + horizon]
    init_price = float(history[-1])
    returns = np.diff(np.log(history))
    init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02

    # GARCH MAE (baseline)
    garch.estimate(returns)
    garch_paths = garch.simulate(n_paths, horizon, init_price, init_vol)
    garch_pred = np.mean(garch_paths[:, 1:], axis=0)
    garch_mae = float(np.mean(np.abs(garch_pred - actual)))

    # Neural SDE MAE (路径依赖: 用 history 调用 forecast)
    sde_paths = model.forecast(history, horizon, n_paths)
    if sde_paths is not None:
        sde_pred = np.mean(sde_paths[:, 1:], axis=0)
        sde_mae = float(np.mean(np.abs(sde_pred - actual)))
    else:
        sde_mae = float("inf")

    return {
        "neural_sde_mae": round(sde_mae, 6),
        "garch_mae": round(garch_mae, 6),
        "improvement": round(garch_mae - sde_mae, 6) if sde_mae != float("inf") else 0.0,
    }


def main():
    print("=" * 70)
    print("TDD-007 PoC 风险闸门: 30 ep 训练 + MAE ≤ 1.2× GARCH")
    print("=" * 70)

    # 1. 加载真实 BTC 数据
    btc_path = REPO / "dreambuddy_evolution" / "data" / "btc_close.json"
    closes = load_closes(btc_path)
    print(f"[1] 加载 BTC close: {len(closes)} 点 ← {btc_path.name}")

    # 2. 初始化模型 + 训练器
    model = NeuralSDEModel(device="cpu")
    if not model.is_available:
        print("[FAIL] torch 不可用")
        return 1
    trainer = NeuralSDETrainer(model, lr=1e-4, seq_len=64, horizon=20, batch_size=64)
    print(f"[2] 模型初始化: sig_dim={model.sig_dim}, n_step={model.n_step}, sig_depth={model.sig_depth}")

    # 3. 训练 30 epochs
    t0 = time.time()
    report = trainer.train(closes, epochs=30)
    elapsed = time.time() - t0
    if report["status"] != "ok":
        print(f"[FAIL] 训练失败: {report}")
        return 1
    print(f"[3] 训练完成: 30 ep, final_loss={report['final_loss']:.6f}, n_windows={report['n_windows']}, 耗时={elapsed:.1f}s")

    # 4. 评估 MAE (路径依赖 forecast)
    garch = GARCHFallback()
    mae = evaluate_mae_path_dependent(model, garch, closes, horizon=20, n_paths=200)
    print(f"[4] MAE 对比:")
    print(f"    NeuralSDE (路径依赖): {mae['neural_sde_mae']:.4f}")
    print(f"    GARCH baseline:      {mae['garch_mae']:.4f}")
    print(f"    improvement:         {mae['improvement']:.4f} (正=优于GARCH)")

    # 5. PoC 闸门: neural_sde_mae <= 1.2 * garch_mae
    threshold = 1.2 * mae["garch_mae"]
    passed = mae["neural_sde_mae"] <= threshold
    print(f"[5] PoC 闸门: neural_sde_mae <= 1.2 × garch_mae")
    print(f"    {mae['neural_sde_mae']:.4f} <= {threshold:.4f} ? {'PASS' if passed else 'FAIL'}")

    print("=" * 70)
    if passed:
        print("✅ PoC 通过 — 可推进 TDD-008 (200 ep 完整训练)")
    else:
        print("❌ PoC 失败 — 回滚到马尔可夫 MLP 架构 (维持 GARCH 同水平)")
    print("=" * 70)

    # 6. 保存 PoC 报告
    poc_report = {
        "tdd": "TDD-007",
        "epochs": 30,
        "n_windows": report["n_windows"],
        "final_loss": report["final_loss"],
        "mae_comparison": mae,
        "threshold": threshold,
        "passed": passed,
        "elapsed_sec": round(elapsed, 2),
    }
    report_path = REPO / "dreambuddy_evolution" / "data" / "neural_sde_v1_poc_tdd007.json"
    report_path.write_text(json.dumps(poc_report, indent=2), encoding="utf-8")
    print(f"[6] PoC 报告保存 → {report_path}")

    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
