#!/usr/bin/env python3
"""高胜率低收益根因分析

回测结果：胜率76.59%，总收益仅5.23%，账户收益仅0.26%
本脚本深入分析每笔交易明细，定位根因。
"""
import sys
import os
import json
import math
import numpy as np
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT_DIR = str(BASE_DIR / "scripts" / "memory_l4")
if SCRIPT_DIR in sys.path:
    sys.path.remove(SCRIPT_DIR)
PROJECT_ROOT = str(BASE_DIR)
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from scripts.memory_l4.classic_exit_system import ExitConfig
from scripts.memory_l4.exit_backtest_optimize import (
    run_backtest, load_trades, load_klines, SYMBOLS, LEVERAGE, FEE_PCT,
)

# 修复后参数
CONFIG = ExitConfig(
    l0_max_loss_pct=-0.05,
    l1_enabled=True,
    l2_close_threshold=0.75,
    l2_reduce_threshold=0.55,
    apply_leverage_to_thresholds=True,
    tb_enabled=True, tb_sl_atr_mult=1.5, tb_tp_atr_mult=3.0,
    tb_sl_min_pct=0.045, tb_tp_min_pct=0.04,
    trailing_enabled=True, trailing_arm_profit_pct=0.04, trailing_retrace_pct=0.035,
    tstp_enabled=True, inflight_cooldown_sec=180,
    l0_risk_gate_enabled=True, l0_risk_gate_close_enabled=False,
    l0_risk_gate_cooldown_min=60.0, l0_risk_gate_confirm_n=3,
    l0_risk_gate_long_thr=0.65, l0_risk_gate_short_thr=0.60,
    l0_risk_gate_min_hold_sec=3600.0, l0_risk_gate_profit_bypass_pct=0.05,
)


