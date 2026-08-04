#!/usr/bin/env python3
"""A-E五项优化独立贝叶斯验证

原则：每项独立验证 + 贝叶斯寻优 + 持续上升才落地
基线：当前修复后参数（胜率76.59%，策略收益5.23%，账户收益0.26%）

评估口径（持续上升判定）：
  1. 策略总收益 > 基线
  2. 账户收益 > 基线
  3. 夏普比 ≥ 基线 × 0.9
  4. 最大回撤 ≤ 基线 × 1.5
"""
import sys
import os
import json
import time
import math
import numpy as np
from pathlib import Path
from copy import deepcopy
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT_DIR = str(BASE_DIR / "scripts" / "memory_l4")
if SCRIPT_DIR in sys.path:
    sys.path.remove(SCRIPT_DIR)
PROJECT_ROOT = str(BASE_DIR)
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from scripts.memory_l4.classic_exit_system import (
    ClassicExitSystem, PositionState, ExitAction, ExitConfig, ExitPriority,
)
from scripts.memory_l4.exit_backtest_optimize import (
    run_backtest, run_single_trade, load_trades, load_klines,
    compute_metrics, compute_account_equity,
    SYMBOLS, LEVERAGE, FEE_PCT, TradeResult, BacktestMetrics,
)

OUTPUT_DIR = BASE_DIR / "data" / "backtest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ════════════════════════════════════════════════════════════════════════════
# 基线配置（来自 analyze_low_yield.py，即当前修复后参数）
# ════════════════════════════════════════════════════════════════════════════

def make_baseline_config() -> ExitConfig:
    return ExitConfig(
        l0_max_loss_pct=-0.05,
        l1_enabled=True, l2_close_threshold=0.75, l2_reduce_threshold=0.55,
        apply_leverage_to_thresholds=True,
        tb_enabled=True, tb_sl_atr_mult=1.5, tb_tp_atr_mult=3.0,
        tb_sl_min_pct=0.045, tb_tp_min_pct=0.04,
        trailing_enabled=True, trailing_arm_profit_pct=0.04, trailing_retrace_pct=0.035,
        # B项基线：使用落地前的原始值（非ExitConfig默认值，因默认值已被落地覆盖）
        trailing_tp_arm_pct=0.015, trailing_tp_retrace_ratio=0.40,
        tstp_enabled=True, inflight_cooldown_sec=180,
        l0_risk_gate_enabled=True, l0_risk_gate_close_enabled=False,
        l0_risk_gate_cooldown_min=60.0, l0_risk_gate_confirm_n=3,
        l0_risk_gate_long_thr=0.65, l0_risk_gate_short_thr=0.60,
        l0_risk_gate_min_hold_sec=3600.0, l0_risk_gate_profit_bypass_pct=0.05,
    )


# ════════════════════════════════════════════════════════════════════════════
# 辅助：带交易过滤的回测（用于A/D项）
# ════════════════════════════════════════════════════════════════════════════

def run_backtest_filtered(
    config: ExitConfig,
    symbols=None,
    confidence_thr: float = 0.0,
    max_reduce_count: int = -1,
    position_size_pct: float = 0.05,
) -> tuple:
    """带过滤的回测
    - confidence_thr: 过滤掉 confidence < thr 的交易
    - max_reduce_count: 限制最大减仓次数（-1=不限制）
    - position_size_pct: 账户仓位比例（影响账户收益）
    """
    if symbols is None:
        symbols = SYMBOLS

    system = ClassicExitSystem(config=config)
    all_results = []

    for symbol in symbols:
        klines = load_klines(symbol)
        trades = load_trades(symbol)
        if klines is None or trades is None:
            continue

        for _, row in trades.iterrows():
            # A项：confidence过滤
            if confidence_thr > 0 and float(row.get("confidence", 1.0)) < confidence_thr:
                continue
            result = run_single_trade(system, symbol, row, klines)
            # E项：限制减仓次数
            if max_reduce_count >= 0 and result.reduce_count > max_reduce_count:
                result.reduce_count = max_reduce_count
                # 重新计算pnl：减仓次数被截断，手续费减少
                # 简化处理：减仓超出部分视为不平仓，按原始pnl计算
                # 更准确：重跑回测，但为效率这里用近似
            all_results.append(result)

    metrics = compute_metrics_custom(all_results, position_size_pct)
    return metrics, all_results


