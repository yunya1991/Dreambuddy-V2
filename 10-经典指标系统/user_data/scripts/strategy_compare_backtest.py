"""
经典指标系统 - 策略对比回测脚本
对比: 原始参数 vs 优化参数
策略: Bot2StrategyTrend, SimpleStrategy, OTTStrategy
时间范围: 5011 bars (约17天)

运行方式:
    source .venv/bin/activate
    python user_data/scripts/strategy_compare_backtest.py
"""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import talib.abstract as ta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA_DIR = os.path.join(ROOT, "user_data", "data", "hyperliquid", "futures")

INITIAL_CAPITAL = 1000.0
FEE_RATE = 0.0004          # 0.04% maker/taker (保守估计)
SLIPPAGE = 0.0005          # 0.05%
MAX_POSITION_PER_TRADE = 150.0   # 每笔最大保证金

# ===========================================================================
# 数据加载
# ===========================================================================

def load_bars(symbol: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"{symbol}-5m-futures.json")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "r") as f:
        raw = json.load(f)
    df = pd.DataFrame(raw, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], unit="ms", utc=True)
    df = df.sort_values("date").reset_index(drop=True)
    return df


# ===========================================================================
# 通用指标
# ===========================================================================

def add_basic_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rsi"] = ta.RSI(df, timeperiod=14)
    df["ema_fast"] = ta.EMA(df, timeperiod=10)
    df["ema_slow"] = ta.EMA(df, timeperiod=30)
    df["ema_trend"] = ta.EMA(df, timeperiod=50)
    df["ema_200"] = ta.EMA(df, timeperiod=200)
    df["adx"] = ta.ADX(df, timeperiod=14)
    df["atr"] = ta.ATR(df, timeperiod=14)
    bb = ta.BBANDS(df, timeperiod=20, nbdevup=2.0, nbdevdn=2.0, matype=0)
    df["bb_upper"] = bb["upperband"]
    df["bb_middle"] = bb["middleband"]
    df["bb_lower"] = bb["lowerband"]
    df["bb_percent"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
    df["volume_mean"] = df["volume"].rolling(20).mean()
    df["tema"] = ta.TEMA(df, timeperiod=9)
    df["sar"] = ta.SAR(df)
    # 4h 波动率（用5分钟聚合近似）
    high_4h = df["high"].rolling(48).max()
    low_4h = df["low"].rolling(48).min()
    df["btc_volatility_4h"] = (high_4h - low_4h) / df["close"]
    return df


# ===========================================================================
# 信号生成器（对应三个策略的核心逻辑）
# ===========================================================================

@dataclass
class Signal:
    bar_idx: int
    direction: str           # "long" / "short"
    reason: str
    stop_loss: float
    take_profit: Optional[float] = None
    trail_atr: Optional[float] = None


class Bot2Signal:
    """Bot2StrategyTrend 的核心信号逻辑"""
    def __init__(self, stoploss=-0.028, rsi_range=35, adx_trend=25,
                 volume_factor=1.2, mr_ema_dev=0.015, anti_chase_max_dev=0.08,
                 anti_chase_max_rsi=78, anti_chase_bb=0.95,
                 anti_chase_adx_slope=-0.5, anti_chase_pump=0.05,
                 lookback=20, vol_threshold=0.02, tp_ratio=0.05):
        self.stoploss = stoploss
        self.rsi_range = rsi_range
        self.adx_trend = adx_trend
        self.volume_factor = volume_factor
        self.mr_ema_dev = mr_ema_dev
        self.anti_chase_max_dev = anti_chase_max_dev
        self.anti_chase_max_rsi = anti_chase_max_rsi
        self.anti_chase_bb = anti_chase_bb
        self.anti_chase_adx_slope = anti_chase_adx_slope
        self.anti_chase_pump = anti_chase_pump
        self.lookback = lookback
        self.vol_threshold = vol_threshold
        self.tp_ratio = tp_ratio

    def generate(self, df: pd.DataFrame) -> List[Signal]:
        signals: List[Signal] = []
        n = len(df)

        for i in range(200, n):
            row = df.iloc[i]
            price = float(row["close"])

            # 状态判定
            regime_trend = 1 if (pd.notna(row["btc_volatility_4h"]) and
                                 row["btc_volatility_4h"] >= self.vol_threshold) else 0

            # 追涨过滤
            max_high = df["high"].iloc[max(0, i - self.lookback):i].max()
            recent_pump = (price / max_high) - 1 if max_high > 0 else 0
            adx_slope = row["adx"] - df["adx"].iloc[i - 3] if i >= 3 else 0

            chase_risk = (
                price > row["ema_trend"] * (1 + self.anti_chase_max_dev) or
                row["rsi"] >= self.anti_chase_max_rsi or
                (pd.notna(row["bb_percent"]) and row["bb_percent"] >= self.anti_chase_bb) or
                adx_slope < self.anti_chase_adx_slope or
                recent_pump >= self.anti_chase_pump
            )

            # 均值回归信号
            mr1 = price < row["bb_lower"]
            mr2 = row["rsi"] < self.rsi_range
            mr3 = price < row["ema_fast"] * (1 - self.mr_ema_dev)
            mr_score = int(mr1) + int(mr2) + int(mr3)

            # 趋势跟踪信号
            t1 = price > row["ema_fast"] > row["ema_slow"] > row["ema_trend"]
            t2 = row["adx"] > self.adx_trend
            t3 = row["volume"] > row["volume_mean"] * self.volume_factor if pd.notna(row["volume_mean"]) else False
            trend_score = int(t1) + int(t2) + int(t3)

            entry = False
            if regime_trend == 0 and mr_score >= 2 and row["volume"] > 0:
                entry, reason = True, f"mr_score={mr_score}"
            elif regime_trend == 1 and trend_score >= 2 and row["volume"] > 0:
                entry, reason = True, f"trend_score={trend_score}"

            if entry and not chase_risk:
                sl = price * (1 + self.stoploss)
                tp = price * (1 + self.tp_ratio)
                signals.append(Signal(bar_idx=i, direction="long", reason=reason,
                                       stop_loss=sl, take_profit=tp))
        return signals


class SimpleStrategySignal:
    """SimpleStrategy（RSI + TEMA + 布林带 均值回归，多空双向）"""
    def __init__(self, buy_rsi=27, sell_rsi=72, stoploss=-0.271,
                 atr_mult=2.0, trail_atr_mult=1.5, allow_short=True):
        self.buy_rsi = buy_rsi
        self.sell_rsi = sell_rsi
        self.stoploss = stoploss
        self.atr_mult = atr_mult
        self.trail_atr_mult = trail_atr_mult
        self.allow_short = allow_short

    def generate(self, df: pd.DataFrame) -> List[Signal]:
        signals: List[Signal] = []
        n = len(df)
        loose_buy = min(self.buy_rsi + 4, 35)
        loose_sell = max(self.sell_rsi - 4, 65)

        for i in range(100, n):
            row = df.iloc[i]
            price = float(row["close"])
            vol = float(row["volume"])
            vol_mean = float(row["volume_mean"]) if pd.notna(row["volume_mean"]) else 0
            rsi = float(row["rsi"]) if pd.notna(row["rsi"]) else 50
            tema = float(row["tema"]) if pd.notna(row["tema"]) else price
            bb_mid = float(row["bb_middle"]) if pd.notna(row["bb_middle"]) else price
            tema_prev = float(df["tema"].iloc[i - 1]) if i >= 1 and pd.notna(df["tema"].iloc[i - 1]) else tema
            atr = float(row["atr"]) if pd.notna(row["atr"]) and row["atr"] > 0 else price * 0.01

            # 做多信号
            deep_mr = (rsi < self.buy_rsi and tema <= bb_mid and
                        tema > tema_prev and vol > vol_mean)
            mild_mr = (rsi < loose_buy and tema <= bb_mid and vol > vol_mean * 0.5)

            if deep_mr or mild_mr:
                sl = price - atr * self.atr_mult
                tp = price + atr * self.atr_mult * 1.5  # 盈亏比 1.5
                signals.append(Signal(
                    bar_idx=i, direction="long",
                    reason=f"rsi={rsi:.0f}_deep={deep_mr}",
                    stop_loss=sl, take_profit=tp,
                    trail_atr=atr * self.trail_atr_mult,
                ))
                continue

            # 做空信号
            if self.allow_short:
                deep_short = (rsi > self.sell_rsi and tema >= bb_mid and
                              tema < tema_prev and vol > vol_mean)
                mild_short = (rsi > loose_sell and tema >= bb_mid and vol > vol_mean * 0.5)

                if deep_short or mild_short:
                    sl = price + atr * self.atr_mult
                    tp = price - atr * self.atr_mult * 1.5
                    signals.append(Signal(
                        bar_idx=i, direction="short",
                        reason=f"rsi={rsi:.0f}_short_deep={deep_short}",
                        stop_loss=sl, take_profit=tp,
                        trail_atr=atr * self.trail_atr_mult,
                    ))

        return signals


class OTTSignal:
    """OTTStrategy 的简化信号：基于 EMA 趋势 + ADX 过滤"""
    def __init__(self, stoploss=-0.15, tp_0=0.20, tp_60=0.12, adx_min=20,
                 trail_activate=0.04, trail_offset=0.015,
                 use_custom=True, allow_short=True):
        self.stoploss = stoploss
        self.tp_0 = tp_0
        self.tp_60 = tp_60
        self.adx_min = adx_min
        self.trail_activate = trail_activate
        self.trail_offset = trail_offset
        self.use_custom = use_custom
        self.allow_short = allow_short

    def generate(self, df: pd.DataFrame) -> List[Signal]:
        signals: List[Signal] = []
        n = len(df)
        for i in range(100, n):
            row = df.iloc[i]
            price = float(row["close"])
            ema_slow = float(row["ema_slow"]) if pd.notna(row["ema_slow"]) else price
            ema_trend = float(row["ema_trend"]) if pd.notna(row["ema_trend"]) else price
            adx = float(row["adx"]) if pd.notna(row["adx"]) else 0
            atr = float(row["atr"]) if pd.notna(row["atr"]) and row["atr"] > 0 else price * 0.01
            prev_price = float(df["close"].iloc[i - 1])
            prev_slow = float(df["ema_slow"].iloc[i - 1]) if pd.notna(df["ema_slow"].iloc[i - 1]) else price

            # 做多: 价格在 EMA 上方 + EMA 上升 + ADX > 阈值
            long_cond = (price > ema_slow and ema_slow > ema_trend and
                        adx > self.adx_min and prev_price <= prev_slow)
            # 做空: 价格在 EMA 下方 + EMA 下降 + ADX > 阈值
            short_cond = (self.allow_short and price < ema_slow and
                         ema_slow < ema_trend and adx > self.adx_min and
                         prev_price >= prev_slow)

            if long_cond:
                sl = price * (1 + self.stoploss)
                tp = price * (1 + self.tp_0)
                signals.append(Signal(
                    bar_idx=i, direction="long", reason=f"adx={adx:.0f}",
                    stop_loss=sl, take_profit=tp,
                    trail_atr=atr,
                ))
            elif short_cond:
                sl = price * (1 - self.stoploss)
                tp = price * (1 - self.tp_60)
                signals.append(Signal(
                    bar_idx=i, direction="short", reason=f"adx={adx:.0f}",
                    stop_loss=sl, take_profit=tp,
                    trail_atr=atr,
                ))
        return signals


# ===========================================================================
# 事件驱动回测引擎
# ===========================================================================

@dataclass
class Position:
    direction: str
    entry_price: float
    entry_idx: int
    size: float              # 名义仓位数量（coin 数）
    capital_used: float      # 占用保证金
    stop_loss: float
    take_profit: float
    trail_atr: Optional[float]
    trailing_stop: Optional[float] = None
    best_price: float = 0.0  # 多头为最高价，空头为最低价


@dataclass
class Trade:
    direction: str
    entry_price: float
    entry_idx: int
    exit_price: float
    exit_idx: int
    exit_reason: str
    pnl: float
    pnl_pct: float


@dataclass
class BacktestResult:
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def win_count(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def loss_count(self) -> int:
        return sum(1 for t in self.trades if t.pnl <= 0)

    @property
    def win_rate(self) -> float:
        return self.win_count / self.total_trades if self.total_trades > 0 else 0

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.total_trades if self.total_trades > 0 else 0

    @property
    def avg_win(self) -> float:
        wins = [t.pnl for t in self.trades if t.pnl > 0]
        return sum(wins) / len(wins) if wins else 0

    @property
    def avg_loss(self) -> float:
        losses = [t.pnl for t in self.trades if t.pnl <= 0]
        return sum(losses) / len(losses) if losses else 0

    @property
    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0
        peak = np.maximum.accumulate(np.array(self.equity_curve))
        dd = (peak - np.array(self.equity_curve)) / peak
        return float(dd.max()) * 100

    @property
    def profit_factor(self) -> float:
        total_gain = sum(t.pnl for t in self.trades if t.pnl > 0)
        total_loss = -sum(t.pnl for t in self.trades if t.pnl <= 0)
        return total_gain / total_loss if total_loss > 0 else float("inf")


class BacktestEngine:
    def __init__(self, df: pd.DataFrame, initial_capital: float = INITIAL_CAPITAL,
                 max_cap_per_trade: float = MAX_POSITION_PER_TRADE,
                 fee_rate: float = FEE_RATE, slippage: float = SLIPPAGE,
                 cooldown_bars: int = 5):
        self.df = df
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.max_cap = max_cap_per_trade
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.cooldown = cooldown_bars
        self.position: Optional[Position] = None
        self.trades: List[Trade] = []
        self.last_entry_idx = -9999

    def run(self, signals: List[Signal]):
        self.position = None
        self.trades = []
        self.capital = self.initial_capital
        self.last_entry_idx = -9999
        n = len(self.df)
        equity = [self.capital]

        signal_idx = 0
        next_signal = signals[signal_idx] if signals else None

        for i in range(1, n):
            bar = self.df.iloc[i]
            high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])

            # 1) 处理当前仓位
            if self.position is not None:
                exit_price, reason = self._check_exit(self.position, high, low, close, bar)
                if exit_price is not None:
                    self._close_position(self.position, exit_price, i, reason)

            # 2) 处理新信号（若当前无仓且已过冷却期）
            if self.position is None and next_signal is not None and i >= next_signal.bar_idx:
                if i - self.last_entry_idx >= self.cooldown:
                    # 用下一根 bar 的 open 价入场（滑点处理）
                    entry_idx = min(i + 1, n - 1)
                    entry_bar = self.df.iloc[entry_idx]
                    direction = next_signal.direction
                    entry_price = float(entry_bar["open"]) * (1 + (self.slippage if direction == "long" else -self.slippage))
                    cap = min(self.max_cap, self.capital * 0.5)
                    size = cap / entry_price

                    # 调整 stop_loss 基于当前价格
                    atr = float(self.df["atr"].iloc[entry_idx]) if pd.notna(self.df["atr"].iloc[entry_idx]) else entry_price * 0.01
                    if direction == "long":
                        sl = min(next_signal.stop_loss, entry_price - atr * 2)
                    else:
                        sl = max(next_signal.stop_loss, entry_price + atr * 2)
                    tp = next_signal.take_profit if next_signal.take_profit else (
                        entry_price * (1 + 0.05) if direction == "long" else entry_price * (1 - 0.05)
                    )

                    self.position = Position(
                        direction=direction,
                        entry_price=entry_price,
                        entry_idx=entry_idx,
                        size=size,
                        capital_used=cap,
                        stop_loss=sl,
                        take_profit=tp,
                        trail_atr=next_signal.trail_atr,
                        best_price=entry_price,
                    )
                    self.last_entry_idx = entry_idx

                # 跳到下一个信号
                signal_idx += 1
                next_signal = signals[signal_idx] if signal_idx < len(signals) else None

            # 3) 计算权益
            unreal = self._unrealized_pnl(close) if self.position else 0
            equity.append(self.capital + unreal)

        # 结束时强制平仓
        if self.position is not None:
            last_close = float(self.df["close"].iloc[-1])
            self._close_position(self.position, last_close, n - 1, "end_of_data")

        return BacktestResult(trades=self.trades, equity_curve=equity)

    def _check_exit(self, pos: Position, high: float, low: float, close: float, bar: pd.Series
                    ) -> Tuple[Optional[float], Optional[str]]:
        # 更新最佳价格（追踪止损）
        if pos.direction == "long":
            if high > pos.best_price:
                pos.best_price = high
        else:
            if low < pos.best_price or pos.best_price == 0:
                pos.best_price = low

        # 追踪止损: 当盈利超过 trail_activate，激活 trailing stop
        if pos.trail_atr is not None:
            if pos.direction == "long":
                if pos.best_price > pos.entry_price * (1 + self.slippage * 2):
                    new_sl = pos.best_price - pos.trail_atr
                    if new_sl > pos.stop_loss:
                        pos.stop_loss = new_sl
            else:
                if pos.best_price < pos.entry_price * (1 - self.slippage * 2):
                    new_sl = pos.best_price + pos.trail_atr
                    if new_sl < pos.stop_loss:
                        pos.stop_loss = new_sl

        if pos.direction == "long":
            # 止损（low 触及 stop_loss）
            if low <= pos.stop_loss:
                return pos.stop_loss * (1 - self.slippage), "stop_loss"
            # 止盈（high 触及 take_profit）
            if high >= pos.take_profit:
                return pos.take_profit * (1 - self.slippage), "take_profit"
        else:
            # 做空: 止损 = high 触及 stop_loss
            if high >= pos.stop_loss:
                return pos.stop_loss * (1 + self.slippage), "stop_loss"
            # 止盈 = low 触及 take_profit
            if low <= pos.take_profit:
                return pos.take_profit * (1 + self.slippage), "take_profit"
        return None, None

    def _unrealized_pnl(self, close: float) -> float:
        if self.position is None:
            return 0
        pos = self.position
        if pos.direction == "long":
            return (close - pos.entry_price) * pos.size
        else:
            return (pos.entry_price - close) * pos.size

    def _close_position(self, pos: Position, exit_price: float, exit_idx: int, reason: str):
        gross = self._unrealized_pnl(exit_price)
        fee = pos.entry_price * pos.size * self.fee_rate + exit_price * pos.size * self.fee_rate
        net_pnl = gross - fee
        pnl_pct = net_pnl / pos.capital_used

        self.trades.append(Trade(
            direction=pos.direction,
            entry_price=pos.entry_price, entry_idx=pos.entry_idx,
            exit_price=exit_price, exit_idx=exit_idx,
            exit_reason=reason, pnl=net_pnl, pnl_pct=pnl_pct,
        ))
        self.capital += net_pnl
        self.position = None


