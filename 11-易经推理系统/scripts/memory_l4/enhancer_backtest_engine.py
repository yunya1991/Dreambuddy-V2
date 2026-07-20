#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强器回测验证引擎
===================

验证目标：
1. 震荡市增强器是否能提升胜率
2. 动态止损是否减少最大回撤
3. 布林带双确认是否过滤坏信号
4. MA200方向性偏向是否提升盈亏比

策略设计：
- 基础信号：EMA交叉 + RSI过滤（经典趋势跟踪）
- 对比组A：原始策略（固定1.5×ATR止损，固定阈值0.55）
- 对比组B：增强器优化（动态阈值+布林确认+动态止损+MA200偏向）

回测维度：
- 总收益、年化收益
- 胜率、盈亏比
- 最大回撤、Calmar比率
- 连续亏损次数
- 交易次数、持仓时间
- 各市场状态下的表现分化
"""
import os
import sys
import json
import math
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict, Counter

import numpy as np
import pandas as pd

# 确保可以导入本地模块
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from memory_l4.ranging_market_enhancer import (
    RangingMarketEnhancer,
    MarketRegime,
    BollingerSignal,
)


# ── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    """单笔交易"""
    entry_time: str = ""
    exit_time: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    direction: str = ""  # long/short
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # stop_loss / take_profit / signal_reverse / time_stop
    entry_confidence: float = 0.0
    regime: str = ""
    bollinger_signal: str = ""
    sl_atr_mult: float = 0.0
    tp_atr_mult: float = 0.0
    hold_bars: int = 0


@dataclass
class BacktestResult:
    """回测结果"""
    symbol: str = ""
    timeframe: str = ""
    strategy: str = ""
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0
    total_pnl_pct: float = 0.0
    total_pnl: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    max_consecutive_losses: int = 0
    calmar_ratio: float = 0.0
    sharpe_ratio: float = 0.0
    avg_hold_bars: float = 0.0
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    regime_stats: Dict[str, Dict] = field(default_factory=dict)


# ── 基础策略：EMA交叉 + RSI过滤 ─────────────────────────────────────────────

class EMATrendStrategy:
    """
    基础趋势跟踪策略：
    - EMA10上穿EMA30 → 做多
    - EMA10下穿EMA30 → 做空
    - RSI过滤：极端超买超卖区不反向开仓
    """

    def __init__(self, fast_period: int = 10, slow_period: int = 30,
                 rsi_period: int = 14):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.rsi_period = rsi_period

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成信号序列"""
        df = df.copy()

        # EMA
        df['ema_fast'] = df['close'].ewm(span=self.fast_period, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=self.slow_period, adjust=False).mean()

        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=self.rsi_period, min_periods=self.rsi_period).mean()
        avg_loss = loss.rolling(window=self.rsi_period, min_periods=self.rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))
        df['rsi'] = df['rsi'].fillna(50)

        # ATR
        high = df['high']
        low = df['low']
        close = df['close']
        tr = pd.concat([
            high - low,
            abs(high - close.shift(1)),
            abs(low - close.shift(1))
        ], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14, min_periods=1).mean()

        # 信号：EMA方向（每10根K线重新评估一次，模拟易经推理模型的周期性输出）
        df['signal'] = 'FLAT'
        
        # 方向：EMA9在EMA21上方为UP，下方为DOWN
        direction_up = df['ema_fast'] > df['ema_slow']
        direction_down = df['ema_fast'] < df['ema_slow']
        
        # 每10根K线产生一个新信号（避免过于频繁交易）
        signal_interval = 10
        for i in range(signal_interval, len(df)):
            if i % signal_interval == 0:
                if direction_up.iloc[i]:
                    df.loc[df.index[i], 'signal'] = 'UP'
                elif direction_down.iloc[i]:
                    df.loc[df.index[i], 'signal'] = 'DOWN'

        # 置信度：基于趋势强度和RSI位置计算
        df['confidence'] = 0.5  # 默认

        # 趋势强度：EMA间距 / 价格
        trend_strength = abs(df['ema_fast'] - df['ema_slow']) / df['ema_slow'] * 100
        trend_strength_norm = (trend_strength / 5.0).clip(0, 1)  # 5%差距为满格

        # RSI位置：RSI距离50的距离
        rsi_pos = abs(df['rsi'] - 50) / 50  # 0-1

        # 合成置信度
        df['confidence'] = 0.45 + 0.25 * trend_strength_norm + 0.2 * rsi_pos
        df['confidence'] = df['confidence'].clip(0.35, 0.80)

        # 趋势强度（供增强器使用）
        df['trend_strength'] = trend_strength_norm

        # 震荡市检测：简化版
        df['is_ranging'] = (trend_strength < 1.5) & (df['rsi'].between(35, 65))
        df['ranging_confidence'] = np.where(df['is_ranging'], 0.6, 0.25)
        # 更强的震荡市：趋势更弱+RSI更居中
        strong_ranging = (trend_strength < 0.8) & (df['rsi'].between(42, 58))
        df.loc[strong_ranging, 'ranging_confidence'] = 0.75

        # 波动率
        df['volatility'] = df['atr'] / df['close']

        return df


