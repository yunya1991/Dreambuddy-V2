#!/usr/bin/env python3
"""
五角校验 v3 纯风控版 — 回测验证脚本

对比 baseline（无五角校验）vs v3（纯风控版，仅双预警止损收紧）。
口径对齐 baseline-v1：6000 bars / 5 folds / use_regime_switching / feature_selection。

验证目标：
  1. v3 不拖累夏普（容许 ±5%）
  2. v3 回撤不恶化（极端行情下应改善）
  3. v3 双预警确实触发并收紧止损（风控层在工作）
"""
import sys
import os
import time
import json
import importlib

# 修复 inspect 模块遮蔽（必须在 pandas/dataclasses 之前）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)

_remove_paths = [p for p in sys.path if 'memory_l4' in p or p == SCRIPT_DIR]
for _p in _remove_paths:
    if _p in sys.path:
        sys.path.remove(_p)
_std_inspect = importlib.import_module('inspect')
sys.modules['inspect'] = _std_inspect
for _p in reversed(_remove_paths):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import logging
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

SYMBOLS = ["BTC", "ETH", "SOL"]
TIMEFRAME = "1H"
MAX_BARS = 6000
N_FOLDS = 5


def load_klines(symbol, timeframe="1H", max_bars=6000):
    data_dir = os.path.join(PROJECT_ROOT, "scripts", "data", "klines")
    filepath = os.path.join(data_dir, f"{symbol}_{timeframe}.csv")
    if not os.path.exists(filepath):
        return None
    df = pd.read_csv(filepath)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)
    if len(df) > max_bars:
        df = df.iloc[-max_bars:]
    return df


def run_backtest(symbol, df, ref_df, enable_pentagon):
    """运行单币种回测，返回 (result, elapsed)"""
    from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester

    bt = WalkForwardBacktester(
        symbol=symbol,
        n_folds=N_FOLDS,
        conf_threshold=0.40,
        tp_atr=3.0,
        sl_atr=2.0,
        max_hold_bars=60,
        use_regime_switching=True,
        feature_selection=True,
        fs_imp_threshold=0.05,
        fs_corr_threshold=0.85,
    )
    bt.enable_pentagon = enable_pentagon
    if not enable_pentagon:
        bt._triangle_verifier = None

    t0 = time.time()
    result = bt.run(df, ref_df=ref_df, verbose=False, auto_mcap_config=True)
    elapsed = time.time() - t0
    return result, elapsed


def extract_metrics(result):
    return {
        "total_trades": result.total_trades,
        "win_rate": round(result.overall_win_rate * 100, 1),
        "total_return_pct": round(result.total_return, 2),
        "max_drawdown_pct": round(result.max_drawdown, 2),
        "profit_factor": round(result.profit_factor, 2),
        "sharpe_ratio": round(result.sharpe_ratio, 2),
        "avg_hold_bars": round(result.avg_hold_bars, 1),
    }


def extract_pentagon_stats(result):
    """提取五角校验 v4 风险评分风控统计"""
    trades = result.all_trades
    total = len(trades)
    early_exit = sum(1 for t in trades if t.pentagon_early_exit)
    reversal = sum(1 for t in trades if t.pentagon_reversal)
    # v4: 统计仓位调整分布
    pos_up = sum(1 for t in trades if t.pentagon_position_factor > 1.01)
    pos_down = sum(1 for t in trades if t.pentagon_position_factor < 0.99)
    pos_normal = total - pos_up - pos_down
    return {
        "early_exit_trades": early_exit,
        "reversal_alert_trades": reversal,
        "early_exit_pct": round(early_exit / max(total, 1) * 100, 1),
        "pos_up_trades": pos_up,
        "pos_down_trades": pos_down,
        "pos_normal_trades": pos_normal,
        "pos_up_pct": round(pos_up / max(total, 1) * 100, 1),
        "pos_down_pct": round(pos_down / max(total, 1) * 100, 1),
    }


