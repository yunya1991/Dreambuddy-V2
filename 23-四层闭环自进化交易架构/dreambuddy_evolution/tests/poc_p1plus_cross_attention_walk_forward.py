"""E7 PoC: Cross-Attention 外生因子注入 walk-forward 2024 OOS 对比.

对比三个配置:
  - Config A (baseline, 无外生):
      NeuralSDEModel(n_regimes=3, use_moe=True, moe_routing="hard", dropout=0.05)
  - Config B (P1 9维拼接):
      同 A + use_exogenous=True, exogenous_dim=9 + exogenous_snapshot
  - Config C (方案C Cross-Attention):
      同 A + use_cross_attention=True, exogenous_factor_dim=F + exogenous_factors

评估指标:
  - ratio = sde_mae / garch_mae (目标 < 0.93)
  - max_ratio (最差窗口)
  - MAE 均值

FAIL-OPEN: DAL 不可用时 exogenous_factors 全 0, Cross-Attention 退化为无外生.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer
from dreambuddy_evolution.core.garch_fallback import GARCHFallback
from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector
from dreambuddy_evolution.core.exogenous_data_bridge import (
    build_exogenous_series,
    build_exogenous_factors_for_cross_attention,
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def build_model(config_name: str, exogenous_factor_dim: int = 0):
    """根据配置名构建模型."""
    base_kwargs = dict(
        n_regimes=3, use_moe=True, moe_routing="hard", dropout=0.05,
    )
    if config_name == "A":
        return NeuralSDEModel(**base_kwargs)
    elif config_name == "B":
        return NeuralSDEModel(**base_kwargs, use_exogenous=True, exogenous_dim=9)
    elif config_name == "C":
        return NeuralSDEModel(
            **base_kwargs,
            use_cross_attention=True,
            exogenous_factor_dim=exogenous_factor_dim,
            cross_attn_dim=32,
            cross_attn_heads=4,
        )
    raise ValueError(f"未知配置: {config_name}")


def evaluate_on_windows(model, closes, test_starts, regime_labels,
                         exo_snapshot_series=None,
                         exo_factors_matrix=None,
                         n_paths=200, horizon=20):
    """在测试窗口上评估 SDE vs GARCH."""
    results = []
    for ts in test_starts:
        history = closes[:ts + 1]
        actual = closes[ts + 1:ts + 1 + horizon]
        if len(actual) < horizon:
            continue
        init_price = float(history[-1])
        returns = np.diff(np.log(history))
        init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02

        # GARCH baseline
        garch = GARCHFallback()
        garch.estimate(returns)
        garch_paths = garch.simulate(n_paths, horizon, init_price, init_vol)
        garch_pred = np.mean(garch_paths[:, 1:], axis=0)
        garch_mae = float(np.mean(np.abs(garch_pred - actual)))

        test_regime = int(regime_labels[ts])

        # exogenous snapshot (Config B)
        exo_snap = None
        if exo_snapshot_series is not None and ts < len(exo_snapshot_series):
            exo_snap = np.asarray(exo_snapshot_series[ts], dtype=np.float64).ravel()

        # exogenous factors (Config C)
        exo_factors = None
        if exo_factors_matrix is not None and ts < len(exo_factors_matrix):
            exo_factors = np.asarray(exo_factors_matrix[ts], dtype=np.float64)
            if exo_factors.ndim == 1:
                exo_factors = exo_factors.reshape(-1, 1)

        sde_paths = model.forecast(
            history, horizon, n_paths,
            regime=test_regime,
            exogenous_snapshot=exo_snap,
            exogenous_factors=exo_factors,
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


def summarize(results: list[dict]) -> dict:
    """汇总评估结果."""
    if not results:
        return {}
    ratios = [r["ratio"] for r in results]
    maes = [r["sde_mae"] for r in results]
    return {
        "mean_ratio": round(float(np.mean(ratios)), 4),
        "median_ratio": round(float(np.median(ratios)), 4),
        "max_ratio": round(float(np.max(ratios)), 4),
        "min_ratio": round(float(np.min(ratios)), 4),
        "mean_mae": round(float(np.mean(maes)), 4),
        "n_windows": len(results),
    }


def main():
    data_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
    if not data_path.exists():
        logger.error("数据不存在: %s", data_path)
        return 1
    with open(data_path) as f:
        closes_full = np.array(json.load(f), dtype=np.float64)
    logger.info("加载 BTC 10y close: %d 点", len(closes_full))

    # 2024 OOS: 1 年 (对齐补采数据 2024-01 ~ 2025-01)
    N_TEST = 24 * 365
    train_end = len(closes_full) - N_TEST
    closes_train = closes_full[:train_end].copy()
    logger.info("Walk-forward: train=%d, test=%d (2024 OOS)", train_end, N_TEST)

    # Regime detection
    np.random.seed(42)
    detector = BTCRegimeDetector()
    regime_train = detector.detect(closes_train)
    regime_test = detector.detect(closes_full[train_end:])
    regime_full = np.concatenate([regime_train, regime_test])

    # 月度测试窗口 (每月第 1 天)
    test_starts = [train_end + i * 24 * 30 for i in range(12)]
    test_starts = [s for s in test_starts if s + 20 + 1 < len(closes_full)]

    # ---- 外生数据准备 ----
    # P1: 9维外生快照时序
    logger.info("构建 P1 9维外生时序...")
    exo_series_full = build_exogenous_series(closes_full, bridge=None)

    # 方案C: Cross-Attention 因子矩阵
    # 时间戳对齐: 数据末尾设为 2025-01-01, 使 2024 OOS 窗口匹配补采数据
    logger.info("构建 Cross-Attention 因子矩阵 (真实 DAL 数据)...")
    end_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    timestamps = [
        end_ts - timedelta(hours=len(closes_full) - 1 - i)
        for i in range(len(closes_full))
    ]
    exo_factors_full, factor_names = build_exogenous_factors_for_cross_attention(
        timestamps=timestamps,
        factor_names=["cpi_actual", "funding_rate", "etf_net_flow", "dxy", "stablecoin_tvl"],
    )
    logger.info("因子矩阵: shape=%s, names=%s", exo_factors_full.shape, factor_names)
    # 统计非零比例
    for i, name in enumerate(factor_names):
        col = exo_factors_full[:, i]
        nz = np.count_nonzero(col)
        logger.info("  因子 %s: 非零 %d/%d (%.1f%%)", name, nz, len(col), 100 * nz / len(col))
    exogenous_factor_dim = exo_factors_full.shape[1] if exo_factors_full.ndim == 2 else 0

    # 因子 z-score 归一化 (仅用训练段统计量, 避免数据泄露)
    factor_mean = np.mean(exo_factors_full[:train_end], axis=0)
    factor_std = np.std(exo_factors_full[:train_end], axis=0)
    factor_std[factor_std < 1e-8] = 1.0  # 防除零
    exo_factors_full = (exo_factors_full - factor_mean) / factor_std
    logger.info("因子已 z-score 归一化 (mean≈0, std≈1)")

    # ---- 训练并评估三个配置 ----
    all_summaries = {}

    for config in ["A", "B", "C"]:
        logger.info("=" * 60)
        logger.info("训练 Config %s ...", config)
        model = build_model(config, exogenous_factor_dim=exogenous_factor_dim)
        model._activated = True

        trainer = NeuralSDETrainer(
            model,
            lr=1e-4, seq_len=64, horizon=20, batch_size=64,
            loss_type="return_mse", weight_decay=1e-4,
            patience=10, val_split=0.1,
        )

        # 训练 (Config A 无外生, B 有 P1 exogenous, C 有 P1+ cross-attention factors)
        train_kwargs = dict(epochs=250, regime_labels=regime_train, regime_balance="natural")
        if config == "B":
            train_kwargs["exogenous_series"] = exo_series_full[:train_end]
        elif config == "C":
            # Config C: 训练时注入 cross-attention 因子, 让模型学会使用 context
            train_kwargs["exogenous_factors"] = exo_factors_full[:train_end]

        trainer.train(closes_train, **train_kwargs)

        # 评估
        exo_snap = exo_series_full if config == "B" else None
        exo_factors = exo_factors_full if config == "C" else None

        results = evaluate_on_windows(
            model, closes_full, test_starts, regime_full,
            exo_snapshot_series=exo_snap,
            exo_factors_matrix=exo_factors,
        )
        summary = summarize(results)
        all_summaries[config] = summary
        logger.info("Config %s 汇总: %s", config, summary)

    # ---- 最终对比 ----
    logger.info("=" * 60)
    logger.info("最终对比 (2024 OOS walk-forward):")
    for config, s in all_summaries.items():
        logger.info(
            "Config %s: mean_ratio=%.4f, max_ratio=%.4f, mean_mae=%.4f",
            config, s.get("mean_ratio", float("nan")),
            s.get("max_ratio", float("nan")),
            s.get("mean_mae", float("nan")),
        )

    target = 0.93
    if "C" in all_summaries:
        mean_ratio_c = all_summaries["C"].get("mean_ratio", float("inf"))
        if mean_ratio_c < target:
            logger.info(
                "✓ 方案C 达标! mean_ratio=%.4f < %.3f (改善 %.1f%% vs baseline %.4f)",
                mean_ratio_c, target,
                100 * (1 - mean_ratio_c / all_summaries["A"].get("mean_ratio", 1.0)),
                all_summaries["A"].get("mean_ratio", float("nan")),
            )
        else:
            logger.warning(
                "✗ 方案C 未达标: mean_ratio=%.4f >= %.3f", mean_ratio_c, target,
            )

    # 保存结果
    output = {
        "configs": all_summaries,
        "target_ratio": target,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    out_path = REPO / "dreambuddy_evolution" / "tests" / "e7_poc_cross_attention_result.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info("结果已保存: %s", out_path)


if __name__ == "__main__":
    main()
