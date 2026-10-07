"""消融实验 — 验证交叉验证层各优化模块的边际贡献.

实验组:
  E0 全功能:     Q1+Q2+Q3+Q4+Q5 全开
  E1 无 Q2:      关闭 head_multipliers floor/ceiling/mean reversion
  E2 无 Q5:      关闭 structural_break 类型加权（简单 OR）
  E3 无 Q4 降级: G_dim=None 时直接中性（不降级到单链路）
  E4 纯 Attention: G_dim=None 全程（只用 A_dim 单链路）

指标: OOS 夏普 / DSR / PBO + Holm-Bonferroni 配对校正
"""
from __future__ import annotations

import json
import os
from typing import Optional

import numpy as np

from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate
from dreambuddy_evolution.core.framework_comparison import (
    FrameworkComparison,
    holm_bonferroni,
)


ABLATION_CONFIGS = {
    "E0_full": {
        "persistence_threshold": 3,
        "structural_break_threshold": 0.5,
        "head_floor": 0.1,
        "head_ceiling": 2.0,
        "enable_head_multipliers_mean_reversion": True,
        "enable_degraded_mode": True,
        "enable_structural_break_weighting": True,
        "use_granger": True,  # G_dim 来自 Granger
    },
    "E1_no_Q2": {
        "persistence_threshold": 3,
        "structural_break_threshold": 0.5,
        "head_floor": 0.0,
        "head_ceiling": 1e9,
        "enable_head_multipliers_mean_reversion": False,
        "enable_degraded_mode": True,
        "enable_structural_break_weighting": True,
        "use_granger": True,
    },
    "E2_no_Q5": {
        "persistence_threshold": 3,
        "structural_break_threshold": 0.5,
        "head_floor": 0.1,
        "head_ceiling": 2.0,
        "enable_head_multipliers_mean_reversion": True,
        "enable_degraded_mode": True,
        "enable_structural_break_weighting": False,
        "use_granger": True,
    },
    "E3_no_Q4": {
        "persistence_threshold": 3,
        "structural_break_threshold": 0.5,
        "head_floor": 0.1,
        "head_ceiling": 2.0,
        "enable_head_multipliers_mean_reversion": True,
        "enable_degraded_mode": False,
        "enable_structural_break_weighting": True,
        "use_granger": True,
    },
    "E4_attention_only": {
        "persistence_threshold": 3,
        "structural_break_threshold": 0.5,
        "head_floor": 0.1,
        "head_ceiling": 2.0,
        "enable_head_multipliers_mean_reversion": True,
        "enable_degraded_mode": True,
        "enable_structural_break_weighting": True,
        "use_granger": False,  # G_dim=None 全程
    },
}


def momentum_direction(factors: np.ndarray, i: int, factor_idx: int) -> float:
    """因子方向：最近 w 期均值 vs 前一期."""
    w = 60
    if i < w + 1:
        return 0.0
    recent = np.mean(factors[i - w : i, factor_idx])
    prev = factors[i - w - 1, factor_idx]
    return recent - prev


