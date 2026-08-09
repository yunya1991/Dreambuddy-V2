#!/usr/bin/env python3
"""
Phase 4 回测对比脚本 —— 波浪 + 斐波那契时机软调控 TimingGate 是否有效
========================================================================
对比维度:
  - 模型 A (Phase 2): DirectionGate 力学化（MA弹簧 + Verlet + 减速检测）NO timing
                  → use_direction_gate=True, use_timing_gate=False
  - 模型 B (Phase 4): DirectionGate 力学化 + TimingGate 软调控
                  → use_direction_gate=True, use_timing_gate=True

对比币种: BTC, ETH, SOL, ARB, OP, UNI（6 币经典组合）
对比指标: 总收益 (%)、夏普比、最大回撤 (%)、交易数、胜率、盈亏比

输出: 逐币 + 平均。若 Phase4 平均总收益提升 > 5% → 建议默认启用开关。
"""
import json
import sys
from pathlib import Path

import numpy as np

DIR = Path(__file__).parent
sys.path.insert(0, str(DIR / "core"))
sys.path.insert(0, str(DIR / "lib"))

from v15_backtest import fetch_klines, run_backtest

COINS = ["BTC", "ETH", "SOL", "ARB", "OP", "UNI"]
KLIMIT = 1500
INITIAL_CAPITAL = 10000

BO_BEST_PARAMS_JSON = DIR / "output" / "phase4_best_params.json"


def _load_bo_best_params() -> dict:
    """若 output/phase4_best_params.json 存在则加载最优参数并返回 timing 相关 kwargs。"""
    if not BO_BEST_PARAMS_JSON.exists():
        return {}
    try:
        data = json.loads(BO_BEST_PARAMS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}
    params = data.get("params", {}) if isinstance(data, dict) else {}
    # 包含 timing_gate_* 前缀 + timing_size_power（不以 timing_gate_ 开头但属于 timing 参数）
    timing_kwargs = {k: v for k, v in params.items() if k.startswith("timing_gate_")}
    if "timing_size_power" in params:
        timing_kwargs["timing_size_power"] = params["timing_size_power"]
    return timing_kwargs


def _metrics(r: dict) -> dict:
    m = r.get("metrics", {})
    short_cnt = sum(1 for t in r.get("trades", []) if t.get("side") == "SHORT")
    return {
        "total_return_pct": float(m.get("total_return_pct", 0.0) or 0.0),
        "sharpe": float(m.get("sharpe_ratio", 0.0) or 0.0),
        "max_dd_pct": float(m.get("max_drawdown_pct", 0.0) or 0.0),
        "trades": int(m.get("total_trades", 0) or 0),
        "win_rate": float(m.get("win_rate", 0.0) or 0.0),
        "profit_factor": float(m.get("profit_factor", 0.0) or 0.0),
        "short_trades": short_cnt,
    }


def compare_one(coin: str, bo_timing_kwargs: dict) -> dict:
    klines = fetch_klines(coin, "4h", KLIMIT)
    # A: Phase2 (方向先验但无 timing 软调控)
    r_a = run_backtest(
        coin=coin,
        klines=klines,
        initial_capital=INITIAL_CAPITAL,
        use_direction_gate=True,
        use_timing_gate=False,
        # 让 BTC 也走 use_direction_gate（智能默认 BTC 时本来就走）
        # 其他币时 use_direction_gate 可能被覆盖成 btc_windvane，这是 run_backtest 内部智能策略
    )
    # B: Phase4* (叠加 timing + BO 最优参数；若无 BO 则用默认参数)
    r_b = run_backtest(
        coin=coin,
        klines=klines,
        initial_capital=INITIAL_CAPITAL,
        use_direction_gate=True,
        use_timing_gate=True,
        **bo_timing_kwargs,
    )
    ma = _metrics(r_a)
    mb = _metrics(r_b)
    return {"coin": coin, "A": ma, "B": mb, "A_raw": r_a, "B_raw": r_b}


def _delta(old: float, new: float) -> float:
    return new - old