def compute_metrics_custom(results, position_size_pct: float = 0.05) -> BacktestMetrics:
    """带自定义仓位比例的指标计算"""
    if not results:
        return BacktestMetrics()

    n = len(results)
    wins = [r for r in results if r.pnl_pct > 0]
    losses = [r for r in results if r.pnl_pct <= 0]

    pnls = [r.pnl_pct for r in results]
    total_return = sum(pnls)
    avg_return = total_return / n

    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe = np.mean(pnls) / np.std(pnls) * math.sqrt(6048)
    else:
        sharpe = 0.0

    # 账户权益曲线（自定义仓位）
    total_ret_account, max_dd_account, _ = compute_account_equity_custom(
        results, position_size_pct=position_size_pct
    )

    gross_profit = sum(r.pnl_pct for r in wins)
    gross_loss = abs(sum(r.pnl_pct for r in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    return BacktestMetrics(
        total_trades=n,
        win_trades=len(wins),
        loss_trades=len(losses),
        win_rate=len(wins) / n * 100,
        total_return_pct=total_return,
        total_return_account_pct=total_ret_account,
        avg_return_pct=avg_return,
        sharpe_ratio=sharpe,
        max_drawdown_pct_account=max_dd_account,
        profit_factor=pf,
        avg_hold_bars=np.mean([r.hold_bars for r in results]),
    )


def compute_account_equity_custom(results, initial_capital=100.0, position_size_pct=0.05):
    """自定义仓位的账户权益曲线"""
    if not results:
        return 0.0, 0.0, pd.Series()

    events = []
    for r in results:
        events.append((r.entry_time, "entry", r.pnl_pct, r.symbol))
        events.append((r.exit_time, "exit", r.pnl_pct, r.symbol))
    events.sort(key=lambda x: x[0])

    capital = initial_capital
    equity_curve = [capital]
    times = [events[0][0]]

    for ts, evt_type, pnl, sym in events:
        if evt_type == "exit":
            capital += initial_capital * position_size_pct * pnl / 100.0
            equity_curve.append(capital)
            times.append(ts)

    equity = pd.Series(equity_curve, index=times)
    peak = equity.expanding(min_periods=1).max()
    dd = (equity - peak) / peak * 100.0
    max_dd = abs(dd.min()) if len(dd) > 0 else 0.0
    total_ret = (equity.iloc[-1] - initial_capital) / initial_capital * 100.0
    return total_ret, max_dd, equity


# ════════════════════════════════════════════════════════════════════════════
# E项专用：限制减仓次数的回测（精确版，重跑单笔交易）
# ════════════════════════════════════════════════════════════════════════════

def run_single_trade_max_reduce(
    system: ClassicExitSystem,
    symbol: str,
    row: pd.Series,
    klines: pd.DataFrame,
    max_reduce_count: int = -1,
    leverage: float = LEVERAGE,
) -> TradeResult:
    """带减仓次数限制的单笔交易回测"""
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

    atr_entry = 0.02
    if len(klines.loc[:entry_time]) >= 15:
        pre = klines.loc[:entry_time].iloc[-15:]
        atr_entry = compute_atr_pct(pre["high"].values, pre["low"].values, pre["close"].values)

    current_price = float(kline_slice.iloc[0]["close"])
    pos = PositionState(
        coin=f"{symbol}_{entry_time.strftime('%m%d')}",
        side=side,
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=0.0,
        unrealized_pnl_pct=(current_price - entry_price) / entry_price if side == "long"
                           else (entry_price - current_price) / entry_price,
        leverage=leverage,
        atr_pct=atr_entry,
        mfe_pnl_pct=0.0,
        max_dd_pct=0.0,
        entry_ts=int(entry_time.timestamp()),
        trailing_armed=False,
        trailing_stop_price=0.0,
    )

    bars_held = 0
    mfe = 0.0
    max_dd = 0.0
    exit_price = current_price
    exit_time = kline_slice.index[0]
    exit_reason = "data_end"
    reduce_count = 0
    remaining_frac = 1.0
    realized_pnl = 0.0

    regime_at_entry = "trend"
    pre_entry = klines.loc[:entry_time]
    if len(pre_entry) >= 21:
        regime_at_entry = infer_regime(pre_entry.iloc[-21:]["close"].values)

    for i in range(1, len(kline_slice)):
        bar = kline_slice.iloc[i]
        current_price = float(bar["close"])
        bar_time = kline_slice.index[i]
        age_sec = (bar_time - entry_time).total_seconds()

        pos.current_price = current_price
        pos.position_age_sec = age_sec

        if side == "long":
            raw_pnl = (current_price - entry_price) / entry_price
        else:
            raw_pnl = (entry_price - current_price) / entry_price
        pos.unrealized_pnl_pct = raw_pnl

        if raw_pnl > mfe:
            mfe = raw_pnl
        pos.mfe_pnl_pct = mfe

        cur_dd = max(0.0, -raw_pnl)
        if cur_dd > max_dd:
            max_dd = cur_dd
        pos.max_dd_pct = max_dd

        recent = kline_slice.iloc[max(0, i - 14):i + 1]
        atr_pct = compute_atr_pct(recent["high"].values, recent["low"].values, recent["close"].values)
        pos.atr_pct = atr_pct

        candles_window = []
        start_idx = max(0, i - 60)
        for j in range(start_idx, i + 1):
            b = kline_slice.iloc[j]
            candles_window.append({
                "t": int(kline_slice.index[j].timestamp()),
                "o": float(b["open"]), "h": float(b["high"]),
                "l": float(b["low"]), "c": float(b["close"]),
                "v": float(b["volume"]),
            })

        closes_21 = kline_slice["close"].iloc[max(0, i - 20):i + 1].values
        regime = infer_regime(closes_21) if len(closes_21) >= 21 else regime_at_entry

        decision = system.evaluate_full(pos, candles_window, regime=regime, now_ts=int(bar_time.timestamp()))

        bars_held = i

        if decision.action == ExitAction.CLOSE:
            exit_price = current_price
            exit_time = bar_time
            exit_reason = decision.reason or "close"
            realized_pnl += remaining_frac * raw_pnl
            remaining_frac = 0.0
            break
        elif decision.action == ExitAction.REDUCE:
            # E项：减仓次数上限
            if max_reduce_count >= 0 and reduce_count >= max_reduce_count:
                continue  # 跳过减仓信号
            frac = decision.reduce_frac if decision.reduce_frac > 0 else 0.3
            actual_frac = min(remaining_frac, frac)
            realized_pnl += actual_frac * raw_pnl
            remaining_frac -= actual_frac
            reduce_count += 1
            if remaining_frac <= 0.01:
                exit_price = current_price
                exit_time = bar_time
                exit_reason = decision.reason or "reduce_full"
                remaining_frac = 0.0
                break

    if remaining_frac > 0.01:
        exit_price = current_price
        exit_time = kline_slice.index[-1]
        exit_reason = "data_end"
        realized_pnl += remaining_frac * raw_pnl

    pnl_raw = realized_pnl
    pnl_eff = pnl_raw * leverage
    fee_cost = FEE_PCT * 2 * (1 + reduce_count)
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
        reduce_count=reduce_count,
        atr_pct_at_entry=atr_entry,
        regime=regime_at_entry,
    )


def compute_atr_pct(highs, lows, closes) -> float:
    if len(highs) < 2:
        return 0.02
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    atr = np.mean(trs[-14:]) if len(trs) >= 14 else np.mean(trs)
    return atr / closes[-1] if closes[-1] > 0 else 0.02


def infer_regime(closes: np.ndarray) -> str:
    if len(closes) < 21:
        return "trend"
    ema = closes[0]
    k = 2.0 / 21.0
    for p in closes:
        ema = p * k + ema * (1 - k)
    ret_20 = (closes[-1] - closes[-21]) / closes[-21]
    range_pct = (np.max(closes[-21:]) - np.min(closes[-21:])) / np.mean(closes[-21:])
    trend_ratio = abs(ret_20) / (range_pct + 1e-6)
    if trend_ratio < 0.35:
        return "chop"
    elif ret_20 > 0.015:
        return "uptrend"
    elif ret_20 < -0.015:
        return "downtrend"
    else:
        return "trend"


# ════════════════════════════════════════════════════════════════════════════
# D项专用：min_hold_bars过滤的回测
# ════════════════════════════════════════════════════════════════════════════

def run_single_trade_min_hold(
    system: ClassicExitSystem,
    symbol: str,
    row: pd.Series,
    klines: pd.DataFrame,
    min_hold_bars: int = 0,
    max_reduce_count: int = -1,
    leverage: float = LEVERAGE,
) -> TradeResult:
    """带最小持仓时间过滤的单笔交易回测
    在 min_hold_bars 之前忽略所有非L0离场信号
    同时支持 E项 max_reduce_count 减仓次数限制
    """
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

    atr_entry = 0.02
    if len(klines.loc[:entry_time]) >= 15:
        pre = klines.loc[:entry_time].iloc[-15:]
        atr_entry = compute_atr_pct(pre["high"].values, pre["low"].values, pre["close"].values)

    current_price = float(kline_slice.iloc[0]["close"])
    pos = PositionState(
        coin=f"{symbol}_{entry_time.strftime('%m%d')}",
        side=side,
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=0.0,
        unrealized_pnl_pct=(current_price - entry_price) / entry_price if side == "long"
                           else (entry_price - current_price) / entry_price,
        leverage=leverage,
        atr_pct=atr_entry,
        mfe_pnl_pct=0.0,
        max_dd_pct=0.0,
        entry_ts=int(entry_time.timestamp()),
        trailing_armed=False,
        trailing_stop_price=0.0,
    )

    bars_held = 0
    mfe = 0.0
    max_dd = 0.0
    exit_price = current_price
    exit_time = kline_slice.index[0]
    exit_reason = "data_end"
    reduce_count = 0
    remaining_frac = 1.0
    realized_pnl = 0.0

    regime_at_entry = "trend"
    pre_entry = klines.loc[:entry_time]
    if len(pre_entry) >= 21:
        regime_at_entry = infer_regime(pre_entry.iloc[-21:]["close"].values)

    for i in range(1, len(kline_slice)):
        bar = kline_slice.iloc[i]
        current_price = float(bar["close"])
        bar_time = kline_slice.index[i]
        age_sec = (bar_time - entry_time).total_seconds()

        pos.current_price = current_price
        pos.position_age_sec = age_sec

        if side == "long":
            raw_pnl = (current_price - entry_price) / entry_price
        else:
            raw_pnl = (entry_price - current_price) / entry_price
        pos.unrealized_pnl_pct = raw_pnl

        if raw_pnl > mfe:
            mfe = raw_pnl
        pos.mfe_pnl_pct = mfe

        cur_dd = max(0.0, -raw_pnl)
        if cur_dd > max_dd:
            max_dd = cur_dd
        pos.max_dd_pct = max_dd

        recent = kline_slice.iloc[max(0, i - 14):i + 1]
        atr_pct = compute_atr_pct(recent["high"].values, recent["low"].values, recent["close"].values)
        pos.atr_pct = atr_pct

        candles_window = []
        start_idx = max(0, i - 60)
        for j in range(start_idx, i + 1):
            b = kline_slice.iloc[j]
            candles_window.append({
                "t": int(kline_slice.index[j].timestamp()),
                "o": float(b["open"]), "h": float(b["high"]),
                "l": float(b["low"]), "c": float(b["close"]),
                "v": float(b["volume"]),
            })

        closes_21 = kline_slice["close"].iloc[max(0, i - 20):i + 1].values
        regime = infer_regime(closes_21) if len(closes_21) >= 21 else regime_at_entry

        decision = system.evaluate_full(pos, candles_window, regime=regime, now_ts=int(bar_time.timestamp()))

        bars_held = i

        # D项：min_hold_bars保护期，只允许L0硬离场（安全网）
        in_protection = (min_hold_bars > 0 and i < min_hold_bars)
        is_l0_hard = decision.priority == ExitPriority.P0_L0_HARD

        if decision.action == ExitAction.CLOSE:
            if in_protection and not is_l0_hard:
                continue  # 保护期内跳过非L0离场
            exit_price = current_price
            exit_time = bar_time
            exit_reason = decision.reason or "close"
            realized_pnl += remaining_frac * raw_pnl
            remaining_frac = 0.0
            break
        elif decision.action == ExitAction.REDUCE:
            if in_protection and not is_l0_hard:
                continue  # 保护期内跳过非L0减仓
            # E项：减仓次数上限
            if max_reduce_count >= 0 and reduce_count >= max_reduce_count:
                continue  # 达到减仓上限，跳过
            frac = decision.reduce_frac if decision.reduce_frac > 0 else 0.3
            actual_frac = min(remaining_frac, frac)
            realized_pnl += actual_frac * raw_pnl
            remaining_frac -= actual_frac
            reduce_count += 1
            if remaining_frac <= 0.01:
                exit_price = current_price
                exit_time = bar_time
                exit_reason = decision.reason or "reduce_full"
                remaining_frac = 0.0
                break

    if remaining_frac > 0.01:
        exit_price = current_price
        exit_time = kline_slice.index[-1]
        exit_reason = "data_end"
        realized_pnl += remaining_frac * raw_pnl

    pnl_raw = realized_pnl
    pnl_eff = pnl_raw * leverage
    fee_cost = FEE_PCT * 2 * (1 + reduce_count)
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
        reduce_count=reduce_count,
        atr_pct_at_entry=atr_entry,
        regime=regime_at_entry,
    )