def main():
    print("=" * 70)
    print("  高胜率低收益根因分析")
    print("  回测: 252笔交易, 胜率76.59%, 总收益5.23%, 账户收益0.26%")
    print("=" * 70)

    metrics, results = run_backtest(CONFIG, symbols=SYMBOLS)

    # ── 1. 单笔盈亏分布 ──
    pnls = [r.pnl_pct for r in results]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    print(f"\n{'─'*70}")
    print(f"  1. 单笔盈亏分布")
    print(f"{'─'*70}")
    print(f"  总交易: {len(pnls)}")
    print(f"  盈利: {len(wins)}笔, 亏损: {len(losses)}笔")
    print(f"  胜率: {len(wins)/len(pnls)*100:.2f}%")
    print(f"  总收益(简单加总): {sum(pnls):.2f}%")
    print(f"  平均单笔收益: {np.mean(pnls):.4f}%")
    print(f"  中位数收益: {np.median(pnls):.4f}%")

    print(f"\n  盈利交易统计:")
    print(f"    平均盈利: {np.mean(wins):.4f}%  中位数: {np.median(wins):.4f}%")
    print(f"    最大盈利: {max(wins):.4f}%  最小盈利: {min(wins):.4f}%")
    print(f"    总盈利: {sum(wins):.2f}%")

    print(f"\n  亏损交易统计:")
    print(f"    平均亏损: {np.mean(losses):.4f}%  中位数: {np.median(losses):.4f}%")
    print(f"    最大亏损: {min(losses):.4f}%  最小亏损: {max(losses):.4f}%")
    print(f"    总亏损: {sum(losses):.2f}%")

    print(f"\n  盈亏比(总盈利/总亏损): {abs(sum(wins)/sum(losses)):.2f}")
    print(f"  平均盈亏比(平均盈利/平均亏损): {abs(np.mean(wins)/np.mean(losses)):.2f}")

    # ── 2. 盈亏区间分布 ──
    print(f"\n{'─'*70}")
    print(f"  2. 盈亏区间分布（单笔pnl_pct）")
    print(f"{'─'*70}")
    buckets = [
        ("大亏  <-3%", lambda p: p < -3),
        ("中亏  -3%~-1%", lambda p: -3 <= p < -1),
        ("小亏  -1%~-0.2%", lambda p: -1 <= p < -0.2),
        ("微亏  -0.2%~0%", lambda p: -0.2 <= p <= 0),
        ("微赢  0~0.2%", lambda p: 0 < p <= 0.2),
        ("小赢  0.2%~1%", lambda p: 0.2 < p <= 1),
        ("中赢  1%~3%", lambda p: 1 < p <= 3),
        ("大赢  >3%", lambda p: p > 3),
    ]
    print(f"  {'区间':<20} {'笔数':>6} {'占比':>8} {'总收益':>10} {'平均':>8}")
    for label, cond in buckets:
        ps = [p for p in pnls if cond(p)]
        cnt = len(ps)
        pct = cnt / len(pnls) * 100
        total = sum(ps)
        avg = np.mean(ps) if ps else 0
        print(f"  {label:<20} {cnt:>6} {pct:>7.1f}% {total:>+10.2f}% {avg:>+8.4f}%")

    # ── 3. 手续费侵蚀分析 ──
    print(f"\n{'─'*70}")
    print(f"  3. 手续费侵蚀分析")
    print(f"{'─'*70}")
    total_fee = 0.0
    total_gross_pnl = 0.0
    total_net_pnl = 0.0
    for r in results:
        fee = FEE_PCT * 2 * (1 + r.reduce_count)  # 与回测引擎一致
        total_fee += fee
        total_net_pnl += r.pnl_pct
        # pnl_pct已扣费，gross = net + fee
        total_gross_pnl += r.pnl_pct + fee

    print(f"  单边手续费率: {FEE_PCT*100:.2f}%")
    print(f"  杠杆: {LEVERAGE}x")
    print(f"  总交易: {len(results)}笔")
    print(f"  减仓交易: {sum(1 for r in results if r.reduce_count > 0)}笔")
    print(f"  总减仓次数: {sum(r.reduce_count for r in results)}")
    print(f"  ")
    print(f"  总毛收益(扣费前): {total_gross_pnl:.2f}%")
    print(f"  总手续费: {total_fee:.2f}%")
    print(f"  总净收益(扣费后): {total_net_pnl:.2f}%")
    print(f"  手续费占毛收益比: {total_fee/max(total_gross_pnl,0.01)*100:.1f}%")
    print(f"  单笔平均手续费: {total_fee/len(results):.4f}%")
    print(f"  单笔平均毛收益: {total_gross_pnl/len(results):.4f}%")

    # ── 4. 仓位管理分析 ──
    print(f"\n{'─'*70}")
    print(f"  4. 仓位管理分析")
    print(f"{'─'*70}")
    position_size_pct = 0.05  # 回测引擎使用5%仓位
    account_return = sum(pnls) * position_size_pct
    print(f"  单笔仓位: {position_size_pct*100:.0f}% of capital")
    print(f"  杠杆: {LEVERAGE}x")
    print(f"  有效暴露: {position_size_pct*LEVERAGE*100:.0f}% of capital per trade")
    print(f"  总收益率(简单加总): {sum(pnls):.2f}%")
    print(f"  账户收益率: {sum(pnls)*position_size_pct:.2f}%")
    print(f"  说明: 账户收益 = 总收益 × 仓位比例 = {sum(pnls):.2f}% × {position_size_pct} = {sum(pnls)*position_size_pct:.2f}%")

    # ── 5. exit_reason与盈亏关系 ──
    print(f"\n{'─'*70}")
    print(f"  5. exit_reason与盈亏关系")
    print(f"{'─'*70}")
    reason_stats = defaultdict(lambda: {"count": 0, "total_pnl": 0.0, "wins": 0, "pnls": []})
    for r in results:
        reason = r.exit_reason.split("(")[0] if "(" in r.exit_reason else r.exit_reason
        reason_stats[reason]["count"] += 1
        reason_stats[reason]["total_pnl"] += r.pnl_pct
        reason_stats[reason]["pnls"].append(r.pnl_pct)
        if r.pnl_pct > 0:
            reason_stats[reason]["wins"] += 1

    print(f"  {'exit_reason':<30} {'笔数':>5} {'胜率':>7} {'总收益':>10} {'平均':>8} {'中位':>8}")
    print(f"  {'─'*75}")
    for reason in sorted(reason_stats.keys(), key=lambda x: reason_stats[x]["count"], reverse=True):
        s = reason_stats[reason]
        wr = s["wins"] / s["count"] * 100 if s["count"] > 0 else 0
        avg = np.mean(s["pnls"])
        med = np.median(s["pnls"])
        print(f"  {reason:<30} {s['count']:>5} {wr:>6.1f}% {s['total_pnl']:>+10.2f}% {avg:>+8.4f}% {med:>+8.4f}%")

    # ── 6. 持仓时间与盈亏关系 ──
    print(f"\n{'─'*70}")
    print(f"  6. 持仓时间与盈亏关系")
    print(f"{'─'*70}")
    hold_buckets = [
        ("1-3 bars (1-3h)", lambda r: 1 <= r.hold_bars <= 3),
        ("4-7 bars (4-7h)", lambda r: 4 <= r.hold_bars <= 7),
        ("8-15 bars (8-15h)", lambda r: 8 <= r.hold_bars <= 15),
        ("16-30 bars (16-30h)", lambda r: 16 <= r.hold_bars <= 30),
        ("31-48 bars (31-48h)", lambda r: 31 <= r.hold_bars <= 48),
        (">48 bars (>48h)", lambda r: r.hold_bars > 48),
    ]
    print(f"  {'持仓区间':<25} {'笔数':>5} {'胜率':>7} {'总收益':>10} {'平均':>8} {'平均持仓':>8}")
    print(f"  {'─'*70}")
    for label, cond in hold_buckets:
        rs = [r for r in results if cond(r)]
        if not rs:
            continue
        ps = [r.pnl_pct for r in rs]
        wr = sum(1 for p in ps if p > 0) / len(ps) * 100
        total = sum(ps)
        avg = np.mean(ps)
        avg_hold = np.mean([r.hold_bars for r in rs])
        print(f"  {label:<25} {len(rs):>5} {wr:>6.1f}% {total:>+10.2f}% {avg:>+8.4f}% {avg_hold:>8.1f}")

    # ── 7. 核心问题诊断 ──
    print(f"\n{'='*70}")
    print(f"  7. 核心问题诊断")
    print(f"{'='*70}")

    avg_win = np.mean(wins)
    avg_loss = abs(np.mean(losses))
    total_gross = sum(wins)
    total_loss = abs(sum(losses))

    print(f"""
  ┌─────────────────────────────────────────────────────────────────┐
  │ 问题1: 手续费侵蚀严重                                           │
  │   总毛收益: {total_gross_pnl:>8.2f}%  总手续费: {total_fee:>8.2f}%              │
  │   手续费占毛收益: {total_fee/max(total_gross_pnl,0.01)*100:>6.1f}%  ← 这是收益杀手#1        │
  │   单笔平均毛收益: {total_gross_pnl/len(results):>7.4f}%  单笔手续费: {total_fee/len(results):>7.4f}%       │
  │   每笔交易来回成本0.2%(含杠杆)，252笔=50.4%，吃掉绝大部分利润   │
  └─────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │ 问题2: 单笔盈利太小                                             │
  │   平均盈利: {avg_win:.4f}%  平均亏损: {avg_loss:.4f}%                      │
  │   盈亏比(均值): {avg_win/avg_loss:.2f}  ← 低于2.0说明赢的幅度不够大            │
  │   盈利中位数: {np.median(wins):.4f}%  ← 中位数极低，大量微利交易             │
  │   微赢(0~0.2%): {sum(1 for p in wins if p <= 0.2)}笔 / {len(wins)}笔盈利 = {sum(1 for p in wins if p <= 0.2)/len(wins)*100:.1f}%       │
  │   说明: trailing_tp和tstp_chop离场太早，只吃到极小利润            │
  └─────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │ 问题3: 仓位管理过于保守                                         │
  │   单笔仓位: 5%  杠杆: 3x  有效暴露: 15%                         │
  │   账户收益率 = 总收益 × 5% = {sum(pnls):.2f}% × 5% = {sum(pnls)*0.05:.2f}%           │
  │   即使策略收益5.23%，实际账户只增长0.26%                          │
  └─────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │ 问题4: 平均持仓时间短                                           │
  │   平均持仓: {np.mean([r.hold_bars for r in results]):.1f} bars ≈ {np.mean([r.hold_bars for r in results]):.1f}小时            │
  │   1-3h持仓的交易占比高，短持仓→小波动→小利润                    │
  │   交易频率高(252笔)×单笔利润低→手续费占比放大                   │
  └─────────────────────────────────────────────────────────────────┘
""")

    # ┌─ 根因总结 ─┐
    print(f"  【根因总结】")
    print(f"  高胜率(76.59%)来自大量微利离场(trailing_tp/tstp_chop)")
    print(f"  低收益(5.23%)来自三个叠加因素:")
    print(f"    1. 手续费侵蚀: 50.4%总费用吃掉90%+的毛收益 ← 核心杀手")
    print(f"    2. 单笔利润太薄: 平均盈利{avg_win:.2f}%，大量0~0.2%微利交易")
    print(f"    3. 仓位5%保守: 账户收益仅0.26%，策略收益未有效放大")
    print(f"  ")
    print(f"  优化方向:")
    print(f"    A. 降低交易频率: 减少短持仓微利交易（提高trailing_arm/trailing_retrace）")
    print(f"    B. 放大止盈空间: trailing_retrace 0.035→0.05，让利润奔跑更久")
    print(f"    C. 提高仓位比例: 5%→10-15%，或动态仓位（高信心加仓）")
    print(f"    D. 过滤低信号交易: confidence<0.6的不开仓，减少无谓的高频交易")

    return 0


if __name__ == "__main__":
    sys.exit(main())
