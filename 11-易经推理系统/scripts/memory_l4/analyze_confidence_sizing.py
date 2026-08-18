#!/usr/bin/env python3
"""
置信度→仓位/杠杆调控 可行性分析

用已有回测交易明细（含 confidence 和 pnl_pct），分析：
  1. 置信度分布
  2. 置信度与收益的相关性（高置信度是否确实收益更高）
  3. 模拟不同仓位调控策略的收益/夏普/回撤变化
  4. 得出是否值得实施的结论

注意：当前回测的 pnl_pct 是等仓位假设下的价格变动百分比。
引入 size_mult 后，调整后收益 = pnl_pct * size_mult。
"""
import os
import sys
import importlib

# 修复 inspect 模块遮蔽（必须在 pandas/dataclasses 之前）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_remove_paths = [p for p in sys.path if 'memory_l4' in p or p == SCRIPT_DIR]
for _p in _remove_paths:
    if _p in sys.path:
        sys.path.remove(_p)
_std_inspect = importlib.import_module('inspect')
sys.modules['inspect'] = _std_inspect

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "bcrm2_phase0")

SYMBOLS = ["BTC", "ETH", "SOL", "UNI"]


def load_trades():
    """加载所有币种的交易明细"""
    all_trades = []
    for sym in SYMBOLS:
        path = os.path.join(DATA_DIR, f"trades_{sym}_1H.csv")
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        df["symbol"] = sym
        all_trades.append(df)
    if not all_trades:
        return None
    return pd.concat(all_trades, ignore_index=True)


