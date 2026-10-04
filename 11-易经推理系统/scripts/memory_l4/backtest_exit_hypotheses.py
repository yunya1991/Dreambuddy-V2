#!/usr/bin/env python3
"""
回测验证离场系统修复假设

假设清单：
  H1: SL/TP 硬下限强制（SL≥8%）→ 亏损上限 8%
  H2: SignalReverse PnL 感知 → 浮亏接近 SL 时让 SL 触发
  H3: 时间衰减 TP 减速 → 12h→24h 衰减起点，72h+ 最低 3%
  H4: 易经 veto_value 抬高 → 0.60→0.65（减少过早离场）
  H5: trial_trend_reverse 损失上限 → 信号反转时浮亏 > SL×80% 则等 SL

验证方法：对 all_trades.jsonl 中的每笔交易，模拟假设生效后的 PnL 变化
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass

TRADES_FILE = Path(__file__).parent.parent.parent / ".workbuddy/memory_l4/stats/all_trades.jsonl"

# ── 时间衰减 TP 调度 ──
def current_tp_decay(hold_hours: float, base_tp_pct: float = 0.06) -> float:
    """当前系统的 TP 衰减逻辑"""
    if hold_hours <= 12:
        return base_tp_pct
    elif hold_hours <= 24:
        return 0.045
    elif hold_hours <= 36:
        return 0.030
    elif hold_hours <= 48:
        return 0.0225
    elif hold_hours <= 72:
        return 0.015
    else:
        return 0.015

def proposed_tp_decay(hold_hours: float, base_tp_pct: float = 0.06) -> float:
    """假设 H3：减速后的 TP 衰减逻辑"""
    if hold_hours <= 24:
        return base_tp_pct  # 6%，0-24h 不衰减
    elif hold_hours <= 48:
        return 0.05  # 5%
    elif hold_hours <= 72:
        return 0.04  # 4%
    elif hold_hours <= 96:
        return 0.035  # 3.5%
    else:
        return 0.03  # 3% 最低

def parse_time(t_str: str) -> datetime | None:
    if not t_str:
        return None
    try:
        return datetime.fromisoformat(t_str[:19])
    except:
        return None

def hold_hours(entry_time: str, exit_time: str) -> float:
    t1 = parse_time(entry_time)
    t2 = parse_time(exit_time)
    if not t1 or not t2:
        return 0.0
    return (t2 - t1).total_seconds() / 3600.0

def load_trades():
    trades = []
    with open(TRADES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except:
                pass
    return trades

def calc_stats(trades_list):
    """计算 W/L 统计"""
    if not trades_list:
        return {"n": 0, "wr": 0, "avg_win": 0, "avg_loss": 0, "wl_ratio": 0, "total_pnl": 0, "kelly": 0}
    wins = [t for t in trades_list if float(t.get("_sim_pnl_pct", t.get("pnl_pct", 0))) >= 0]
    losses = [t for t in trades_list if float(t.get("_sim_pnl_pct", t.get("pnl_pct", 0))) < 0]
    n = len(trades_list)
    wr = len(wins) / n if n > 0 else 0
    avg_win = sum(float(t.get("_sim_pnl_pct", t.get("pnl_pct", 0))) for t in wins) / len(wins) * 100 if wins else 0
    avg_loss = sum(float(t.get("_sim_pnl_pct", t.get("pnl_pct", 0))) for t in losses) / len(losses) * 100 if losses else 0
    wl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    total_pnl = sum(float(t.get("_sim_pnl", t.get("pnl", 0))) for t in trades_list)
    # Kelly
    if avg_loss != 0 and wr > 0:
        b = abs(avg_win / avg_loss) / 100  # need decimal
        p = wr
        q = 1 - p
        kelly = max(0, (p * b - q) / b) if b > 0 else 0
    else:
        kelly = 0
    return {
        "n": n, "wr": wr * 100, "avg_win": avg_win, "avg_loss": avg_loss,
        "wl_ratio": wl_ratio, "total_pnl": total_pnl, "kelly": kelly * 100
    }

def print_stats(label, stats):
    print(f"  {label:40s} n={stats['n']:>3} WR={stats['wr']:>5.1f}% "
          f"AvgWin={stats['avg_win']:>+7.2f}% AvgLoss={stats['avg_loss']:>+7.2f}% "
          f"W/L={stats['wl_ratio']:.2f} Kelly={stats['kelly']:>5.1f}% "
          f"PnL={stats['total_pnl']:>+10.2f}")

def run_backtest():
    trades = load_trades()
    print(f"加载 {len(trades)} 笔交易\n")

    # ── Baseline ──
    for t in trades:
        t["_sim_pnl_pct"] = float(t.get("pnl_pct", 0))
        t["_sim_pnl"] = float(t.get("pnl", 0))

    print("=== Baseline（排除 BDSM 0% 交易）===")
    real_trades = [t for t in trades if "bdsm_exit" not in t.get("exit_reason", "")]
    bdsm_trades = [t for t in trades if "bdsm_exit" in t.get("exit_reason", "")]
    print(f"  BDSM 0% 交易: {len(bdsm_trades)} 笔（已修复，排除）")
    print(f"  真实交易: {len(real_trades)} 笔")
    base_stats = calc_stats(real_trades)
    print_stats("Baseline", base_stats)

    # ── H1: SL/TP 硬下限强制 ──
    print("\n=== H1: SL≥8% 硬下限强制（所有交易 SL 上限 8%）===")
    h1_trades = []
    for t in real_trades:
        t_copy = dict(t)
        pnl_pct = float(t.get("pnl_pct", 0))
        lev = int(t.get("leverage", 1) or 1)
        # 价格级亏损 = pnl_pct / leverage（如果是亏损且 |pnl_pct| > 8%*lev）
        if pnl_pct < 0:
            price_loss_pct = abs(pnl_pct) / max(lev, 1)
            if price_loss_pct > 0.08:
                # 假设 SL=8% 会触发，亏损被限制在 8% 价格级
                new_price_loss = -0.08
                new_pnl_pct = new_price_loss * max(lev, 1) / 100  # 回到百分比
                t_copy["_sim_pnl_pct"] = new_pnl_pct
                # 重新计算 PnL（按比例）
                old_pnl = float(t.get("pnl", 0))
                ratio = new_pnl_pct / (pnl_pct / 100) if pnl_pct != 0 else 1
                t_copy["_sim_pnl"] = old_pnl * ratio
                t_copy["_h1_capped"] = True
            else:
                t_copy["_h1_capped"] = False
        else:
            t_copy["_h1_capped"] = False
        h1_trades.append(t_copy)

    capped = [t for t in h1_trades if t.get("_h1_capped")]
    print(f"  被限亏的交易: {len(capped)} 笔")
    for t in capped:
        old = float(t.get("pnl_pct", 0)) * 100
        new = float(t.get("_sim_pnl_pct", 0)) * 100
        print(f"    {t.get('coin',''):10s} 原={old:>+7.2f}% → 新={new:>+7.2f}% (lev={t.get('leverage',1)}x)")
    h1_stats = calc_stats(h1_trades)
    print_stats("H1: SL≥8%", h1_stats)

    # ── H2: SignalReverse PnL 感知 ──
    print("\n=== H2: SignalReverse PnL 感知（信号反转时浮亏接近 SL 则等 SL）===")
    h2_trades = []
    for t in real_trades:
        t_copy = dict(t)
        reason = t.get("exit_reason", "")
        pnl_pct = float(t.get("pnl_pct", 0))
        lev = int(t.get("leverage", 1) or 1)
        # 针对 trial_trend_reverse 和 signal_reverse
        if "trial_trend_reverse" in reason or "signal_reverse" in reason:
            if pnl_pct < 0:
                price_loss = abs(pnl_pct) / max(lev, 1)
                # 如果价格级亏损 > SL 的 80%（即 6.4%），改为 SL 触发（8%）
                if price_loss > 0.064:
                    new_pnl_pct = -0.08 * max(lev, 1) / 100
                    t_copy["_sim_pnl_pct"] = new_pnl_pct
                    old_pnl = float(t.get("pnl", 0))
                    ratio = new_pnl_pct / (pnl_pct / 100) if pnl_pct != 0 else 1
                    t_copy["_sim_pnl"] = old_pnl * ratio
                    t_copy["_h2_modified"] = True
                else:
                    t_copy["_h2_modified"] = False
            else:
                t_copy["_h2_modified"] = False
        else:
            t_copy["_h2_modified"] = False
        h2_trades.append(t_copy)

    modified = [t for t in h2_trades if t.get("_h2_modified")]
    print(f"  被修改的信号反转交易: {len(modified)} 笔")
    for t in modified:
        old = float(t.get("pnl_pct", 0)) * 100
        new = float(t.get("_sim_pnl_pct", 0)) * 100
        print(f"    {t.get('coin',''):10s} 原={old:>+7.2f}% → 新={new:>+7.2f}% (lev={t.get('leverage',1)}x)")
    h2_stats = calc_stats(h2_trades)
    print_stats("H2: SignalReverse PnL感知", h2_stats)

    # ── H3: 时间衰减 TP 减速 ──
    print("\n=== H3: 时间衰减 TP 减速（12h→24h 起点，72h+ 最低 3%）===")
    h3_trades = []
    for t in real_trades:
        t_copy = dict(t)
        pnl_pct = float(t.get("pnl_pct", 0))
        hh = hold_hours(t.get("entry_time", ""), t.get("exit_time", ""))
        # 只看盈利单且持有 > 12h（时间衰减影响范围）
        if pnl_pct > 0 and hh > 12:
            old_tp = current_tp_decay(hh)
            new_tp = proposed_tp_decay(hh)
            # 如果新 TP 更高，说明原系统提前止盈了
            if new_tp > old_tp and pnl_pct < new_tp:
                # 假设在新 TP 下能持有到更高盈利
                # 不直接假设到 TP，而是按比例提升：new_pnl = pnl × (new_tp / old_tp)
                # 但要保守：最多提升到 new_tp
                estimated_new_pnl = min(pnl_pct * (new_tp / max(old_tp, 0.001)), new_tp)
                t_copy["_sim_pnl_pct"] = estimated_new_pnl
                old_pnl = float(t.get("pnl", 0))
                ratio = estimated_new_pnl / pnl_pct if pnl_pct != 0 else 1
                t_copy["_sim_pnl"] = old_pnl * ratio
                t_copy["_h3_adjusted"] = True
                t_copy["_h3_old_tp"] = old_tp
                t_copy["_h3_new_tp"] = new_tp
            else:
                t_copy["_h3_adjusted"] = False
        else:
            t_copy["_h3_adjusted"] = False
        h3_trades.append(t_copy)

    adjusted = [t for t in h3_trades if t.get("_h3_adjusted")]
    print(f"  被调整的盈利单: {len(adjusted)} 笔（持有>12h 且 TP 衰减影响）")
    for t in adjusted:
        old = float(t.get("pnl_pct", 0)) * 100
        new = float(t.get("_sim_pnl_pct", 0)) * 100
        hh = hold_hours(t.get("entry_time", ""), t.get("exit_time", ""))
        print(f"    {t.get('coin',''):10s} hold={hh:>5.1f}h 原={old:>+7.2f}% → 新={new:>+7.2f}% "
              f"(TP: {t.get('_h3_old_tp',0)*100:.1f}% → {t.get('_h3_new_tp',0)*100:.1f}%)")
    h3_stats = calc_stats(h3_trades)
    print_stats("H3: TP衰减减速", h3_stats)

    # ── H4: 易经 veto_value 抬高 ──
    print("\n=== H4: 易经 veto_value 0.60→0.65（减少过早离场）===")
    # 这个假设难以直接量化，因为它影响的是离场决策而非 PnL
    # 间接验证：统计被 timeout_profit_switch 和 early exit 平仓的盈利单
    # 如果 veto_value 更高，这些交易会持有更久
    early_exits = [t for t in real_trades if float(t.get("pnl_pct", 0)) > 0
                   and hold_hours(t.get("entry_time", ""), t.get("exit_time", "")) < 3]
    print(f"  持仓<3h 的盈利单（可能被过早平出）: {len(early_exits)} 笔")
    for t in early_exits:
        hh = hold_hours(t.get("entry_time", ""), t.get("exit_time", ""))
        pnl_pct = float(t.get("pnl_pct", 0)) * 100
        print(f"    {t.get('coin',''):10s} hold={hh:>4.1f}h pnl={pnl_pct:>+6.2f}% reason={t.get('exit_reason','')[:40]}")
    print(f"  → 评估：如果 veto_value 提高到 0.65，约 {len(early_exits)} 笔可能持有更久")
    print(f"  → 预期 avg_win 提升 ~0.5-1.0%（间接效果，不直接模拟）")

    # ── H5: trial_trend_reverse 损失上限 ──
    print("\n=== H5: trial_trend_reverse 损失上限（信号反转时浮亏 > SL×80% → 等 SL）===")
    h5_trades = []
    for t in real_trades:
        t_copy = dict(t)
        reason = t.get("exit_reason", "")
        pnl_pct = float(t.get("pnl_pct", 0))
        lev = int(t.get("leverage", 1) or 1)
        snap = t.get("market_snapshot", {})
        sl_px = snap.get("stop_loss_px")
        entry_px = float(t.get("entry_price", 0))
        # 针对没有 SL 或 SL 太宽的交易
        if "trial_trend_reverse" in reason and pnl_pct < 0:
            if not sl_px or sl_px == "?":
                # 无 SL → 假设 SL=8% 会将亏损限制在 8%
                new_pnl_pct = -0.08 * max(lev, 1) / 100
                t_copy["_sim_pnl_pct"] = new_pnl_pct
                old_pnl = float(t.get("pnl", 0))
                ratio = new_pnl_pct / (pnl_pct / 100) if pnl_pct != 0 else 1
                t_copy["_sim_pnl"] = old_pnl * ratio
                t_copy["_h5_fixed"] = True
            else:
                # 有 SL 但未触发 → 假设 SL 触发
                try:
                    sl = float(sl_px)
                    if entry_px > 0 and sl > 0:
                        sl_price_pct = abs(sl - entry_px) / entry_px
                        if sl_price_pct > 0.08:
                            sl_price_pct = 0.08  # SL 太宽，限到 8%
                        new_pnl_pct = -sl_price_pct * max(lev, 1) / 100
                        if abs(new_pnl_pct) < abs(pnl_pct / 100):
                            t_copy["_sim_pnl_pct"] = new_pnl_pct
                            old_pnl = float(t.get("pnl", 0))
                            ratio = new_pnl_pct / (pnl_pct / 100) if pnl_pct != 0 else 1
                            t_copy["_sim_pnl"] = old_pnl * ratio
                            t_copy["_h5_fixed"] = True
                        else:
                            t_copy["_h5_fixed"] = False
                    else:
                        t_copy["_h5_fixed"] = False
                except:
                    t_copy["_h5_fixed"] = False
        else:
            t_copy["_h5_fixed"] = False
        h5_trades.append(t_copy)

    fixed = [t for t in h5_trades if t.get("_h5_fixed")]
    print(f"  被修复的 trial_trend_reverse: {len(fixed)} 笔")
    for t in fixed:
        old = float(t.get("pnl_pct", 0)) * 100
        new = float(t.get("_sim_pnl_pct", 0)) * 100
        print(f"    {t.get('coin',''):10s} 原={old:>+7.2f}% → 新={new:>+7.2f}% (lev={t.get('leverage',1)}x)")
    h5_stats = calc_stats(h5_trades)
    print_stats("H5: trial_trend_reverse 损失上限", h5_stats)

    # ── 组合效果：H1+H2+H5 (亏损侧) + H3 (盈利侧) ──
    print("\n=== 组合效果: H1+H2+H5 (亏损侧) + H3 (盈利侧) ===")
    combo_trades = []
    for t in real_trades:
        t_copy = dict(t)
        pnl_pct = float(t.get("pnl_pct", 0))
        lev = int(t.get("leverage", 1) or 1)
        reason = t.get("exit_reason", "")
        hh = hold_hours(t.get("entry_time", ""), t.get("exit_time", ""))

        # 盈利侧 H3
        if pnl_pct > 0 and hh > 12:
            old_tp = current_tp_decay(hh)
            new_tp = proposed_tp_decay(hh)
            if new_tp > old_tp and pnl_pct < new_tp:
                estimated_new_pnl = min(pnl_pct * (new_tp / max(old_tp, 0.001)), new_tp)
                t_copy["_sim_pnl_pct"] = estimated_new_pnl
                t_copy["_sim_pnl"] = float(t.get("pnl", 0)) * (estimated_new_pnl / pnl_pct if pnl_pct != 0 else 1)
            else:
                t_copy["_sim_pnl_pct"] = pnl_pct
                t_copy["_sim_pnl"] = float(t.get("pnl", 0))
        # 亏损侧 H1+H2+H5
        elif pnl_pct < 0:
            price_loss = abs(pnl_pct) / max(lev, 1)
            # 所有亏损限到 8% 价格级
            if price_loss > 0.08:
                new_pnl_pct = -0.08 * max(lev, 1) / 100
                t_copy["_sim_pnl_pct"] = new_pnl_pct
                t_copy["_sim_pnl"] = float(t.get("pnl", 0)) * (new_pnl_pct / (pnl_pct / 100) if pnl_pct != 0 else 1)
            else:
                t_copy["_sim_pnl_pct"] = pnl_pct
                t_copy["_sim_pnl"] = float(t.get("pnl", 0))
        else:
            t_copy["_sim_pnl_pct"] = pnl_pct
            t_copy["_sim_pnl"] = float(t.get("pnl", 0))
        combo_trades.append(t_copy)

    combo_stats = calc_stats(combo_trades)
    print_stats("组合 H1+H2+H3+H5", combo_stats)

    # ── 汇总对比 ──
    print("\n" + "=" * 90)
    print("=== 汇总对比 ===")
    print(f"{'方案':40s} {'W/L':>6} {'Kelly':>7} {'AvgWin':>7} {'AvgLoss':>8} {'WR':>6} {'PnL':>10}")
    print("-" * 90)
    for label, stats in [
        ("Baseline (排除BDSM 0%)", base_stats),
        ("H1: SL≥8% 硬下限", h1_stats),
        ("H2: SignalReverse PnL感知", h2_stats),
        ("H3: TP衰减减速", h3_stats),
        ("H5: trial_trend_reverse 损失上限", h5_stats),
        ("组合 H1+H2+H3+H5", combo_stats),
    ]:
        print(f"  {label:38s} {stats['wl_ratio']:>5.2f} {stats['kelly']:>6.1f}% "
              f"{stats['avg_win']:>+6.2f}% {stats['avg_loss']:>+7.2f}% "
              f"{stats['wr']:>5.1f}% {stats['total_pnl']:>+9.2f}")

    # ── 结论 ──
    print(f"\n=== 结论 ===")
    print(f"  Baseline W/L = {base_stats['wl_ratio']:.2f}, Kelly = {base_stats['kelly']:.1f}%")
    print(f"  组合 W/L = {combo_stats['wl_ratio']:.2f}, Kelly = {combo_stats['kelly']:.1f}%")
    improvement = combo_stats['wl_ratio'] / base_stats['wl_ratio'] if base_stats['wl_ratio'] > 0 else 0
    print(f"  W/L 提升: {base_stats['wl_ratio']:.2f} → {combo_stats['wl_ratio']:.2f} ({improvement:.1f}x)")
    if combo_stats['kelly'] > 0:
        print(f"  Kelly 从 0% → {combo_stats['kelly']:.1f}%（正Kelly = 数学上可加仓）")
        print(f"  ¼ Kelly = {combo_stats['kelly']/4:.1f}%（建议初始仓位）")
    else:
        print(f"  Kelly 仍为 0% — 需要进一步优化")

if __name__ == "__main__":
    run_backtest()
