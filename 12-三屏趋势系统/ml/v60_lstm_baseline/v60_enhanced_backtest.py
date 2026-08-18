#!/usr/bin/env python3
"""V6.0 方向2 + 波浪 + 物理增强版

配置（夏普最优）：
  - confidence_threshold = 0.7（V4仓位<0.7时ML介入）
  - top_threshold = 0.5, dip_threshold = 0.5
  - dip_max_position = 0.3
  - reduction_strength = 1.0

增强规则（在V4空仓期抄底时）：
  Layer 1: LSTM概率 > 0.5（基础条件）
  Layer 2: 波浪信号支持抄底（ENTER_LONG_W3/W5/HOLD_LONG_W3）
  Layer 3: 物理置信度高（eta < 0.1 或 phys_conf > 0.6）

满足全部三层 → 抄底入场
否则 → 保持V4原仓位（空仓）

对比：
  1. V4基线
  2. 方向2原版
  3. 方向2+波浪+物理增强版

如果增强版表现差 → 回退到原版
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
    load_coin_data, compute_v4_position, backtest_position,
)
from ml.v60_lstm_baseline.v60_direction_comparison import load_proba


def generate_wave_signals(prices, zigzag_threshold=0.05):
    """生成波浪信号（滚动识别）"""
    from ml.ewave_recognizer import ElliottWaveRecognizer

    recognizer = ElliottWaveRecognizer(zigzag_threshold=zigzag_threshold)
    n = len(prices)
    signals = []
    confs = []

    min_window = 90
    print(f"  [Wave] 波浪识别开始...")
    t0 = time.time()

    for i in range(n):
        if i < min_window:
            signals.append("WAIT")
            confs.append(0.0)
            continue

        if i % 500 == 0:
            print(f"    波浪识别进度 {i}/{n} ({i/n*100:.1f}%)")

        slice_df = prices.iloc[: i + 1]
        try:
            ws = recognizer.identify_waves(slice_df)
            signals.append(ws.signal)
            confs.append(ws.confidence)
        except Exception:
            signals.append("WAIT")
            confs.append(0.0)

    print(f"  波浪识别完成, 耗时: {time.time()-t0:.1f}s")
    return np.array(signals), np.array(confs)


def generate_physics_confidence(prices):
    """生成物理置信度"""
    from ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights
    from ml.pitd_kinematics_engineer import KinematicsEngineer
    from ml.pitd_dynamics_engineer import DynamicsEngineer

    print(f"  [Physics] 物理置信度计算开始...")
    t0 = time.time()

    weights = ConfidenceWeights(
        w_eta=0.211, w_reversal=0.368,
        w_support=0.211, w_kinetic=0.211,
        position_lower=0.6, position_scale=1.0,
    )
    scorer = PhysicsConfidenceScorer(weights)

    kin_fe = KinematicsEngineer()
    dyn_fe = DynamicsEngineer()
    kin_feats = kin_fe.extract_series(prices)
    dyn_feats = dyn_fe.extract_series(prices, kin_feats)
    eta_series = dyn_feats["dyn_coupling_eta"].values

    n = len(prices)
    ml_pred_neutral = np.full(n, 0.5)
    phys_conf, _ = scorer.score_signals(prices=prices, ml_predictions=ml_pred_neutral)

    print(f"  物理置信度计算完成, 耗时: {time.time()-t0:.1f}s")
    return eta_series, phys_conf


def compute_direction2_enhanced(v4_pos, v4_dir, top_proba, dip_proba,
                                wave_signals, wave_confs, eta_series, phys_conf,
                                confidence_threshold=0.7, top_threshold=0.5,
                                dip_threshold=0.5, dip_max_position=0.3,
                                reduction_strength=1.0,
                                use_wave=True, use_physics=True):
    """方向2 + 波浪 + 物理增强版

    在V4空仓期抄底时，增加波浪和物理过滤：
    - use_wave=True: 要求波浪信号支持抄底
    - use_physics=True: 要求物理置信度高（eta低或phys_conf高）
    """
    n = len(v4_pos)
    hybrid_pos = v4_pos.copy()
    hybrid_dir = v4_dir.copy()

    # 抄底信号定义
    dip_signals = {"ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3"}

    ml_reduce = 0
    ml_dip_total = 0
    ml_dip_wave_pass = 0
    ml_dip_physics_pass = 0
    ml_dip_final = 0

    for i in range(n):
        if v4_pos[i] >= confidence_threshold:
            # V4高置信度，保持原仓位
            continue

        # V4低置信度，ML介入
        if v4_dir[i] > 0 and top_proba[i] > top_threshold:
            # 多头但顶部风险高，减仓
            reduction_ratio = (top_proba[i] - top_threshold) / max(1 - top_threshold, 1e-6)
            reduction_ratio = min(reduction_ratio, 1.0)
            v4_p = v4_pos[i] * v4_dir[i]
            new_p = v4_p * (1 - reduction_strength * reduction_ratio)
            hybrid_pos[i] = abs(new_p)
            hybrid_dir[i] = np.sign(new_p) if abs(new_p) > 1e-6 else 0
            ml_reduce += 1

        elif v4_dir[i] == 0 and dip_proba[i] > dip_threshold:
            # V4空仓 + LSTM抄底信号
            ml_dip_total += 1

            # Layer 2: 波浪过滤
            wave_ok = True
            if use_wave:
                wave_ok = wave_signals[i] in dip_signals
                if wave_ok:
                    ml_dip_wave_pass += 1

            # Layer 3: 物理过滤
            physics_ok = True
            if use_physics:
                eta_low = eta_series[i] < 0.10 if not np.isnan(eta_series[i]) else False
                phys_high = phys_conf[i] > 0.6
                physics_ok = eta_low or phys_high
                if physics_ok:
                    ml_dip_physics_pass += 1

            # 全部通过才入场
            if wave_ok and physics_ok:
                confidence = (dip_proba[i] - dip_threshold) / max(1 - dip_threshold, 1e-6)
                confidence = min(confidence, 1.0)
                hybrid_pos[i] = dip_max_position * confidence
                hybrid_dir[i] = 1.0
                ml_dip_final += 1
            # else: 保持空仓

    return hybrid_pos, hybrid_dir, {
        'ml_reduce': ml_reduce,
        'ml_dip_total': ml_dip_total,
        'ml_dip_wave_pass': ml_dip_wave_pass,
        'ml_dip_physics_pass': ml_dip_physics_pass,
        'ml_dip_final': ml_dip_final,
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


def run_comparison(symbol="BTC", use_wave=True, use_physics=True):
    print(f"\n{'='*80}")
    print(f"  V6.0 方向2 + 波浪 + 物理增强版 - {symbol}")
    print(f"  use_wave={use_wave}, use_physics={use_physics}")
    print(f"{'='*80}")

    prices = load_coin_data(symbol)
    n = len(prices)
    print(f"\n  数据: {n}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

    # 1. V4仓位
    print(f"\n  [1/4] 计算V4仓位...")
    t0 = time.time()
    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
    print(f"    耗时: {time.time()-t0:.1f}s")

    # 2. ML概率
    print(f"\n  [2/4] 加载ML概率...")
    top_proba = load_proba(symbol, "lgbm")
    dip_proba = load_proba(symbol, "lstm")

    # 3. 波浪信号
    wave_signals, wave_confs = None, None
    if use_wave:
        print(f"\n  [3/4] 生成波浪信号...")
        wave_signals, wave_confs = generate_wave_signals(prices, zigzag_threshold=0.05)
    else:
        print(f"\n  [3/4] 跳过波浪信号（use_wave=False）")

    # 4. 物理置信度
    eta_series, phys_conf = None, None
    if use_physics:
        print(f"\n  [4/4] 计算物理置信度...")
        eta_series, phys_conf = generate_physics_confidence(prices)
    else:
        print(f"\n  [4/4] 跳过物理置信度（use_physics=False）")

    valid_start = 365

    # ========== 回测对比 ==========
    print(f"\n{'='*80}")
    print(f"  回测结果对比")
    print(f"{'='*80}")

    # V4基线
    v4_metrics = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:],
                                    prices.iloc[valid_start:])
    v4_vol = calc_volatility(v4_pos, v4_dir, prices, valid_start)

    # 方向2原版（只用ML）
    h2_pos = v4_pos.copy()
    h2_dir = v4_dir.copy()
    ml_reduce = 0
    ml_dip = 0
    for i in range(n):
        if v4_pos[i] < 0.7:
            if v4_dir[i] > 0 and top_proba[i] > 0.5:
                reduction_ratio = (top_proba[i] - 0.5) / 0.5
                reduction_ratio = min(reduction_ratio, 1.0)
                v4_p = v4_pos[i] * v4_dir[i]
                new_p = v4_p * (1 - 1.0 * reduction_ratio)
                h2_pos[i] = abs(new_p)
                h2_dir[i] = np.sign(new_p) if abs(new_p) > 1e-6 else 0
                ml_reduce += 1
            elif v4_dir[i] == 0 and dip_proba[i] > 0.5:
                confidence = (dip_proba[i] - 0.5) / 0.5
                confidence = min(confidence, 1.0)
                h2_pos[i] = 0.3 * confidence
                h2_dir[i] = 1.0
                ml_dip += 1

    h2_metrics = backtest_position(h2_pos[valid_start:], h2_dir[valid_start:],
                                    prices.iloc[valid_start:])
    h2_vol = calc_volatility(h2_pos, h2_dir, prices, valid_start)

    # 方向2增强版
    h_enhanced_pos, h_enhanced_dir, stats = compute_direction2_enhanced(
        v4_pos, v4_dir, top_proba, dip_proba,
        wave_signals if use_wave else np.full(n, "ENTER_LONG_W3"),
        wave_confs if use_wave else np.ones(n),
        eta_series if use_physics else np.zeros(n),
        phys_conf if use_physics else np.ones(n),
        confidence_threshold=0.7, top_threshold=0.5,
        dip_threshold=0.5, dip_max_position=0.3,
        reduction_strength=1.0,
        use_wave=use_wave, use_physics=use_physics,
    )

    h_enhanced_metrics = backtest_position(h_enhanced_pos[valid_start:], h_enhanced_dir[valid_start:],
                                            prices.iloc[valid_start:])
    h_enhanced_vol = calc_volatility(h_enhanced_pos, h_enhanced_dir, prices, valid_start)

    # 打印结果
    print(f"\n  {'策略':<35s} {'年化':>8} {'夏普':>8} {'回撤':>8} {'波动':>8} {'Calmar':>8}")
    print(f"  {'-'*75}")
    print(f"  {'V4基线':<35s} {v4_metrics['ann_return']*100:>7.2f}% {v4_metrics['sharpe']:>8.4f} {v4_metrics['max_drawdown']*100:>7.2f}% {v4_vol*100:>7.2f}% {v4_metrics['calmar']:>8.4f}")
    print(f"  {'方向2原版(ML)':<35s} {h2_metrics['ann_return']*100:>7.2f}% {h2_metrics['sharpe']:>8.4f} {h2_metrics['max_drawdown']*100:>7.2f}% {h2_vol*100:>7.2f}% {h2_metrics['calmar']:>8.4f}")
    print(f"  {'方向2增强(ML+Wave+Physics)':<35s} {h_enhanced_metrics['ann_return']*100:>7.2f}% {h_enhanced_metrics['sharpe']:>8.4f} {h_enhanced_metrics['max_drawdown']*100:>7.2f}% {h_enhanced_vol*100:>7.2f}% {h_enhanced_metrics['calmar']:>8.4f}")

    # 增量分析
    print(f"\n  增量分析:")
    print(f"  {'策略':<35s} {'年化增量':>10} {'夏普增量':>10} {'回撤改善':>10}")
    print(f"  {'-'*70}")
    for name, m, vol in [("方向2原版", h2_metrics, h2_vol), ("方向2增强", h_enhanced_metrics, h_enhanced_vol)]:
        ann_d = (m['ann_return'] - v4_metrics['ann_return']) * 100
        sharpe_d = m['sharpe'] - v4_metrics['sharpe']
        mdd_d = (m['max_drawdown'] - v4_metrics['max_drawdown']) * 100
        print(f"  {name:<35s} {ann_d:>+9.2f}pp {sharpe_d:>+10.4f} {mdd_d:>+9.2f}pp")

    # 过滤效果统计
    print(f"\n  过滤效果统计:")
    print(f"    LSTM抄底信号: {stats['ml_dip_total']}天")
    if use_wave:
        print(f"    波浪过滤通过: {stats['ml_dip_wave_pass']}天 ({stats['ml_dip_wave_pass']/max(stats['ml_dip_total'],1)*100:.1f}%)")
    if use_physics:
        print(f"    物理过滤通过: {stats['ml_dip_physics_pass']}天 ({stats['ml_dip_physics_pass']/max(stats['ml_dip_total'],1)*100:.1f}%)")
    print(f"    最终入场: {stats['ml_dip_final']}天 ({stats['ml_dip_final']/max(stats['ml_dip_total'],1)*100:.1f}%)")

    # 决策：增强版是否值得采用
    print(f"\n  决策:")
    if h_enhanced_metrics['sharpe'] > h2_metrics['sharpe']:
        print(f"    ✅ 增强版夏普优于原版 ({h_enhanced_metrics['sharpe']:.4f} > {h2_metrics['sharpe']:.4f})，采用增强版")
        final_decision = "enhanced"
    elif h_enhanced_metrics['ann_return'] > h2_metrics['ann_return'] and h_enhanced_metrics['sharpe'] >= h2_metrics['sharpe'] - 0.01:
        print(f"    ✅ 增强版年化优于原版且夏普接近，采用增强版")
        final_decision = "enhanced"
    else:
        print(f"    ⚠️ 增强版效果不如原版，回退到原版")
        final_decision = "original"

    # 保存结果
    save_data = {
        'symbol': symbol,
        'config': {
            'use_wave': use_wave,
            'use_physics': use_physics,
            'confidence_threshold': 0.7,
            'top_threshold': 0.5,
            'dip_threshold': 0.5,
            'dip_max_position': 0.3,
            'reduction_strength': 1.0,
        },
        'v4_baseline': {**v4_metrics, 'volatility': float(v4_vol)},
        'direction2_original': {**h2_metrics, 'volatility': float(h2_vol)},
        'direction2_enhanced': {**h_enhanced_metrics, 'volatility': float(h_enhanced_vol)},
        'filter_stats': stats,
        'final_decision': final_decision,
    }
    out_path = os.path.join(BASE_DIR, "ml/backtest_results/v60_enhanced_backtest.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}")

    return final_decision


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="BTC")
    parser.add_argument("--no-wave", action="store_true", help="禁用波浪过滤")
    parser.add_argument("--no-physics", action="store_true", help="禁用物理过滤")
    args = parser.parse_args()

    run_comparison(
        symbol=args.symbol,
        use_wave=not args.no_wave,
        use_physics=not args.no_physics,
    )


if __name__ == "__main__":
    main()