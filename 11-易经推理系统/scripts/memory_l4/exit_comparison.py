#!/usr/bin/env python3
"""
离场系统三选一对比实验
======================

对比四组离场策略：
1. 原始 BCRM 离场（基线）
2. ClassicExit 修复版（提高 risk_gate 阈值 + 盈利旁路）
3. ATR 自适应离场（按市态/币种/波动率动态调整 SL/TP）
4. ClassicExit 贝叶斯寻优版（当前代码默认参数）

判定标准：相对原始 BCRM 必须有提升（收益/夏普/回撤综合），否则回退。
"""
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR in sys.path:
    sys.path.remove(SCRIPT_DIR)

import json
import time
import math
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)

from scripts.memory_l4.classic_exit_system import (
    ClassicExitSystem, PositionState, ExitAction, ExitConfig, ExitPriority,
)
from scripts.memory_l4.exit_backtest_optimize import (
    TradeResult, BacktestMetrics, load_klines, load_trades,
    compute_atr_pct, infer_regime, compute_account_equity,
    run_single_trade, compute_metrics, print_metrics,
    LEVERAGE, FEE_PCT, SYMBOLS,
)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "backtest")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── 1. ClassicExit 修复版配置 ───────────────────────────────────────────────

CONFIG_FIXED = ExitConfig(
    # 提高 risk_gate 阈值：0.50→0.75, 0.40→0.65
    l0_risk_gate_long_thr=0.75,
    l0_risk_gate_short_thr=0.65,
    # 提高 confirm_n：2→4（需 4 根 K 线连续确认）
    l0_risk_gate_confirm_n=4,
    # 盈利旁路：pnl_eff > 3% 时跳过 risk_gate
    l0_risk_gate_profit_bypass_enabled=True,
    l0_risk_gate_profit_bypass_pct=0.03,
    # cooldown 放宽到 30min
    l0_risk_gate_cooldown_min=30.0,
    # L0 止损
    l0_max_loss_pct=-0.15,
    # L2 阈值
    l2_close_threshold=0.70,
    l2_reduce_threshold=0.58,
    # Triple Barrier
    tb_sl_atr_mult=1.5,
    tb_tp_atr_mult=3.0,
    # 跟踪止损
    trailing_arm_profit_pct=0.06,
    trailing_retrace_pct=0.03,
    # RAISE_TP
    l2_raise_tp_value_thr=0.70,
    l2_raise_tp_risk_thr=0.30,
)


# ── 2. ATR 自适应离场系统 ───────────────────────────────────────────────────

@dataclass
class ATRExitConfig:
    """ATR 自适应离场配置"""

    # 市态分桶参数：SL/TP 的 ATR 倍数
    regime_params: Dict[str, dict] = field(default_factory=lambda: {
        "uptrend":   {"sl_mult": 1.8, "tp_mult": 4.5, "max_hold_h": 72, "trail_arm": 0.05, "trail_retrace": 0.30},
        "downtrend": {"sl_mult": 1.3, "tp_mult": 2.5, "max_hold_h": 48, "trail_arm": 0.04, "trail_retrace": 0.35},
        "trend":     {"sl_mult": 1.5, "tp_mult": 3.0, "max_hold_h": 48, "trail_arm": 0.05, "trail_retrace": 0.30},
        "chop":      {"sl_mult": 1.0, "tp_mult": 1.8, "max_hold_h": 24, "trail_arm": 0.03, "trail_retrace": 0.50},
    })

    # 币种波动率分桶微调
    symbol_adjust: Dict[str, dict] = field(default_factory=lambda: {
        "BTC": {"sl_mult_adj": 1.2, "tp_mult_adj": 1.3},   # 低波动，给更多空间
        "ETH": {"sl_mult_adj": 1.0, "tp_mult_adj": 1.1},
        "SOL": {"sl_mult_adj": 0.9, "tp_mult_adj": 1.0},
        "UNI": {"sl_mult_adj": 0.8, "tp_mult_adj": 0.9},   # 高波动，收紧
    })

    # ATR 波动率分桶微调
    atr_bucket_adjust: Dict[str, dict] = field(default_factory=lambda: {
        "low":  {"sl_mult_adj": 1.15, "tp_mult_adj": 1.2},
        "mid":  {"sl_mult_adj": 1.0,  "tp_mult_adj": 1.0},
        "high": {"sl_mult_adj": 0.85, "tp_mult_adj": 0.95},
    })

    # 全局硬止损（含杠杆口径）
    hard_stop_loss_pct: float = -0.20  # pnl_eff < -20% 强制离场

    # 盈利保护：盈利超过此值后启动回撤保护
    profit_protect_arm_pct: float = 0.05  # pnl_eff > 5% 启动
    profit_protect_retrace_ratio: float = 0.50  # 从 MFE 回撤 50% 离场

    # 入场后最小持仓（根 K 线）
    min_hold_bars: int = 2