def run_ablation_signal(
    factors: np.ndarray, returns: np.ndarray, config: dict
) -> np.ndarray:
    """运行单个消融实验组的信号生成."""
    w = 60
    n = len(returns)
    sig = np.zeros(n)

    gate_kwargs = {
        k: v
        for k, v in config.items()
        if k != "use_granger"
    }
    gate = CrossValidationGate(**gate_kwargs)

    factor_dim_map = ["technical", "technical", "fundamental", "fundamental", "macro"]
    dims = ["technical", "fundamental", "macro"]

    for i in range(w * 2, n):
        past_rets = returns[i - 2 * w : i - w]
        past_factors = factors[i - 2 * w : i - w]

        # G_dim: 过去因
        if config["use_granger"]:
            corrs = [
                np.corrcoef(past_factors[:, j], past_rets)[0, 1]
                if np.std(past_factors[:, j]) > 1e-10
                else 0.0
                for j in range(factors.shape[1])
            ]
            best_g = int(np.argmax(np.abs(corrs)))
            g_dim = factor_dim_map[best_g]
            g_conf = abs(corrs[best_g])
        else:
            g_dim = None
            g_conf = 0.0
            best_g = 0

        # A_dim: 现在力
        recent_factors = factors[i - w : i]
        recent_rets = returns[i - w : i]
        attn_weights = np.array(
            [
                abs(np.corrcoef(recent_factors[:, j], recent_rets)[0, 1])
                if np.std(recent_factors[:, j]) > 1e-10
                else 0.0
                for j in range(factors.shape[1])
            ]
        )
        dim_strength = {d: 0.0 for d in dims}
        for j, d in enumerate(factor_dim_map):
            dim_strength[d] += attn_weights[j]
        total = sum(dim_strength.values())
        if total > 0:
            dim_strength = {k: v / total for k, v in dim_strength.items()}
        a_dim = max(dim_strength, key=dim_strength.get)
        a_strength = dim_strength[a_dim]

        # 结构性断裂
        vol_recent = np.std(recent_rets)
        vol_past = np.std(returns[i - 2 * w : i - w])
        vol_shift = bool(vol_recent > vol_past * 1.3) if vol_past > 1e-10 else False

        # 相关性断裂：过去 vs 现在 因子-收益相关性显著变化
        corr_recent = abs(np.corrcoef(recent_factors[:, 0], recent_rets)[0, 1]) if np.std(recent_factors[:, 0]) > 1e-10 else 0.0
        corr_past = abs(np.corrcoef(past_factors[:, 0], past_rets)[0, 1]) if np.std(past_factors[:, 0]) > 1e-10 else 0.0
        corr_break = bool(abs(corr_recent - corr_past) > 0.3)

        # 市场形态转变：Hurst 近似（用收益率自相关系数符号变化代理）
        ac_recent = np.corrcoef(recent_rets[:-1], recent_rets[1:])[0, 1] if np.std(recent_rets[:-1]) > 1e-10 else 0.0
        ac_past = np.corrcoef(past_rets[:-1], past_rets[1:])[0, 1] if np.std(past_rets[:-1]) > 1e-10 else 0.0
        form_shift = bool((ac_recent > 0) != (ac_past > 0))

        structural_break = {
            "volatility_regime_shift": vol_shift,
            "correlation_break": corr_break,
            "market_form_shift": form_shift,
        }

        result = gate.compare(
            G_dim=g_dim,
            G_conf=g_conf,
            A_dim=a_dim,
            A_strength=a_strength,
            structural_break=structural_break,
        )

        # 信号方向：用 A_dim 对应因子的动量方向
        direction = 1.0 if momentum_direction(factors, i, best_g) > 0 else -1.0

        if result["confidence_mult"] > 1.0:
            # 一致：放大信号
            sig[i] = direction * result["confidence_mult"]
        elif result["shift_signal"]:
            # 分歧：信号幅度受 head_adjustment 影响（Q2）
            head_mult = 1.0
            if result["head_adjustment"]:
                # 取 A_dim 对应 head 的平均 multiplier
                a_heads = [h for h in result["head_adjustment"].keys()]
                if a_heads:
                    head_mult = np.mean(list(result["head_adjustment"].values()))
            sig[i] = direction * result["confidence_mult"] * head_mult

        # 质变（Q5）：主矛盾转移，反转信号方向
        if result["quality_change"]:
            sig[i] = -sig[i]

    return sig


