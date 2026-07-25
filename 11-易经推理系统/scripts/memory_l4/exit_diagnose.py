#!/usr/bin/env python3
"""
ClassicExitSystem 回测诊断脚本
- 诊断为什么 L0 时间硬退出未触发
- 按币种/市态/ATR 分析离场效果
- 用账户权益曲线重新计算真实回撤
"""
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR in sys.path:
    sys.path.remove(SCRIPT_DIR)

import json
import math
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
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

TRADES_DIR = os.path.join(PROJECT_ROOT, "data", "bcrm2_phase0")
KLINES_DIR = os.path.join(PROJECT_ROOT, "scripts", "data", "klines")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "backtest")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SYMBOLS = ["BTC", "ETH", "SOL", "UNI"]
LEVERAGE = 3.0
FEE_PCT = 0.001

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


@dataclass
class TradeResult:
    symbol: str = ""
    direction: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    entry_time: pd.Timestamp = None
    exit_time: pd.Timestamp = None
    pnl_pct: float = 0.0
    pnl_raw_pct: float = 0.0
    hold_bars: int = 0
    max_dd_pct_raw: float = 0.0
    max_dd_pct_eff: float = 0.0
    mfe_pct_raw: float = 0.0
    exit_reason: str = ""
    original_pnl_pct: float = 0.0
    original_exit_reason: str = ""
    leverage: float = 1.0
    reduce_count: int = 0
    atr_pct_at_entry: float = 0.0
    avg_atr_pct: float = 0.0
    regime: str = "trend"


@dataclass
class BacktestMetrics:
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0
    avg_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct_wrong: float = 0.0  # 错误算法：累加pnl
    max_drawdown_pct_account: float = 0.0  # 正确算法：账户权益曲线
    profit_factor: float = 0.0
    avg_hold_bars: float = 0.0
    exit_reason_dist: Dict[str, int] = field(default_factory=dict)
    symbol_metrics: Dict[str, dict] = field(default_factory=dict)
    regime_metrics: Dict[str, dict] = field(default_factory=dict)


def infer_regime(closes: np.ndarray, atr_pct: float) -> str:
    """基于趋势强度和波动率推断市态"""
    if len(closes) < 21:
        return "trend"
    # EMA 计算
    ema = closes[0]
    k = 2.0 / 21.0
    for p in closes:
        ema = p * k + ema * (1 - k)
    ret_20 = (closes[-1] - closes[-21]) / closes[-21]
    # 使用更合理的价格波动区间而非对数收益年化波动率
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


def compute_atr_pct(highs, lows, closes) -> float:
    if len(highs) < 2:
        return 0.02
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    atr = np.mean(trs[-14:]) if len(trs) >= 14 else np.mean(trs)
    return atr / closes[-1] if closes[-1] > 0 else 0.02


