#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
易经推理模型亏损深度分析
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta

TRADES_FILE = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/.workbuddy/memory_l4/stats/all_trades.jsonl"

def load_trades():
    trades = []
    with open(TRADES_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trade = json.loads(line)
                    trades.append(trade)
                except:
                    pass
    return trades

def analyze_basic_stats(trades):
    total = len(trades)
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] < 0]
    breakeven = [t for t in trades if t['pnl_pct'] == 0]
    
    win_rate = len(wins) / total * 100 if total > 0 else 0
    loss_rate = len(losses) / total * 100 if total > 0 else 0
    
    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    
    avg_win_pct = sum(t['pnl_pct'] for t in wins) / len(wins) * 100 if wins else 0
    avg_loss_pct = sum(t['pnl_pct'] for t in losses) / len(losses) * 100 if losses else 0
    
    print("=" * 80)
    print("📊 易经推理模型 - 交易基本统计")
    print("=" * 80)
    print(f"总交易数: {total}")
    print(f"盈利交易: {len(wins)} ({win_rate:.2f}%)")
    print(f"亏损交易: {len(losses)} ({loss_rate:.2f}%)")
    print(f"盈亏平衡: {len(breakeven)}")
    print(f"总盈亏: {total_pnl:.2f} USDT")
    print(f"平均盈利: {avg_win:.4f} USDT ({avg_win_pct:.2f}%)")
    print(f"平均亏损: {avg_loss:.4f} USDT ({avg_loss_pct:.2f}%)")
    print(f"盈亏比: {win_loss_ratio:.2f}")
    print()
    
    return wins, losses

def analyze_consecutive_losses(trades):
    sorted_trades = sorted(trades, key=lambda x: x['entry_time'])
    
    max_consecutive = 0
    current_consecutive = 0
    current_streak = []
    max_streak = []
    
    for trade in sorted_trades:
        if trade['pnl_pct'] < 0:
            current_consecutive += 1
            current_streak.append(trade)
            if current_consecutive > max_consecutive:
                max_consecutive = current_consecutive
                max_streak = current_streak.copy()
        else:
            current_consecutive = 0
            current_streak = []
    
    print("=" * 80)
    print("🔥 连续亏损分析")
    print("=" * 80)
    print(f"最大连续亏损次数: {max_consecutive}")
    print()
    
    if max_streak:
        print("最大连亏序列详情:")
        for i, t in enumerate(max_streak):
            print(f"  #{i+1} {t['coin']} {t['direction']} @ {t['entry_price']} "
                  f"盈亏: {t['pnl_pct']*100:.2f}% 卦象: {t.get('hexagram', 'N/A')} "
                  f"退出原因: {t.get('exit_reason', 'N/A')}")
        print()
    
    recent_losses = [t for t in sorted_trades if t['pnl_pct'] < 0][-15:]
    print("最近15笔亏损交易:")
    for i, t in enumerate(recent_losses):
        print(f"  #{i+1} {t['entry_time'][:16]} {t['coin']} {t['direction']} "
              f"盈亏: {t['pnl_pct']*100:.2f}% 卦象: {t.get('hexagram', 'N/A')} "
              f"置信度: {t.get('confidence', 'N/A')}")
    print()
    
    return max_consecutive, max_streak

def analyze_loss_by_hexagram(losses):
    hexagram_counts = Counter()
    hexagram_pnl = defaultdict(list)
    
    for t in losses:
        hexagram = t.get('hexagram', '未知')
        hexagram_counts[hexagram] += 1
        hexagram_pnl[hexagram].append(t['pnl_pct'])
    
    print("=" * 80)
    print("🔯 亏损交易卦象分布 (Top 15)")
    print("=" * 80)
    
    sorted_hex = sorted(hexagram_counts.items(), key=lambda x: -x[1])[:15]
    for hex_name, count in sorted_hex:
        avg_pct = sum(hexagram_pnl[hex_name]) / len(hexagram_pnl[hex_name]) * 100
        print(f"  {hex_name:12s}: {count:3d} 次  平均亏损: {avg_pct:.2f}%")
    print()
    
    return hexagram_counts, hexagram_pnl

def analyze_loss_by_exit_reason(losses):
    exit_counts = Counter()
    exit_pnl = defaultdict(list)
    
    for t in losses:
        reason = t.get('exit_reason', '未知')
        exit_counts[reason] += 1
        exit_pnl[reason].append(t['pnl_pct'])
    
    print("=" * 80)
    print("🚪 亏损退出原因分布")
    print("=" * 80)
    
    for reason, count in sorted(exit_counts.items(), key=lambda x: -x[1]):
        avg_pct = sum(exit_pnl[reason]) / len(exit_pnl[reason]) * 100
        print(f"  {reason:40s}: {count:3d} 次  平均亏损: {avg_pct:.2f}%")
    print()
    
    return exit_counts