# ════════════════════════════════════════════════════════════════════════════
# 贝叶斯优化目标函数
# ════════════════════════════════════════════════════════════════════════════

def score_metrics(metrics: BacktestMetrics) -> float:
    """综合得分：夏普 + 收益 - 回撤惩罚"""
    return (
        metrics.sharpe_ratio
        + 0.01 * metrics.total_return_pct
        + 0.5 * metrics.total_return_account_pct
        - 0.05 * metrics.max_drawdown_pct_account
    )


def run_baseline():
    """基线评估"""
    print("\n" + "=" * 70)
    print("  基线评估（当前修复后参数，无A-E优化）")
    print("=" * 70)
    config = make_baseline_config()
    metrics, results = run_backtest_filtered(config, position_size_pct=0.05)
    print(f"  交易数:     {metrics.total_trades}")
    print(f"  胜率:       {metrics.win_rate:.2f}%")
    print(f"  策略收益:   {metrics.total_return_pct:.2f}%")
    print(f"  账户收益:   {metrics.total_return_account_pct:.4f}%")
    print(f"  夏普:       {metrics.sharpe_ratio:.2f}")
    print(f"  最大回撤:   {metrics.max_drawdown_pct_account:.4f}%")
    print(f"  盈亏比:     {metrics.profit_factor:.2f}")
    print(f"  平均持仓:   {metrics.avg_hold_bars:.1f}bars")
    return metrics, results


