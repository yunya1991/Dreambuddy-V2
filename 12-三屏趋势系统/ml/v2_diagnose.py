"""v2策略诊断 - 找出真正的短板

分析v2在各个场景下的表现，找出最需要优化的环节。
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


def diagnose_v2():
    engine = ScenarioBacktestEngine()
    prices = load_local_data("BTC")

    print("📊 v2策略诊断报告")
    print("=" * 70)

    v2 = EnhancedMA200Strategy(is_btc=True)
    result = engine.run_scenario_backtest(prices, v2, "v2_diagnose", symbol="BTC", experiment_name="v2_diag")

    # 整体表现
    print()
    print("📈 整体表现:")
    print(f"  总收益: {result.overall_total_return:.1%}")
    print(f"  夏普比率: {result.overall_sharpe:.3f}")
    print(f"  卡玛比率: {result.overall_calmar:.3f}")
    print(f"  最大回撤: {result.overall_max_drawdown:.1%}")
    print(f"  胜率: {result.overall_win_rate:.2%}")
    print(f"  交易次数: {result.overall_trade_count}")
    print(f"  综合评分: {result.composite_score:.3f}")

    # 各场景收益贡献
    print()
    print("🎯 各场景表现:")
    print(f"  {'场景':<18} {'天数':>6} {'占比':>8} {'收益贡献':>10} {'平均日收益':>12}")
    print("  " + "-" * 60)

    # 计算各场景的收益
    signals = v2.generate_signals(prices)
    daily_returns = prices["close"].pct_change().fillna(0)
    strategy_returns = signals.shift(1).fillna(0) * daily_returns

    # 按状态分组
    closes = prices["close"].values
    pos = signals.values
    ma = pd.Series(closes).rolling(200, min_periods=200).mean().values
    slope = np.zeros(len(closes))
    for i in range(250, len(closes)):
        if not np.isnan(ma[i]) and not np.isnan(ma[i-5]):
            slope[i] = (ma[i] / ma[i-5] - 1) * 100

    weekly_ma200 = v2._compute_weekly_ma200(prices)

    states = []
    for i in range(len(closes)):
        if i < 250 or np.isnan(ma[i]):
            states.append("warmup")
            continue
        price_above = closes[i] > ma[i]
        slope_pos = slope[i] > 0
        slope_neg = slope[i] < 0

        dip_pos = 0
        if not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
            weekly_below = (weekly_ma200[i] - closes[i]) / weekly_ma200[i] * 100
            if weekly_below > 0:
                levels = min(int(weekly_below / 5.0), 4)
                if levels > 0:
                    dip_pos = levels / 4 * 0.8

        if price_above and slope_pos:
            states.append("bull")
        elif not price_above and dip_pos > 0:
            states.append("dip_buy")
        elif not price_above and slope_neg:
            states.append("bear_short_l2")
        elif not price_above:
            states.append("bear_short_l1")
        else:
            states.append("sideways")

    # 各状态统计
    state_days = {}
    state_returns = {}
    for i in range(1, len(states)):
        s = states[i]
        if s == "warmup":
            continue
        state_days[s] = state_days.get(s, 0) + 1
        state_returns[s] = state_returns.get(s, 0) + strategy_returns.iloc[i]

    total_days = sum(state_days.values())
    total_ret = sum(state_returns.values())

    for state in ["bull", "dip_buy", "bear_short_l2", "bear_short_l1", "sideways"]:
        days = state_days.get(state, 0)
        ret = state_returns.get(state, 0)
        avg_ret = ret / days if days > 0 else 0
        print(f"  {state:<18} {days:>6} {days/total_days:>7.1%} {ret:>10.2%} {avg_ret:>11.4%}")

    # 抄底详细分析
    print()
    print("🔍 抄底详细分析:")
    dip_periods = []
    in_dip = False
    dip_start = 0
    for i, s in enumerate(states):
        if s == "dip_buy" and not in_dip:
            in_dip = True
            dip_start = i
        elif s != "dip_buy" and in_dip:
            in_dip = False
            dip_periods.append((dip_start, i-1))
    if in_dip:
        dip_periods.append((dip_start, len(states)-1))

    print(f"  抄底周期数: {len(dip_periods)} 次")
    for idx, (s, e) in enumerate(dip_periods):
        dur = e - s + 1
        start_price = closes[s]
        end_price = closes[e]
        price_change = (end_price - start_price) / start_price
        pos_at_start = pos[s]
        pos_at_end = pos[e]

        # 计算这个周期的策略收益
        period_ret = 1.0
        for i in range(s, e+1):
            if i > 0:
                period_ret *= (1 + strategy_returns.iloc[i])

        # 找最低点
        period_min = np.min(closes[s:e+1])
        min_idx = s + np.argmin(closes[s:e+1])
        drawdown_from_start = (period_min - start_price) / start_price

        print(f"  周期{idx+1}: {prices.index[s].strftime('%Y-%m-%d')} ~ {prices.index[e].strftime('%Y-%m-%d')} "
              f"({dur}天)")
        print(f"    价格变化: {price_change:.1%}, 策略收益: {period_ret-1:.1%}")
        print(f"    起始仓位: {pos_at_start:.0%}, 结束仓位: {pos_at_end:.0%}")
        print(f"    期间最大跌幅: {drawdown_from_start:.1%} (最低点在第{min_idx-s}天)")

    # 做空详细分析
    print()
    print("🐻 做空详细分析:")
    bear_periods = []
    in_bear = False
    bear_start = 0
    for i, s in enumerate(states):
        if s in ("bear_short_l1", "bear_short_l2") and not in_bear:
            in_bear = True
            bear_start = i
        elif s not in ("bear_short_l1", "bear_short_l2") and in_bear:
            in_bear = False
            bear_periods.append((bear_start, i-1))
    if in_bear:
        bear_periods.append((bear_start, len(states)-1))

    print(f"  做空周期数: {len(bear_periods)} 次")
    for idx, (s, e) in enumerate(bear_periods):
        dur = e - s + 1
        start_price = closes[s]
        end_price = closes[e]
        price_change = (end_price - start_price) / start_price

        period_ret = 1.0
        for i in range(s, e+1):
            if i > 0:
                period_ret *= (1 + strategy_returns.iloc[i])

        print(f"  周期{idx+1}: {prices.index[s].strftime('%Y-%m-%d')} ~ {prices.index[e].strftime('%Y-%m-%d')} "
              f"({dur}天)")
        print(f"    价格变化: {price_change:.1%}, 策略收益: {period_ret-1:.1%}")

    # 目标维度
    print()
    print("🎯 各目标维度评分:")
    for obj, m in result.objective_metrics.items():
        print(f"  {obj}:")
        print(f"    信号数: {m.total_signals}, 频率: {m.signal_freq_pct:.2%}")
        print(f"    平均收益: {m.avg_return:.2%}, 胜率: {m.win_rate:.2%}")
        print(f"    盈亏比: {m.profit_factor:.2f}, 类夏普: {m.sharpe_like:.3f}")
        print(f"    标签F1: {m.label_f1:.3f}")

    print()
    print("=" * 70)
    print("💡 诊断结论：找出v2的主要短板")

    # 简单分析
    bull_ret = state_returns.get("bull", 0)
    bear_ret = state_returns.get("bear_short_l2", 0) + state_returns.get("bear_short_l1", 0)
    dip_ret = state_returns.get("dip_buy", 0)

    print(f"  牛市贡献: {bull_ret:.1%} (做多赚钱)")
    print(f"  熊市贡献: {bear_ret:.1%} (做空赚钱)")
    print(f"  抄底贡献: {dip_ret:.1%} (抄底赚钱)")
    print()
    if abs(bear_ret) < abs(bull_ret) * 0.3:
        print("  ⚠️  做空贡献相对较小，可能是优化方向")
    if dip_ret < 0:
        print("  ⚠️  抄底收益为负，是主要优化方向")
    elif dip_ret < bull_ret * 0.2:
        print("  💡 抄底收益较小，有提升空间")
    print()

    return result


if __name__ == "__main__":
    diagnose_v2()
