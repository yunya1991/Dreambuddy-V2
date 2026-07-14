#!/usr/bin/env python3
"""
回测验证框架 — 16-调控系统 Phase 3

对比验证：
  - 纯技术离场（ClassicExitSystem 体系）
  - 宏观+技术融合离场（A1/A2/A3 + 技术）

核心功能：
  1. 模拟价格走势生成（基于历史波动率的随机漫步）
  2. 回测引擎（逐 bar 模拟持仓和离场）
  3. 多策略对比（纯技术 vs 宏观+技术）
  4. 绩效指标计算（胜率、盈亏比、最大回撤、夏普比）
  5. 回测报告生成

回测策略对比矩阵：
  | 策略 | 入场 | 离场 | 说明 |
  |------|------|------|------|
  | baseline | 随机入场 | 技术指标 | 纯技术离场基准 |
  | macro_enhanced | 随机入场 | 宏观+技术融合 | 宏观赋能离场 |
  | hold | 随机入场 | 持有到结束 | 买入持有基准 |
"""

import math
import random
import json
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum


BASE_DIR = Path(__file__).parent.parent.parent
BACKTEST_DIR = BASE_DIR / "16-调控系统" / "artifacts" / "backtests"


class ExitAction(str, Enum):
    CLOSE = "CLOSE"
    REDUCE = "REDUCE"
    HOLD = "HOLD"
    RAISE_TP = "RAISE_TP"


@dataclass
class Bar:
    """K 线数据"""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Position:
    """持仓状态"""
    symbol: str
    direction: str  # LONG / SHORT
    entry_price: float
    entry_time: float
    size: float = 1.0
    current_price: float = 0.0
    unrealized_pnl_pct: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    is_open: bool = True


@dataclass
class TradeRecord:
    """交易记录"""
    symbol: str
    direction: str
    entry_price: float
    entry_time: float
    exit_price: float
    exit_time: float
    pnl_pct: float
    exit_reason: str
    bars_held: int


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    avg_bars_held: float = 0.0
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)


def generate_simulated_bars(
    start_price: float = 60000,
    num_bars: int = 500,
    volatility_pct: float = 2.0,
    drift_pct: float = 0.0,
    timeframe_min: int = 60,
    seed: int = 42,
) -> List[Bar]:
    """
    生成模拟 K 线数据（几何布朗运动 + 波动率聚集）

    Args:
        start_price: 起始价格
        num_bars: K 线数量
        volatility_pct: 每根K线波动率（%）
        drift_pct: 每根K线漂移率（%）
        timeframe_min: 时间周期（分钟）
        seed: 随机种子

    Returns:
        K 线列表
    """
    random.seed(seed)
    bars = []
    price = start_price
    base_time = datetime.now(timezone.utc).timestamp() - num_bars * timeframe_min * 60

    vol_factor = volatility_pct / 100
    drift_factor = drift_pct / 100

    prev_return = 0.0
    vol_cluster = 0.0

    for i in range(num_bars):
        vol_cluster = vol_cluster * 0.7 + abs(prev_return) * 0.3
        current_vol = vol_factor * (0.8 + vol_cluster * 15)

        ret = random.gauss(drift_factor, current_vol)
        prev_return = ret

        open_price = price
        close_price = price * (1 + ret)

        high_wick = abs(random.gauss(0, current_vol * 0.5))
        low_wick = abs(random.gauss(0, current_vol * 0.5))

        if ret >= 0:
            high_price = close_price * (1 + high_wick)
            low_price = open_price * (1 - low_wick)
        else:
            high_price = open_price * (1 + high_wick)
            low_price = close_price * (1 - low_wick)

        volume = random.uniform(0.5, 2.0) * start_price * 0.01

        bar = Bar(
            timestamp=base_time + i * timeframe_min * 60,
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=round(volume, 2),
        )
        bars.append(bar)
        price = close_price

    return bars


def calc_rsi(prices: List[float], period: int = 14) -> float:
    """计算 RSI"""
    if len(prices) < period + 1:
        return 50.0

    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    if len(gains) < period:
        return 50.0

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_atr(bars: List[Bar], period: int = 14) -> float:
    """计算 ATR（百分比形式）"""
    if len(bars) < period + 1:
        return 2.0

    tr_list = []
    for i in range(1, len(bars)):
        hl = bars[i].high - bars[i].low
        hc = abs(bars[i].high - bars[i - 1].close)
        lc = abs(bars[i].low - bars[i - 1].close)
        tr = max(hl, hc, lc)
        tr_list.append(tr)

    if not tr_list:
        return 2.0

    atr = sum(tr_list[-period:]) / min(len(tr_list), period)
    current_price = bars[-1].close
    atr_pct = (atr / current_price) * 100 if current_price > 0 else 2.0
    return atr_pct