# ── 回测引擎 ────────────────────────────────────────────────────────────────

class EnhancerBacktestEngine:
    """
    增强器回测引擎

    支持两种模式：
    - 'baseline': 基础策略（固定参数）
    - 'enhanced': 增强器优化（动态阈值+布林确认+动态止损+MA200偏向）
    """

    def __init__(self, symbol: str = "BTC", timeframe: str = "1H",
                 initial_capital: float = 10000.0,
                 position_pct: float = 0.1,  # 每次用10%资金
                 commission_pct: float = 0.04,  # 手续费0.04%
                 max_hold_bars: int = 120,  # 最长持有120根K线
                 ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.initial_capital = initial_capital
        self.position_pct = position_pct
        self.commission_pct = commission_pct
        self.max_hold_bars = max_hold_bars

        self.enhancer = RangingMarketEnhancer()
        self.base_strategy = EMATrendStrategy()

    def run(self, df: pd.DataFrame, mode: str = "baseline") -> BacktestResult:
        """
        运行回测

        Args:
            df: 包含OHLCV的DataFrame
            mode: 'baseline' or 'enhanced'

        Returns:
            BacktestResult
        """
        # 生成基础信号
        df = self.base_strategy.generate_signals(df)

        closes = df['close'].values.tolist()
        highs = df['high'].values.tolist()
        lows = df['low'].values.tolist()
        signals = df['signal'].values
        confidences = df['confidence'].values
        atrs = df['atr'].values
        volatilities = df['volatility'].values
        is_rangings = df['is_ranging'].values
        ranging_confs = df['ranging_confidence'].values
        trend_strengths = df['trend_strength'].values

        # 回测状态
        capital = self.initial_capital
        position = None  # 当前持仓
        trades = []
        equity_curve = []
        consecutive_losses = 0
        max_consecutive_losses = 0
        peak_equity = capital
        max_dd = 0.0

        # 统计各市场状态的交易表现
        regime_trades = defaultdict(list)

        for i in range(len(df)):
            current_price = closes[i]
            timestamp = str(df.index[i]) if hasattr(df.index[i], '__str__') else str(i)

            # 检查持仓
            if position is not None:
                position['hold_bars'] += 1

                # 检查止损止盈
                pnl_pct = 0.0
                if position['direction'] == 'long':
                    pnl_pct = (current_price - position['entry_price']) / position['entry_price']
                else:
                    pnl_pct = (position['entry_price'] - current_price) / position['entry_price']

                # 止损
                if current_price <= position['stop_loss'] and position['direction'] == 'long':
                    trade = self._close_position(position, current_price, timestamp, "stop_loss")
                    trades.append(trade)
                    capital *= (1 + trade.pnl_pct - self.commission_pct / 100)
                    position = None
                    if trade.pnl_pct < 0:
                        consecutive_losses += 1
                        max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
                    else:
                        consecutive_losses = 0
                    regime_trades[trade.regime].append(trade)

                elif current_price >= position['stop_loss'] and position['direction'] == 'short':
                    trade = self._close_position(position, current_price, timestamp, "stop_loss")
                    trades.append(trade)
                    capital *= (1 + trade.pnl_pct - self.commission_pct / 100)
                    position = None
                    if trade.pnl_pct < 0:
                        consecutive_losses += 1
                        max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
                    else:
                        consecutive_losses = 0
                    regime_trades[trade.regime].append(trade)

                # 止盈
                elif current_price >= position['take_profit'] and position['direction'] == 'long':
                    trade = self._close_position(position, current_price, timestamp, "take_profit")
                    trades.append(trade)
                    capital *= (1 + trade.pnl_pct - self.commission_pct / 100)
                    position = None
                    if trade.pnl_pct < 0:
                        consecutive_losses += 1
                        max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
                    else:
                        consecutive_losses = 0
                    regime_trades[trade.regime].append(trade)

                elif current_price <= position['take_profit'] and position['direction'] == 'short':
                    trade = self._close_position(position, current_price, timestamp, "take_profit")
                    trades.append(trade)
                    capital *= (1 + trade.pnl_pct - self.commission_pct / 100)
                    position = None
                    if trade.pnl_pct < 0:
                        consecutive_losses += 1
                        max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
                    else:
                        consecutive_losses = 0
                    regime_trades[trade.regime].append(trade)

                # 时间止损
                elif position['hold_bars'] >= self.max_hold_bars:
                    trade = self._close_position(position, current_price, timestamp, "time_stop")
                    trades.append(trade)
                    capital *= (1 + trade.pnl_pct - self.commission_pct / 100)
                    position = None
                    if trade.pnl_pct < 0:
                        consecutive_losses += 1
                        max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
                    else:
                        consecutive_losses = 0
                    regime_trades[trade.regime].append(trade)

                # 信号反转平仓
                elif signals[i] != 'FLAT':
                    sig_dir = 'long' if signals[i] == 'UP' else 'short'
                    if sig_dir != position['direction']:
                        trade = self._close_position(position, current_price, timestamp, "signal_reverse")
                        trades.append(trade)
                        capital *= (1 + trade.pnl_pct - self.commission_pct / 100)
                        position = None
                        if trade.pnl_pct < 0:
                            consecutive_losses += 1
                            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
                        else:
                            consecutive_losses = 0
                        regime_trades[trade.regime].append(trade)

            # 如果有空仓且有信号，考虑开仓
            if position is None and signals[i] != 'FLAT' and i >= 200:
                direction = 'long' if signals[i] == 'UP' else 'short'
                confidence = float(confidences[i])
                atr = float(atrs[i])
                volatility = float(volatilities[i])
                is_ranging = bool(is_rangings[i])
                ranging_conf = float(ranging_confs[i])
                trend_strength = float(trend_strengths[i])

                should_open = True
                sl_mult = 1.5
                tp_mult = 3.0
                regime_label = "unknown"
                boll_sig = "none"

                if mode == "baseline":
                    # 基础策略：固定阈值（较低，让交易更频繁）
                    threshold = 0.45
                    if confidence < threshold:
                        should_open = False

                else:
                    # 增强器模式：调用增强器
                    if i >= 200:
                        window_closes = closes[max(0, i-250):i+1]
                        window_highs = highs[max(0, i-250):i+1]
                        window_lows = lows[max(0, i-250):i+1]

                        enhance_result = self.enhancer.enhance(
                            price=current_price,
                            direction=signals[i],
                            confidence=confidence,
                            closes=window_closes,
                            highs=window_highs,
                            lows=window_lows,
                            atr=atr,
                            is_ranging=is_ranging,
                            ranging_confidence=ranging_conf,
                            trend_strength=trend_strength,
                            coin=self.symbol,
                        )

                        should_open = enhance_result.should_trade
                        sl_mult = enhance_result.recommended_sl_atr_mult
                        tp_mult = enhance_result.recommended_tp_atr_mult
                        regime_label = enhance_result.regime.value
                        boll_sig = enhance_result.bollinger.signal.value

                        # 应用校准后的置信度（如果有）
                        confidence = self.enhancer.calibrate_confidence(
                            confidence,
                            enhance_result.regime,
                            "",
                            signals[i],
                        )
                    else:
                        should_open = confidence >= 0.55

                if should_open:
                    # 计算止损止盈
                    if direction == 'long':
                        stop_loss = current_price - atr * sl_mult
                        take_profit = current_price + atr * tp_mult
                    else:
                        stop_loss = current_price + atr * sl_mult
                        take_profit = current_price - atr * tp_mult

                    position = {
                        'entry_time': timestamp,
                        'entry_price': current_price,
                        'direction': direction,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'confidence': confidence,
                        'hold_bars': 0,
                        'regime': regime_label,
                        'bollinger_signal': boll_sig,
                        'sl_atr_mult': sl_mult,
                        'tp_atr_mult': tp_mult,
                    }

            # 更新权益曲线
            equity = capital
            if position is not None:
                if position['direction'] == 'long':
                    unrealized = (current_price - position['entry_price']) / position['entry_price']
                else:
                    unrealized = (position['entry_price'] - current_price) / position['entry_price']
                equity = capital * (1 + unrealized * self.position_pct)

            equity_curve.append(equity)

            if equity > peak_equity:
                peak_equity = equity
            dd = (peak_equity - equity) / peak_equity * 100
            if dd > max_dd:
                max_dd = dd

        # 如果还有持仓，用最后价格平仓
        if position is not None:
            last_price = closes[-1]
            last_time = str(df.index[-1])
            trade = self._close_position(position, last_price, last_time, "end_of_data")
            trades.append(trade)
            capital *= (1 + trade.pnl_pct - self.commission_pct / 100)
            regime_trades[trade.regime].append(trade)

        # 计算指标
        result = self._calc_metrics(trades, equity_curve, capital, max_dd,
                                     max_consecutive_losses, mode, regime_trades)
        return result

    def _close_position(self, position: Dict, exit_price: float,
                         exit_time: str, exit_reason: str) -> Trade:
        """平仓并生成交易记录"""
        if position['direction'] == 'long':
            pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
        else:
            pnl_pct = (position['entry_price'] - exit_price) / position['entry_price']

        pnl_pct *= self.position_pct  # 按仓位比例

        return Trade(
            entry_time=position['entry_time'],
            exit_time=exit_time,
            entry_price=position['entry_price'],
            exit_price=exit_price,
            direction=position['direction'],
            pnl_pct=pnl_pct,
            pnl=pnl_pct * self.initial_capital,
            exit_reason=exit_reason,
            entry_confidence=position['confidence'],
            regime=position.get('regime', ''),
            bollinger_signal=position.get('bollinger_signal', ''),
            sl_atr_mult=position.get('sl_atr_mult', 0),
            tp_atr_mult=position.get('tp_atr_mult', 0),
            hold_bars=position['hold_bars'],
        )

    def _calc_metrics(self, trades: List[Trade], equity_curve: List[float],
                       final_capital: float, max_dd: float,
                       max_consecutive_losses: int, mode: str,
                       regime_trades: Dict[str, List[Trade]]) -> BacktestResult:
        """计算回测指标"""
        total = len(trades)
        wins = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct < 0]

        total_pnl_pct = (final_capital - self.initial_capital) / self.initial_capital * 100
        win_rate = len(wins) / total * 100 if total > 0 else 0

        avg_win = sum(t.pnl_pct for t in wins) / len(wins) * 100 if wins else 0
        avg_loss = sum(t.pnl_pct for t in losses) / len(losses) * 100 if losses else 0

        gross_win = sum(t.pnl_pct for t in wins) * 100 if wins else 0
        gross_loss = abs(sum(t.pnl_pct for t in losses)) * 100 if losses else 0.0001
        profit_factor = gross_win / gross_loss if gross_loss > 0 else 0

        avg_hold = sum(t.hold_bars for t in trades) / total if total > 0 else 0

        # 夏普比率（简化版，用bar收益率）
        if len(equity_curve) > 1:
            returns = pd.Series(equity_curve).pct_change().dropna()
            if len(returns) > 0 and returns.std() > 0:
                # 年化夏普（假设1H周期 = 365*24 bars）
                sharpe = returns.mean() / returns.std() * math.sqrt(365 * 24)
            else:
                sharpe = 0
        else:
            sharpe = 0

        # Calmar比率
        calmar = total_pnl_pct / max_dd if max_dd > 0 else 0

        # 各市场状态统计
        regime_stats = {}
        for regime, r_trades in regime_trades.items():
            if not r_trades:
                continue
            r_wins = [t for t in r_trades if t.pnl_pct > 0]
            r_losses = [t for t in r_trades if t.pnl_pct < 0]
            regime_stats[regime] = {
                'trades': len(r_trades),
                'win_rate': len(r_wins) / len(r_trades) * 100 if r_trades else 0,
                'avg_pnl_pct': sum(t.pnl_pct for t in r_trades) / len(r_trades) * 100 if r_trades else 0,
                'total_pnl_pct': sum(t.pnl_pct for t in r_trades) * 100,
            }

        return BacktestResult(
            symbol=self.symbol,
            timeframe=self.timeframe,
            strategy=mode,
            total_trades=total,
            win_trades=len(wins),
            loss_trades=len(losses),
            win_rate=win_rate,
            total_pnl_pct=total_pnl_pct,
            total_pnl=final_capital - self.initial_capital,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            profit_factor=profit_factor,
            max_drawdown_pct=max_dd,
            max_consecutive_losses=max_consecutive_losses,
            calmar_ratio=calmar,
            sharpe_ratio=sharpe,
            avg_hold_bars=avg_hold,
            trades=trades,
            equity_curve=equity_curve,
            regime_stats=regime_stats,
        )


