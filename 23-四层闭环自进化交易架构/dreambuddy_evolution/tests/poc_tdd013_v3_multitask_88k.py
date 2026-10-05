"""TDD-013 v3 PoC 风险闸门: 200 ep + multitask + 87598 点.

第 3 轮架构优化 PoC, 解决 4 个根因中剩余的 2 个:
  - 根因 3: 数据量 17469 点偏少 → Binance 5y 30m K 线 87598 点 ✅
  - 根因 4: QLIKE loss 不适合价格预测 → 多任务 loss 0.7*MSE + 0.3*QLIKE ✅

  (前 2 个根因已在 PoC v2 解决)
  - 根因 1: log_sig z-score 归一化 (TDD-010) ✅
  - 根因 2: sig_dim=15 不截断 (TDD-011) ✅

验证: 200 epochs multitask 训练后, NeuralSDE MAE 是否 ≤ 1.2× GARCH.
基线: PoC v2 (MSE + 17469 点): MAE=269.51 vs GARCH=881.14 (ratio=0.31)
期望: PoC v3 (multitask + 87598 点): MAE 进一步改善 (期望 < 269.51)

- 用 btc_close_30m.json 真实数据 (87598 点 5 年 30m K 线)
- forecast(history, ...) 调用使用 path-signature (15 维, z-score 归一化)
- multitask loss = 0.7*MSE + 0.3*QLIKE (TDD-013)
- 对比 GARCH baseline MAE
- 闸门: neural_sde_mae <= 1.2 * garch_mae
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
    """对比 Neural SDE (路径依赖) vs GARCH 的预测 MAE."""
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
        "ratio": round(sde_mae / garch_mae, 4) if garch_mae > 0 and sde_mae != float("inf") else float("inf"),
    }


def main():
    print("=" * 70)
    print("TDD-013 v3 PoC: 200 ep + multitask + 87598 点 (第 3 轮优化)")
    print("=" * 70)

    # 1. 加载真实 BTC 数据 (5 年 30m K 线, Binance)
    btc_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_30m.json"
    closes = load_closes(btc_path)
    print(f"[1] 加载 BTC close (30m, 5y): {len(closes)} 点 ← {btc_path.name}")
    print(f"    首 3: {closes[:3].tolist()}")
    print(f"    末 3: {closes[-3:].tolist()}")
    print(f"    min={closes.min():.2f}, max={closes.max():.2f}")

    # 2. 初始化模型 + 训练器 (multitask loss = 0.7*MSE + 0.3*QLIKE)
    model = NeuralSDEModel(device="cpu")
    if not model.is_available:
        print("[FAIL] torch 不可用")
        return 1
    trainer = NeuralSDETrainer(
        model, lr=1e-4, seq_len=64, horizon=20, batch_size=64, loss_type="multitask",
    )
    print(f"[2] 模型初始化: sig_dim={model.sig_dim} (不截断), n_step={model.n_step}, loss_type=multitask")

    # 3. 训练 200 epochs (大数据量 → 训练时间会变长)
    t0 = time.time()
    report = trainer.train(closes, epochs=200)
    elapsed = time.time() - t0
    if report["status"] != "ok":
        print(f"[FAIL] 训练失败: {report}")
        return 1
    print(f"[3] 训练完成: 200 ep, final_loss={report['final_loss']:.6f}, n_windows={report['n_windows']}, 耗时={elapsed:.1f}s")
    print(f"    loss_type={report.get('loss_type')}, sig_dim={report.get('sig_dim')}")

    # 4. 评估 MAE (路径依赖 forecast)
    garch = GARCHFallback()
    mae = evaluate_mae_path_dependent(model, garch, closes, horizon=20, n_paths=200)
    print(f"[4] MAE 对比:")
    print(f"    NeuralSDE (路径依赖+multitask+sig15+zsc+88k): {mae['neural_sde_mae']:.4f}")
    print(f"    GARCH baseline:                                {mae['garch_mae']:.4f}")
    print(f"    improvement:                                    {mae['improvement']:.4f} (正=优于GARCH)")
    print(f"    ratio (sde/garch):                              {mae['ratio']}")
    print(f"    [基线对照] PoC v2 (MSE+17k): MAE=269.51, ratio=0.31")

    # 5. PoC 闸门: neural_sde_mae <= 1.2 * garch_mae
    threshold = 1.2 * mae["garch_mae"]
    passed = mae["neural_sde_mae"] <= threshold
    print(f"[5] PoC 闸门: neural_sde_mae <= 1.2 × garch_mae")
    print(f"    {mae['neural_sde_mae']:.4f} <= {threshold:.4f} ? {'PASS' if passed else 'FAIL'}")

    print("=" * 70)
    if passed:
        print("✅ PoC v3 通过 — NeuralSDE 超越 GARCH 同水平 (≤1.2×)")
    else:
        print("❌ PoC v3 失败 — 仍劣于 GARCH (>1.2×)")
    print("=" * 70)

    # 6. 保存 PoC v3 报告 + 模型权重
    poc_report = {
        "tdd": "TDD-013-v3",
        "round": 3,
        "optimizations": [
            "log_sig z-score (TDD-010, from v2)",
            "sig_dim=15 (TDD-011, from v2)",
            "multitask loss 0.7*MSE+0.3*QLIKE (TDD-013)",
            "Binance 5y 30m K线 87598 点 (数据扩充)",
        ],
        "data_source": "binance_btcusdt_30m_5y",
        "data_size": int(len(closes)),
        "epochs": 200,
        "n_windows": report["n_windows"],
        "final_loss": report["final_loss"],
        "loss_type": report.get("loss_type"),
        "sig_dim": report.get("sig_dim"),
        "mae_comparison": mae,
        "baseline_v2": {"neural_sde_mae": 269.51, "garch_mae": 881.14, "ratio": 0.31},
        "threshold": threshold,
        "passed": passed,
        "elapsed_sec": round(elapsed, 2),
    }
    report_path = REPO / "dreambuddy_evolution" / "data" / "neural_sde_v1_poc_tdd013_v3.json"
    report_path.write_text(json.dumps(poc_report, indent=2), encoding="utf-8")
    print(f"[6] PoC v3 报告保存 → {report_path}")

    # 7. 保存模型权重 (multitask + 88k)
    weight_path = REPO / "dreambuddy_evolution" / "data" / "neural_sde_v1_multitask_88k_v3.pt"
    model.save(str(weight_path))
    print(f"[7] 模型权重保存 → {weight_path}")

    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
