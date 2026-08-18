"""自适应策略对比回测

对比4种策略：
1. 原版（无过滤）
2. 优化版v1（固定参数: hold=5, confirm=2, step=3）
3. 综合最优固定参数（hold=15, confirm=4, pos=1.0）
4. 自适应策略（根据牛/熊/震荡动态切换参数）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd

from data.market_data import fetch_historical_candles
from backtest.engine import BacktestEngine
from backtest.strategy import (
    LeastResistanceStrategy,
    AdaptiveLeastResistanceStrategy,
    MovingAverageStrategy,
)


def fetch_real_data(inst_id, days=730):
    candles = fetch_historical_candles(inst_id, bar="1D", days=days)
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def classify_regime(prices):
    close = prices["close"]
    ma200 = close.rolling(window=200, min_periods=200).mean()
    ma50 = close.rolling(window=50, min_periods=50).mean()
    ma200_slope = ma200.pct_change(periods=20)
    regime = pd.Series("sideways", index=prices.index)
    regime[(close > ma200) & (ma50 > ma200) & (ma200_slope > 0)] = "bull"
    regime[(close < ma200) & (ma50 < ma200) & (ma200_slope < 0)] = "bear"
    regime.iloc[:200] = "sideways"
    return regime


def run_backtest(prices, strategy, name, regime=None):
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    try:
        signals = strategy.generate_signals(prices)
        result = engine.run(prices["close"], signals)
        m = result["metrics"]
        trades = result["trades"]
        n_trades = len(trades) if not trades.empty else 0
        avg_hold = trades["holding_bars"].mean() if n_trades > 0 else 0

        stats = {"name": name, "return": m["total_return_pct"], "sharpe": m["sharpe_ratio"],
                 "drawdown": m["max_drawdown_pct"], "trades": n_trades, "avg_holding": avg_hold}

        if regime is not None:
            for r_name in ["bull", "bear", "sideways"]:
                mask = regime == r_name
                if mask.sum() > 0:
                    pos = signals[mask]
                    daily_ret = prices["close"].pct_change()[mask]
                    strategy_ret = pos.shift(1) * daily_ret
                    reg_ret = (1 + strategy_ret.fillna(0)).prod() - 1
                    stats[f"{r_name}_ret"] = float(reg_ret * 100)
                    stats[f"{r_name}_days"] = int(mask.sum())
                else:
                    stats[f"{r_name}_ret"] = 0
                    stats[f"{r_name}_days"] = 0

        if hasattr(strategy, "get_stats"):
            stats["strategy_stats"] = strategy.get_stats()

        return stats
    except Exception as e:
        print(f"  [ERROR] {name}: {e}")
        return None


def main():
    print("=" * 90)
    print("  自适应策略对比回测（多币种 × 多策略）")
    print("=" * 90)

    symbols = [("BTC-USDT", "BTC"), ("ETH-USDT", "ETH"), ("SOL-USDT", "SOL"), ("UNI-USDT", "UNI")]

    all_results = {}

    for inst_id, name in symbols:
        print(f"\n{'='*90}")
        print(f"  {name}")
        print(f"{'='*90}")

        prices = fetch_real_data(inst_id, days=730)
        if prices.empty:
            print(f"  数据获取失败")
            continue

        n = len(prices)
        regime = classify_regime(prices)
        bull_d = (regime == "bull").sum()
        bear_d = (regime == "bear").sum()
        side_d = (regime == "sideways").sum()
        print(f"  数据: {n}天 | 牛市{bull_d}天({bull_d/n*100:.0f}%) 熊市{bear_d}天({bear_d/n*100:.0f}%) 震荡{side_d}天({side_d/n*100:.0f}%)")

        bh = (prices["close"].iloc[-1] / prices["close"].iloc[0] - 1) * 100

        strategies = [
            ("原版", lambda: LeastResistanceStrategy(
                warmup_periods=min(80, n-10), update_step=1,
                enable_trend_filter=False, min_holding_bars=1, signal_confirm_bars=1,
            )),
            ("优化v1", lambda: LeastResistanceStrategy(
                warmup_periods=min(80, n-10), update_step=3,
                min_holding_bars=5, signal_confirm_bars=2,
                enable_trend_filter=True, bear_short_only=True,
            )),
            ("综合最优", lambda: LeastResistanceStrategy(
                warmup_periods=min(80, n-10), update_step=1,
                min_holding_bars=15, signal_confirm_bars=4,
                max_position=1.0, enable_trend_filter=True, bear_short_only=True,
            )),
            ("自适应", lambda: AdaptiveLeastResistanceStrategy(
                warmup_periods=min(80, n-10), update_step=1,
                enable_trend_filter=True,
            )),
            ("双均线", lambda: MovingAverageStrategy(20, 200)),
        ]

        print(f"\n  {'策略':>8} {'收益%':>10} {'夏普':>8} {'回撤%':>8} {'交易':>6} {'持仓天':>8} | "
              f"{'牛市%':>8} {'熊市%':>8} {'震荡%':>8}")
        print(f"  {'-'*90}")

        for sname, strat_fn in strategies:
            strategy = strat_fn()
            r = run_backtest(prices, strategy, sname, regime)
            if r:
                all_results.setdefault(sname, []).append(r)
                bull_r = r.get("bull_ret", 0)
                bear_r = r.get("bear_ret", 0)
                side_r = r.get("sideways_ret", 0)
                print(f"  {r['name']:>8} {r['return']:>+9.2f}% {r['sharpe']:>8.3f} {r['drawdown']:>7.2f}% "
                      f"{r['trades']:>6d} {r['avg_holding']:>7.1f}天 | "
                      f"{bull_r:>+7.2f}% {bear_r:>+7.2f}% {side_r:>+7.2f}%")

        print(f"  {'买入持有':>8} {bh:>+9.2f}%")
        all_results.setdefault("买入持有", []).append({"return": bh, "name": "买入持有"})

    # 汇总
    print(f"\n\n{'='*90}")
    print(f"  汇总：各策略平均收益")
    print(f"{'='*90}")

    print(f"\n  {'策略':>8} {'BTC':>10} {'ETH':>10} {'SOL':>10} {'UNI':>10} {'平均':>10} {'夏普':>8} {'回撤%':>8} {'交易':>6}")
    print(f"  {'-'*85}")

    for sname in ["原版", "优化v1", "综合最优", "自适应", "双均线", "买入持有"]:
        rets = all_results.get(sname, [])
        if not rets:
            continue

        if sname == "买入持有":
            avg_ret = np.mean([r["return"] for r in rets])
            print(f"  {sname:>8} {rets[0]['return']:>+9.2f}% {rets[1]['return']:>+9.2f}% "
                  f"{rets[2]['return']:>+9.2f}% {rets[3]['return']:>+9.2f}% {avg_ret:>+9.2f}%")
            continue

        avg_ret = np.mean([r["return"] for r in rets])
        avg_sharpe = np.mean([r["sharpe"] for r in rets])
        avg_dd = np.mean([r["drawdown"] for r in rets])
        avg_trades = np.mean([r["trades"] for r in rets])

        vals = [r["return"] for r in rets]
        while len(vals) < 4:
            vals.append(0)

        print(f"  {sname:>8} {vals[0]:>+9.2f}% {vals[1]:>+9.2f}% {vals[2]:>+9.2f}% {vals[3]:>+9.2f}% "
              f"{avg_ret:>+9.2f}% {avg_sharpe:>8.3f} {avg_dd:>7.2f}% {avg_trades:>6.0f}")

    # 自适应策略统计
    adaptive_results = all_results.get("自适应", [])
    if adaptive_results:
        print(f"\n  自适应策略市场状态统计:")
        for r in adaptive_results:
            ss = r.get("strategy_stats", {})
            bull = ss.get("regime_bull", 0)
            bear = ss.get("regime_bear", 0)
            side = ss.get("regime_sideways", 0)
            switches = ss.get("regime_switches", 0)
            blocks = ss.get("trend_filter_blocks", 0)
            total = bull + bear + side
            if total > 0:
                print(f"    {r['name'] if 'name' in r else '?':>6}: "
                      f"牛{bull}({bull/total*100:.0f}%) 熊{bear}({bear/total*100:.0f}%) "
                      f"震{side}({side/total*100:.0f}%) | 切换{switchs if False else switches}次 过滤{blocks}次")


if __name__ == "__main__":
    main()