# ── A项：confidence过滤 ──────────────────────────────────────────────────────

def objective_A(trial):
    thr = trial.suggest_float("confidence_thr", 0.0, 0.8)
    config = make_baseline_config()
    metrics, _ = run_backtest_filtered(
        config, confidence_thr=thr, position_size_pct=0.05
    )
    score = score_metrics(metrics)
    trial.set_user_attr("metrics", {
        "trades": metrics.total_trades,
        "win_rate": metrics.win_rate,
        "total_return": metrics.total_return_pct,
        "account_return": metrics.total_return_account_pct,
        "sharpe": metrics.sharpe_ratio,
        "max_dd": metrics.max_drawdown_pct_account,
        "pf": metrics.profit_factor,
    })
    return score


# ── B项：放大止盈空间 ────────────────────────────────────────────────────────

def objective_B(trial):
    arm_pct = trial.suggest_float("trailing_tp_arm_pct", 0.015, 0.06)
    retrace_ratio = trial.suggest_float("trailing_tp_retrace_ratio", 0.15, 0.50)
    config = make_baseline_config()
    config.trailing_tp_arm_pct = arm_pct
    config.trailing_tp_retrace_ratio = retrace_ratio
    metrics, _ = run_backtest_filtered(config, position_size_pct=0.05)
    score = score_metrics(metrics)
    trial.set_user_attr("metrics", {
        "trades": metrics.total_trades,
        "win_rate": metrics.win_rate,
        "total_return": metrics.total_return_pct,
        "account_return": metrics.total_return_account_pct,
        "sharpe": metrics.sharpe_ratio,
        "max_dd": metrics.max_drawdown_pct_account,
        "pf": metrics.profit_factor,
    })
    return score


# ── C项：仓位管理 ────────────────────────────────────────────────────────────

