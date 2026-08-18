#!/usr/bin/env python3
"""Bug修复 收益率对比回测

用同一套历史交易数据（data/bcrm2_phase0/trades_*.csv）+ 同一套K线，
分别用「修复前参数」和「修复后参数」运行 ClassicExitSystem 回测，
量化对比修复前后的收益率、胜率、夏普、回撤、exit_reason分布。

验证目标：
  Bug2修复：L0_RISK_GATE long_thr 0.5→0.65 + min_hold_sec=0→3600 + profit_bypass 3%→5%
  预期效果：减少L0_RISK_GATE误触发（原95.6%→大幅下降），让利润充分奔跑，收益率提升

注：Bug1(48h超时)是polling_trader层门控，不在classic_exit_system回测范围内，
    但会统计历史数据中>48h的交易占比，评估Bug1的潜在影响。
"""
import sys
import os
import json
import time
import math
from pathlib import Path
from copy import deepcopy

# 路径配置
BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT_DIR = str(BASE_DIR / "scripts" / "memory_l4")
# 必须在导入前移除，避免 inspect.py 冲突
if SCRIPT_DIR in sys.path:
    sys.path.remove(SCRIPT_DIR)

PROJECT_ROOT = str(BASE_DIR)
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np

from scripts.memory_l4.classic_exit_system import ExitConfig
# 复用现有回测引擎
from scripts.memory_l4.exit_backtest_optimize import (
    run_backtest, compute_metrics, compute_account_equity,
    load_trades, load_klines, SYMBOLS, LEVERAGE,
    BacktestMetrics, TradeResult,
)


# ============================================================
# 三组参数配置
# ============================================================

# 通用基础参数（与polling_trader.py中一致的部分）
_BASE_PARAMS = dict(
    l0_max_loss_pct=-0.05,
    l1_enabled=True,
    l2_close_threshold=0.75,
    l2_reduce_threshold=0.55,
    apply_leverage_to_thresholds=True,
    tb_enabled=True,
    tb_sl_atr_mult=1.5,
    tb_tp_atr_mult=3.0,
    tb_sl_min_pct=0.045,
    tb_tp_min_pct=0.04,
    trailing_enabled=True,
    trailing_arm_profit_pct=0.04,
    trailing_retrace_pct=0.035,
    tstp_enabled=True,
    inflight_cooldown_sec=180,
)

# ── Config A: 修复前（Bug2未修复：long_thr=0.50, min_hold=0, bypass=3%）──
CONFIG_BEFORE_FIX = ExitConfig(
    **_BASE_PARAMS,
    l0_risk_gate_enabled=True,
    l0_risk_gate_close_enabled=False,
    l0_risk_gate_cooldown_min=60.0,
    l0_risk_gate_confirm_n=3,
    l0_risk_gate_long_thr=0.50,        # Bug2: 原始过低阈值
    l0_risk_gate_short_thr=0.50,
    l0_risk_gate_min_hold_sec=0.0,     # Bug2: 无保护期
    l0_risk_gate_profit_bypass_pct=0.03,  # Bug2: 3%过低
)

# ── Config B: 修复后（Bug2已修复：long_thr=0.65, min_hold=3600, bypass=5%）──
CONFIG_AFTER_FIX = ExitConfig(
    **_BASE_PARAMS,
    l0_risk_gate_enabled=True,
    l0_risk_gate_close_enabled=False,
    l0_risk_gate_cooldown_min=60.0,
    l0_risk_gate_confirm_n=3,
    l0_risk_gate_long_thr=0.65,        # Bug2修复: 0.5→0.65
    l0_risk_gate_short_thr=0.60,       # Bug2修复: 比例同步
    l0_risk_gate_min_hold_sec=3600.0,  # Bug2修复: 1h保护期
    l0_risk_gate_profit_bypass_pct=0.05,  # Bug2修复: 3%→5%
)

# ── Config C: 完全关闭risk_gate（参照组，验证risk_gate本身的价值）──
CONFIG_NO_RISK_GATE = ExitConfig(
    **_BASE_PARAMS,
    l0_risk_gate_enabled=False,        # 完全关闭risk_gate
)