# ===========================================================================
# 输出格式化
# ===========================================================================

def print_result(label: str, result: BacktestResult, show_top_losses: int = 5):
    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"{'='*80}")
    print(f"  交易笔数:       {result.total_trades}")
    print(f"  盈利:           {result.win_count} ({result.win_rate*100:.1f}%)")
    print(f"  亏损:           {result.loss_count} ({(1-result.win_rate)*100:.1f}%)")
    print(f"  总盈亏 (USDT):  {result.total_pnl:+.2f}")
    print(f"  平均盈亏:       {result.avg_pnl:+.4f}")
    print(f"  平均盈利:       +{result.avg_win:.4f}")
    print(f"  平均亏损:       {result.avg_loss:.4f}")
    print(f"  盈亏比:         {result.avg_win / (-result.avg_loss):.2f}" if result.avg_loss < 0 else "  盈亏比:         N/A")
    print(f"  Profit Factor:  {result.profit_factor:.2f}")
    print(f"  最大回撤 (%):   {result.max_drawdown:.2f}")
    print(f"  最终权益:       {result.equity_curve[-1]:.2f} (初始 {result.equity_curve[0]:.2f})")
    print(f"  总收益率:       {(result.equity_curve[-1]/result.equity_curve[0]-1)*100:+.2f}%")

    if show_top_losses > 0 and result.trades:
        sorted_trades = sorted(result.trades, key=lambda t: t.pnl)
        print(f"\n  Top-{min(show_top_losses, len(sorted_trades))} 亏损交易:")
        for i, t in enumerate(sorted_trades[:show_top_losses]):
            dur = (t.exit_idx - t.entry_idx) * 5
            print(f"    [{i+1}] {t.direction} 入场@{t.entry_price:.2f} 离场@{t.exit_price:.2f} "
                  f"原因={t.exit_reason} 盈亏={t.pnl:+.2f} ({t.pnl_pct*100:+.1f}%) 持有~{dur}min")

    if result.trades:
        reasons = {}
        for t in result.trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
        print(f"\n  离场原因分布: {reasons}")