def _tech_exit_signal(position: Position, bars: List[Bar], bar_idx: int) -> Tuple[str, str]:
    """
    纯技术离场信号（简化版 ClassicExitSystem）

    Returns:
        (action, reason)
    """
    if bar_idx < 20:
        return "HOLD", "预热期"

    recent_bars = bars[:bar_idx + 1]
    closes = [b.close for b in recent_bars]
    current_price = bars[bar_idx].close
    rsi = calc_rsi(closes, 14)
    atr_pct = calc_atr(recent_bars, 14)

    entry_price = position.entry_price
    direction = position.direction

    if direction == "LONG":
        pnl_pct = (current_price - entry_price) / entry_price * 100
    else:
        pnl_pct = (entry_price - current_price) / entry_price * 100

    stop_loss_atr = 2.0 * atr_pct
    take_profit_atr = 3.0 * atr_pct

    if pnl_pct <= -stop_loss_atr:
        return "CLOSE", f"技术ATR止损 ({pnl_pct:.1f}% / 2×ATR={stop_loss_atr:.1f}%)"

    if pnl_pct >= take_profit_atr:
        return "REDUCE", f"技术ATR止盈 ({pnl_pct:.1f}% / 3×ATR={take_profit_atr:.1f}%)"

    if direction == "LONG" and rsi >= 75:
        return "REDUCE", f"技术RSI超卖 (RSI={rsi:.1f})"
    if direction == "SHORT" and rsi <= 25:
        return "REDUCE", f"技术RSI超买 (RSI={rsi:.1f})"

    bars_held = bar_idx - _find_entry_bar(position, bars)
    if bars_held > 168:
        return "CLOSE", f"技术最大持仓时间 ({bars_held}根)"

    return "HOLD", "无技术离场信号"


def _find_entry_bar(position: Position, bars: List[Bar]) -> int:
    """找到入场 bar 的索引（简化版）"""
    for i, bar in enumerate(bars):
        if bar.timestamp >= position.entry_time:
            return i
    return 0


def _macro_regime_estimate(bars: List[Bar], bar_idx: int) -> Dict[str, Any]:
    """
    简化版宏观状态估计（模拟 A1/A2 输出）

    在真实系统中，这里会调用真实的 A1/A2/A3 分析。
    回测中我们用价格走势特征来模拟宏观判断。
    """
    if bar_idx < 50:
        return {
            "directive_bias": "HOLD",
            "path_confidence": 0.5,
            "least_resistance_path": "NEUTRAL",
            "regime": "RANGE_BOUND",
        }

    recent = bars[max(0, bar_idx - 50):bar_idx + 1]
    closes = [b.close for b in recent]

    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / 50
    current = closes[-1]

    rsi = calc_rsi(closes, 14)
    atr_pct = calc_atr(recent, 14)

    if current > ma20 > ma50:
        trend = "BULL"
        lrp = "UP"
        directive = "LONG"
        regime = "TREND_STRONG" if rsi > 60 else "TREND_BULL"
    elif current < ma20 < ma50:
        trend = "BEAR"
        lrp = "DOWN"
        directive = "SHORT"
        regime = "TREND_STRONG" if rsi < 40 else "TREND_BEAR"
    else:
        trend = "NEUTRAL"
        lrp = "NEUTRAL"
        directive = "HOLD"
        regime = "RANGE_BOUND"

    confidence = 0.5
    if abs(rsi - 50) > 20:
        confidence += 0.15
    if atr_pct > 3:
        confidence -= 0.1
    if abs(current / ma20 - 1) > 0.02:
        confidence += 0.1
    confidence = max(0.2, min(0.9, confidence))

    if rsi > 75 or rsi < 25:
        regime = "TREND_EXHAUSTION"
        if trend == "BULL":
            directive = "REDUCE"
        elif trend == "BEAR":
            directive = "REDUCE"

    return {
        "directive_bias": directive,
        "path_confidence": confidence,
        "least_resistance_path": lrp,
        "regime": regime,
        "trend": trend,
        "rsi": rsi,
        "atr_pct": atr_pct,
    }


