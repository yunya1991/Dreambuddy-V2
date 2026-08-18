#!/usr/bin/env python3
"""验证优化参数的样本外稳健性（防止过拟合）

将9年数据分为样本内（前2/3）和样本外（后1/3），验证优化参数在样本外的表现。
"""
import os
import sys
import json
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ml.bayesian_optimize_v4_wave import (
    load_data, compute_v4_position, generate_wave_signals,
    compute_v4_wave_mutex_fusion, backtest_position,
)


def split_backtest(prices, v4_pos, v4_dir, fusion_pos, fusion_dir, split_ratio=0.66):
    """样本内外分割回测"""
    n = len(prices)
    split_idx = int(n * split_ratio)

    in_sample_end = split_idx
    out_sample_start = 730 if 730 < in_sample_end else 0
    out_sample_start_oos = in_sample_end

    def slice_bt(pos, dir_, start, end):
        if end <= start:
            return None
        p = pos[start:end]
        d = dir_[start:end]
        if len(p) == 0 or np.all(p == 0):
            return {"ann_return": 0, "sharpe": 0, "max_drawdown": 0, "calmar": 0, "avg_position": 0}
        closes_slice = prices["close"].iloc[start:end]
        eff_len = end - start
        daily_ret = np.zeros(eff_len)
        daily_ret[1:] = closes_slice.values[1:] / closes_slice.values[:-1] - 1
        strategy_ret = p * d * daily_ret
        pos_with_dir = p * d
        position_change = np.abs(np.diff(np.concatenate([[0], pos_with_dir])))
        cost = position_change * 0.001
        strategy_ret_net = strategy_ret - cost

        years = eff_len / 365
        cum_ret_arr = np.cumprod(1 + strategy_ret_net) - 1
        total_return = cum_ret_arr[-1]
        ann_ret = (1 + total_return) ** (1 / years) - 1 if years > 0 and total_return > -1 else -1.0

        daily_nonzero = strategy_ret_net[strategy_ret_net != 0]
        if len(daily_nonzero) > 10:
            sharpe = np.mean(daily_nonzero) / (np.std(daily_nonzero) + 1e-10) * np.sqrt(365)
        else:
            sharpe = 0.0

        cum_value = np.cumprod(1 + strategy_ret_net)
        running_max = np.maximum.accumulate(cum_value)
        drawdown = (cum_value - running_max) / running_max
        max_dd = np.min(drawdown) if len(drawdown) > 0 else 0.0
        calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0
        return {
            "ann_return": float(ann_ret),
            "sharpe": float(sharpe),
            "max_drawdown": float(max_dd),
            "calmar": float(calmar),
            "avg_position": float(np.mean(p)),
        }

    return {
        "in_sample": slice_bt(fusion_pos, fusion_dir, out_sample_start, in_sample_end),
        "out_sample": slice_bt(fusion_pos, fusion_dir, in_sample_end, n),
    }