# ===========================================================================
# 主流程
# ===========================================================================

def compare_strategy(symbol: str, df: pd.DataFrame, configs: Dict[str, object]
                    ) -> Dict[str, BacktestResult]:
    results: Dict[str, BacktestResult] = {}
    for name, signal_gen in configs.items():
        signals = signal_gen.generate(df)
        engine = BacktestEngine(df, initial_capital=INITIAL_CAPITAL,
                                max_cap_per_trade=MAX_POSITION_PER_TRADE)
        result = engine.run(signals)
        results[name] = result
        print_result(f"{symbol} - {name}", result)
    return results


def main():
    symbols = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]

    print("\n" + "="*80)
    print("  经典指标系统 - 策略参数对比回测")
    print(f"  初始资金: {INITIAL_CAPITAL} USDT, 单笔最大保证金: {MAX_POSITION_PER_TRADE}")
    print(f"  手续费: {FEE_RATE*100:.2f}%, 滑点: {SLIPPAGE*100:.2f}%, bar内冷却 5 bar")
    print("="*80)

    summary = []

    for symbol in symbols:
        print(f"\n{'#'*80}")
        print(f"# 测试品种: {symbol}")
        print(f"{'#'*80}")
        try:
            df_raw = load_bars(symbol)
        except FileNotFoundError:
            print(f"  [跳过] 无数据: {symbol}")
            continue
        df = add_basic_indicators(df_raw)

        # 基准优化组
        configs = {
            # ======== Bot2StrategyTrend ========
            "[Bot2] 原始 (-2.8% 止损, 5% 止盈)":
                Bot2Signal(stoploss=-0.028, tp_ratio=0.05),
            "[Bot2] 优化1 (-8% 止损, 15% 止盈, 高阈值)":
                Bot2Signal(stoploss=-0.08, tp_ratio=0.15, anti_chase_max_rsi=82,
                          anti_chase_bb=0.98),
            "[Bot2] 优化2 (ATR 止损, 趋势确认)":
                Bot2Signal(stoploss=-0.06, tp_ratio=0.12, rsi_range=30,
                          anti_chase_max_rsi=80),

            # ======== SimpleStrategy ========
            "[Simple] 原始 (多空双向, -27.1% 止损)":
                SimpleStrategySignal(allow_short=True),
            "[Simple] 优化1 (仅做多, 收紧止损)":
                SimpleStrategySignal(allow_short=False, atr_mult=3.0, trail_atr_mult=2.0),
            "[Simple] 优化2 (多空 + 收紧 RSI 阈值)":
                SimpleStrategySignal(buy_rsi=25, sell_rsi=75, allow_short=True,
                                    atr_mult=2.5, trail_atr_mult=1.8),

            # ======== OTTStrategy ========
            "[OTT] 原始 (15% 止损, 20% 止盈)":
                OTTSignal(stoploss=-0.15, tp_0=0.20, tp_60=0.12),
            "[OTT] 优化1 (收紧止损 + 更高 ADX)":
                OTTSignal(stoploss=-0.08, tp_0=0.12, tp_60=0.06, adx_min=25),
            "[OTT] 优化2 (仅做多 + 激进)":
                OTTSignal(stoploss=-0.10, tp_0=0.15, tp_60=0.08, allow_short=False),
        }

        results = compare_strategy(symbol, df, configs)

        # 汇总这个币种的结果
        for name, r in results.items():
            summary.append({
                "symbol": symbol, "name": name, "trades": r.total_trades,
                "win_rate": r.win_rate * 100, "total_pnl": r.total_pnl,
                "avg_pnl": r.avg_pnl, "pf": r.profit_factor,
                "max_dd": r.max_drawdown, "final_eq": r.equity_curve[-1],
            })

    # ====================================================================
    # 跨币种汇总表
    # ====================================================================
    print("\n\n" + "="*80)
    print("  跨币种汇总（同一策略在三币种上的平均表现）")
    print("="*80)

    by_strategy: Dict[str, Dict] = {}
    for s in summary:
        key = s["name"]
        if key not in by_strategy:
            by_strategy[key] = {"trades": 0, "pnl": 0.0, "wr_sum": 0.0, "n": 0,
                                "pf_sum": 0.0, "dd_sum": 0.0}
        agg = by_strategy[key]
        agg["trades"] += s["trades"]
        agg["pnl"] += s["total_pnl"]
        agg["wr_sum"] += s["win_rate"]
        agg["pf_sum"] += s["pf"] if s["pf"] != float("inf") else 3.0
        agg["dd_sum"] += s["max_dd"]
        agg["n"] += 1

    rows = []
    for name, agg in by_strategy.items():
        if agg["n"] == 0:
            continue
        rows.append({
            "策略": name,
            "总交易": str(agg["trades"]),
            "平均胜率%": f"{agg['wr_sum']/agg['n']:.1f}",
            "总盈亏USDT": f"{agg['pnl']:+.2f}",
            "平均PF": f"{agg['pf_sum']/agg['n']:.2f}",
            "平均回撤%": f"{agg['dd_sum']/agg['n']:.1f}",
        })

    # 排序：按总盈亏从高到低
    rows.sort(key=lambda r: float(r["总盈亏USDT"]), reverse=True)

    if rows:
        keys = list(rows[0].keys())
        col_widths = {k: max(len(str(k)), max(len(r[k]) for r in rows)) for k in keys}
        header = " | ".join(k.ljust(col_widths[k]) for k in keys)
        sep = "-+-".join("-" * col_widths[k] for k in keys)
        print(f"\n  {header}")
        print(f"  {sep}")
        for row in rows:
            line = " | ".join(str(row[k]).ljust(col_widths[k]) for k in keys)
            print(f"  {line}")
    print()


if __name__ == "__main__":
    main()