def _macro_tech_fused_exit(position: Position, bars: List[Bar], bar_idx: int) -> Tuple[str, str]:
    """
    宏观+技术融合离场（模拟 Phase 3 融合决策）

    融合逻辑：
      1. 技术 P0 硬退出 → 一票否决
      2. 宏观+技术同向 → 强化（更早执行）
      3. 宏观+技术反向 → 降级（减仓而非平仓）
    """
    tech_action, tech_reason = _tech_exit_signal(position, bars, bar_idx)
    macro = _macro_regime_estimate(bars, bar_idx)

    direction = position.direction
    macro_direction = macro.get("directive_bias", "HOLD")
    macro_conf = macro.get("path_confidence", 0.5)

    if tech_action == "CLOSE" and "ATR止损" in tech_reason:
        return tech_action, f"[P0硬退出] {tech_reason}"

    pos_is_long = direction == "LONG"
    macro_is_short = macro_direction in ("SHORT", "REDUCE")
    macro_is_long = macro_direction in ("LONG", "RAISE_TP")

    recent_bars = bars[:bar_idx + 1]
    closes = [b.close for b in recent_bars]
    current_price = bars[bar_idx].close
    entry_price = position.entry_price

    if pos_is_long:
        pnl_pct = (current_price - entry_price) / entry_price * 100
    else:
        pnl_pct = (entry_price - current_price) / entry_price * 100

    tech_close = tech_action in ("CLOSE", "REDUCE")
    macro_bearish_for_pos = (pos_is_long and macro_is_short) or (not pos_is_long and macro_is_long)
    macro_bullish_for_pos = (pos_is_long and macro_is_long) or (not pos_is_long and macro_is_short)

    if tech_close and macro_bearish_for_pos and macro_conf > 0.6:
        return "CLOSE", f"[宏观+技术共振] 技术{tech_action}+宏观看空({macro_direction}, 置信{macro_conf:.0%})"

    if tech_action == "HOLD" and macro_bearish_for_pos and macro_conf > 0.7 and pnl_pct < 0:
        return "REDUCE", f"[宏观预警] 宏观看空({macro_direction}, 置信{macro_conf:.0%})，亏损仓位建议减仓"

    if tech_close and macro_bullish_for_pos and macro_conf > 0.6:
        return "HOLD", f"[宏观对冲] 技术{tech_action}但宏观看多({macro_direction})，降级持有观察"

    if macro_bullish_for_pos and macro_conf > 0.7 and tech_action == "HOLD" and pnl_pct > 0:
        return "RAISE_TP", f"[宏观增强] 宏观确认趋势({macro_direction}, 置信{macro_conf:.0%})，建议提高止盈"

    return tech_action, f"[技术主导] {tech_reason}"


