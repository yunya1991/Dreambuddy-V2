"""Neural SDE 训练脚本 — 训练 neural_sde_v1.pt

从历史 K 线 close 序列训练 Neural SDE 模型 (drift + diffusion 网络)。
训练完成后与 GARCH 基线对比 MAE。

使用方式：
  python3 -m dreambuddy_evolution.scripts.train_neural_sde --epochs 200
  python3 -m dreambuddy_evolution.scripts.train_neural_sde --closes-file data/btc_close.json --epochs 50

输出：
  dreambuddy_evolution/data/neural_sde_v1.pt
  dreambuddy_evolution/data/neural_sde_v1.training_report.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer
from dreambuddy_evolution.core.garch_fallback import GARCHFallback

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_PATH = str(
    Path(__file__).resolve().parents[1] / "data" / "neural_sde_v1.pt"
)


def generate_synthetic_closes(n: int = 2000) -> np.ndarray:
    """生成合成价格序列用于训练（当无真实数据时）."""
    np.random.seed(42)
    returns = np.random.randn(n) * 0.02 + 0.0001
    closes = 100 * np.exp(np.cumsum(returns))
    return closes


def load_closes(path: str) -> np.ndarray:
    """从 JSON 文件加载 close 序列."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return np.array(data, dtype=np.float64)
    if isinstance(data, dict) and "close" in data:
        return np.array(data["close"], dtype=np.float64)
    raise ValueError("无法解析 close 序列")


def evaluate_mae(
    model: NeuralSDEModel,
    garch: GARCHFallback,
    closes: np.ndarray,
    horizon: int = 20,
    n_paths: int = 200,
) -> dict[str, float]:
    """对比 Neural SDE vs GARCH 的预测 MAE."""
    closes = np.asarray(closes, dtype=np.float64).ravel()
    n = len(closes)
    if n < horizon + 100:
        return {"neural_sde_mae": 0.0, "garch_mae": 0.0, "improvement": 0.0}

    # 用最后 horizon 个点做评估
    test_start = n - horizon - 1
    history = closes[:test_start + 1]
    actual = closes[test_start + 1:test_start + 1 + horizon]
    init_price = float(history[-1])
    returns = np.diff(np.log(history))
    init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02

    # GARCH MAE
    garch.estimate(returns)
    garch_paths = garch.simulate(n_paths, horizon, init_price, init_vol)
    garch_pred = np.mean(garch_paths[:, 1:], axis=0)
    garch_mae = float(np.mean(np.abs(garch_pred - actual)))

    # Neural SDE MAE
    sde_paths = model.forecast(np.array([init_price, init_vol]), horizon, n_paths)
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
    parser = argparse.ArgumentParser(description="Neural SDE 训练")
    parser.add_argument("--closes-file", default=None, help="历史 close 序列 JSON 文件")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="模型输出路径")
    parser.add_argument("--epochs", type=int, default=200, help="训练轮数")
    parser.add_argument("--batch-size", type=int, default=64, help="batch size")
    parser.add_argument("--lr", type=float, default=1e-4, help="学习率")
    parser.add_argument("--seq-len", type=int, default=64, help="输入窗口长度")
    parser.add_argument("--horizon", type=int, default=20, help="预测步数")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
    )

    # 加载 close 序列
    if args.closes_file:
        closes = load_closes(args.closes_file)
        logger.info("加载 %d 条 close 数据 ← %s", len(closes), args.closes_file)
    else:
        logger.info("使用合成数据训练 (2000 点)")
        closes = generate_synthetic_closes(2000)

    # 初始化模型
    model = NeuralSDEModel(device="cpu")
    if not model.is_available:
        logger.error("torch 不可用，无法训练 Neural SDE")
        return 1

    # 初始化训练器
    trainer = NeuralSDETrainer(
        model=model,
        lr=args.lr,
        seq_len=args.seq_len,
        horizon=args.horizon,
        batch_size=args.batch_size,
    )

    # 训练
    logger.info("=== 开始训练: epochs=%d batch_size=%d ===", args.epochs, args.batch_size)
    report = trainer.train(closes, epochs=args.epochs)

    if report["status"] != "ok":
        logger.error("训练失败: %s", report)
        return 1

    logger.info("训练完成: final_loss=%.6f, n_windows=%d", report["final_loss"], report["n_windows"])

    # 评估
    garch = GARCHFallback()
    mae_report = evaluate_mae(model, garch, closes, horizon=args.horizon)
    logger.info(
        "MAE 对比: NeuralSDE=%.6f vs GARCH=%.6f (improvement=%.6f)",
        mae_report["neural_sde_mae"],
        mae_report["garch_mae"],
        mae_report["improvement"],
    )

    # 保存模型（带版本号）
    output = Path(args.output)
    model.save(str(output))
    logger.info("模型保存 → %s", output)

    # 保存训练报告
    report_path = output.with_suffix(".training_report.json")
    full_report = {
        **report,
        "mae_comparison": mae_report,
        "config": {
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "seq_len": args.seq_len,
            "horizon": args.horizon,
        },
    }
    report_path.write_text(json.dumps(full_report, indent=2), encoding="utf-8")
    logger.info("训练报告 → %s", report_path)

    # --- 模型版本管理：对比已有版本，保留最优 ---
    main_path = select_best_version(output)
    if main_path:
        logger.info("🏆 最优版本已设为 neural_sde_v1.pt（reason() 将加载此版本）")

    return 0


