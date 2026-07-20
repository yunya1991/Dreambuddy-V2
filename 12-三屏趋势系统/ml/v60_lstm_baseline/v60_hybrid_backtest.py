#!/usr/bin/env python3
"""V6.0 混合策略实盘回测（主脚本）

策略设计（基于Walk-Forward验证结论）：
  - TOP_EXIT场景：使用 LightGBM（V5.5基线，测试AUC 0.7372 优于LSTM 0.5908）
  - DIP_BUY场景：使用 LSTM（V6.0基线，过拟合缓解显著，衰减率20.3% vs 30.2%）

融合规则（V4定方向 + ML增强）：
  - V4多头 + LightGBM预测顶部高概率 → 渐进减仓（逃顶增强）
  - V4空仓 + LSTM预测抄底高概率 → 轻仓抄底20%（抄底增强）
  - 其他情况 → 保持V4仓位

为避免LightGBM与PyTorch的OpenMP冲突（段错误），
LightGBM和LSTM分别在独立子进程中运行，结果通过json传递。

用法:
  python v60_hybrid_backtest.py --symbol BTC
  python v60_hybrid_backtest.py --symbol BTC --skip-predict  # 跳过预测，直接用已有概率
"""

import os
import sys
import json
import time
import argparse
import subprocess
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '12-三屏趋势系统'))

from ml.v60_lstm_baseline.v60_common import (
    load_coin_data, compute_v4_position, backtest_position, print_result_row,
)


def run_predict_script(script_name, symbol):
    """在子进程中运行预测脚本"""
    script_path = os.path.join(os.path.dirname(__file__), script_name)
    print(f"\n  启动子进程: {script_name} --symbol {symbol}")
    cmd = [sys.executable, script_path, "--symbol", symbol]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [子进程错误] {script_name}")
        print(result.stderr[-2000:])
        raise RuntimeError(f"{script_name} 失败 (exit {result.returncode})")
    print(result.stdout[-1500:])


def load_proba(symbol, model_type):
    """加载预测概率"""
    path = os.path.join(BASE_DIR, f"ml/backtest_results/v60_{model_type}_proba_{symbol}.json")
    with open(path) as f:
        data = json.load(f)
    return np.array(data['proba'])


def compute_hybrid_position(v4_pos, v4_dir, top_proba, dip_proba,
                           top_threshold=0.5, dip_threshold=0.5,
                           dip_max_position=0.2):
    """计算 V4 + ML 混合仓位

    融合规则：
      1. V4多头 + LightGBM顶部概率高 → 渐进减仓（逃顶增强）
      2. V4空仓 + LSTM抄底概率高 → 轻仓抄底（上限 dip_max_position）
      3. 其他 → 保持V4仓位
    """
    n = len(v4_pos)
    hybrid_pos = v4_pos.copy()
    hybrid_dir = v4_dir.copy()

    for i in range(n):
        v4_p = v4_pos[i] * v4_dir[i]

        if v4_dir[i] > 0 and top_proba[i] > top_threshold:
            reduction_ratio = (top_proba[i] - top_threshold) / max(1 - top_threshold, 1e-6)
            reduction_ratio = min(reduction_ratio, 1.0)
            new_p = v4_p * (1 - 0.7 * reduction_ratio)
            hybrid_pos[i] = abs(new_p)
            hybrid_dir[i] = np.sign(new_p) if abs(new_p) > 1e-6 else 0

        elif v4_dir[i] == 0 and dip_proba[i] > dip_threshold:
            confidence = (dip_proba[i] - dip_threshold) / max(1 - dip_threshold, 1e-6)
            confidence = min(confidence, 1.0)
            hybrid_pos[i] = dip_max_position * confidence
            hybrid_dir[i] = 1.0

    return hybrid_pos, hybrid_dir


