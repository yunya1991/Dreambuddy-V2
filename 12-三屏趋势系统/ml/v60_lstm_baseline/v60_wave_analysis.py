"""分析波浪过滤的效果，并尝试优化

目标：在保持夏普提升的同时，提高年化
方案：放宽波浪条件，只要波浪信号是中性或看涨即可（不要求强烈看涨）
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '12-三屏趋势系统'))

from ml.v60_lstm_baseline.v60_common import load_coin_data, compute_v4_position, backtest_position
from ml.v60_lstm_baseline.v60_direction_comparison import load_proba
from ml.v60_lstm_baseline.v60_enhanced_backtest import generate_wave_signals, generate_physics_confidence


def compute_direction2_relaxed(v4_pos, v4_dir, dip_proba, wave_signals, wave_confs,
                               confidence_threshold=0.7, dip_threshold=0.5,
                               dip_max_position=0.3):
    """方向2 + 放宽的波浪条件

    原版：波浪信号必须是 ENTER_LONG_W3/W5/HOLD_LONG_W3（强烈看涨）
    放宽版：波浪信号不是强烈看跌（EXIT_LONG, ENTER_SHORT）即可
    """
    n = len(v4_pos)
    hybrid_pos = v4_pos.copy()
    hybrid_dir = v4_dir.copy()

    # 原版严格信号
    strict_signals = {"ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3"}
    # 放宽版：排除强烈看跌信号
    relaxed_signals = {"ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3", "EXIT_LONG"}

    ml_dip_total = 0
    ml_dip_strict = 0
    ml_dip_relaxed = 0

    for i in range(n):
        if v4_pos[i] < confidence_threshold and v4_dir[i] == 0 and dip_proba[i] > dip_threshold:
            ml_dip_total += 1

            # 严格版本
            if wave_signals[i] in strict_signals:
                ml_dip_strict += 1
                confidence = (dip_proba[i] - dip_threshold) / max(1 - dip_threshold, 1e-6)
                confidence = min(confidence, 1.0)
                hybrid_pos[i] = dip_max_position * confidence
                hybrid_dir[i] = 1.0

            # 放宽版本（排除看跌即可）
            elif wave_signals[i] not in relaxed_signals:
                ml_dip_relaxed += 1
                # 可以考虑降低仓位
                confidence = (dip_proba[i] - dip_threshold) / max(1 - dip_threshold, 1e-6)
                confidence = min(confidence, 1.0)
                hybrid_pos[i] = dip_max_position * 0.7 * confidence  # 降低仓位
                hybrid_dir[i] = 1.0

    return hybrid_pos, hybrid_dir, {
        'ml_dip_total': ml_dip_total,
        'ml_dip_strict': ml_dip_strict,
        'ml_dip_relaxed': ml_dip_relaxed,
    }


def calc_volatility(position, direction, prices, valid_start=365):
    closes = prices["close"].values
    n = len(closes)
    daily_ret = np.zeros(n)
    daily_ret[1:] = closes[1:] / closes[:-1] - 1
    strat_ret = position * direction * daily_ret
    pos_wd = position * direction
    pos_chg = np.abs(np.diff(np.concatenate([[0], pos_wd])))
    strat_ret_net = strat_ret - pos_chg * 0.001
    nonzero = strat_ret_net[valid_start:][strat_ret_net[valid_start:] != 0]
    return np.std(nonzero) * np.sqrt(365) if len(nonzero) > 10 else 0


def main():
    print(f"\n{'='*80}")
    print(f"  波浪过滤优化分析")
    print(f"{'='*80}")

    symbol = "BTC"
    prices = load_coin_data(symbol)
    n = len(prices)

    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
    dip_proba = load_proba(symbol, "lstm")
    top_proba = load_proba(symbol, "lgbm")

    wave_signals, wave_confs = generate_wave_signals(prices, zigzag_threshold=0.05)

    valid_start = 365

    # V4基线
    v4_metrics = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:],
                                    prices.iloc[valid_start:])

    print(f"\n  V4基线: 年化={v4_metrics['ann_return']*100:.2f}%, 夏普={v4_metrics['sharpe']:.4f}")

    # 分析波浪信号分布
    print(f"\n  波浪信号分布（全数据）:")
    unique, counts = np.unique(wave_signals, return_counts=True)
    for sig, cnt in zip(unique, counts):
        print(f"    {sig}: {cnt} ({cnt/n*100:.1f}%)")

    # 在LSTM抄底信号日（V4空仓+dip_proba>0.5）的波浪分布
    dip_mask = (v4_pos < 0.7) & (v4_dir == 0) & (dip_proba > 0.5)
    dip_wave = wave_signals[dip_mask]
    print(f"\n  LSTM抄底信号日的波浪分布（{int(dip_mask.sum())}天）:")
    if len(dip_wave) > 0:
        unique, counts = np.unique(dip_wave, return_counts=True)
        for sig, cnt in zip(unique, counts):
            print(f"    {sig}: {cnt} ({cnt/len(dip_wave)*100:.1f}%)")

    # 不同波浪条件的回测对比
    print(f"\n{'='*80}")
    print(f"  不同波浪条件的回测对比")
    print(f"{'='*80}")

    # 原版：无过滤
    h_pos = v4_pos.copy()
    h_dir = v4_dir.copy()
    ml_dip = 0
    for i in range(n):
        if v4_pos[i] < 0.7 and v4_dir[i] == 0 and dip_proba[i] > 0.5:
            confidence = (dip_proba[i] - 0.5) / 0.5
            confidence = min(confidence, 1.0)
            h_pos[i] = 0.3 * confidence
            h_dir[i] = 1.0
            ml_dip += 1
    m_no_filter = backtest_position(h_pos[valid_start:], h_dir[valid_start:],
                                     prices.iloc[valid_start:])
    vol_no_filter = calc_volatility(h_pos, h_dir, prices, valid_start)

    # 严格过滤
    strict_signals = {"ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3"}
    h_pos_strict = v4_pos.copy()
    h_dir_strict = v4_dir.copy()
    ml_dip_strict = 0
    for i in range(n):
        if v4_pos[i] < 0.7 and v4_dir[i] == 0 and dip_proba[i] > 0.5:
            if wave_signals[i] in strict_signals:
                confidence = (dip_proba[i] - 0.5) / 0.5
                confidence = min(confidence, 1.0)
                h_pos_strict[i] = 0.3 * confidence
                h_dir_strict[i] = 1.0
                ml_dip_strict += 1
    m_strict = backtest_position(h_pos_strict[valid_start:], h_dir_strict[valid_start:],
                                  prices.iloc[valid_start:])
    vol_strict = calc_volatility(h_pos_strict, h_dir_strict, prices, valid_start)

    # 放宽过滤（排除看跌即可）
    relaxed_block = {"ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3", "EXIT_LONG"}
    h_pos_relaxed = v4_pos.copy()
    h_dir_relaxed = v4_dir.copy()
    ml_dip_relaxed = 0
    for i in range(n):
        if v4_pos[i] < 0.7 and v4_dir[i] == 0 and dip_proba[i] > 0.5:
            if wave_signals[i] not in relaxed_block:
                confidence = (dip_proba[i] - 0.5) / 0.5
                confidence = min(confidence, 1.0)
                h_pos_relaxed[i] = 0.3 * confidence
                h_dir_relaxed[i] = 1.0
                ml_dip_relaxed += 1
    m_relaxed = backtest_position(h_pos_relaxed[valid_start:], h_dir_relaxed[valid_start:],
                                    prices.iloc[valid_start:])
    vol_relaxed = calc_volatility(h_pos_relaxed, h_dir_relaxed, prices, valid_start)

    print(f"\n  {'策略':<30s} {'入场天数':>8} {'年化':>8} {'夏普':>8} {'回撤':>8} {'波动':>8}")
    print(f"  {'-'*75}")
    print(f"  {'V4基线':<30s} {0:>8} {v4_metrics['ann_return']*100:>7.2f}% {v4_metrics['sharpe']:>8.4f} {v4_metrics['max_drawdown']*100:>7.2f}% {46.45:>7.2f}%")
    print(f"  {'方向2原版(无波浪过滤)':<30s} {ml_dip:>8} {m_no_filter['ann_return']*100:>7.2f}% {m_no_filter['sharpe']:>8.4f} {m_no_filter['max_drawdown']*100:>7.2f}% {vol_no_filter*100:>7.2f}%")
    print(f"  {'方向2严格波浪(强烈看涨)':<30s} {ml_dip_strict:>8} {m_strict['ann_return']*100:>7.2f}% {m_strict['sharpe']:>8.4f} {m_strict['max_drawdown']*100:>7.2f}% {vol_strict*100:>7.2f}%")
    print(f"  {'方向2放宽波浪(非看跌)':<30s} {ml_dip_relaxed:>8} {m_relaxed['ann_return']*100:>7.2f}% {m_relaxed['sharpe']:>8.4f} {m_relaxed['max_drawdown']*100:>7.2f}% {vol_relaxed*100:>7.2f}%")

    # 分析抄底效果（严格波浪的5天）
    print(f"\n{'='*80}")
    print(f"  严格波浪过滤抄底的5天详情")
    print(f"{'='*80}")

    closes = prices["close"].values
    strict_indices = np.where((v4_pos < 0.7) & (v4_dir == 0) & (dip_proba > 0.5) &
                               np.isin(wave_signals, list(strict_signals)))[0]

    print(f"\n  {'日期':<12s} {'收盘价':>10s} {'LSTM概率':>10s} {'波浪信号':<20s} {'20天后':>10s}")
    print(f"  {'-'*65}")
    for idx in strict_indices:
        if idx + 20 < n:
            future_ret = (closes[idx + 20] - closes[idx]) / closes[idx] * 100
            print(f"  {prices.index[idx].date()} {closes[idx]:>10.2f} {dip_proba[idx]:>10.3f} {wave_signals[idx]:<20s} {future_ret:>+9.2f}%")

    # 增量分析
    print(f"\n  增量分析:")
    print(f"  {'策略':<30s} {'年化增量':>10} {'夏普增量':>10}")
    print(f"  {'-'*55}")
    for name, m in [("方向2原版", m_no_filter), ("方向2严格波浪", m_strict), ("方向2放宽波浪", m_relaxed)]:
        ann_d = (m['ann_return'] - v4_metrics['ann_return']) * 100
        sharpe_d = m['sharpe'] - v4_metrics['sharpe']
        print(f"  {name:<30s} {ann_d:>+9.2f}pp {sharpe_d:>+10.4f}")

    # 结论
    print(f"\n  结论:")
    if m_strict['sharpe'] > m_no_filter['sharpe'] and m_strict['ann_return'] >= m_no_filter['ann_return'] - 0.005:
        print(f"    ✅ 严格波浪过滤有效，夏普提升且年化接近")
    elif m_relaxed['sharpe'] > m_no_filter['sharpe']:
        print(f"    ✅ 放宽波浪过滤有效，夏普提升")
    else:
        print(f"    ⚠️ 波浪过滤效果有限，建议保持原版")


if __name__ == "__main__":
    main()