# ── 报告生成 ────────────────────────────────────────────────────────────────

def generate_comparison_report(baseline: BacktestResult,
                                enhanced: BacktestResult,
                                output_path: str):
    """生成对比报告"""
    report = {
        "timestamp": datetime.now().isoformat(),
        "symbol": baseline.symbol,
        "timeframe": baseline.timeframe,
        "initial_capital": 10000.0,
        "position_pct": 0.1,
        "baseline": {
            k: v for k, v in asdict(baseline).items()
            if k not in ('trades', 'equity_curve', 'regime_stats')
        },
        "enhanced": {
            k: v for k, v in asdict(enhanced).items()
            if k not in ('trades', 'equity_curve', 'regime_stats')
        },
        "improvement": {
            "win_rate_delta": enhanced.win_rate - baseline.win_rate,
            "total_pnl_pct_delta": enhanced.total_pnl_pct - baseline.total_pnl_pct,
            "max_drawdown_delta": enhanced.max_drawdown_pct - baseline.max_drawdown_pct,
            "profit_factor_delta": enhanced.profit_factor - baseline.profit_factor,
            "sharpe_delta": enhanced.sharpe_ratio - baseline.sharpe_ratio,
            "calmar_delta": enhanced.calmar_ratio - baseline.calmar_ratio,
            "max_consecutive_losses_delta": enhanced.max_consecutive_losses - baseline.max_consecutive_losses,
            "trade_count_delta": enhanced.total_trades - baseline.total_trades,
        },
        "baseline_regime_stats": baseline.regime_stats,
        "enhanced_regime_stats": enhanced.regime_stats,
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    return report


def print_comparison(baseline: BacktestResult, enhanced: BacktestResult):
    """打印对比结果"""
    print()
    print("=" * 80)
    print(f"📊 回测对比报告 | {baseline.symbol} {baseline.timeframe}")
    print("=" * 80)

    items = [
        ("总交易数", baseline.total_trades, enhanced.total_trades, "d", "+"),
        ("盈利交易", baseline.win_trades, enhanced.win_trades, "d", "+"),
        ("亏损交易", baseline.loss_trades, enhanced.loss_trades, "d", "-"),
        ("胜率(%)", baseline.win_rate, enhanced.win_rate, ".2f", "+"),
        ("总收益(%)", baseline.total_pnl_pct, enhanced.total_pnl_pct, ".2f", "+"),
        ("平均盈利(%)", baseline.avg_win_pct, enhanced.avg_win_pct, ".3f", "+"),
        ("平均亏损(%)", baseline.avg_loss_pct, enhanced.avg_loss_pct, ".3f", "-"),
        ("盈亏比(PF)", baseline.profit_factor, enhanced.profit_factor, ".2f", "+"),
        ("最大回撤(%)", baseline.max_drawdown_pct, enhanced.max_drawdown_pct, ".2f", "-"),
        ("最大连亏次数", baseline.max_consecutive_losses, enhanced.max_consecutive_losses, "d", "-"),
        ("夏普比率", baseline.sharpe_ratio, enhanced.sharpe_ratio, ".3f", "+"),
        ("Calmar比率", baseline.calmar_ratio, enhanced.calmar_ratio, ".3f", "+"),
        ("平均持仓(bar)", baseline.avg_hold_bars, enhanced.avg_hold_bars, ".1f", "~"),
    ]

    print(f"{'指标':20s} {'基础策略':>12s} {'增强策略':>12s} {'变化':>12s} {'评估':>6s}")
    print("-" * 80)

    for name, base_val, enh_val, fmt, direction in items:
        delta = enh_val - base_val
        if isinstance(base_val, int):
            base_str = f"{base_val:{fmt}}"
            enh_str = f"{enh_val:{fmt}}"
            delta_str = f"{delta:+{fmt}}"
        else:
            base_str = f"{base_val:{fmt}}"
            enh_str = f"{enh_val:{fmt}}"
            delta_str = f"{delta:+{fmt}}"

        # 评估
        if direction == "+":
            better = delta > 0
        elif direction == "-":
            better = delta < 0
        else:
            better = None

        if better is None:
            eval_str = "  ~  "
        elif better:
            eval_str = " ✅ "
        else:
            eval_str = " ❌ "

        print(f"{name:20s} {base_str:>12s} {enh_str:>12s} {delta_str:>12s} {eval_str:>6s}")

    print()
    print("=" * 80)
    print("📈 各市场状态表现对比（增强策略）")
    print("=" * 80)
    for regime, stats in sorted(enhanced.regime_stats.items()):
        print(f"  {regime:20s}: {stats['trades']:3d} 笔  "
              f"胜率={stats['win_rate']:5.1f}%  "
              f"平均收益={stats['avg_pnl_pct']:+.3f}%  "
              f"累计收益={stats['total_pnl_pct']:+.2f}%")

    print()
    print("=" * 80)
    print("📉 各退出原因分布（增强策略）")
    print("=" * 80)
    exit_reasons = Counter(t.exit_reason for t in enhanced.trades)
    for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason:20s}: {count:3d} 次")

    print()


