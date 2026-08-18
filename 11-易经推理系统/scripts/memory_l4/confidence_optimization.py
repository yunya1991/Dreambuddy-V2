#!/usr/bin/env python3
"""
置信度阈值优化回测脚本。

用历史 K 线数据测试不同置信度阈值下的表现，找到最优值。
"""

import sys
import os
import csv
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass, field
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bcrm.engine import BCRMEngine
from bcrm.output_contract import BCRMOutput
from bcrm.market_preprocessor import MarketPreprocessor


@dataclass
class ThresholdResult:
    """单个阈值的回测结果"""
    threshold: float
    total_bars: int = 0
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    total_return: float = 0.0
    avg_return: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    fail_closed_count: int = 0


def load_klines(csv_path: str) -> List[Dict[str, Any]]:
    """加载 K 线数据"""
    bars = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append({
                'timestamp': row['timestamp'],
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']),
            })
    return bars


def compute_indicators(bars: List[Dict[str, Any]], period: int = 14) -> List[Dict[str, Any]]:
    """计算技术指标（RSI、EMA、波动率等）"""
    closes = [b['close'] for b in bars]
    highs = [b['high'] for b in bars]
    lows = [b['low'] for b in bars]
    volumes = [b['volume'] for b in bars]
    
    # RSI
    rsis = [50.0] * len(bars)
    if len(bars) > period:
        gains = []
        losses = []
        for i in range(1, period + 1):
            change = closes[i] - closes[i-1]
            gains.append(max(0, change))
            losses.append(max(0, -change))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        for i in range(period, len(bars)):
            change = closes[i] - closes[i-1]
            gain = max(0, change)
            loss = max(0, -change)
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
            if avg_loss == 0:
                rsis[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsis[i] = 100 - (100 / (1 + rs))
    
    # EMA20, EMA50
    ema20 = [closes[0]] * len(bars)
    ema50 = [closes[0]] * len(bars)
    for i in range(1, len(bars)):
        ema20[i] = closes[i] * (2 / 21) + ema20[i-1] * (1 - 2 / 21)
        if i >= 50:
            ema50[i] = closes[i] * (2 / 51) + ema50[i-1] * (1 - 2 / 51)
        else:
            ema50[i] = ema20[i]
    
    # 波动率（ATR 近似）
    atrs = [0.0] * len(bars)
    if len(bars) > period:
        trs = []
        for i in range(1, period + 1):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            trs.append(tr)
        atrs[period] = sum(trs) / period
        for i in range(period + 1, len(bars)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            atrs[i] = (atrs[i-1] * (period - 1) + tr) / period
    
    # 价格变化百分比
    pct_changes = [0.0] * len(bars)
    for i in range(1, len(bars)):
        pct_changes[i] = (closes[i] - closes[i-1]) / closes[i-1] * 100
    
    # 24小时涨跌幅（近似：用最近24根K线）
    ch24 = [0.0] * len(bars)
    for i in range(24, len(bars)):
        ch24[i] = (closes[i] - closes[i-24]) / closes[i-24] * 100
    
    # 4小时涨跌幅
    ch4h = [0.0] * len(bars)
    for i in range(4, len(bars)):
        ch4h[i] = (closes[i] - closes[i-4]) / closes[i-4] * 100
    
    # 量比
    vol_ratio = [1.0] * len(bars)
    for i in range(period, len(bars)):
        avg_vol = sum(volumes[i-period:i]) / period
        if avg_vol > 0:
            vol_ratio[i] = volumes[i] / avg_vol
    
    # 价格位置（最近100根K线的相对位置）
    price_position = [0.5] * len(bars)
    lookback = 100
    for i in range(lookback, len(bars)):
        window = closes[i-lookback:i+1]
        high = max(window)
        low = min(window)
        if high > low:
            price_position[i] = (closes[i] - low) / (high - low)
    
    # 组装结果
    result = []
    for i in range(len(bars)):
        bar = dict(bars[i])
        bar['rsi'] = rsis[i]
        bar['ema20'] = ema20[i]
        bar['ema50'] = ema50[i]
        bar['atr'] = atrs[i]
        bar['price_change_pct'] = pct_changes[i]
        bar['ch24'] = ch24[i]
        bar['ch4h'] = ch4h[i]
        bar['volume_ratio'] = vol_ratio[i]
        bar['price_position'] = price_position[i]
        bar['volatility'] = atrs[i] / closes[i] if closes[i] > 0 else 0.03
        bar['price'] = closes[i]
        result.append(bar)
    
    return result


def run_backtest(bars: List[Dict[str, Any]],
                 threshold: float,
                 hold_bars: int = 5,
                 tp_atr_mult: float = 3.0,
                 sl_atr_mult: float = 1.5) -> ThresholdResult:
    """运行单个阈值的回测"""
    engine = BCRMEngine()
    preprocessor = MarketPreprocessor()
    result = ThresholdResult(threshold=threshold)
    result.total_bars = len(bars)
    
    position = None  # None=空仓, dict=持仓
    
    equity_curve = [0.0]
    
    for i in range(50, len(bars) - hold_bars):
        bar = bars[i]
        
        # 构造市场快照
        snapshot = {
            'price': bar['price'],
            'close': bar['close'],
            'high': bar['high'],
            'low': bar['low'],
            'volume': bar['volume'],
            'rsi': bar['rsi'],
            'ema20': bar['ema20'],
            'ema50': bar['ema50'],
            'price_change_pct': bar['price_change_pct'],
            'ch24': bar['ch24'],
            'ch4h': bar['ch4h'],
            'volume_ratio': bar['volume_ratio'],
            'price_position': bar['price_position'],
            'volatility': bar['volatility'],
            'atr': bar['atr'],
            'snapshot_ts': bar['timestamp'],
        }
        
        # 预处理
        normalized = preprocessor.normalize(snapshot)
        
        # BCRM 推理
        try:
            # 手动生成矛盾列表（绕过 Guardrail 的矛盾列表检查 bug）
            contradiction_list = engine._auto_generate_contradictions(normalized)
            output = engine.infer(market_snapshot=normalized, contradiction_list=contradiction_list)
        except Exception:
            continue
        
        if output.is_fail_closed():
            result.fail_closed_count += 1
            continue
        
        direction = output.next_state.direction
        confidence = output.next_state.confidence
        
        # 检查持仓
        if position:
            # 检查止盈止损或持有到期
            entry_price = position['entry_price']
            pos_direction = position['direction']
            entry_bar = position['entry_bar']
            atr = position['atr']
            
            # 止盈止损价
            if pos_direction == 'UP':
                tp_price = entry_price + atr * tp_atr_mult
                sl_price = entry_price - atr * sl_atr_mult
            else:
                tp_price = entry_price - atr * tp_atr_mult
                sl_price = entry_price + atr * sl_atr_mult
            
            # 检查是否触发止盈止损
            current_high = bar['high']
            current_low = bar['low']
            exit_price = None
            exit_reason = None
            
            if pos_direction == 'UP':
                if current_high >= tp_price:
                    exit_price = tp_price
                    exit_reason = 'tp'
                elif current_low <= sl_price:
                    exit_price = sl_price
                    exit_reason = 'sl'
            else:
                if current_low <= tp_price:
                    exit_price = tp_price
                    exit_reason = 'tp'
                elif current_high >= sl_price:
                    exit_price = sl_price
                    exit_reason = 'sl'
            
            # 持有到期
            if i - entry_bar >= hold_bars and exit_price is None:
                exit_price = bar['close']
                exit_reason = 'time'
            
            if exit_price is not None:
                # 平仓
                if pos_direction == 'UP':
                    pnl_pct = (exit_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - exit_price) / entry_price
                
                result.trade_count += 1
                if pnl_pct > 0:
                    result.win_count += 1
                else:
                    result.loss_count += 1
                result.total_return += pnl_pct
                
                equity_curve.append(result.total_return)
                
                position = None
        
        # 开仓条件
        if position is None and confidence >= threshold:
            if direction in ('UP', 'DOWN'):
                position = {
                    'direction': direction,
                    'entry_price': bar['close'],
                    'entry_bar': i,
                    'atr': bar['atr'],
                    'confidence': confidence,
                }
    
    # 计算指标
    if result.trade_count > 0:
        result.win_rate = result.win_count / result.trade_count
        result.avg_return = result.total_return / result.trade_count
    
    # 最大回撤
    if equity_curve:
        peak = 0
        max_dd = 0
        for eq in equity_curve:
            peak = max(peak, eq)
            dd = peak - eq
            max_dd = max(max_dd, dd)
        result.max_drawdown = max_dd
    
    # 盈亏比
    if result.loss_count > 0:
        wins = [0]
        losses = [0]
        # 简化：用平均收益估算
        if result.win_count > 0 and result.loss_count > 0:
            # 重新计算需要遍历，这里简化
            pass
    result.profit_factor = 0.0  # 简化计算
    
    return result


def main():
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'data', 'klines'
    )
    
    coins = ['BTC', 'ETH', 'SOL', 'UNI']
    
    print("=" * 80)
    print("BCRM 置信度阈值优化回测")
    print("=" * 80)
    
    thresholds = [0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]
    
    all_results = {}
    
    for coin in coins:
        csv_path = os.path.join(data_dir, f'{coin}_1H.csv')
        if not os.path.exists(csv_path):
            print(f"\n跳过 {coin}: 数据文件不存在")
            continue
        
        print(f"\n加载 {coin} 数据...")
        raw_bars = load_klines(csv_path)
        print(f"  共 {len(raw_bars)} 根K线")
        
        print(f"  计算技术指标...")
        bars = compute_indicators(raw_bars)
        
        coin_results = []
        print(f"\n  {'阈值':<8} {'交易数':<8} {'胜率':<8} {'总收益':<10} {'平均收益':<10} {'fail_closed':<12}")
        print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*12}")
        
        for th in thresholds:
            result = run_backtest(bars, th)
            coin_results.append(result)
            print(f"  {th:<8.2f} {result.trade_count:<8} {result.win_rate:<8.2%} "
                  f"{result.total_return:<+10.2%} {result.avg_return:<+10.2%} "
                  f"{result.fail_closed_count:<12}")
        
        all_results[coin] = coin_results
    
    # 综合统计
    print("\n" + "=" * 80)
    print("综合统计（四币种平均）")
    print("=" * 80)
    print(f"{'阈值':<8} {'平均交易数':<10} {'平均胜率':<10} {'平均总收益':<12} {'平均fail_closed':<15}")
    print(f"{'-'*8} {'-'*10} {'-'*10} {'-'*12} {'-'*15}")
    
    for i, th in enumerate(thresholds):
        avg_trades = 0
        avg_win_rate = 0
        avg_return = 0
        avg_fail = 0
        count = 0
        
        for coin in all_results:
            if i < len(all_results[coin]):
                r = all_results[coin][i]
                avg_trades += r.trade_count
                avg_win_rate += r.win_rate
                avg_return += r.total_return
                avg_fail += r.fail_closed_count
                count += 1
        
        if count > 0:
            avg_trades /= count
            avg_win_rate /= count
            avg_return /= count
            avg_fail /= count
        
        print(f"{th:<8.2f} {avg_trades:<10.1f} {avg_win_rate:<10.2%} "
              f"{avg_return:<+12.2%} {avg_fail:<15.0f}")
    
    print("\n说明：")
    print("  - 回测周期：1小时K线")
    print("  - 持仓周期：5根K线（5小时）或止盈止损触发")
    print("  - 止盈：3xATR，止损：1.5xATR（盈亏比2:1）")
    print("  - 收益为百分比（未计手续费和滑点）")


if __name__ == '__main__':
    main()