def generate_simulated_prices(n: int = 5000, seed: int = 42) -> np.ndarray:
    """生成带 regime shift + 动量效应的模拟价格序列.

    包含 3 个 regime：
      - 动量主导期：趋势延续
      - 均值回归期：反转
      - 高波动期：噪声主导
    """
    rng = np.random.RandomState(seed)
    log_prices = np.zeros(n)
    log_prices[0] = np.log(100.0)
    regime_len = n // 3

    for i in range(1, n):
        p = np.exp(log_prices[i - 1])
        if i < regime_len:
            # 动量主导
            drift = 0.0003
            vol = 0.01
            if i > 10:
                momentum = (log_prices[i - 1] - log_prices[i - 10]) / 10.0
                drift += np.clip(momentum * 0.3, -0.005, 0.005)
        elif i < 2 * regime_len:
            # 均值回归
            drift = -0.0002
            vol = 0.015
            if i > 5:
                mean_rev = (log_prices[i - 1] - log_prices[i - 5]) / 5.0
                drift -= np.clip(mean_rev * 0.2, -0.005, 0.005)
        else:
            # 高波动
            drift = 0.0
            vol = 0.02

        log_ret = drift + vol * rng.randn()
        log_prices[i] = log_prices[i - 1] + log_ret

    return np.exp(log_prices)


def main():
    data_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "btc_30m_close.npy"
    )
    if os.path.exists(data_path):
        prices = np.load(data_path)
        print(f"加载 BTC 30m 数据: {len(prices)} 期")
    else:
        print(f"真实数据不存在 ({data_path})，使用模拟数据")
        prices = generate_simulated_prices(n=5000)
        print(f"模拟数据: {len(prices)} 期（3 regime: 动量/均值回归/高波动）")

    comp = FrameworkComparison(prices, window=60)
    factors = comp.build_factors()
    returns = comp.returns
    n = len(returns)

    # 训练/测试分割：前 70% 训练，后 30% OOS
    split = int(n * 0.7)
    train_factors = factors[:split]
    train_returns = returns[:split]
    oos_factors = factors[split:]
    oos_returns = returns[split:]

    # 生成所有组的 OOS 信号
    all_sigs = {}
    for name, config in ABLATION_CONFIGS.items():
        print(f"运行 {name}...")
        all_sigs[name] = run_ablation_signal(oos_factors, oos_returns, config)

    results = {}
    print("\n=== 消融实验 OOS 指标 ===")
    for name, sig in all_sigs.items():
        min_len = min(len(sig), len(oos_returns))
        strat_rets = sig[:min_len] * oos_returns[:min_len]
        sharpe = comp.sharpe_ratio(strat_rets)
        dsr = comp.deflated_sharpe_ratio(strat_rets, n_trials=len(ABLATION_CONFIGS))
        winrate = float(np.mean(strat_rets > 0)) if len(strat_rets) > 0 else 0.0
        results[name] = {
            "sharpe": sharpe,
            "dsr": dsr,
            "winrate": winrate,
        }
        print(f"  {name}: sharpe={sharpe:.2f}, dsr={dsr:.4f}, winrate={winrate:.3f}")

    # Holm-Bonferroni 配对检验（E0 vs 其他）
    e0_rets = None
    pairwise_p = {}
    from scipy import stats

    for name, sig in all_sigs.items():
        min_len = min(len(sig), len(oos_returns))
        strat_rets = sig[:min_len] * oos_returns[:min_len]
        if name == "E0_full":
            e0_rets = strat_rets
        elif e0_rets is not None:
            min_l = min(len(e0_rets), len(strat_rets))
            t_stat, p_val = stats.ttest_rel(e0_rets[:min_l], strat_rets[:min_l])
            pairwise_p[name] = p_val

    adj_p = holm_bonferroni(pairwise_p)
    print("\n=== 配对检验 (E0 vs 其他, Holm-Bonferroni) ===")
    for name, p in adj_p.items():
        sig_mark = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
        print(f"  E0 vs {name}: adj_p={p:.6f} {sig_mark}")

    # PBO（用训练集信号）
    train_sigs = {
        name: run_ablation_signal(train_factors, train_returns, cfg)
        for name, cfg in ABLATION_CONFIGS.items()
    }
    pbo = comp.probability_of_backtest_overfitting(train_sigs, train_returns, n_splits=5)
    print(f"\nPBO (过拟合概率): {pbo:.4f}")

    # 保存结果
    output = {
        "configs": ABLATION_CONFIGS,
        "metrics": results,
        "pairwise_holm_bonferroni": adj_p,
        "pbo": pbo,
    }
    out_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "ablation_result.json"
    )
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
