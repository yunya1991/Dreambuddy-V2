#!/usr/bin/env python3
"""
ClassicExitSystem 回测 + 贝叶斯参数寻优
==========================================

流程：
1. 读取历史交易记录（data/bcrm2_phase0/trades_*.csv）作为开仓点
2. 用 ClassicExitSystem.evaluate_full 重新决策每笔交易的离场
3. 对比三组参数：
   - 基线A（修复前）：l0_max_loss=-0.05, l2_close=0.75, cooldown=30
   - 基线B（修复后）：l0_max_loss=-0.15, l2_close=0.65, cooldown=10
   - 贝叶斯寻优后：Optuna 搜索 ExitConfig 最优参数
4. 择优选用
"""
import sys
import os

# 解决 inspect.py 冲突：scripts/memory_l4/inspect.py 会覆盖标准库 inspect
# 必须在任何其他导入之前，从 sys.path 移除脚本目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR in sys.path:
    sys.path.remove(SCRIPT_DIR)

import json
import time
import math
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from copy import deepcopy

import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)

from scripts.memory_l4.classic_exit_system import (
    ClassicExitSystem, PositionState, ExitAction, ExitConfig, ExitPriority,
)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# ── 数据路径 ────────────────────────────────────────────────────────────────
TRADES_DIR = os.path.join(PROJECT_ROOT, "data", "bcrm2_phase0")
KLINES_DIR = os.path.join(PROJECT_ROOT, "scripts", "data", "klines")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "backtest")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SYMBOLS = ["BTC", "ETH", "SOL", "UNI"]
LEVERAGE = 3.0
FEE_PCT = 0.001  # 单边手续费 0.1%

# ── 参数组定义 ──────────────────────────────────────────────────────────────

# 基线A（修复前参数）
CONFIG_BEFORE = ExitConfig(
    l0_max_loss_pct=-0.05,
    l0_risk_gate_cooldown_min=30.0,
    l2_close_threshold=0.75,
    l2_reduce_threshold=0.55,
    tb_sl_atr_mult=1.5,
    tb_tp_atr_mult=3.0,
    trailing_arm_profit_pct=0.06,
    trailing_retrace_pct=0.03,
    l2_raise_tp_value_thr=0.65,
    l2_raise_tp_risk_thr=0.30,
)

# 基线B（修复后参数，即当前代码默认值）
CONFIG_AFTER = ExitConfig(
    l0_max_loss_pct=-0.15,
    l0_risk_gate_cooldown_min=10.0,
    l2_close_threshold=0.65,
    l2_reduce_threshold=0.55,
    tb_sl_atr_mult=1.5,
    tb_tp_atr_mult=3.0,
    trailing_arm_profit_pct=0.06,
    trailing_retrace_pct=0.03,
    l2_raise_tp_value_thr=0.65,
    l2_raise_tp_risk_thr=0.30,
)


# ── 数据加载 ────────────────────────────────────────────────────────────────

_KLINE_CACHE: Dict[str, pd.DataFrame] = {}
_TRADE_CACHE: Dict[str, pd.DataFrame] = {}


def load_klines(symbol: str) -> Optional[pd.DataFrame]:
    if symbol not in _KLINE_CACHE:
        path = os.path.join(KLINES_DIR, f"{symbol}_1H.csv")
        if not os.path.exists(path):
            _KLINE_CACHE[symbol] = None
            return None
        df = pd.read_csv(path)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df.set_index("timestamp", inplace=True)
        _KLINE_CACHE[symbol] = df
    return _KLINE_CACHE[symbol]


def load_trades(symbol: str) -> Optional[pd.DataFrame]:
    if symbol not in _TRADE_CACHE:
        path = os.path.join(TRADES_DIR, f"trades_{symbol}_1H.csv")
        if not os.path.exists(path):
            _TRADE_CACHE[symbol] = None
            return None
        df = pd.read_csv(path)
        df["entry_time"] = pd.to_datetime(df["entry_time"])
        df["exit_time"] = pd.to_datetime(df["exit_time"])
        _TRADE_CACHE[symbol] = df
    return _TRADE_CACHE[symbol]


