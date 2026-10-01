#!/usr/bin/env python3
"""Phase B+ 子形态参数微调 对比回测脚本

对比方案：
  BASE (Phase A+): BTC MA128宏观二分 + 3日确认 + sticky + 12bar冷却 + Elder-ray仓位调度
  B+   (Phase B+): Phase A+ + 宏观二分下 Elder-ray 子形态做 TP/holding 小幅微调(±15~20%)

子形态微调逻辑（3bar众数平滑后的Elder-ray方向 × 宏观BULL/BEAR）：
  STRONG (趋势强劲) → tp×1.10, holding×1.20  (让利润跑)
  WEAK   (动能逆转) → tp×0.85, holding×0.70  (快速离场)
  NORMAL (基准)     → tp×1.00, holding×1.00

落地门槛：avg Calmar + 胜率 同比提升，且 max_dd 不恶化 >2pp，否则回退 Phase A+
"""
import sys
import json
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "lib"))

from v15_backtest import run_backtest, fetch_klines

coins = ["BTC", "ETH", "SOL"]
limit = 1500

# Phase A+ 智能参数基线（来自 data/phase_a_plus_result.json）
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

print("=" * 110)
print("  Phase B+ 子形态参数微调 对比回测")
print("  BASE (A+): 宏观二分 + 3日确认 + sticky + 12bar冷却 + Elder-ray仓位")
print("  B+    : A+ + 宏观下Elder-ray子形态 TP/holding 小幅微调(±15~20%)")
print("=" * 110)

all_results = []

for coin in coins:
    print(f"\n  回测 {coin}...", flush=True)
    klines = fetch_klines(coin, "4h", limit)
    if len(klines) < 200:
        print(f"  {coin}: 数据不足 ({len(klines)} 根)")
        continue

    # Phase A+ 基线
    r_base = run_backtest(coin=coin, klines=klines, **COMMON_KW)
    # Phase B+ 子形态微调
    r_bp = run_backtest(coin=coin, klines=klines, subregime_enabled=True, **COMMON_KW)

    all_results.append((coin, r_base, r_bp))

    if "error" in r_base or "error" in r_bp:
        print(f"  {coin}: 回测出错 base={r_base.get('error')} bp={r_bp.get('error')}")
        continue

    m_base = r_base["metrics"]
    m_bp = r_bp["metrics"]

    print(f"\n  {coin} 详细对比:")
    print(f"    指标            BASE(A+)       B+(子形态)       差值")
    print(f"    {'-'*68}")
    print(f"    总收益:     {m_base['total_return_pct']:>+10.2f}%    {m_bp['total_return_pct']:>+10.2f}%    {m_bp['total_return_pct'] - m_base['total_return_pct']:>+9.2f}%")
    print(f"    交易数:     {m_base['total_trades']:>10}      {m_bp['total_trades']:>10}      {m_bp['total_trades'] - m_base['total_trades']:>+8}")
    print(f"    胜率:       {m_base['win_rate']*100:>9.2f}%     {m_bp['win_rate']*100:>9.2f}%     {m_bp['win_rate']*100 - m_base['win_rate']*100:>+9.2f}%")
    print(f"    盈亏比:     {m_base['profit_factor']:>10.2f}     {m_bp['profit_factor']:>10.2f}     {m_bp['profit_factor'] - m_base['profit_factor']:>+9.2f}")
    print(f"    最大回撤:   {m_base['max_drawdown_pct']:>9.2f}%     {m_bp['max_drawdown_pct']:>9.2f}%     {m_bp['max_drawdown_pct'] - m_base['max_drawdown_pct']:>+9.2f}%")
    print(f"    夏普比:     {m_base['sharpe_ratio']:>10.4f}     {m_bp['sharpe_ratio']:>10.4f}     {m_bp['sharpe_ratio'] - m_base['sharpe_ratio']:>+9.4f}")

    # 子形态分布统计
    bp_trades = r_bp.get("trades", [])
    sr_dist = Counter(t.get("subregime") for t in bp_trades)
    print(f"\n    B+ 子形态分布: {dict(sr_dist)}")

# ── 汇总对比 ──
print("\n" + "=" * 110)
print("  Phase B+ 子形态微调 对比汇总")
print("=" * 110)
print(f"  {'币种':>6}  {'模式':>8}  {'总收益':>10}  {'交易数':>6}  {'胜率':>7}  "
      f"{'盈亏比':>7}  {'最大回撤':>9}  {'夏普':>9}  {'Calmar':>8}")
print("-" * 110)

valid = [(c, b, p) for c, b, p in all_results if "error" not in b and "error" not in p]
for coin, r_base, r_bp in valid:
    for label, r in [("A+", r_base), ("B+", r_bp)]:
        m = r["metrics"]
        calmar = (m["total_return_pct"] / m["max_drawdown_pct"]) if m["max_drawdown_pct"] > 0 else 0
        print(f"  {coin:>6}  {label:>8}  {m['total_return_pct']:>+9.2f}%  {m['total_trades']:>6}  "
              f"{m['win_rate']*100:>6.2f}%  {m['profit_factor']:>7.2f}  "
              f"{m['max_drawdown_pct']:>8.2f}%  {m['sharpe_ratio']:>9.4f}  {calmar:>8.2f}")
    print("-" * 110)

# ── 均值对比与决策 ──
if not valid:
    print("\n  无有效回测结果，退出")
    sys.exit(1)

def avg(rs, key):
    return sum(r["metrics"][key] for r in rs) / len(rs)