def run_comparison(symbol="BTC", top_threshold=0.5, dip_threshold=0.5,
                   dip_max_position=0.2, skip_predict=False):
    print(f"\n{'='*80}")
    print(f"  V6.0 混合策略实盘回测 - {symbol}")
    print(f"  TOP_EXIT: LightGBM (阈值 {top_threshold})")
    print(f"  DIP_BUY:  LSTM (阈值 {dip_threshold}, 最大仓位 {dip_max_position})")
    print(f"{'='*80}")

    prices = load_coin_data(symbol)
    n = len(prices)
    print(f"\n  数据: {n}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

    # 1. ML预测（子进程，避免OpenMP冲突）
    lgbm_proba_path = os.path.join(BASE_DIR, f"ml/backtest_results/v60_lgbm_proba_{symbol}.json")
    lstm_proba_path = os.path.join(BASE_DIR, f"ml/backtest_results/v60_lstm_proba_{symbol}.json")

    if not skip_predict or not os.path.exists(lgbm_proba_path):
        print(f"\n  [1/4] LightGBM TOP_EXIT 概率预测...")
        t0 = time.time()
        run_predict_script("v60_lgbm_predict.py", symbol)
        print(f"    总耗时: {time.time()-t0:.1f}s")

    if not skip_predict or not os.path.exists(lstm_proba_path):
        print(f"\n  [2/4] LSTM DIP_BUY 概率预测...")
        t0 = time.time()
        run_predict_script("v60_lstm_predict.py", symbol)
        print(f"    总耗时: {time.time()-t0:.1f}s")

    # 2. 加载概率
    print(f"\n  [3/4] 加载ML概率...")
    top_proba = load_proba(symbol, "lgbm")
    dip_proba = load_proba(symbol, "lstm")
    print(f"    TOP_EXIT概率: 均值={np.mean(top_proba):.3f}, 最大={np.max(top_proba):.3f}")
    print(f"    DIP_BUY概率:  均值={np.mean(dip_proba):.3f}, 最大={np.max(dip_proba):.3f}")

    # 3. V4基线仓位 + 混合仓位
    print(f"\n  [4/4] 计算仓位...")
    t0 = time.time()
    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)
    print(f"    V4仓位耗时: {time.time()-t0:.1f}s, 平均仓位: {np.mean(v4_pos):.3f}")

    hybrid_pos, hybrid_dir = compute_hybrid_position(
        v4_pos, v4_dir, top_proba, dip_proba,
        top_threshold=top_threshold, dip_threshold=dip_threshold,
        dip_max_position=dip_max_position,
    )

    top_intervene = int(np.sum((v4_dir > 0) & (top_proba > top_threshold)))
    dip_intervene = int(np.sum((v4_dir == 0) & (dip_proba > dip_threshold)))
    print(f"    逃顶干预次数: {top_intervene}天")
    print(f"    抄底干预次数: {dip_intervene}天")

    # 有效起始（跳过V4预热期）
    valid_start = 365

    # ========== 回测对比 ==========
    print(f"\n{'='*80}")
    print(f"  回测结果对比（有效天数: {n-valid_start}天, 约{(n-valid_start)/365:.1f}年）")
    print(f"{'='*80}")
    print(f"{'策略':<30s} {'年化':>8} {'总收益':>10} {'夏普':>8} {'回撤':>10} {'Calmar':>8} {'胜率':>8} {'均仓':>7}")
    print(f"{'-'*97}")

    results = {}

    metrics = backtest_position(v4_pos[valid_start:], v4_dir[valid_start:],
                                prices.iloc[valid_start:])
    results["V4基线"] = metrics
    print_result_row("V4基线", metrics)

    metrics = backtest_position(hybrid_pos[valid_start:], hybrid_dir[valid_start:],
                                prices.iloc[valid_start:])
    results["V4+ML混合(LGB+LSTM)"] = metrics
    print_result_row("V4+ML混合(LGB+LSTM)", metrics)

    bh_pos = np.ones(n); bh_dir = np.ones(n)
    metrics = backtest_position(bh_pos[valid_start:], bh_dir[valid_start:],
                               prices.iloc[valid_start:])
    results["买入持有"] = metrics
    print_result_row("买入持有", metrics)

    # ========== 增量分析 ==========
    print(f"\n{'='*80}")
    print(f"  相对V4基线的增量价值")
    print(f"{'='*80}")
    print(f"{'策略':<30s} {'年化增量':>10} {'夏普增量':>10} {'回撤改善':>10} {'综合评分':>10}")
    print(f"{'-'*75}")

    v4_base = results["V4基线"]
    v4_ann = v4_base['ann_return']
    v4_sharpe = v4_base['sharpe']
    v4_mdd = v4_base['max_drawdown']

    for name, m in results.items():
        if name == "V4基线":
            continue
        ann_delta = (m['ann_return'] - v4_ann) * 100
        sharpe_delta = m['sharpe'] - v4_sharpe
        mdd_delta = (m['max_drawdown'] - v4_mdd) * 100
        score = sharpe_delta * 0.4 + ann_delta * 0.01 * 0.3 + (-mdd_delta) * 0.01 * 0.3
        print(f"{name:<30s} {ann_delta:>+9.2f}pp {sharpe_delta:>+10.4f} {mdd_delta:>+9.2f}pp {score:>10.4f}")

    # ========== 保存结果 ==========
    out_path = os.path.join(BASE_DIR, "ml/backtest_results/v60_hybrid_backtest.json")
    save_data = {
        "symbol": symbol,
        "data_days": int(n),
        "valid_days": int(n - valid_start),
        "date_range": [str(prices.index[0].date()), str(prices.index[-1].date())],
        "strategy": {
            "top_exit_model": "LightGBM",
            "dip_buy_model": "LSTM",
            "top_threshold": top_threshold,
            "dip_threshold": dip_threshold,
            "dip_max_position": dip_max_position,
        },
        "ml_intervention": {
            "top_exit_days": top_intervene,
            "dip_buy_days": dip_intervene,
        },
        "results": results,
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}")

    return results


def main():
    parser = argparse.ArgumentParser(description="V6.0 混合策略实盘回测")
    parser.add_argument("--symbol", type=str, default="BTC")
    parser.add_argument("--top-threshold", type=float, default=0.5)
    parser.add_argument("--dip-threshold", type=float, default=0.5)
    parser.add_argument("--dip-max-position", type=float, default=0.2)
    parser.add_argument("--skip-predict", action="store_true", help="跳过预测，直接用已有概率")
    args = parser.parse_args()

    run_comparison(
        symbol=args.symbol,
        top_threshold=args.top_threshold,
        dip_threshold=args.dip_threshold,
        dip_max_position=args.dip_max_position,
        skip_predict=args.skip_predict,
    )


if __name__ == "__main__":
    main()
