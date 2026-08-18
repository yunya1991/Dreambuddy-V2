#!/usr/bin/env python3
"""
新版 BCRM 离场回测
==================
使用更新后的 BCRM TP/SL 参数 + ATR 回退 + L0 安全网
对比原始 BCRM 离场，判断是否需要回退。
"""
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR in sys.path:
    sys.path.remove(SCRIPT_DIR)

import json
import time
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)

from scripts.memory_l4.exit_backtest_optimize import (
    TradeResult, BacktestMetrics, load_klines, load_trades,
    compute_atr_pct, infer_regime, compute_account_equity,
    compute_metrics, print_metrics,
    LEVERAGE, FEE_PCT, SYMBOLS,
)

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "backtest")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def run_new_bcrm_backtest(symbols: List[str] = None) -> Tuple[BacktestMetrics, List[TradeResult]]:
    """
    新版 BCRM 离场回测
    规则（已回退到原始参数）：
    1. SL = min(volatility * 2.0, 8%) 价格波动
    2. TP = min(volatility * 3.5, 15%) 价格波动
    3. 低置信度(confidence < 0.5): SL *= 0.7, TP *= 0.8
    4. ATR 回退：当 BCRM 未计算 SL/TP 时，SL = 1.5x ATR, TP = 3.0x ATR
    5. L0 安全网：持仓超 48h 或订单亏损超 10% 强制离场
    """
    if symbols is None:
        symbols = SYMBOLS

    all_results: List[TradeResult] = []

    for symbol in symbols:
        klines = load_klines(symbol)
        trades = load_trades(symbol)
        if klines is None or trades is None:
            continue

        for _, row in trades.iterrows():
            direction = row["direction"]
            entry_price = float(row["entry_price"])
            entry_time = row["entry_time"]
            original_pnl = float(row.get("pnl_pct", 0.0))
            original_exit_reason = str(row.get("exit_reason", ""))
            confidence = float(row.get("confidence", 0.5))

            side = "long" if direction.upper() in ("LONG", "BUY") else "short"

            kline_slice = klines[klines.index >= entry_time]
            if len(kline_slice) < 5:
                all_results.append(TradeResult(
                    symbol=symbol, direction=direction,
                    entry_price=entry_price, exit_price=entry_price,
                    entry_time=entry_time, exit_time=entry_time,
                    entry_time_str=str(entry_time), exit_time_str=str(entry_time),
                    original_exit_reason=original_exit_reason,
                    original_pnl_pct=original_pnl,
                ))
                continue

            # 入场时 ATR
            atr_entry = 0.02
            if len(klines.loc[:entry_time]) >= 15:
                pre = klines.loc[:entry_time].iloc[-15:]
                atr_entry = compute_atr_pct(pre["high"].values, pre["low"].values, pre["close"].values)

            # 市态
            regime_at_entry = "trend"
            pre_entry = klines.loc[:entry_time]
            if len(pre_entry) >= 21:
                regime_at_entry = infer_regime(pre_entry.iloc[-21:]["close"].values)

            # 计算 SL / TP（基于波动率）— 已回退到原始参数
            volatility = atr_entry
            sl_pct = min(volatility * 2.0, 0.08)
            tp_pct = min(volatility * 3.5, 0.15)

            # 低置信度调整
            if confidence < 0.5:
                sl_pct *= 0.7
                tp_pct *= 0.8

            # ATR 回退：如果波动率异常低，使用 ATR 倍数
            if sl_pct < 0.005:  # 小于 0.5%
                sl_pct = max(0.005, atr_entry * 1.5)
            if tp_pct < 0.01:  # 小于 1%
                tp_pct = max(0.01, atr_entry * 3.0)

            if side == "long":
                sl_price = entry_price * (1 - sl_pct)
                tp_price = entry_price * (1 + tp_pct)
            else:
                sl_price = entry_price * (1 + sl_pct)
                tp_price = entry_price * (1 - tp_pct)

            # L0 安全网参数
            max_hold_sec = 172800  # 48h
            max_loss_pct = -0.10   # 订单亏损 10%

            # 遍历 K 线
            exit_price = entry_price
            exit_time = entry_time
            exit_reason = "data_end"
            bars_held = 0
            mfe = 0.0
            max_dd = 0.0

            for i in range(1, len(kline_slice)):
                bar = kline_slice.iloc[i]
                current_price = float(bar["close"])
                bar_high = float(bar["high"])
                bar_low = float(bar["low"])
                bar_time = kline_slice.index[i]
                age_sec = (bar_time - entry_time).total_seconds()
                bars_held = i

                if side == "long":
                    raw_pnl = (current_price - entry_price) / entry_price
                else:
                    raw_pnl = (entry_price - current_price) / entry_price

                if raw_pnl > mfe:
                    mfe = raw_pnl

                cur_dd = max(0.0, -raw_pnl)
                if cur_dd > max_dd:
                    max_dd = cur_dd

                # 检查 TP/SL 触发（订单级）
                if side == "long":
                    if bar_low <= sl_price:
                        exit_price = sl_price
                        exit_time = bar_time
                        exit_reason = "sl"
                        break
                    if bar_high >= tp_price:
                        exit_price = tp_price
                        exit_time = bar_time
                        exit_reason = "tp"
                        break
                else:
                    if bar_high >= sl_price:
                        exit_price = sl_price
                        exit_time = bar_time
                        exit_reason = "sl"
                        break
                    if bar_low <= tp_price:
                        exit_price = tp_price
                        exit_time = bar_time
                        exit_reason = "tp"
                        break

                # L0 安全网：最大亏损
                if raw_pnl * LEVERAGE <= max_loss_pct:
                    exit_price = current_price
                    exit_time = bar_time
                    exit_reason = "l0_max_loss"
                    break

                # L0 安全网：最大持仓时间
                if age_sec >= max_hold_sec:
                    exit_price = current_price
                    exit_time = bar_time
                    exit_reason = "l0_max_hold"
                    break

            # 数据结束
            if exit_reason == "data_end":
                exit_price = float(kline_slice.iloc[-1]["close"])
                exit_time = kline_slice.index[-1]
                if side == "long":
                    raw_pnl = (exit_price - entry_price) / entry_price
                else:
                    raw_pnl = (entry_price - exit_price) / entry_price

            pnl_raw = raw_pnl
            pnl_eff = pnl_raw * LEVERAGE
            fee_cost = FEE_PCT * 2
            pnl_eff -= fee_cost
            pnl_raw -= fee_cost / LEVERAGE

            all_results.append(TradeResult(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                exit_price=exit_price,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_time_str=str(entry_time),
                exit_time_str=str(exit_time),
                pnl_pct=pnl_eff,
                pnl_raw_pct=pnl_raw,
                hold_bars=bars_held,
                max_dd_pct_raw=max_dd,
                exit_reason=exit_reason,
                original_exit_reason=original_exit_reason,
                original_pnl_pct=original_pnl,
                leverage=LEVERAGE,
                reduce_count=0,
                atr_pct_at_entry=atr_entry,
                regime=regime_at_entry,
            ))

    metrics = compute_metrics(all_results)
    return metrics, all_results