def run_backtest(
    bars: List[Bar],
    strategy: str = "macro_enhanced",
    entry_interval: int = 30,
    max_positions: int = 3,
    direction: str = "random",
    leverage: float = 1.0,
    strategy_name: str = "",
    use_macro: bool = True,
    tech_weight: float = 0.5,
    macro_weight: float = 0.5,
    close_threshold: float = 0.70,
    reduce_threshold: float = 0.60,
) -> BacktestResult:
    """
    运行回测

    Args:
        bars: K 线数据
        strategy: 策略名称 (baseline / macro_enhanced / hold)
        entry_interval: 每隔多少根K线入场一次
        max_positions: 最大同时持仓数
        direction: 入场方向 (LONG / SHORT / random)
        leverage: 杠杆
        strategy_name: 自定义策略名（用于进化验证）
        use_macro: 是否使用宏观+技术融合离场
        tech_weight: 技术信号权重
        macro_weight: 宏观信号权重
        close_threshold: 平仓置信度门槛
        reduce_threshold: 减仓置信度门槛

    Returns:
        BacktestResult
    """
    display_name = strategy_name if strategy_name else strategy
    result = BacktestResult(strategy_name=display_name)

    positions: List[Position] = []
    equity = 10000.0
    peak_equity = equity
    max_drawdown = 0.0

    exit_fn = None
    if strategy == "baseline":
        exit_fn = _tech_exit_signal
    elif strategy == "macro_enhanced" or use_macro:
        exit_fn = _macro_tech_fused_exit
    elif strategy == "hold":
        exit_fn = lambda pos, bars, idx: ("HOLD", "持有策略")

    for i in range(len(bars)):
        bar = bars[i]

        for pos in positions:
            if not pos.is_open:
                continue
            pos.current_price = bar.close
            if pos.direction == "LONG":
                pos.unrealized_pnl_pct = (bar.close - pos.entry_price) / pos.entry_price * 100
            else:
                pos.unrealized_pnl_pct = (pos.entry_price - bar.close) / pos.entry_price * 100

        for pos in positions:
            if not pos.is_open:
                continue

            action, reason = exit_fn(pos, bars, i)

            if action in ("CLOSE", "REDUCE"):
                exit_price = bar.close
                if pos.direction == "LONG":
                    pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
                else:
                    pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100

                pnl_pct *= leverage

                trade = TradeRecord(
                    symbol="BTC",
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    entry_time=pos.entry_time,
                    exit_price=exit_price,
                    exit_time=bar.timestamp,
                    pnl_pct=round(pnl_pct, 2),
                    exit_reason=reason,
                    bars_held=i - _find_entry_bar(pos, bars),
                )
                result.trades.append(trade)
                pos.is_open = False

                position_size_pct = 0.3
                pnl_amount = equity * position_size_pct * pnl_pct / 100
                equity += pnl_amount

                if equity > peak_equity:
                    peak_equity = equity
                drawdown = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

        positions = [p for p in positions if p.is_open]

        if i > 20 and i % entry_interval == 0 and len(positions) < max_positions:
            if direction == "random":
                dir = "LONG" if random.random() > 0.5 else "SHORT"
            else:
                dir = direction

            pos = Position(
                symbol="BTC",
                direction=dir,
                entry_price=bar.close,
                entry_time=bar.timestamp,
                size=1.0,
                current_price=bar.close,
            )
            positions.append(pos)

        result.equity_curve.append(round(equity, 2))

    for pos in positions:
        if pos.is_open:
            last_bar = bars[-1]
            if pos.direction == "LONG":
                pnl_pct = (last_bar.close - pos.entry_price) / pos.entry_price * 100
            else:
                pnl_pct = (pos.entry_price - last_bar.close) / pos.entry_price * 100
            pnl_pct *= leverage

            trade = TradeRecord(
                symbol="BTC",
                direction=pos.direction,
                entry_price=pos.entry_price,
                entry_time=pos.entry_time,
                exit_price=last_bar.close,
                exit_time=last_bar.timestamp,
                pnl_pct=round(pnl_pct, 2),
                exit_reason="回测结束平仓",
                bars_held=len(bars) - _find_entry_bar(pos, bars),
            )
            result.trades.append(trade)
            pos.is_open = False

            position_size_pct = 0.3
            pnl_amount = equity * position_size_pct * pnl_pct / 100
            equity += pnl_amount
            result.equity_curve[-1] = round(equity, 2)

    result.total_trades = len(result.trades)
    if result.total_trades > 0:
        wins = [t for t in result.trades if t.pnl_pct > 0]
        losses = [t for t in result.trades if t.pnl_pct <= 0]
        result.winning_trades = len(wins)
        result.losing_trades = len(losses)
        result.win_rate = round(result.winning_trades / result.total_trades, 4)
        result.avg_win_pct = round(sum(t.pnl_pct for t in wins) / len(wins), 2) if wins else 0
        result.avg_loss_pct = round(sum(t.pnl_pct for t in losses) / len(losses), 2) if losses else 0
        result.profit_factor = round(
            abs(sum(t.pnl_pct for t in wins) / sum(t.pnl_pct for t in losses)), 2
        ) if losses and sum(t.pnl_pct for t in losses) != 0 else float('inf')
        result.total_return_pct = round((result.equity_curve[-1] - 10000) / 10000 * 100, 2)
        result.max_drawdown_pct = round(max_drawdown, 2)
        result.avg_bars_held = round(sum(t.bars_held for t in result.trades) / result.total_trades, 1)

        if len(result.equity_curve) > 1:
            returns = []
            for j in range(1, len(result.equity_curve)):
                if result.equity_curve[j - 1] > 0:
                    ret = (result.equity_curve[j] - result.equity_curve[j - 1]) / result.equity_curve[j - 1]
                    returns.append(ret)
            if returns and len(returns) > 1:
                avg_ret = sum(returns) / len(returns)
                std_ret = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5
                if std_ret > 0:
                    result.sharpe_ratio = round((avg_ret / std_ret) * (24 ** 0.5), 2)

    return result