def objective_C(trial):
    pos_size = trial.suggest_float("position_size_pct", 0.05, 0.20)
    config = make_baseline_config()
    # 仓位不影响策略收益，只影响账户收益
    metrics, _ = run_backtest_filtered(config, position_size_pct=pos_size)
    score = score_metrics(metrics)
    trial.set_user_attr("metrics", {
        "trades": metrics.total_trades,
        "win_rate": metrics.win_rate,
        "total_return": metrics.total_return_pct,
        "account_return": metrics.total_return_account_pct,
        "sharpe": metrics.sharpe_ratio,
        "max_dd": metrics.max_drawdown_pct_account,
        "pf": metrics.profit_factor,
        "position_size_pct": pos_size,
    })
    return score


# ── D项：min_hold_bars保护 ───────────────────────────────────────────────────

def objective_D(trial):
    min_hold = trial.suggest_int("min_hold_bars", 0, 8)
    config = make_baseline_config()
    # 需要使用min_hold专用回测
    system = ClassicExitSystem(config=config)
    all_results = []
    for symbol in SYMBOLS:
        klines = load_klines(symbol)
        trades = load_trades(symbol)
        if klines is None or trades is None:
            continue
        for _, row in trades.iterrows():
            result = run_single_trade_min_hold(system, symbol, row, klines, min_hold_bars=min_hold)
            all_results.append(result)
    metrics = compute_metrics_custom(all_results, position_size_pct=0.05)
    score = score_metrics(metrics)
    trial.set_user_attr("metrics", {
        "trades": metrics.total_trades,
        "win_rate": metrics.win_rate,
        "total_return": metrics.total_return_pct,
        "account_return": metrics.total_return_account_pct,
        "sharpe": metrics.sharpe_ratio,
        "max_dd": metrics.max_drawdown_pct_account,
        "pf": metrics.profit_factor,
    })
    return score


# ── E项：max_reduce_count ────────────────────────────────────────────────────

def objective_E(trial):
    max_rc = trial.suggest_int("max_reduce_count", 0, 5)
    config = make_baseline_config()
    system = ClassicExitSystem(config=config)
    all_results = []
    for symbol in SYMBOLS:
        klines = load_klines(symbol)
        trades = load_trades(symbol)
        if klines is None or trades is None:
            continue
        for _, row in trades.iterrows():
            result = run_single_trade_max_reduce(system, symbol, row, klines, max_reduce_count=max_rc)
            all_results.append(result)
    metrics = compute_metrics_custom(all_results, position_size_pct=0.05)
    score = score_metrics(metrics)
    trial.set_user_attr("metrics", {
        "trades": metrics.total_trades,
        "win_rate": metrics.win_rate,
        "total_return": metrics.total_return_pct,
        "account_return": metrics.total_return_account_pct,
        "sharpe": metrics.sharpe_ratio,
        "max_dd": metrics.max_drawdown_pct_account,
        "pf": metrics.profit_factor,
    })
    return score


# ════════════════════════════════════════════════════════════════════════════
# 贝叶斯优化运行器
# ════════════════════════════════════════════════════════════════════════════

def run_optimization(name: str, objective_fn, n_trials: int = 40):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    print(f"\n{'─' * 70}")
    print(f"  {name} 贝叶斯优化（{n_trials} trials）")
    print(f"{'─' * 70}")

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    t0 = time.time()
    study.optimize(objective_fn, n_trials=n_trials, show_progress_bar=False)
    elapsed = time.time() - t0

    best = study.best_trial
    print(f"\n  耗时: {elapsed:.0f}秒")
    print(f"  最优 Trial #{best.number}:")
    print(f"    综合得分:   {best.value:.4f}")
    m = best.user_attrs.get("metrics", {})
    print(f"    交易数:     {m.get('trades', 0)}")
    print(f"    胜率:       {m.get('win_rate', 0):.2f}%")
    print(f"    策略收益:   {m.get('total_return', 0):+.2f}%")
    print(f"    账户收益:   {m.get('account_return', 0):+.4f}%")
    print(f"    夏普:       {m.get('sharpe', 0):.2f}")
    print(f"    最大回撤:   {m.get('max_dd', 0):.4f}%")
    print(f"    盈亏比:     {m.get('pf', 0):.2f}")
    print(f"    最优参数:   {best.params}")

    # Top 3
    sorted_trials = sorted(
        [t for t in study.trials if t.value is not None],
        key=lambda t: t.value, reverse=True
    )[:3]
    print(f"\n  Top 3:")
    for t in sorted_trials:
        tm = t.user_attrs.get("metrics", {})
        print(f"    #{t.number}: score={t.value:.4f}, "
              f"ret={tm.get('total_return', 0):+.2f}%, "
              f"acc={tm.get('account_return', 0):+.4f}%, "
              f"sharpe={tm.get('sharpe', 0):.2f}, "
              f"win={tm.get('win_rate', 0):.1f}%")

    return best, study


# ════════════════════════════════════════════════════════════════════════════
# 持续上升判定
# ════════════════════════════════════════════════════════════════════════════

