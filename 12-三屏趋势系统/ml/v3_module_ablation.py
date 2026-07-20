"""v3模块消融实验

分别测试：
1. 仅启用抄底优化（DIP_BUY）
2. 仅启用逃顶优化（TOP_EXIT）
3. 两者都启用（完整v3）

对比v2基线，量化每个模块的独立贡献。
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from backtest.strategy import EnhancedMA200Strategy
from ml.enhanced_ma200_v3_strategy import EnhancedMA200V3Strategy
from ml.scenario_backtest_engine import ScenarioBacktestEngine


def load_local_data(symbol):
    filepath = f"data/historical/{symbol}_1D_730d.json"
    with open(filepath) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def run_ablation():
    engine = ScenarioBacktestEngine()
    prices = load_local_data("BTC")

    print("=" * 90)
    print("  v3模块消融实验 — 分别测试抄底和逃顶的独立贡献")
    print("=" * 90)
    print()

    configs = [
        ("v2 基线", {
            "use_dip_enhanced": False,
            "use_exit_enhanced": False,
        }),
        ("v3 仅抄底优化", {
            "use_dip_enhanced": True,
            "use_exit_enhanced": False,
        }),
        ("v3 仅逃顶优化", {
            "use_dip_enhanced": False,
            "use_exit_enhanced": True,
        }),
        ("v3 完整优化", {
            "use_dip_enhanced": True,
            "use_exit_enhanced": True,
        }),
    ]

    results = {}

    for name, cfg in configs:
        print(f"⏳ 运行: {name}...")

        if name == "v2 基线":
            strategy = EnhancedMA200Strategy(is_btc=True)
        else:
            strategy = EnhancedMA200V3Strategy(
                is_btc=True,
                # 抄底相关
                weekly_ma200_dip_buy=cfg["use_dip_enhanced"],
                dip_buy_max_position=0.9 if cfg["use_dip_enhanced"] else 0.8,
                dip_buy_levels=6 if cfg["use_dip_enhanced"] else 4,
                dip_buy_step_pct=3.0 if cfg["use_dip_enhanced"] else 5.0,
                dip_buy_initial_pct=0.1 if cfg["use_dip_enhanced"] else 1.0,
                dip_buy_end_on_ma200_breakout=cfg["use_dip_enhanced"],
                # 逃顶相关
                use_ma128_exit=cfg["use_exit_enhanced"],
                use_bounce_sell=cfg["use_exit_enhanced"],
            )

        result = engine.run_scenario_backtest(
            prices, strategy, name.replace(" ", "_"),
            symbol="BTC", experiment_name=f"ablation_{name.replace(' ', '_')}",
        )
        results[name] = result
        print(f"  ✅ 完成 | 夏普: {result.overall_sharpe:.3f} | 收益: {result.overall_total_return:.1%} | 评分: {result.composite_score:.3f}")
        print()

    # === 整体对比表 ===
    print("=" * 90)
    print("  一、整体表现对比")
    print("=" * 90)
    print()
    print(f"{'配置':<18} {'总收益':>12} {'夏普':>8} {'卡玛':>8} {'最大回撤':>10} {'交易数':>8} {'综合评分':>10}")
    print("-" * 90)

    for name, result in results.items():
        print(
            f"{name:<18} "
            f"{result.overall_total_return:>12.1%} "
            f"{result.overall_sharpe:>8.3f} "
            f"{result.overall_calmar:>8.3f} "
            f"{result.overall_max_drawdown:>10.1%} "
            f"{result.overall_trade_count:>8.0f} "
            f"{result.composite_score:>10.3f}"
        )

    print()

    # === DIP_BUY 对比 ===
    print("=" * 90)
    print("  二、DIP_BUY（牛市抄底）对比")
    print("=" * 90)
    print()
    print(f"{'配置':<18} {'信号数':>8} {'胜率':>8} {'平均收益':>10} {'Precision':>10} {'Recall':>8} {'F1':>8}")
    print("-" * 90)

    for name, result in results.items():
        m = result.objective_metrics.get("dip_buy")
        if m:
            print(
                f"{name:<18} "
                f"{m.total_signals:>8.0f} "
                f"{m.win_rate:>8.2%} "
                f"{m.avg_return:>10.2%} "
                f"{m.label_precision:>10.3f} "
                f"{m.label_recall:>8.3f} "
                f"{m.label_f1:>8.3f}"
            )

    print()

    # === TOP_EXIT 对比 ===
    print("=" * 90)
    print("  三、TOP_EXIT（牛市离场）对比")
    print("=" * 90)
    print()
    print(f"{'配置':<18} {'信号数':>8} {'胜率':>8} {'平均收益':>10} {'Precision':>10} {'Recall':>8} {'F1':>8}")
    print("-" * 90)

    for name, result in results.items():
        m = result.objective_metrics.get("top_exit")
        if m:
            print(
                f"{name:<18} "
                f"{m.total_signals:>8.0f} "
                f"{m.win_rate:>8.2%} "
                f"{m.avg_return:>10.2%} "
                f"{m.label_precision:>10.3f} "
                f"{m.label_recall:>8.3f} "
                f"{m.label_f1:>8.3f}"
            )

    print()

    # === 结论 ===
    print("=" * 90)
    print("  四、模块贡献分析")
    print("=" * 90)
    print()

    v2 = results["v2 基线"]
    dip_only = results["v3 仅抄底优化"]
    exit_only = results["v3 仅逃顶优化"]
    full = results["v3 完整优化"]

    print("📈 抄底优化独立贡献：")
    print(f"  综合评分: {v2.composite_score:.3f} → {dip_only.composite_score:.3f} ({dip_only.composite_score - v2.composite_score:+.3f})")
    print(f"  夏普比率: {v2.overall_sharpe:.3f} → {dip_only.overall_sharpe:.3f} ({dip_only.overall_sharpe - v2.overall_sharpe:+.3f})")
    print(f"  DIP胜率: {v2.objective_metrics['dip_buy'].win_rate:.2%} → {dip_only.objective_metrics['dip_buy'].win_rate:.2%}")
    print(f"  DIP收益: {v2.objective_metrics['dip_buy'].avg_return:.2%} → {dip_only.objective_metrics['dip_buy'].avg_return:.2%}")
    print()

    print("📉 逃顶优化独立贡献：")
    print(f"  综合评分: {v2.composite_score:.3f} → {exit_only.composite_score:.3f} ({exit_only.composite_score - v2.composite_score:+.3f})")
    print(f"  夏普比率: {v2.overall_sharpe:.3f} → {exit_only.overall_sharpe:.3f} ({exit_only.overall_sharpe - v2.overall_sharpe:+.3f})")
    print(f"  TOP胜率: {v2.objective_metrics['top_exit'].win_rate:.2%} → {exit_only.objective_metrics['top_exit'].win_rate:.2%}")
    print(f"  TOP收益: {v2.objective_metrics['top_exit'].avg_return:.2%} → {exit_only.objective_metrics['top_exit'].avg_return:.2%}")
    print()

    if dip_only.composite_score > v2.composite_score:
        print("✅ 结论：抄底优化有效，可单独采纳")
    else:
        print("❌ 结论：抄底优化效果不明显")

    if exit_only.composite_score > v2.composite_score:
        print("✅ 结论：逃顶优化有效，可单独采纳")
    else:
        print("❌ 结论：逃顶优化目前无效，需重新设计")

    print()
    return results


if __name__ == "__main__":
    run_ablation()
