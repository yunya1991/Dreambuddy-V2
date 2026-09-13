"""CQL 离场策略训练脚本 — 训练 exit_policy_v1.pt

从 exit_rl_samples.jsonl 加载样本，用 CQLTrainer 训练 Q 网络。

使用方式：
  python3 -m dreambuddy_evolution.scripts.train_exit_policy
  python3 -m dreambuddy_evolution.scripts.train_exit_policy --epochs 200 --batch-size 64

输出：
  dreambuddy_evolution/data/exit_policy_v1.pt
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

# 确保 dreambuddy_evolution 包可导入
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dreambuddy_evolution.core.exit_rl_policy import CQLTrainer

logger = logging.getLogger(__name__)

DEFAULT_SAMPLES_PATH = str(
    Path(__file__).resolve().parents[1] / "data" / "exit_rl_samples.jsonl"
)
DEFAULT_OUTPUT_PATH = str(
    Path(__file__).resolve().parents[1] / "data" / "exit_policy_v1.pt"
)


def load_samples(path: str) -> List[Dict[str, Any]]:
    """加载 RL 样本"""
    samples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    logger.info("加载 %d 条样本 ← %s", len(samples), path)
    return samples


def to_train_batch(samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """转换为 CQLTrainer.train_batch 所需格式"""
    batch = []
    for s in samples:
        batch.append({
            "state": np.array(s["state"], dtype=np.float32),
            "action": int(s["action"]),
            "reward": float(s["reward"]),
            "next_state": np.array(s["next_state"], dtype=np.float32),
            "done": bool(s.get("done", False)),
        })
    return batch


def evaluate_q(trainer: CQLTrainer, samples: List[Dict[str, Any]], n: int = 200) -> Dict[str, float]:
    """评估 Q 值分布"""
    subset = samples[:n] if len(samples) > n else samples
    q_values = []
    for s in subset:
        state = np.array(s["state"], dtype=np.float32)
        q = trainer.predict_q(state)
        q_values.append(q)
    q_arr = np.array(q_values)
    # 动作分布（argmax）
    action_dist = np.zeros(5, dtype=int)
    for q in q_arr:
        action_dist[int(np.argmax(q))] += 1
    return {
        "n_evaluated": len(subset),
        "mean_q": round(float(q_arr.mean()), 6),
        "std_q": round(float(q_arr.std()), 6),
        "action_distribution": action_dist.tolist(),
    }


def main():
    parser = argparse.ArgumentParser(description="CQL 离场策略训练")
    parser.add_argument("--samples", default=DEFAULT_SAMPLES_PATH, help="样本文件路径")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="模型输出路径")
    parser.add_argument("--epochs", type=int, default=100, help="训练轮数")
    parser.add_argument("--batch-size", type=int, default=64, help="batch size")
    parser.add_argument("--lr", type=float, default=1e-4, help="学习率")
    parser.add_argument("--cql-alpha", type=float, default=0.1, help="CQL 保守惩罚系数")
    parser.add_argument("--state-dim", type=int, default=8, help="状态维度")
    parser.add_argument("--n-actions", type=int, default=5, help="动作数")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
    )

    # 加载样本
    samples = load_samples(args.samples)
    if not samples:
        logger.error("无样本可训练")
        return 1

    train_batch = to_train_batch(samples)
    n = len(train_batch)

    # 初始化 CQLTrainer
    trainer = CQLTrainer(
        state_dim=args.state_dim,
        n_actions=args.n_actions,
        lr=args.lr,
        cql_alpha=args.cql_alpha,
        gamma=0.99,
        hidden_dim=64,
        device="cpu",
    )

    if not trainer._available:
        logger.error("torch 不可用，无法训练")
        return 1

    # 训练前评估
    logger.info("=== 训练前评估 ===")
    pre_eval = evaluate_q(trainer, samples)
    logger.info("Q 值: mean=%.4f std=%.4f | 动作分布=%s", pre_eval["mean_q"], pre_eval["std_q"], pre_eval["action_distribution"])

    # 训练循环
    logger.info("=== 开始训练: epochs=%d batch_size=%d samples=%d ===", args.epochs, args.batch_size, n)
    losses: List[float] = []
    for epoch in range(args.epochs):
        # 随机 shuffle
        rng = np.random.RandomState(epoch)
        indices = rng.permutation(n)
        epoch_loss = 0.0
        n_batches = 0
        for i in range(0, n, args.batch_size):
            batch_idx = indices[i : i + args.batch_size]
            batch = [train_batch[j] for j in batch_idx]
            loss = trainer.train_batch(batch)
            epoch_loss += loss
            n_batches += 1
        avg_loss = epoch_loss / max(n_batches, 1)
        losses.append(avg_loss)

        if (epoch + 1) % 10 == 0 or epoch == 0:
            logger.info(
                "Epoch %3d/%d | avg_loss=%.6f | min=%.6f max=%.6f",
                epoch + 1, args.epochs, avg_loss, min(losses), max(losses),
            )

    # 训练后评估
    logger.info("=== 训练后评估 ===")
    post_eval = evaluate_q(trainer, samples)
    logger.info("Q 值: mean=%.4f std=%.4f | 动作分布=%s", post_eval["mean_q"], post_eval["std_q"], post_eval["action_distribution"])

    # 保存模型
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    trainer.save(str(output))
    logger.info("模型保存 → %s", output)

    # 保存训练报告
    report_path = output.with_suffix(".training_report.json")
    report = {
        "model_path": str(output),
        "samples_path": args.samples,
        "n_samples": n,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "cql_alpha": args.cql_alpha,
        "final_loss": round(losses[-1], 6),
        "min_loss": round(min(losses), 6),
        "max_loss": round(max(losses), 6),
        "pre_eval": pre_eval,
        "post_eval": post_eval,
        "loss_curve_last_10": [round(l, 6) for l in losses[-10:]],
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("训练报告 → %s", report_path)

    print(f"\n训练完成: {args.epochs} epochs, {n} samples")
    print(f"模型: {output}")
    print(f"final_loss={losses[-1]:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