def judge_improvement(baseline: BacktestMetrics, best_metrics: dict, name: str) -> dict:
    """判定是否持续上升"""
    bl_ret = baseline.total_return_pct
    bl_acc = baseline.total_return_account_pct
    bl_sharpe = baseline.sharpe_ratio
    bl_dd = baseline.max_drawdown_pct_account

    opt_ret = best_metrics.get("total_return", 0)
    opt_acc = best_metrics.get("account_return", 0)
    opt_sharpe = best_metrics.get("sharpe", 0)
    opt_dd = best_metrics.get("max_dd", 0)

    verdict = {
        "name": name,
        "ret_up": opt_ret > bl_ret,
        "acc_up": opt_acc > bl_acc,
        "sharpe_ok": opt_sharpe >= bl_sharpe * 0.9,
        "dd_ok": opt_dd <= max(bl_dd * 1.5, 0.1),  # 允许1.5倍或0.1%下限
        "baseline_ret": bl_ret,
        "opt_ret": opt_ret,
        "baseline_acc": bl_acc,
        "opt_acc": opt_acc,
        "baseline_sharpe": bl_sharpe,
        "opt_sharpe": opt_sharpe,
    }
    verdict["pass"] = all([
        verdict["ret_up"],
        verdict["acc_up"],
        verdict["sharpe_ok"],
        verdict["dd_ok"],
    ])
    return verdict


# ════════════════════════════════════════════════════════════════════════════
# 落地验证：用已落地的精确参数验证组合效果
# ════════════════════════════════════════════════════════════════════════════

# 已落地参数（与代码中一致）
LANDED_PARAMS = {
    "A_confidence_thr": 0.7955,       # polling_trader.py A_CONFIDENCE_FLOOR
    "B_trailing_arm": 0.0508,          # classic_exit_system.py trailing_tp_arm_pct
    "B_trailing_retrace": 0.4668,      # classic_exit_system.py trailing_tp_retrace_ratio
    "C_position_size_pct": 0.20,       # .env DEFAULT_POSITION_PCT
    "D_min_hold_bars": 6,              # classic_exit_system.py min_hold_bars
    "E_max_reduce_count": 1,           # classic_exit_system.py max_reduce_count
}


def run_landed_combined():
    """用已落地的精确参数运行 A+B+C+D+E 组合回测"""
    config = make_baseline_config()
    # B项：trailing_tp 参数
    config.trailing_tp_arm_pct = LANDED_PARAMS["B_trailing_arm"]
    config.trailing_tp_retrace_ratio = LANDED_PARAMS["B_trailing_retrace"]

    system = ClassicExitSystem(config=config)
    all_results = []

    for symbol in SYMBOLS:
        klines = load_klines(symbol)
        trades = load_trades(symbol)
        if klines is None or trades is None:
            continue
        for _, row in trades.iterrows():
            # A项：confidence 硬性过滤
            conf = float(row.get("confidence", 1.0))
            if conf < LANDED_PARAMS["A_confidence_thr"]:
                continue
            # D项 + E项：min_hold_bars 保护期 + max_reduce_count 限制
            result = run_single_trade_min_hold(
                system, symbol, row, klines,
                min_hold_bars=LANDED_PARAMS["D_min_hold_bars"],
                max_reduce_count=LANDED_PARAMS["E_max_reduce_count"],
            )
            all_results.append(result)

    # C项：仓位比例
    metrics = compute_metrics_custom(all_results, LANDED_PARAMS["C_position_size_pct"])
    return metrics, all_results


