#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0修复回测验证脚本

对比：
1. 原始策略（修复前）：所有信号都执行
2. P0修复后：震荡市强制空仓 + 置信度动态阈值

基于历史交易记录中的市场快照数据进行模拟。
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime

TRADES_FILE = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/.workbuddy/memory_l4/stats/all_trades.jsonl"


def load_trades():
    trades = []
    with open(TRADES_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except Exception:
                    pass
    return trades


def compute_ranging_confidence(trade):
    """
    从历史交易快照重建 ranging_confidence (score/4)
    基于yijing_trainer.py中_detect_ranging_market的4个特征:
    - low_volatility: volatility < 0.025
    - small_range: med_change < 0.03
    - weak_trend: trend_strength < 0.35
    - boll_squeeze: 无法从快照重建，设为False
    """
    snapshot = trade.get("market_snapshot", {})
    volatility = snapshot.get("volatility", 0.5)
    med_change = abs(snapshot.get("med_change_pct", 0))
    trend_str = snapshot.get("trend_strength", 0.5)

    low_vol = volatility < 0.025
    small_range = med_change < 0.03
    weak_trend = trend_str < 0.35
    # boll_squeeze 无法从快照重建，保守设为False（会导致部分震荡市被低估）
    squeeze = False

    score = sum([low_vol, small_range, weak_trend, squeeze])
    is_ranging = score >= 2
    confidence = score / 4
    return is_ranging, confidence, score


def p0_filter(trade):
    """
    应用P0修复后的过滤逻辑（分级阈值）：
    返回 (should_trade: bool, reason: str)

    分级策略：
    - ranging_confidence >= 0.75（强震荡市）: 强制空仓
    - ranging_confidence >= 0.5（中震荡市）: 阈值提高到0.7
    - 其他震荡市: 阈值提高到0.6
    - trend_strength > 0.6（强趋势市）: 阈值放宽到0.3
    - 默认: 保持0.4-0.55
    """
    confidence = trade.get("confidence", 0)
    direction = trade.get("direction", "FLAT")
    is_ranging, ranging_conf, _ = compute_ranging_confidence(trade)
    trend_strength = trade.get("market_snapshot", {}).get("trend_strength", 0.5)

    # 1. 方向不明确
    if direction not in ("UP", "DOWN"):
        return False, "direction_flat"

    # 2. P0强震荡市强制空仓
    if is_ranging and ranging_conf >= 0.75:
        return False, f"p0_strong_ranging_skip(rconf={ranging_conf:.2f})"

    # 3. P0中震荡市阈值提高到0.7
    if is_ranging and ranging_conf >= 0.5:
        if confidence < 0.7:
            return False, f"p0_mid_ranging_threshold(rconf={ranging_conf:.2f},conf={confidence:.2f}<0.7)"
        return True, "p0_mid_ranging_pass"

    # 4. P0弱震荡市阈值提高到0.6
    if is_ranging:
        if confidence < 0.6:
            return False, f"p0_weak_ranging_threshold(rconf={ranging_conf:.2f},conf={confidence:.2f}<0.6)"
        return True, "p0_weak_ranging_pass"

    # 5. 强趋势市阈值放宽到0.3
    if trend_strength > 0.6:
        if confidence < 0.3:
            return False, f"trend_strong_but_low_conf(conf={confidence:.2f}<0.3)"
        return True, "trend_strong_pass"

    # 6. 默认阈值0.55
    if confidence < 0.55:
        # 轻仓试错区间
        if confidence >= 0.40:
            return True, "default_trial_zone"
        return False, f"default_low_conf(conf={confidence:.2f}<0.40)"

    return True, "default_pass"


def simulate_strategy(trades, apply_p0=False):
    """
    模拟策略执行
    返回: (executed_trades, filtered_trades, stats)
    """
    sorted_trades = sorted(trades, key=lambda x: x['entry_time'])

    executed = []
    filtered = []
    current_consecutive_loss = 0
    max_consecutive_loss = 0
    paused = False
    pause_count = 0

    for trade in sorted_trades:
        if apply_p0:
            should_trade, reason = p0_filter(trade)
        else:
            should_trade, reason = True, "no_filter"

        # 连续亏损熔断（5次）
        if current_consecutive_loss >= 5:
            paused = True
            pause_count += 1
            filtered.append({
                **trade,
                "filter_reason": "risk_pause_consecutive_5",
                "pnl_pct": 0,
                "pnl": 0,
            })
            # 重置连续亏损（相当于跳过一天）
            current_consecutive_loss = 0
            continue

        if paused:
            # 暂停期间跳过
            filtered.append({
                **trade,
                "filter_reason": "risk_paused",
                "pnl_pct": 0,
                "pnl": 0,
            })
            # 假设暂停1个交易后恢复
            paused = False
            continue

        if should_trade:
            executed.append({**trade, "filter_reason": reason})
            if trade['pnl_pct'] < 0:
                current_consecutive_loss += 1
                max_consecutive_loss = max(max_consecutive_loss, current_consecutive_loss)
            else:
                current_consecutive_loss = 0
        else:
            filtered.append({
                **trade,
                "filter_reason": reason,
                "pnl_pct": 0,
                "pnl": 0,
            })

    return executed, filtered, {
        "max_consecutive_loss": max_consecutive_loss,
        "pause_count": pause_count,
    }


def compute_metrics(trades, label):
    """计算交易指标"""
    if not trades:
        print(f"\n[{label}] 无交易")
        return {}

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

    # 期望收益
    exp_return = (win_rate / 100) * avg_win_pct + (loss_rate / 100) * avg_loss_pct

    # 最大回撤
    equity = 0
    peak = 0
    max_dd = 0
    sorted_trades = sorted(trades, key=lambda x: x['entry_time'])
    for t in sorted_trades:
        equity += t['pnl']
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    metrics = {
        "label": label,
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "exp_return_per_trade": exp_return,
        "max_drawdown": max_dd,
    }

    return metrics


def print_metrics(m, filter_stats=None):
    """打印指标"""
    if not m:
        print("\n[无指标数据]")
        return
    print(f"\n{'=' * 70}")
    print(f"📊 {m.get('label', 'N/A')}")
    print(f"{'=' * 70}")
    print(f"总交易数: {m['total']}")
    print(f"盈利交易: {m['wins']} ({m['win_rate']:.2f}%)")
    print(f"亏损交易: {m['losses']} ({m['loss_rate']:.2f}%)")
    print(f"盈亏平衡: {m['breakeven']}")
    print(f"总盈亏: {m['total_pnl']:.2f} USDT")
    print(f"平均盈利: {m['avg_win']:.4f} USDT ({m['avg_win_pct']:.2f}%)")
    print(f"平均亏损: {m['avg_loss']:.4f} USDT ({m['avg_loss_pct']:.2f}%)")
    print(f"盈亏比: {m['win_loss_ratio']:.2f}")
    print(f"单笔期望收益: {m['exp_return_per_trade']:.4f}%")
    print(f"最大回撤: {m['max_drawdown']:.2f} USDT")

    if filter_stats:
        print(f"最大连续亏损: {filter_stats['max_consecutive_loss']}")
        print(f"风控暂停次数: {filter_stats['pause_count']}")


def analyze_filter_reasons(filtered_trades):
    """分析被过滤的原因"""
    reasons = Counter()
    for t in filtered_trades:
        reasons[t.get("filter_reason", "unknown")] += 1

    print(f"\n{'=' * 70}")
    print(f"🚫 过滤原因分布")
    print(f"{'=' * 70}")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason:50s}: {count:3d} 次")


