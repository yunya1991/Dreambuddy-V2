"""分析V4仓位分布，为定义'V4置信度'提供依据"""

import os
import sys
import json
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '12-三屏趋势系统'))

from ml.v60_lstm_baseline.v60_common import load_coin_data, compute_v4_position


def main():
    symbol = "BTC"
    prices = load_coin_data(symbol)
    n = len(prices)

    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
    signed_pos = v4_pos * v4_dir  # 带符号仓位

    # 加载ML概率
    with open(os.path.join(BASE_DIR, f"ml/backtest_results/v60_lgbm_proba_{symbol}.json")) as f:
        top_proba = np.array(json.load(f)['proba'])
    with open(os.path.join(BASE_DIR, f"ml/backtest_results/v60_lstm_proba_{symbol}.json")) as f:
        dip_proba = np.array(json.load(f)['proba'])

    valid_start = 365
    v4_pos_v = v4_pos[valid_start:]
    v4_dir_v = v4_dir[valid_start:]
    top_p_v = top_proba[valid_start:]
    dip_p_v = dip_proba[valid_start:]

    print(f"\n  V4仓位分布分析（有效区间 {n-valid_start}天）")
    print(f"  {'='*70}")

    # 仓位分布
    bins = [0, 0.001, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.01]
    labels = ['空仓(0)', '(0,0.1]', '(0.1,0.2]', '(0.2,0.3]',
              '(0.3,0.5]', '(0.5,0.7]', '(0.7,0.9]', '(0.9,1.0]']
    counts, _ = np.histogram(v4_pos_v, bins=bins)
    print(f"\n  {'仓位区间':<16s} {'天数':>6s} {'占比':>8s}")
    print(f"  {'-'*35}")
    for lab, c in zip(labels, counts):
        print(f"  {lab:<16s} {c:>6d} {c/len(v4_pos_v)*100:>7.1f}%")

    # 方向分布
    print(f"\n  方向分布:")
    for d, name in [(1, '多头'), (0, '空仓'), (-1, '空头')]:
        cnt = int(np.sum(v4_dir_v == d))
        print(f"    {name}: {cnt}天 ({cnt/len(v4_dir_v)*100:.1f}%)")

    # 定义V4置信度
    # 方案A：仓位直接作为置信度（仓位高=高置信度）
    # 方案B：仓位绝对值 + 方向稳定性
    # 这里用仓位绝对值作为置信度
    print(f"\n  V4置信度定义（仓位绝对值）:")
    print(f"    高置信度 (>0.5):    {int(np.sum(v4_pos_v > 0.5)):>5d}天 ({np.mean(v4_pos_v > 0.5)*100:.1f}%)")
    print(f"    中置信度 (0.3-0.5): {int(np.sum((v4_pos_v >= 0.3) & (v4_pos_v <= 0.5))):>5d}天 ({np.mean((v4_pos_v >= 0.3) & (v4_pos_v <= 0.5))*100:.1f}%)")
    print(f"    低置信度 (0-0.3):   {int(np.sum((v4_pos_v > 0) & (v4_pos_v < 0.3))):>5d}天 ({np.mean((v4_pos_v > 0) & (v4_pos_v < 0.3))*100:.1f}%)")
    print(f"    空仓 (=0):          {int(np.sum(v4_pos_v == 0)):>5d}天 ({np.mean(v4_pos_v == 0)*100:.1f}%)")

    # ML概率与V4仓位的关系
    print(f"\n  ML概率在不同V4仓位区间的均值:")
    print(f"  {'仓位区间':<16s} {'天数':>6s} {'LGB顶部概率':>12s} {'LSTM抄底概率':>12s}")
    print(f"  {'-'*50}")
    for i in range(len(bins)-1):
        mask = (v4_pos_v >= bins[i]) & (v4_pos_v < bins[i+1])
        cnt = int(mask.sum())
        if cnt > 0:
            top_mean = np.mean(top_p_v[mask])
            dip_mean = np.mean(dip_p_v[mask])
            print(f"  {labels[i]:<16s} {cnt:>6d} {top_mean:>12.3f} {dip_mean:>12.3f}")

    # 重点关注：V4空仓时LSTM抄底概率分布
    zero_mask = (v4_pos_v == 0)
    if zero_mask.sum() > 0:
        print(f"\n  V4空仓时（{int(zero_mask.sum())}天）LSTM抄底概率分布:")
        dip_at_zero = dip_p_v[zero_mask]
        for thr in [0.3, 0.4, 0.5, 0.6, 0.7]:
            cnt = int(np.sum(dip_at_zero > thr))
            print(f"    LSTM概率>{thr}: {cnt}天 ({cnt/len(dip_at_zero)*100:.1f}%)")

    # V4<0.3时的统计
    low_mask = v4_pos_v < 0.3
    print(f"\n  V4仓位<0.3时（{int(low_mask.sum())}天）:")
    print(f"    LGB顶部概率>0.5: {int(np.sum(top_p_v[low_mask] > 0.5))}天")
    print(f"    LSTM抄底概率>0.5: {int(np.sum(dip_p_v[low_mask] > 0.5))}天")


if __name__ == "__main__":
    main()