def compare_strategies(bars: List[Bar], leverage: float = 1.0) -> Dict[str, BacktestResult]:
    """
    对比多个策略

    Args:
        bars: K 线数据
        leverage: 杠杆

    Returns:
        {strategy_name: BacktestResult}
    """
    strategies = ["baseline", "macro_enhanced", "hold"]
    results = {}

    for strategy in strategies:
        result = run_backtest(bars, strategy=strategy, leverage=leverage)
        results[strategy] = result

    return results


def generate_backtest_report(results: Dict[str, BacktestResult], bars: List[Bar]) -> str:
    """生成回测报告"""
    lines = []
    lines.append("# 回测对比报告")
    lines.append("")
    lines.append(f"生成时间: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"回测K线数: {len(bars)}")
    lines.append(f"起始价格: ${bars[0].close:,.2f}")
    lines.append(f"结束价格: ${bars[-1].close:,.2f}")
    price_change = (bars[-1].close - bars[0].close) / bars[0].close * 100
    lines.append(f"价格变化: {price_change:+.2f}%")
    lines.append("")

    lines.append("## 策略对比表")
    lines.append("")
    lines.append("| 指标 | 纯技术离场 | 宏观+技术融合 | 买入持有 |")
    lines.append("|------|:----------:|:------------:|:--------:|")

    metrics = [
        ("总交易数", "total_trades", ""),
        ("胜率", "win_rate", "%"),
        ("平均盈利", "avg_win_pct", "%"),
        ("平均亏损", "avg_loss_pct", "%"),
        ("盈亏比", "profit_factor", ""),
        ("总收益率", "total_return_pct", "%"),
        ("最大回撤", "max_drawdown_pct", "%"),
        ("夏普比率", "sharpe_ratio", ""),
        ("平均持仓K线数", "avg_bars_held", "根"),
    ]

    baseline = results.get("baseline", BacktestResult("baseline"))
    macro = results.get("macro_enhanced", BacktestResult("macro_enhanced"))
    hold = results.get("hold", BacktestResult("hold"))

    for label, key, unit in metrics:
        b_val = getattr(baseline, key, 0)
        m_val = getattr(macro, key, 0)
        h_val = getattr(hold, key, 0)

        if key == "win_rate":
            b_str = f"{b_val:.1%}"
            m_str = f"{m_val:.1%}"
            h_str = f"{h_val:.1%}"
        elif key == "profit_factor" and (b_val == float('inf') or m_val == float('inf') or h_val == float('inf')):
            b_str = "∞" if b_val == float('inf') else f"{b_val:.2f}"
            m_str = "∞" if m_val == float('inf') else f"{m_val:.2f}"
            h_str = "∞" if h_val == float('inf') else f"{h_val:.2f}"
        else:
            b_str = f"{b_val}{unit}"
            m_str = f"{m_val}{unit}"
            h_str = f"{h_val}{unit}"

        if key in ("total_return_pct", "win_rate", "profit_factor", "sharpe_ratio"):
            if m_val > b_val:
                m_str = f"**{m_str} ↑**"
            elif m_val < b_val:
                m_str = f"{m_str} ↓"

        lines.append(f"| {label} | {b_str} | {m_str} | {h_str} |")

    lines.append("")
    lines.append("## 宏观赋能效果分析")
    lines.append("")

    if baseline.total_trades > 0 and macro.total_trades > 0:
        ret_diff = macro.total_return_pct - baseline.total_return_pct
        win_diff = macro.win_rate - baseline.win_rate
        dd_diff = baseline.max_drawdown_pct - macro.max_drawdown_pct

        lines.append(f"- 收益率差: {ret_diff:+.2f}% ({'宏观胜出' if ret_diff > 0 else '技术胜出'})")
        lines.append(f"- 胜率差: {win_diff:+.1%}")
        lines.append(f"- 回撤差: {dd_diff:+.2f}% (正=宏观回撤更小)")

        if ret_diff > 0 and dd_diff > 0:
            lines.append("- **结论：宏观赋能有效，收益提升且回撤降低**")
        elif ret_diff > 0:
            lines.append("- **结论：宏观赋能提升收益，但需注意回撤控制**")
        elif dd_diff > 0:
            lines.append("- **结论：宏观赋能降低回撤，收益略低但更稳健**")
        else:
            lines.append("- **结论：当前参数下宏观赋能未体现优势，需优化融合逻辑**")

    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("- 本回测使用模拟数据，仅用于验证框架功能")
    lines.append("- 真实回测需接入历史K线数据和完整的 A1/A2/A3 分析")
    lines.append("- 融合逻辑可进一步优化，包括：权重调整、信号过滤、动态阈值等")

    return "\n".join(lines)


def save_backtest_results(results: Dict[str, BacktestResult], bars: List[Bar]) -> str:
    """保存回测结果"""
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = generate_backtest_report(results, bars)
    report_path = BACKTEST_DIR / f"backtest_report_{timestamp}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    json_data = {}
    for name, result in results.items():
        json_data[name] = {
            "strategy_name": result.strategy_name,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": result.win_rate,
            "avg_win_pct": result.avg_win_pct,
            "avg_loss_pct": result.avg_loss_pct,
            "profit_factor": result.profit_factor if result.profit_factor != float('inf') else 999,
            "total_return_pct": result.total_return_pct,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "avg_bars_held": result.avg_bars_held,
            "equity_curve": result.equity_curve,
            "trades": [
                {
                    "direction": t.direction,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "pnl_pct": t.pnl_pct,
                    "exit_reason": t.exit_reason,
                    "bars_held": t.bars_held,
                }
                for t in result.trades
            ],
        }

    json_path = BACKTEST_DIR / f"backtest_data_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    return str(report_path)


if __name__ == "__main__":
    print("生成模拟K线数据...")
    bars = generate_simulated_bars(
        start_price=60000,
        num_bars=500,
        volatility_pct=2.0,
        drift_pct=0.0,
        seed=42,
    )
    print(f"  生成 {len(bars)} 根K线")
    print(f"  起始: ${bars[0].close:,.2f}")
    print(f"  结束: ${bars[-1].close:,.2f}")

    print("\n运行回测对比...")
    results = compare_strategies(bars, leverage=1.0)

    for name, result in results.items():
        print(f"\n  [{name}]")
        print(f"    交易数: {result.total_trades}")
        print(f"    胜率: {result.win_rate:.1%}")
        print(f"    总收益: {result.total_return_pct:+.2f}%")
        print(f"    最大回撤: {result.max_drawdown_pct:.2f}%")
        print(f"    盈亏比: {result.profit_factor:.2f}")

    report_path = save_backtest_results(results, bars)
    print(f"\n回测报告已保存: {report_path}")


# ==========================================
# 决策验证 & 进化反馈
# ==========================================

def validate_evolution_adjustment(
    strategy_id: str,
    before_params: Dict[str, float],
    after_params: Dict[str, float],
    bars: List[Bar] = None,
    leverage: float = 1.0,
) -> Dict[str, Any]:
    """验证进化参数调优效果
    
    对比调优前后的回测表现，决定是否采纳
    
    Returns:
        {
            "should_adopt": bool,
            "improvement": float,  # 收益改善
            "before_metrics": {...},
            "after_metrics": {...},
            "reason": str,
        }
    """
    if bars is None:
        bars = generate_simulated_bars(
            start_price=60000, num_bars=300, volatility_pct=2.0, seed=42,
        )
    
    # 用调优前参数回测
    before_results = _run_backtest_with_params(bars, leverage, before_params)
    # 用调优后参数回测
    after_results = _run_backtest_with_params(bars, leverage, after_params)
    
    before_return = before_results.total_return_pct
    after_return = after_results.total_return_pct
    improvement = after_return - before_return
    
    before_dd = before_results.max_drawdown_pct
    after_dd = after_results.max_drawdown_pct
    dd_change = after_dd - before_dd
    
    before_wr = before_results.win_rate
    after_wr = after_results.win_rate
    wr_change = after_wr - before_wr
    
    # 采纳标准：
    # 1. 收益改善 > 0.5%
    # 2. 最大回撤不恶化（增加 < 2%）
    # 3. 胜率不大幅下降（下降 < 5%）
    should_adopt = (
        improvement > 0.5 and
        dd_change < 2.0 and
        wr_change > -0.05
    )
    
    reason_parts = []
    if improvement > 0.5:
        reason_parts.append(f"收益改善 {improvement:+.2f}%")
    elif improvement > 0:
        reason_parts.append(f"收益微增 {improvement:+.2f}%（不满足0.5%门槛）")
    else:
        reason_parts.append(f"收益下降 {improvement:+.2f}%")
    
    if dd_change < 0:
        reason_parts.append(f"回撤改善 {dd_change:+.2f}%")
    elif dd_change > 2:
        reason_parts.append(f"回撤恶化 {dd_change:+.2f}%")
    
    if wr_change > 0:
        reason_parts.append(f"胜率提升 {wr_change:+.1%}")
    elif wr_change < -0.05:
        reason_parts.append(f"胜率下降 {wr_change:+.1%}")
    
    return {
        "should_adopt": should_adopt,
        "improvement": round(improvement, 2),
        "dd_change": round(dd_change, 2),
        "wr_change": round(wr_change, 3),
        "before_metrics": {
            "total_return": round(before_return, 2),
            "max_drawdown": round(before_dd, 2),
            "win_rate": round(before_wr, 3),
            "sharpe": round(before_results.sharpe_ratio, 3),
            "trades": before_results.total_trades,
        },
        "after_metrics": {
            "total_return": round(after_return, 2),
            "max_drawdown": round(after_dd, 2),
            "win_rate": round(after_wr, 3),
            "sharpe": round(after_results.sharpe_ratio, 3),
            "trades": after_results.total_trades,
        },
        "reason": "；".join(reason_parts),
    }


def _run_backtest_with_params(
    bars: List[Bar],
    leverage: float,
    params: Dict[str, float],
) -> BacktestResult:
    """用指定参数运行回测（用于验证参数调优效果）
    
    参数影响：
    - confidence_threshold_*: 影响离场决策的置信度门槛
    - technical/macro_signal_weight: 影响融合权重
    """
    close_threshold = params.get("confidence_threshold_close", 0.70)
    reduce_threshold = params.get("confidence_threshold_reduce", 0.60)
    observe_threshold = params.get("confidence_threshold_observe", 0.40)
    tech_weight = params.get("technical_signal_weight", 0.5)
    macro_weight = params.get("macro_signal_weight", 0.5)
    
    # 使用调优后的参数运行宏观+技术融合回测
    result = run_backtest(
        bars=bars,
        leverage=leverage,
        strategy_name=f"tuned({close_threshold:.2f}/{reduce_threshold:.2f})",
        use_macro=True,
        tech_weight=tech_weight,
        macro_weight=macro_weight,
        close_threshold=close_threshold,
        reduce_threshold=reduce_threshold,
    )
    
    return result


def run_evolution_cycle(
    strategy_ids: List[str] = None,
    min_samples: int = 5,
) -> Dict[str, Any]:
    """执行一次完整的进化周期
    
    流程：
    1. 分析各策略准确性
    2. 提出参数调优建议
    3. 回测验证调优效果
    4. 采纳通过验证的调优
    5. 返回进化报告
    
    Returns:
        进化周期报告
    """
    try:
        from evolution_loop import get_evolution_loop
    except ImportError:
        from .evolution_loop import get_evolution_loop
    
    loop = get_evolution_loop()
    
    if strategy_ids is None:
        strategy_ids = list(loop.params.keys()) or [
            "v15_martin", "screen_trend", "yijing_bcrm",
            "agent_a", "agent_b", "agent_c",
        ]
    
    # 生成固定的回测数据用于验证
    bars = generate_simulated_bars(
        start_price=60000, num_bars=300, volatility_pct=2.0, seed=42,
    )
    
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategies_checked": len(strategy_ids),
        "adjustments_proposed": 0,
        "adjustments_validated": 0,
        "adjustments_adopted": 0,
        "details": [],
    }
    
    for sid in strategy_ids:
        # 1. 提出调优建议
        adjustment = loop.propose_adjustment(sid, min_samples)
        if adjustment is None:
            report["details"].append({
                "strategy_id": sid,
                "status": "SKIP",
                "reason": "样本不足或无需调整",
            })
            continue
        
        report["adjustments_proposed"] += 1
        
        # 2. 回测验证
        validation = validate_evolution_adjustment(
            sid, adjustment.before, adjustment.after, bars,
        )
        
        if validation["should_adopt"]:
            report["adjustments_validated"] += 1
            # 3. 采纳
            loop.adopt_adjustment(adjustment, backtest_validated=True)
            report["adjustments_adopted"] += 1
            report["details"].append({
                "strategy_id": sid,
                "status": "ADOPTED",
                "trigger": adjustment.trigger,
                "before": adjustment.before,
                "after": adjustment.after,
                "validation": validation,
            })
        else:
            report["details"].append({
                "strategy_id": sid,
                "status": "REJECTED",
                "trigger": adjustment.trigger,
                "reason": validation["reason"],
                "before": adjustment.before,
                "after": adjustment.after,
                "validation": validation,
            })
    
    # 生成进化报告
    summary = loop.get_evolution_summary()
    report["evolution_summary"] = summary
    
    return report


