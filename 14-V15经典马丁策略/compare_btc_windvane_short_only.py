#!/usr/bin/env python3
"""BTC风向标SHORT_ALLOWED模式对比回测

对比方案：
  BOTH:  SHORT_ALLOWED状态下多空都允许（当前默认）
  SHORT: SHORT_ALLOWED状态下只允许做空（btc_windvane_short_only=true）
"""
import sys
import json
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "lib"))

from v15_backtest import run_backtest, fetch_klines

coins = ["BTC", "ETH", "SOL", "ARB", "OP", "UNI"]
limit = 1500

print("=" * 120)
print("  BTC风向标 SHORT_ALLOWED 模式对比")
print("  BOTH:  SHORT_ALLOWED状态下多空都允许（当前默认）")
print("  SHORT: SHORT_ALLOWED状态下只允许做空（short_only=true）")
print("  （BTC使用MA200+DG，非BTC使用BTC风向标3日确认）")
print("=" * 120)

all_results = []

for coin in coins:
    print(f"\n  回测 {coin}...", flush=True)
    klines = fetch_klines(coin, "4h", limit)
    if len(klines) < 200:
        print(f"  {coin}: 数据不足")
        continue

    common_kw = dict(
        coin=coin, klines=klines,
        use_atr=True, use_trailing_tp=True,
        long_only=False, base_position_pct=0.22,
    )

    is_btc = coin.upper() == "BTC"

    if is_btc:
        # BTC使用MA200+DG，不适用short_only对比，跳过
        print(f"  BTC 使用MA200+DG模式，跳过short_only对比")
        continue

    # BOTH: 多空都允许（默认）
    r_both = run_backtest(**common_kw, use_btc_windvane=True, use_direction_gate=False,
                          btc_windvane_confirm_days=3, btc_windvane_short_only=False)

    # SHORT: 只允许做空
    r_short = run_backtest(**common_kw, use_btc_windvane=True, use_direction_gate=False,
                           btc_windvane_confirm_days=3, btc_windvane_short_only=True)

    all_results.append((coin, r_both, r_short))

    m_both = r_both["metrics"]
    m_short = r_short["metrics"]

    print(f"\n  {coin} 详细对比:")
    print(f"    指标             BOTH(多空都允许)    SHORT(只做空)        差值")
    print(f"    {'-'*75}")
    print(f"    总收益:     {m_both['total_return_pct']:>+9.2f}%    {m_short['total_return_pct']:>+9.2f}%    {m_short['total_return_pct'] - m_both['total_return_pct']:>+8.2f}%")
    print(f"    交易数:     {m_both['total_trades']:>9}      {m_short['total_trades']:>9}      {m_short['total_trades'] - m_both['total_trades']:>+7}")
    print(f"    做多交易:   {m_both.get('long_trades', 0):>9}      {m_short.get('long_trades', 0):>9}      {m_short.get('long_trades', 0) - m_both.get('long_trades', 0):>+7}")
    print(f"    做空交易:   {m_both.get('short_trades', 0):>9}      {m_short.get('short_trades', 0):>9}      {m_short.get('short_trades', 0) - m_both.get('short_trades', 0):>+7}")
    print(f"    胜率:       {m_both['win_rate']*100:>8.2f}%     {m_short['win_rate']*100:>8.2f}%     {m_short['win_rate']*100 - m_both['win_rate']*100:>+8.2f}%")
    print(f"    盈亏比:     {m_both['profit_factor']:>9.2f}     {m_short['profit_factor']:>9.2f}     {m_short['profit_factor'] - m_both['profit_factor']:>+9.2f}")
    print(f"    最大回撤:   {m_both['max_drawdown_pct']:>8.2f}%     {m_short['max_drawdown_pct']:>8.2f}%     {m_short['max_drawdown_pct'] - m_both['max_drawdown_pct']:>+8.2f}%")
    print(f"    夏普比:     {m_both['sharpe_ratio']:>9.4f}     {m_short['sharpe_ratio']:>9.4f}     {m_short['sharpe_ratio'] - m_both['sharpe_ratio']:>+9.4f}")

# ── 汇总对比 ──
print("\n" + "=" * 120)
print("  📊 SHORT_ALLOWED 模式对比汇总（非BTC币种）")
print("=" * 120)
print(f"  {'币种':>6}  {'模式':>8}  {'总收益':>10}  {'交易数':>6}  {'胜率':>7}  "
      f"{'盈亏比':>7}  {'最大回撤':>9}  {'夏普':>9}  {'做多':>5}  {'做空':>5}")
print("-" * 120)

