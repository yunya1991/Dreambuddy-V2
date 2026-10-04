"""CQL 离场策略训练脚本 — 训练 exit_policy_v2.pt

从 exit_rl_samples.jsonl 加载样本，用 CQLTrainer 训练 Q 网络。

使用方式：
  python3 -m dreambuddy_evolution.scripts.train_exit_policy
  python3 -m dreambuddy_evolution.scripts.train_exit_policy --epochs 200 --batch-size 64
  python3 -m dreambuddy_evolution.scripts.train_exit_policy --samples a.jsonl,b.jsonl --two-phase

输出：
  dreambuddy_evolution/data/exit_policy_v2.pt
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List

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
    Path(__file__).resolve().parents[1] / "data" / "exit_policy_v2.pt"
)
STREAM_THRESHOLD = 10_000  # 超过此数量使用流式加载


def load_samples(paths: str) -> List[Dict[str, Any]]:
    """加载 RL 样本，支持逗号分隔多路径"""
    samples: List[Dict[str, Any]] = []
    for p in paths.split(","):
        p = p.strip()
        if not p:
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        samples.append(json.loads(line))
            logger.info("加载 %d 条样本 ← %s", len(samples), p)
        except Exception as e:
            logger.warning("[FO] load samples fail %s: %s", p, e)
    return samples


def count_samples(paths: str) -> int:
    """快速统计样本数（不加载到内存）"""
    n = 0
    for p in paths.split(","):
        p = p.strip()
        if not p:
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                n += sum(1 for line in f if line.strip())
        except Exception:
            continue
    return n


def stream_samples(paths: str, chunk_size: int = 10_000) -> Iterator[List[Dict[str, Any]]]:
    """流式加载样本（避免内存爆炸）"""
    chunk: List[Dict[str, Any]] = []
    for p in paths.split(","):
        p = p.strip()
        if not p:
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        chunk.append(json.loads(line))
                        if len(chunk) >= chunk_size:
                            yield chunk
                            chunk = []
        except Exception as e:
            logger.warning("[FO] stream samples fail %s: %s", p, e)
    if chunk:
        yield chunk


def to_train_batch(samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """转换为 CQLTrainer.train_batch 所需格式，传递 meta.sample_weight"""
    batch = []
    for s in samples:
        weight = s.get("meta", {}).get("sample_weight", 1.0)
        batch.append({
            "state": np.array(s["state"], dtype=np.float32),
            "action": int(s["action"]),
            "reward": float(s["reward"]),
            "next_state": np.array(s["next_state"], dtype=np.float32),
            "done": bool(s.get("done", False)),
            "weight": float(weight),
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
    action_dist = np.zeros(5, dtype=int)
    for q in q_arr:
        action_dist[int(np.argmax(q))] += 1
    return {
        "n_evaluated": len(subset),
        "mean_q": round(float(q_arr.mean()), 6),
        "std_q": round(float(q_arr.std()), 6),
        "action_distribution": action_dist.tolist(),
    }


def run_epochs(
    trainer: CQLTrainer,
    samples_or_paths,
    epochs: int,
    batch_size: int,
    streaming: bool = False,
    label: str = "",
) -> List[float]:
    """训练若干 epochs"""
    losses: List[float] = []
    for epoch in range(epochs):
        epoch_loss = 0.0
        n_batches = 0
        if streaming:
            rng = np.random.RandomState(epoch)
            for chunk in stream_samples(samples_or_paths):
                batch = to_train_batch(chunk)
                rng.shuffle(batch)
                for i in range(0, len(batch), batch_size):
                    mini = batch[i : i + batch_size]
                    loss = trainer.train_batch(mini)
                    epoch_loss += loss
                    n_batches += 1
        else:
            train_batch = to_train_batch(samples_or_paths)
            n = len(train_batch)
            rng = np.random.RandomState(epoch)
            indices = rng.permutation(n)
            for i in range(0, n, batch_size):
                batch_idx = indices[i : i + batch_size]
                batch = [train_batch[j] for j in batch_idx]
                loss = trainer.train_batch(batch)
                epoch_loss += loss
                n_batches += 1
        avg_loss = epoch_loss / max(n_batches, 1)
        losses.append(avg_loss)
        if (epoch + 1) % 10 == 0 or epoch == 0:
            logger.info(
                "[%s] Epoch %3d/%d | avg_loss=%.6f",
                label, epoch + 1, epochs, avg_loss,
            )
    return losses


def main():
    parser = argparse.ArgumentParser(description="CQL 离场策略训练")
    parser.add_argument("--samples", default=DEFAULT_SAMPLES_PATH, help="样本文件路径（逗号分隔多文件）")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="模型输出路径")
    parser.add_argument("--epochs", type=int, default=100, help="训练轮数")
    parser.add_argument("--batch-size", type=int, default=64, help="batch size")
    parser.add_argument("--lr", type=float, default=1e-4, help="学习率")
    parser.add_argument("--cql-alpha", type=float, default=0.1, help="CQL 保守惩罚系数")
    parser.add_argument("--state-dim", type=int, default=8, help="状态维度")
    parser.add_argument("--n-actions", type=int, default=5, help="动作数")
    parser.add_argument("--two-phase", action="store_true", help="两阶段训练：回测粗训→真实微调")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
    )

    # 统计样本数决定是否流式
    n_samples = count_samples(args.samples)
    if n_samples == 0:
        logger.error("无样本可训练")
        return 1
    streaming = n_samples > STREAM_THRESHOLD
    logger.info("样本总数: %d, 流式加载: %s", n_samples, streaming)

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

    # 训练前评估（用一小部分样本）
    eval_samples = load_samples(args.samples)[:200]
    logger.info("=== 训练前评估 ===")
    pre_eval = evaluate_q(trainer, eval_samples)
    logger.info("Q 值: mean=%.4f std=%.4f | 动作分布=%s", pre_eval["mean_q"], pre_eval["std_q"], pre_eval["action_distribution"])

    losses: List[float] = []
    phase_a_losses: List[float] = []
    phase_b_losses: List[float] = []

    if args.two_phase:
        # Phase A: 全量样本粗训练（含回测，lr=1e-4）
        logger.info("=== Phase A: 回测+真实样本粗训练 (epochs=30, lr=1e-4) ===")
        trainer.optimizer = trainer._optim.Adam(trainer.q_net.parameters(), lr=1e-4)
        data = args.samples if streaming else load_samples(args.samples)
        phase_a_losses = run_epochs(trainer, data, epochs=30, batch_size=args.batch_size, streaming=streaming, label="PhaseA")
        losses.extend(phase_a_losses)

        # Phase B: 仅真实样本微调（lr=3e-5）
        logger.info("=== Phase B: 仅真实样本微调 (epochs=20, lr=3e-5) ===")
        real_samples = [s for s in (load_samples(args.samples) if not streaming else load_samples(args.samples)) if s.get("meta", {}).get("meta_source") != "backtest"]
        if not real_samples:
            logger.warning("无真实样本，Phase B 跳过")
        else:
            trainer.optimizer = trainer._optim.Adam(trainer.q_net.parameters(), lr=3e-5)
            phase_b_losses = run_epochs(trainer, real_samples, epochs=20, batch_size=args.batch_size, streaming=False, label="PhaseB")
            losses.extend(phase_b_losses)
    else:
        # 单阶段训练
        logger.info("=== 开始训练: epochs=%d batch_size=%d samples=%d ===", args.epochs, args.batch_size, n_samples)
        data = args.samples if streaming else load_samples(args.samples)
        losses = run_epochs(trainer, data, epochs=args.epochs, batch_size=args.batch_size, streaming=streaming, label="train")

    # 训练后评估
    logger.info("=== 训练后评估 ===")
    post_eval = evaluate_q(trainer, eval_samples)
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
        "n_samples": n_samples,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "cql_alpha": args.cql_alpha,
        "two_phase": args.two_phase,
        "streaming": streaming,
        "final_loss": round(losses[-1], 6) if losses else 0.0,
        "min_loss": round(min(losses), 6) if losses else 0.0,
        "max_loss": round(max(losses), 6) if losses else 0.0,
        "phase_a": {"epochs": len(phase_a_losses), "final_loss": round(phase_a_losses[-1], 6)} if phase_a_losses else None,
        "phase_b": {"epochs": len(phase_b_losses), "final_loss": round(phase_b_losses[-1], 6)} if phase_b_losses else None,
        "pre_eval": pre_eval,
        "post_eval": post_eval,
        "loss_curve_last_10": [round(l, 6) for l in losses[-10:]],
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("训练报告 → %s", report_path)

    print(f"\n训练完成: {len(losses)} epochs, {n_samples} samples")
    print(f"模型: {output}")
    print(f"final_loss={losses[-1]:.6f}" if losses else "无 loss")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
