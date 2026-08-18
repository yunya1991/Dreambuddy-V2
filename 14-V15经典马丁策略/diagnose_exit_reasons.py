#!/usr/bin/env python3
"""诊断ARB/OP/UNI的exit_reason分布 — 验证ATR无变化是否因非止盈出场"""
import sys
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / "core"))

from v15_backtest import run_backtest, fetch_klines

coins = ["BTC", "ETH", "SOL", "ARB", "OP", "UNI"]
limit = 1500

print("=" * 80)
print("  诊断：各币种 exit_reason 分布（ATR ON 模式）")
print("=" * 80)

for coin in coins:
    klines = fetch_klines(coin, "4h", limit)
    if len(klines) < 200:
        print(f"\n{coin}: 数据不足")
        continue

    r = run_backtest(coin=coin, klines=klines, use_atr=True)
    if "error" in r:
        print(f"\n{coin}: ERROR {r['error']}")
        continue

    trades = r.get("trades", [])
    if not trades:
        print(f"\n{coin}: 无交易")
        continue

    reasons = [t["exit_reason"] for t in trades]
    cnt = Counter(reasons)
    total = len(trades)

    print(f"\n{coin}: 总交易数={total}")
    for reason, count in cnt.most_common():
        pct = count / total * 100
        # 计算该类出场的平均盈亏
        subset = [t for t in trades if t["exit_reason"] == reason]
        avg_pnl = sum(t["pnl_pct"] for t in subset) / len(subset)
        print(f"  {reason:>14}: {count:>3} ({pct:>5.1f}%)  平均盈亏={avg_pnl:>+7.2f}%")

    # 检查止盈出场的比例
    tp_count = cnt.get("take_profit", 0)
    tp_pct = tp_count / total * 100
    print(f"  ── 止盈出场占比: {tp_pct:.1f}% (ATR仅影响这部分)")

    # 如果止盈占比低，说明ATR影响有限
    if tp_pct < 30:
        print(f"  ⚠️  止盈占比<30%，ATR调整TP对结果影响有限 — 解释了ON/OFF无变化")
