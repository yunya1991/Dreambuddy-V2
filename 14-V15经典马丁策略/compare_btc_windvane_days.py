#!/usr/bin/env python3
"""BTC风向标确认天数对比回测脚本

对比方案：
  BASE:    现状 = MA200动态止损 + ATR止盈 + 移动止盈 + DirectionGate多空
  WV_1D:   BTC风向标1日确认（当日收盘跌破即平多允空）
  WV_3D:   BTC风向标3日确认（连续3日收盘跌破才平多允空）
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
print("  BTC风向标确认天数对比回测")
print("  BASE:   MA200止损 + ATR止盈 + 移动止盈 + DirectionGate多空")
print("  WV_1D:  BTC风向标1日确认（当日跌破即平多）")
print("  WV_3D:  BTC风向标3日确认（连续3日跌破平多）")
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

    # 基线
    r_base = run_backtest(**common_kw, use_btc_windvane=False, use_direction_gate=True)

    # 1日确认风向标
    r_wv1d = run_backtest(**common_kw, use_btc_windvane=True, use_direction_gate=False,
                           btc_windvane_confirm_days=1)

    # 3日确认风向标
    r_wv3d = run_backtest(**common_kw, use_btc_windvane=True, use_direction_gate=False,
                           btc_windvane_confirm_days=3)

    all_results.append((coin, r_base, r_wv1d, r_wv3d))

    m_base = r_base["metrics"]
    m_1d = r_wv1d["metrics"]
    m_3d = r_wv3d["metrics"]

    print(f"\n  {coin} 详细对比:")
    print(f"    指标            BASE(MA200+DG)    WV_1D(1日确认)     WV_3D(3日确认)")
    print(f"    {'-'*75}")
    print(f"    总收益:     {m_base['total_return_pct']:>+9.2f}%    {m_1d['total_return_pct']:>+9.2f}%    {m_3d['total_return_pct']:>+9.2f}%")
    print(f"    交易数:     {m_base['total_trades']:>9}      {m_1d['total_trades']:>9}      {m_3d['total_trades']:>9}")
    print(f"    胜率:       {m_base['win_rate']*100:>8.2f}%     {m_1d['win_rate']*100:>8.2f}%     {m_3d['win_rate']*100:>8.2f}%")
    print(f"    盈亏比:     {m_base['profit_factor']:>9.2f}     {m_1d['profit_factor']:>9.2f}     {m_3d['profit_factor']:>9.2f}")
    print(f"    最大回撤:   {m_base['max_drawdown_pct']:>8.2f}%     {m_1d['max_drawdown_pct']:>8.2f}%     {m_3d['max_drawdown_pct']:>8.2f}%")
    print(f"    夏普比:     {m_base['sharpe_ratio']:>9.4f}     {m_1d['sharpe_ratio']:>9.4f}     {m_3d['sharpe_ratio']:>9.4f}")
    btc_base = 0
    btc_1d = m_1d.get("btc_windvane_exits", 0)
    btc_3d = m_3d.get("btc_windvane_exits", 0)
    print(f"    BTC平仓:    {btc_base:>9}      {btc_1d:>9}      {btc_3d:>9}")

# ── 汇总对比 ──
print("\n" + "=" * 120)
print("  📊 BTC风向标确认天数对比汇总")
print("=" * 120)
print(f"  {'币种':>6}  {'模式':>10}  {'总收益':>10}  {'交易数':>6}  {'胜率':>7}  "
      f"{'盈亏比':>7}  {'最大回撤':>9}  {'夏普':>9}  {'BTC平仓':>7}")
print("-" * 120)

for coin, r_base, r_wv1d, r_wv3d in all_results:
    for label, r in [("BASE", r_base), ("WV_1D", r_wv1d), ("WV_3D", r_wv3d)]:
        if "error" in r:
            print(f"  {coin:>6}  {label:>10}  ERROR: {r['error']}")
            continue
        m = r["metrics"]
        btc_exit = m.get("btc_windvane_exits", 0) if label != "BASE" else 0
        print(f"  {coin:>6}  {label:>10}  {m['total_return_pct']:>+9.2f}%  {m['total_trades']:>6}  "
              f"{m['win_rate']*100:>6.2f}%  {m['profit_factor']:>7.2f}  "
              f"{m['max_drawdown_pct']:>8.2f}%  {m['sharpe_ratio']:>9.4f}  "
              f"{btc_exit:>7}")
    print("-" * 120)

# ── 效果总结与回退决策 ──
print("\n  📈 效果总结与回退决策:")
print("  " + "-" * 105)

for coin, r_base, r_wv1d, r_wv3d in all_results:
    if "error" in r_base or "error" in r_wv1d or "error" in r_wv3d:
        continue

    m_base = r_base["metrics"]
    m_1d = r_wv1d["metrics"]
    m_3d = r_wv3d["metrics"]

    # 找最优方案
    best_label = "BASE"
    best_ret = m_base["total_return_pct"]
    best_sharpe = m_base["sharpe_ratio"]

    if m_1d["total_return_pct"] > best_ret and m_1d["sharpe_ratio"] > best_sharpe * 0.9:
        best_label = "WV_1D"
        best_ret = m_1d["total_return_pct"]
        best_sharpe = m_1d["sharpe_ratio"]

    if m_3d["total_return_pct"] > best_ret and m_3d["sharpe_ratio"] > best_sharpe * 0.9:
        best_label = "WV_3D"
        best_ret = m_3d["total_return_pct"]
        best_sharpe = m_3d["sharpe_ratio"]

    d1_ret = m_1d["total_return_pct"] - m_base["total_return_pct"]
    d3_ret = m_3d["total_return_pct"] - m_base["total_return_pct"]
    d_1v3_ret = m_1d["total_return_pct"] - m_3d["total_return_pct"]

    d1_sign = "✅" if d1_ret > 0 else "❌"
    d3_sign = "✅" if d3_ret > 0 else "❌"
    d1v3_sign = "✅1日好" if d_1v3_ret > 0 else "➡️3日好"

    print(f"  {coin:>6}: 1日确认{d1_sign}{d1_ret:>+7.2f}%  "
          f"3日确认{d3_sign}{d3_ret:>+7.2f}%  "
          f"1日vs3日{d1v3_sign}{d_1v3_ret:>+7.2f}%  "
          f"→ 最优: {best_label}")

print("  " + "-" * 105)

# ── 最终决策 ──
print("\n  🎯 最终决策建议:")
print("  " + "-" * 105)

d1_better_coins = []
d3_better_coins = []
base_better_coins = []
for coin, r_base, r_wv1d, r_wv3d in all_results:
    if "error" in r_base or "error" in r_wv1d or "error" in r_wv3d:
        continue
    m_base = r_base["metrics"]
    m_1d = r_wv1d["metrics"]
    m_3d = r_wv3d["metrics"]

    best_ret = max(m_base["total_return_pct"], m_1d["total_return_pct"], m_3d["total_return_pct"])
    if best_ret == m_1d["total_return_pct"]:
        d1_better_coins.append(coin)
    elif best_ret == m_3d["total_return_pct"]:
        d3_better_coins.append(coin)
    else:
        base_better_coins.append(coin)

if d1_better_coins:
    print(f"  ✅ 1日确认最优币种: {', '.join(d1_better_coins)}")
if d3_better_coins:
    print(f"  ✅ 3日确认最优币种: {', '.join(d3_better_coins)}")
if base_better_coins:
    print(f"  ❌ 基线(MA200止损)最优币种: {', '.join(base_better_coins)}")

print("=" * 120)

# 保存结果
output_file = BASE_DIR / "data" / "btc_windvane_days_backtest_result.json"
output_file.parent.mkdir(parents=True, exist_ok=True)
output = {
    "mode": "btc_windvane_days_comparison",
    "results": [],
}

for coin, r_base, r_wv1d, r_wv3d in all_results:
    if "error" in r_base or "error" in r_wv1d or "error" in r_wv3d:
        continue
    output["results"].append({
        "coin": coin,
        "base": {
            "total_return_pct": r_base["metrics"]["total_return_pct"],
            "max_drawdown_pct": r_base["metrics"]["max_drawdown_pct"],
            "sharpe_ratio": r_base["metrics"]["sharpe_ratio"],
            "total_trades": r_base["metrics"]["total_trades"],
            "win_rate": r_base["metrics"]["win_rate"],
            "profit_factor": r_base["metrics"]["profit_factor"],
        },
        "wv_1d": {
            "total_return_pct": r_wv1d["metrics"]["total_return_pct"],
            "max_drawdown_pct": r_wv1d["metrics"]["max_drawdown_pct"],
            "sharpe_ratio": r_wv1d["metrics"]["sharpe_ratio"],
            "total_trades": r_wv1d["metrics"]["total_trades"],
            "win_rate": r_wv1d["metrics"]["win_rate"],
            "profit_factor": r_wv1d["metrics"]["profit_factor"],
            "btc_windvane_exits": r_wv1d["metrics"].get("btc_windvane_exits", 0),
        },
        "wv_3d": {
            "total_return_pct": r_wv3d["metrics"]["total_return_pct"],
            "max_drawdown_pct": r_wv3d["metrics"]["max_drawdown_pct"],
            "sharpe_ratio": r_wv3d["metrics"]["sharpe_ratio"],
            "total_trades": r_wv3d["metrics"]["total_trades"],
            "win_rate": r_wv3d["metrics"]["win_rate"],
            "profit_factor": r_wv3d["metrics"]["profit_factor"],
            "btc_windvane_exits": r_wv3d["metrics"].get("btc_windvane_exits", 0),
        },
    })

with open(output_file, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"\n  结果已保存: {output_file}")