# ── 回测引擎 ────────────────────────────────────────────────────────────────

@dataclass
class TradeResult:
    """单笔交易回测结果"""
    symbol: str = ""
    direction: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    entry_time: pd.Timestamp = None
    exit_time: pd.Timestamp = None
    entry_time_str: str = ""
    exit_time_str: str = ""
    pnl_pct: float = 0.0          # 含杠杆的有效收益率
    pnl_raw_pct: float = 0.0      # 不含杠杆的原始收益率
    hold_bars: int = 0
    max_dd_pct_raw: float = 0.0
    exit_reason: str = ""
    original_exit_reason: str = ""
    original_pnl_pct: float = 0.0
    leverage: float = 1.0
    reduce_count: int = 0         # 减仓次数
    atr_pct_at_entry: float = 0.0
    regime: str = "trend"


@dataclass
class BacktestMetrics:
    """回测汇总指标"""
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0     # 累计收益率（含杠杆，简单加总）
    total_return_account_pct: float = 0.0  # 账户权益曲线总收益
    avg_return_pct: float = 0.0       # 平均单笔收益率
    sharpe_ratio: float = 0.0
    max_drawdown_pct_wrong: float = 0.0   # 错误算法：累加pnl
    max_drawdown_pct_account: float = 0.0 # 正确算法：账户权益曲线
    profit_factor: float = 0.0
    avg_hold_bars: float = 0.0
    total_fee_pct: float = 0.0
    exit_reason_dist: Dict[str, int] = field(default_factory=dict)
    symbol_metrics: Dict[str, dict] = field(default_factory=dict)
    regime_metrics: Dict[str, dict] = field(default_factory=dict)
    atr_bucket_metrics: Dict[str, dict] = field(default_factory=dict)


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
    """基于20根K线价格走势推断市态：uptrend/downtrend/trend/chop"""
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


def run_single_trade(
    system: ClassicExitSystem,
    symbol: str,
    row: pd.Series,
    klines: pd.DataFrame,
    leverage: float = LEVERAGE,
) -> TradeResult:
    """对单笔交易运行 ClassicExitSystem 离场决策"""
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

    # 入场时 ATR（用于后续按 ATR 分组分析）
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

    # 入场前市态：用 entry_time 之前（含）的 21 根 K 线推断
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

        # 市态推断：窗口不足 21 根时使用入场前市态
        closes_21 = kline_slice["close"].iloc[max(0, i - 20):i + 1].values
        regime = infer_regime(closes_21) if len(closes_21) >= 21 else regime_at_entry

        # 必须传入 now_ts，否则 inflight cooldown 会锁死后续决策
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


def run_backtest(config: ExitConfig, symbols: List[str] = None) -> Tuple[BacktestMetrics, List[TradeResult]]:
    """运行完整回测"""
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

    # 计算汇总指标
    metrics = compute_metrics(all_results)
    return metrics, all_results


def compute_account_equity(results: List[TradeResult], initial_capital: float = 100.0,
                           position_size_pct: float = 0.05) -> Tuple[float, float, pd.Series]:
    """
    按账户权益曲线计算真实总收益和最大回撤。
    假设每笔交易分配初始资金的固定比例作为名义本金，多币种并行持仓。
    """
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


