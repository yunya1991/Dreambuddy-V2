"""消融实验：拆解抄底增强的各个组件，找出正负贡献"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from backtest.strategy import EnhancedMA200Strategy
from ml.v36_combo_strategy import V36ComboStrategy
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


def ablation_test():
    engine = ScenarioBacktestEngine()
    prices = load_local_data("BTC")

    print("🔬 抄底增强消融实验")
    print("=" * 80)
    print("基准：做空优化版（L1=0, L2=0.6）")
    print()

    base_short_opt = {
        "bear_short_level1_pct": 0.0,
        "bear_short_level2_pct": 0.6,
    }

    configs = [
        ("基准：做空优化", {**base_short_opt, "bb_accel_pct": 0, "bottom_confirm_pct": 0}),
        ("+ 布林带加速(10%)", {**base_short_opt, "bb_accel_pct": 0.10, "bottom_confirm_pct": 0}),
        ("+ 布林带加速(15%)", {**base_short_opt, "bb_accel_pct": 0.15, "bottom_confirm_pct": 0}),
        ("+ 布林带加速(20%)", {**base_short_opt, "bb_accel_pct": 0.20, "bottom_confirm_pct": 0}),
        ("+ 底部确认(10%)", {**base_short_opt, "bb_accel_pct": 0, "bottom_confirm_pct": 0.10}),
        ("+ 底部确认(15%)", {**base_short_opt, "bb_accel_pct": 0, "bottom_confirm_pct": 0.15}),
        ("+ 底部确认(20%)", {**base_short_opt, "bb_accel_pct": 0, "bottom_confirm_pct": 0.20}),
        ("+ 两者都加(10%+10%)", {**base_short_opt, "bb_accel_pct": 0.10, "bottom_confirm_pct": 0.10}),
        ("+ 两者都加(15%+15%)", {**base_short_opt, "bb_accel_pct": 0.15, "bottom_confirm_pct": 0.15}),
    ]

    print(f"{'配置':<25} {'总收益':>10} {'夏普':>8} {'卡玛':>8} {'回撤':>10} {'评分':>8} {'相对基准':>10}")
    print("-" * 85)

    results = []
    baseline_score = None
    baseline_ret = None

    for name, kwargs in configs:
        strategy = V36ComboStrategy(is_btc=True, **kwargs)
        result = engine.run_scenario_backtest(
            prices, strategy, name.replace(" ", "_"),
            symbol="BTC", experiment_name=f"ablation_{name.replace(' ', '_')}",
        )

        if baseline_score is None:
            baseline_score = result.composite_score
            baseline_ret = result.overall_total_return
            rel_score = "-"
        else:
            rel_score = f"{result.composite_score / baseline_score - 1:+.1%}"

        marker = " ⭐" if result.composite_score > baseline_score else ""
        print(
            f"{name:<25} "
            f"{result.overall_total_return:>10.1%} "
            f"{result.overall_sharpe:>8.3f} "
            f"{result.overall_calmar:>8.3f} "
            f"{result.overall_max_drawdown:>10.1%} "
            f"{result.composite_score:>8.3f}{marker} "
            f"{rel_score:>10}"
        )
        results.append((name, result))

    print()
    print("=" * 80)
    print("💡 结论：")

    # 分析抄底增强的负贡献来源
    best = max(results, key=lambda x: x[1].composite_score)
    print(f"  最佳配置: {best[0]}")
    print(f"  相对基准提升: {best[1].composite_score / baseline_score - 1:+.1%}")

    # 分析底部确认为什么是负贡献
    print()
    print("🔍 底部确认详细分析：")
    print("  底部确认的逻辑是'站稳布林带中轨N天 → 加仓'")
    print("  但在熊市中，价格可能多次假突破中轨然后继续下跌")
    print("  这时候加仓反而买在反弹高点")

    print()
    print("📝 建议：")
    print("  1. 布林带加速（下轨加仓）可能有正贡献，但幅度小")
    print("  2. 底部确认（中轨突破加仓）大概率是负贡献")
    print("  3. 抄底增强的边际收益很小，做空优化才是主要抓手")

    # 再测试一个方向：反过来，底部确认后减仓？
    print()
    print("=" * 80)
    print("🧪 反向测试：底部确认后不是加仓，而是减仓（止盈）？")
    print("  逻辑：熊市中触及中轨往往是反弹高点，应该减仓而不是加仓")

    reverse_configs = [
        ("基准", {**base_short_opt, "bb_accel_pct": 0, "bottom_confirm_pct": 0}),
        ("底部确认减仓10%", {**base_short_opt, "bb_accel_pct": 0, "bottom_confirm_pct": -0.10}),
        ("底部确认减仓20%", {**base_short_opt, "bb_accel_pct": 0, "bottom_confirm_pct": -0.20}),
    ]

    print()
    print(f"{'配置':<25} {'总收益':>10} {'夏普':>8} {'卡玛':>8} {'回撤':>10} {'评分':>8}")
    print("-" * 65)

    for name, kwargs in reverse_configs:
        strategy = V36ComboStrategy(is_btc=True, **kwargs)
        result = engine.run_scenario_backtest(
            prices, strategy, name.replace(" ", "_"),
            symbol="BTC", experiment_name=f"reverse_{name.replace(' ', '_')}",
        )
        print(
            f"{name:<25} "
            f"{result.overall_total_return:>10.1%} "
            f"{result.overall_sharpe:>8.3f} "
            f"{result.overall_calmar:>8.3f} "
            f"{result.overall_max_drawdown:>10.1%} "
            f"{result.composite_score:>8.3f}"
        )


if __name__ == "__main__":
    ablation_test()