def analyze_loss_by_coin(losses):
    coin_counts = Counter()
    coin_pnl = defaultdict(list)
    
    for t in losses:
        coin = t.get('coin', '未知')
        coin_counts[coin] += 1
        coin_pnl[coin].append(t['pnl_pct'])
    
    print("=" * 80)
    print("💰 亏损币种分布")
    print("=" * 80)
    
    for coin, count in sorted(coin_counts.items(), key=lambda x: -x[1]):
        avg_pct = sum(coin_pnl[coin]) / len(coin_pnl[coin]) * 100
        print(f"  {coin:6s}: {count:3d} 次  平均亏损: {avg_pct:.2f}%")
    print()
    
    return coin_counts

def analyze_loss_by_direction(losses):
    dir_counts = Counter()
    dir_pnl = defaultdict(list)
    
    for t in losses:
        direction = t.get('direction', '未知')
        dir_counts[direction] += 1
        dir_pnl[direction].append(t['pnl_pct'])
    
    print("=" * 80)
    print("📈 亏损方向分布")
    print("=" * 80)
    
    for direction, count in sorted(dir_counts.items(), key=lambda x: -x[1]):
        avg_pct = sum(dir_pnl[direction]) / len(dir_pnl[direction]) * 100
        print(f"  {direction:6s}: {count:3d} 次  平均亏损: {avg_pct:.2f}%")
    print()
    
    return dir_counts

def analyze_loss_by_confidence(losses):
    buckets = [
        (0.0, 0.3, "低置信度 (<0.3)"),
        (0.3, 0.4, "较低置信度 (0.3-0.4)"),
        (0.4, 0.5, "中等置信度 (0.4-0.5)"),
        (0.5, 0.6, "较高置信度 (0.5-0.6)"),
        (0.6, 0.7, "高置信度 (0.6-0.7)"),
        (0.7, 1.0, "极高置信度 (>=0.7)"),
    ]
    
    bucket_counts = defaultdict(int)
    bucket_pnl = defaultdict(list)
    
    for t in losses:
        conf = t.get('confidence', 0)
        for low, high, label in buckets:
            if low <= conf < high:
                bucket_counts[label] += 1
                bucket_pnl[label].append(t['pnl_pct'])
                break
    
    print("=" * 80)
    print("🎯 亏损置信度分布")
    print("=" * 80)
    
    for _, _, label in buckets:
        count = bucket_counts[label]
        if count > 0:
            avg_pct = sum(bucket_pnl[label]) / len(bucket_pnl[label]) * 100
            print(f"  {label:25s}: {count:3d} 次  平均亏损: {avg_pct:.2f}%")
    print()

def analyze_loss_by_market_regime(losses):
    regime_counts = Counter()
    regime_pnl = defaultdict(list)
    
    for t in losses:
        liangyi = t.get('liangyi_state', {})
        regime = liangyi.get('macro_phase', '未知')
        regime_cn = liangyi.get('macro_season', '未知')
        key = f"{regime} ({regime_cn})"
        regime_counts[key] += 1
        regime_pnl[key].append(t['pnl_pct'])
    
    print("=" * 80)
    print("🌍 亏损宏观环境分布")
    print("=" * 80)
    
    for regime, count in sorted(regime_counts.items(), key=lambda x: -x[1]):
        avg_pct = sum(regime_pnl[regime]) / len(regime_pnl[regime]) * 100
        print(f"  {regime:20s}: {count:3d} 次  平均亏损: {avg_pct:.2f}%")
    print()
    
    is_ranging_count = sum(1 for t in losses if t.get('market_snapshot', {}).get('is_ranging', False))
    total = len(losses)
    print(f"震荡市中亏损占比: {is_ranging_count}/{total} ({is_ranging_count/total*100:.1f}%)")
    print()

def analyze_timeline(trades):
    sorted_trades = sorted(trades, key=lambda x: x['entry_time'])
    
    daily_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0})
    
    for t in sorted_trades:
        date = t['entry_time'][:10]
        daily_stats[date]['pnl'] += t['pnl']
        if t['pnl_pct'] > 0:
            daily_stats[date]['wins'] += 1
        else:
            daily_stats[date]['losses'] += 1
    
    print("=" * 80)
    print("📅 近期每日交易统计 (最近14天)")
    print("=" * 80)
    
    recent_dates = sorted(daily_stats.keys())[-14:]
    for date in recent_dates:
        stats = daily_stats[date]
        total = stats['wins'] + stats['losses']
        win_rate = stats['wins'] / total * 100 if total > 0 else 0
        print(f"  {date}: 总{total:2d} 胜{stats['wins']:2d} 负{stats['losses']:2d} "
              f"胜率{win_rate:5.1f}% 盈亏{stats['pnl']:+.2f}")
    print()

def main():
    print()
    trades = load_trades()
    print(f"加载交易记录: {len(trades)} 笔")
    print()
    
    wins, losses = analyze_basic_stats(trades)
    analyze_consecutive_losses(trades)
    analyze_loss_by_hexagram(losses)
    analyze_loss_by_exit_reason(losses)
    analyze_loss_by_coin(losses)
    analyze_loss_by_direction(losses)
    analyze_loss_by_confidence(losses)
    analyze_loss_by_market_regime(losses)
    analyze_timeline(trades)
    
    print("=" * 80)
    print("✅ 分析完成")
    print("=" * 80)

if __name__ == '__main__':
    main()