def analyze_p0_saved_losses(filtered_trades):
    """分析P0过滤掉的交易是否为亏损"""
    saved_losses = 0
    saved_wins = 0
    saved_loss_pnl = 0
    saved_win_pnl = 0

    for t in filtered_trades:
        reason = t.get("filter_reason", "")
        if reason.startswith("p0_"):
            if t['pnl_pct'] < 0:
                saved_losses += 1
                saved_loss_pnl += t['pnl']
            elif t['pnl_pct'] > 0:
                saved_wins += 1
                saved_win_pnl += t['pnl']

    print(f"\n{'=' * 70}")
    print(f"💰 P0过滤效果分析")
    print(f"{'=' * 70}")
    print(f"P0过滤掉的亏损交易: {saved_losses} 次")
    print(f"  节省的亏损: {abs(saved_loss_pnl):.4f} USDT")
    print(f"P0过滤掉的盈利交易: {saved_wins} 次")
    print(f"  错过的盈利: {saved_win_pnl:.4f} USDT")
    print(f"净收益: {abs(saved_loss_pnl) - saved_win_pnl:.4f} USDT")
    return saved_losses, saved_wins, saved_loss_pnl, saved_win_pnl


def main():
    print()
    print("=" * 70)
    print("🔬 P0修复回测验证")
    print("=" * 70)

    trades = load_trades()
    print(f"加载历史交易: {len(trades)} 笔")

    # 验证ranging_confidence分布
    print(f"\n{'=' * 70}")
    print("📡 市场环境分布")
    print(f"{'=' * 70}")
    ranging_dist = Counter()
    for t in trades:
        is_r, rconf, score = compute_ranging_confidence(t)
        bucket = f"score={score} (rconf={rconf:.2f})"
        ranging_dist[bucket] += 1
    for k, v in sorted(ranging_dist.items()):
        print(f"  {k}: {v} 次")

    # 原始策略
    orig_exec, orig_filt, orig_stats = simulate_strategy(trades, apply_p0=False)
    orig_metrics = compute_metrics(orig_exec, "原始策略（修复前）")
    print_metrics(orig_metrics, orig_stats)

    # P0修复后
    p0_exec, p0_filt, p0_stats = simulate_strategy(trades, apply_p0=True)
    p0_metrics = compute_metrics(p0_exec, "P0修复后策略")
    print_metrics(p0_metrics, p0_stats)

    # 过滤分析
    analyze_filter_reasons(p0_filt)
    analyze_p0_saved_losses(p0_filt)

    # 对比
    print(f"\n{'=' * 70}")
    print(f"📈 对比分析")
    print(f"{'=' * 70}")
    print(f"{'指标':20s} {'修复前':>15s} {'修复后':>15s} {'变化':>15s}")
    print(f"{'-' * 65}")
    print(f"{'总交易数':20s} {orig_metrics['total']:>15d} {p0_metrics['total']:>15d} {p0_metrics['total']-orig_metrics['total']:>+15d}")
    print(f"{'盈利交易':20s} {orig_metrics['wins']:>15d} {p0_metrics['wins']:>15d} {p0_metrics['wins']-orig_metrics['wins']:>+15d}")
    print(f"{'亏损交易':20s} {orig_metrics['losses']:>15d} {p0_metrics['losses']:>15d} {p0_metrics['losses']-orig_metrics['losses']:>+15d}")
    print(f"{'胜率(%)':20s} {orig_metrics['win_rate']:>15.2f} {p0_metrics['win_rate']:>15.2f} {p0_metrics['win_rate']-orig_metrics['win_rate']:>+15.2f}")
    print(f"{'总盈亏(USDT)':20s} {orig_metrics['total_pnl']:>15.2f} {p0_metrics['total_pnl']:>15.2f} {p0_metrics['total_pnl']-orig_metrics['total_pnl']:>+15.2f}")
    print(f"{'盈亏比':20s} {orig_metrics['win_loss_ratio']:>15.2f} {p0_metrics['win_loss_ratio']:>15.2f} {p0_metrics['win_loss_ratio']-orig_metrics['win_loss_ratio']:>+15.2f}")
    print(f"{'最大回撤(USDT)':20s} {orig_metrics['max_drawdown']:>15.2f} {p0_metrics['max_drawdown']:>15.2f} {p0_metrics['max_drawdown']-orig_metrics['max_drawdown']:>+15.2f}")
    print(f"{'最大连续亏损':20s} {orig_stats['max_consecutive_loss']:>15d} {p0_stats['max_consecutive_loss']:>15d} {p0_stats['max_consecutive_loss']-orig_stats['max_consecutive_loss']:>+15d}")
    print(f"{'风控暂停次数':20s} {orig_stats['pause_count']:>15d} {p0_stats['pause_count']:>15d} {p0_stats['pause_count']-orig_stats['pause_count']:>+15d}")

    # 保存结果
    result = {
        "timestamp": datetime.now().isoformat(),
        "total_trades_loaded": len(trades),
        "original": {**orig_metrics, **orig_stats},
        "p0_fixed": {**p0_metrics, **p0_stats},
        "improvement": {
            "win_rate_delta": p0_metrics['win_rate'] - orig_metrics['win_rate'],
            "pnl_delta": p0_metrics['total_pnl'] - orig_metrics['total_pnl'],
            "max_consecutive_loss_delta": p0_stats['max_consecutive_loss'] - orig_stats['max_consecutive_loss'],
            "pause_count_delta": p0_stats['pause_count'] - orig_stats['pause_count'],
            "max_drawdown_delta": p0_metrics['max_drawdown'] - orig_metrics['max_drawdown'],
        },
    }

    output_path = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/p0_backtest_result.json"
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n结果已保存: {output_path}")

    # 观察期通过标准检查
    print(f"\n{'=' * 70}")
    print(f"✅ 观察期通过标准检查")
    print(f"{'=' * 70}")
    checks = [
        ("连续亏损次数 ≤ 5", p0_stats['max_consecutive_loss'] <= 5),
        ("胜率 ≥ 25%", p0_metrics['win_rate'] >= 25),
        ("最大回撤 ≤ 5 USDT", p0_metrics['max_drawdown'] <= 5),
    ]
    for name, passed in checks:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} - {name}")

    all_pass = all(c[1] for c in checks)
    if all_pass:
        print(f"\n🎉 P0修复通过观察期验证！建议正式采纳。")
    else:
        print(f"\n⚠️  P0修复部分指标未达标，建议进一步调整。")


if __name__ == '__main__':
    main()