def main():
    bo_timing_kwargs = _load_bo_best_params()
    bo_loaded = bool(bo_timing_kwargs)

    print("=" * 92)
    if bo_loaded:
        print(
            "  Phase 4 回测对比: Phase2(力学化无timing) vs Phase4*(力学化+wave-fib timing + 贝叶斯最优参数)"
        )
    else:
        print("  Phase 4 回测对比: Phase2(力学化无timing) vs Phase4(力学化+wave-fib timing软调控)")
    print("=" * 92)
    print("  A = use_direction_gate=True, use_timing_gate=False (现状力学化基线)")
    if bo_loaded:
        print(
            "  B*= use_direction_gate=True, use_timing_gate=True  + BO最优参数(贝叶斯优化 output/phase4_best_params.json)"
        )
    else:
        print(
            "  B = use_direction_gate=True, use_timing_gate=True  (叠加TimingGate软调控，默认参数)"
        )
    print("  币种:", COINS)
    print("  初始资金:", INITIAL_CAPITAL, "| 4H K线:", KLIMIT)
    print("=" * 92)

    header = (
        f"  {'币种':>6} {'组':>2} "
        f"{'总收益%':>9} {'Δ收益':>8} "
        f"{'夏普':>7} {'Δ夏普':>7} "
        f"{'最大回撤%':>9} {'Δ回撤':>8} "
        f"{'交易数':>6} {'胜率%':>7} {'盈亏比':>7}"
    )
    print(header)
    print("-" * len(header) + "-" * 12)

    results = []
    for coin in COINS:
        print(f"  · 回测 {coin} ... ", end="", flush=True)
        try:
            cmp = compare_one(coin, bo_timing_kwargs)
        except Exception as e:
            print(f"失败: {e}")
            continue
        print("OK")
        results.append(cmp)
        for tag, m in (("A", cmp["A"]), ("B", cmp["B"])):
            dr = _delta(cmp["A"]["total_return_pct"], m["total_return_pct"]) if tag == "B" else 0.0
            ds = _delta(cmp["A"]["sharpe"], m["sharpe"]) if tag == "B" else 0.0
            dd = _delta(cmp["A"]["max_dd_pct"], m["max_dd_pct"]) if tag == "B" else 0.0
            print(
                f"  {cmp['coin']:>6} {tag:>2} "
                f"{m['total_return_pct']:>+8.2f}% {dr:>+7.2f}% "
                f"{m['sharpe']:>7.4f} {ds:>+7.4f} "
                f"{m['max_dd_pct']:>8.2f}% {dd:>+7.2f}% "
                f"{m['trades']:>6} {m['win_rate']*100:>6.2f}% {m['profit_factor']:>7.2f}"
            )
        print(" " * 10 + f"short: A={cmp['A']['short_trades']} | B={cmp['B']['short_trades']}")

    if not results:
        print("❌ 没有成功的回测结果。")
        return

    # 平均统计
    print()
    print("=" * 92)
    print("  📊 平均汇总（逐币算数平均）")
    print("=" * 92)
    for tag in ("A", "B"):
        avg_ret = np.mean([c[tag]["total_return_pct"] for c in results])
        avg_sharpe = np.mean([c[tag]["sharpe"] for c in results])
        avg_dd = np.mean([c[tag]["max_dd_pct"] for c in results])
        avg_trades = np.mean([c[tag]["trades"] for c in results])
        avg_wr = np.mean([c[tag]["win_rate"] for c in results])
        avg_pf = np.mean([c[tag]["profit_factor"] for c in results])
        label = f"Phase {2 if tag=='A' else ('4*' if bo_loaded else '4')}"
        print(
            f"  [{label}] 平均 "
            f"总收益={avg_ret:+.2f}% 夏普={avg_sharpe:.4f} 最大回撤={avg_dd:.2f}% "
            f"交易数={avg_trades:.1f} 胜率={avg_wr*100:.2f}% 盈亏比={avg_pf:.2f}"
        )
    # Δ
    avg_ret_a = np.mean([c["A"]["total_return_pct"] for c in results])
    avg_ret_b = np.mean([c["B"]["total_return_pct"] for c in results])
    avg_sharpe_a = np.mean([c["A"]["sharpe"] for c in results])
    avg_sharpe_b = np.mean([c["B"]["sharpe"] for c in results])
    avg_dd_a = np.mean([c["A"]["max_dd_pct"] for c in results])
    avg_dd_b = np.mean([c["B"]["max_dd_pct"] for c in results])
    delta_ret = avg_ret_b - avg_ret_a
    delta_sharpe = avg_sharpe_b - avg_sharpe_a
    delta_dd = avg_dd_b - avg_dd_a
    rel_ret = (delta_ret / abs(avg_ret_a) * 100.0) if abs(avg_ret_a) > 1e-9 else 0.0
    print()
    print("  Δ (Phase4 - Phase2):")
    print(
        f"    · 平均总收益 {avg_ret_a:+.2f}% → {avg_ret_b:+.2f}%  "
        f"Δ绝对={delta_ret:+.2f}%  Δ相对={rel_ret:+.2f}%"
    )
    print(f"    · 平均夏普   {avg_sharpe_a:.4f}  → {avg_sharpe_b:.4f}  Δ={delta_sharpe:+.4f}")
    print(
        f"    · 平均回撤   {avg_dd_a:.2f}%  → {avg_dd_b:.2f}%  Δ={delta_dd:+.2f}%  (负值=降低回撤=好事)"
    )

    # 判定
    print()
    print("=" * 92)
    print("  🎯 判定：相对收益提升 > 5% 时启用 TimingGate（默认开启），否则关闭但保留代码")
    print("=" * 92)
    if rel_ret > 5.0 and delta_sharpe >= 0.0:
        print(
            "  ✅ Phase4 相对 Phase2 平均总收益提升 > 5% 且夏普不降 → 建议默认打开 V15_USE_TIMING_GATE=true"
        )
        verdict = "ENABLE_GATE"
    elif rel_ret > 0.0 and delta_sharpe > 0.0:
        print(f"  ⚠️  Phase4 收益提升 {rel_ret:+.2f}%（未达5%阈值），夏普提升 {delta_sharpe:+.4f}")
        print("     → 保守：默认关闭开关，保留代码便于后续参数调优/币种特定启用")
        verdict = "KEEP_CLOSED_BUT_PROMISING"
    else:
        print(f"  ❌ Phase4 相对 Phase2 收益变化 {rel_ret:+.2f}%，夏普变化 {delta_sharpe:+.4f}")
        print("     → 默认关闭开关，保持现状，代码保留（可币种特定开启）")
        verdict = "KEEP_CLOSED"

    # 保存详细报告 JSON（便于人工复盘）
    report = {
        "coins": COINS,
        "kline_limit": KLIMIT,
        "initial_capital": INITIAL_CAPITAL,
        "bo_loaded": bo_loaded,
        "bo_timing_kwargs": bo_timing_kwargs,
        "phase4_label": "4*" if bo_loaded else "4",
        "per_coin": [
            {
                "coin": c["coin"],
                "A": c["A"],
                "B": c["B"],
                "delta_return_pct": c["B"]["total_return_pct"] - c["A"]["total_return_pct"],
                "delta_sharpe": c["B"]["sharpe"] - c["A"]["sharpe"],
                "delta_max_dd_pct": c["B"]["max_dd_pct"] - c["A"]["max_dd_pct"],
            }
            for c in results
        ],
        "averages": {
            "A": {"total_return_pct": avg_ret_a, "sharpe": avg_sharpe_a, "max_dd_pct": avg_dd_a},
            "B": {"total_return_pct": avg_ret_b, "sharpe": avg_sharpe_b, "max_dd_pct": avg_dd_b},
            "delta_return_pct": delta_ret,
            "delta_sharpe": delta_sharpe,
            "delta_max_dd_pct": delta_dd,
            "relative_return_pct": rel_ret,
        },
        "verdict": verdict,
    }
    out = DIR / "reports"
    out.mkdir(exist_ok=True)
    out_file = out / "phase4_timing_backtest.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n  📄 详细 JSON 报告: {out_file}")
    print("=" * 92)


if __name__ == "__main__":
    main()
