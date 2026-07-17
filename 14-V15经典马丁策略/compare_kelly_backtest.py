#!/usr/bin/env python3
"""凯利公式底仓优化对比回测脚本

对比方案：
  BASE: 固定22%底仓（基线）
  KELLY: 凯利公式优化底仓（半凯利 + 风控上限 + 保守估计）

决策规则：
  - 如果KELLY收益优于BASE → ✅ 采用凯利
  - 如果KELLY收益变差（收益更低 或 回撤显著增大）→ ❌ 回退基线
  - 如果KELLY与BASE相同（凯利建议=基线）→ ➡️ 无影响
"""
import sys
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "lib"))

from v15_backtest import run_backtest, fetch_klines
from kelly_optimizer import format_kelly_report

coins = ["BTC", "ETH", "SOL", "ARB", "OP", "UNI"]
limit = 1500
KELLY_BASE_PCT = 0.22  # 22%基线底仓

print("=" * 95)
print("  凯利公式底仓优化对比回测")
print(f"  基线底仓: {KELLY_BASE_PCT*100:.0f}% | 分数凯利: 0.5x(半凯利) | 风控上限: 单笔≤2%")
print("=" * 95)

all_results = []
kelly_reports = []

for coin in coins:
    print(f"\n  回测 {coin}...", flush=True)
    klines = fetch_klines(coin, "4h", limit)
    if len(klines) < 200:
        print(f"  {coin}: 数据不足({len(klines)}根)")
        continue

    # 基线：固定22%底仓
    r_base = run_backtest(
        coin=coin, klines=klines, use_atr=True,
        use_kelly=False, base_position_pct=KELLY_BASE_PCT,
    )

    # 凯利优化
    r_kelly = run_backtest(
        coin=coin, klines=klines, use_atr=True,
        use_kelly=True, kelly_base_pct=KELLY_BASE_PCT,
    )

    all_results.append((coin, r_base, r_kelly))

    # 输出凯利分析报告
    kp_dict = r_kelly.get("kelly_params")
    if kp_dict:
        from kelly_optimizer import KellyParams
        kp = KellyParams(**kp_dict)
        print(format_kelly_report(kp, coin))

# ── 汇总对比 ──
print("\n" + "=" * 95)
print("  📊 凯利公式底仓优化对比汇总")
print("=" * 95)
print(f"  {'币种':>6}  {'模式':>6}  {'底仓%':>7}  {'总收益':>10}  {'交易数':>6}  {'胜率':>8}  "
      f"{'盈亏比':>8}  {'最大回撤':>10}  {'夏普':>8}  {'连亏':>5}")
print("-" * 95)

for coin, r_base, r_kelly in all_results:
    for label, r in [("BASE", r_base), ("KELLY", r_kelly)]:
        if "error" in r:
            print(f"  {coin:>6}  {label:>6}  ERROR: {r['error']}")
            continue
        m = r["metrics"]
        eff_pct = r.get("effective_base_pct", r.get("base_position_pct", 0))
        print(f"  {coin:>6}  {label:>6}  {eff_pct*100:>6.1f}%  {m['total_return_pct']:>+8.2f}%  "
              f"{m['total_trades']:>6}  {m['win_rate']*100:>7.2f}%  {m['profit_factor']:>8.2f}  "
              f"{m['max_drawdown_pct']:>9.2f}%  {m['sharpe_ratio']:>8.4f}  {m['max_consecutive_losses']:>5}")
    print("-" * 95)

# ── 效果总结与回退决策 ──
print("\n  📈 凯利优化效果总结与回退决策:")
print("  " + "-" * 70)

overall_better = True
worse_coins = []

for coin, r_base, r_kelly in all_results:
    if "error" in r_base or "error" in r_kelly:
        continue

    m_base = r_base["metrics"]
    m_kelly = r_kelly["metrics"]
    kp_dict = r_kelly.get("kelly_params")

    ret_diff = m_kelly["total_return_pct"] - m_base["total_return_pct"]
    dd_diff = m_kelly["max_drawdown_pct"] - m_base["max_drawdown_pct"]
    sharpe_diff = m_kelly["sharpe_ratio"] - m_base["sharpe_ratio"]

    used_kelly = kp_dict.get("used_kelly", False) if kp_dict else False

    # 决策逻辑
    if not used_kelly:
        # 凯利未实际启用（建议=基线 或 样本不足）
        status = "➡️ 无影响（凯利=基线）"
        decision = "保持基线"
    elif ret_diff > 0.5 and dd_diff <= 2.0:
        # 收益改善且回撤未显著增大
        status = "✅ 改善"
        decision = "采用凯利"
    elif ret_diff < -0.5 or dd_diff > 5.0:
        # 收益变差或回撤显著增大
        status = "❌ 变差"
        decision = "❌ 回退基线"
        worse_coins.append(coin)
        overall_better = False
    else:
        status = "➡️ 持平"
        decision = "保持基线（无显著改善）"

    print(f"  {coin:>6}: 收益{ret_diff:>+7.2f}%  回撤{dd_diff:>+6.2f}%  夏普{sharpe_diff:>+7.4f}  "
          f"{status}  → {decision}")

print("  " + "-" * 70)

# ── 最终决策 ──
print("\n  🎯 最终决策:")
if worse_coins:
    print(f"  ❌ 以下币种凯利优化表现变差: {', '.join(worse_coins)}")
    print(f"  → 建议回退到固定{KELLY_BASE_PCT*100:.0f}%基线底仓")
elif overall_better:
    print(f"  ✅ 所有币种凯利优化均未变差，可启用凯利公式底仓优化")
    print(f"  → 采用半凯利(0.5x) + 保守估计 + 2%单笔风控上限")
else:
    print(f"  ➡️ 凯利优化无显著改善，保持固定{KELLY_BASE_PCT*100:.0f}%基线底仓即可")

print("=" * 95)

# ── 保存结果到文件 ──
output_file = BASE_DIR / "data" / "kelly_backtest_result.json"
output_file.parent.mkdir(parents=True, exist_ok=True)
output = {
    "base_pct": KELLY_BASE_PCT,
    "kelly_fraction": 0.5,
    "max_risk_pct": 0.02,
    "results": [],
}

for coin, r_base, r_kelly in all_results:
    if "error" in r_base or "error" in r_kelly:
        continue
    kp_dict = r_kelly.get("kelly_params")
    output["results"].append({
        "coin": coin,
        "base": {
            "total_return_pct": r_base["metrics"]["total_return_pct"],
            "max_drawdown_pct": r_base["metrics"]["max_drawdown_pct"],
            "sharpe_ratio": r_base["metrics"]["sharpe_ratio"],
            "total_trades": r_base["metrics"]["total_trades"],
            "win_rate": r_base["metrics"]["win_rate"],
        },
        "kelly": {
            "total_return_pct": r_kelly["metrics"]["total_return_pct"],
            "max_drawdown_pct": r_kelly["metrics"]["max_drawdown_pct"],
            "sharpe_ratio": r_kelly["metrics"]["sharpe_ratio"],
            "total_trades": r_kelly["metrics"]["total_trades"],
            "win_rate": r_kelly["metrics"]["win_rate"],
            "effective_base_pct": r_kelly.get("effective_base_pct"),
        },
        "kelly_params": kp_dict,
    })

with open(output_file, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"\n  结果已保存: {output_file}")