# ── 主函数 ──────────────────────────────────────────────────────────────────

def load_data(symbol: str, timeframe: str = "1H") -> pd.DataFrame:
    """加载K线数据"""
    data_dir = os.path.join(BASE_DIR, 'data', 'klines')
    filepath = os.path.join(data_dir, f"{symbol}_{timeframe}.csv")

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"数据文件不存在: {filepath}")

    df = pd.read_csv(filepath)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

    df = df.sort_index()
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description="增强器回测验证")
    parser.add_argument("--symbol", type=str, default="BTC", help="交易对")
    parser.add_argument("--timeframe", type=str, default="1H", help="时间周期")
    parser.add_argument("--output", type=str, default="", help="输出路径")
    args = parser.parse_args()

    symbol = args.symbol
    timeframe = args.timeframe

    print(f"🚀 开始回测: {symbol} {timeframe}")

    # 加载数据
    df = load_data(symbol, timeframe)
    print(f"📈 数据范围: {df.index[0]} → {df.index[-1]} ({len(df)} 根K线)")

    # 回测引擎
    engine = EnhancerBacktestEngine(
        symbol=symbol,
        timeframe=timeframe,
        initial_capital=10000.0,
        position_pct=0.1,
        max_hold_bars=120,
    )

    # 基础策略回测
    print(f"\n⚙️  运行基础策略回测...")
    baseline = engine.run(df, mode="baseline")

    # 增强策略回测
    print(f"🚀 运行增强策略回测...")
    enhanced = engine.run(df, mode="enhanced")

    # 打印对比
    print_comparison(baseline, enhanced)

    # 保存报告
    output_dir = os.path.join(BASE_DIR, '..', 'data', 'backtest')
    os.makedirs(output_dir, exist_ok=True)

    output_file = args.output or os.path.join(
        output_dir, f"enhancer_backtest_{symbol}_{timeframe}.json")
    generate_comparison_report(baseline, enhanced, output_file)

    print(f"💾 报告已保存: {output_file}")
    print()
    print("✅ 回测完成")


if __name__ == '__main__':
    main()