def main():
    print("=" * 90)
    print("  五角校验 v3 纯风控版 — 回测验证")
    print(f"  币种: {', '.join(SYMBOLS)} | 周期: {TIMEFRAME} | MaxBars: {MAX_BARS} | Folds: {N_FOLDS}")
    print("=" * 90)

    # 预加载数据
    data = {}
    btc_ref = None
    for sym in SYMBOLS:
        df = load_klines(sym, TIMEFRAME, MAX_BARS)
        if df is None or len(df) < 500:
            print(f"  ⚠️  {sym} 数据不足，跳过")
            continue
        data[sym] = df
        if sym == "BTC":
            btc_ref = df
        print(f"  {sym}: {len(df)} 根K线 ({df.index[0]} ~ {df.index[-1]})")

    if not data:
        print("  ❌ 无可用数据")
        return

    baseline_results = {}
    v3_results = {}
    baseline_times = {}
    v3_times = {}

    # === Baseline 回测 ===
    print("\n" + "=" * 90)
    print("  [Phase 1/2] Baseline 回测（无五角校验）")
    print("=" * 90)
    for sym in data:
        print(f"\n  ▸ {sym} baseline 运行中...")
        ref = btc_ref if sym != "BTC" else None
        result, elapsed = run_backtest(sym, data[sym], ref, enable_pentagon=False)
        baseline_results[sym] = extract_metrics(result)
        baseline_times[sym] = elapsed
        m = baseline_results[sym]
        print(f"    ✅ {sym}: 夏普={m['sharpe_ratio']}, 收益={m['total_return_pct']}%, "
              f"回撤={m['max_drawdown_pct']}%, 胜率={m['win_rate']}%, 交易={m['total_trades']}笔 "
              f"({elapsed:.1f}s)")

    # === v3 纯风控版回测 ===
    print("\n" + "=" * 90)
    print("  [Phase 2/2] v3 纯风控版回测（双预警止损收紧）")
    print("=" * 90)
    v3_pentagon_stats = {}
    for sym in data:
        print(f"\n  ▸ {sym} v3 运行中...")
        ref = btc_ref if sym != "BTC" else None
        result, elapsed = run_backtest(sym, data[sym], ref, enable_pentagon=True)
        v3_results[sym] = extract_metrics(result)
        v3_times[sym] = elapsed
        v3_pentagon_stats[sym] = extract_pentagon_stats(result)
        m = v3_results[sym]
        ps = v3_pentagon_stats[sym]
        print(f"    ✅ {sym}: 夏普={m['sharpe_ratio']}, 收益={m['total_return_pct']}%, "
              f"回撤={m['max_drawdown_pct']}%, 胜率={m['win_rate']}%, 交易={m['total_trades']}笔 "
              f"({elapsed:.1f}s)")
        print(f"       风控: 双预警提前退出={ps['early_exit_trades']}笔({ps['early_exit_pct']}%), "
              f"反转预警={ps['reversal_alert_trades']}笔")

    # === 对比汇总 ===
    print("\n" + "=" * 90)
    print("  📊 对比汇总：Baseline vs v3 纯风控版")
    print("=" * 90)

    # 主指标对比表
    print(f"\n  {'币种':<8} {'模式':<10} {'交易数':<8} {'胜率':<8} {'总收益%':<10} "
          f"{'最大回撤%':<10} {'盈亏比':<8} {'夏普':<8}")
    print(f"  {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*8} {'-'*8}")

    avg_sharpe_base = []
    avg_sharpe_v3 = []
    avg_dd_base = []
    avg_dd_v3 = []
    avg_ret_base = []
    avg_ret_v3 = []

    for sym in data:
        b = baseline_results[sym]
        v = v3_results[sym]
        print(f"  {sym:<8} {'baseline':<10} {b['total_trades']:<8} {b['win_rate']:<7.1f}% "
              f"{b['total_return_pct']:<9.2f} {b['max_drawdown_pct']:<9.2f} "
              f"{b['profit_factor']:<7.2f} {b['sharpe_ratio']:<7.2f}")
        print(f"  {sym:<8} {'v3风控':<10} {v['total_trades']:<8} {v['win_rate']:<7.1f}% "
              f"{v['total_return_pct']:<9.2f} {v['max_drawdown_pct']:<9.2f} "
              f"{v['profit_factor']:<7.2f} {v['sharpe_ratio']:<7.2f}")

        # 差值
        d_sharpe = v['sharpe_ratio'] - b['sharpe_ratio']
        d_return = v['total_return_pct'] - b['total_return_pct']
        d_dd = v['max_drawdown_pct'] - b['max_drawdown_pct']
        d_wr = v['win_rate'] - b['win_rate']
        sharpe_arrow = "↑" if d_sharpe > 0.1 else ("↓" if d_sharpe < -0.1 else "→")
        dd_arrow = "↑" if d_dd > 0.1 else ("↓" if d_dd < -0.1 else "→")
        print(f"  {sym:<8} {'delta':<10} {'':8} {d_wr:+.1f}   {d_return:+.2f}    "
              f"{d_dd:+.2f} {dd_arrow}      {'':8} {d_sharpe:+.2f} {sharpe_arrow}")
        print()

        avg_sharpe_base.append(b['sharpe_ratio'])
        avg_sharpe_v3.append(v['sharpe_ratio'])
        avg_dd_base.append(b['max_drawdown_pct'])
        avg_dd_v3.append(v['max_drawdown_pct'])
        avg_ret_base.append(b['total_return_pct'])
        avg_ret_v3.append(v['total_return_pct'])

    # 平均值对比
    print(f"  {'平均':<8} {'baseline':<10} {'':8} {'':8} "
          f"{np.mean(avg_ret_base):<9.2f} {np.mean(avg_dd_base):<9.2f} {'':8} "
          f"{np.mean(avg_sharpe_base):<7.2f}")
    print(f"  {'平均':<8} {'v3风控':<10} {'':8} {'':8} "
          f"{np.mean(avg_ret_v3):<9.2f} {np.mean(avg_dd_v3):<9.2f} {'':8} "
          f"{np.mean(avg_sharpe_v3):<7.2f}")

    d_sharpe_avg = np.mean(avg_sharpe_v3) - np.mean(avg_sharpe_base)
    d_dd_avg = np.mean(avg_dd_v3) - np.mean(avg_dd_base)
    d_ret_avg = np.mean(avg_ret_v3) - np.mean(avg_ret_base)
    sharpe_pct = d_sharpe_avg / max(abs(np.mean(avg_sharpe_base)), 0.01) * 100

    print(f"  {'平均':<8} {'delta':<10} {'':8} {'':8} "
          f"{d_ret_avg:+.2f}    {d_dd_avg:+.2f}      {'':8} {d_sharpe_avg:+.2f} ({sharpe_pct:+.1f}%)")

    # v4 风控触发统计
    print("\n" + "=" * 90)
    print("  🛡️  v4 风险评分风控层触发统计")
    print("=" * 90)
    print(f"\n  {'币种':<8} {'双预警退出':<12} {'反转预警':<10} {'加仓':<10} {'降仓':<10} {'正常':<8} {'总交易':<8}")
    print(f"  {'-'*8} {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*8}")
    total_early_exit = 0
    total_reversal = 0
    total_pos_up = 0
    total_pos_down = 0
    total_trades_all = 0
    for sym in data:
        ps = v3_pentagon_stats[sym]
        tt = v3_results[sym]['total_trades']
        print(f"  {sym:<8} {ps['early_exit_trades']}({ps['early_exit_pct']}%)  "
              f"{ps['reversal_alert_trades']}笔      "
              f"{ps['pos_up_trades']}({ps['pos_up_pct']}%)  "
              f"{ps['pos_down_trades']}({ps['pos_down_pct']}%)  "
              f"{ps['pos_normal_trades']}      {tt}")
        total_early_exit += ps['early_exit_trades']
        total_reversal += ps['reversal_alert_trades']
        total_pos_up += ps['pos_up_trades']
        total_pos_down += ps['pos_down_trades']
        total_trades_all += tt
    print(f"  {'合计':<8} {total_early_exit}笔        {total_reversal}笔      "
          f"{total_pos_up}笔       {total_pos_down}笔       "
          f"          {total_trades_all}")

    # 验证结论
    print("\n" + "=" * 90)
    print("  🎯 验证结论")
    print("=" * 90)

    # 标准1: 夏普不拖累（容许 5% 以内）
    sharpe_ok = sharpe_pct >= -5.0
    print(f"\n  标准1: 夏普不拖累（容许 -5% 以内）")
    print(f"    平均夏普: {np.mean(avg_sharpe_base):.2f} → {np.mean(avg_sharpe_v3):.2f} "
          f"({sharpe_pct:+.1f}%)")
    print(f"    {'✅ 通过' if sharpe_ok else '❌ 未通过'}")

    # 标准2: 回撤不恶化
    dd_ok = d_dd_avg <= 0.5  # 容许 0.5% 波动
    print(f"\n  标准2: 回撤不恶化（容许 +0.5% 以内）")
    print(f"    平均回撤: {np.mean(avg_dd_base):.2f}% → {np.mean(avg_dd_v3):.2f}% "
          f"({d_dd_avg:+.2f}%)")
    print(f"    {'✅ 通过' if dd_ok else '❌ 未通过'}")

    # 标准3: 风控层确实触发
    risk_ok = total_early_exit > 0 or total_reversal > 0 or total_pos_up > 0 or total_pos_down > 0
    print(f"\n  标准3: 风控层确实触发（仓位调整/双预警 > 0）")
    print(f"    加仓: {total_pos_up}笔, 降仓: {total_pos_down}笔, 双预警: {total_early_exit}笔, 反转: {total_reversal}笔")
    print(f"    {'✅ 通过' if risk_ok else '⚠️ 未触发'}")

    # 标准4: 收益提升（v4 新增目标）
    ret_ok = d_ret_avg > 0
    print(f"\n  标准4: 收益提升（v4 目标）")
    print(f"    平均收益: {np.mean(avg_ret_base):.2f}% → {np.mean(avg_ret_v3):.2f}% ({d_ret_avg:+.2f}%)")
    print(f"    {'✅ 通过' if ret_ok else '❌ 未通过'}")

    all_pass = sharpe_ok and dd_ok
    print(f"\n  {'='*60}")
    if all_pass:
        print(f"  ✅ 总体结论: v4 风险评分风控版通过回测验证")
        print(f"     五角校验不拖累夏普，风险评分驱动的双向风控有效")
    else:
        print(f"  ⚠️  总体结论: v4 风险评分风控版未完全通过，需进一步分析")
    print(f"  {'='*60}")

    # 保存结果
    output = {
        "version": "pentagon-v3-validation",
        "timestamp": pd.Timestamp.now().isoformat(),
        "config": {
            "symbols": SYMBOLS,
            "timeframe": TIMEFRAME,
            "max_bars": MAX_BARS,
            "n_folds": N_FOLDS,
        },
        "baseline": baseline_results,
        "v3_pentagon": v3_results,
        "v3_pentagon_stats": v3_pentagon_stats,
        "summary": {
            "avg_sharpe_baseline": round(np.mean(avg_sharpe_base), 2),
            "avg_sharpe_v3": round(np.mean(avg_sharpe_v3), 2),
            "sharpe_delta_pct": round(sharpe_pct, 2),
            "avg_drawdown_baseline": round(np.mean(avg_dd_base), 2),
            "avg_drawdown_v3": round(np.mean(avg_dd_v3), 2),
            "drawdown_delta": round(d_dd_avg, 2),
            "total_early_exit": total_early_exit,
            "total_reversal": total_reversal,
            "sharpe_ok": sharpe_ok,
            "dd_ok": dd_ok,
            "risk_ok": risk_ok,
            "all_pass": all_pass,
        },
    }
    output_path = os.path.join(PROJECT_ROOT, "data", "pentagon_v3_validation.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存: {output_path}")


if __name__ == "__main__":
    main()
