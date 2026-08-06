#!/usr/bin/env python3
"""Phase C walk-forward 验证脚本

对比方案：
  BASE (Phase A+): 宏观二分 + 3日确认 + sticky + 12bar冷却 + Elder-ray仓位
  C    (Phase C) : A+ + 子形态微调 + 易经 risk/value 插值

验证：3 币种 × 5 段 walk-forward，全段退化 < 5% 才通过
"""
import sys
import json
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "lib"))

from v15_backtest import run_backtest, fetch_klines
from walk_forward_validator import WalkForwardValidator

coins = ["BTC", "ETH", "SOL"]
limit = 1500

COMMON_KW = dict(
    use_atr=True,
    use_trailing_tp=True,
    use_direction_gate=True,
    use_btc_windvane=False,
    long_only=False,
    base_position_pct=0.22,
    regime_cooldown_bars=12,
    max_base_holding_hours=29.9,
    max_post_addon_hours=37.7,
    golden_window_hours=11.1,
    trailing_atr_mult=1.0,
    trailing_start_pct_of_tp=0.8,
    use_elder_ray=True,
)

print("=" * 100)
print("  Phase C Walk-Forward 验证")
print("  BASE: Phase A+ (宏观二分 + 3日确认 + sticky + 冷却)")
print("  C   : A+ + 子形态微调(B+) + 易经 risk/value 插值")
print("  验证: 3 币种 × 5 段, 全段退化 < 5% 才通过")
print("=" * 100)

all_coin_reports = []
all_base_trades = []
all_test_trades = []

for coin in coins:
    print(f"\n{'='*80}")
    print(f"  {coin}")
    print(f"{'='*80}")

    klines = fetch_klines(coin, "4h", limit)
    if len(klines) < 200:
        print(f"  数据不足 ({len(klines)} 根)")
        continue

    # BASE: Phase A+
    r_base = run_backtest(coin=coin, klines=klines, **COMMON_KW)
    # Phase B+: 子形态
    r_bp = run_backtest(coin=coin, klines=klines, subregime_enabled=True, **COMMON_KW)
    # Phase C: 子形态 + 易经
    r_c = run_backtest(
        coin=coin, klines=klines,
        subregime_enabled=True, yijing_enabled=True, yijing_step=6,
        **COMMON_KW,
    )

    if "error" in r_base or "error" in r_c:
        print(f"  回测出错")
        continue

    base_trades = r_base.get("trades", [])
    bp_trades = r_bp.get("trades", [])
    c_trades = r_c.get("trades", [])

    # 整体 metrics 对比
    mb = r_base["metrics"]
    mp = r_bp["metrics"]
    mc = r_c["metrics"]
    print(f"\n  整体对比:")
    print(f"    {'方案':>10}  {'收益':>10}  {'交易':>6}  {'胜率':>7}  {'回撤':>8}  {'夏普':>8}")
    print(f"    {'-'*60}")
    for label, m in [("A+(BASE)", mb), ("B+(子形态)", mp), ("C(+易经)", mc)]:
        print(f"    {label:>10}  {m['total_return_pct']:>+9.2f}%  {m['total_trades']:>6}  "
              f"{m['win_rate']*100:>6.1f}%  {m['max_drawdown_pct']:>7.2f}%  {m['sharpe_ratio']:>8.4f}")

    # 易经信息统计
    yiji_trades = [t for t in c_trades if t.get("yiji_hexagram")]
    if yiji_trades:
        hex_dist = Counter(t["yiji_hexagram"] for t in yiji_trades)
        print(f"\n    易经卦象分布(top5): {dict(hex_dist.most_common(5))}")
        avg_risk = sum(t["yiji_risk"] for t in yiji_trades) / len(yiji_trades)
        avg_value = sum(t["yiji_value"] for t in yiji_trades) / len(yiji_trades)
        print(f"    平均 risk={avg_risk:.3f}  value={avg_value:.3f}")

    # Walk-forward: BASE vs C
    validator = WalkForwardValidator(n_segments=5, max_degradation_pct=5.0)
    report = validator.validate(
        base_trades, c_trades, total_bars=limit,
        label_base="A+", label_test="C",
    )
    print()
    print(validator.format_report(report))

    all_coin_reports.append({"coin": coin, "report": report})
    all_base_trades.extend(base_trades)
    all_test_trades.extend(c_trades)

# ── 汇总 ──
print("\n" + "=" * 100)
print("  Phase C Walk-Forward 汇总")
print("=" * 100)

# 逐币种决策
all_pass = True
for cr in all_coin_reports:
    coin = cr["coin"]
    rep = cr["report"]
    status = "✅" if rep["overall_pass"] else "❌"
    print(f"  {coin}: {status} 通过{rep['pass_count']}/{rep['n_segments']}段 "
          f"整体收益差={rep['overall_ret_delta']:+.2f} "
          f"胜率差={rep['overall_wr_delta']:+.2f}%")
    if not rep["overall_pass"]:
        all_pass = False

# 整体汇总（3 币种合并）
print(f"\n  3 币种合并 walk-forward:")
validator_all = WalkForwardValidator(n_segments=5, max_degradation_pct=5.0)
report_all = validator_all.validate(
    all_base_trades, all_test_trades, total_bars=limit,
    label_base="A+(合并)", label_test="C(合并)",
)
print(validator_all.format_report(report_all))

final_pass = all_pass and report_all["overall_pass"]
print(f"\n  最终决策: {'✅ Phase C 通过 → 可部署实盘' if final_pass else '❌ 未通过 → 回退 Phase B+'}")

# 保存结果
output_file = BASE_DIR / "data" / "phase_c_walkforward_result.json"
output = {
    "date": "2026-08-06",
    "phase": "C",
    "description": "Phase A+ + 子形态微调 + 易经 risk/value 插值",
    "final_pass": final_pass,
    "per_coin": {},
    "overall": {
        "pass_count": report_all["pass_count"],
        "n_segments": report_all["n_segments"],
        "overall_pass": report_all["overall_pass"],
        "ret_delta": report_all["overall_ret_delta"],
        "wr_delta": report_all["overall_wr_delta"],
        "calmar_delta": report_all["overall_calmar_delta"],
    },
}
for cr in all_coin_reports:
    r = cr["report"]
    output["per_coin"][cr["coin"]] = {
        "pass": r["overall_pass"],
        "pass_count": r["pass_count"],
        "ret_delta": r["overall_ret_delta"],
        "wr_delta": r["overall_wr_delta"],
    }

with open(output_file, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"\n  结果已保存: {output_file}")