base_rs = [b for _, b, _ in valid]
bp_rs = [p for _, _, p in valid]

avg_ret_b = avg(base_rs, "total_return_pct")
avg_ret_p = avg(bp_rs, "total_return_pct")
avg_dd_b = avg(base_rs, "max_drawdown_pct")
avg_dd_p = avg(bp_rs, "max_drawdown_pct")
avg_wr_b = avg(base_rs, "win_rate")
avg_wr_p = avg(bp_rs, "win_rate")
avg_sh_b = avg(base_rs, "sharpe_ratio")
avg_sh_p = avg(bp_rs, "sharpe_ratio")
calmar_b = avg_ret_b / avg_dd_b if avg_dd_b > 0 else 0
calmar_p = avg_ret_p / avg_dd_p if avg_dd_p > 0 else 0

print(f"\n  均值对比 (n={len(valid)} 币种):")
print(f"  {'指标':>12}  {'BASE(A+)':>12}  {'B+(子形态)':>12}  {'差值':>10}  {'判定':>8}")
print(f"  {'-'*68}")
print(f"  {'平均收益':>12}  {avg_ret_b:>11.2f}%  {avg_ret_p:>11.2f}%  {avg_ret_p-avg_ret_b:>+9.2f}%  {'✅' if avg_ret_p>avg_ret_b else '❌'}")
print(f"  {'平均胜率':>12}  {avg_wr_b*100:>11.2f}%  {avg_wr_p*100:>11.2f}%  {(avg_wr_p-avg_wr_b)*100:>+9.2f}%  {'✅' if avg_wr_p>avg_wr_b else '❌'}")
print(f"  {'平均回撤':>12}  {avg_dd_b:>11.2f}%  {avg_dd_p:>11.2f}%  {avg_dd_p-avg_dd_b:>+9.2f}%  {'✅' if avg_dd_p<=avg_dd_b+2 else '❌'}")
print(f"  {'平均夏普':>12}  {avg_sh_b:>12.4f}  {avg_sh_p:>12.4f}  {avg_sh_p-avg_sh_b:>+10.4f}  {'✅' if avg_sh_p>avg_sh_b else '❌'}")
print(f"  {'Calmar':>12}  {calmar_b:>12.2f}  {calmar_p:>12.2f}  {calmar_p-calmar_b:>+10.2f}  {'✅' if calmar_p>calmar_b else '❌'}")
print(f"  {'-'*68}")

# ── 落地决策 ──
ret_up = avg_ret_p > avg_ret_b
wr_up = avg_wr_p > avg_wr_b
dd_ok = avg_dd_p <= avg_dd_b + 2.0
calmar_up = calmar_p > calmar_b

print(f"\n  落地门槛校验:")
print(f"    1. 平均收益提升:   {'✅' if ret_up else '❌'} ({avg_ret_p-avg_ret_b:+.2f}%)")
print(f"    2. 平均胜率提升:   {'✅' if wr_up else '❌'} ({(avg_wr_p-avg_wr_b)*100:+.2f}%)")
print(f"    3. 回撤不恶化>2pp: {'✅' if dd_ok else '❌'} ({avg_dd_p-avg_dd_b:+.2f}%)")
print(f"    4. Calmar 提升:    {'✅' if calmar_up else '❌'} ({calmar_p-calmar_b:+.2f})")

# 门槛：Calmar + 胜率 同比提升，且回撤不恶化 >2pp
pass_gate = calmar_up and wr_up and dd_ok
print(f"\n  最终决策: {'✅ 通过 → 可部署 Phase B+ 到实盘' if pass_gate else '❌ 未通过 → 回退 Phase A+'}")

# 保存结果
output_file = BASE_DIR / "data" / "phase_b_plus_result.json"
output = {
    "date": "2026-08-06",
    "phase": "B+",
    "description": "Phase A+ + 宏观二分下Elder-ray子形态 TP/holding 小幅微调",
    "config": {**COMMON_KW, "subregime_enabled": True, "subregime_mults": "DEFAULT_SUBREGIME_MULTS"},
    "summary": {
        "avg_return_pct": round(avg_ret_p, 2),
        "avg_max_drawdown_pct": round(avg_dd_p, 2),
        "avg_win_rate": round(avg_wr_p, 4),
        "calmar_ratio": round(calmar_p, 2),
        "avg_sharpe_ratio": round(avg_sh_p, 4),
        "total_trades": sum(r["metrics"]["total_trades"] for r in bp_rs),
        "valid_coins": len(valid),
        "baseline_calmar": round(calmar_b, 2),
        "baseline_avg_return": round(avg_ret_b, 2),
        "baseline_avg_win_rate": round(avg_wr_b, 4),
        "pass_gate": pass_gate,
    },
    "per_coin": {},
}
for coin, r_base, r_bp in valid:
    mb = r_base["metrics"]
    mp = r_bp["metrics"]
    bp_trades = r_bp.get("trades", [])
    sr_dist = Counter(t.get("subregime") for t in bp_trades)
    output["per_coin"][coin] = {
        "base_return_pct": round(mb["total_return_pct"], 2),
        "bp_return_pct": round(mp["total_return_pct"], 2),
        "base_win_rate": round(mb["win_rate"], 4),
        "bp_win_rate": round(mp["win_rate"], 4),
        "base_dd": round(mb["max_drawdown_pct"], 2),
        "bp_dd": round(mp["max_drawdown_pct"], 2),
        "bp_subregime_dist": dict(sr_dist),
    }

with open(output_file, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"\n  结果已保存: {output_file}")
print("=" * 110)
