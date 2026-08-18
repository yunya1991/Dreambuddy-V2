#!/usr/bin/env python3
"""
P1 步骤8: 跑宏观特征回测 + BaselineManager 对比验证

执行流程:
1. 对 9 个 OKX 币种跑包含宏观特征的 walk-forward 回测
2. 保存 v2 回测结果
3. 与 baseline-v1 对比（bootstrap p-value）
4. 输出对比报告 + 通过/不通过结论
"""
import sys
import json
import subprocess
import traceback
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.memory_l4.bcrm2.data_fetcher import get_klines
from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester
from scripts.memory_l4.bcrm2.baseline_manager import BaselineManager


# ============================================================
# 配置（与 baseline_v1 对齐）
# ============================================================
COINS = ["UNI", "PUMP", "HYPE", "ETH", "BTC", "SOL", "XAUT", "OKB", "BNB"]
TIMEFRAME = "1H"
MAX_BARS = 6000
N_FOLDS = 5
CONF_THRESHOLD = 0.40
TP_ATR = 3.0
SL_ATR = 2.0
MAX_HOLD_BARS = 60
FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.001
FEATURE_SELECTION = True


def get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
        ).decode().strip()
    except Exception:
        return "unknown"


def fetch_ref_df(timeframe: str, max_bars: int):
    try:
        ref_df = get_klines("BTC", timeframe, max_bars=max_bars + 200)
        if ref_df is not None and len(ref_df) > 200:
            return ref_df
    except Exception as e:
        print(f"[WARN] 获取 BTC ref_df 失败: {e}")
    return None


