"""验证：只优化做空，看看v2的真正短板

测试：去掉bear_short_l1，只在斜率明确为负时才做空
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from backtest.strategy import EnhancedMA200Strategy
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


def test_short_optimization():
    engine = ScenarioBacktestEngine()
    prices = load_local_data("BTC")

    print("🔬 做空优化测试")
    print("=" * 70)

    configs = [
        ("v2基线", {"bear_short_level1_pct": 0.3, "bear_short_level2_pct": 0.5}),
        ("去掉L1做空", {"bear_short_level1_pct": 0.0, "bear_short_level2_pct": 0.5}),
        ("L1减半", {"bear_short_level1_pct": 0.15, "bear_short_level2_pct": 0.5}),
        ("L1=0.2, L2=0.5", {"bear_short_level1_pct": 0.2, "bear_short_level2_pct": 0.5}),
        ("L1=0.1, L2=0.6", {"bear_short_level1_pct": 0.1, "bear_short_level2_pct": 0.6}),
        ("L1=0, L2=0.6", {"bear_short_level1_pct": 0.0, "bear_short_level2_pct": 0.6}),
        ("L1=0, L2=0.7", {"bear_short_level1_pct": 0.0, "bear_short_level2_pct": 0.7}),
    ]

    print(f"{'配置':<20} {'总收益':>10} {'夏普':>8} {'卡玛':>8} {'回撤':>10} {'评分':>8}")
    print("-" * 70)

    results = []
    for name, kwargs in configs:
        strategy = EnhancedMA200Strategy(is_btc=True, **kwargs)
        result = engine.run_scenario_backtest(
            prices, strategy, name.replace(" ", "_"),
            symbol="BTC", experiment_name=f"short_opt_{name.replace(' ', '_')}",
        )
        marker = " ⭐" if result.composite_score > 1.0 else ""
        print(
            f"{name:<20} "
            f"{result.overall_total_return:>10.1%} "
            f"{result.overall_sharpe:>8.3f} "
            f"{result.overall_calmar:>8.3f} "
            f"{result.overall_max_drawdown:>10.1%} "
            f"{result.composite_score:>8.3f}{marker}"
        )
        results.append((name, result))

    # 最佳配置
    print()
    best = max(results, key=lambda x: x[1].composite_score)
    print(f"🏆 最佳: {best[0]}, 评分 {best[1].composite_score:.3f}")
    if best[1].composite_score > 1.0:
        print(f"   🎉 超越v2基线！")

    # 再试：如果我们把做空L1的位置换成抄底呢？
    print()
    print("=" * 70)
    print("🤔 另一个思路：价格在MA200下方但斜率为正时，不做空也不抄底？还是抄底？")

    # 这个比较复杂，因为v2的逻辑是：价格在MA200下方 → 先看抄底，如果没有抄底信号再看做空
    # 也就是说，当价格在MA200下方但斜率为正时，如果没有抄底信号，就会进入bear_short_l1
    # 这时候的bear_short_l1其实是"价格在下跌趋势后反弹，但还没站上MA200"的阶段

    # 让我看看这个阶段的价格表现
    print()
    print("📊 bear_short_l1阶段的价格表现分析:")
    v2 = EnhancedMA200Strategy(is_btc=True)
    signals = v2.generate_signals(prices)
    closes = prices["close"].values

    ma = pd.Series(closes).rolling(200, min_periods=200).mean().values
    slope = np.zeros(len(closes))
    for i in range(250, len(closes)):
        if not np.isnan(ma[i]) and not np.isnan(ma[i-5]):
            slope[i] = (ma[i] / ma[i-5] - 1) * 100

    weekly_ma200 = v2._compute_weekly_ma200(prices)

    l1_days = 0
    l1_future_5d = []
    l1_future_10d = []
    l1_future_20d = []

    for i in range(250, len(closes) - 20):
        price_above = closes[i] > ma[i]
        slope_pos = slope[i] > 0
        if not price_above and slope_pos:
            # 检查是否有抄底信号
            has_dip = False
            if not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                weekly_below = (weekly_ma200[i] - closes[i]) / weekly_ma200[i] * 100
                if weekly_below > 0:
                    has_dip = True

            if not has_dip:
                # 这就是bear_short_l1的日子
                l1_days += 1
                ret_5d = (closes[i+5] - closes[i]) / closes[i]
                ret_10d = (closes[i+10] - closes[i]) / closes[i]
                ret_20d = (closes[i+20] - closes[i]) / closes[i]
                l1_future_5d.append(ret_5d)
                l1_future_10d.append(ret_10d)
                l1_future_20d.append(ret_20d)

    print(f"  bear_short_l1天数: {l1_days} 天")
    if l1_future_5d:
        print(f"  未来5天平均收益: {np.mean(l1_future_5d):.2%}")
        print(f"  未来10天平均收益: {np.mean(l1_future_10d):.2%}")
        print(f"  未来20天平均收益: {np.mean(l1_future_20d):.2%}")
        print(f"  未来5天胜率: {np.mean(np.array(l1_future_5d) > 0):.2%}")
        print(f"  未来10天胜率: {np.mean(np.array(l1_future_10d) > 0):.2%}")
        print(f"  未来20天胜率: {np.mean(np.array(l1_future_20d) > 0):.2%}")

    print()
    print("💡 结论：")
    print("  如果bear_short_l1阶段未来收益为正，说明不该做空，应该空仓甚至轻仓做多")
    print("  如果为负，说明做空还是对的，只是仓位太重")


if __name__ == "__main__":
    test_short_optimization()
