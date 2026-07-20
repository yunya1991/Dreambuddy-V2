"""计算V4基线波动率，并做方向2的最终优化对比

发现：dip_thr=0.5 时波动率从44.6%降到46.0%（实际是升高）
      实际上 dip_thr=0.5 干预少，波动率更接近V4基线
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
from ml.v60_lstm_baseline.v60_direction_comparison import compute_direction1, compute_direction2, load_proba


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
    symbol = "BTC"
    prices = load_coin_data(symbol)
    n = len(prices)

    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
    top_proba = load_proba(symbol, "lgbm")
    dip_proba = load_proba(symbol, "lstm")

    valid_start = 365

    v4_metrics = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:], prices.iloc[valid_start:])
    v4_vol = calc_volatility(v4_pos, v4_dir, prices, valid_start)

    print(f"\n  V4基线: 年化={v4_metrics['ann_return']*100:.2f}%, 夏普={v4_metrics['sharpe']:.4f}, 波动率={v4_vol*100:.2f}%, 回撤={v4_metrics['max_drawdown']*100:.2f}%")

    # 全面参数搜索 - 按夏普和年化综合排序
    print(f"\n{'='*100}")
    print(f"  方向2全面优化（综合评分 = 年化增量*0.5 + 夏普增量*15 + 回撤改善*0.5）")
    print(f"{'='*100}")

    results = []
    for conf in [0.3, 0.5, 0.7]:
        for top_thr in [0.4, 0.5, 0.6]:
            for dip_thr in [0.4, 0.5, 0.6, 0.7]:
                for dip_max in [0.1, 0.15, 0.2, 0.3]:
                    for reduce_str in [0.5, 0.7, 0.9, 1.0]:
                        h_pos, h_dir, stats = compute_direction2(
                            v4_pos, v4_dir, top_proba, dip_proba,
                            confidence_threshold=conf, top_threshold=top_thr,
                            dip_threshold=dip_thr, dip_max_position=dip_max,
                            reduction_strength=reduce_str,
                        )
                        m = backtest_position(h_pos[valid_start:], h_dir[valid_start:],
                                              prices.iloc[valid_start:])
                        vol = calc_volatility(h_pos, h_dir, prices, valid_start)

                        ann_d = (m['ann_return'] - v4_metrics['ann_return']) * 100
                        sharpe_d = m['sharpe'] - v4_metrics['sharpe']
                        mdd_d = (m['max_drawdown'] - v4_metrics['max_drawdown']) * 100

                        # 综合评分：年化+夏普+回撤改善
                        score = ann_d * 0.5 + sharpe_d * 15 + (-mdd_d) * 0.5

                        results.append({
                            'conf': conf, 'top_thr': top_thr, 'dip_thr': dip_thr,
                            'dip_max': dip_max, 'reduce': reduce_str,
                            'ann': m['ann_return'], 'sharpe': m['sharpe'],
                            'mdd': m['max_drawdown'], 'vol': vol,
                            'calmar': m['calmar'],
                            'ann_d': ann_d, 'sharpe_d': sharpe_d, 'mdd_d': mdd_d,
                            'score': score,
                            'intervene': stats['ml_intervene'],
                        })

    # 按综合评分排序
    results.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n  Top 10 参数组合（综合评分排序）:")
    print(f"  {'conf':>5} {'top':>5} {'dip':>5} {'max':>5} {'red':>5} {'干预':>5} {'年化':>8} {'夏普':>8} {'回撤':>8} {'波动':>8} {'年化增':>8} {'夏普增':>8}")
    print(f"  {'-'*100}")
    for r in results[:10]:
        print(f"  {r['conf']:>5.1f} {r['top_thr']:>5.1f} {r['dip_thr']:>5.1f} {r['dip_max']:>5.2f} {r['reduce']:>5.1f} {r['intervene']:>5d} {r['ann']*100:>7.2f}% {r['sharpe']:>8.4f} {r['mdd']*100:>7.2f}% {r['vol']*100:>7.2f}% {r['ann_d']:>+7.2f} {r['sharpe_d']:>+8.4f}")

    # 按夏普排序（夏普优先）
    results_by_sharpe = sorted(results, key=lambda x: x['sharpe'], reverse=True)
    print(f"\n  Top 5 参数组合（夏普优先排序）:")
    print(f"  {'conf':>5} {'top':>5} {'dip':>5} {'max':>5} {'red':>5} {'年化':>8} {'夏普':>8} {'回撤':>8} {'波动':>8} {'年化增':>8} {'夏普增':>8}")
    print(f"  {'-'*100}")
    for r in results_by_sharpe[:5]:
        print(f"  {r['conf']:>5.1f} {r['top_thr']:>5.1f} {r['dip_thr']:>5.1f} {r['dip_max']:>5.2f} {r['reduce']:>5.1f} {r['ann']*100:>7.2f}% {r['sharpe']:>8.4f} {r['mdd']*100:>7.2f}% {r['vol']*100:>7.2f}% {r['ann_d']:>+7.2f} {r['sharpe_d']:>+8.4f}")

    # 方向1也做全面搜索
    print(f"\n{'='*100}")
    print(f"  方向1全面优化对比")
    print(f"{'='*100}")

    results1 = []
    for v4_thr in [0.2, 0.3, 0.5]:
        for dip_thr in [0.4, 0.5, 0.6, 0.7]:
            for dip_max in [0.1, 0.15, 0.2, 0.3]:
                h_pos, h_dir, stats = compute_direction1(
                    v4_pos, v4_dir, top_proba, dip_proba,
                    v4_threshold=v4_thr, dip_threshold=dip_thr,
                    dip_max_position=dip_max, top_block_threshold=0.5,
                )
                m = backtest_position(h_pos[valid_start:], h_dir[valid_start:],
                                      prices.iloc[valid_start:])
                vol = calc_volatility(h_pos, h_dir, prices, valid_start)

                ann_d = (m['ann_return'] - v4_metrics['ann_return']) * 100
                sharpe_d = m['sharpe'] - v4_metrics['sharpe']
                mdd_d = (m['max_drawdown'] - v4_metrics['max_drawdown']) * 100
                score = ann_d * 0.5 + sharpe_d * 15 + (-mdd_d) * 0.5

                results1.append({
                    'v4_thr': v4_thr, 'dip_thr': dip_thr, 'dip_max': dip_max,
                    'ann': m['ann_return'], 'sharpe': m['sharpe'],
                    'mdd': m['max_drawdown'], 'vol': vol, 'calmar': m['calmar'],
                    'ann_d': ann_d, 'sharpe_d': sharpe_d, 'mdd_d': mdd_d,
                    'score': score, 'intervene': stats['ml_intervene'],
                })

    results1.sort(key=lambda x: x['score'], reverse=True)
    print(f"\n  Top 5 参数组合（综合评分排序）:")
    print(f"  {'v4t':>5} {'dip':>5} {'max':>5} {'干预':>5} {'年化':>8} {'夏普':>8} {'回撤':>8} {'波动':>8} {'年化增':>8} {'夏普增':>8}")
    print(f"  {'-'*90}")
    for r in results1[:5]:
        print(f"  {r['v4_thr']:>5.1f} {r['dip_thr']:>5.1f} {r['dip_max']:>5.2f} {r['intervene']:>5d} {r['ann']*100:>7.2f}% {r['sharpe']:>8.4f} {r['mdd']*100:>7.2f}% {r['vol']*100:>7.2f}% {r['ann_d']:>+7.2f} {r['sharpe_d']:>+8.4f}")

    # 最终对比
    print(f"\n{'='*100}")
    print(f"  最终对比（方向1最优 vs 方向2最优 vs V4基线）")
    print(f"{'='*100}")

    best1 = results1[0]
    best2 = results[0]

    # 重新计算最优配置
    h1_pos, h1_dir, _ = compute_direction1(
        v4_pos, v4_dir, top_proba, dip_proba,
        v4_threshold=best1['v4_thr'], dip_threshold=best1['dip_thr'],
        dip_max_position=best1['dip_max'], top_block_threshold=0.5,
    )
    m1 = backtest_position(h1_pos[valid_start:], h1_dir[valid_start:], prices.iloc[valid_start:])

    h2_pos, h2_dir, _ = compute_direction2(
        v4_pos, v4_dir, top_proba, dip_proba,
        confidence_threshold=best2['conf'], top_threshold=best2['top_thr'],
        dip_threshold=best2['dip_thr'], dip_max_position=best2['dip_max'],
        reduction_strength=best2['reduce'],
    )
    m2 = backtest_position(h2_pos[valid_start:], h2_dir[valid_start:], prices.iloc[valid_start:])

    print(f"\n  {'策略':<45s} {'年化':>8} {'夏普':>8} {'回撤':>8} {'波动':>8} {'Calmar':>8}")
    print(f"  {'-'*85}")
    print(f"  {'V4基线':<45s} {v4_metrics['ann_return']*100:>7.2f}% {v4_metrics['sharpe']:>8.4f} {v4_metrics['max_drawdown']*100:>7.2f}% {v4_vol*100:>7.2f}% {v4_metrics['calmar']:>8.4f}")
    dir1_label = f"方向1: v4_thr={best1['v4_thr']},dip_thr={best1['dip_thr']},dip_max={best1['dip_max']}"
    dir2_label = f"方向2: conf={best2['conf']},top={best2['top_thr']},dip={best2['dip_thr']},max={best2['dip_max']},red={best2['reduce']}"
    vol1 = calc_volatility(h1_pos, h1_dir, prices) * 100
    vol2 = calc_volatility(h2_pos, h2_dir, prices) * 100
    print(f"  {dir1_label:<45s} {m1['ann_return']*100:>7.2f}% {m1['sharpe']:>8.4f} {m1['max_drawdown']*100:>7.2f}% {vol1:>7.2f}% {m1['calmar']:>8.4f}")
    print(f"  {dir2_label:<45s} {m2['ann_return']*100:>7.2f}% {m2['sharpe']:>8.4f} {m2['max_drawdown']*100:>7.2f}% {vol2:>7.2f}% {m2['calmar']:>8.4f}")

    # 保存
    save_data = {
        'symbol': symbol,
        'v4_baseline': {**v4_metrics, 'volatility': float(v4_vol)},
        'direction1_best': {
            'params': {'v4_thr': best1['v4_thr'], 'dip_thr': best1['dip_thr'], 'dip_max': best1['dip_max']},
            'metrics': {**m1, 'volatility': float(calc_volatility(h1_pos, h1_dir, prices))},
        },
        'direction2_best': {
            'params': {'conf_thr': best2['conf'], 'top_thr': best2['top_thr'],
                       'dip_thr': best2['dip_thr'], 'dip_max': best2['dip_max'],
                       'reduce': best2['reduce']},
            'metrics': {**m2, 'volatility': float(calc_volatility(h2_pos, h2_dir, prices))},
        },
    }
    out_path = os.path.join(BASE_DIR, "ml/backtest_results/v60_direction_final.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}")


if __name__ == "__main__":
    main()
