"""V6.0 混合策略参数搜索（用已有概率，快速测试不同融合参数）"""

import os
import sys
import json
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '12-三屏趋势系统'))

from ml.v60_lstm_baseline.v60_common import (
    load_coin_data, compute_v4_position, backtest_position,
)
from ml.v60_lstm_baseline.v60_hybrid_backtest import compute_hybrid_position


def main():
    symbol = "BTC"
    prices = load_coin_data(symbol)
    n = len(prices)

    with open(os.path.join(BASE_DIR, f"ml/backtest_results/v60_lgbm_proba_{symbol}.json")) as f:
        top_proba = np.array(json.load(f)['proba'])
    with open(os.path.join(BASE_DIR, f"ml/backtest_results/v60_lstm_proba_{symbol}.json")) as f:
        dip_proba = np.array(json.load(f)['proba'])

    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)

    valid_start = 365

    # V4基准
    v4_metrics = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:],
                                    prices.iloc[valid_start:])

    print(f"\n  V4基线: 年化={v4_metrics['ann_return']*100:.2f}%, 夏普={v4_metrics['sharpe']:.4f}, 回撤={v4_metrics['max_drawdown']*100:.2f}%")

    # 参数搜索
    top_thresholds = [0.3, 0.4, 0.5, 0.6]
    dip_thresholds = [0.3, 0.4, 0.5, 0.6]
    dip_max_positions = [0.2, 0.3, 0.4, 0.5]
    reduction_strengths = [0.5, 0.7, 0.9, 1.0]

    print(f"\n{'='*100}")
    print(f"  参数搜索（共{len(top_thresholds)*len(dip_thresholds)*len(dip_max_positions)*len(reduction_strengths)}种组合）")
    print(f"{'='*100}")
    print(f"{'top_thr':>8} {'dip_thr':>8} {'dip_max':>8} {'reduce':>8} {'逃顶干预':>8} {'抄底干预':>8} {'年化':>8} {'夏普':>8} {'回撤':>8} {'年化增量':>10}")
    print(f"{'-'*95}")

    best_score = -999
    best_params = None
    best_metrics = None
    results_list = []

    for top_thr in top_thresholds:
        for dip_thr in dip_thresholds:
            for dip_max in dip_max_positions:
                for reduce_str in reduction_strengths:
                    # 自定义减仓强度
                    n_len = len(v4_pos)
                    hybrid_pos = v4_pos.copy()
                    hybrid_dir = v4_dir.copy()

                    top_intervene = 0
                    dip_intervene = 0
                    for i in range(n_len):
                        if v4_dir[i] > 0 and top_proba[i] > top_thr:
                            reduction_ratio = (top_proba[i] - top_thr) / max(1 - top_thr, 1e-6)
                            reduction_ratio = min(reduction_ratio, 1.0)
                            v4_p = v4_pos[i] * v4_dir[i]
                            new_p = v4_p * (1 - reduce_str * reduction_ratio)
                            hybrid_pos[i] = abs(new_p)
                            hybrid_dir[i] = np.sign(new_p) if abs(new_p) > 1e-6 else 0
                            top_intervene += 1
                        elif v4_dir[i] == 0 and dip_proba[i] > dip_thr:
                            confidence = (dip_proba[i] - dip_thr) / max(1 - dip_thr, 1e-6)
                            confidence = min(confidence, 1.0)
                            hybrid_pos[i] = dip_max * confidence
                            hybrid_dir[i] = 1.0
                            dip_intervene += 1

                    m = backtest_position(hybrid_pos[valid_start:], hybrid_dir[valid_start:],
                                          prices.iloc[valid_start:])

                    ann_delta = (m['ann_return'] - v4_metrics['ann_return']) * 100
                    sharpe_delta = m['sharpe'] - v4_metrics['sharpe']
                    mdd_delta = (m['max_drawdown'] - v4_metrics['max_drawdown']) * 100
                    # 综合评分：年化增量 + 夏普增量 + 回撤改善
                    score = ann_delta * 0.4 + sharpe_delta * 20 + (-mdd_delta) * 0.3

                    results_list.append({
                        'top_thr': top_thr, 'dip_thr': dip_thr,
                        'dip_max': dip_max, 'reduce': reduce_str,
                        'top_intervene': top_intervene, 'dip_intervene': dip_intervene,
                        'ann': m['ann_return'], 'sharpe': m['sharpe'],
                        'mdd': m['max_drawdown'], 'ann_delta': ann_delta,
                        'sharpe_delta': sharpe_delta, 'mdd_delta': mdd_delta,
                        'score': score,
                    })

                    if score > best_score:
                        best_score = score
                        best_params = (top_thr, dip_thr, dip_max, reduce_str)
                        best_metrics = m

    # 按评分排序，打印Top 15
    results_list.sort(key=lambda x: x['score'], reverse=True)
    for r in results_list[:15]:
        print(f"{r['top_thr']:>8.1f} {r['dip_thr']:>8.1f} {r['dip_max']:>8.1f} {r['reduce']:>8.1f} {r['top_intervene']:>8d} {r['dip_intervene']:>8d} {r['ann']*100:>7.2f}% {r['sharpe']:>8.4f} {r['mdd']*100:>7.2f}% {r['ann_delta']:>+9.2f}pp")

    print(f"\n  🏆 最优参数: top_thr={best_params[0]}, dip_thr={best_params[1]}, dip_max={best_params[2]}, reduce={best_params[3]}")
    print(f"     年化={best_metrics['ann_return']*100:.2f}%, 夏普={best_metrics['sharpe']:.4f}, 回撤={best_metrics['max_drawdown']*100:.2f}%")
    print(f"     年化增量={((best_metrics['ann_return']-v4_metrics['ann_return'])*100):+.2f}pp")
    print(f"     夏普增量={best_metrics['sharpe']-v4_metrics['sharpe']:+.4f}")
    print(f"     回撤改善={(best_metrics['max_drawdown']-v4_metrics['max_drawdown'])*100:+.2f}pp")


if __name__ == "__main__":
    main()
