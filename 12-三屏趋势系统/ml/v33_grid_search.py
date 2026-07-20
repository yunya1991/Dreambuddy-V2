"""v3.3 参数扫描

测试不同的布林带网格参数，找到最优组合。
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from backtest.strategy import EnhancedMA200Strategy
from ml.grid_dip_buy_strategy import GridDipBuyStrategy
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


def run_grid_search():
    engine = ScenarioBacktestEngine()
    prices = load_local_data("BTC")

    # v2基线
    print("⏳ v2 基线...")
    v2 = EnhancedMA200Strategy(is_btc=True)
    v2_r = engine.run_scenario_backtest(prices, v2, "v2_baseline", symbol="BTC", experiment_name="v33_grid_v2")
    print(f"  ✅ 夏普 {v2_r.overall_sharpe:.3f} | 收益 {v2_r.overall_total_return:.1%} | 评分 {v2_r.composite_score:.3f}")
    print()

    # 参数组合
    configs = [
        # 基础配置（接近v2）
        ("v2基线", {"bb_period": 20, "bb_std": 2.0, "bb_grid_step": 0.0, "bb_max_extra": 0.0}),

        # 不同网格步长
        ("网格步长2%", {"bb_period": 20, "bb_std": 2.0, "bb_grid_step": 0.02, "bb_max_extra": 0.2}),
        ("网格步长5%", {"bb_period": 20, "bb_std": 2.0, "bb_grid_step": 0.05, "bb_max_extra": 0.2}),
        ("网格步长10%", {"bb_period": 20, "bb_std": 2.0, "bb_grid_step": 0.10, "bb_max_extra": 0.3}),

        # 不同布林带周期
        ("布林带10日", {"bb_period": 10, "bb_std": 2.0, "bb_grid_step": 0.05, "bb_max_extra": 0.2}),
        ("布林带30日", {"bb_period": 30, "bb_std": 2.0, "bb_grid_step": 0.05, "bb_max_extra": 0.2}),
        ("布林带60日", {"bb_period": 60, "bb_std": 2.0, "bb_grid_step": 0.05, "bb_max_extra": 0.2}),

        # 不同标准差倍数
        ("布林带1.5σ", {"bb_period": 20, "bb_std": 1.5, "bb_grid_step": 0.03, "bb_max_extra": 0.2}),
        ("布林带2.5σ", {"bb_period": 20, "bb_std": 2.5, "bb_grid_step": 0.05, "bb_max_extra": 0.2}),
        ("布林带3σ", {"bb_period": 20, "bb_std": 3.0, "bb_grid_step": 0.05, "bb_max_extra": 0.2}),

        # 更大的最大额外仓位
        ("最大额外30%", {"bb_period": 20, "bb_std": 2.0, "bb_grid_step": 0.05, "bb_max_extra": 0.3}),
        ("最大额外50%", {"bb_period": 20, "bb_std": 2.0, "bb_grid_step": 0.05, "bb_max_extra": 0.5}),

        # 头肩底开关对比
        ("无头肩底", {"bb_period": 20, "bb_std": 2.0, "bb_grid_step": 0.05, "bb_max_extra": 0.2, "use_hs_confirmation": False}),

        # 更密集的网格
        ("密集网格", {"bb_period": 10, "bb_std": 1.5, "bb_grid_step": 0.02, "bb_max_extra": 0.3}),
    ]

    results = []
    print(f"{'配置':<18} {'总收益':>10} {'夏普':>8} {'卡玛':>8} {'回撤':>10} {'评分':>8} {'DIP胜率':>10} {'DIP收益':>10} {'网格次数':>8}")
    print("-" * 110)

    for name, kwargs in configs:
        use_bb = kwargs.pop("bb_grid_step", 0) > 0 and kwargs.get("bb_max_extra", 0) > 0
        strategy = GridDipBuyStrategy(
            is_btc=True,
            use_bb_grid=use_bb,
            **kwargs,
        )
        result = engine.run_scenario_backtest(
            prices, strategy, name.replace(" ", "_"),
            symbol="BTC", experiment_name=f"v33_grid_{name.replace(' ', '_')}",
        )
        dip = result.objective_metrics["dip_buy"]
        stats = strategy.get_stats()
        bb_count = stats.get("bb_grid_buy_days", 0)

        marker = " ⭐" if result.composite_score > v2_r.composite_score else ""
        print(
            f"{name:<18} "
            f"{result.overall_total_return:>10.1%} "
            f"{result.overall_sharpe:>8.3f} "
            f"{result.overall_calmar:>8.3f} "
            f"{result.overall_max_drawdown:>10.1%} "
            f"{result.composite_score:>8.3f}{marker} "
            f"{dip.win_rate:>10.2%} "
            f"{dip.avg_return:>10.2%} "
            f"{bb_count:>8}"
        )
        results.append((name, result, stats))

    print()
    print("🏆 综合评分Top 5:")
    sorted_results = sorted(results, key=lambda x: x[1].composite_score, reverse=True)
    for i, (name, r, s) in enumerate(sorted_results[:5]):
        print(f"  {i+1}. {name}: 评分 {r.composite_score:.3f}, 夏普 {r.overall_sharpe:.3f}, 收益 {r.overall_total_return:.1%}")

    print()
    best_name, best_result, best_stats = sorted_results[0]
    print(f"💡 最佳配置: {best_name}")
    if best_result.composite_score > v2_r.composite_score:
        print(f"   🎉 超越v2基线！超出 {best_result.composite_score - v2_r.composite_score:.3f}")
    else:
        print(f"   ⚠️  未超越v2基线，差距 {v2_r.composite_score - best_result.composite_score:.3f}")

    print()
    return results


if __name__ == "__main__":
    run_grid_search()
