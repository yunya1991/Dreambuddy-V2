#!/usr/bin/env python3
"""调试脚本：查看 BCRM 推理失败原因"""

import sys
import os
import csv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bcrm.engine import BCRMEngine
from bcrm.market_preprocessor import MarketPreprocessor


def load_klines(csv_path: str, n: int = 100):
    bars = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= n:
                break
            bars.append({
                'timestamp': row['timestamp'],
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']),
            })
    return bars


def compute_simple_indicators(bars):
    closes = [b['close'] for b in bars]
    highs = [b['high'] for b in bars]
    lows = [b['low'] for b in bars]
    volumes = [b['volume'] for b in bars]
    period = 14
    
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


def main():
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'data', 'klines'
    )
    
    csv_path = os.path.join(data_dir, 'BTC_1H.csv')
    print(f"加载数据: {csv_path}")
    
    raw_bars = load_klines(csv_path, 100)
    print(f"共 {len(raw_bars)} 根K线")
    
    bars = compute_simple_indicators(raw_bars)
    
    engine = BCRMEngine()
    preprocessor = MarketPreprocessor()
    
    # 测试第 80 根 K 线
    i = 80
    bar = bars[i]
    print(f"\n测试第 {i} 根K线: {bar['timestamp']} 价格={bar['close']}")
    
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
    
    print(f"\n原始快照字段: {list(snapshot.keys())}")
    print(f"RSI={bar['rsi']:.2f}, ch24={bar['ch24']:.2f}%, ch4h={bar['ch4h']:.2f}%")
    print(f"volatility={bar['volatility']:.4f}, price_position={bar['price_position']:.2f}")
    
    normalized = preprocessor.normalize(snapshot)
    print(f"\n预处理后四维评分:")
    print(f"  supply_demand_score = {normalized.get('supply_demand_score')}")
    print(f"  technical_score = {normalized.get('technical_score')}")
    print(f"  capital_flow_score = {normalized.get('capital_flow_score')}")
    print(f"  sentiment_score = {normalized.get('sentiment_score')}")
    
    try:
        output = engine.infer(market_snapshot=normalized)
        print(f"\n推理结果:")
        print(f"  fail_closed = {output.is_fail_closed()}")
        print(f"  reason_codes = {output.reason_codes}")
        print(f"  direction = {output.next_state.direction}")
        print(f"  confidence = {output.next_state.confidence:.4f}")
        print(f"  derivation = {output.next_state.derivation}")
    except Exception as e:
        print(f"\n推理异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
