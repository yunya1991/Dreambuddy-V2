"""v2 vs v3 策略对比回测

用分场景回测引擎对比v2基线和v3增强版策略，
重点关注DIP_BUY和TOP_EXIT两类目的的改进效果。
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
from ml.closed_loop_manager import ClosedLoopManager


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


def run_comparison():
    engine = ScenarioBacktestEngine()
    prices = load_local_data("BTC")

    print("=" * 90)
    print("  v2 (基线) vs v3 (增强版) 策略对比回测 — BTC 9年数据")
    print("=" * 90)
    print()

    # V2 基线
    print("⏳ 运行 v2 基线策略...")
    v2_strategy = EnhancedMA200Strategy(is_btc=True)
    v2_result = engine.run_scenario_backtest(
        prices, v2_strategy, "EnhancedMA200_v2",
        symbol="BTC", experiment_name="v2_baseline_compare",
    )
    print("✅ v2 完成")
    print()

    # V3 增强版
    print("⏳ 运行 v3 增强版策略...")
    v3_strategy = EnhancedMA200V3Strategy(is_btc=True)
    v3_result = engine.run_scenario_backtest(
        prices, v3_strategy, "EnhancedMA200_v3",
        symbol="BTC", experiment_name="v3_enhanced_compare",
    )
    print("✅ v3 完成")
    print()

    # 保存结果
    engine.save_result(v2_result)
    engine.save_result(v3_result)

    # === 整体对比 ===
    print("=" * 90)
    print("  一、整体表现对比")
    print("=" * 90)
    print()
    print(f"{'指标':<20} {'v2基线':>15} {'v3增强版':>15} {'变化':>12} {'效果':>8}")
    print("-" * 90)

    metrics_compare = [
        ("总收益率", v2_result.overall_total_return, v3_result.overall_total_return, True),
        ("夏普比率", v2_result.overall_sharpe, v3_result.overall_sharpe, True),
        ("卡玛比率", v2_result.overall_calmar, v3_result.overall_calmar, True),
        ("最大回撤", v2_result.overall_max_drawdown, v3_result.overall_max_drawdown, False),
        ("交易次数", v2_result.overall_trade_count, v3_result.overall_trade_count, False),
        ("综合评分", v2_result.composite_score, v3_result.composite_score, True),
    ]

    for name, v2_val, v3_val, higher_is_better in metrics_compare:
        delta = v3_val - v2_val
        if name in ["总收益率", "最大回撤"]:
            v2_str = f"{v2_val:.2%}"
            v3_str = f"{v3_val:.2%}"
            delta_str = f"{delta:+.2%}"
        elif name == "交易次数":
            v2_str = f"{v2_val:.0f}"
            v3_str = f"{v3_val:.0f}"
            delta_str = f"{delta:+.0f}"
        else:
            v2_str = f"{v2_val:.3f}"
            v3_str = f"{v3_val:.3f}"
            delta_str = f"{delta:+.3f}"

        if higher_is_better:
            good = delta > 0
        else:
            good = delta < 0

        effect = "✅" if good else "❌"
        print(f"{name:<20} {v2_str:>15} {v3_str:>15} {delta_str:>12} {effect:>8}")

    print()

    # === 四类目的对比 ===
    print("=" * 90)
    print("  二、四类目的对比")
    print("=" * 90)
    print()

    objectives = ["dip_buy", "top_exit", "bear_short", "bear_exit"]
    obj_names = {
        "dip_buy": "🐂 牛市抄底 DIP_BUY",
        "top_exit": "💰 牛市离场 TOP_EXIT",
        "bear_short": "🐻 熊市做空 BEAR_SHORT",
        "bear_exit": "🔄 熊市空平 BEAR_EXIT",
    }

    for obj in objectives:
        v2_m = v2_result.objective_metrics.get(obj)
        v3_m = v3_result.objective_metrics.get(obj)
        if not v2_m or not v3_m:
            continue

        print(f"\n{obj_names[obj]}")
        print(f"{'指标':<18} {'v2':>12} {'v3':>12} {'变化':>12} {'效果':>8}")
        print("-" * 70)

        obj_metrics = [
            ("信号数", v2_m.total_signals, v3_m.total_signals, False),
            ("信号频率%", v2_m.signal_freq_pct, v3_m.signal_freq_pct, False),
            ("胜率", v2_m.win_rate, v3_m.win_rate, True),
            ("平均收益", v2_m.avg_return, v3_m.avg_return, True),
            ("Precision", v2_m.label_precision, v3_m.label_precision, True),
            ("Recall", v2_m.label_recall, v3_m.label_recall, True),
            ("F1", v2_m.label_f1, v3_m.label_f1, True),
        ]

        for name, v2_val, v3_val, higher_is_better in obj_metrics:
            delta = v3_val - v2_val
            if name in ["胜率", "平均收益", "信号频率%"]:
                v2_str = f"{v2_val:.2%}" if name != "信号频率%" else f"{v2_val:.2f}%"
                v3_str = f"{v3_val:.2%}" if name != "信号频率%" else f"{v3_val:.2f}%"
                delta_str = f"{delta:+.2%}" if name != "信号频率%" else f"{delta:+.2f}%"
            elif name == "信号数":
                v2_str = f"{v2_val:.0f}"
                v3_str = f"{v3_val:.0f}"
                delta_str = f"{delta:+.0f}"
            else:
                v2_str = f"{v2_val:.3f}"
                v3_str = f"{v3_val:.3f}"
                delta_str = f"{delta:+.3f}"

            if higher_is_better:
                good = delta > 0
            else:
                good = delta < 0

            effect = "✅" if good else "❌"
            print(f"{name:<18} {v2_str:>12} {v3_str:>12} {delta_str:>12} {effect:>8}")

    print()

    # === v3新增功能统计 ===
    print("=" * 90)
    print("  三、v3新增功能使用统计")
    print("=" * 90)
    print()
    stats = v3_strategy.get_stats()
    v3_stats = {k: v for k, v in stats.items() if v > 0}
    for k, v in sorted(v3_stats.items(), key=lambda x: -x[1]):
        print(f"  {k:<25} {v:>6} 天")

    print()

    # === 结论 ===
    print("=" * 90)
    print("  四、结论")
    print("=" * 90)
    print()

    composite_delta = v3_result.composite_score - v2_result.composite_score
    sharpe_delta = v3_result.overall_sharpe - v2_result.overall_sharpe

    print(f"综合评分变化: {v2_result.composite_score:.3f} → {v3_result.composite_score:.3f} ({composite_delta:+.3f})")
    print(f"夏普比率变化: {v2_result.overall_sharpe:.3f} → {v3_result.overall_sharpe:.3f} ({sharpe_delta:+.3f})")
    print()

    if v3_result.composite_score > 1.0:
        print("🎉 v3综合评分 > 1.0，超越v2基线，可采纳！")
    else:
        print("⚠️  v3综合评分 ≤ 1.0，未超越v2基线，需继续优化")
        print("   分析各目的表现，针对性改进")

    print()
    print("💡 DIP_BUY 重点观察：")
    v2_dip = v2_result.objective_metrics.get("dip_buy")
    v3_dip = v3_result.objective_metrics.get("dip_buy")
    if v2_dip and v3_dip:
        print(f"  胜率: {v2_dip.win_rate:.2%} → {v3_dip.win_rate:.2%} ({v3_dip.win_rate - v2_dip.win_rate:+.2%})")
        print(f"  平均收益: {v2_dip.avg_return:.2%} → {v3_dip.avg_return:.2%} ({v3_dip.avg_return - v2_dip.avg_return:+.2%})")

    print()
    print("💡 TOP_EXIT 重点观察：")
    v2_top = v2_result.objective_metrics.get("top_exit")
    v3_top = v3_result.objective_metrics.get("top_exit")
    if v2_top and v3_top:
        print(f"  胜率: {v2_top.win_rate:.2%} → {v3_top.win_rate:.2%} ({v3_top.win_rate - v2_top.win_rate:+.2%})")
        print(f"  平均收益: {v2_top.avg_return:.2%} → {v3_top.avg_return:.2%} ({v3_top.avg_return - v2_top.avg_return:+.2%})")

    print()
    return v2_result, v3_result


if __name__ == "__main__":
    run_comparison()