def run_single_coin(symbol: str, ref_df, verbose: bool = True):
    """运行单币种回测（包含宏观特征）"""
    print(f"\n{'='*60}")
    print(f"  回测 {symbol} (含宏观特征)")
    print(f"{'='*60}")

    try:
        df = get_klines(symbol, TIMEFRAME, max_bars=MAX_BARS)
        if df is None or len(df) < 500:
            print(f"  [SKIP] 数据不足: {len(df) if df is not None else 0} bars")
            return None
        print(f"  加载 {len(df)} 根K线: {df.index[0]} ~ {df.index[-1]}")

        bt = WalkForwardBacktester(
            symbol=symbol,
            n_folds=N_FOLDS,
            conf_threshold=CONF_THRESHOLD,
            tp_atr=TP_ATR,
            sl_atr=SL_ATR,
            max_hold_bars=MAX_HOLD_BARS,
            fee_rate=FEE_RATE,
            slippage_rate=SLIPPAGE_RATE,
            feature_selection=FEATURE_SELECTION,
        )

        result = bt.run(df, ref_df=ref_df, verbose=verbose)

        metrics = {
            "total_trades": result.total_trades,
            "win_rate": round(result.overall_win_rate, 4),
            "total_return_pct": round(result.total_return, 4),
            "avg_return_per_trade_pct": round(result.avg_return_per_trade, 4),
            "max_drawdown_pct": round(result.max_drawdown, 4),
            "profit_factor": round(result.profit_factor, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "avg_hold_bars": round(result.avg_hold_bars, 2),
            "n_folds": result.n_folds,
            "long_count": result.long_stats.get("count", 0),
            "short_count": result.short_stats.get("count", 0),
        }
        print(f"  交易数={metrics['total_trades']} "
              f"胜率={metrics['win_rate']:.1%} "
              f"收益={metrics['total_return_pct']:+.2f}% "
              f"夏普={metrics['sharpe_ratio']:.2f} "
              f"回撤={metrics['max_drawdown_pct']:.2f}%")
        return metrics

    except Exception as e:
        print(f"  [ERROR] {symbol} 回测失败: {e}")
        traceback.print_exc()
        return None


def aggregate_metrics(per_coin: dict) -> dict:
    valid = [v for v in per_coin.values() if v is not None]
    if not valid:
        return {}
    n = len(valid)
    return {
        "coin_count": n,
        "total_trades": sum(v["total_trades"] for v in valid),
        "avg_win_rate": round(sum(v["win_rate"] for v in valid) / n, 4),
        "avg_return_pct": round(sum(v["total_return_pct"] for v in valid) / n, 4),
        "avg_max_drawdown_pct": round(sum(v["max_drawdown_pct"] for v in valid) / n, 4),
        "avg_profit_factor": round(sum(v["profit_factor"] for v in valid) / n, 4),
        "avg_sharpe_ratio": round(sum(v["sharpe_ratio"] for v in valid) / n, 4),
        "avg_hold_bars": round(sum(v["avg_hold_bars"] for v in valid) / n, 2),
    }


def main():
    print("=" * 70)
    print("  P1 宏观特征回测 + 基线对比验证")
    print("=" * 70)
    print(f"  币种: {', '.join(COINS)}")
    print(f"  版本: v2-macro (含 25 个宏观特征)")
    print(f"  基线: baseline-v1")
    print()

    # 获取 BTC ref_df
    print("[准备] 获取 BTC 参考数据...")
    ref_df = fetch_ref_df(TIMEFRAME, MAX_BARS)
    if ref_df is not None:
        print(f"  BTC ref_df: {len(ref_df)} bars")

    # 逐币种回测
    per_coin = {}
    for coin in COINS:
        metrics = run_single_coin(coin, ref_df, verbose=True)
        if metrics is not None:
            per_coin[coin] = metrics

    summary = aggregate_metrics(per_coin)

    # 保存 v2 结果
    v2_result = {
        "version": "v2-macro",
        "created_at": datetime.now().isoformat(),
        "git_commit": get_git_commit(),
        "config": {
            "coins": COINS,
            "timeframe": TIMEFRAME,
            "max_bars": MAX_BARS,
            "n_folds": N_FOLDS,
            "conf_threshold": CONF_THRESHOLD,
            "tp_atr": TP_ATR,
            "sl_atr": SL_ATR,
            "max_hold_bars": MAX_HOLD_BARS,
            "fee_rate": FEE_RATE,
            "slippage_rate": SLIPPAGE_RATE,
            "feature_selection": FEATURE_SELECTION,
        },
        "summary": summary,
        "per_coin_metrics": per_coin,
    }

    output_v2 = PROJECT_ROOT / "data" / "baseline" / "v2_macro_result.json"
    output_v2.parent.mkdir(parents=True, exist_ok=True)
    output_v2.write_text(json.dumps(v2_result, indent=2, ensure_ascii=False))
    print(f"\n  v2 结果已保存: {output_v2}")

    # 基线对比
    print(f"\n{'='*70}")
    print("  基线对比验证")
    print(f"{'='*70}")

    mgr = BaselineManager()
    report = mgr.compare(v2_result, baseline_version="v1")

    # 打印对比结果
    print(f"\n  基线版本: {report.baseline_version}")
    print(f"  新版本: {report.version}")
    print(f"  通过: {'✓' if report.passed else '✗'}")
    print(f"  建议: {report.recommendation}")
    print(f"  原因: {report.reason}")

    print(f"\n  指标对比:")
    print(f"  {'指标':<25} {'基线':>10} {'新版本':>10} {'变化%':>8} {'p-value':>8} {'显著':>6} {'劣化':>6}")
    print(f"  {'-'*80}")
    for mc in report.metric_comparisons:
        sig = "✓" if mc["is_significant"] else ""
        deg = "✗" if mc["is_degraded"] else ""
        print(f"  {mc['metric']:<25} {mc['baseline_value']:>10.4f} {mc['new_value']:>10.4f} "
              f"{mc['change_pct']*100:>+7.2f}% {mc['p_value']:>8.4f} {sig:>6} {deg:>6}")

    # 保存报告
    report_path = mgr.save_report(report)
    print(f"\n  对比报告已保存: {report_path}")

    if report.passed:
        print(f"\n  ✓ P1 宏观特征通过基线验证，可进入实盘配置")
    else:
        print(f"\n  ✗ P1 宏观特征未通过基线验证，标记为探索方向")
        print(f"    下一步: 继续优化特征工程，或调整宏观特征选择策略")

    print(f"{'='*70}")


if __name__ == "__main__":
    main()