def select_best_version(current_model_path: Path) -> Path:
    """对比所有版本 MAE，将最优版本复制为 neural_sde_v1.pt.

    版本文件命名: neural_sde_v1_<tag>.pt + .training_report.json
    主权重文件: neural_sde_v1.pt (reason() 加载此文件)

    Returns:
        最优版本的路径
    """
    data_dir = current_model_path.parent
    stem = current_model_path.stem  # e.g. neural_sde_v1_real

    # 收集所有版本
    versions: list[tuple[str, float, Path]] = []  # (tag, mae, model_path)

    # 当前版本
    current_report_path = current_model_path.with_suffix(".training_report.json")
    if current_report_path.exists():
        rpt = json.loads(current_report_path.read_text(encoding="utf-8"))
        mae = rpt.get("mae_comparison", {}).get("neural_sde_mae", float("inf"))
        versions.append(("current", mae, current_model_path))

    # 已有版本
    for rpt_file in data_dir.glob("neural_sde_v1*.training_report.json"):
        if rpt_file == current_report_path:
            continue
        try:
            rpt = json.loads(rpt_file.read_text(encoding="utf-8"))
            mae = rpt.get("mae_comparison", {}).get("neural_sde_mae", float("inf"))
            model_file = rpt_file.with_suffix(".pt")
            tag = rpt_file.stem.replace("neural_sde_v1", "").strip("_") or "base"
            if model_file.exists():
                versions.append((tag, mae, model_file))
        except Exception:  # noqa: BLE001
            continue

    if not versions:
        return current_model_path

    # 选择 MAE 最低的版本
    versions.sort(key=lambda x: x[1])
    best_tag, best_mae, best_path = versions[0]

    logger.info(
        "=== 版本对比 ===\n%s",
        "\n".join(f"  {tag}: MAE={mae:.4f}" for tag, mae, _ in versions),
    )
    logger.info("最优版本: %s (MAE=%.4f)", best_tag, best_mae)

    # 如果当前版本不是最优，将最优版本复制为主权重文件
    main_path = data_dir / "neural_sde_v1.pt"
    if best_path != main_path:
        import shutil
        shutil.copy2(best_path, main_path)
        # 复制对应的 training_report
        best_report = best_path.with_suffix(".training_report.json")
        if best_report.exists():
            shutil.copy2(best_report, main_path.with_suffix(".training_report.json"))
        logger.info("最优版本已复制 → %s", main_path)

    return main_path if best_path != main_path else best_path


if __name__ == "__main__":
    sys.exit(main())