# ============================================================
# 回测执行
# ============================================================
def run_config_backtest(name: str, config: ExitConfig) -> dict:
    """运行一组配置的回测，返回指标dict"""
    print(f"\n{'─'*60}")
    print(f"  运行回测: {name}")
    print(f"  long_thr={config.l0_risk_gate_long_thr} "
          f"min_hold={config.l0_risk_gate_min_hold_sec}s "
          f"bypass={config.l0_risk_gate_profit_bypass_pct}")
    print(f"{'─'*60}")

    t0 = time.time()
    metrics, results = run_backtest(config, symbols=SYMBOLS)
    elapsed = time.time() - t0

    print(f"  完成: {metrics.total_trades}笔交易, 耗时{elapsed:.1f}s")
    print(f"  胜率={metrics.win_rate:.2f}%  总收益={metrics.total_return_pct:.2f}%  "
          f"夏普={metrics.sharpe_ratio:.2f}  回撤={metrics.max_drawdown_pct_account:.2f}%  "
          f"盈亏比={metrics.profit_factor:.2f}")
    print(f"  exit_reason分布: {metrics.exit_reason_dist}")

    return {
        "name": name,
        "config": {
            "long_thr": config.l0_risk_gate_long_thr,
            "short_thr": config.l0_risk_gate_short_thr,
            "min_hold_sec": config.l0_risk_gate_min_hold_sec,
            "profit_bypass_pct": config.l0_risk_gate_profit_bypass_pct,
            "risk_gate_enabled": config.l0_risk_gate_enabled,
        },
        "metrics": {
            "total_trades": metrics.total_trades,
            "win_rate": round(metrics.win_rate, 2),
            "total_return_pct": round(metrics.total_return_pct, 2),
            "total_return_account_pct": round(metrics.total_return_account_pct, 2),
            "avg_return_pct": round(metrics.avg_return_pct, 4),
            "sharpe_ratio": round(metrics.sharpe_ratio, 2),
            "max_drawdown_pct_account": round(metrics.max_drawdown_pct_account, 2),
            "profit_factor": round(metrics.profit_factor, 2),
            "avg_hold_bars": round(metrics.avg_hold_bars, 2),
            "exit_reason_dist": metrics.exit_reason_dist,
            "symbol_metrics": metrics.symbol_metrics,
            "regime_metrics": metrics.regime_metrics,
        },
        "elapsed_sec": round(elapsed, 1),
        "raw_results": results,  # 保留明细用于后续分析
    }


def analyze_48h_timeout_impact() -> dict:
    """分析历史数据中>48h交易占比（Bug1影响评估）"""
    print(f"\n{'─'*60}")
    print(f"  Bug1影响评估: 历史数据中>48h持仓占比")
    print(f"{'─'*60}")

    total_trades = 0
    timeout_trades = 0
    timeout_threshold_bars = 48  # 1H K线，48 bars = 48h

    for symbol in SYMBOLS:
        trades = load_trades(symbol)
        if trades is None:
            continue
        for _, row in trades.iterrows():
            total_trades += 1
            hold_bars = int(row.get("hold_bars", 0))
            if hold_bars > timeout_threshold_bars:
                timeout_trades += 1

    ratio = timeout_trades / total_trades * 100 if total_trades > 0 else 0
    print(f"  总交易: {total_trades}笔, >48h: {timeout_trades}笔 ({ratio:.1f}%)")

    return {
        "total_trades": total_trades,
        "timeout_trades_48h": timeout_trades,
        "timeout_ratio_pct": round(ratio, 1),
        "note": "Bug1修复在polling_trader层，此为历史数据评估其潜在影响",
    }