def _get_atr_bucket(atr_pct: float) -> str:
    """ATR 波动率分桶"""
    if atr_pct < 0.008:
        return "low"
    elif atr_pct < 0.015:
        return "mid"
    else:
        return "high"


def run_atr_adaptive_trade(
    config: ATRExitConfig,
    symbol: str,
    row: pd.Series,
    klines: pd.DataFrame,
    leverage: float = LEVERAGE,
) -> TradeResult:
    """ATR 自适应离场：按市态/币种/波动率动态设置 SL/TP/持仓时间"""

    direction = row["direction"]
    entry_price = float(row["entry_price"])
    entry_time = row["entry_time"]
    original_exit_reason = str(row.get("exit_reason", ""))
    original_pnl = float(row.get("pnl_pct", 0.0))

    side = "long" if direction.upper() in ("LONG", "BUY") else "short"

    kline_slice = klines[klines.index >= entry_time]
    if len(kline_slice) < 5:
        return TradeResult(
            symbol=symbol, direction=direction,
            entry_price=entry_price, exit_price=entry_price,
            entry_time=entry_time, exit_time=entry_time,
            entry_time_str=str(entry_time), exit_time_str=str(entry_time),
            original_exit_reason=original_exit_reason,
            original_pnl_pct=original_pnl,
        )

    # 入场时 ATR
    atr_entry = 0.02
    if len(klines.loc[:entry_time]) >= 15:
        pre = klines.loc[:entry_time].iloc[-15:]
        atr_entry = compute_atr_pct(pre["high"].values, pre["low"].values, pre["close"].values)

    # 入场前市态
    regime_at_entry = "trend"
    pre_entry = klines.loc[:entry_time]
    if len(pre_entry) >= 21:
        regime_at_entry = infer_regime(pre_entry.iloc[-21:]["close"].values)

    # 获取自适应参数
    regime_cfg = config.regime_params.get(regime_at_entry, config.regime_params["trend"])
    sym_adj = config.symbol_adjust.get(symbol, {"sl_mult_adj": 1.0, "tp_mult_adj": 1.0})
    atr_bucket = _get_atr_bucket(atr_entry)
    atr_adj = config.atr_bucket_adjust.get(atr_bucket, {"sl_mult_adj": 1.0, "tp_mult_adj": 1.0})

    sl_mult = regime_cfg["sl_mult"] * sym_adj["sl_mult_adj"] * atr_adj["sl_mult_adj"]
    tp_mult = regime_cfg["tp_mult"] * sym_adj["tp_mult_adj"] * atr_adj["tp_mult_adj"]
    max_hold_h = regime_cfg["max_hold_h"]
    trail_arm = regime_cfg["trail_arm"]
    trail_retrace = regime_cfg["trail_retrace"]

    # 计算 SL/TP 价格
    atr_value = atr_entry * entry_price
    if side == "long":
        sl_price = entry_price - sl_mult * atr_value
        tp_price = entry_price + tp_mult * atr_value
    else:
        sl_price = entry_price + sl_mult * atr_value
        tp_price = entry_price - tp_mult * atr_value

    max_hold_bars = max_hold_h  # 1H K线
    min_hold_bars = config.min_hold_bars

    # 遍历 K 线
    bars_held = 0
    mfe = 0.0
    max_dd = 0.0
    exit_price = float(kline_slice.iloc[0]["close"])
    exit_time = kline_slice.index[0]
    exit_reason = "data_end"
    trailing_stop_price = 0.0
    trailing_armed = False

    for i in range(1, len(kline_slice)):
        bar = kline_slice.iloc[i]
        current_price = float(bar["close"])
        bar_time = kline_slice.index[i]

        if side == "long":
            raw_pnl = (current_price - entry_price) / entry_price
        else:
            raw_pnl = (entry_price - current_price) / entry_price
        pnl_eff = raw_pnl * leverage

        if raw_pnl > mfe:
            mfe = raw_pnl
        cur_dd = max(0.0, -raw_pnl)
        if cur_dd > max_dd:
            max_dd = cur_dd

        bars_held = i

        # 最小持仓期内不离场（除非硬止损）
        if bars_held < min_hold_bars:
            if pnl_eff < config.hard_stop_loss_pct:
                exit_price = current_price
                exit_time = bar_time
                exit_reason = "HARD_STOP"
                break
            continue

        # 1. 硬止损
        if pnl_eff < config.hard_stop_loss_pct:
            exit_price = current_price
            exit_time = bar_time
            exit_reason = "HARD_STOP"
            break

        # 2. SL / TP 触及（用 high/low 判断）
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])

        if side == "long":
            if bar_low <= sl_price:
                exit_price = sl_price
                exit_time = bar_time
                exit_reason = "ATR_SL"
                break
            if bar_high >= tp_price:
                exit_price = tp_price
                exit_time = bar_time
                exit_reason = "ATR_TP"
                break
        else:
            if bar_high >= sl_price:
                exit_price = sl_price
                exit_time = bar_time
                exit_reason = "ATR_SL"
                break
            if bar_low <= tp_price:
                exit_price = tp_price
                exit_time = bar_time
                exit_reason = "ATR_TP"
                break

        # 3. 盈利保护（回撤保护）
        if pnl_eff > config.profit_protect_arm_pct:
            retrace = (mfe - raw_pnl) / (mfe + 1e-8)
            if retrace > config.profit_protect_retrace_ratio:
                exit_price = current_price
                exit_time = bar_time
                exit_reason = "PROFIT_PROTECT"
                break

        # 4. 跟踪止损
        if pnl_eff > trail_arm:
            if not trailing_armed:
                trailing_armed = True
                if side == "long":
                    trailing_stop_price = current_price - trail_retrace * atr_value
                else:
                    trailing_stop_price = current_price + trail_retrace * atr_value
            else:
                if side == "long":
                    new_stop = current_price - trail_retrace * atr_value
                    if new_stop > trailing_stop_price:
                        trailing_stop_price = new_stop
                    if bar_low <= trailing_stop_price:
                        exit_price = trailing_stop_price
                        exit_time = bar_time
                        exit_reason = "TRAILING"
                        break
                else:
                    new_stop = current_price + trail_retrace * atr_value
                    if new_stop < trailing_stop_price or trailing_stop_price == 0:
                        trailing_stop_price = new_stop
                    if bar_high >= trailing_stop_price:
                        exit_price = trailing_stop_price
                        exit_time = bar_time
                        exit_reason = "TRAILING"
                        break

        # 5. 最大持仓时间
        if bars_held >= max_hold_bars:
            exit_price = current_price
            exit_time = bar_time
            exit_reason = "MAX_HOLD"
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
    pnl_eff = pnl_raw * leverage
    fee_cost = FEE_PCT * 2
    pnl_eff -= fee_cost
    pnl_raw -= fee_cost / leverage

    return TradeResult(
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
        leverage=leverage,
        reduce_count=0,
        atr_pct_at_entry=atr_entry,
        regime=regime_at_entry,
    )


