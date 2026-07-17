"""分市场状态参数优化

1. 划分牛市/熊市/震荡市
2. 对每种市场状态分别扫描参数组合
3. 找到各市场状态下的最优参数
4. 实现自适应策略并回测验证

市场状态划分标准：
- 牛市: 价格>MA200, MA50>MA200, MA200斜率>0
- 熊市: 价格<MA200, MA50<MA200, MA200斜率<0
- 震荡: 不满足牛/熊条件的区域（MA交叉频繁、价格围绕MA200波动）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import json
from itertools import product
from datetime import datetime

from data.market_data import fetch_historical_candles
from backtest.engine import BacktestEngine
from backtest.strategy import LeastResistanceStrategy


def fetch_real_data(inst_id, days=730):
    candles = fetch_historical_candles(inst_id, bar="1D", days=days)
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def classify_market_regime(prices, ma_long=200, ma_short=50, slope_window=20):
    """划分市场状态

    返回: pd.Series, 每天一个值 "bull"/"bear"/"sideways"
    """
    close = prices["close"]
    n = len(close)

    ma200 = close.rolling(window=ma_long, min_periods=ma_long).mean()
    ma50 = close.rolling(window=ma_short, min_periods=ma_short).mean()

    # MA200斜率（20天变化率）
    ma200_slope = ma200.pct_change(periods=slope_window)

    # ADX-like趋势强度：用价格波动范围与方向性运动的比值
    high = prices["high"]
    low = prices["low"]
    atr = (high - low).rolling(window=14).mean()
    directional_move = close.diff(periods=14).abs()
    trend_strength = directional_move / (atr * 14 + 1e-8)

    regime = pd.Series("sideways", index=prices.index)

    bull_mask = (
        (close > ma200) &
        (ma50 > ma200) &
        (ma200_slope > 0.001) &
        (trend_strength > 0.3)
    )
    bear_mask = (
        (close < ma200) &
        (ma50 < ma200) &
        (ma200_slope < -0.001) &
        (trend_strength > 0.3)
    )

    regime[bull_mask] = "bull"
    regime[bear_mask] = "bear"

    regime.iloc[:ma_long] = "sideways"

    return regime


def run_backtest_with_regime(prices, strategy, regime):
    """回测并按市场状态统计收益"""
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    signals = strategy.generate_signals(prices)
    result = engine.run(prices["close"], signals)

    m = result["metrics"]
    trades = result["trades"]

    # 按市场状态统计
    regime_stats = {}
    for r_name in ["bull", "bear", "sideways"]:
        mask = regime == r_name
        days = mask.sum()
        if days == 0:
            regime_stats[r_name] = {"days": 0, "return_pct": 0, "pct": 0}
            continue

        # 该状态下持仓收益贡献
        pos = signals[mask]
        daily_ret = prices["close"].pct_change()[mask]
        strategy_ret = pos.shift(1) * daily_ret
        regime_return = (1 + strategy_ret.fillna(0)).prod() - 1

        regime_stats[r_name] = {
            "days": int(days),
            "return_pct": float(regime_return * 100),
            "pct": float(days / len(regime) * 100),
        }

    n_trades = len(trades) if not trades.empty else 0
    avg_hold = trades["holding_bars"].mean() if n_trades > 0 else 0

    return {
        "return": m["total_return_pct"],
        "sharpe": m["sharpe_ratio"],
        "drawdown": m["max_drawdown_pct"],
        "trades": n_trades,
        "avg_holding": avg_hold,
        "regime_stats": regime_stats,
    }


def scan_params(prices, regime, param_grid):
    """参数扫描，找出各市场状态下的最优参数"""
    results = []

    total_combos = 1
    for v in param_grid.values():
        total_combos *= len(v)
    print(f"  参数组合数: {total_combos}")

    n = len(prices)
    warmup = min(80, n - 10)

    for idx, combo in enumerate(product(*param_grid.values())):
        params = dict(zip(param_grid.keys(), combo))

        strategy = LeastResistanceStrategy(
            warmup_periods=warmup,
            update_step=params["update_step"],
            min_holding_bars=params["min_holding_bars"],
            signal_confirm_bars=params["signal_confirm_bars"],
            max_position=params["max_position"],
            enable_trend_filter=True,
            bear_short_only=True,
            bull_long_only=False,
        )

        r = run_backtest_with_regime(prices, strategy, regime)

        results.append({
            "params": params,
            **r,
        })

        if (idx + 1) % 10 == 0:
            print(f"  进度: {idx+1}/{total_combos} ({(idx+1)/total_combos*100:.0f}%)")

    return results


def find_best_per_regime(results):
    """找出各市场状态下的最优参数"""
    best = {}

    for r_name in ["bull", "bear", "sideways", "overall"]:
        if r_name == "overall":
            sorted_results = sorted(results, key=lambda x: x["return"], reverse=True)
        else:
            # 按该状态下的收益排序
            sorted_results = sorted(
                results,
                key=lambda x: x["regime_stats"].get(r_name, {}).get("return_pct", -999),
                reverse=True,
            )

        if sorted_results:
            best[r_name] = sorted_results[0]

    return best


def main():
    print("=" * 80)
    print("  分市场状态参数优化")
    print("=" * 80)

    # 使用BTC作为基准进行参数搜索（数据最长）
    print("\n[1] 获取BTC历史数据...")
    prices = fetch_real_data("BTC-USDT", days=730)
    if prices.empty:
        print("  数据获取失败")
        return

    n = len(prices)
    print(f"  数据: {n} 天")

    # 市场状态划分
    print("\n[2] 划分市场状态...")
    regime = classify_market_regime(prices)

    bull_days = (regime == "bull").sum()
    bear_days = (regime == "bear").sum()
    side_days = (regime == "sideways").sum()
    print(f"  牛市: {bull_days} 天 ({bull_days/n*100:.1f}%)")
    print(f"  熊市: {bear_days} 天 ({bear_days/n*100:.1f}%)")
    print(f"  震荡: {side_days} 天 ({side_days/n*100:.1f}%)")

    # 验证各状态下的买入持有收益
    for r_name in ["bull", "bear", "sideways"]:
        mask = regime == r_name
        if mask.sum() > 0:
            subset = prices["close"][mask]
            bh = (subset.iloc[-1] / subset.iloc[0] - 1) * 100
            print(f"  {r_name} 买入持有: {bh:+.2f}%")

    # 参数搜索空间
    param_grid = {
        "update_step": [1, 3, 5],
        "min_holding_bars": [3, 5, 7, 10, 15],
        "signal_confirm_bars": [1, 2, 3],
        "max_position": [0.4, 0.6, 0.8],
    }

    print(f"\n[3] 参数扫描...")
    results = scan_params(prices, regime, param_grid)

    # 找出各状态最优参数
    print(f"\n[4] 各市场状态最优参数:")
    best = find_best_per_regime(results)

    print(f"\n{'状态':>8} {'收益%':>10} {'夏普':>8} {'回撤%':>8} {'交易':>6} {'持仓天':>8} | {'step':>5} {'holding':>8} {'confirm':>8} {'pos':>6}")
    print("-" * 95)

    for r_name in ["bull", "bear", "sideways", "overall"]:
        if r_name not in best:
            continue
        b = best[r_name]
        p = b["params"]
        r_label = {"bull": "牛市", "bear": "熊市", "sideways": "震荡", "overall": "综合"}.get(r_name, r_name)
        print(f"{r_label:>8} {b['return']:>+9.2f}% {b['sharpe']:>8.3f} {b['drawdown']:>7.2f}% "
              f"{b['trades']:>6d} {b['avg_holding']:>7.1f}天 | "
              f"{p['update_step']:>5} {p['min_holding_bars']:>8} {p['signal_confirm_bars']:>8} {p['max_position']:>6.1f}")

    # 显示各状态下Top3
    print(f"\n[5] 各状态Top3参数详情:")
    for r_name in ["bull", "bear", "sideways"]:
        r_label = {"bull": "牛市", "bear": "熊市", "sideways": "震荡"}.get(r_name, r_name)
        if r_name == "overall":
            sorted_results = sorted(results, key=lambda x: x["return"], reverse=True)
        else:
            sorted_results = sorted(
                results,
                key=lambda x: x["regime_stats"].get(r_name, {}).get("return_pct", -999),
                reverse=True,
            )

        print(f"\n  {r_label} Top3:")
        for i, r in enumerate(sorted_results[:3]):
            p = r["params"]
            rs = r["regime_stats"].get(r_name, {})
            reg_ret = rs.get("return_pct", 0)
            reg_days = rs.get("days", 0)
            print(f"    #{i+1} {r_name}收益={reg_ret:+.2f}% ({reg_days}天) | "
                  f"总收益={r['return']:+.2f}% 夏普={r['sharpe']:.3f} | "
                  f"step={p['update_step']} hold={p['min_holding_bars']} confirm={p['signal_confirm_bars']} pos={p['max_position']}")

    # 保存结果
    os.makedirs("ml/optimization_results", exist_ok=True)
    output = {
        "timestamp": datetime.now().isoformat(),
        "symbol": "BTC-USDT",
        "n_days": n,
        "regime_distribution": {
            "bull": {"days": int(bull_days), "pct": float(bull_days / n * 100)},
            "bear": {"days": int(bear_days), "pct": float(bear_days / n * 100)},
            "sideways": {"days": int(side_days), "pct": float(side_days / n * 100)},
        },
        "best_params": {},
        "all_results": [],
    }

    for r_name, b in best.items():
        output["best_params"][r_name] = {
            "params": b["params"],
            "return": b["return"],
            "sharpe": b["sharpe"],
            "drawdown": b["drawdown"],
            "trades": b["trades"],
            "avg_holding": b["avg_holding"],
        }

    for r in results[:20]:
        output["all_results"].append({
            "params": r["params"],
            "return": r["return"],
            "sharpe": r["sharpe"],
            "drawdown": r["drawdown"],
            "trades": r["trades"],
            "regime_stats": r["regime_stats"],
        })

    result_file = f"ml/optimization_results/regime_param_optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {result_file}")


if __name__ == "__main__":
    main()