def compare_exit_reason_dist(before: dict, after: dict, no_gate: dict) -> list:
    """对比三组的exit_reason分布"""
    comparisons = []
    before_dist = before["metrics"]["exit_reason_dist"]
    after_dist = after["metrics"]["exit_reason_dist"]
    no_gate_dist = no_gate["metrics"]["exit_reason_dist"]

    all_reasons = set(list(before_dist.keys()) + list(after_dist.keys()) + list(no_gate_dist.keys()))

    for reason in sorted(all_reasons):
        b = before_dist.get(reason, 0)
        a = after_dist.get(reason, 0)
        n = no_gate_dist.get(reason, 0)
        comparisons.append({
            "exit_reason": reason,
            "before_fix": b,
            "after_fix": a,
            "no_risk_gate": n,
            "delta_after_vs_before": a - b,
        })

    # L0_RISK_GATE 触发率对比
    l0_before = before_dist.get("L0_RISK_GATE", 0)
    l0_after = after_dist.get("L0_RISK_GATE", 0)
    l0_no_gate = no_gate_dist.get("L0_RISK_GATE", 0)
    total = before["metrics"]["total_trades"]

    print(f"\n  L0_RISK_GATE触发率对比:")
    print(f"    修复前: {l0_before}/{total} = {l0_before/total*100:.1f}%")
    print(f"    修复后: {l0_after}/{total} = {l0_after/total*100:.1f}%")
    print(f"    关闭gate: {l0_no_gate}/{total} = {l0_no_gate/total*100:.1f}%")

    return comparisons


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 70)
    print("  离场系统 Bug修复 收益率对比回测")
    print("  数据: data/bcrm2_phase0/trades_{BTC,ETH,SOL,UNI}_1H.csv")
    print("  对比: 修复前 vs 修复后 vs 关闭risk_gate")
    print("=" * 70)

    # 运行三组回测
    result_before = run_config_backtest("A_修复前(Bug2未修复)", CONFIG_BEFORE_FIX)
    result_after = run_config_backtest("B_修复后(Bug2已修复)", CONFIG_AFTER_FIX)
    result_no_gate = run_config_backtest("C_参照组(关闭risk_gate)", CONFIG_NO_RISK_GATE)

    # Bug1影响评估
    bug1_impact = analyze_48h_timeout_impact()

    # exit_reason分布对比
    reason_comparison = compare_exit_reason_dist(result_before, result_after, result_no_gate)

    # 收益率核心对比
    m_before = result_before["metrics"]
    m_after = result_after["metrics"]
    m_no_gate = result_no_gate["metrics"]

    print(f"\n{'='*70}")
    print(f"  【收益率核心对比】")
    print(f"{'='*70}")
    print(f"{'指标':<20} {'修复前':>12} {'修复后':>12} {'关闭gate':>12} {'修复后vs前':>12}")
    print(f"{'─'*70}")
    print(f"{'总收益率(%)':<20} {m_before['total_return_pct']:>12.2f} {m_after['total_return_pct']:>12.2f} {m_no_gate['total_return_pct']:>12.2f} {m_after['total_return_pct']-m_before['total_return_pct']:>+12.2f}")
    print(f"{'账户收益率(%)':<20} {m_before['total_return_account_pct']:>12.2f} {m_after['total_return_account_pct']:>12.2f} {m_no_gate['total_return_account_pct']:>12.2f} {m_after['total_return_account_pct']-m_before['total_return_account_pct']:>+12.2f}")
    print(f"{'胜率(%)':<20} {m_before['win_rate']:>12.2f} {m_after['win_rate']:>12.2f} {m_no_gate['win_rate']:>12.2f} {m_after['win_rate']-m_before['win_rate']:>+12.2f}")
    print(f"{'夏普比率':<20} {m_before['sharpe_ratio']:>12.2f} {m_after['sharpe_ratio']:>12.2f} {m_no_gate['sharpe_ratio']:>12.2f} {m_after['sharpe_ratio']-m_before['sharpe_ratio']:>+12.2f}")
    print(f"{'最大回撤(%)':<20} {m_before['max_drawdown_pct_account']:>12.2f} {m_after['max_drawdown_pct_account']:>12.2f} {m_no_gate['max_drawdown_pct_account']:>12.2f} {m_after['max_drawdown_pct_account']-m_before['max_drawdown_pct_account']:>+12.2f}")
    print(f"{'盈亏比':<20} {m_before['profit_factor']:>12.2f} {m_after['profit_factor']:>12.2f} {m_no_gate['profit_factor']:>12.2f} {m_after['profit_factor']-m_before['profit_factor']:>+12.2f}")
    print(f"{'平均持仓(bars)':<20} {m_before['avg_hold_bars']:>12.2f} {m_after['avg_hold_bars']:>12.2f} {m_no_gate['avg_hold_bars']:>12.2f} {m_after['avg_hold_bars']-m_before['avg_hold_bars']:>+12.2f}")

    # exit_reason分布表
    print(f"\n{'='*70}")
    print(f"  【exit_reason分布对比】")
    print(f"{'='*70}")
    print(f"{'exit_reason':<25} {'修复前':>8} {'修复后':>8} {'关闭gate':>8} {'后vs前':>8}")
    print(f"{'─'*70}")
    for rc in reason_comparison:
        print(f"{rc['exit_reason']:<25} {rc['before_fix']:>8} {rc['after_fix']:>8} {rc['no_risk_gate']:>8} {rc['delta_after_vs_before']:>+8}")

    # 按币种对比
    print(f"\n{'='*70}")
    print(f"  【按币种收益率对比】")
    print(f"{'='*70}")
    print(f"{'币种':<8} {'修复前收益':>12} {'修复后收益':>12} {'关闭gate':>12} {'后vs前':>10}")
    print(f"{'─'*60}")
    for sym in SYMBOLS:
        b_sym = m_before["symbol_metrics"].get(sym, {})
        a_sym = m_after["symbol_metrics"].get(sym, {})
        n_sym = m_no_gate["symbol_metrics"].get(sym, {})
        b_ret = b_sym.get("total_return", 0)
        a_ret = a_sym.get("total_return", 0)
        n_ret = n_sym.get("total_return", 0)
        print(f"{sym:<8} {b_ret:>12.2f} {a_ret:>12.2f} {n_ret:>12.2f} {a_ret-b_ret:>+10.2f}")

    # Bug1影响
    print(f"\n{'='*70}")
    print(f"  【Bug1(48h超时)影响评估】")
    print(f"{'='*70}")
    print(f"  历史交易中>48h持仓: {bug1_impact['timeout_trades_48h']}/{bug1_impact['total_trades']} "
          f"({bug1_impact['timeout_ratio_pct']:.1f}%)")
    print(f"  说明: Bug1修复在polling_trader层（全局门控），回测中classic层不直接体现")
    print(f"        但>48h的老仓位在修复后会被强制降级classic，避免无限调整SL/TP")

    # 保存JSON报告
    report = {
        "backtest_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "data/bcrm2_phase0/trades_{BTC,ETH,SOL,UNI}_1H.csv",
        "leverage": LEVERAGE,
        "symbols": SYMBOLS,
        "bug1_impact": bug1_impact,
        "exit_reason_comparison": reason_comparison,
        "configs": {
            "before_fix": result_before["config"],
            "after_fix": result_after["config"],
            "no_risk_gate": result_no_gate["config"],
        },
        "results": {
            "before_fix": {k: v for k, v in result_before.items() if k != "raw_results"},
            "after_fix": {k: v for k, v in result_after.items() if k != "raw_results"},
            "no_risk_gate": {k: v for k, v in result_no_gate.items() if k != "raw_results"},
        },
        "summary": {
            "total_return_delta": round(m_after["total_return_pct"] - m_before["total_return_pct"], 2),
            "win_rate_delta": round(m_after["win_rate"] - m_before["win_rate"], 2),
            "sharpe_delta": round(m_after["sharpe_ratio"] - m_before["sharpe_ratio"], 2),
            "l0_risk_gate_before_pct": round(
                result_before["metrics"]["exit_reason_dist"].get("L0_RISK_GATE", 0) /
                max(1, m_before["total_trades"]) * 100, 1
            ),
            "l0_risk_gate_after_pct": round(
                result_after["metrics"]["exit_reason_dist"].get("L0_RISK_GATE", 0) /
                max(1, m_after["total_trades"]) * 100, 1
            ),
        },
    }

    out_path = BASE_DIR / "tests" / "data" / "backtest_yield_comparison_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  JSON报告: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