def verify_landed():
    """落地验证：基线 vs 落地组合 对比"""
    print("=" * 70)
    print("  落地验证：A+B+C+D+E 组合效果对比")
    print("=" * 70)
    print(f"\n  已落地参数:")
    print(f"    A: confidence_thr      = {LANDED_PARAMS['A_confidence_thr']}")
    print(f"    B: trailing_arm_pct    = {LANDED_PARAMS['B_trailing_arm']}")
    print(f"    B: trailing_retrace    = {LANDED_PARAMS['B_trailing_retrace']}")
    print(f"    C: position_size_pct   = {LANDED_PARAMS['C_position_size_pct']}")
    print(f"    D: min_hold_bars       = {LANDED_PARAMS['D_min_hold_bars']}")
    print(f"    E: max_reduce_count    = {LANDED_PARAMS['E_max_reduce_count']}")

    # 基线
    print("\n" + "-" * 70)
    print("  [1/2] 基线回测（无A-E优化，仓位5%）")
    print("-" * 70)
    base_metrics, base_results = run_baseline()

    # 落地组合
    print("\n" + "-" * 70)
    print("  [2/2] 落地组合回测（A+B+C+D+E，仓位20%）")
    print("-" * 70)
    landed_metrics, landed_results = run_landed_combined()
    print(f"  交易数:     {landed_metrics.total_trades}")
    print(f"  胜率:       {landed_metrics.win_rate:.2f}%")
    print(f"  策略收益:   {landed_metrics.total_return_pct:.2f}%")
    print(f"  账户收益:   {landed_metrics.total_return_account_pct:.4f}%")
    print(f"  夏普:       {landed_metrics.sharpe_ratio:.2f}")
    print(f"  最大回撤:   {landed_metrics.max_drawdown_pct_account:.4f}%")
    print(f"  盈亏比:     {landed_metrics.profit_factor:.2f}")
    print(f"  平均持仓:   {landed_metrics.avg_hold_bars:.1f}bars")

    # 减仓次数分布
    reduce_dist = defaultdict(int)
    for r in landed_results:
        reduce_dist[r.reduce_count] += 1
    print(f"  减仓次数分布: {dict(sorted(reduce_dist.items()))}")

    # 对比
    print("\n" + "=" * 70)
    print("  对比汇总")
    print("=" * 70)
    print(f"\n  {'指标':<16} {'基线':>12} {'落地':>12} {'变化':>12} {'判定':<8}")
    print(f"  {'─' * 62}")

    def _cmp(base, landed, higher_better=True, fmt=".4f"):
        delta = landed - base
        if higher_better:
            ok = delta > 0
            arrow = "↑" if ok else ("→" if abs(delta) < 1e-9 else "↓")
        else:
            ok = delta < 0
            arrow = "↓" if ok else ("→" if abs(delta) < 1e-9 else "↑")
        verdict = "✓" if ok else "✗"
        return f"{delta:+{fmt}}", arrow, verdict

    # 交易数
    d_trades, a_trades, v_trades = _cmp(base_metrics.total_trades, landed_metrics.total_trades, higher_better=False, fmt="d")
    print(f"  {'交易数':<16} {base_metrics.total_trades:>12d} {landed_metrics.total_trades:>12d} {d_trades:>12} {v_trades}")

    # 胜率
    d_wr, a_wr, v_wr = _cmp(base_metrics.win_rate, landed_metrics.win_rate, fmt=".2f")
    print(f"  {'胜率(%)':<16} {base_metrics.win_rate:>12.2f} {landed_metrics.win_rate:>12.2f} {d_wr:>12} {v_wr}")

    # 策略收益
    d_sr, a_sr, v_sr = _cmp(base_metrics.total_return_pct, landed_metrics.total_return_pct, fmt=".2f")
    print(f"  {'策略收益(%)':<16} {base_metrics.total_return_pct:>12.2f} {landed_metrics.total_return_pct:>12.2f} {d_sr:>12} {v_sr}")

    # 账户收益
    d_ar, a_ar, v_ar = _cmp(base_metrics.total_return_account_pct, landed_metrics.total_return_account_pct, fmt=".4f")
    print(f"  {'账户收益(%)':<16} {base_metrics.total_return_account_pct:>12.4f} {landed_metrics.total_return_account_pct:>12.4f} {d_ar:>12} {v_ar}")

    # 夏普
    d_sh, a_sh, v_sh = _cmp(base_metrics.sharpe_ratio, landed_metrics.sharpe_ratio, fmt=".2f")
    print(f"  {'夏普':<16} {base_metrics.sharpe_ratio:>12.2f} {landed_metrics.sharpe_ratio:>12.2f} {d_sh:>12} {v_sh}")

    # 最大回撤
    d_dd, a_dd, v_dd = _cmp(base_metrics.max_drawdown_pct_account, landed_metrics.max_drawdown_pct_account, higher_better=False, fmt=".4f")
    print(f"  {'最大回撤(%)':<16} {base_metrics.max_drawdown_pct_account:>12.4f} {landed_metrics.max_drawdown_pct_account:>12.4f} {d_dd:>12} {v_dd}")

    # 盈亏比
    d_pf, a_pf, v_pf = _cmp(base_metrics.profit_factor, landed_metrics.profit_factor, fmt=".2f")
    print(f"  {'盈亏比':<16} {base_metrics.profit_factor:>12.2f} {landed_metrics.profit_factor:>12.2f} {d_pf:>12} {v_pf}")

    # 平均持仓
    d_hb, a_hb, v_hb = _cmp(base_metrics.avg_hold_bars, landed_metrics.avg_hold_bars, fmt=".1f")
    print(f"  {'平均持仓(bars)':<16} {base_metrics.avg_hold_bars:>12.1f} {landed_metrics.avg_hold_bars:>12.1f} {d_hb:>12} {v_hb}")

    # 总体判定
    checks = [
        ("策略收益↑", v_sr),
        ("账户收益↑", v_ar),
        ("夏普↑", v_sh),
        ("回撤↓", v_dd),
    ]
    passed = sum(1 for _, v in checks if v == "✓")
    print(f"\n  总体判定: {passed}/{len(checks)} 项通过")

    if passed == len(checks):
        print("  → ✓ 落地验证通过：所有指标均改善")
    elif passed >= len(checks) - 1:
        print("  → △ 基本通过：核心指标改善，1项需观察")
    else:
        print("  → ✗ 验证未通过：多项指标未改善，需复查参数")

    # 保存报告
    report = {
        "baseline": {
            "trades": base_metrics.total_trades,
            "win_rate": base_metrics.win_rate,
            "total_return_pct": base_metrics.total_return_pct,
            "total_return_account_pct": base_metrics.total_return_account_pct,
            "sharpe_ratio": base_metrics.sharpe_ratio,
            "max_drawdown_pct_account": base_metrics.max_drawdown_pct_account,
            "profit_factor": base_metrics.profit_factor,
            "avg_hold_bars": base_metrics.avg_hold_bars,
        },
        "landed": {
            "params": LANDED_PARAMS,
            "trades": landed_metrics.total_trades,
            "win_rate": landed_metrics.win_rate,
            "total_return_pct": landed_metrics.total_return_pct,
            "total_return_account_pct": landed_metrics.total_return_account_pct,
            "sharpe_ratio": landed_metrics.sharpe_ratio,
            "max_drawdown_pct_account": landed_metrics.max_drawdown_pct_account,
            "profit_factor": landed_metrics.profit_factor,
            "avg_hold_bars": landed_metrics.avg_hold_bars,
            "reduce_count_dist": dict(sorted(reduce_dist.items())),
        },
        "verdict": {
            "passed": passed,
            "total": len(checks),
            "checks": {name: v for name, v in checks},
        },
    }
    report_path = OUTPUT_DIR / "verify_landed_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  报告已保存: {report_path}")

    return 0 if passed >= len(checks) - 1 else 1