def run_original_bcrm(symbols: List[str] = None) -> Tuple[BacktestMetrics, List[TradeResult]]:
    """原始 BCRM 离场（直接用 trades CSV 的原始 exit）"""
    if symbols is None:
        symbols = SYMBOLS

    all_results: List[TradeResult] = []

    for symbol in symbols:
        trades = load_trades(symbol)
        if trades is None:
            continue
        klines = load_klines(symbol)
        for _, row in trades.iterrows():
            entry_price = float(row["entry_price"])
            entry_time = row["entry_time"]
            original_pnl = float(row.get("pnl_pct", 0.0))
            original_exit_reason = str(row.get("exit_reason", ""))
            exit_time = row["exit_time"]

            atr_entry = 0.02
            if klines is not None and len(klines.loc[:entry_time]) >= 15:
                pre = klines.loc[:entry_time].iloc[-15:]
                atr_entry = compute_atr_pct(pre["high"].values, pre["low"].values, pre["close"].values)

            regime_at_entry = "trend"
            if klines is not None:
                pre_entry = klines.loc[:entry_time]
                if len(pre_entry) >= 21:
                    regime_at_entry = infer_regime(pre_entry.iloc[-21:]["close"].values)

            hold_bars = 0
            if klines is not None:
                slice_df = klines[(klines.index >= entry_time) & (klines.index <= exit_time)]
                hold_bars = len(slice_df)

            all_results.append(TradeResult(
                symbol=symbol,
                direction=str(row.get("direction", "")),
                entry_price=entry_price,
                exit_price=entry_price,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_time_str=str(entry_time),
                exit_time_str=str(exit_time),
                pnl_pct=original_pnl,
                pnl_raw_pct=original_pnl / LEVERAGE,
                hold_bars=hold_bars,
                max_dd_pct_raw=0.0,
                exit_reason=original_exit_reason,
                original_exit_reason=original_exit_reason,
                original_pnl_pct=original_pnl,
                leverage=LEVERAGE,
                reduce_count=0,
                atr_pct_at_entry=atr_entry,
                regime=regime_at_entry,
            ))

    metrics = compute_metrics(all_results)
    return metrics, all_results