def compute_metrics(results: List[TradeResult]) -> BacktestMetrics:
    """计算回测指标"""
    if not results:
        return BacktestMetrics()

    n = len(results)
    wins = [r for r in results if r.pnl_pct > 0]
    losses = [r for r in results if r.pnl_pct <= 0]

    pnls = [r.pnl_pct for r in results]
    total_return = sum(pnls)
    avg_return = total_return / n

    # Sharpe（P0修正：用日收益序列年化，sqrt(252)）
    if len(results) > 0:
        # 按平仓日期聚合日收益
        daily_returns = {}
        for r in results:
            day_str = (r.exit_time_str or "")[:10]
            if not day_str:
                day_str = "unknown"
            daily_returns[day_str] = daily_returns.get(day_str, 0.0) + r.pnl_pct
        daily_pnls = list(daily_returns.values())
        if len(daily_pnls) > 1 and np.std(daily_pnls) > 0:
            sharpe = np.mean(daily_pnls) / np.std(daily_pnls) * math.sqrt(252)
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    # 错误算法：累加 pnl 的回撤
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    drawdown = peak - cum
    max_dd_wrong = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

    # 正确算法：账户权益曲线
    total_ret_account, max_dd_account, _ = compute_account_equity(results)

    # 盈亏比
    gross_profit = sum(r.pnl_pct for r in wins)
    gross_loss = abs(sum(r.pnl_pct for r in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # exit_reason 分布
    reason_dist = {}
    for r in results:
        reason = r.exit_reason.split("(")[0] if "(" in r.exit_reason else r.exit_reason
        reason_dist[reason] = reason_dist.get(reason, 0) + 1

    # 按币种
    symbol_metrics = {}
    for sym in SYMBOLS:
        rs = [r for r in results if r.symbol == sym]
        if rs:
            sym_pnls = [r.pnl_pct for r in rs]
            symbol_metrics[sym] = {
                "trades": len(rs),
                "win_rate": sum(1 for p in sym_pnls if p > 0) / len(rs) * 100,
                "total_return": sum(sym_pnls),
                "avg_atr_pct": np.mean([r.atr_pct_at_entry for r in rs]) * 100,
                "avg_hold_bars": np.mean([r.hold_bars for r in rs]),
                "max_dd_raw": max(r.max_dd_pct_raw for r in rs) * 100 if hasattr(r, 'max_dd_pct_raw') else 0.0,
            }
            # P0修正：夏普按日收益序列年化
            sym_daily = {}
            for r in rs:
                d = (r.exit_time_str or "")[:10] or "unknown"
                sym_daily[d] = sym_daily.get(d, 0.0) + r.pnl_pct
            sym_dp = list(sym_daily.values())
            symbol_metrics[sym]["sharpe"] = np.mean(sym_dp) / np.std(sym_dp) * math.sqrt(252) if len(sym_dp) > 1 and np.std(sym_dp) > 0 else 0.0

    # 按市态
    regime_metrics = {}
    for reg in ["uptrend", "downtrend", "trend", "chop"]:
        rs = [r for r in results if r.regime == reg]
        if rs:
            reg_pnls = [r.pnl_pct for r in rs]
            regime_metrics[reg] = {
                "trades": len(rs),
                "win_rate": sum(1 for p in reg_pnls if p > 0) / len(rs) * 100,
                "total_return": sum(reg_pnls),
                "avg_return": np.mean(reg_pnls),
                "avg_hold_bars": np.mean([r.hold_bars for r in rs]),
            }

    # 按 ATR 分组：低波动 / 中波动 / 高波动
    atrs = [r.atr_pct_at_entry for r in results]
    atr_low = np.percentile(atrs, 33)
    atr_high = np.percentile(atrs, 67)
    atr_bucket_metrics = {}
    for label, cond in [
        ("low_atr", lambda r: r.atr_pct_at_entry <= atr_low),
        ("mid_atr", lambda r: atr_low < r.atr_pct_at_entry <= atr_high),
        ("high_atr", lambda r: r.atr_pct_at_entry > atr_high),
    ]:
        rs = [r for r in results if cond(r)]
        if rs:
            b_pnls = [r.pnl_pct for r in rs]
            atr_bucket_metrics[label] = {
                "trades": len(rs),
                "win_rate": sum(1 for p in b_pnls if p > 0) / len(rs) * 100,
                "total_return": sum(b_pnls),
                "avg_return": np.mean(b_pnls),
                "avg_atr_pct": np.mean([r.atr_pct_at_entry for r in rs]) * 100,
                "avg_hold_bars": np.mean([r.hold_bars for r in rs]),
            }

    return BacktestMetrics(
        total_trades=n,
        win_trades=len(wins),
        loss_trades=len(losses),
        win_rate=len(wins) / n * 100,
        total_return_pct=total_return,
        total_return_account_pct=total_ret_account,
        avg_return_pct=avg_return,
        sharpe_ratio=sharpe,
        max_drawdown_pct_wrong=max_dd_wrong,
        max_drawdown_pct_account=max_dd_account,
        profit_factor=pf,
        avg_hold_bars=np.mean([r.hold_bars for r in results]),
        total_fee_pct=sum(FEE_PCT * 2 * (1 + r.reduce_count) for r in results) * 100,
        exit_reason_dist=reason_dist,
        symbol_metrics=symbol_metrics,
        regime_metrics=regime_metrics,
        atr_bucket_metrics=atr_bucket_metrics,
    )


def print_metrics(name: str, metrics: BacktestMetrics, results: List[TradeResult]):
    """打印回测指标"""
    print(f"\n  {'─'*60}")
    print(f"  {name}")
    print(f"  {'─'*60}")
    print(f"    总交易数:     {metrics.total_trades}")
    print(f"    胜率:         {metrics.win_rate:.1f}%  ({metrics.win_trades}胜 / {metrics.loss_trades}负)")
    print(f"    总收益率(加总): {metrics.total_return_pct:+.2f}% (含杠杆{LEVERAGE}x)")
    print(f"    总收益率(账户): {metrics.total_return_account_pct:+.2f}%")
    print(f"    平均单笔:     {metrics.avg_return_pct:+.2f}%")
    print(f"    夏普比率:     {metrics.sharpe_ratio:.2f}")
    print(f"    最大回撤(错误): {metrics.max_drawdown_pct_wrong:.2f}%")
    print(f"    最大回撤(账户): {metrics.max_drawdown_pct_account:.2f}%")
    print(f"    盈亏比:       {metrics.profit_factor:.2f}")
    print(f"    平均持仓:     {metrics.avg_hold_bars:.1f} 根K线 ({metrics.avg_hold_bars:.1f}h)")
    print(f"    总手续费:     {metrics.total_fee_pct:.2f}%")
    print(f"    离场原因分布:")
    for reason, count in sorted(metrics.exit_reason_dist.items(), key=lambda x: -x[1]):
        pct = count / metrics.total_trades * 100
        print(f"      {reason:30s}: {count:3d} ({pct:.1f}%)")

    # 按币种
    if metrics.symbol_metrics:
        print(f"\n    [按币种分析]")
        print(f"    {'币种':<6} {'交易数':>8} {'胜率%':>8} {'总收益%':>10} {'夏普':>8} {'入场ATR%':>10} {'平均持仓h':>10}")
        for sym, m in metrics.symbol_metrics.items():
            print(f"    {sym:<6} {m['trades']:>8} {m['win_rate']:>8.1f} {m['total_return']:>+10.2f} {m['sharpe']:>8.2f} {m['avg_atr_pct']:>10.2f} {m['avg_hold_bars']:>10.1f}")

    # 按市态
    if metrics.regime_metrics:
        print(f"\n    [按市态分析]")
        print(f"    {'市态':<12} {'交易数':>8} {'胜率%':>8} {'总收益%':>10} {'平均收益%':>10} {'平均持仓h':>10}")
        for reg, m in metrics.regime_metrics.items():
            print(f"    {reg:<12} {m['trades']:>8} {m['win_rate']:>8.1f} {m['total_return']:>+10.2f} {m['avg_return']:>+10.2f} {m['avg_hold_bars']:>10.1f}")

    # 按 ATR 分组
    if metrics.atr_bucket_metrics:
        print(f"\n    [按ATR波动率分组]")
        print(f"    {'ATR分组':<12} {'交易数':>8} {'胜率%':>8} {'总收益%':>10} {'平均收益%':>10} {'平均ATR%':>10} {'平均持仓h':>10}")
        for label, m in metrics.atr_bucket_metrics.items():
            print(f"    {label:<12} {m['trades']:>8} {m['win_rate']:>8.1f} {m['total_return']:>+10.2f} {m['avg_return']:>+10.2f} {m['avg_atr_pct']:>10.2f} {m['avg_hold_bars']:>10.1f}")

    # 与原始交易对比
    orig_pnls = [r.original_pnl_pct for r in results]
    orig_total = sum(orig_pnls)
    orig_wins = sum(1 for p in orig_pnls if p > 0)
    print(f"\n  {'─'*60}")
    print(f"    [原始BCRM系统对比]")
    print(f"    原始总收益:   {orig_total:+.2f}%")
    print(f"    原始胜率:     {orig_wins/len(orig_pnls)*100:.1f}%")
    print(f"    优化后收益:   {metrics.total_return_pct:+.2f}%")
    print(f"    收益改善:     {metrics.total_return_pct - orig_total:+.2f}%")


# ── 贝叶斯优化 ──────────────────────────────────────────────────────────────

def create_config_from_trial(trial) -> ExitConfig:
    """从 Optuna trial 构造 ExitConfig"""
    return ExitConfig(
        # L0 硬退出
        l0_max_loss_pct=trial.suggest_float("l0_max_loss_pct", -0.25, -0.08),
        l0_risk_gate_cooldown_min=trial.suggest_float("l0_risk_gate_cooldown_min", 5.0, 20.0),
        # L1/L2
        l2_close_threshold=trial.suggest_float("l2_close_threshold", 0.55, 0.75),
        l2_reduce_threshold=trial.suggest_float("l2_reduce_threshold", 0.45, 0.62),
        # Triple Barrier
        tb_sl_atr_mult=trial.suggest_float("tb_sl_atr_mult", 1.0, 2.5),
        tb_tp_atr_mult=trial.suggest_float("tb_tp_atr_mult", 2.0, 4.5),
        # Trailing
        trailing_arm_profit_pct=trial.suggest_float("trailing_arm_profit_pct", 0.03, 0.10),
        trailing_retrace_pct=trial.suggest_float("trailing_retrace_pct", 0.02, 0.05),
        # RAISE_TP
        l2_raise_tp_value_thr=trial.suggest_float("l2_raise_tp_value_thr", 0.55, 0.80),
        l2_raise_tp_risk_thr=trial.suggest_float("l2_raise_tp_risk_thr", 0.20, 0.40),
    )


def objective(trial):
    """Optuna 目标函数：最大化综合得分"""
    config = create_config_from_trial(trial)
    metrics, _ = run_backtest(config)

    # 综合得分：夏普 + 收益 - 回撤惩罚（使用账户权益曲线口径）
    score = metrics.sharpe_ratio + 0.01 * metrics.total_return_pct - 0.05 * metrics.max_drawdown_pct_account

    trial.set_user_attr("win_rate", metrics.win_rate)
    trial.set_user_attr("total_return", metrics.total_return_pct)
    trial.set_user_attr("sharpe", metrics.sharpe_ratio)
    trial.set_user_attr("max_drawdown", metrics.max_drawdown_pct_account)
    trial.set_user_attr("profit_factor", metrics.profit_factor)
    trial.set_user_attr("total_trades", metrics.total_trades)

    if trial.number % 5 == 0:
        print(f"    Trial #{trial.number}: score={score:.4f}, "
              f"return={metrics.total_return_pct:+.1f}%, "
              f"sharpe={metrics.sharpe_ratio:.2f}, "
              f"win={metrics.win_rate:.1f}%, "
              f"dd={metrics.max_drawdown_pct_account:.1f}%", flush=True)

    return score


def run_bayesian_optimize(n_trials: int = 40) -> Tuple[ExitConfig, dict]:
    """运行贝叶斯优化"""
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    print(f"\n  [贝叶斯优化] 开始搜索（{n_trials} trials）...")
    print(f"  搜索空间：10 个 ExitConfig 关键参数")
    print(f"  目标函数：sharpe + 0.01*return - 0.05*drawdown")

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    t0 = time.time()
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    elapsed = time.time() - t0

    best = study.best_trial
    print(f"\n  优化完成！耗时: {elapsed:.0f}秒")
    print(f"\n  最优 Trial #{best.number}:")
    print(f"    综合得分: {best.value:.4f}")
    print(f"    收益率:   {best.user_attrs.get('total_return', 0):+.2f}%")
    print(f"    夏普:     {best.user_attrs.get('sharpe', 0):.2f}")
    print(f"    胜率:     {best.user_attrs.get('win_rate', 0):.1f}%")
    print(f"    回撤:     {best.user_attrs.get('max_drawdown', 0):.2f}%")
    print(f"    盈亏比:   {best.user_attrs.get('profit_factor', 0):.2f}")

    print(f"\n  最优参数：")
    best_config = ExitConfig()
    for k, v in best.params.items():
        setattr(best_config, k, v)
        print(f"    {k}: {v:.4f}")

    # Top 5
    print(f"\n  Top 5 试验：")
    sorted_trials = sorted(
        [t for t in study.trials if t.value is not None],
        key=lambda t: t.value, reverse=True
    )[:5]
    for t in sorted_trials:
        print(f"    #{t.number}: score={t.value:.4f}, "
              f"return={t.user_attrs.get('total_return', 0):+.1f}%, "
              f"sharpe={t.user_attrs.get('sharpe', 0):.2f}, "
              f"win={t.user_attrs.get('win_rate', 0):.1f}%")

    return best_config, dict(best.params)


# ── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  ClassicExitSystem 回测 + 贝叶斯参数寻优")
    print("=" * 70)
    print(f"  币种: {SYMBOLS}")
    print(f"  杠杆: {LEVERAGE}x")
    print(f"  手续费: {FEE_PCT*100}%/边")

    # 加载数据
    print(f"\n  [数据加载]")
    for symbol in SYMBOLS:
        klines = load_klines(symbol)
        trades = load_trades(symbol)
        if klines is not None and trades is not None:
            print(f"    {symbol}: {len(trades)} 笔交易, {len(klines)} 根K线, "
                  f"范围 {klines.index[0]} ~ {klines.index[-1]}")

    # ── 1. 基线A（修复前）回测 ──
    print(f"\n  [基线A] 修复前参数回测...")
    print(f"    l0_max_loss=-0.05, l2_close=0.75, cooldown=30min")
    t0 = time.time()
    metrics_a, results_a = run_backtest(CONFIG_BEFORE)
    print(f"    耗时: {time.time()-t0:.0f}秒")
    print_metrics("基线A（修复前参数）", metrics_a, results_a)

    # ── 2. 基线B（修复后）回测 ──
    print(f"\n  [基线B] 修复后参数回测...")
    print(f"    l0_max_loss=-0.15, l2_close=0.65, cooldown=10min")
    t0 = time.time()
    metrics_b, results_b = run_backtest(CONFIG_AFTER)
    print(f"    耗时: {time.time()-t0:.0f}秒")
    print_metrics("基线B（修复后参数）", metrics_b, results_b)

    # ── 3. 贝叶斯寻优 ──
    best_config, best_params = run_bayesian_optimize(n_trials=25)

    # ── 4. 寻优后参数回测 ──
    print(f"\n  [寻优后] 贝叶斯最优参数回测...")
    t0 = time.time()
    metrics_opt, results_opt = run_backtest(best_config)
    print(f"    耗时: {time.time()-t0:.0f}秒")
    print_metrics("寻优后参数", metrics_opt, results_opt)

    # ── 5. 三组对比 ──
    print(f"\n\n{'='*70}")
    print(f"  三组参数对比汇总")
    print(f"{'='*70}")
    print(f"  {'指标':<16} {'基线A(修复前)':>16} {'基线B(修复后)':>16} {'贝叶斯寻优':>16}")
    print(f"  {'─'*70}")
    print(f"  {'总收益率%':<16} {metrics_a.total_return_pct:>16.2f} {metrics_b.total_return_pct:>16.2f} {metrics_opt.total_return_pct:>16.2f}")
    print(f"  {'胜率%':<16} {metrics_a.win_rate:>16.1f} {metrics_b.win_rate:>16.1f} {metrics_opt.win_rate:>16.1f}")
    print(f"  {'夏普比率':<16} {metrics_a.sharpe_ratio:>16.2f} {metrics_b.sharpe_ratio:>16.2f} {metrics_opt.sharpe_ratio:>16.2f}")
    print(f"  {'最大回撤%(账户)':<16} {metrics_a.max_drawdown_pct_account:>16.2f} {metrics_b.max_drawdown_pct_account:>16.2f} {metrics_opt.max_drawdown_pct_account:>16.2f}")
    print(f"  {'盈亏比':<16} {metrics_a.profit_factor:>16.2f} {metrics_b.profit_factor:>16.2f} {metrics_opt.profit_factor:>16.2f}")
    print(f"  {'平均持仓h':<16} {metrics_a.avg_hold_bars:>16.1f} {metrics_b.avg_hold_bars:>16.1f} {metrics_opt.avg_hold_bars:>16.1f}")

    # 原始BCRM对比
    orig_pnls = [r.original_pnl_pct for r in results_a]
    orig_total = sum(orig_pnls)
    orig_wins = sum(1 for p in orig_pnls if p > 0) / len(orig_pnls) * 100
    print(f"  {'─'*70}")
    print(f"  {'原始BCRM收益%':<16} {orig_total:>16.2f}")
    print(f"  {'原始BCRM胜率%':<16} {orig_wins:>16.1f}")

    # ── 6. 择优选用 ──
    print(f"\n  [择优决策]")

    candidates = [
        ("基线A(修复前)", metrics_a, CONFIG_BEFORE),
        ("基线B(修复后)", metrics_b, CONFIG_AFTER),
        ("贝叶斯寻优", metrics_opt, best_config),
    ]

    # 综合评分：夏普 + 收益 - 回撤（账户口径）
    def score(m):
        return m.sharpe_ratio + 0.01 * m.total_return_pct - 0.05 * m.max_drawdown_pct_account

    best_name, best_m, best_cfg = max(candidates, key=lambda x: score(x[1]))
    print(f"    综合评分公式: sharpe + 0.01*return - 0.05*drawdown")
    for name, m, _ in candidates:
        s = score(m)
        marker = " ◀ 最优" if name == best_name else ""
        print(f"    {name:<16}: {s:+.4f}{marker}")

    print(f"\n    >>> 择优选用: {best_name}")

    # 保存结果
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "leverage": LEVERAGE,
        "symbols": SYMBOLS,
        "baseline_a": {
            "name": "修复前参数",
            "config": {"l0_max_loss_pct": -0.05, "l2_close_threshold": 0.75, "l0_risk_gate_cooldown_min": 30.0},
            "metrics": {
                "total_return_pct": metrics_a.total_return_pct,
                "win_rate": metrics_a.win_rate,
                "sharpe_ratio": metrics_a.sharpe_ratio,
                "max_drawdown_pct": metrics_a.max_drawdown_pct_account,
                "profit_factor": metrics_a.profit_factor,
            },
        },
        "baseline_b": {
            "name": "修复后参数",
            "config": {"l0_max_loss_pct": -0.15, "l2_close_threshold": 0.65, "l0_risk_gate_cooldown_min": 10.0},
            "metrics": {
                "total_return_pct": metrics_b.total_return_pct,
                "win_rate": metrics_b.win_rate,
                "sharpe_ratio": metrics_b.sharpe_ratio,
                "max_drawdown_pct": metrics_b.max_drawdown_pct_account,
                "profit_factor": metrics_b.profit_factor,
            },
        },
        "bayesian_optimal": {
            "name": "贝叶斯寻优",
            "params": best_params,
            "metrics": {
                "total_return_pct": metrics_opt.total_return_pct,
                "win_rate": metrics_opt.win_rate,
                "sharpe_ratio": metrics_opt.sharpe_ratio,
                "max_drawdown_pct": metrics_opt.max_drawdown_pct_account,
                "profit_factor": metrics_opt.profit_factor,
            },
        },
        "selected": best_name,
        "original_bcrm": {"total_return_pct": orig_total, "win_rate": orig_wins},
    }

    output_path = os.path.join(OUTPUT_DIR, "exit_optimize_result.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  结果已保存: {output_path}")

    return best_name, best_cfg


if __name__ == "__main__":
    main()