def run_atr_backtest(config: ATRExitConfig, symbols: List[str] = None) -> Tuple[BacktestMetrics, List[TradeResult]]:
    """运行 ATR 自适应离场回测"""
    if symbols is None:
        symbols = SYMBOLS

    all_results: List[TradeResult] = []

    for symbol in symbols:
        klines = load_klines(symbol)
        trades = load_trades(symbol)
        if klines is None or trades is None:
            continue
        for _, row in trades.iterrows():
            result = run_atr_adaptive_trade(config, symbol, row, klines)
            all_results.append(result)

    metrics = compute_metrics(all_results)
    return metrics, all_results


def run_classic_backtest(config: ExitConfig, symbols: List[str] = None) -> Tuple[BacktestMetrics, List[TradeResult]]:
    """运行 ClassicExit 回测（复用 exit_backtest_optimize 的 run_single_trade）"""
    if symbols is None:
        symbols = SYMBOLS

    system = ClassicExitSystem(config=config)
    all_results: List[TradeResult] = []

    for symbol in symbols:
        klines = load_klines(symbol)
        trades = load_trades(symbol)
        if klines is None or trades is None:
            continue
        for _, row in trades.iterrows():
            result = run_single_trade(system, symbol, row, klines)
            all_results.append(result)

    metrics = compute_metrics(all_results)
    return metrics, all_results


