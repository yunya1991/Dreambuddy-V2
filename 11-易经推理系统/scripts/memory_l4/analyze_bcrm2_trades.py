#!/usr/bin/env python3
"""
分析 bcrm2 phase0 的交易记录，计算胜率。
"""

import csv
import os

data_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data', 'bcrm2_phase0'
)

coins = ['BTC', 'ETH', 'SOL', 'UNI']

print("=" * 80)
print("BCRM 2.0 Phase 0 交易记录分析")
print("=" * 80)

total_trades = 0
total_wins = 0
total_pnl = 0

for coin in coins:
    csv_path = os.path.join(data_dir, f'trades_{coin}_1H.csv')
    if not os.path.exists(csv_path):
        print(f"\n{coin}: 文件不存在")
        continue
    
    trades = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)
    
    wins = sum(1 for t in trades if float(t['pnl_pct']) > 0)
    losses = sum(1 for t in trades if float(t['pnl_pct']) <= 0)
    win_rate = wins / len(trades) if trades else 0
    total_pnl_coin = sum(float(t['pnl_pct']) for t in trades)
    avg_pnl = total_pnl_coin / len(trades) if trades else 0
    
    tp_count = sum(1 for t in trades if t['exit_reason'] == 'tp')
    sl_count = sum(1 for t in trades if t['exit_reason'] == 'sl')
    time_count = sum(1 for t in trades if t['exit_reason'] == 'time')
    
    print(f"\n{coin}:")
    print(f"  总交易数: {len(trades)}")
    print(f"  胜率: {win_rate:.2%} ({wins}胜 / {losses}负)")
    print(f"  总收益: {total_pnl_coin:+.2f}%")
    print(f"  平均单笔收益: {avg_pnl:+.3f}%")
    print(f"  止盈: {tp_count} 次 | 止损: {sl_count} 次 | 时间离场: {time_count} 次")
    
    # 按置信度区间统计
    conf_buckets = {
        '0.4-0.5': [0, 0, 0],
        '0.5-0.6': [0, 0, 0],
        '0.6-0.7': [0, 0, 0],
        '0.7-0.8': [0, 0, 0],
        '0.8-0.9': [0, 0, 0],
        '0.9+': [0, 0, 0],
    }
    
    for t in trades:
        conf = float(t['confidence'])
        pnl = float(t['pnl_pct'])
        if conf < 0.5:
            bucket = '0.4-0.5'
        elif conf < 0.6:
            bucket = '0.5-0.6'
        elif conf < 0.7:
            bucket = '0.6-0.7'
        elif conf < 0.8:
            bucket = '0.7-0.8'
        elif conf < 0.9:
            bucket = '0.8-0.9'
        else:
            bucket = '0.9+'
        
        conf_buckets[bucket][0] += 1
        conf_buckets[bucket][2] += pnl
        if pnl > 0:
            conf_buckets[bucket][1] += 1
    
    print(f"\n  置信度区间统计:")
    print(f"  {'区间':<10} {'交易数':<8} {'胜率':<10} {'平均收益':<12}")
    print(f"  {'-'*10} {'-'*8} {'-'*10} {'-'*12}")
    for bucket, (count, wins_b, pnl_b) in conf_buckets.items():
        if count > 0:
            wr = wins_b / count
            avg = pnl_b / count
            print(f"  {bucket:<10} {count:<8} {wr:<10.2%} {avg:+.3f}%")
    
    total_trades += len(trades)
    total_wins += wins
    total_pnl += total_pnl_coin

print(f"\n{'='*80}")
print(f"综合统计（四币种汇总）:")
print(f"  总交易数: {total_trades}")
print(f"  总胜率: {total_wins/total_trades:.2%} ({total_wins}胜 / {total_trades - total_wins}负)")
print(f"  总收益: {total_pnl:+.2f}%")
print(f"  平均单笔收益: {total_pnl/total_trades:+.3f}%")
