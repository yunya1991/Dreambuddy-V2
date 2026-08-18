#!/usr/bin/env python3
"""
详细置信度分析：按置信度区间统计胜率和收益。
"""

import sys
import os
import csv
from typing import List, Dict, Any
from dataclasses import dataclass, field
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bcrm.engine import BCRMEngine
from bcrm.market_preprocessor import MarketPreprocessor


@dataclass
class ConfidenceBucket:
    """置信度区间统计"""
    bucket: str
    count: int = 0
    win_count: int = 0
    loss_count: int = 0
    total_return: float = 0.0
    avg_return: float = 0.0
    win_rate: float = 0.0


def load_klines(csv_path: str) -> List[Dict[str, Any]]:
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
    closes = [b['close'] for b in bars]
    highs = [b['high'] for b in bars]
    lows = [b['low'] for b in bars]
    volumes = [b['volume'] for b in bars]
    
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
    
    ema20 = [closes[0]] * len(bars)
    ema50 = [closes[0]] * len(bars)
    for i in range(1, len(bars)):
        ema20[i] = closes[i] * (2 / 21) + ema20[i-1] * (1 - 2 / 21)
        if i >= 50:
            ema50[i] = closes[i] * (2 / 51) + ema50[i-1] * (1 - 2 / 51)
        else:
            ema50[i] = ema20[i]
    
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
    
    pct_changes = [0.0] * len(bars)
    for i in range(1, len(bars)):
        pct_changes[i] = (closes[i] - closes[i-1]) / closes[i-1] * 100
    
    ch24 = [0.0] * len(bars)
    for i in range(24, len(bars)):
        ch24[i] = (closes[i] - closes[i-24]) / closes[i-24] * 100
    
    ch4h = [0.0] * len(bars)
    for i in range(4, len(bars)):
        ch4h[i] = (closes[i] - closes[i-4]) / closes[i-4] * 100
    
    vol_ratio = [1.0] * len(bars)
    for i in range(period, len(bars)):
        avg_vol = sum(volumes[i-period:i]) / period
        if avg_vol > 0:
            vol_ratio[i] = volumes[i] / avg_vol
    
    price_position = [0.5] * len(bars)
    lookback = 100
    for i in range(lookback, len(bars)):
        window = closes[i-lookback:i+1]
        high = max(window)
        low = min(window)
        if high > low:
            price_position[i] = (closes[i] - low) / (high - low)
    
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


def analyze_confidence_buckets(bars: List[Dict[str, Any]],
                               hold_bars: int = 5,
                               tp_atr_mult: float = 3.0,
                               sl_atr_mult: float = 1.5) -> List[ConfidenceBucket]:
    """按置信度区间分析表现"""
    engine = BCRMEngine()
    preprocessor = MarketPreprocessor()
    
    bucket_ranges = [
        ("0.20-0.25", 0.20, 0.25),
        ("0.25-0.30", 0.25, 0.30),
        ("0.30-0.35", 0.30, 0.35),
        ("0.35-0.40", 0.35, 0.40),
        ("0.40-0.45", 0.40, 0.45),
        ("0.45-0.50", 0.45, 0.50),
        ("0.50-0.55", 0.50, 0.55),
        ("0.55-0.60", 0.55, 0.60),
        ("0.60+", 0.60, 1.01),
    ]
    
    buckets = [ConfidenceBucket(bucket=b[0]) for b in bucket_ranges]
    fail_closed_count = 0
    flat_count = 0
    
    position = None
    
    for i in range(50, len(bars) - hold_bars):
        bar = bars[i]
        
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
        
        normalized = preprocessor.normalize(snapshot)
        
        try:
            contradiction_list = engine._auto_generate_contradictions(normalized)
            output = engine.infer(market_snapshot=normalized, contradiction_list=contradiction_list)
        except Exception:
            continue
        
        if output.is_fail_closed():
            fail_closed_count += 1
            continue
        
        direction = output.next_state.direction
        confidence = output.next_state.confidence
        
        if direction == 'FLAT':
            flat_count += 1
        
        # 检查持仓
        if position:
            entry_price = position['entry_price']
            pos_direction = position['direction']
            entry_bar = position['entry_bar']
            atr = position['atr']
            entry_confidence = position['confidence']
            
            if pos_direction == 'UP':
                tp_price = entry_price + atr * tp_atr_mult
                sl_price = entry_price - atr * sl_atr_mult
            else:
                tp_price = entry_price - atr * tp_atr_mult
                sl_price = entry_price + atr * sl_atr_mult
            
            current_high = bar['high']
            current_low = bar['low']
            exit_price = None
            
            if pos_direction == 'UP':
                if current_high >= tp_price:
                    exit_price = tp_price
                elif current_low <= sl_price:
                    exit_price = sl_price
            else:
                if current_low <= tp_price:
                    exit_price = tp_price
                elif current_high >= sl_price:
                    exit_price = sl_price
            
            if i - entry_bar >= hold_bars and exit_price is None:
                exit_price = bar['close']
            
            if exit_price is not None:
                if pos_direction == 'UP':
                    pnl_pct = (exit_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - exit_price) / entry_price
                
                # 找到对应的置信度区间
                for idx, (_, low, high) in enumerate(bucket_ranges):
                    if low <= entry_confidence < high:
                        buckets[idx].count += 1
                        buckets[idx].total_return += pnl_pct
                        if pnl_pct > 0:
                            buckets[idx].win_count += 1
                        else:
                            buckets[idx].loss_count += 1
                        break
                
                position = None
        
        # 开仓
        if position is None and direction in ('UP', 'DOWN'):
            position = {
                'direction': direction,
                'entry_price': bar['close'],
                'entry_bar': i,
                'atr': bar['atr'],
                'confidence': confidence,
            }
    
    # 计算统计指标
    for b in buckets:
        if b.count > 0:
            b.win_rate = b.win_count / b.count
            b.avg_return = b.total_return / b.count
    
    return buckets, fail_closed_count, flat_count


