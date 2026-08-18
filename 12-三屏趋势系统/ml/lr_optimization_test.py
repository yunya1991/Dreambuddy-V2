"""最小阻力策略优化前后对比回测

对比原版和优化版（降低交易频率+趋势过滤+最小持仓）的表现。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd

from data.market_data import fetch_historical_candles
from backtest.engine import BacktestEngine
from backtest.strategy import LeastResistanceStrategy, MovingAverageStrategy


def fetch_real_data(inst_id, days=730):
    candles = fetch_historical_candles(inst_id, bar="1D", days=days)
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def run_backtest(prices, strategy, name):
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    try:
        signals = strategy.generate_signals(prices)
        result = engine.run(prices["close"], signals)
        m = result["metrics"]
        trades = result["trades"]
        n_trades = len(trades) if not trades.empty else 0
        avg_hold = trades["holding_bars"].mean() if n_trades > 0 else 0

        return {
            "name": name,
            "return": m["total_return_pct"],
            "sharpe": m["sharpe_ratio"],
            "drawdown": m["max_drawdown_pct"],
            "trades": n_trades,
            "avg_holding": avg_hold,
        }
    except Exception as e:
        print(f"  [ERROR] {name}: {e}")
        return None


def main():
    print("=" * 80)
    print("  最小阻力策略优化对比回测（2年历史数据）")
    print("=" * 80)

    symbols = [("BTC-USDT", "BTC"), ("ETH-USDT", "ETH"), ("SOL-USDT", "SOL"), ("UNI-USDT", "UNI")]

    strategies = [
        ("原版", lambda n: LeastResistanceStrategy(
            warmup_periods=min(80, n-10), update_step=1,
            enable_trend_filter=False, min_holding_bars=1, signal_confirm_bars=1,
        )),
        ("优化版v1", lambda n: LeastResistanceStrategy(
            warmup_periods=min(80, n-10), update_step=3,
            min_holding_bars=5, signal_confirm_bars=2,
            enable_trend_filter=True, bear_short_only=True, bull_long_only=False,
        )),
        ("优化版v2(强过滤)", lambda n: LeastResistanceStrategy(
            warmup_periods=min(80, n-10), update_step=5,
            min_holding_bars=10, signal_confirm_bars=3,
            enable_trend_filter=True, bear_short_only=True, bull_long_only=False,
        )),
    ]

    all_results = {sname: [] for sname, _ in strategies}
    all_results["买入持有"] = []

    for inst_id, name in symbols:
        print(f"\n{'='*80}")
        print(f"  {name}")
        print(f"{'='*80}")

        prices = fetch_real_data(inst_id, days=730)
        if prices.empty:
            print(f"  数据获取失败")
            continue

        n = len(prices)
        bh = (prices["close"].iloc[-1] / prices["close"].iloc[0] - 1) * 100
        all_results["买入持有"].append(bh)

        print(f"\n  {'策略':>12} {'收益':>10} {'夏普':>8} {'回撤':>8} {'交易':>6} {'持仓天':>8}")
        print(f"  {'-'*60}")

        for sname, strat_fn in strategies:
            strategy = strat_fn(n)
            r = run_backtest(prices, strategy, sname)
            if r:
                all_results[sname].append(r["return"])
                print(f"  {r['name']:>12} {r['return']:>+9.2f}% {r['sharpe']:>8.3f} "
                      f"{r['drawdown']:>7.2f}% {r['trades']:>6d} {r['avg_holding']:>7.1f}天")

        print(f"  {'买入持有':>12} {bh:>+9.2f}%")

    print(f"\n\n{'='*80}")
    print(f"  汇总：各策略平均收益")
    print(f"{'='*80}")
    print(f"\n  {'策略':>12} {'BTC':>10} {'ETH':>10} {'SOL':>10} {'UNI':>10} {'平均':>10}")
    print(f"  {'-'*65}")

    for sname in [s[0] for s in strategies] + ["买入持有"]:
        rets = all_results[sname]
        avg = np.mean(rets) if rets else 0
        line = f"  {sname:>12}"
        for r in rets:
            line += f" {r:>+9.2f}%"
        line += f" {avg:>+9.2f}%"
        print(line)

    if all_results["原版"] and all_results["优化版v1"]:
        print(f"\n  优化效果（原版 -> 优化版v1）:")
        print(f"    平均收益: {np.mean(all_results['原版']):+.2f}% -> {np.mean(all_results['优化版v1']):+.2f}%")


if __name__ == "__main__":
    main()
