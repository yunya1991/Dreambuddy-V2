"""v3.7 参数扫描

测试不同的布林带和双底参数组合。
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from backtest.strategy import EnhancedMA200Strategy
from ml.double_bottom_strategy import DoubleBottomDipStrategy
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

    # v2和做空优化基线
    v2 = EnhancedMA200Strategy(is_btc=True)
    v2_r = engine.run_scenario_backtest(prices, v2, "v2", symbol="BTC", experiment_name="v37gs_v2")

    so = EnhancedMA200Strategy(is_btc=True, bear_short_level1_pct=0.0, bear_short_level2_pct=0.6)
    so_r = engine.run_scenario_backtest(prices, so, "so", symbol="BTC", experiment_name="v37gs_so")

    print("🔬 v3.7 参数扫描")
    print(f"  v2基线: 收益 {v2_r.overall_total_return:.1%}, 夏普 {v2_r.overall_sharpe:.3f}, 评分 {v2_r.composite_score:.3f}")
    print(f"  做空优化: 收益 {so_r.overall_total_return:.1%}, 夏普 {so_r.overall_sharpe:.3f}, 评分 {so_r.composite_score:.3f}")
    print()

    configs = [
        # 基准
        ("基准(反弹加仓)", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.15, "bb_std": 2.0, "bb_period": 20}),

        # 不同布林带参数
        ("BB10/1.5σ", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.15, "bb_std": 1.5, "bb_period": 10}),
        ("BB10/2σ", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.15, "bb_std": 2.0, "bb_period": 10}),
        ("BB30/2σ", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.15, "bb_std": 2.0, "bb_period": 30}),

        # 不同加仓幅度
        ("反弹加5%", {"bb_lower_add_pct": 0.05, "bb_lower_deep_add_pct": 0.10, "db_boost_pct": 0.15, "bb_std": 2.0, "bb_period": 20}),
        ("反弹加20%", {"bb_lower_add_pct": 0.20, "bb_lower_deep_add_pct": 0.25, "db_boost_pct": 0.15, "bb_std": 2.0, "bb_period": 20}),

        # 不同双底加仓
        ("双底加5%", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.05, "bb_std": 2.0, "bb_period": 20}),
        ("双底加25%", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.25, "bb_std": 2.0, "bb_period": 20}),

        # 关闭布林带或双底
        ("只双底", {"bb_lower_add_pct": 0.0, "bb_lower_deep_add_pct": 0.0, "db_boost_pct": 0.15, "bb_std": 2.0, "bb_period": 20}),
        ("只布林带", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.0, "bb_std": 2.0, "bb_period": 20}),

        # 宽松双底
        ("宽松双底", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.15, "bb_std": 2.0, "bb_period": 20, "db_max_low_diff_pct": 0.10, "db_min_depth_pct": 0.05}),
        ("严格双底", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.15, "bb_std": 2.0, "bb_period": 20, "db_max_low_diff_pct": 0.03, "db_min_depth_pct": 0.12}),

        # 大lookback
        ("DB90天", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.15, "bb_std": 2.0, "bb_period": 20, "db_lookback": 90}),
        ("DB120天", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.15, "bb_std": 2.0, "bb_period": 20, "db_lookback": 120}),

        # 组合
        ("BB10/1.5+宽松DB", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.15, "bb_std": 1.5, "bb_period": 10, "db_max_low_diff_pct": 0.10, "db_min_depth_pct": 0.05}),
        ("BB10/1.5+DB90", {"bb_lower_add_pct": 0.10, "bb_lower_deep_add_pct": 0.15, "db_boost_pct": 0.20, "bb_std": 1.5, "bb_period": 10, "db_lookback": 90}),
    ]

    print(f"{'配置':<22} {'总收益':>10} {'夏普':>8} {'卡玛':>8} {'回撤':>10} {'评分':>8} {'vs做空':>8} {'反弹加':>6} {'双底':>4} {'失败':>4}")
    print("-" * 100)

    results = []
    for name, kwargs in configs:
        strategy = DoubleBottomDipStrategy(is_btc=True, **kwargs)
        result = engine.run_scenario_backtest(
            prices, strategy, name.replace(" ", "_"),
            symbol="BTC", experiment_name=f"v37gs_{name.replace(' ', '_')}",
        )
        stats = strategy.get_stats()
        bb_count = stats.get("bb_rebound_add_days", 0)
        db_count = stats.get("double_bottom_confirmed_days", 0)
        db_fail = stats.get("double_bottom_failed_days", 0)
        vs_so = result.composite_score / so_r.composite_score - 1

        marker = " ⭐" if result.composite_score > so_r.composite_score else ""
        print(
            f"{name:<22} "
            f"{result.overall_total_return:>10.1%} "
            f"{result.overall_sharpe:>8.3f} "
            f"{result.overall_calmar:>8.3f} "
            f"{result.overall_max_drawdown:>10.1%} "
            f"{result.composite_score:>8.3f}{marker} "
            f"{vs_so:>+7.1%} "
            f"{bb_count:>6} "
            f"{db_count:>4} "
            f"{db_fail:>4}"
        )
        results.append((name, result))

    print()
    best = max(results, key=lambda x: x[1].composite_score)
    print(f"🏆 最佳: {best[0]}, 评分 {best[1].composite_score:.3f}")
    if best[1].composite_score > so_r.composite_score:
        print(f"   🎉 超越做空优化版！")
    else:
        print(f"   ⚠️ 未超越做空优化版（{so_r.composite_score:.3f}）")


if __name__ == "__main__":
    run_grid_search()