def run_single_trade(system: ClassicExitSystem, symbol: str, row: pd.Series, klines: pd.DataFrame,
                     verbose: bool = False) -> TradeResult:
    direction = row["direction"]
    entry_price = float(row["entry_price"])
    entry_time = row["entry_time"]
    original_exit_reason = str(row.get("exit_reason", ""))
    original_pnl = float(row.get("pnl_pct", 0.0))
    side = "long" if direction.upper() in ("LONG", "BUY") else "short"

    kline_slice = klines[klines.index >= entry_time]
    if len(kline_slice) < 5:
        return TradeResult(symbol=symbol, direction=direction, entry_price=entry_price,
                           exit_price=entry_price, entry_time=entry_time, exit_time=entry_time,
                           original_pnl_pct=original_pnl, original_exit_reason=original_exit_reason)

    current_price = float(kline_slice.iloc[0]["close"])
    # 入场时 ATR
    atr_entry = 0.02
    if len(klines.loc[:entry_time]) >= 15:
        pre = klines.loc[:entry_time].iloc[-15:]
        atr_entry = compute_atr_pct(pre["high"].values, pre["low"].values, pre["close"].values)

    pos = PositionState(
        coin=f"{symbol}_{entry_time.strftime('%m%d')}",
        side=side,
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=0.0,
        unrealized_pnl_pct=(current_price - entry_price) / entry_price if side == "long" else (entry_price - current_price) / entry_price,
        leverage=LEVERAGE,
        atr_pct=atr_entry,
        mfe_pnl_pct=0.0,
        max_dd_pct=0.0,
        entry_ts=int(entry_time.timestamp()),
        trailing_armed=False,
        trailing_stop_price=0.0,
    )

    mfe = 0.0
    max_dd = 0.0
    atrs = [atr_entry]
    exit_price = current_price
    exit_time = kline_slice.index[0]
    exit_reason = "data_end"
    reduce_count = 0
    remaining_frac = 1.0
    realized_pnl = 0.0
    bars_held = 0
    regime_at_entry = "trend"

    for i in range(1, len(kline_slice)):
        bar = kline_slice.iloc[i]
        current_price = float(bar["close"])
        bar_time = kline_slice.index[i]
        age_sec = (bar_time - entry_time).total_seconds()
        pos.current_price = current_price
        pos.position_age_sec = age_sec

        raw_pnl = (current_price - entry_price) / entry_price if side == "long" else (entry_price - current_price) / entry_price
        pos.unrealized_pnl_pct = raw_pnl
        if raw_pnl > mfe: mfe = raw_pnl
        pos.mfe_pnl_pct = mfe
        cur_dd = max(0.0, -raw_pnl)
        if cur_dd > max_dd: max_dd = cur_dd
        pos.max_dd_pct = max_dd

        recent = kline_slice.iloc[max(0, i - 14):i + 1]
        atr_pct = compute_atr_pct(recent["high"].values, recent["low"].values, recent["close"].values)
        pos.atr_pct = atr_pct
        atrs.append(atr_pct)

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
        regime = infer_regime(closes_21, atr_pct)
        if i == 1:
            regime_at_entry = regime

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
    pnl_eff = pnl_raw * LEVERAGE
    fee_cost = FEE_PCT * 2 * (1 + reduce_count)
    pnl_eff -= fee_cost
    pnl_raw -= fee_cost / LEVERAGE

    return TradeResult(
        symbol=symbol, direction=direction, entry_price=entry_price, exit_price=exit_price,
        entry_time=entry_time, exit_time=exit_time, pnl_pct=pnl_eff, pnl_raw_pct=pnl_raw,
        hold_bars=bars_held, max_dd_pct_raw=max_dd, max_dd_pct_eff=max_dd * LEVERAGE,
        mfe_pct_raw=mfe, exit_reason=exit_reason, original_pnl_pct=original_pnl,
        original_exit_reason=original_exit_reason, leverage=LEVERAGE, reduce_count=reduce_count,
        atr_pct_at_entry=atr_entry, avg_atr_pct=np.mean(atrs), regime=regime_at_entry,
    )


def compute_account_drawdown(results: List[TradeResult], initial_capital: float = 100.0,
                             position_size_pct: float = 0.05) -> Tuple[float, pd.DataFrame]:
    """
    按账户权益曲线计算真实最大回撤。
    假设每笔交易占用固定仓位比例 position_size_pct，多币种并行持仓。
    """
    if not results:
        return 0.0, pd.DataFrame()

    # 按时间排序
    events = []
    for r in results:
        events.append((r.entry_time, "entry", r.pnl_pct))
        events.append((r.exit_time, "exit", r.pnl_pct))
    events.sort(key=lambda x: x[0])

    # 简单模型：每笔交易分配初始资金的固定比例作为名义本金
    # 使用未平仓权益曲线（假设每笔独立，账户权益 = 初始 + 所有已平仓盈亏 + 未平仓浮动盈亏）
    # 为简化，采用"每笔交易固定仓位，盈亏直接加总到累计权益"的近似
    # 更精确：需要K线级持仓状态，这里先用交易级近似
    capital = initial_capital
    equity_curve = [capital]
    times = [events[0][0]]
    active_pnls = []

    for ts, evt_type, pnl in events:
        if evt_type == "entry":
            active_pnls.append(0.0)
        else:
            # 找到一笔 entry 对应的 exit，简化处理：直接加上该笔盈亏
            capital += initial_capital * position_size_pct * pnl / 100.0
            equity_curve.append(capital)
            times.append(ts)

    equity = pd.Series(equity_curve, index=times)
    peak = equity.expanding(min_periods=1).max()
    dd = (equity - peak) / peak * 100.0
    max_dd = dd.min()
    return abs(max_dd), equity


