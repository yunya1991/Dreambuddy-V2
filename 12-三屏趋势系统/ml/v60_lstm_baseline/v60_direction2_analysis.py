"""方向2深度分析：为什么年化提升但夏普下降？

可能原因：
1. ML抄底增加了波动率（抄底仓位波动大）
2. ML干预时机不够精准
3. 需要更细致的参数调优

分析内容：
1. 逐年收益对比
2. ML干预的收益贡献
3. 更细致的参数搜索（包含波动率控制）
"""

import os
import sys
import json
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '12-三屏趋势系统'))

from ml.v60_lstm_baseline.v60_common import load_coin_data, compute_v4_position, backtest_position
from ml.v60_lstm_baseline.v60_direction_comparison import compute_direction2, load_proba


def yearly_returns(position, direction, prices, valid_start=365):
    """计算逐年收益"""
    closes = prices["close"].values
    daily_ret = np.zeros(len(closes))
    daily_ret[1:] = closes[1:] / closes[:-1] - 1
    strategy_ret = position * direction * daily_ret

    pos_with_dir = position * direction
    position_change = np.abs(np.diff(np.concatenate([[0], pos_with_dir])))
    cost = position_change * 0.001
    strategy_ret_net = strategy_ret - cost

    dates = prices.index[valid_start:]
    rets = pd.Series(strategy_ret_net[valid_start:], index=dates)
    yearly = rets.resample('Y').apply(lambda x: (1 + x).prod() - 1)
    return yearly


def main():
    symbol = "BTC"
    prices = load_coin_data(symbol)
    n = len(prices)

    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
    top_proba = load_proba(symbol, "lgbm")
    dip_proba = load_proba(symbol, "lstm")

    valid_start = 365

    # 方向2最优参数
    h2_pos, h2_dir, stats = compute_direction2(
        v4_pos, v4_dir, top_proba, dip_proba,
        confidence_threshold=0.7, top_threshold=0.5,
        dip_threshold=0.4, dip_max_position=0.5,
        reduction_strength=0.7,
    )

    v4_metrics = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:], prices.iloc[valid_start:])
    h2_metrics = backtest_position(h2_pos[valid_start:], h2_dir[valid_start:], prices.iloc[valid_start:])

    print(f"\n  V4基线: 年化={v4_metrics['ann_return']*100:.2f}%, 夏普={v4_metrics['sharpe']:.4f}")
    print(f"  方向2:   年化={h2_metrics['ann_return']*100:.2f}%, 夏普={h2_metrics['sharpe']:.4f}")

    # 1. 逐年收益对比
    print(f"\n{'='*80}")
    print(f"  逐年收益对比")
    print(f"{'='*80}")

    v4_yearly = yearly_returns(v4_pos, v4_dir, prices, valid_start)
    h2_yearly = yearly_returns(h2_pos, h2_dir, prices, valid_start)

    print(f"\n  {'年份':<8s} {'V4基线':>10s} {'方向2':>10s} {'差异':>10s}")
    print(f"  {'-'*40}")
    for year, v4_ret, h2_ret in zip(v4_yearly.index, v4_yearly.values, h2_yearly.values):
        print(f"  {year.year:<8d} {v4_ret*100:>9.2f}% {h2_ret*100:>9.2f}% {(h2_ret-v4_ret)*100:>+9.2f}pp")

    # 2. 分析ML干预的时段
    print(f"\n{'='*80}")
    print(f"  ML干预时段分析")
    print(f"{'='*80}")

    # 找出ML干预的日子
    intervene_mask = (v4_pos < 0.7) & (((v4_dir > 0) & (top_proba > 0.5)) | ((v4_dir == 0) & (dip_proba > 0.4)))
    dip_intervene_mask = (v4_pos < 0.7) & (v4_dir == 0) & (dip_proba > 0.4)
    reduce_intervene_mask = (v4_pos < 0.7) & (v4_dir > 0) & (top_proba > 0.5)

    print(f"  总ML干预天数: {int(intervene_mask.sum())}")
    print(f"    减仓干预: {int(reduce_intervene_mask.sum())}天")
    print(f"    抄底干预: {int(dip_intervene_mask.sum())}天")

    # 干预日的日期分布
    if dip_intervene_mask.sum() > 0:
        intervene_dates = prices.index[dip_intervene_mask]
        print(f"\n  抄底干预日期分布:")
        for year in sorted(set(intervene_dates.year)):
            cnt = int(np.sum(intervene_dates.year == year))
            print(f"    {year}: {cnt}天")

    # 3. ML抄底的效果：干预日后的收益
    print(f"\n{'='*80}")
    print(f"  ML抄底干预效果（干预后20天收益）")
    print(f"{'='*80}")

    closes = prices["close"].values
    dip_indices = np.where(dip_intervene_mask)[0]
    if len(dip_indices) > 0:
        future_rets = []
        for idx in dip_indices:
            if idx + 20 < n:
                future_ret = (closes[idx + 20] - closes[idx]) / closes[idx]
                future_rets.append(future_ret)
        future_rets = np.array(future_rets)
        print(f"  抄底干预次数: {len(future_rets)}")
        print(f"  干预后20天收益: 均值={np.mean(future_rets)*100:.2f}%, 中位数={np.median(future_rets)*100:.2f}%")
        print(f"  正收益比例: {np.mean(future_rets > 0)*100:.1f}%")

    # 4. 尝试降低抄底仓位来控制波动率
    print(f"\n{'='*80}")
    print(f"  优化：降低抄底仓位控制波动率")
    print(f"{'='*80}")

    print(f"\n  {'conf':>6} {'top_thr':>8} {'dip_thr':>8} {'dip_max':>8} {'年化':>8} {'夏普':>8} {'回撤':>8} {'波动率':>8} {'Calmar':>8}")
    print(f"  {'-'*80}")

    for conf in [0.5, 0.7]:
        for dip_thr in [0.4, 0.5, 0.6]:
            for dip_max in [0.15, 0.2, 0.3, 0.4]:
                h_pos, h_dir, _ = compute_direction2(
                    v4_pos, v4_dir, top_proba, dip_proba,
                    confidence_threshold=conf, top_threshold=0.5,
                    dip_threshold=dip_thr, dip_max_position=dip_max,
                    reduction_strength=0.7,
                )
                m = backtest_position(h_pos[valid_start:], h_dir[valid_start:],
                                      prices.iloc[valid_start:])

                # 计算波动率
                closes_arr = prices["close"].values
                daily_ret = np.zeros(n)
                daily_ret[1:] = closes_arr[1:] / closes_arr[:-1] - 1
                strat_ret = h_pos * h_dir * daily_ret
                pos_wd = h_pos * h_dir
                pos_chg = np.abs(np.diff(np.concatenate([[0], pos_wd])))
                strat_ret_net = strat_ret - pos_chg * 0.001
                vol = np.std(strat_ret_net[valid_start:][strat_ret_net[valid_start:] != 0]) * np.sqrt(365)

                print(f"  {conf:>6.1f} {0.5:>8.1f} {dip_thr:>8.1f} {dip_max:>8.2f} {m['ann_return']*100:>7.2f}% {m['sharpe']:>8.4f} {m['max_drawdown']*100:>7.2f}% {vol*100:>7.2f}% {m['calmar']:>8.4f}")

    print(f"\n  V4基线: 波动率参考")


if __name__ == "__main__":
    main()
