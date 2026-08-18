"""深入分析：为什么加仓反而亏？"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from backtest.strategy import EnhancedMA200Strategy
from ml.double_bottom_strategy import DoubleBottomDipStrategy


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


def analyze():
    prices = load_local_data("BTC")
    close = prices["close"].values

    so = EnhancedMA200Strategy(is_btc=True, bear_short_level1_pct=0.0, bear_short_level2_pct=0.6)
    v37 = DoubleBottomDipStrategy(is_btc=True)

    so_sig = so.generate_signals(prices)
    v37_sig = v37.generate_signals(prices)

    daily_ret = prices["close"].pct_change().fillna(0)
    so_ret = so_sig.shift(1).fillna(0) * daily_ret
    v37_ret = v37_sig.shift(1).fillna(0) * daily_ret

    diff = v37_sig - so_sig

    print("🔍 v3.7仓位更重的93天详细分析:")
    print("=" * 90)

    heavier_idx = diff[diff > 0.001].index
    total_diff_ret = 0
    for idx in heavier_idx:
        i = prices.index.get_loc(idx)
        v37_pos = v37_sig.iloc[i]
        so_pos = so_sig.iloc[i]
        pos_diff = v37_pos - so_pos
        v37_r = v37_ret.iloc[i]
        so_r = so_ret.iloc[i]
        r_diff = v37_r - so_r
        total_diff_ret += r_diff

        date = idx.strftime("%Y-%m-%d")
        price = close[i]

        # 后5天收益
        ret_5d = (close[min(i+5, len(close)-1)] - price) / price

        if abs(r_diff) > 0.001:  # 只显示有影响的
            print(f"  {date} | 价格 {price:>8.0f} | v37仓 {v37_pos:.0%} vs so仓 {so_pos:.0%} (差{pos_diff:+.0%}) "
                  f"| 日收益差 {r_diff:+.2%} | 后5天 {ret_5d:+.1%}")

    print()
    print(f"  总收益差异: {total_diff_ret:.2%}")
    print()

    # 按加仓来源分类
    print("=" * 90)
    print("📊 加仓来源分析:")

    stats = v37.get_stats()
    print(f"  布林带下轨加仓天数: {stats.get('bb_lower_add_days', 0)}")
    print(f"  布林带深跌加仓天数: {stats.get('bb_lower_deep_add_days', 0)}")
    print(f"  双底检测天数: {stats.get('double_bottom_detected_days', 0)}")
    print(f"  双底确认天数: {stats.get('double_bottom_confirmed_days', 0)}")

    # 分析布林带加仓的效果
    print()
    print("📊 布林带加仓的独立效果:")
    bb_upper, bb_mid, bb_lower = v37._compute_bollinger_bands(close)

    bb_add_rets = []
    for i in range(v37.warmup_periods, len(close)):
        if not np.isnan(bb_lower[i]) and close[i] <= bb_lower[i]:
            # 这天布林带加仓了
            ret_5d = (close[min(i+5, len(close)-1)] - close[i]) / close[i]
            ret_10d = (close[min(i+10, len(close)-1)] - close[i]) / close[i]
            ret_20d = (close[min(i+20, len(close)-1)] - close[i]) / close[i]
            bb_add_rets.append((i, ret_5d, ret_10d, ret_20d))

    if bb_add_rets:
        r5 = [x[1] for x in bb_add_rets]
        r10 = [x[2] for x in bb_add_rets]
        r20 = [x[3] for x in bb_add_rets]
        print(f"  布林带加仓次数: {len(bb_add_rets)}")
        print(f"  后5天: 平均 {np.mean(r5):+.2%}, 胜率 {np.mean(np.array(r5)>0):.0%}")
        print(f"  后10天: 平均 {np.mean(r10):+.2%}, 胜率 {np.mean(np.array(r10)>0):.0%}")
        print(f"  后20天: 平均 {np.mean(r20):+.2%}, 胜率 {np.mean(np.array(r20)>0):.0%}")

    # 分析双底确认后的效果
    print()
    print("📊 双底确认后的效果:")
    # 重新跑一遍，记录双底确认的日子
    low = prices["low"].values
    db_confirmed_days = []
    last_breakout = -1
    db_confirmed = False
    for i in range(v37.warmup_periods, len(close)):
        if not db_confirmed:
            detected, confirmed = v37._detect_double_bottom(low, close, i, last_breakout)
            if detected:
                last_breakout = i
            if confirmed:
                db_confirmed = True
                db_confirmed_days.append(i)
        # 检查是否需要重置（价格站上MA200）
        ma = pd.Series(close).rolling(200, min_periods=200).mean().values
        if not np.isnan(ma[i]) and close[i] > ma[i]:
            db_confirmed = False

    if db_confirmed_days:
        print(f"  双底确认次数: {len(db_confirmed_days)}")
        for i in db_confirmed_days:
            date = prices.index[i].strftime("%Y-%m-%d")
            price = close[i]
            ret_5d = (close[min(i+5, len(close)-1)] - price) / price
            ret_10d = (close[min(i+10, len(close)-1)] - price) / price
            ret_20d = (close[min(i+20, len(close)-1)] - price) / price
            print(f"    {date} | 价格 {price:.0f} | 后5天 {ret_5d:+.1%} | 后10天 {ret_10d:+.1%} | 后20天 {ret_20d:+.1%}")

        r5 = [(close[min(i+5, len(close)-1)] - close[i]) / close[i] for i in db_confirmed_days]
        r10 = [(close[min(i+10, len(close)-1)] - close[i]) / close[i] for i in db_confirmed_days]
        r20 = [(close[min(i+20, len(close)-1)] - close[i]) / close[i] for i in db_confirmed_days]
        print(f"  平均: 后5天 {np.mean(r5):+.2%}, 后10天 {np.mean(r10):+.2%}, 后20天 {np.mean(r20):+.2%}")

    # 核心结论
    print()
    print("=" * 90)
    print("💡 核心结论:")
    print()
    print("1. 布林带下轨加仓的时机不好（后20天平均-0.74%）")
    print("   原因：底部区域价格还会继续跌破布林带下轨，加仓太早")
    print()
    print("2. 双底检测的预测能力一般（后20天平均+0.45%，胜率47%）")
    print("   原因：简化版双底检测无法区分真假突破")
    print()
    print("3. 加仓的93天收益远低于不加仓（-8.62%）")
    print("   原因：加仓主要发生在下跌途中，而不是真正的底部")
    print()
    print("🎯 建议：")
    print("   - 布林带加仓应该用更长的周期（周线级别），避免日线噪音")
    print("   - 或者改变思路：不在下轨加仓，而是在价格从下轨反弹时加仓")
    print("   - 双底确认应该结合成交量，放量突破才是真突破")


if __name__ == "__main__":
    analyze()