def main():
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'data', 'klines'
    )
    
    coins = ['BTC', 'ETH', 'SOL', 'UNI']
    
    print("=" * 90)
    print("BCRM 置信度区间详细分析")
    print("=" * 90)
    
    all_buckets = {}
    all_fail = 0
    all_flat = 0
    total_signals = 0
    
    for coin in coins:
        csv_path = os.path.join(data_dir, f'{coin}_1H.csv')
        if not os.path.exists(csv_path):
            continue
        
        print(f"\n{coin} 数据加载中...")
        raw_bars = load_klines(csv_path)
        print(f"  共 {len(raw_bars)} 根K线")
        
        bars = compute_indicators(raw_bars)
        
        buckets, fail_count, flat_count = analyze_confidence_buckets(bars)
        all_fail += fail_count
        all_flat += flat_count
        
        print(f"\n  {'置信度区间':<12} {'交易数':<8} {'胜率':<8} {'总收益':<10} {'平均收益':<10}")
        print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*10} {'-'*10}")
        
        for b in buckets:
            print(f"  {b.bucket:<12} {b.count:<8} {b.win_rate:<8.2%} "
                  f"{b.total_return:<+10.2%} {b.avg_return:<+10.2%}")
        
        print(f"\n  fail_closed: {fail_count} | FLAT方向: {flat_count}")
        
        all_buckets[coin] = buckets
        total_signals += len(bars) - 55
    
    # 综合统计
    print("\n" + "=" * 90)
    print("综合统计（四币种汇总）")
    print("=" * 90)
    
    print(f"\n总K线数: {total_signals}")
    print(f"fail_closed: {all_fail} ({all_fail/total_signals*100:.1f}%)")
    print(f"FLAT方向: {all_flat} ({all_flat/total_signals*100:.1f}%)")
    print(f"可交易信号(UP/DOWN): {total_signals - all_fail - all_flat}")
    
    # 汇总各币种的 bucket
    print(f"\n{'置信度区间':<12} {'总交易数':<10} {'平均胜率':<10} {'平均总收益':<12} {'平均单笔收益':<12}")
    print(f"{'-'*12} {'-'*10} {'-'*10} {'-'*12} {'-'*12}")
    
    num_coins = len(all_buckets)
    for i in range(9):  # 9个区间
        total_count = 0
        avg_win_rate = 0
        avg_total_return = 0
        avg_single_return = 0
        
        for coin in all_buckets:
            b = all_buckets[coin][i]
            total_count += b.count
            avg_win_rate += b.win_rate
            avg_total_return += b.total_return
            avg_single_return += b.avg_return
        
        avg_win_rate /= num_coins
        avg_total_return /= num_coins
        avg_single_return /= num_coins
        
        bucket_name = list(all_buckets.values())[0][i].bucket
        
        print(f"{bucket_name:<12} {total_count:<10} {avg_win_rate:<10.2%} "
              f"{avg_total_return:<+12.2%} {avg_single_return:<+12.2%}")
    
    print("\n说明：")
    print("  - 回测周期：1小时K线，约8.5个月数据")
    print("  - 持仓周期：5根K线（5小时）或止盈止损触发")
    print("  - 止盈：3xATR，止损：1.5xATR（盈亏比2:1）")
    print("  - 收益为百分比（未计手续费和滑点）")


if __name__ == '__main__':
    main()
