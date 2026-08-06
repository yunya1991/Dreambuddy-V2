#!/usr/bin/env python3
"""
宏观特征 K=5 最优子集 9 币种完整验证

用 Phase 2 选出的 top-5 特征:
  stablecoin_growth, tvl_change_7d, fgi_trend_7d, fgi_divergence, fgi_zscore

在 9 币种 5 折完整回测中验证，与 baseline-v1 对比。
"""
import sys
import os
import json
import subprocess
import traceback
import importlib
from datetime import datetime
from pathlib import Path

import numpy as np

# 设置路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
sys.path.insert(0, PROJECT_ROOT)

# 避免 inspect.py 冲突
_std_inspect = importlib.import_module('inspect')
sys.modules['inspect'] = _std_inspect

from scripts.memory_l4.bcrm2.data_fetcher import get_klines
from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester
from scripts.memory_l4.bcrm2.macro_features import MacroFeatures

# ============================================================
# 配置（与 run_baseline_comparison.py 对齐）
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

# Phase 2 选出的最优 5 个宏观特征
BEST_FEATURES = [
    "stablecoin_growth",   # 流动性维度
    "tvl_change_7d",       # 流动性维度
    "fgi_trend_7d",        # 情绪维度
    "fgi_divergence",      # 情绪维度
    "fgi_zscore",          # 情绪维度
]


def build_macro_feat_config(enabled_features):
    """构建特征级开关配置"""
    config = {}
    for feat in MacroFeatures.ALL_FEATURES:
        config[f"macro_feat_{feat}"] = feat in enabled_features
    return config


def get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
        ).decode().strip()
    except Exception:
        return "unknown"


def fetch_ref_df(timeframe, max_bars):
    try:
        ref_df = get_klines("BTC", timeframe, max_bars=max_bars + 200)
        if ref_df is not None and len(ref_df) > 200:
            return ref_df
    except Exception as e:
        print(f"[WARN] 获取 BTC ref_df 失败: {e}")
    return None


def run_single_coin(symbol, ref_df, macro_config, verbose=True):
    """运行单币种回测"""
    print(f"\n{'='*60}")
    print(f"  回测 {symbol} (K=5 宏观特征子集)")
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
            macro_config=macro_config,
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


def aggregate_metrics(per_coin):
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
    print("  宏观特征 K=5 最优子集 — 9 币种 5 折完整验证")
    print("=" * 70)
    print(f"  币种: {', '.join(COINS)}")
    print(f"  启用特征 ({len(BEST_FEATURES)}个): {BEST_FEATURES}")
    print(f"  回测: {N_FOLDS} 折, {MAX_BARS} bars")
    print()

    macro_config = build_macro_feat_config(BEST_FEATURES)
    print(f"  特征开关配置:")
    for feat in MacroFeatures.ALL_FEATURES:
        key = f"macro_feat_{feat}"
        status = "✓" if macro_config[key] else "✗"
        print(f"    {status} {feat}")

    # 获取 BTC ref_df
    print("\n[准备] 获取 BTC 参考数据...")
    ref_df = fetch_ref_df(TIMEFRAME, MAX_BARS)
    if ref_df is not None:
        print(f"  BTC ref_df: {len(ref_df)} bars")

    # 逐币种回测
    per_coin = {}
    for coin in COINS:
        metrics = run_single_coin(coin, ref_df, macro_config, verbose=True)
        if metrics is not None:
            per_coin[coin] = metrics

    summary = aggregate_metrics(per_coin)

    # 保存结果
    v2_result = {
        "version": "v2-macro-k5",
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
            "macro_features": BEST_FEATURES,
        },
        "summary": summary,
        "per_coin_metrics": per_coin,
    }

    output_path = PROJECT_ROOT / "data" / "baseline" / "v2_macro_k5_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(v2_result, indent=2, ensure_ascii=False))
    print(f"\n  v2 结果已保存: {output_path}")

    # 加载 baseline-v1 对比
    v1_path = PROJECT_ROOT / "data" / "baseline" / "baseline_v1.json"
    if v1_path.exists():
        v1_data = json.loads(v1_path.read_text())
        v1_summary = v1_data.get("summary", {})

        print(f"\n{'='*70}")
        print(f"  与 baseline-v1 对比")
        print(f"{'='*70}")

        metrics_to_compare = [
            ("avg_sharpe_ratio", "夏普比率"),
            ("avg_win_rate", "胜率"),
            ("avg_return_pct", "总收益%"),
            ("avg_max_drawdown_pct", "最大回撤%"),
            ("avg_profit_factor", "盈亏比"),
            ("total_trades", "总交易数"),
        ]

        print(f"  {'指标':<15} {'baseline-v1':>15} {'v2-macro-k5':>15} {'变化':>10}")
        print(f"  {'-'*60}")
        for key, label in metrics_to_compare:
            v1_val = v1_summary.get(key, 0)
            v2_val = summary.get(key, 0)
            if v1_val != 0:
                change = (v2_val - v1_val) / abs(v1_val) * 100
                print(f"  {label:<15} {v1_val:>15.4f} {v2_val:>15.4f} {change:>+9.1f}%")
            else:
                print(f"  {label:<15} {v1_val:>15.4f} {v2_val:>15.4f} {'N/A':>10}")

        # 判断是否通过
        v1_sharpe = v1_summary.get("avg_sharpe_ratio", 0)
        v2_sharpe = summary.get("avg_sharpe_ratio", 0)
        v1_wr = v1_summary.get("avg_win_rate", 0)
        v2_wr = summary.get("avg_win_rate", 0)
        v1_dd = v1_summary.get("avg_max_drawdown_pct", 0)
        v2_dd = summary.get("avg_max_drawdown_pct", 0)

        improved = v2_sharpe > v1_sharpe and v2_wr >= v1_wr and v2_dd <= v1_dd

        if improved:
            print(f"\n  ✓ v2-macro-k5 通过验证：夏普↑ 胜率↑ 回撤↓")
            print(f"    宏观特征 K=5 子集可落地")
        else:
            print(f"\n  △ 部分指标未全面优于 baseline-v1")
            if v2_sharpe > v1_sharpe:
                print(f"    夏普: {v1_sharpe:.4f} → {v2_sharpe:.4f} ✓")
            else:
                print(f"    夏普: {v1_sharpe:.4f} → {v2_sharpe:.4f} ✗")
            if v2_wr >= v1_wr:
                print(f"    胜率: {v1_wr:.4f} → {v2_wr:.4f} ✓")
            else:
                print(f"    胜率: {v1_wr:.4f} → {v2_wr:.4f} ✗")
            if v2_dd <= v1_dd:
                print(f"    回撤: {v1_dd:.4f} → {v2_dd:.4f} ✓")
            else:
                print(f"    回撤: {v1_dd:.4f} → {v2_dd:.4f} ✗")
    else:
        print(f"\n  [WARN] baseline-v1 不存在: {v1_path}")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
