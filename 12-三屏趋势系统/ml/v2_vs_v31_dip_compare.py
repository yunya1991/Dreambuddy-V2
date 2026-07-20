"""v2 vs v3.1 抄底优化专项对比

只对比抄底优化的效果，用分场景回测引擎准确计算。
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from backtest.strategy import EnhancedMA200Strategy
from ml.enhanced_ma200_v31_strategy import EnhancedMA200V31Strategy
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


def run_compare():
    engine = ScenarioBacktestEngine()
    prices = load_local_data("BTC")

    print("=" * 90)
    print("  v2 基线 vs v3.1 精准抄底 — 专项对比（BTC 9年）")
    print("=" * 90)
    print()
    print("v3.1改动：")
    print("  - 抄底档位：4档→6档，步长5%→3%（更精细）")
    print("  - 初始仓位：满仓起步→15%轻仓试探")
    print("  - 最大抄底仓位：80%→90%")
    print("  - 其他逻辑完全沿用v2（不改动逃顶、做空）")
    print()

    # v2
    print("⏳ 运行 v2 基线...")
    v2 = EnhancedMA200Strategy(is_btc=True)
    v2_r = engine.run_scenario_backtest(prices, v2, "v2_baseline", symbol="BTC", experiment_name="v2_v31_compare_v2")
    print(f"  ✅ 完成 | 夏普 {v2_r.overall_sharpe:.3f} | 收益 {v2_r.overall_total_return:.1%} | 评分 {v2_r.composite_score:.3f}")
    print()

    # v3.1
    print("⏳ 运行 v3.1 精准抄底...")
    v31 = EnhancedMA200V31Strategy(is_btc=True)
    v31_r = engine.run_scenario_backtest(prices, v31, "v31_dip_enhanced", symbol="BTC", experiment_name="v2_v31_compare_v31")
    print(f"  ✅ 完成 | 夏普 {v31_r.overall_sharpe:.3f} | 收益 {v31_r.overall_total_return:.1%} | 评分 {v31_r.composite_score:.3f}")
    print()

    # 整体对比
    print("=" * 90)
    print("  一、整体表现")
    print("=" * 90)
    print()
    print(f"{'指标':<20} {'v2基线':>15} {'v3.1抄底优化':>15} {'变化':>12} {'效果':>8}")
    print("-" * 90)

    metrics = [
        ("总收益率", v2_r.overall_total_return, v31_r.overall_total_return, True, "%"),
        ("夏普比率", v2_r.overall_sharpe, v31_r.overall_sharpe, True, "f"),
        ("卡玛比率", v2_r.overall_calmar, v31_r.overall_calmar, True, "f"),
        ("最大回撤", v2_r.overall_max_drawdown, v31_r.overall_max_drawdown, False, "%"),
        ("交易次数", v2_r.overall_trade_count, v31_r.overall_trade_count, False, "d"),
        ("综合评分", v2_r.composite_score, v31_r.composite_score, True, "f"),
    ]

    for name, v2_val, v31_val, higher_better, fmt in metrics:
        delta = v31_val - v2_val
        if fmt == "%":
            v2s = f"{v2_val:.2%}"
            v31s = f"{v31_val:.2%}"
            ds = f"{delta:+.2%}"
        elif fmt == "d":
            v2s = f"{v2_val:.0f}"
            v31s = f"{v31_val:.0f}"
            ds = f"{delta:+.0f}"
        else:
            v2s = f"{v2_val:.3f}"
            v31s = f"{v31_val:.3f}"
            ds = f"{delta:+.3f}"

        good = delta > 0 if higher_better else delta < 0
        effect = "✅" if good else "❌"
        print(f"{name:<20} {v2s:>15} {v31s:>15} {ds:>12} {effect:>8}")

    print()

    # DIP_BUY对比
    print("=" * 90)
    print("  二、DIP_BUY（牛市抄底）专项对比")
    print("=" * 90)
    print()

    v2_dip = v2_r.objective_metrics["dip_buy"]
    v31_dip = v31_r.objective_metrics["dip_buy"]

    print(f"{'指标':<18} {'v2':>12} {'v3.1':>12} {'变化':>12} {'效果':>8}")
    print("-" * 70)

    dip_metrics = [
        ("信号数", v2_dip.total_signals, v31_dip.total_signals, False, "d"),
        ("信号频率", v2_dip.signal_freq_pct, v31_dip.signal_freq_pct, False, "%"),
        ("胜率", v2_dip.win_rate, v31_dip.win_rate, True, "%"),
        ("平均收益", v2_dip.avg_return, v31_dip.avg_return, True, "%"),
        ("Precision", v2_dip.label_precision, v31_dip.label_precision, True, "f"),
        ("Recall", v2_dip.label_recall, v31_dip.label_recall, True, "f"),
        ("F1", v2_dip.label_f1, v31_dip.label_f1, True, "f"),
    ]

    for name, v2_val, v31_val, higher_better, fmt in dip_metrics:
        delta = v31_val - v2_val
        if fmt == "%":
            v2s = f"{v2_val:.2%}"
            v31s = f"{v31_val:.2%}"
            ds = f"{delta:+.2%}"
        elif fmt == "d":
            v2s = f"{v2_val:.0f}"
            v31s = f"{v31_val:.0f}"
            ds = f"{delta:+.0f}"
        else:
            v2s = f"{v2_val:.3f}"
            v31s = f"{v31_val:.3f}"
            ds = f"{delta:+.3f}"

        good = delta > 0 if higher_better else delta < 0
        effect = "✅" if good else "❌"
        print(f"{name:<18} {v2s:>12} {v31s:>12} {ds:>12} {effect:>8}")

    print()

    # 四类目的总览
    print("=" * 90)
    print("  三、四类目的F1分数对比")
    print("=" * 90)
    print()
    print(f"{'目的':<20} {'v2 F1':>10} {'v3.1 F1':>10} {'变化':>10}")
    print("-" * 60)
    for obj in ["dip_buy", "top_exit", "bear_short", "bear_exit"]:
        v2_f1 = v2_r.objective_metrics[obj].label_f1
        v31_f1 = v31_r.objective_metrics[obj].label_f1
        delta = v31_f1 - v2_f1
        print(f"{obj:<20} {v2_f1:>10.3f} {v31_f1:>10.3f} {delta:>+10.3f}")

    print()

    # 结论
    print("=" * 90)
    print("  四、结论")
    print("=" * 90)
    print()

    composite_delta = v31_r.composite_score - v2_r.composite_score
    if composite_delta > 0:
        print(f"🎉 综合评分提升 {composite_delta:+.3f}，抄底优化整体有效！")
    else:
        print(f"⚠️  综合评分变化 {composite_delta:+.3f}，抄底优化整体未跑赢基线")

    print()
    print("📊 DIP_BUY改善：")
    print(f"  胜率: {v2_dip.win_rate:.2%} → {v31_dip.win_rate:.2%} ({v31_dip.win_rate - v2_dip.win_rate:+.2%})")
    print(f"  收益: {v2_dip.avg_return:.2%} → {v31_dip.avg_return:.2%} ({v31_dip.avg_return - v2_dip.avg_return:+.2%})")
    print()
    print("💡 分析：")
    if v31_dip.win_rate > v2_dip.win_rate and v31_dip.avg_return > v2_dip.avg_return:
        print("  ✅ 抄底本身的胜率和收益都提升了——轻仓试探+精细加仓是有效的")
        print("  ❓ 但整体收益未提升，可能原因：")
        print("     1. 抄底仓位更轻，底部加仓慢，错过部分反弹收益")
        print("     2. 抄底最大仓位从80%→90%，但入场更晚，净效果可能为负")
        print("     3. 需要找到最优的初始仓位和档位组合")
    else:
        print("  ❌ 抄底本身效果也不佳，需重新设计")

    print()
    return v2_r, v31_r


if __name__ == "__main__":
    run_compare()