# ════════════════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════════════════

def main():
    # --verify 模式：用已落地参数验证组合效果（不运行贝叶斯寻优）
    if "--verify" in sys.argv:
        return verify_landed()

    N_TRIALS = int(os.environ.get("N_TRIALS", "40"))

    print("=" * 70)
    print("  A-E 五项优化独立贝叶斯验证")
    print(f"  每项 {N_TRIALS} trials | 评估口径: 收益↑ + 账户↑ + 夏普≥90% + 回撤≤150%")
    print("=" * 70)

    # 基线
    baseline_metrics, _ = run_baseline()

    results = {}

    # A项
    best_A, _ = run_optimization("A. confidence过滤", objective_A, N_TRIALS)
    verdict_A = judge_improvement(baseline_metrics, best_A.user_attrs.get("metrics", {}), "A")
    results["A"] = {"best": best_A, "verdict": verdict_A}

    # B项
    best_B, _ = run_optimization("B. 放大止盈空间", objective_B, N_TRIALS)
    verdict_B = judge_improvement(baseline_metrics, best_B.user_attrs.get("metrics", {}), "B")
    results["B"] = {"best": best_B, "verdict": verdict_B}

    # C项
    best_C, _ = run_optimization("C. 仓位管理", objective_C, N_TRIALS)
    verdict_C = judge_improvement(baseline_metrics, best_C.user_attrs.get("metrics", {}), "C")
    results["C"] = {"best": best_C, "verdict": verdict_C}

    # D项
    best_D, _ = run_optimization("D. min_hold保护", objective_D, N_TRIALS)
    verdict_D = judge_improvement(baseline_metrics, best_D.user_attrs.get("metrics", {}), "D")
    results["D"] = {"best": best_D, "verdict": verdict_D}

    # E项
    best_E, _ = run_optimization("E. max_reduce_count", objective_E, N_TRIALS)
    verdict_E = judge_improvement(baseline_metrics, best_E.user_attrs.get("metrics", {}), "E")
    results["E"] = {"best": best_E, "verdict": verdict_E}

    # 汇总报告
    print("\n" + "=" * 70)
    print("  落地决策汇总报告")
    print("=" * 70)
    print(f"\n  基线: 策略收益={baseline_metrics.total_return_pct:.2f}%, "
          f"账户收益={baseline_metrics.total_return_account_pct:.4f}%, "
          f"夏普={baseline_metrics.sharpe_ratio:.2f}, "
          f"回撤={baseline_metrics.max_drawdown_pct_account:.4f}%")

    print(f"\n  {'项':<4} {'策略收益':>10} {'账户收益':>10} {'夏普':>8} {'回撤':>8} {'参数':<30} {'判定':<6}")
    print(f"  {'─' * 80}")
    for k in ["A", "B", "C", "D", "E"]:
        v = results[k]["verdict"]
        best = results[k]["best"]
        params_str = ", ".join(f"{pk}={pv:.4f}" for pk, pv in best.params.items())
        verdict_str = "✓通过" if v["pass"] else "✗不通过"
        print(f"  {k:<4} {v['opt_ret']:>+9.2f}% {v['opt_acc']:>+9.4f}% "
              f"{v['opt_sharpe']:>8.2f} {v.get('opt_dd', 0):>7.4f}% "
              f"{params_str:<30} {verdict_str:<6}")

    print(f"\n  判定明细:")
    for k in ["A", "B", "C", "D", "E"]:
        v = results[k]["verdict"]
        print(f"    {k}: 策略收益{'↑' if v['ret_up'] else '↓'} "
              f"账户收益{'↑' if v['acc_up'] else '↓'} "
              f"夏普{'✓' if v['sharpe_ok'] else '✗'} "
              f"回撤{'✓' if v['dd_ok'] else '✗'} "
              f"→ {'落地' if v['pass'] else '不落地'}")

    # 保存报告
    report = {
        "baseline": {
            "total_return_pct": baseline_metrics.total_return_pct,
            "total_return_account_pct": baseline_metrics.total_return_account_pct,
            "sharpe_ratio": baseline_metrics.sharpe_ratio,
            "max_drawdown_pct_account": baseline_metrics.max_drawdown_pct_account,
            "win_rate": baseline_metrics.win_rate,
            "profit_factor": baseline_metrics.profit_factor,
        },
        "optimizations": {},
    }
    for k in ["A", "B", "C", "D", "E"]:
        v = results[k]["verdict"]
        best = results[k]["best"]
        report["optimizations"][k] = {
            "best_params": best.params,
            "best_score": best.value,
            "metrics": best.user_attrs.get("metrics", {}),
            "verdict": v,
        }
    report_path = OUTPUT_DIR / "optimize_a_e_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  报告已保存: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
