"""Phase 3+4 Ablation: mask type (hard/soft/none) × head_dim (4/8).

目的:
  量化 factor_head_mask 类型与 head_dim 对 NeuralSDE Cross-Attention 推理质量的影响.
  5 组实验, 同种子/同数据/同 epochs:
    A: hard mask (-inf), head_dim=4 (cross_attn_dim=32, heads=8)
    B: soft mask (-1e9), head_dim=4
    C: no mask (None),    head_dim=4  (baseline)
    D: hard mask (-inf), head_dim=8 (cross_attn_dim=64, heads=8)
    E: soft mask (-1e9), head_dim=8

  对比维度:
  1. MAE: 预测精度 (越低越好)
  2. Attention entropy: 权重集中度 (hard mask 应更低 = 更稀疏)
  3. Mask leakage: 被屏蔽因子的注意力残留 (hard=0, soft≈0, none=自由)

输出: dreambuddy_evolution/data/ablation_mask_head_dim.json
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
from dreambuddy_evolution.core.exogenous_data_bridge import (
    CROSS_ATTENTION_FACTOR_METRICS,
    build_factor_head_mask,
    get_factor_dimensions,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

N_FACTORS = len(CROSS_ATTENTION_FACTOR_METRICS)  # 36
DIMENSIONS = get_factor_dimensions()  # C1..C8, news
N_HEADS = len(DIMENSIONS)             # 8


# ---------------------------------------------------------------------------
# 合成因子生成
# ---------------------------------------------------------------------------
def generate_synthetic_factors(
    n_steps: int,
    n_factors: int = N_FACTORS,
    seed: int = 42,
    signal_strength: float = 0.3,
) -> np.ndarray:
    """生成合成外生因子时序, 部分含预测信号.

    每个因子为均值回归的 AR(1) 过程:
      f[t+1] = phi * f[t] + epsilon,  phi=0.95, epsilon~N(0, 0.1)

    信号注入: 前 1/3 因子的 f[t] 与未来 1 步收益率有相关性.
    每个维度至少有 1 个信号因子 + 1 个纯噪声因子.

    Returns:
        (n_steps, n_factors) float64
    """
    rng = np.random.RandomState(seed)
    factors = np.zeros((n_steps, n_factors), dtype=np.float64)

    # 按维度分组
    dim_groups: dict[str, list[int]] = {}
    for idx, entry in enumerate(CROSS_ATTENTION_FACTOR_METRICS):
        dim = entry[3] if len(entry) > 3 else "unknown"
        dim_groups.setdefault(dim, []).append(idx)

    phi = 0.95  # 均值回归系数
    for dim, indices in dim_groups.items():
        for j, f_idx in enumerate(indices):
            # AR(1) 过程
            f = np.zeros(n_steps)
            f[0] = rng.randn() * 0.1
            for t in range(1, n_steps):
                f[t] = phi * f[t - 1] + rng.randn() * 0.1
            factors[:, f_idx] = f

    # 信号注入: 每个维度的第一个因子注入预测信号
    # factor[t] 与 return[t+1] 的相关性 = signal_strength
    # 通过在因子上加一个与未来收益相关的分量来实现
    # (这里用随机信号, 因为真实收益在生成时未知)
    for dim, indices in dim_groups.items():
        if len(indices) == 0:
            continue
        signal_idx = indices[0]  # 第一个因子作为信号因子
        # 叠加一个与随机"隐信号"相关的分量
        hidden_signal = rng.randn(n_steps) * signal_strength
        factors[:, signal_idx] += hidden_signal

    # 标准化 (z-score)
    means = factors.mean(axis=0)
    stds = factors.std(axis=0)
    stds[stds < 1e-8] = 1.0
    factors = (factors - means) / stds

    return factors


# ---------------------------------------------------------------------------
# 单组实验
# ---------------------------------------------------------------------------
def _train_and_evaluate(
    closes: np.ndarray,
    factors: np.ndarray,
    mask_type: str,       # "hard" | "soft" | "none"
    cross_attn_dim: int,   # 32 or 64
    cross_attn_heads: int, # 8
    seed: int,
    epochs: int = 100,
    label: str = "",
) -> dict:
    """训练一个带 cross-attention 的 NeuralSDE 并评估.

    Args:
        closes: 全量 close 序列
        factors: (N, n_factors) 合成因子时序
        mask_type: "hard"=-inf, "soft"=-1e9, "none"=None
        cross_attn_dim: 32 (head_dim=4) or 64 (head_dim=8)
        cross_attn_heads: 8 (匹配维度数)
        seed: 随机种子
        epochs: 训练轮数
        label: 实验标签

    Returns:
        dict with mae, attention_metrics, train_time, etc.
    """
    np.random.seed(seed)
    import torch
    torch.manual_seed(seed)

    # 构建 mask
    if mask_type == "hard":
        mask = build_factor_head_mask(mask_value=float("-inf"))
    elif mask_type == "soft":
        mask = build_factor_head_mask(mask_value=-1e9)
    else:  # none
        mask = None

    head_dim = cross_attn_dim // cross_attn_heads

    model = NeuralSDEModel(
        use_cross_attention=True,
        exogenous_factor_dim=N_FACTORS,
        cross_attn_dim=cross_attn_dim,
        cross_attn_heads=cross_attn_heads,
        factor_head_mask=mask,
        device="cpu",
    )
    if not model.is_available:
        raise RuntimeError("torch 不可用")

    trainer = NeuralSDETrainer(
        model=model, lr=1e-4, seq_len=64, horizon=20,
        batch_size=64, loss_type="mse",
    )

    t0 = time.time()
    report = trainer.train(
        closes, epochs=epochs,
        regime_labels=None,  # 无 regime (隔离 cross-attention 效果)
        regime_balance="natural",
        exogenous_factors=factors,
    )
    train_time = time.time() - t0
    logger.info("[%s] 训练: status=%s, n_windows=%d, final_loss=%.6f, 耗时=%.1fs",
                label, report.get("status"), report.get("n_windows", 0),
                report.get("final_loss", 0.0), train_time)

    if report.get("status") != "ok":
        raise RuntimeError(f"[{label}] 训练未完成: {report}")

    # 评估 MAE
    horizon = 20
    n_paths = 200
    n = len(closes)
    test_start = n - horizon - 1
    history = closes[:test_start + 1]
    actual = closes[test_start + 1:test_start + 1 + horizon]

    # 推理时注入末尾因子快照
    factor_snapshot = factors[test_start]  # (n_factors,)
    sde_paths = model.forecast(
        history, horizon, n_paths,
        exogenous_factors=factor_snapshot,
    )
    if sde_paths is None:
        sde_mae = float("inf")
    else:
        sde_pred = np.mean(sde_paths[:, 1:], axis=0)
        sde_mae = float(np.mean(np.abs(sde_pred - actual)))

    # 提取 attention 权重分析 (失败不影响 MAE 结果)
    try:
        attn_metrics = _analyze_attention(model, factor_snapshot)
    except Exception as e:
        logger.warning("[%s] attention 分析失败 (不影响 MAE): %s", label, e)
        attn_metrics = {"entropy": -1, "sparsity": -1, "mask_leakage_ratio": -1, "error": str(e)}

    return {
        "label": label,
        "mask_type": mask_type,
        "head_dim": head_dim,
        "cross_attn_dim": cross_attn_dim,
        "cross_attn_heads": cross_attn_heads,
        "mae": sde_mae,
        "n_windows": int(report.get("n_windows", 0)),
        "final_loss": float(report.get("final_loss", 0.0)),
        "train_time_sec": round(train_time, 2),
        "attention": attn_metrics,
    }


def _analyze_attention(model: NeuralSDEModel, factor_snapshot: np.ndarray) -> dict:
    """提取并分析 cross-attention 权重.

    forecast 后 last_attn_weights 形状为 (B, n_heads, 1, N),
    B 可能 = n_paths (200). 取 batch 平均后分析.

    Returns:
        dict with:
        - entropy: 平均注意力熵 (越低=越集中)
        - sparsity: 接近零的权重比例
        - mask_leakage: 被屏蔽因子上的权重总和 (hard 应=0)
    """
    import torch

    drift_net = model.drift_net
    # 获取 cross_attn 模块 (处理 MoE 取第一个 expert)
    if hasattr(drift_net, "experts"):
        cross_attn = drift_net.experts[0].cross_attn
    else:
        cross_attn = drift_net.cross_attn

    if cross_attn.last_attn_weights is None:
        # 手动跑一次 forward 触发 attention 计算
        B = 1
        log_sig = torch.randn(B, drift_net.sig_dim)
        q = drift_net.q_proj(log_sig)  # (B, d_model)
        factors_t = torch.tensor(factor_snapshot, dtype=torch.float32).unsqueeze(0).unsqueeze(-1)
        k = drift_net.factor_encoder(factors_t)  # (B, N, d_model)
        v = k
        _ = cross_attn(q.unsqueeze(1), k, v)

    weights = cross_attn.last_attn_weights  # (B, n_heads, 1, N)
    if weights is None:
        return {"entropy": -1, "sparsity": -1, "mask_leakage_ratio": -1}

    # 取 batch 平均 → (n_heads, N)
    weights_2d = weights.mean(dim=0).squeeze()  # (n_heads, N)
    n_heads, N = weights_2d.shape

    # Attention entropy (per head, averaged)
    entropy_per_head = []
    for h in range(n_heads):
        w = weights_2d[h]  # (N,)
        w_safe = torch.clamp(w, min=1e-12)
        ent = -torch.sum(w_safe * torch.log(w_safe)).item()
        entropy_per_head.append(ent)
    avg_entropy = float(np.mean(entropy_per_head))

    # Sparsity: 比例 of weights < 0.01
    sparsity = float((weights_2d < 0.01).float().mean().item())

    # Mask leakage: 如果有 mask, 计算被屏蔽位置上的权重总和
    mask = cross_attn.factor_head_mask
    if mask is not None:
        # mask: (n_heads, N), 0=允许, -inf/-1e9=屏蔽
        masked_positions = mask < -1e-6  # (n_heads, N) bool
        if masked_positions.any():
            leakage = weights_2d[masked_positions].sum().item()
            total = weights_2d.sum().item()
            leakage_ratio = float(leakage / max(abs(total), 1e-12))
        else:
            leakage_ratio = 0.0
    else:
        leakage_ratio = -1.0  # N/A

    return {
        "entropy": round(avg_entropy, 4),
        "sparsity": round(sparsity, 4),
        "mask_leakage_ratio": round(leakage_ratio, 6),
    }


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def main():
    data_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
    if not data_path.exists():
        logger.error("数据不存在: %s", data_path)
        return 1

    with open(data_path) as f:
        closes = np.array(json.load(f), dtype=np.float64)
    logger.info("加载 BTC 10y close: %d 点, $%.2f → $%.2f",
                len(closes), closes[0], closes[-1])

    # 生成合成因子
    factors = generate_synthetic_factors(len(closes), N_FACTORS, seed=42)
    logger.info("生成合成因子: shape=%s, dimensions=%s, factors=%d, heads=%d",
                factors.shape, DIMENSIONS, N_FACTORS, N_HEADS)

    SEED = 42
    EPOCHS = 100

    configs = [
        # Ablation 1: mask type (head_dim=4 固定)
        {"mask_type": "hard", "cross_attn_dim": 32, "cross_attn_heads": N_HEADS, "label": "A-hard-hd4"},
        {"mask_type": "soft", "cross_attn_dim": 32, "cross_attn_heads": N_HEADS, "label": "B-soft-hd4"},
        {"mask_type": "none", "cross_attn_dim": 32, "cross_attn_heads": N_HEADS, "label": "C-none-hd4"},
        # Ablation 2: head_dim (hard mask 固定)
        {"mask_type": "hard", "cross_attn_dim": 64, "cross_attn_heads": N_HEADS, "label": "D-hard-hd8"},
        {"mask_type": "soft", "cross_attn_dim": 64, "cross_attn_heads": N_HEADS, "label": "E-soft-hd8"},
    ]

    results = []
    for cfg in configs:
        logger.info("=" * 60)
        logger.info("实验 %s: mask=%s, dim=%d, heads=%d, head_dim=%d",
                    cfg["label"], cfg["mask_type"], cfg["cross_attn_dim"],
                    cfg["cross_attn_heads"],
                    cfg["cross_attn_dim"] // cfg["cross_attn_heads"])
        logger.info("=" * 60)
        try:
            result = _train_and_evaluate(
                closes=closes,
                factors=factors,
                mask_type=cfg["mask_type"],
                cross_attn_dim=cfg["cross_attn_dim"],
                cross_attn_heads=cfg["cross_attn_heads"],
                seed=SEED,
                epochs=EPOCHS,
                label=cfg["label"],
            )
            results.append(result)
            logger.info("[%s] MAE=%.2f, entropy=%.4f, sparsity=%.4f, leakage=%.6f",
                        cfg["label"], result["mae"],
                        result["attention"]["entropy"],
                        result["attention"]["sparsity"],
                        result["attention"]["mask_leakage_ratio"])
        except Exception as e:
            logger.error("[%s] 失败: %s", cfg["label"], e, exc_info=True)
            results.append({
                "label": cfg["label"],
                "mask_type": cfg["mask_type"],
                "head_dim": cfg["cross_attn_dim"] // cfg["cross_attn_heads"],
                "error": str(e),
            })

    # === 对比报告 ===
    report = {
        "tdd": "Phase3+4-ablation",
        "purpose": "mask type (hard/soft/none) × head_dim (4/8) 消融",
        "config": {
            "data": "btc_close_10y.json",
            "n_points": int(len(closes)),
            "epochs": EPOCHS,
            "seed": SEED,
            "n_factors": N_FACTORS,
            "n_heads": N_HEADS,
            "dimensions": DIMENSIONS,
            "factor_generation": "synthetic AR(1) + signal injection",
        },
        "results": results,
    }

    # 汇总对比
    valid = [r for r in results if "mae" in r]
    if len(valid) >= 2:
        report["comparison"] = _build_comparison(valid)

    out_path = REPO / "dreambuddy_evolution" / "data" / "ablation_mask_head_dim.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info("=== Ablation 对照结果 ===")
    for r in results:
        if "mae" in r:
            logger.info("%s: MAE=%.2f, entropy=%.4f, sparsity=%.4f, leakage=%.6f",
                        r["label"], r["mae"],
                        r["attention"]["entropy"], r["attention"]["sparsity"],
                        r["attention"]["mask_leakage_ratio"])
        else:
            logger.info("%s: FAILED (%s)", r["label"], r.get("error", "unknown"))
    logger.info("报告: %s", out_path)

    return 0


def _build_comparison(results: list[dict]) -> dict:
    """构建对比汇总."""
    by_label = {r["label"]: r for r in results}

    comp = {}

    # Ablation 1: hard vs soft vs none (head_dim=4)
    a = by_label.get("A-hard-hd4")
    b = by_label.get("B-soft-hd4")
    c = by_label.get("C-none-hd4")
    if a and b and c:
        comp["mask_type_hd4"] = {
            "hard_mae": a["mae"],
            "soft_mae": b["mae"],
            "none_mae": c["mae"],
            "hard_vs_soft": round(a["mae"] - b["mae"], 4),
            "hard_vs_none": round(a["mae"] - c["mae"], 4),
            "soft_vs_none": round(b["mae"] - c["mae"], 4),
            "hard_entropy": a["attention"]["entropy"],
            "soft_entropy": b["attention"]["entropy"],
            "none_entropy": c["attention"]["entropy"],
            "interpretation": (
                f"hard mask MAE={a['mae']:.2f} vs soft={b['mae']:.2f} vs none={c['mae']:.2f}; "
                f"entropy hard={a['attention']['entropy']:.4f} < soft={b['attention']['entropy']:.4f} "
                f"{'<' if b['attention']['entropy'] < c['attention']['entropy'] else '>'} none={c['attention']['entropy']:.4f}"
            ),
        }

    # Ablation 2: head_dim=4 vs 8 (hard mask)
    d = by_label.get("D-hard-hd8")
    if a and d:
        comp["head_dim_hard"] = {
            "hd4_mae": a["mae"],
            "hd8_mae": d["mae"],
            "improvement": round(a["mae"] - d["mae"], 4),
            "improvement_pct": round((a["mae"] - d["mae"]) / max(a["mae"], 1e-8) * 100, 2),
            "interpretation": (
                f"head_dim=4 MAE={a['mae']:.2f} vs head_dim=8 MAE={d['mae']:.2f} "
                f"(改善 {a['mae'] - d['mae']:.2f}, "
                f"{(a['mae'] - d['mae']) / max(a['mae'], 1e-8) * 100:.1f}%)"
            ),
        }

    # Ablation 2b: head_dim=4 vs 8 (soft mask)
    e = by_label.get("E-soft-hd8")
    if b and e:
        comp["head_dim_soft"] = {
            "hd4_mae": b["mae"],
            "hd8_mae": e["mae"],
            "improvement": round(b["mae"] - e["mae"], 4),
            "improvement_pct": round((b["mae"] - e["mae"]) / max(b["mae"], 1e-8) * 100, 2),
            "interpretation": (
                f"head_dim=4 MAE={b['mae']:.2f} vs head_dim=8 MAE={e['mae']:.2f} "
                f"(改善 {b['mae'] - e['mae']:.2f}, "
                f"{(b['mae'] - e['mae']) / max(b['mae'], 1e-8) * 100:.1f}%)"
            ),
        }

    # Mask leakage comparison
    if a and b:
        comp["leakage"] = {
            "hard_leakage": a["attention"]["mask_leakage_ratio"],
            "soft_leakage": b["attention"]["mask_leakage_ratio"],
            "interpretation": (
                f"hard mask leakage={a['attention']['mask_leakage_ratio']:.6f} (应为0), "
                f"soft mask leakage={b['attention']['mask_leakage_ratio']:.6f} (应≈0)"
            ),
        }

    return comp


if __name__ == "__main__":
    sys.exit(main())
