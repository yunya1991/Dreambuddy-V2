#!/usr/bin/env python3
"""ATR移动止盈对比回测脚本

对比方案：
  BASE: ATR动态止盈（无移动止盈）
  TRAIL: ATR动态止盈 + ATR移动止盈（1.5×ATR，启动阈值=止盈的50%）

决策规则：
  - 如果TRAIL收益优于BASE + 盈亏比改善 → ✅ 采用移动止盈
  - 如果TRAIL收益显著变差（收益更低且回撤更大）→ ❌ 回退
  - 如果TRAIL与BASE持平 → ➡️ 无显著影响
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
TRAIL_ATR_MULT = 1.5
TRAIL_START_PCT = 0.5

print("=" * 100)
print("  ATR移动止盈对比回测")
print(f"  移动止盈参数: {TRAIL_ATR_MULT}×ATR | 启动阈值: 止盈×{TRAIL_START_PCT}(=50%) | ATR动态止盈: ON")
print("=" * 100)

all_results = []

for coin in coins:
    print(f"\n  回测 {coin}...", flush=True)
    klines = fetch_klines(coin, "4h", limit)
    if len(klines) < 200:
        print(f"  {coin}: 数据不足({len(klines)}根)")
        continue

    # 基线：ATR动态止盈（无移动止盈）
    r_base = run_backtest(
        coin=coin, klines=klines,
        use_atr=True, use_trailing_tp=False,
    )

    # 移动止盈：ATR + 移动止盈
    r_trail = run_backtest(
        coin=coin, klines=klines,
        use_atr=True, use_trailing_tp=True,
        trailing_atr_mult=TRAIL_ATR_MULT,
        trailing_start_pct_of_tp=TRAIL_START_PCT,
    )

    all_results.append((coin, r_base, r_trail))

    # 详细输出
    m_base = r_base["metrics"]
    m_trail = r_trail["metrics"]

    print(f"\n  {coin} 详细对比:")
    print(f"    指标        BASE(无移动)    TRAIL(有移动)      差值")
    print(f"    {'-'*55}")
    print(f"    总收益:     {m_base['total_return_pct']:>+8.2f}%    {m_trail['total_return_pct']:>+8.2f}%    {m_trail['total_return_pct'] - m_base['total_return_pct']:>+7.2f}%")
    print(f"    交易数:     {m_base['total_trades']:>8}      {m_trail['total_trades']:>8}      {m_trail['total_trades'] - m_base['total_trades']:>+6}")
    print(f"    胜率:       {m_base['win_rate']*100:>7.2f}%     {m_trail['win_rate']*100:>7.2f}%     {m_trail['win_rate']*100 - m_base['win_rate']*100:>+7.2f}%")
    print(f"    盈亏比:     {m_base['profit_factor']:>8.2f}     {m_trail['profit_factor']:>8.2f}     {m_trail['profit_factor'] - m_base['profit_factor']:>+8.2f}")
    print(f"    最大回撤:   {m_base['max_drawdown_pct']:>7.2f}%     {m_trail['max_drawdown_pct']:>7.2f}%     {m_trail['max_drawdown_pct'] - m_base['max_drawdown_pct']:>+7.2f}%")
    print(f"    夏普比:     {m_base['sharpe_ratio']:>8.4f}     {m_trail['sharpe_ratio']:>8.4f}     {m_trail['sharpe_ratio'] - m_base['sharpe_ratio']:>+8.4f}")

    # 出场原因分布
    base_trades = r_base.get("trades", [])
    trail_trades = r_trail.get("trades", [])

    base_reasons = Counter(t["exit_reason"] for t in base_trades)
    trail_reasons = Counter(t["exit_reason"] for t in trail_trades)

    print(f"\n    出场原因分布:")
    for reason in ["take_profit", "ma200_stop", "time_exit"]:
        b_cnt = base_reasons.get(reason, 0)
        t_cnt = trail_reasons.get(reason, 0)
        b_pct = b_cnt / len(base_trades) * 100 if base_trades else 0
        t_pct = t_cnt / len(trail_trades) * 100 if trail_trades else 0
        print(f"      {reason:>14}: BASE {b_cnt:>3}({b_pct:>5.1f}%)  TRAIL {t_cnt:>3}({t_pct:>5.1f}%)")

    # 移动止盈细分
    if m_trail.get("trailing_tp_trades", 0) > 0:
        ttp_trades = [t for t in trail_trades if t.get("sl_type") == "trailing_tp"]
        avg_ttp = sum(t["pnl_pct"] for t in ttp_trades) / len(ttp_trades) if ttp_trades else 0
        print(f"\n    移动止盈细节:")
        print(f"      移动止盈笔数: {m_trail['trailing_tp_trades']}")
        print(f"      固定止盈笔数: {m_trail['fixed_tp_trades']}")
        print(f"      移动止盈平均盈利: +{avg_ttp:.2f}%")

# ── 汇总对比 ──
print("\n" + "=" * 100)
print("  📊 移动止盈对比汇总")
print("=" * 100)
print(f"  {'币种':>6}  {'模式':>7}  {'总收益':>9}  {'交易数':>6}  {'胜率':>7}  "
      f"{'盈亏比':>7}  {'最大回撤':>9}  {'夏普':>8}  {'连亏':>5}  {'止盈':>5}  {'MA200':>5}")
print("-" * 100)

for coin, r_base, r_trail in all_results:
    for label, r in [("BASE", r_base), ("TRAIL", r_trail)]:
        if "error" in r:
            print(f"  {coin:>6}  {label:>7}  ERROR: {r['error']}")
            continue
        m = r["metrics"]
        ttp = m.get("trailing_tp_trades", 0) + m.get("fixed_tp_trades", 0)
        ma200 = m.get("ma200_stop_trades", 0)
        print(f"  {coin:>6}  {label:>7}  {m['total_return_pct']:>+8.2f}%  {m['total_trades']:>6}  "
              f"{m['win_rate']*100:>6.2f}%  {m['profit_factor']:>7.2f}  "
              f"{m['max_drawdown_pct']:>8.2f}%  {m['sharpe_ratio']:>8.4f}  {m['max_consecutive_losses']:>5}  "
              f"{ttp:>5}  {ma200:>5}")
    print("-" * 100)

# ── 效果总结与回退决策 ──
print("\n  📈 移动止盈效果总结与回退决策:")
print("  " + "-" * 80)

overall_better = True
worse_coins = []
improved_coins = []
flat_coins = []

for coin, r_base, r_trail in all_results:
    if "error" in r_base or "error" in r_trail:
        continue

    m_base = r_base["metrics"]
    m_trail = r_trail["metrics"]

    ret_diff = m_trail["total_return_pct"] - m_base["total_return_pct"]
    dd_diff = m_trail["max_drawdown_pct"] - m_base["max_drawdown_pct"]
    pf_diff = m_trail["profit_factor"] - m_base["profit_factor"]

    # 决策逻辑
    if ret_diff > 1.0 and pf_diff > 0.1 and dd_diff <= 2.0:
        status = "✅ 显著改善"
        decision = "✅ 采用移动止盈"
        improved_coins.append(coin)
    elif ret_diff < -1.0 or dd_diff > 3.0:
        status = "❌ 变差"
        decision = "❌ 回退（关闭移动止盈）"
        worse_coins.append(coin)
        overall_better = False
    elif ret_diff > 0.5:
        status = "✅ 改善"
        decision = "✅ 采用移动止盈"
        improved_coins.append(coin)
    elif ret_diff < -0.5:
        status = "➡️ 略变差"
        decision = "➡️ 建议关闭"
        worse_coins.append(coin)
        overall_better = False
    else:
        status = "➡️ 持平"
        decision = "➡️ 可选（无显著差异）"
        flat_coins.append(coin)

    print(f"  {coin:>6}: 收益{ret_diff:>+7.2f}%  盈亏比{pf_diff:>+7.2f}  回撤{dd_diff:>+6.2f}%  "
          f"{status}  → {decision}")

print("  " + "-" * 80)

# ── 最终决策 ──
print("\n  🎯 最终决策:")
if worse_coins:
    print(f"  ❌ 以下币种移动止盈表现变差: {', '.join(worse_coins)}")
    print(f"  → 建议回退，关闭移动止盈")
elif improved_coins and overall_better:
    print(f"  ✅ 以下币种移动止盈有改善: {', '.join(improved_coins)}")
    if flat_coins:
        print(f"  ➡️ 以下币种持平: {', '.join(flat_coins)}")
    print(f"  → 建议启用移动止盈（{TRAIL_ATR_MULT}×ATR, 启动阈值{TRAIL_START_PCT*100:.0f}%）")
else:
    print(f"  ➡️ 移动止盈无显著改善，可保持现状")

print("=" * 100)

# 保存结果
output_file = BASE_DIR / "data" / "trailing_tp_backtest_result.json"
output_file.parent.mkdir(parents=True, exist_ok=True)
output = {
    "trailing_atr_mult": TRAIL_ATR_MULT,
    "trailing_start_pct_of_tp": TRAIL_START_PCT,
    "results": [],
}

for coin, r_base, r_trail in all_results:
    if "error" in r_base or "error" in r_trail:
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
        "trailing": {
            "total_return_pct": r_trail["metrics"]["total_return_pct"],
            "max_drawdown_pct": r_trail["metrics"]["max_drawdown_pct"],
            "sharpe_ratio": r_trail["metrics"]["sharpe_ratio"],
            "total_trades": r_trail["metrics"]["total_trades"],
            "win_rate": r_trail["metrics"]["win_rate"],
            "profit_factor": r_trail["metrics"]["profit_factor"],
            "trailing_tp_trades": r_trail["metrics"].get("trailing_tp_trades", 0),
            "fixed_tp_trades": r_trail["metrics"].get("fixed_tp_trades", 0),
        },
    })

with open(output_file, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"\n  结果已保存: {output_file}")
