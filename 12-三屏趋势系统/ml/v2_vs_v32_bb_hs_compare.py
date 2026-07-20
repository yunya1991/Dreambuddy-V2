"""v2 vs v3.2 布林带+头肩底 抄底对比

三层抄底架构 vs v2基线
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from backtest.strategy import EnhancedMA200Strategy
from ml.bb_hs_dip_strategy import BBSHeadShoulderBottomStrategy
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
    print("  v2 基线 vs v3.2 布林带+头肩底 抄底对比 — BTC 9年")
    print("=" * 90)
    print()
    print("v3.2三层抄底架构：")
    print("  第一层：周线MA200 → 抄底大区域判断")
    print("  第二层：日线布林带 → 底部震荡高抛低吸，降成本")
    print("  第三层：头肩底形态 → 确认最终底部，加满仓")
    print()

    # 测试多组参数
    configs = [
        ("v2 基线", {}),
        ("v3.2 默认参数", {
            "bb_buy_position": 0.15,
            "bb_sell_ratio": 0.3,
            "hs_max_position": 1.0,
            "dip_buy_max_position": 1.0,
        }),
        ("v3.2 保守型", {
            "bb_buy_position": 0.1,
            "bb_sell_ratio": 0.5,
            "hs_max_position": 0.8,
            "dip_buy_max_position": 0.8,
        }),
        ("v3.2 激进型", {
            "bb_buy_position": 0.25,
            "bb_sell_ratio": 0.2,
            "hs_max_position": 1.0,
            "dip_buy_max_position": 1.0,
        }),
        ("v3.2 宽布林带", {
            "bb_period": 20,
            "bb_std": 2.5,
            "bb_buy_position": 0.2,
            "bb_sell_ratio": 0.4,
            "hs_max_position": 1.0,
            "dip_buy_max_position": 1.0,
        }),
    ]

    results = {}
    stats_dict = {}

    for name, kwargs in configs:
        print(f"⏳ 运行: {name}...")
        if name == "v2 基线":
            strategy = EnhancedMA200Strategy(is_btc=True)
        else:
            strategy = BBSHeadShoulderBottomStrategy(is_btc=True, **kwargs)

        result = engine.run_scenario_backtest(
            prices, strategy, name.replace(" ", "_"),
            symbol="BTC", experiment_name=f"v32_compare_{name.replace(' ', '_')}",
        )
        results[name] = result
        stats_dict[name] = strategy.get_stats()
        print(f"  ✅ 完成 | 夏普 {result.overall_sharpe:.3f} | 收益 {result.overall_total_return:.1%} | 评分 {result.composite_score:.3f}")
        print()

    # 整体对比
    print("=" * 90)
    print("  一、整体表现对比")
    print("=" * 90)
    print()
    print(f"{'配置':<20} {'总收益':>10} {'夏普':>8} {'卡玛':>8} {'最大回撤':>10} {'交易数':>8} {'综合评分':>10}")
    print("-" * 90)

    for name, result in results.items():
        marker = " ⭐" if result.composite_score > 1.0 else ""
        print(
            f"{name:<20} "
            f"{result.overall_total_return:>10.1%} "
            f"{result.overall_sharpe:>8.3f} "
            f"{result.overall_calmar:>8.3f} "
            f"{result.overall_max_drawdown:>10.1%} "
            f"{result.overall_trade_count:>8.0f} "
            f"{result.composite_score:>10.3f}{marker}"
        )

    print()

    # DIP_BUY对比
    print("=" * 90)
    print("  二、DIP_BUY（牛市抄底）对比")
    print("=" * 90)
    print()
    print(f"{'配置':<20} {'信号数':>8} {'胜率':>8} {'平均收益':>10} {'Precision':>10} {'Recall':>8} {'F1':>8}")
    print("-" * 90)

    for name, result in results.items():
        m = result.objective_metrics.get("dip_buy")
        if m:
            print(
                f"{name:<20} "
                f"{m.total_signals:>8.0f} "
                f"{m.win_rate:>8.2%} "
                f"{m.avg_return:>10.2%} "
                f"{m.label_precision:>10.3f} "
                f"{m.label_recall:>8.3f} "
                f"{m.label_f1:>8.3f}"
            )

    print()

    # 四类目的F1对比
    print("=" * 90)
    print("  三、四类目的F1分数对比")
    print("=" * 90)
    print()
    print(f"{'配置':<20} {'DIP_BUY':>10} {'TOP_EXIT':>10} {'BEAR_SHORT':>12} {'BEAR_EXIT':>10}")
    print("-" * 70)

    for name, result in results.items():
        dip_f1 = result.objective_metrics["dip_buy"].label_f1
        top_f1 = result.objective_metrics["top_exit"].label_f1
        short_f1 = result.objective_metrics["bear_short"].label_f1
        exit_f1 = result.objective_metrics["bear_exit"].label_f1
        print(f"{name:<20} {dip_f1:>10.3f} {top_f1:>10.3f} {short_f1:>12.3f} {exit_f1:>10.3f}")

    print()

    # v3.2功能统计
    print("=" * 90)
    print("  四、v3.2新增功能使用统计（默认参数）")
    print("=" * 90)
    print()

    default_stats = stats_dict.get("v3.2 默认参数", {})
    relevant_keys = [k for k in default_stats if k in [
        "dip_buy_days", "bb_buy_days", "bb_sell_days",
        "hs_confirmed_days", "dip_bb_days",
        "bull_days", "bear_short_l1_days", "bear_short_l2_days",
        "sideways_days", "fib_tp_days", "trend_switches",
    ]]
    for k in sorted(relevant_keys, key=lambda x: -default_stats.get(x, 0)):
        v = default_stats.get(k, 0)
        if v > 0:
            print(f"  {k:<25} {v:>6} 天")

    print()

    # 结论
    print("=" * 90)
    print("  五、结论")
    print("=" * 90)
    print()

    best_name = max(results.keys(), key=lambda k: results[k].composite_score)
    best_result = results[best_name]
    v2_result = results["v2 基线"]

    print(f"🏆 最佳配置: {best_name}")
    print(f"   综合评分: {best_result.composite_score:.3f} (v2: {v2_result.composite_score:.3f})")
    print(f"   夏普比率: {best_result.overall_sharpe:.3f} (v2: {v2_result.overall_sharpe:.3f})")
    print(f"   总收益: {best_result.overall_total_return:.1%} (v2: {v2_result.overall_total_return:.1%})")
    print()

    best_dip = best_result.objective_metrics["dip_buy"]
    v2_dip = v2_result.objective_metrics["dip_buy"]
    print("📊 DIP_BUY改善：")
    print(f"   胜率: {v2_dip.win_rate:.2%} → {best_dip.win_rate:.2%} ({best_dip.win_rate - v2_dip.win_rate:+.2%})")
    print(f"   收益: {v2_dip.avg_return:.2%} → {best_dip.avg_return:.2%} ({best_dip.avg_return - v2_dip.avg_return:+.2%})")
    print(f"   F1:   {v2_dip.label_f1:.3f} → {best_dip.label_f1:.3f} ({best_dip.label_f1 - v2_dip.label_f1:+.3f})")

    print()

    if best_result.composite_score > 1.0:
        print("🎉 超越v2基线！布林带+头肩底的三层抄底架构有效！")
    else:
        print("⚠️  未超越v2基线，需要进一步优化")
        print("   可能的方向：")
        print("   - 调整布林带参数（周期、标准差倍数）")
        print("   - 调整头肩底检测灵敏度")
        print("   - 优化仓位管理（加仓节奏、最大仓位）")
        print("   - 增加更多确认指标（RSI、MACD、成交量）")

    print()
    return results


if __name__ == "__main__":
    run_compare()
