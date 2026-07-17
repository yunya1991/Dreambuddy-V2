#!/usr/bin/env python3
"""BTC风向标模式对比回测脚本

对比方案：
  BASE: 现状 = MA200动态止损 + ATR动态止盈 + 移动止盈 + DirectionGate多空
  BTC_WV: BTC风向标模式 = 移除各币种MA200止损 + BTC MA200状态控方向+平仓

BTC风向标逻辑：
  - LONG_ONLY: BTC在日MA200上方 → 只做多
  - SHORT_ALLOWED: BTC连续3日收盘价低于日MA200 → 平掉多仓，多空都允许
  - LONG_ONLY_FORCE: BTC价格触及周MA200 → 平掉空仓，强制做多
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

print("=" * 105)
print("  BTC风向标模式对比回测")
print("  BASE: MA200止损 + ATR止盈 + 移动止盈 + DirectionGate多空")
print("  BTC_WV: BTC风向标(移除MA200止损, BTC MA200控方向+平仓)")
print("=" * 105)

all_results = []

for coin in coins:
    print(f"\n  回测 {coin}...", flush=True)
    klines = fetch_klines(coin, "4h", limit)
    if len(klines) < 200:
        print(f"  {coin}: 数据不足")
        continue

    # 基线：MA200止损 + ATR + 移动止盈 + DirectionGate多空
    r_base = run_backtest(
        coin=coin, klines=klines,
        use_atr=True, use_trailing_tp=True,
        use_btc_windvane=False, use_direction_gate=True,
        long_only=False, base_position_pct=0.22,
    )

    # BTC风向标模式
    r_btcwv = run_backtest(
        coin=coin, klines=klines,
        use_atr=True, use_trailing_tp=True,
        use_btc_windvane=True, use_direction_gate=False,
        long_only=False, base_position_pct=0.22,
    )

    all_results.append((coin, r_base, r_btcwv))

    m_base = r_base["metrics"]
    m_btcwv = r_btcwv["metrics"]

    print(f"\n  {coin} 详细对比:")
    print(f"    指标            BASE(MA200+DG)    BTC_WV(风向标)      差值")
    print(f"    {'-'*65}")
    print(f"    总收益:     {m_base['total_return_pct']:>+9.2f}%    {m_btcwv['total_return_pct']:>+9.2f}%    {m_btcwv['total_return_pct'] - m_base['total_return_pct']:>+8.2f}%")
    print(f"    交易数:     {m_base['total_trades']:>9}      {m_btcwv['total_trades']:>9}      {m_btcwv['total_trades'] - m_base['total_trades']:>+7}")
    print(f"    胜率:       {m_base['win_rate']*100:>8.2f}%     {m_btcwv['win_rate']*100:>8.2f}%     {m_btcwv['win_rate']*100 - m_base['win_rate']*100:>+8.2f}%")
    print(f"    盈亏比:     {m_base['profit_factor']:>9.2f}     {m_btcwv['profit_factor']:>9.2f}     {m_btcwv['profit_factor'] - m_base['profit_factor']:>+9.2f}")
    print(f"    最大回撤:   {m_base['max_drawdown_pct']:>8.2f}%     {m_btcwv['max_drawdown_pct']:>8.2f}%     {m_btcwv['max_drawdown_pct'] - m_base['max_drawdown_pct']:>+8.2f}%")
    print(f"    夏普比:     {m_base['sharpe_ratio']:>9.4f}     {m_btcwv['sharpe_ratio']:>9.4f}     {m_btcwv['sharpe_ratio'] - m_base['sharpe_ratio']:>+9.4f}")

    # 出场原因分布
    base_trades = r_base.get("trades", [])
    btc_trades = r_btcwv.get("trades", [])

    base_reasons = Counter(t["exit_reason"] for t in base_trades)
    btc_reasons = Counter(t["exit_reason"] for t in btc_trades)

    print(f"\n    出场原因分布:")
    for reason in ["take_profit", "ma200_stop", "time_exit"]:
        b_cnt = base_reasons.get(reason, 0)
        btc_cnt = btc_reasons.get(reason, 0)
        b_pct = b_cnt / len(base_trades) * 100 if base_trades else 0
        btc_pct = btc_cnt / len(btc_trades) * 100 if btc_trades else 0
        print(f"      {reason:>14}: BASE {b_cnt:>3}({b_pct:>5.1f}%)  BTC_WV {btc_cnt:>3}({btc_pct:>5.1f}%)")

    print(f"    BTC风向标平仓: {m_btcwv.get('btc_windvane_exits', 0)}笔")

# ── 汇总对比 ──
print("\n" + "=" * 105)
print("  📊 BTC风向标模式对比汇总")
print("=" * 105)
print(f"  {'币种':>6}  {'模式':>10}  {'总收益':>10}  {'交易数':>6}  {'胜率':>7}  "
      f"{'盈亏比':>7}  {'最大回撤':>9}  {'夏普':>9}  {'止盈':>5}  {'MA200':>5}  {'BTC平仓':>7}")
print("-" * 105)

for coin, r_base, r_btcwv in all_results:
    for label, r in [("BASE", r_base), ("BTC_WV", r_btcwv)]:
        if "error" in r:
            print(f"  {coin:>6}  {label:>10}  ERROR: {r['error']}")
            continue
        m = r["metrics"]
        ttp = m.get("trailing_tp_trades", 0) + m.get("fixed_tp_trades", 0)
        ma200 = m.get("ma200_stop_trades", 0)
        btc_exit = m.get("btc_windvane_exits", 0)
        print(f"  {coin:>6}  {label:>10}  {m['total_return_pct']:>+9.2f}%  {m['total_trades']:>6}  "
              f"{m['win_rate']*100:>6.2f}%  {m['profit_factor']:>7.2f}  "
              f"{m['max_drawdown_pct']:>8.2f}%  {m['sharpe_ratio']:>9.4f}  "
              f"{ttp:>5}  {ma200:>5}  {btc_exit:>7}")
    print("-" * 105)

# ── 效果总结与回退决策 ──
print("\n  📈 BTC风向标效果总结与回退决策:")
print("  " + "-" * 85)

overall_better = True
worse_coins = []
improved_coins = []
flat_coins = []

for coin, r_base, r_btcwv in all_results:
    if "error" in r_base or "error" in r_btcwv:
        continue

    m_base = r_base["metrics"]
    m_btc = r_btcwv["metrics"]

    ret_diff = m_btc["total_return_pct"] - m_base["total_return_pct"]
    dd_diff = m_btc["max_drawdown_pct"] - m_base["max_drawdown_pct"]
    pf_diff = m_btc["profit_factor"] - m_base["profit_factor"]
    sharpe_diff = m_btc["sharpe_ratio"] - m_base["sharpe_ratio"]

    if ret_diff > 3.0 and sharpe_diff > 0.3 and dd_diff <= 2.0:
        status = "✅ 显著改善"
        decision = "✅ 采用BTC风向标"
        improved_coins.append(coin)
    elif ret_diff < -3.0 or dd_diff > 5.0:
        status = "❌ 变差"
        decision = "❌ 回退（保持MA200止损）"
        worse_coins.append(coin)
        overall_better = False
    elif ret_diff > 1.0:
        status = "✅ 改善"
        decision = "✅ 采用BTC风向标"
        improved_coins.append(coin)
    elif ret_diff < -1.0:
        status = "➡️ 略变差"
        decision = "➡️ 建议保持MA200止损"
        worse_coins.append(coin)
        overall_better = False
    else:
        status = "➡️ 持平"
        decision = "➡️ 可选（无显著差异）"
        flat_coins.append(coin)

    print(f"  {coin:>6}: 收益{ret_diff:>+8.2f}%  盈亏比{pf_diff:>+7.2f}  回撤{dd_diff:>+7.2f}%  "
          f"夏普{sharpe_diff:>+8.4f}  {status}  → {decision}")

print("  " + "-" * 85)

# ── 最终决策 ──
print("\n  🎯 最终决策:")
if worse_coins:
    print(f"  ❌ 以下币种BTC风向标表现变差: {', '.join(worse_coins)}")
    print(f"  → 建议回退，保持MA200动态止损 + DirectionGate模式")
elif improved_coins and overall_better:
    print(f"  ✅ 以下币种BTC风向标有改善: {', '.join(improved_coins)}")
    if flat_coins:
        print(f"  ➡️ 以下币种持平: {', '.join(flat_coins)}")
    print(f"  → 建议启用BTC风向标模式（移除MA200止损，BTC MA200控方向+平仓）")
else:
    print(f"  ➡️ BTC风向标无显著改善，保持现状")

print("=" * 105)

# 保存结果
output_file = BASE_DIR / "data" / "btc_windvane_backtest_result.json"
output_file.parent.mkdir(parents=True, exist_ok=True)
output = {
    "mode": "btc_windvane_vs_base",
    "results": [],
}

for coin, r_base, r_btcwv in all_results:
    if "error" in r_base or "error" in r_btcwv:
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
        "btc_windvane": {
            "total_return_pct": r_btcwv["metrics"]["total_return_pct"],
            "max_drawdown_pct": r_btcwv["metrics"]["max_drawdown_pct"],
            "sharpe_ratio": r_btcwv["metrics"]["sharpe_ratio"],
            "total_trades": r_btcwv["metrics"]["total_trades"],
            "win_rate": r_btcwv["metrics"]["win_rate"],
            "profit_factor": r_btcwv["metrics"]["profit_factor"],
            "btc_windvane_exits": r_btcwv["metrics"].get("btc_windvane_exits", 0),
        },
    })

with open(output_file, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"\n  结果已保存: {output_file}")
