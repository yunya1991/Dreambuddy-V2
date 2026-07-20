"""V6.0 混合策略方向对比测试

方向1：V4主线 + ML补充
  - V4仓位 >= 0.3：完全保持V4仓位（V4主导）
  - V4仓位 < 0.3 或空仓：ML才允许入场
    - LightGBM顶部概率高 → 不入场（规避下跌）
    - LSTM抄底概率高 → 轻仓抄底

方向2：V4置信度低时采用ML
  - V4置信度高（仓位 >= 0.5）：完全保持V4仓位
  - V4置信度低（仓位 < 0.5）：采用ML建议
    - 多头方向 + LightGBM顶部高 → 减仓
    - 空仓 + LSTM抄底高 → 入场抄底
"""

import os
import sys
import json
import time
import argparse
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '12-三屏趋势系统'))

from ml.v60_lstm_baseline.v60_common import (
    load_coin_data, compute_v4_position, backtest_position, print_result_row,
)


def load_proba(symbol, model_type):
    path = os.path.join(BASE_DIR, f"ml/backtest_results/v60_{model_type}_proba_{symbol}.json")
    with open(path) as f:
        return np.array(json.load(f)['proba'])


def compute_direction1(v4_pos, v4_dir, top_proba, dip_proba,
                       v4_threshold=0.3, dip_threshold=0.5,
                       dip_max_position=0.3, top_block_threshold=0.5):
    """方向1：V4主线 + ML补充

    V4仓位 >= v4_threshold：完全保持V4仓位
    V4仓位 < v4_threshold：ML才允许入场
      - LightGBM顶部概率 > top_block_threshold → 不入场（规避下跌）
      - LSTM抄底概率 > dip_threshold → 入场抄底（仓位 = dip_max_position * confidence）
      - 其他 → 保持V4原仓位
    """
    n = len(v4_pos)
    hybrid_pos = v4_pos.copy()
    hybrid_dir = v4_dir.copy()

    ml_intervene = 0
    ml_block = 0
    ml_dip = 0

    for i in range(n):
        if v4_pos[i] >= v4_threshold:
            # V4主导，保持原仓位
            continue

        # V4仓位低，ML允许入场
        if top_proba[i] > top_block_threshold:
            # 顶部概率高，不入场，清仓
            if v4_pos[i] > 0:
                hybrid_pos[i] = 0.0
                hybrid_dir[i] = 0.0
                ml_block += 1
                ml_intervene += 1
        elif dip_proba[i] > dip_threshold:
            # 抄底信号，入场
            confidence = (dip_proba[i] - dip_threshold) / max(1 - dip_threshold, 1e-6)
            confidence = min(confidence, 1.0)
            hybrid_pos[i] = dip_max_position * confidence
            hybrid_dir[i] = 1.0
            ml_dip += 1
            ml_intervene += 1
        # else: 保持V4原仓位（可能为0或低仓位）

    return hybrid_pos, hybrid_dir, {
        'ml_intervene': ml_intervene,
        'ml_block': ml_block,
        'ml_dip': ml_dip,
    }


def compute_direction2(v4_pos, v4_dir, top_proba, dip_proba,
                       confidence_threshold=0.5, top_threshold=0.5,
                       dip_threshold=0.5, dip_max_position=0.3,
                       reduction_strength=0.7):
    """方向2：V4置信度低时采用ML

    V4仓位 >= confidence_threshold（高置信度）：完全保持V4仓位
    V4仓位 < confidence_threshold（低置信度）：采用ML建议
      - 多头 + LightGBM顶部高 → 减仓
      - 空仓 + LSTM抄底高 → 入场抄底
      - 其他 → 保持V4原仓位
    """
    n = len(v4_pos)
    hybrid_pos = v4_pos.copy()
    hybrid_dir = v4_dir.copy()

    ml_intervene = 0
    ml_reduce = 0
    ml_dip = 0

    for i in range(n):
        if v4_pos[i] >= confidence_threshold:
            # V4高置信度，保持原仓位
            continue

        # V4低置信度，采用ML建议
        if v4_dir[i] > 0 and top_proba[i] > top_threshold:
            # 多头但顶部风险高，减仓
            reduction_ratio = (top_proba[i] - top_threshold) / max(1 - top_threshold, 1e-6)
            reduction_ratio = min(reduction_ratio, 1.0)
            v4_p = v4_pos[i] * v4_dir[i]
            new_p = v4_p * (1 - reduction_strength * reduction_ratio)
            hybrid_pos[i] = abs(new_p)
            hybrid_dir[i] = np.sign(new_p) if abs(new_p) > 1e-6 else 0
            ml_reduce += 1
            ml_intervene += 1
        elif v4_dir[i] == 0 and dip_proba[i] > dip_threshold:
            # 空仓时抄底信号，入场
            confidence = (dip_proba[i] - dip_threshold) / max(1 - dip_threshold, 1e-6)
            confidence = min(confidence, 1.0)
            hybrid_pos[i] = dip_max_position * confidence
            hybrid_dir[i] = 1.0
            ml_dip += 1
            ml_intervene += 1
        # else: 保持V4原仓位

    return hybrid_pos, hybrid_dir, {
        'ml_intervene': ml_intervene,
        'ml_reduce': ml_reduce,
        'ml_dip': ml_dip,
    }