def verify_params(symbol, default_params, optimized_params):
    """验证默认 vs 优化参数的样本内外表现"""
    print(f"\n{'='*80}")
    print(f"  样本内外验证 - {symbol}")
    print(f"{'='*80}")

    prices = load_data(symbol)
    v4_pos, v4_dir = compute_v4_position(prices, symbol=symbol)

    zigzag = optimized_params["zigzag_threshold"]
    wave_signals, wave_confs = generate_wave_signals(prices, zigzag_threshold=zigzag)

    default_pos, default_dir = compute_v4_wave_mutex_fusion(
        v4_pos, v4_dir, wave_signals, wave_confs,
        wave_weight=default_params["wave_weight"],
        confirm_threshold=default_params["confirm_threshold"],
        bottom_position_cap=default_params["bottom_position_cap"],
    )
    opt_pos, opt_dir = compute_v4_wave_mutex_fusion(
        v4_pos, v4_dir, wave_signals, wave_confs,
        wave_weight=optimized_params["wave_weight"],
        confirm_threshold=optimized_params["confirm_threshold"],
        bottom_position_cap=optimized_params["bottom_position_cap"],
    )

    default_split = split_backtest(prices, v4_pos, v4_dir, default_pos, default_dir)
    opt_split = split_backtest(prices, v4_pos, v4_dir, opt_pos, opt_dir)

    print(f"\n{'指标':<10} {'默认(样本内)':>14} {'默认(样本外)':>14} {'优化(样本内)':>14} {'优化(样本外)':>14} {'外样本差异':>12}")
    print("-" * 80)
    for key, label in [("ann_return", "年化"), ("sharpe", "夏普"), ("max_drawdown", "回撤"), ("calmar", "Calmar")]:
        def_v = default_split["in_sample"][key]
        def_o = default_split["out_sample"][key]
        opt_v = opt_split["in_sample"][key]
        opt_o = opt_split["out_sample"][key]
        diff = opt_o - def_o
        if key == "max_drawdown":
            print(f"{label:<10} {def_v*100:>13.2f}% {def_o*100:>13.2f}% {opt_v*100:>13.2f}% {opt_o*100:>13.2f}% {diff*100:>+11.2f}%")
        else:
            print(f"{label:<10} {def_v:>14.4f} {def_o:>14.4f} {opt_v:>14.4f} {opt_o:>14.4f} {diff:>+12.4f}")

    oos_better = opt_split["out_sample"]["ann_return"] > default_split["out_sample"]["ann_return"]
    oos_calmar_better = opt_split["out_sample"]["calmar"] > default_split["out_sample"]["calmar"]

    print()
    if oos_better and oos_calmar_better:
        print(f"✅ {symbol}: 优化参数在样本外（年化+Calmar）均优于默认参数")
    elif oos_better or oos_calmar_better:
        print(f"⚠️ {symbol}: 优化参数在样本外仅部分指标优于默认参数")
    else:
        print(f"❌ {symbol}: 优化参数在样本外未优于默认参数，可能过拟合")

    return {
        "symbol": symbol,
        "default": default_split,
        "optimized": opt_split,
        "oos_better": oos_better,
        "oos_calmar_better": oos_calmar_better,
    }


if __name__ == "__main__":
    results = []
    for symbol, opt_file in [("BTC", "bayesian_optimization_BTC.json"), ("ETH", "bayesian_optimization_ETH.json")]:
        opt_path = os.path.join(BASE_DIR, f"ml/backtest_results/{opt_file}")
        if not os.path.exists(opt_path):
            print(f"跳过 {symbol}：未找到优化结果文件")
            continue
        with open(opt_path) as f:
            opt_data = json.load(f)
        default_params = opt_data["default_params"]
        optimized_params = opt_data["best_params"]
        r = verify_params(symbol, default_params, optimized_params)
        results.append(r)

    print(f"\n{'='*80}")
    print(f"  样本外验证总结")
    print(f"{'='*80}")
    for r in results:
        sym = r["symbol"]
        def_o = r["default"]["out_sample"]["ann_return"] * 100
        opt_o = r["optimized"]["out_sample"]["ann_return"] * 100
        def_c = r["default"]["out_sample"]["calmar"]
        opt_c = r["optimized"]["out_sample"]["calmar"]
        status = "✅" if r["oos_better"] and r["oos_calmar_better"] else ("⚠️" if r["oos_better"] or r["oos_calmar_better"] else "❌")
        print(f"  {sym}: 默认外样本 {def_o:.2f}%(C{def_c:.2f}) → 优化外样本 {opt_o:.2f}%(C{opt_c:.2f})  {status}")

    all_pass = all(r["oos_better"] and r["oos_calmar_better"] for r in results)
    print()
    if all_pass:
        print("✅ 所有币种样本外验证通过，优化参数可应用")
    else:
        print("⚠️ 部分币种样本外验证未通过，需谨慎应用或回退")