for coin, r_both, r_short in all_results:
    for label, r in [("BOTH", r_both), ("SHORT", r_short)]:
        if "error" in r:
            print(f"  {coin:>6}  {label:>8}  ERROR: {r['error']}")
            continue
        m = r["metrics"]
        lt = m.get("long_trades", 0)
        st = m.get("short_trades", 0)
        print(f"  {coin:>6}  {label:>8}  {m['total_return_pct']:>+9.2f}%  {m['total_trades']:>6}  "
              f"{m['win_rate']*100:>6.2f}%  {m['profit_factor']:>7.2f}  "
              f"{m['max_drawdown_pct']:>8.2f}%  {m['sharpe_ratio']:>9.4f}  "
              f"{lt:>5}  {st:>5}")
    print("-" * 120)

# ── 效果总结与决策 ──
print("\n  📈 效果总结与决策:")
print("  " + "-" * 105)

short_better = []
both_better = []
flat_coins = []

for coin, r_both, r_short in all_results:
    if "error" in r_both or "error" in r_short:
        continue

    m_both = r_both["metrics"]
    m_short = r_short["metrics"]

    ret_diff = m_short["total_return_pct"] - m_both["total_return_pct"]
    sharpe_diff = m_short["sharpe_ratio"] - m_both["sharpe_ratio"]
    dd_diff = m_short["max_drawdown_pct"] - m_both["max_drawdown_pct"]

    if ret_diff > 3.0 and sharpe_diff > 0.3:
        status = "✅ 只做空显著更优"
        short_better.append(coin)
    elif ret_diff < -3.0 or sharpe_diff < -0.5:
        status = "❌ 多空都允许更好"
        both_better.append(coin)
    elif ret_diff > 1.0:
        status = "✅ 只做空略优"
        short_better.append(coin)
    elif ret_diff < -1.0:
        status = "❌ 多空都允许略好"
        both_better.append(coin)
    else:
        status = "➡️ 持平"
        flat_coins.append(coin)

    print(f"  {coin:>6}: 收益差{ret_diff:>+8.2f}%  夏普差{sharpe_diff:>+8.4f}  回撤差{dd_diff:>+7.2f}%  {status}")

print("  " + "-" * 105)

# ── 最终决策 ──
print("\n  🎯 最终决策建议:")
print("  " + "-" * 105)

if short_better and not both_better:
    print(f"  ✅ 只做空模式更优币种: {', '.join(short_better)}")
    if flat_coins:
        print(f"  ➡️ 持平币种: {', '.join(flat_coins)}")
    print(f"  → 建议启用 short_only 模式（SHORT_ALLOWED时只允许做空）")
elif both_better and not short_better:
    print(f"  ❌ 多空都允许模式更优币种: {', '.join(both_better)}")
    if flat_coins:
        print(f"  ➡️ 持平币种: {', '.join(flat_coins)}")
    print(f"  → 建议保持默认（SHORT_ALLOWED时多空都允许）")
elif short_better and both_better:
    print(f"  ✅ 只做空更优: {', '.join(short_better)}")
    print(f"  ❌ 多空都允许更优: {', '.join(both_better)}")
    if flat_coins:
        print(f"  ➡️ 持平: {', '.join(flat_coins)}")
    print(f"  → 币种差异大，建议按币种选择")
else:
    print(f"  ➡️ 两种模式差异不大")
    print(f"  → 建议保持默认（多空都允许，更灵活）")

print("=" * 120)

# 保存结果
output_file = BASE_DIR / "data" / "btc_windvane_short_only_result.json"
output_file.parent.mkdir(parents=True, exist_ok=True)
output = {
    "mode": "btc_windvane_short_only_comparison",
    "results": [],
}

for coin, r_both, r_short in all_results:
    if "error" in r_both or "error" in r_short:
        continue
    output["results"].append({
        "coin": coin,
        "both_sides": {
            "total_return_pct": r_both["metrics"]["total_return_pct"],
            "max_drawdown_pct": r_both["metrics"]["max_drawdown_pct"],
            "sharpe_ratio": r_both["metrics"]["sharpe_ratio"],
            "total_trades": r_both["metrics"]["total_trades"],
            "win_rate": r_both["metrics"]["win_rate"],
            "profit_factor": r_both["metrics"]["profit_factor"],
        },
        "short_only": {
            "total_return_pct": r_short["metrics"]["total_return_pct"],
            "max_drawdown_pct": r_short["metrics"]["max_drawdown_pct"],
            "sharpe_ratio": r_short["metrics"]["sharpe_ratio"],
            "total_trades": r_short["metrics"]["total_trades"],
            "win_rate": r_short["metrics"]["win_rate"],
            "profit_factor": r_short["metrics"]["profit_factor"],
        },
    })

with open(output_file, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"\n  结果已保存: {output_file}")