def run_comparison(symbol="BTC"):
    print(f"\n{'='*80}")
    print(f"  V6.0 混合策略方向对比测试 - {symbol}")
    print(f"{'='*80}")

    prices = load_coin_data(symbol)
    n = len(prices)
    print(f"\n  数据: {n}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
    top_proba = load_proba(symbol, "lgbm")
    dip_proba = load_proba(symbol, "lstm")

    valid_start = 365

    # V4基准
    v4_metrics = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:],
                                    prices.iloc[valid_start:])

    print(f"\n  V4基线: 年化={v4_metrics['ann_return']*100:.2f}%, 夏普={v4_metrics['sharpe']:.4f}, 回撤={v4_metrics['max_drawdown']*100:.2f}%")

    # ========== 方向1：参数搜索 ==========
    print(f"\n{'='*80}")
    print(f"  方向1：V4主线 + ML补充（V4仓位<阈值时ML入场）")
    print(f"{'='*80}")

    dir1_results = []
    for v4_thr in [0.2, 0.3, 0.5]:
        for dip_thr in [0.4, 0.5, 0.6]:
            for dip_max in [0.2, 0.3, 0.5]:
                h_pos, h_dir, stats = compute_direction1(
                    v4_pos, v4_dir, top_proba, dip_proba,
                    v4_threshold=v4_thr, dip_threshold=dip_thr,
                    dip_max_position=dip_max, top_block_threshold=0.5,
                )
                m = backtest_position(h_pos[valid_start:], h_dir[valid_start:],
                                      prices.iloc[valid_start:])
                m.update(stats)
                m.update({'v4_thr': v4_thr, 'dip_thr': dip_thr, 'dip_max': dip_max})
                dir1_results.append(m)

    dir1_results.sort(key=lambda x: x['ann_return'], reverse=True)

    print(f"\n  Top 5 参数组合（按年化排序）:")
    print(f"  {'v4_thr':>7} {'dip_thr':>8} {'dip_max':>8} {'干预':>6} {'规避':>6} {'抄底':>6} {'年化':>8} {'夏普':>8} {'回撤':>8} {'年化增量':>10}")
    print(f"  {'-'*85}")
    for r in dir1_results[:5]:
        print(f"  {r['v4_thr']:>7.1f} {r['dip_thr']:>8.1f} {r['dip_max']:>8.1f} {r['ml_intervene']:>6d} {r['ml_block']:>6d} {r['ml_dip']:>6d} {r['ann_return']*100:>7.2f}% {r['sharpe']:>8.4f} {r['max_drawdown']*100:>7.2f}% {(r['ann_return']-v4_metrics['ann_return'])*100:>+9.2f}pp")

    # ========== 方向2：参数搜索 ==========
    print(f"\n{'='*80}")
    print(f"  方向2：V4置信度低时采用ML（V4仓位<置信度阈值时ML建议）")
    print(f"{'='*80}")

    dir2_results = []
    for conf_thr in [0.3, 0.5, 0.7]:
        for top_thr in [0.4, 0.5, 0.6]:
            for dip_thr in [0.4, 0.5, 0.6]:
                for dip_max in [0.2, 0.3, 0.5]:
                    h_pos, h_dir, stats = compute_direction2(
                        v4_pos, v4_dir, top_proba, dip_proba,
                        confidence_threshold=conf_thr, top_threshold=top_thr,
                        dip_threshold=dip_thr, dip_max_position=dip_max,
                        reduction_strength=0.7,
                    )
                    m = backtest_position(h_pos[valid_start:], h_dir[valid_start:],
                                          prices.iloc[valid_start:])
                    m.update(stats)
                    m.update({'conf_thr': conf_thr, 'top_thr': top_thr,
                              'dip_thr': dip_thr, 'dip_max': dip_max})
                    dir2_results.append(m)

    dir2_results.sort(key=lambda x: x['ann_return'], reverse=True)

    print(f"\n  Top 5 参数组合（按年化排序）:")
    print(f"  {'conf':>6} {'top_thr':>8} {'dip_thr':>8} {'dip_max':>8} {'干预':>6} {'减仓':>6} {'抄底':>6} {'年化':>8} {'夏普':>8} {'回撤':>8} {'年化增量':>10}")
    print(f"  {'-'*100}")
    for r in dir2_results[:5]:
        print(f"  {r['conf_thr']:>6.1f} {r['top_thr']:>8.1f} {r['dip_thr']:>8.1f} {r['dip_max']:>8.1f} {r['ml_intervene']:>6d} {r['ml_reduce']:>6d} {r['ml_dip']:>6d} {r['ann_return']*100:>7.2f}% {r['sharpe']:>8.4f} {r['max_drawdown']*100:>7.2f}% {(r['ann_return']-v4_metrics['ann_return'])*100:>+9.2f}pp")

    # ========== 综合对比 ==========
    print(f"\n{'='*80}")
    print(f"  综合对比（方向1最优 vs 方向2最优 vs V4基线）")
    print(f"{'='*80}")

    best_dir1 = dir1_results[0]
    best_dir2 = dir2_results[0]

    print(f"\n  {'策略':<35s} {'年化':>8} {'总收益':>10} {'夏普':>8} {'回撤':>10} {'Calmar':>8} {'胜率':>8} {'均仓':>7}")
    print(f"  {'-'*100}")

    print_result_row("V4基线", v4_metrics)

    h1_pos, h1_dir, _ = compute_direction1(
        v4_pos, v4_dir, top_proba, dip_proba,
        v4_threshold=best_dir1['v4_thr'], dip_threshold=best_dir1['dip_thr'],
        dip_max_position=best_dir1['dip_max'], top_block_threshold=0.5,
    )
    m1 = backtest_position(h1_pos[valid_start:], h1_dir[valid_start:],
                           prices.iloc[valid_start:])
    print_result_row(f"方向1最优(v4_thr={best_dir1['v4_thr']},dip_thr={best_dir1['dip_thr']},dip_max={best_dir1['dip_max']})", m1)

    h2_pos, h2_dir, _ = compute_direction2(
        v4_pos, v4_dir, top_proba, dip_proba,
        confidence_threshold=best_dir2['conf_thr'], top_threshold=best_dir2['top_thr'],
        dip_threshold=best_dir2['dip_thr'], dip_max_position=best_dir2['dip_max'],
        reduction_strength=0.7,
    )
    m2 = backtest_position(h2_pos[valid_start:], h2_dir[valid_start:],
                           prices.iloc[valid_start:])
    print_result_row(f"方向2最优(conf={best_dir2['conf_thr']},top={best_dir2['top_thr']},dip={best_dir2['dip_thr']})", m2)

    # 增量分析
    print(f"\n  增量分析:")
    print(f"  {'策略':<35s} {'年化增量':>10} {'夏普增量':>10} {'回撤改善':>10} {'综合评分':>10}")
    print(f"  {'-'*80}")
    for name, m in [("方向1最优", m1), ("方向2最优", m2)]:
        ann_d = (m['ann_return'] - v4_metrics['ann_return']) * 100
        sharpe_d = m['sharpe'] - v4_metrics['sharpe']
        mdd_d = (m['max_drawdown'] - v4_metrics['max_drawdown']) * 100
        score = ann_d * 0.4 + sharpe_d * 20 + (-mdd_d) * 0.3
        print(f"  {name:<35s} {ann_d:>+9.2f}pp {sharpe_d:>+10.4f} {mdd_d:>+9.2f}pp {score:>10.4f}")

    # 保存结果
    save_data = {
        'symbol': symbol,
        'v4_baseline': v4_metrics,
        'direction1_best': {
            'params': {'v4_thr': best_dir1['v4_thr'], 'dip_thr': best_dir1['dip_thr'],
                       'dip_max': best_dir1['dip_max']},
            'metrics': m1,
        },
        'direction2_best': {
            'params': {'conf_thr': best_dir2['conf_thr'], 'top_thr': best_dir2['top_thr'],
                       'dip_thr': best_dir2['dip_thr'], 'dip_max': best_dir2['dip_max']},
            'metrics': m2,
        },
    }
    out_path = os.path.join(BASE_DIR, "ml/backtest_results/v60_direction_comparison.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}")


if __name__ == "__main__":
    run_comparison("BTC")