def run_original_bcrm(symbols: List[str] = None) -> Tuple[BacktestMetrics, List[TradeResult]]:
    """运行原始 BCRM 离场（直接用 trades CSV 的原始 exit）"""
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

            # 计算 ATR
            atr_entry = 0.02
            if klines is not None and len(klines.loc[:entry_time]) >= 15:
                pre = klines.loc[:entry_time].iloc[-15:]
                atr_entry = compute_atr_pct(pre["high"].values, pre["low"].values, pre["close"].values)

            # 市态
            regime_at_entry = "trend"
            if klines is not None:
                pre_entry = klines.loc[:entry_time]
                if len(pre_entry) >= 21:
                    regime_at_entry = infer_regime(pre_entry.iloc[-21:]["close"].values)

            # 持仓 K 线数
            hold_bars = 0
            if klines is not None:
                slice_df = klines[(klines.index >= entry_time) & (klines.index <= exit_time)]
                hold_bars = len(slice_df)

            all_results.append(TradeResult(
                symbol=symbol,
                direction=str(row.get("direction", "")),
                entry_price=entry_price,
                exit_price=entry_price,  # 原始 exit_price 不精确
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


# ── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  离场系统三选一对比实验")
    print("=" * 70)
    print(f"  币种: {SYMBOLS}")
    print(f"  杠杆: {LEVERAGE}x")
    print(f"  手续费: {FEE_PCT*100}%/边")

    # 数据加载
    print(f"\n  [数据加载]")
    for symbol in SYMBOLS:
        klines = load_klines(symbol)
        trades = load_trades(symbol)
        if klines is not None and trades is not None:
            print(f"    {symbol}: {len(trades)} 笔交易, {len(klines)} 根K线")

    # ── 1. 原始 BCRM ──
    print(f"\n  [1] 原始 BCRM 离场...")
    t0 = time.time()
    metrics_orig, results_orig = run_original_bcrm()
    print(f"    耗时: {time.time()-t0:.0f}秒")
    print_metrics("原始 BCRM 离场", metrics_orig, results_orig)

    # ── 2. ClassicExit 修复版 ──
    print(f"\n  [2] ClassicExit 修复版（提高阈值+盈利旁路）...")
    print(f"    risk_gate_thr=0.75/0.65, confirm_n=4, profit_bypass=3%, cooldown=30min")
    t0 = time.time()
    metrics_fixed, results_fixed = run_classic_backtest(CONFIG_FIXED)
    print(f"    耗时: {time.time()-t0:.0f}秒")
    print_metrics("ClassicExit 修复版", metrics_fixed, results_fixed)

    # ── 3. ATR 自适应离场 ──
    print(f"\n  [3] ATR 自适应离场（市态+币种+波动率）...")
    t0 = time.time()
    atr_config = ATRExitConfig()
    metrics_atr, results_atr = run_atr_backtest(atr_config)
    print(f"    耗时: {time.time()-t0:.0f}秒")
    print_metrics("ATR 自适应离场", metrics_atr, results_atr)

    # ── 4. ClassicExit 贝叶斯寻优版 ──
    print(f"\n  [4] ClassicExit 贝叶斯寻优版（当前代码默认参数）...")
    t0 = time.time()
    metrics_bayes, results_bayes = run_classic_backtest(ExitConfig())
    print(f"    耗时: {time.time()-t0:.0f}秒")
    print_metrics("ClassicExit 贝叶斯寻优版", metrics_bayes, results_bayes)

    # ── 对比汇总 ──
    print(f"\n\n{'='*70}")
    print(f"  四组离场策略对比汇总")
    print(f"{'='*70}")
    print(f"  {'指标':<18} {'原始BCRM':>12} {'Classic修复':>12} {'ATR自适应':>12} {'贝叶斯寻优':>12}")
    print(f"  {'─'*70}")
    print(f"  {'总收益率%(加总)':<18} {metrics_orig.total_return_pct:>12.2f} {metrics_fixed.total_return_pct:>12.2f} {metrics_atr.total_return_pct:>12.2f} {metrics_bayes.total_return_pct:>12.2f}")
    print(f"  {'总收益率%(账户)':<18} {metrics_orig.total_return_account_pct:>12.2f} {metrics_fixed.total_return_account_pct:>12.2f} {metrics_atr.total_return_account_pct:>12.2f} {metrics_bayes.total_return_account_pct:>12.2f}")
    print(f"  {'胜率%':<18} {metrics_orig.win_rate:>12.1f} {metrics_fixed.win_rate:>12.1f} {metrics_atr.win_rate:>12.1f} {metrics_bayes.win_rate:>12.1f}")
    print(f"  {'夏普比率':<18} {metrics_orig.sharpe_ratio:>12.2f} {metrics_fixed.sharpe_ratio:>12.2f} {metrics_atr.sharpe_ratio:>12.2f} {metrics_bayes.sharpe_ratio:>12.2f}")
    print(f"  {'最大回撤%(账户)':<18} {metrics_orig.max_drawdown_pct_account:>12.2f} {metrics_fixed.max_drawdown_pct_account:>12.2f} {metrics_atr.max_drawdown_pct_account:>12.2f} {metrics_bayes.max_drawdown_pct_account:>12.2f}")
    print(f"  {'盈亏比':<18} {metrics_orig.profit_factor:>12.2f} {metrics_fixed.profit_factor:>12.2f} {metrics_atr.profit_factor:>12.2f} {metrics_bayes.profit_factor:>12.2f}")
    print(f"  {'平均持仓h':<18} {metrics_orig.avg_hold_bars:>12.1f} {metrics_fixed.avg_hold_bars:>12.1f} {metrics_atr.avg_hold_bars:>12.1f} {metrics_bayes.avg_hold_bars:>12.1f}")

    # 离场原因分布对比
    print(f"\n  [离场原因分布对比]")
    for name, m in [("原始BCRM", metrics_orig), ("Classic修复", metrics_fixed),
                     ("ATR自适应", metrics_atr), ("贝叶斯寻优", metrics_bayes)]:
        print(f"    {name}:")
        for reason, count in sorted(m.exit_reason_dist.items(), key=lambda x: -x[1])[:5]:
            pct = count / m.total_trades * 100
            print(f"      {reason:30s}: {count:3d} ({pct:.1f}%)")

    # ATR/市态/币种 分组对比（ATR自适应 vs 原始BCRM）
    print(f"\n  [ATR自适应 vs 原始BCRM：按市态对比]")
    print(f"    {'市态':<12} {'BCRM收益%':>12} {'ATR收益%':>12} {'差异%':>12} {'BCRM胜率%':>12} {'ATR胜率%':>12}")
    for reg in ["uptrend", "downtrend", "trend", "chop"]:
        orig_m = metrics_orig.regime_metrics.get(reg, {})
        atr_m = metrics_atr.regime_metrics.get(reg, {})
        if orig_m or atr_m:
            o_ret = orig_m.get("total_return", 0)
            a_ret = atr_m.get("total_return", 0)
            o_wr = orig_m.get("win_rate", 0)
            a_wr = atr_m.get("win_rate", 0)
            print(f"    {reg:<12} {o_ret:>12.2f} {a_ret:>12.2f} {a_ret-o_ret:>+12.2f} {o_wr:>12.1f} {a_wr:>12.1f}")

    print(f"\n  [ATR自适应 vs 原始BCRM：按ATR波动率分组对比]")
    print(f"    {'ATR分组':<12} {'BCRM收益%':>12} {'ATR收益%':>12} {'差异%':>12} {'BCRM胜率%':>12} {'ATR胜率%':>12}")
    for label in ["low_atr", "mid_atr", "high_atr"]:
        orig_m = metrics_orig.atr_bucket_metrics.get(label, {})
        atr_m = metrics_atr.atr_bucket_metrics.get(label, {})
        if orig_m or atr_m:
            o_ret = orig_m.get("total_return", 0)
            a_ret = atr_m.get("total_return", 0)
            o_wr = orig_m.get("win_rate", 0)
            a_wr = atr_m.get("win_rate", 0)
            print(f"    {label:<12} {o_ret:>12.2f} {a_ret:>12.2f} {a_ret-o_ret:>+12.2f} {o_wr:>12.1f} {a_wr:>12.1f}")

    print(f"\n  [ATR自适应 vs 原始BCRM：按币种对比]")
    print(f"    {'币种':<8} {'BCRM收益%':>12} {'ATR收益%':>12} {'差异%':>12} {'BCRM胜率%':>12} {'ATR胜率%':>12}")
    for sym in SYMBOLS:
        orig_m = metrics_orig.symbol_metrics.get(sym, {})
        atr_m = metrics_atr.symbol_metrics.get(sym, {})
        if orig_m or atr_m:
            o_ret = orig_m.get("total_return", 0)
            a_ret = atr_m.get("total_return", 0)
            o_wr = orig_m.get("win_rate", 0)
            a_wr = atr_m.get("win_rate", 0)
            print(f"    {sym:<8} {o_ret:>12.2f} {a_ret:>12.2f} {a_ret-o_ret:>+12.2f} {o_wr:>12.1f} {a_wr:>12.1f}")

    # ── 择优决策 ──
    print(f"\n  [择优决策]")

    def score(m):
        return m.sharpe_ratio + 0.01 * m.total_return_pct - 0.05 * m.max_drawdown_pct_account

    candidates = [
        ("原始BCRM", metrics_orig),
        ("Classic修复", metrics_fixed),
        ("ATR自适应", metrics_atr),
        ("贝叶斯寻优", metrics_bayes),
    ]

    print(f"    综合评分公式: sharpe + 0.01*return - 0.05*drawdown(账户)")
    for name, m in candidates:
        s = score(m)
        print(f"    {name:<16}: score={s:+.4f}, return={m.total_return_pct:+.2f}%, sharpe={m.sharpe_ratio:.2f}, dd={m.max_drawdown_pct_account:.2f}%")

    best_name, best_m = max(candidates, key=lambda x: score(x[1]))
    print(f"\n    >>> 最优: {best_name}")

    # 提升判定
    orig_score = score(metrics_orig)
    best_score = score(best_m)
    if best_score > orig_score:
        print(f"    >>> 相对原始BCRM有提升: {best_score:.4f} > {orig_score:.4f} (Δ={best_score-orig_score:+.4f})")
    else:
        print(f"    >>> 警告: 相对原始BCRM无提升: {best_score:.4f} <= {orig_score:.4f}")
        print(f"    >>> 建议回退到原始BCRM离场策略")

    # 保存结果
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "leverage": LEVERAGE,
        "symbols": SYMBOLS,
        "original_bcrm": {
            "total_return_pct": metrics_orig.total_return_pct,
            "total_return_account_pct": metrics_orig.total_return_account_pct,
            "win_rate": metrics_orig.win_rate,
            "sharpe_ratio": metrics_orig.sharpe_ratio,
            "max_drawdown_pct": metrics_orig.max_drawdown_pct_account,
            "profit_factor": metrics_orig.profit_factor,
            "avg_hold_bars": metrics_orig.avg_hold_bars,
            "exit_reason_dist": metrics_orig.exit_reason_dist,
        },
        "classic_fixed": {
            "config": {
                "l0_risk_gate_long_thr": 0.75,
                "l0_risk_gate_short_thr": 0.65,
                "l0_risk_gate_confirm_n": 4,
                "l0_risk_gate_profit_bypass_pct": 0.03,
                "l0_risk_gate_cooldown_min": 30.0,
            },
            "metrics": {
                "total_return_pct": metrics_fixed.total_return_pct,
                "total_return_account_pct": metrics_fixed.total_return_account_pct,
                "win_rate": metrics_fixed.win_rate,
                "sharpe_ratio": metrics_fixed.sharpe_ratio,
                "max_drawdown_pct": metrics_fixed.max_drawdown_pct_account,
                "profit_factor": metrics_fixed.profit_factor,
                "avg_hold_bars": metrics_fixed.avg_hold_bars,
                "exit_reason_dist": metrics_fixed.exit_reason_dist,
            },
        },
        "atr_adaptive": {
            "config": {
                "regime_params": atr_config.regime_params,
                "symbol_adjust": atr_config.symbol_adjust,
                "hard_stop_loss_pct": atr_config.hard_stop_loss_pct,
                "profit_protect_arm_pct": atr_config.profit_protect_arm_pct,
                "profit_protect_retrace_ratio": atr_config.profit_protect_retrace_ratio,
            },
            "metrics": {
                "total_return_pct": metrics_atr.total_return_pct,
                "total_return_account_pct": metrics_atr.total_return_account_pct,
                "win_rate": metrics_atr.win_rate,
                "sharpe_ratio": metrics_atr.sharpe_ratio,
                "max_drawdown_pct": metrics_atr.max_drawdown_pct_account,
                "profit_factor": metrics_atr.profit_factor,
                "avg_hold_bars": metrics_atr.avg_hold_bars,
                "exit_reason_dist": metrics_atr.exit_reason_dist,
            },
        },
        "bayesian_optimal": {
            "metrics": {
                "total_return_pct": metrics_bayes.total_return_pct,
                "total_return_account_pct": metrics_bayes.total_return_account_pct,
                "win_rate": metrics_bayes.win_rate,
                "sharpe_ratio": metrics_bayes.sharpe_ratio,
                "max_drawdown_pct": metrics_bayes.max_drawdown_pct_account,
                "profit_factor": metrics_bayes.profit_factor,
                "avg_hold_bars": metrics_bayes.avg_hold_bars,
                "exit_reason_dist": metrics_bayes.exit_reason_dist,
            },
        },
        "selected": best_name,
        "improvement_over_original": best_score > orig_score,
        "score_original": orig_score,
        "score_best": best_score,
    }

    output_path = os.path.join(OUTPUT_DIR, "exit_comparison_result.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  结果已保存: {output_path}")

    return best_name


if __name__ == "__main__":
    main()
