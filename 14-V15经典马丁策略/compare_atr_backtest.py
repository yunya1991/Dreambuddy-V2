#!/usr/bin/env python3
"""ATR动态止盈对比回测脚本 — 对比 ATR开启 vs ATR关闭"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / "core"))

from v15_backtest import run_backtest, fetch_klines

coins = ["BTC", "ETH", "SOL", "ARB", "OP", "UNI"]
limit = 1500

print("=" * 90)
print("  ATR动态止盈对比回测")
print("=" * 90)

all_results = []

for coin in coins:
    print(f"\n  回测 {coin}...", flush=True)
    klines = fetch_klines(coin, "4h", limit)
    if len(klines) < 200:
        print(f"  {coin}: 数据不足({len(klines)}根)")
        continue

    # ATR关闭（基线）
    r_off = run_backtest(coin=coin, klines=klines, use_atr=False)
    # ATR开启
    r_on = run_backtest(coin=coin, klines=klines, use_atr=True)

    all_results.append((coin, r_off, r_on))

# 汇总对比
print("\n" + "=" * 90)
print("  📊 ATR动态止盈对比汇总")
print("=" * 90)
print(f"  {'币种':>6}  {'ATR':>4}  {'总收益':>10}  {'交易数':>6}  {'胜率':>8}  {'盈亏比':>8}  "
      f"{'最大回撤':>10}  {'夏普':>8}  {'连亏':>5}")
print("-" * 90)

for coin, r_off, r_on in all_results:
    for label, r in [("OFF", r_off), ("ON", r_on)]:
        if "error" in r:
            print(f"  {coin:>6}  {label:>4}  ERROR: {r['error']}")
            continue
        m = r["metrics"]
        print(f"  {coin:>6}  {label:>4}  {m['total_return_pct']:>+8.2f}%  {m['total_trades']:>6}  "
              f"{m['win_rate']*100:>7.2f}%  {m['profit_factor']:>8.2f}  "
              f"{m['max_drawdown_pct']:>9.2f}%  {m['sharpe_ratio']:>8.4f}  {m['max_consecutive_losses']:>5}")
    print("-" * 90)

# 总结
print("\n  📈 ATR效果总结:")
print("  " + "-" * 60)
for coin, r_off, r_on in all_results:
    if "error" in r_off or "error" in r_on:
        continue
    m_off = r_off["metrics"]
    m_on = r_on["metrics"]
    ret_diff = m_on["total_return_pct"] - m_off["total_return_pct"]
    wr_diff = (m_on["win_rate"] - m_off["win_rate"]) * 100
    dd_diff = m_on["max_drawdown_pct"] - m_off["max_drawdown_pct"]
    status = "✅ 改善" if ret_diff > 0 else "❌ 变差" if ret_diff < -0.5 else "➡️ 持平"
    print(f"  {coin:>6}: 收益{ret_diff:>+7.2f}%  胜率{wr_diff:>+6.2f}%  回撤{dd_diff:>+6.2f}%  {status}")
print("  " + "-" * 60)