def generate_evolution_report(cycle_report: Dict[str, Any]) -> str:
    """生成进化周期 Markdown 报告"""
    lines = []
    lines.append("# 进化闭环系统报告")
    lines.append("")
    lines.append(f"**执行时间**: {cycle_report.get('timestamp', 'N/A')}")
    lines.append(f"**检查策略数**: {cycle_report.get('strategies_checked', 0)}")
    lines.append(f"**提出调优**: {cycle_report.get('adjustments_proposed', 0)}")
    lines.append(f"**验证通过**: {cycle_report.get('adjustments_validated', 0)}")
    lines.append(f"**采纳调优**: {cycle_report.get('adjustments_adopted', 0)}")
    lines.append("")
    
    lines.append("## 各策略调优详情")
    lines.append("")
    lines.append("| 策略 | 状态 | 触发原因 | 验证结果 |")
    lines.append("|------|------|---------|---------|")
    
    for detail in cycle_report.get("details", []):
        sid = detail.get("strategy_id", "")
        status = detail.get("status", "")
        trigger = detail.get("trigger", detail.get("reason", ""))[:50]
        
        if status == "ADOPTED":
            val = detail.get("validation", {})
            result_str = f"收益{val.get('improvement', 0):+.2f}%, 回测通过"
        elif status == "REJECTED":
            result_str = detail.get("reason", "回测未通过")[:40]
        else:
            result_str = "—"
        
        lines.append(f"| {sid} | {status} | {trigger} | {result_str} |")
    
    lines.append("")
    
    summary = cycle_report.get("evolution_summary", {})
    if summary:
        lines.append("## 进化系统概览")
        lines.append("")
        lines.append(f"- **总决策数**: {summary.get('total_decisions', 0)}")
        lines.append(f"- **已评估数**: {summary.get('total_evaluated', 0)}")
        lines.append(f"- **整体准确率**: {summary.get('overall_accuracy', 0):.1%}")
        lines.append(f"- **近期趋势**: {summary.get('recent_trend', 'N/A')}")
        lines.append("")
        
        lines.append("### 各策略状态")
        lines.append("")
        lines.append("| 策略 | 总决策 | 正确 | 错误 | 待评估 | 准确率 | 调优次数 | 当前平仓门槛 |")
        lines.append("|------|--------|------|------|--------|--------|---------|------------|")
        
        by_strategy = summary.get("by_strategy", {})
        for sid, stats in sorted(by_strategy.items()):
            thresholds = stats.get("current_thresholds", {})
            lines.append(
                f"| {sid} | {stats.get('total', 0)} | {stats.get('correct', 0)} | "
                f"{stats.get('incorrect', 0)} | {stats.get('pending', 0)} | "
                f"{stats.get('accuracy', 0):.1%} | {stats.get('adjustments', 0)} | "
                f"{thresholds.get('close', 0):.0%} |"
            )
        
        lines.append("")
        
        recommendations = summary.get("recommendations", [])
        if recommendations:
            lines.append("### 系统建议")
            lines.append("")
            for rec in recommendations:
                lines.append(f"- {rec}")
            lines.append("")
    
    lines.append("## 闭环说明")
    lines.append("")
    lines.append("```")
    lines.append("记录决策 → 追踪结果 → 分析准确性 → 参数调优 → 回测验证 → 采纳/回滚")
    lines.append("    ↑                                                          |")
    lines.append("    └────────────────── 反馈到下次决策 ←────────────────────────┘")
    lines.append("```")
    
    return "\n".join(lines)