def analyze_confidence_distribution(trades):
    """1. 置信度分布"""
    print("\n" + "=" * 80)
    print("  1. 置信度分布")
    print("=" * 80)

    print(f"\n  总交易数: {len(trades)}")
    print(f"  置信度均值: {trades['confidence'].mean():.3f}")
    print(f"  置信度中位数: {trades['confidence'].median():.3f}")
    print(f"  置信度标准差: {trades['confidence'].std():.3f}")
    print(f"  置信度范围: [{trades['confidence'].min():.3f}, {trades['confidence'].max():.3f}]")

    # 分桶统计
    bins = [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    labels = ["<0.4", "0.4-0.5", "0.5-0.6", "0.6-0.7", "0.7-0.8", "0.8-0.9", "0.9+"]
    trades["conf_bucket"] = pd.cut(trades["confidence"], bins=bins, labels=labels, right=False)

    print(f"\n  {'置信度区间':<12} {'交易数':<8} {'占比':<8} {'胜率':<8} {'平均收益%':<10} {'总收益%':<10}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*10}")
    for label in labels:
        subset = trades[trades["conf_bucket"] == label]
        if len(subset) == 0:
            continue
        wr = (subset["pnl_pct"] > 0).mean() * 100
        avg_ret = subset["pnl_pct"].mean()
        total_ret = subset["pnl_pct"].sum()
        pct = len(subset) / len(trades) * 100
        print(f"  {label:<12} {len(subset):<8} {pct:<7.1f}% {wr:<7.1f}% {avg_ret:<9.3f} {total_ret:<9.2f}")


def analyze_confidence_return_correlation(trades):
    """2. 置信度与收益的相关性"""
    print("\n" + "=" * 80)
    print("  2. 置信度与收益的相关性")
    print("=" * 80)

    # Pearson 相关系数
    corr = trades["confidence"].corr(trades["pnl_pct"])
    print(f"\n  Pearson 相关系数 (置信度 vs 收益): {corr:.4f}")

    # Spearman 秩相关
    spearman = trades["confidence"].corr(trades["pnl_pct"], method="spearman")
    print(f"  Spearman 秩相关: {spearman:.4f}")

    # 按方向分析
    for direction in ["LONG", "SHORT"]:
        subset = trades[trades["direction"] == direction]
        if len(subset) < 10:
            continue
        c = subset["confidence"].corr(subset["pnl_pct"])
        wr = (subset["pnl_pct"] > 0).mean() * 100
        print(f"\n  {direction}: 相关={c:.4f}, 胜率={wr:.1f}%, 交易数={len(subset)}")

    # 高置信度 vs 低置信度对比
    high_conf = trades[trades["confidence"] >= 0.7]
    low_conf = trades[trades["confidence"] < 0.5]
    mid_conf = trades[(trades["confidence"] >= 0.5) & (trades["confidence"] < 0.7)]

    print(f"\n  {'分组':<12} {'交易数':<8} {'胜率':<8} {'平均收益%':<10} {'总收益%':<10} {'盈亏比':<8}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*8}")
    for name, subset in [("低 conf<0.5", low_conf), ("中 0.5-0.7", mid_conf), ("高 conf>=0.7", high_conf)]:
        if len(subset) == 0:
            continue
        wr = (subset["pnl_pct"] > 0).mean() * 100
        avg_ret = subset["pnl_pct"].mean()
        total_ret = subset["pnl_pct"].sum()
        wins = subset[subset["pnl_pct"] > 0]["pnl_pct"].sum()
        losses = abs(subset[subset["pnl_pct"] < 0]["pnl_pct"].sum())
        pf = wins / losses if losses > 0 else float('inf')
        print(f"  {name:<12} {len(subset):<8} {wr:<7.1f}% {avg_ret:<9.3f} {total_ret:<9.2f} {pf:<7.2f}")

    return high_conf, mid_conf, low_conf


def simulate_sizing_strategies(trades):
    """3. 模拟不同仓位调控策略"""
    print("\n" + "=" * 80)
    print("  3. 模拟仓位调控策略")
    print("=" * 80)

    # 基线：等仓位
    baseline_return = trades["pnl_pct"].sum()
    baseline_trades = trades["pnl_pct"].values
    # 简单夏普：mean / std * sqrt(年化因子)，这里用交易级别
    baseline_sharpe = trades["pnl_pct"].mean() / trades["pnl_pct"].std() * np.sqrt(len(trades)) if trades["pnl_pct"].std() > 0 else 0
    # 回撤
    cumulative = np.cumsum(baseline_trades)
    baseline_dd = float(np.max(np.maximum.accumulate(cumulative) - cumulative))

    print(f"\n  基线（等仓位）: 总收益={baseline_return:.2f}%, 交易夏普={baseline_sharpe:.2f}, 最大回撤={baseline_dd:.2f}%")

    # 策略定义
    strategies = {
        "S1: 线性 (0.4→0.5x, 0.9→1.5x)": lambda c: 0.5 + (c - 0.4) / (0.9 - 0.4) * 1.0,
        "S2: 线性温和 (0.4→0.7x, 0.9→1.3x)": lambda c: 0.7 + (c - 0.4) / (0.9 - 0.4) * 0.6,
        "S3: 分档 (低0.5x/中1.0x/高1.5x)": lambda c: 0.5 if c < 0.5 else (1.5 if c >= 0.7 else 1.0),
        "S4: 分档温和 (低0.7x/中1.0x/高1.3x)": lambda c: 0.7 if c < 0.5 else (1.3 if c >= 0.7 else 1.0),
        "S5: 阈值过滤+加仓 (低0x/中1.0x/高1.5x)": lambda c: 0.0 if c < 0.45 else (1.5 if c >= 0.75 else 1.0),
        "S6: Sigmoid (0.4→0.6x, 0.9→1.4x)": lambda c: 0.6 + 0.8 / (1 + np.exp(-(c - 0.65) * 10)),
        "S7: 仅加仓不减仓 (低1.0x/中1.0x/高1.3x)": lambda c: 1.3 if c >= 0.7 else 1.0,
    }

    print(f"\n  {'策略':<40} {'总收益%':<10} {'收益变化':<10} {'交易夏普':<10} {'夏普变化':<10} {'回撤%':<10} {'回撤变化':<10}")
    print(f"  {'-'*40} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    results = []
    for name, func in strategies.items():
        size_mult = trades["confidence"].apply(func).values
        adjusted_pnl = trades["pnl_pct"].values * size_mult

        total_return = adjusted_pnl.sum()
        sharpe = adjusted_pnl.mean() / adjusted_pnl.std() * np.sqrt(len(adjusted_pnl)) if adjusted_pnl.std() > 0 else 0
        cum = np.cumsum(adjusted_pnl)
        max_dd = float(np.max(np.maximum.accumulate(cum) - cum))

        ret_delta = total_return - baseline_return
        sharpe_delta = sharpe - baseline_sharpe
        dd_delta = max_dd - baseline_dd

        print(f"  {name:<40} {total_return:<9.2f} {ret_delta:+9.2f} {sharpe:<9.2f} {sharpe_delta:+9.2f} {max_dd:<9.2f} {dd_delta:+9.2f}")

        results.append({
            "name": name,
            "total_return": total_return,
            "sharpe": sharpe,
            "max_dd": max_dd,
            "ret_delta": ret_delta,
            "sharpe_delta": sharpe_delta,
            "dd_delta": dd_delta,
        })

    return results, baseline_return, baseline_sharpe, baseline_dd


def analyze_per_symbol(trades):
    """4. 分币种分析"""
    print("\n" + "=" * 80)
    print("  4. 分币种置信度-收益相关性")
    print("=" * 80)

    print(f"\n  {'币种':<8} {'交易数':<8} {'置信度均值':<10} {'相关系数':<10} {'高conf胜率':<10} {'低conf胜率':<10}")
    print(f"  {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    for sym in trades["symbol"].unique():
        subset = trades[trades["symbol"] == sym]
        corr = subset["confidence"].corr(subset["pnl_pct"])
        high = subset[subset["confidence"] >= 0.7]
        low = subset[subset["confidence"] < 0.5]
        high_wr = (high["pnl_pct"] > 0).mean() * 100 if len(high) > 0 else 0
        low_wr = (low["pnl_pct"] > 0).mean() * 100 if len(low) > 0 else 0
        print(f"  {sym:<8} {len(subset):<8} {subset['confidence'].mean():<9.3f} {corr:<9.4f} {high_wr:<9.1f}% {low_wr:<9.1f}%")


def draw_conclusion(trades, results, baseline_return, baseline_sharpe, baseline_dd):
    """5. 结论"""
    print("\n" + "=" * 80)
    print("  5. 分析结论")
    print("=" * 80)

    # 置信度-收益相关性
    corr = trades["confidence"].corr(trades["pnl_pct"])
    print(f"\n  置信度-收益 Pearson 相关: {corr:.4f}")
    if abs(corr) < 0.05:
        print("  → 相关性极弱，置信度对收益几乎无预测力")
    elif abs(corr) < 0.15:
        print("  → 相关性弱，置信度对收益有微弱预测力")
    elif corr > 0:
        print("  → 正相关，高置信度确实对应更高收益，仓位调控有理论基础")
    else:
        print("  → 负相关，高置信度反而收益更低，仓位调控方向需反转")

    # 最佳策略
    best = max(results, key=lambda r: r["sharpe"])
    print(f"\n  最佳夏普策略: {best['name']}")
    print(f"    夏普: {baseline_sharpe:.2f} → {best['sharpe']:.2f} ({best['sharpe_delta']:+.2f})")
    print(f"    收益: {baseline_return:.2f}% → {best['total_return']:.2f}% ({best['ret_delta']:+.2f}%)")
    print(f"    回撤: {baseline_dd:.2f}% → {best['max_dd']:.2f}% ({best['dd_delta']:+.2f}%)")

    # 收益最佳策略
    best_ret = max(results, key=lambda r: r["total_return"])
    print(f"\n  最佳收益策略: {best_ret['name']}")
    print(f"    收益: {baseline_return:.2f}% → {best_ret['total_return']:.2f}% ({best_ret['ret_delta']:+.2f}%)")
    print(f"    夏普: {baseline_sharpe:.2f} → {best_ret['sharpe']:.2f} ({best_ret['sharpe_delta']:+.2f})")
    print(f"    回撤: {baseline_dd:.2f}% → {best_ret['max_dd']:.2f}% ({best_ret['dd_delta']:+.2f}%)")

    # 是否值得实施
    print(f"\n  {'='*60}")
    positive_sharpe = [r for r in results if r["sharpe_delta"] > 0]
    positive_return = [r for r in results if r["ret_delta"] > 0]
    both_positive = [r for r in results if r["sharpe_delta"] > 0 and r["ret_delta"] > 0]

    print(f"  7个策略中:")
    print(f"    夏普提升: {len(positive_sharpe)}/7")
    print(f"    收益提升: {len(positive_return)}/7")
    print(f"    夏普+收益双提升: {len(both_positive)}/7")

    if len(both_positive) >= 3:
        print(f"\n  ✅ 结论: 值得实施")
        print(f"     多个策略实现夏普+收益双提升，置信度仓位调控有正向价值")
        print(f"     建议选择夏普提升最大且回撤不恶化的策略进行回测验证")
    elif len(positive_return) >= 3:
        print(f"\n  ⚠️  结论: 有条件值得实施")
        print(f"     收益可提升但夏普不一定改善，需权衡风险调整收益")
        print(f"     建议选择收益提升且夏普不降的策略，需回测验证")
    else:
        print(f"\n  ❌ 结论: 不值得实施")
        print(f"     置信度对收益预测力不足，仓位调控无正向价值")
    print(f"  {'='*60}")


def main():
    print("=" * 80)
    print("  置信度→仓位/杠杆调控 可行性分析")
    print("=" * 80)

    trades = load_trades()
    if trades is None:
        print("  ❌ 无交易数据")
        return

    print(f"\n  加载交易数据: {len(trades)} 笔")
    print(f"  币种: {', '.join(trades['symbol'].unique())}")

    # 1. 置信度分布
    analyze_confidence_distribution(trades)

    # 2. 置信度-收益相关性
    analyze_confidence_return_correlation(trades)

    # 3. 模拟仓位调控策略
    results, baseline_return, baseline_sharpe, baseline_dd = simulate_sizing_strategies(trades)

    # 4. 分币种分析
    analyze_per_symbol(trades)

    # 5. 结论
    draw_conclusion(trades, results, baseline_return, baseline_sharpe, baseline_dd)


if __name__ == "__main__":
    main()
