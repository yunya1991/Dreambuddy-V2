"""诊断双底检测的触发时机和效果"""

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


def diagnose():
    prices = load_local_data("BTC")
    close = prices["close"].values
    low = prices["low"].values

    v37 = DoubleBottomDipStrategy(is_btc=True)

    # 逐日检测双底
    print("🔍 双底检测触发记录:")
    print("=" * 80)

    detected_days = []
    confirmed_days = []
    last_breakout = -1

    for i in range(v37.warmup_periods, len(close)):
        detected, confirmed = v37._detect_double_bottom(low, close, i, last_breakout)
        if detected:
            detected_days.append(i)
            last_breakout = i
            date = prices.index[i].strftime("%Y-%m-%d")
            price = close[i]
            # 看看后续5/10/20天收益
            ret_5d = (close[min(i+5, len(close)-1)] - price) / price
            ret_10d = (close[min(i+10, len(close)-1)] - price) / price
            ret_20d = (close[min(i+20, len(close)-1)] - price) / price
            print(f"  检测: {date} | 价格 {price:.0f} | 后5天 {ret_5d:+.1%} | 后10天 {ret_10d:+.1%} | 后20天 {ret_20d:+.1%}")
        if confirmed:
            confirmed_days.append(i)

    print()
    print(f"总检测天数: {len(detected_days)}")
    print(f"总确认天数: {len(confirmed_days)}")

    if detected_days:
        print()
        print("📊 检测后收益统计:")
        rets_5d = []
        rets_10d = []
        rets_20d = []
        for i in detected_days:
            rets_5d.append((close[min(i+5, len(close)-1)] - close[i]) / close[i])
            rets_10d.append((close[min(i+10, len(close)-1)] - close[i]) / close[i])
            rets_20d.append((close[min(i+20, len(close)-1)] - close[i]) / close[i])
        print(f"  后5天平均: {np.mean(rets_5d):+.2%}, 胜率: {np.mean(np.array(rets_5d) > 0):.0%}")
        print(f"  后10天平均: {np.mean(rets_10d):+.2%}, 胜率: {np.mean(np.array(rets_10d) > 0):.0%}")
        print(f"  后20天平均: {np.mean(rets_20d):+.2%}, 胜率: {np.mean(np.array(rets_20d) > 0):.0%}")

    # 看看布林带加仓的触发情况
    print()
    print("=" * 80)
    print("🔍 布林带下轨加仓触发记录:")

    bb_upper, bb_mid, bb_lower = v37._compute_bollinger_bands(close)
    bb_add_days = []
    for i in range(v37.warmup_periods, len(close)):
        if not np.isnan(bb_lower[i]) and close[i] <= bb_lower[i]:
            bb_add_days.append(i)

    print(f"  触及下轨天数: {len(bb_add_days)}")
    if bb_add_days:
        rets_5d = []
        rets_10d = []
        rets_20d = []
        for i in bb_add_days:
            rets_5d.append((close[min(i+5, len(close)-1)] - close[i]) / close[i])
            rets_10d.append((close[min(i+10, len(close)-1)] - close[i]) / close[i])
            rets_20d.append((close[min(i+20, len(close)-1)] - close[i]) / close[i])
        print(f"  后5天平均: {np.mean(rets_5d):+.2%}, 胜率: {np.mean(np.array(rets_5d) > 0):.0%}")
        print(f"  后10天平均: {np.mean(rets_10d):+.2%}, 胜率: {np.mean(np.array(rets_10d) > 0):.0%}")
        print(f"  后20天平均: {np.mean(rets_20d):+.2%}, 胜率: {np.mean(np.array(rets_20d) > 0):.0%}")

    # 分析为什么加仓后反而亏
    print()
    print("=" * 80)
    print("🔍 为什么抄底加仓反而拉低收益？")

    # 对比：做空优化版 vs v3.7在抄底区域的表现差异
    so = EnhancedMA200Strategy(is_btc=True, bear_short_level1_pct=0.0, bear_short_level2_pct=0.6)
    v37_strat = DoubleBottomDipStrategy(is_btc=True)

    so_sig = so.generate_signals(prices)
    v37_sig = v37_strat.generate_signals(prices)

    daily_ret = prices["close"].pct_change().fillna(0)
    so_ret = so_sig.shift(1).fillna(0) * daily_ret
    v37_ret = v37_sig.shift(1).fillna(0) * daily_ret

    # 找抄底区域
    ma = pd.Series(close).rolling(200, min_periods=200).mean().values
    weekly_ma200 = v37_strat._compute_weekly_ma200(prices)

    dip_so_ret = 0
    dip_v37_ret = 0
    dip_days = 0
    for i in range(v37.warmup_periods, len(close)):
        if np.isnan(ma[i]) or np.isnan(weekly_ma200[i]):
            continue
        price_above = close[i] > ma[i]
        if not price_above and weekly_ma200[i] > 0:
            weekly_below = (weekly_ma200[i] - close[i]) / weekly_ma200[i] * 100
            if weekly_below > 0:
                dip_days += 1
                dip_so_ret += so_ret.iloc[i]
                dip_v37_ret += v37_ret.iloc[i]

    print(f"  抄底区域天数: {dip_days}")
    print(f"  做空优化版抄底收益: {dip_so_ret:.2%}")
    print(f"  v3.7抄底收益: {dip_v37_ret:.2%}")
    print(f"  差异: {dip_v37_ret - dip_so_ret:+.2%}")

    # 看看v3.7比做空优化版多加仓的那些天
    print()
    print("  v3.7相对做空优化版仓位更重的天数:")
    diff = v37_sig - so_sig
    heavier = diff[diff > 0.001]
    lighter = diff[diff < -0.001]
    print(f"    更重天数: {len(heavier)}")
    print(f"    更轻天数: {len(lighter)}")

    if len(heavier) > 0:
        heavier_idx = diff[diff > 0.001].index
        heavier_ret = v37_ret.loc[heavier_idx].sum()
        so_heavier_ret = so_ret.loc[heavier_idx].sum()
        print(f"    这些天v3.7收益: {heavier_ret:.2%}")
        print(f"    这些天做空优化版收益: {so_heavier_ret:.2%}")
        print(f"    差异: {heavier_ret - so_heavier_ret:+.2%}")


if __name__ == "__main__":
    diagnose()