def main():
    print("=" * 70)
    print("  新版 BCRM 离场回测对比")
    print("=" * 70)
    print(f"  币种: {SYMBOLS}")
    print(f"  杠杆: {LEVERAGE}x")
    print(f"  新版规则: SL=min(vol*2.0, 8%), TP=min(vol*3.5, 15%), 低置信度更紧")
    print(f"  L0 安全网: max_hold=48h, max_loss=-10% (已回退到原始参数)")

    # 1. 原始 BCRM
    print(f"\n  [1] 原始 BCRM 离场...")
    t0 = time.time()
    metrics_orig, results_orig = run_original_bcrm()
    print(f"    耗时: {time.time()-t0:.1f}秒")
    print_metrics("原始 BCRM", metrics_orig, results_orig)

    # 2. 新版 BCRM
    print(f"\n  [2] 新版 BCRM 离场...")
    t0 = time.time()
    metrics_new, results_new = run_new_bcrm_backtest()
    print(f"    耗时: {time.time()-t0:.1f}秒")
    print_metrics("新版 BCRM", metrics_new, results_new)

    # 对比汇总
    print(f"\n{'='*70}")
    print(f"  对比汇总")
    print(f"{'='*70}")
    print(f"  {'指标':<20} {'原始 BCRM':>12} {'新版 BCRM':>12} {'变化':>12}")
    print(f"  {'─'*60}")

    def fmt_delta(old, new, fmt=".2f", pct=False):
        delta = new - old
        sign = "+" if delta >= 0 else ""
        unit = "%" if pct else ""
        return f"{sign}{delta:{fmt}}{unit}"

    print(f"  {'总收益率%(账户)':<20} {metrics_orig.total_return_account_pct:>12.2f} {metrics_new.total_return_account_pct:>12.2f} {fmt_delta(metrics_orig.total_return_account_pct, metrics_new.total_return_account_pct):>12}")
    print(f"  {'胜率%':<20} {metrics_orig.win_rate:>12.1f} {metrics_new.win_rate:>12.1f} {fmt_delta(metrics_orig.win_rate, metrics_new.win_rate, '.1f', True):>12}")
    print(f"  {'夏普比率':<20} {metrics_orig.sharpe_ratio:>12.2f} {metrics_new.sharpe_ratio:>12.2f} {fmt_delta(metrics_orig.sharpe_ratio, metrics_new.sharpe_ratio):>12}")
    print(f"  {'最大回撤%(账户)':<20} {metrics_orig.max_drawdown_pct_account:>12.2f} {metrics_new.max_drawdown_pct_account:>12.2f} {fmt_delta(metrics_orig.max_drawdown_pct_account, metrics_new.max_drawdown_pct_account):>12}")
    print(f"  {'盈亏比':<20} {metrics_orig.profit_factor:>12.2f} {metrics_new.profit_factor:>12.2f} {fmt_delta(metrics_orig.profit_factor, metrics_new.profit_factor):>12}")
    print(f"  {'平均持仓h':<20} {metrics_orig.avg_hold_bars:>12.1f} {metrics_new.avg_hold_bars:>12.1f} {fmt_delta(metrics_orig.avg_hold_bars, metrics_new.avg_hold_bars, '.1f'):>12}")

    # 离场原因分布
    print(f"\n  离场原因分布对比:")
    from collections import Counter
    orig_reasons = Counter([r.exit_reason for r in results_orig])
    new_reasons = Counter([r.exit_reason for r in results_new])
    all_reasons = sorted(set(list(orig_reasons.keys()) + list(new_reasons.keys())))
    print(f"  {'原因':<15} {'原始':>8} {'新版':>8}")
    for reason in all_reasons:
        print(f"  {reason:<15} {orig_reasons.get(reason, 0):>8} {new_reasons.get(reason, 0):>8}")

    # 判定
    print(f"\n{'='*70}")
    score_orig = metrics_orig.sharpe_ratio + metrics_orig.total_return_account_pct / 100.0 - metrics_orig.max_drawdown_pct_account / 10.0
    score_new = metrics_new.sharpe_ratio + metrics_new.total_return_account_pct / 100.0 - metrics_new.max_drawdown_pct_account / 10.0

    if score_new > score_orig:
        print(f"  ✅ 新版 BCRM 综合评分更优: {score_new:.2f} > {score_orig:.2f}")
        print(f"  建议: 保留新版参数")
    else:
        print(f"  ⚠️  新版 BCRM 综合评分更差: {score_new:.2f} <= {score_orig:.2f}")
        print(f"  建议: 回退到原始 BCRM 参数")
    print(f"{'='*70}")

    # 保存结果
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "original": {
            "total_return_account_pct": metrics_orig.total_return_account_pct,
            "win_rate": metrics_orig.win_rate,
            "sharpe_ratio": metrics_orig.sharpe_ratio,
            "max_drawdown_pct_account": metrics_orig.max_drawdown_pct_account,
            "profit_factor": metrics_orig.profit_factor,
            "avg_hold_bars": metrics_orig.avg_hold_bars,
        },
        "new": {
            "total_return_account_pct": metrics_new.total_return_account_pct,
            "win_rate": metrics_new.win_rate,
            "sharpe_ratio": metrics_new.sharpe_ratio,
            "max_drawdown_pct_account": metrics_new.max_drawdown_pct_account,
            "profit_factor": metrics_new.profit_factor,
            "avg_hold_bars": metrics_new.avg_hold_bars,
        },
        "verdict": "keep_new" if score_new > score_orig else "rollback",
    }
    output_path = os.path.join(OUTPUT_DIR, "new_bcrm_backtest_result.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  结果已保存: {output_path}")


if __name__ == "__main__":
    main()