def compute_metrics(results: List[TradeResult]) -> BacktestMetrics:
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

    # 错误算法
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd_wrong = float(np.max(peak - cum)) if len(cum) > 0 else 0.0

    # 正确算法（账户权益近似）
    dd_account, equity = compute_account_drawdown(results)

    gross_profit = sum(r.pnl_pct for r in wins)
    gross_loss = abs(sum(r.pnl_pct for r in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    reason_dist = {}
    for r in results:
        reason = r.exit_reason.split("(")[0] if "(" in r.exit_reason else r.exit_reason
        reason_dist[reason] = reason_dist.get(reason, 0) + 1

    # 按币种
    sym_metrics = {}
    for sym in SYMBOLS:
        rs = [r for r in results if r.symbol == sym]
        if rs:
            sym_pnls = [r.pnl_pct for r in rs]
            sym_metrics[sym] = {
                "trades": len(rs),
                "win_rate": sum(1 for p in sym_pnls if p > 0) / len(rs) * 100,
                "total_return": sum(sym_pnls),
                "sharpe": np.mean(sym_pnls) / np.std(sym_pnls) * math.sqrt(6048) if len(sym_pnls) > 1 and np.std(sym_pnls) > 0 else 0.0,
                "avg_atr_pct": np.mean([r.atr_pct_at_entry for r in rs]) * 100,
                "avg_hold_bars": np.mean([r.hold_bars for r in rs]),
                "max_dd_raw": max(r.max_dd_pct_raw for r in rs) * 100,
            }

    # 按市态
    reg_metrics = {}
    for reg in ["uptrend", "downtrend", "trend", "chop"]:
        rs = [r for r in results if r.regime == reg]
        if rs:
            reg_pnls = [r.pnl_pct for r in rs]
            reg_metrics[reg] = {
                "trades": len(rs),
                "win_rate": sum(1 for p in reg_pnls if p > 0) / len(rs) * 100,
                "total_return": sum(reg_pnls),
                "avg_return": np.mean(reg_pnls),
                "avg_hold_bars": np.mean([r.hold_bars for r in rs]),
            }

    return BacktestMetrics(
        total_trades=n,
        win_trades=len(wins),
        loss_trades=len(losses),
        win_rate=len(wins) / n * 100,
        total_return_pct=total_return,
        avg_return_pct=avg_return,
        sharpe_ratio=sharpe,
        max_drawdown_pct_wrong=dd_wrong,
        max_drawdown_pct_account=dd_account,
        profit_factor=pf,
        avg_hold_bars=np.mean([r.hold_bars for r in results]),
        exit_reason_dist=reason_dist,
        symbol_metrics=sym_metrics,
        regime_metrics=reg_metrics,
    )


def main():
    print("=" * 80)
    print("  ClassicExitSystem 回测诊断")
    print("=" * 80)

    # 使用当前代码默认配置（已写入贝叶斯寻优参数）
    config = ExitConfig()
    system = ClassicExitSystem(config=config)

    all_results = []
    for symbol in SYMBOLS:
        klines = load_klines(symbol)
        trades = load_trades(symbol)
        if klines is None or trades is None:
            continue
        print(f"\n[{symbol}] {len(trades)} 笔交易")
        for _, row in trades.iterrows():
            r = run_single_trade(system, symbol, row, klines)
            all_results.append(r)

    metrics = compute_metrics(all_results)

    print(f"\n{'='*80}")
    print("  汇总指标")
    print(f"{'='*80}")
    print(f"  总交易数:      {metrics.total_trades}")
    print(f"  胜率:          {metrics.win_rate:.1f}%")
    print(f"  总收益率:      {metrics.total_return_pct:+.2f}%")
    print(f"  平均单笔:      {metrics.avg_return_pct:+.2f}%")
    print(f"  夏普比率:      {metrics.sharpe_ratio:.2f}")
    print(f"  盈亏比:        {metrics.profit_factor:.2f}")
    print(f"  平均持仓:      {metrics.avg_hold_bars:.1f} 根K线")
    print(f"\n  最大回撤（错误算法-累加pnl）: {metrics.max_drawdown_pct_wrong:.2f}%")
    print(f"  最大回撤（账户权益近似）:     {metrics.max_drawdown_pct_account:.2f}%")
    print(f"\n  离场原因分布:")
    for reason, count in sorted(metrics.exit_reason_dist.items(), key=lambda x: -x[1]):
        print(f"    {reason:30s}: {count:3d} ({count/metrics.total_trades*100:.1f}%)")

    print(f"\n{'='*80}")
    print("  按币种分析")
    print(f"{'='*80}")
    print(f"  {'币种':<6} {'交易数':>8} {'胜率%':>8} {'总收益%':>10} {'夏普':>8} {'入场ATR%':>10} {'平均持仓h':>10} {'单笔最大回撤%':>14}")
    for sym, m in metrics.symbol_metrics.items():
        print(f"  {sym:<6} {m['trades']:>8} {m['win_rate']:>8.1f} {m['total_return']:>+10.2f} {m['sharpe']:>8.2f} {m['avg_atr_pct']:>10.2f} {m['avg_hold_bars']:>10.1f} {m['max_dd_raw']:>14.2f}")

    print(f"\n{'='*80}")
    print("  按市态分析")
    print(f"{'='*80}")
    print(f"  {'市态':<12} {'交易数':>8} {'胜率%':>8} {'总收益%':>10} {'平均收益%':>10} {'平均持仓h':>10}")
    for reg, m in metrics.regime_metrics.items():
        print(f"  {reg:<12} {m['trades']:>8} {m['win_rate']:>8.1f} {m['total_return']:>+10.2f} {m['avg_return']:>+10.2f} {m['avg_hold_bars']:>10.1f}")

    # 诊断 L0 未触发原因：打印持仓超过 24 根 K 线但未因 L0_MAX_HOLD 离场的样本
    long_hold_non_l0 = [r for r in all_results if r.hold_bars > 24 and "L0_MAX_HOLD" not in r.exit_reason]
    print(f"\n{'='*80}")
    print(f"  诊断：持仓 >24 根 K 线但未触发 L0_MAX_HOLD 的交易数: {len(long_hold_non_l0)}")
    print(f"  样本（前5笔）:")
    for r in long_hold_non_l0[:5]:
        print(f"    {r.symbol} {r.entry_time} -> {r.exit_time}: {r.hold_bars}根K线, 原因={r.exit_reason}, 收益={r.pnl_pct:+.2f}%")

    # 保存诊断结果
    output = {
        "timestamp": pd.Timestamp.now().isoformat(),
        "config": {k: str(v) for k, v in asdict(config).items() if isinstance(v, (int, float, bool, str))},
        "metrics": {
            "total_trades": metrics.total_trades,
            "win_rate": metrics.win_rate,
            "total_return_pct": metrics.total_return_pct,
            "sharpe_ratio": metrics.sharpe_ratio,
            "max_drawdown_pct_wrong": metrics.max_drawdown_pct_wrong,
            "max_drawdown_pct_account": metrics.max_drawdown_pct_account,
            "profit_factor": metrics.profit_factor,
            "avg_hold_bars": metrics.avg_hold_bars,
            "exit_reason_dist": metrics.exit_reason_dist,
        },
        "symbol_metrics": metrics.symbol_metrics,
        "regime_metrics": metrics.regime_metrics,
    }
    out_path = os.path.join(OUTPUT_DIR, "exit_diagnose_result.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  诊断结果已保存: {out_path}")


if __name__ == "__main__":
    main()
