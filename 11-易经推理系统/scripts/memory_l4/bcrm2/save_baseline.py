#!/usr/bin/env python3
"""
P0 步骤9: 跑 15 币种回测 + 保存基线快照

使用 FeatureRegistry 统一特征计算入口，对 polling_trader 配置的 15 币种
执行 walk-forward 回测，将结果汇总为 baseline_v1.json 基线快照。

非 OKX 可获取的标的（股票/商品）会自动跳过并记录。
"""
import sys
import os
import json
import subprocess
import traceback
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 path 中
# parents[3] = 11-易经推理系统/ (scripts/ 在此目录下)
# parents[4] = dreambuddy-v2/
PROJECT_ROOT = Path(__file__).resolve().parents[3]
YIJING_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(YIJING_ROOT))

from scripts.memory_l4.bcrm2.data_fetcher import get_klines
from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester


# ============================================================
# 配置（与 configs/baseline_config.json 对齐）
# ============================================================
COINS = [
    "UNI", "PUMP", "MU", "SKHYNIX", "HYPE",
    "ETH", "BTC", "SOL", "XAUT", "XAG",
    "GOOGL", "NVDA", "AMZN", "OKB", "BNB",
]

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
    """获取当前 git commit hash"""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
        ).decode().strip()
    except Exception:
        return "unknown"


def get_feature_modules():
    """获取 FeatureRegistry 已注册模块列表"""
    try:
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        # 触发所有模块注册
        import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa
        import scripts.memory_l4.bcrm2.classic_experience_features  # noqa
        import scripts.memory_l4.bcrm2.fibonacci_features  # noqa
        import scripts.memory_l4.bcrm2.pivot_point_features  # noqa
        import scripts.memory_l4.bcrm2.rsi_sentiment_features  # noqa
        import scripts.memory_l4.bcrm2.wdh_features  # noqa
        import scripts.memory_l4.bcrm2.cycle_features  # noqa
        import scripts.memory_l4.bcrm2.market_cap  # noqa
        import scripts.memory_l4.bcrm2.cross_asset_features  # noqa
        import scripts.memory_l4.bcrm2.merrill_clock_features  # noqa
        return FeatureRegistry.list_modules()
    except Exception as e:
        print(f"[WARN] 获取 FeatureRegistry 模块列表失败: {e}")
        return []


def fetch_ref_df(timeframe: str, max_bars: int):
    """获取 BTC 参考数据（用于跨资产特征）"""
    try:
        ref_df = get_klines("BTC", timeframe, max_bars=max_bars + 200)
        if ref_df is not None and len(ref_df) > 200:
            return ref_df
    except Exception as e:
        print(f"[WARN] 获取 BTC ref_df 失败: {e}")
    return None


def run_single_coin(symbol: str, ref_df, verbose: bool = True):
    """运行单币种回测，返回指标字典或 None"""
    print(f"\n{'='*60}")
    print(f"  回测 {symbol}")
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
    """汇总所有币种指标"""
    valid = [v for v in per_coin.values() if v is not None]
    if not valid:
        return {}

    n = len(valid)
    total_trades = sum(v["total_trades"] for v in valid)
    return {
        "coin_count": n,
        "total_trades": total_trades,
        "avg_win_rate": round(sum(v["win_rate"] for v in valid) / n, 4),
        "avg_return_pct": round(sum(v["total_return_pct"] for v in valid) / n, 4),
        "avg_max_drawdown_pct": round(sum(v["max_drawdown_pct"] for v in valid) / n, 4),
        "avg_profit_factor": round(sum(v["profit_factor"] for v in valid) / n, 4),
        "avg_sharpe_ratio": round(sum(v["sharpe_ratio"] for v in valid) / n, 4),
        "avg_hold_bars": round(sum(v["avg_hold_bars"] for v in valid) / n, 2),
    }


def main():
    print("=" * 70)
    print("  P0 基线快照生成 — FeatureRegistry 统一特征入口")
    print("=" * 70)
    print(f"  币种池: {', '.join(COINS)}")
    print(f"  周期: {TIMEFRAME}  K线数: {MAX_BARS}  Folds: {N_FOLDS}")
    print(f"  置信度阈值: {CONF_THRESHOLD}  TP/SL: {TP_ATR}x/{SL_ATR}x ATR")
    print()

    # 获取 BTC ref_df
    print("[准备] 获取 BTC 参考数据...")
    ref_df = fetch_ref_df(TIMEFRAME, MAX_BARS)
    if ref_df is not None:
        print(f"  BTC ref_df: {len(ref_df)} bars")
    else:
        print("  [WARN] BTC ref_df 获取失败，跨资产特征将跳过")

    # 获取 FeatureRegistry 模块列表
    feature_modules = get_feature_modules()
    print(f"  FeatureRegistry 模块: {feature_modules}")

    # 逐币种回测
    per_coin = {}
    skipped = []
    for coin in COINS:
        metrics = run_single_coin(coin, ref_df, verbose=True)
        if metrics is not None:
            per_coin[coin] = metrics
        else:
            skipped.append(coin)

    # 汇总
    summary = aggregate_metrics(per_coin)

    # 保存基线快照
    baseline = {
        "version": "baseline-v1",
        "created_at": datetime.now().isoformat(),
        "git_commit": get_git_commit(),
        "feature_modules": feature_modules,
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
        "skipped_coins": skipped,
    }

    output = PROJECT_ROOT / "data" / "baseline" / "baseline_v1.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(baseline, indent=2, ensure_ascii=False))

    print(f"\n{'='*70}")
    print(f"  基线快照已保存: {output}")
    print(f"  成功回测 {len(per_coin)} 币种, 跳过 {len(skipped)} 币种: {skipped}")
    if summary:
        print(f"  汇总: 平均胜率={summary['avg_win_rate']:.1%} "
              f"平均收益={summary['avg_return_pct']:+.2f}% "
              f"平均夏普={summary['avg_sharpe_ratio']:.2f}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
