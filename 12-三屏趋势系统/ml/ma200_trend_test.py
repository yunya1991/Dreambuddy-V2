"""MA200牛熊经验法则策略对比测试

对比策略：
1. MA200趋势策略（纯均线牛熊切换）
2. 综合最优LR策略（hold=15, confirm=4）
3. 买入持有
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
    MA200TrendFollowingStrategy,
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


def run_bt(prices, strategy, name):
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

        if hasattr(strategy, "get_stats"):
            stats["strategy_stats"] = strategy.get_stats()

        return stats
    except Exception as e:
        print(f"  [ERROR] {name}: {e}")
        return None


def main():
    print("=" * 90)
    print("  MA200牛熊经验法则 vs 综合最优LR vs 买入持有")
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
        bh = (prices["close"].iloc[-1] / prices["close"].iloc[0] - 1) * 100
        print(f"  数据: {n}天, 买入持有: {bh:+.2f}%")

        strategies = [
            ("MA200牛熊", lambda: MA200TrendFollowingStrategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=210
            )),
            ("MA200(3日斜率)", lambda: MA200TrendFollowingStrategy(
                ma_period=200, slope_period=3, max_position=1.0, warmup_periods=210
            )),
            ("MA200(10日斜率)", lambda: MA200TrendFollowingStrategy(
                ma_period=200, slope_period=10, max_position=1.0, warmup_periods=210
            )),
            ("MA150牛熊", lambda: MA200TrendFollowingStrategy(
                ma_period=150, slope_period=5, max_position=1.0, warmup_periods=160
            )),
            ("MA250牛熊", lambda: MA200TrendFollowingStrategy(
                ma_period=250, slope_period=5, max_position=1.0, warmup_periods=260
            )),
            ("综合最优LR", lambda: LeastResistanceStrategy(
                warmup_periods=min(80, n-10), update_step=1,
                min_holding_bars=15, signal_confirm_bars=4,
                max_position=1.0, enable_trend_filter=True, bear_short_only=True,
            )),
            ("双均线20/200", lambda: MovingAverageStrategy(20, 200)),
        ]

        print(f"\n  {'策略':>14} {'收益%':>10} {'夏普':>8} {'回撤%':>8} {'交易':>6} {'持仓天':>8}")
        print(f"  {'-'*70}")

        for sname, strat_fn in strategies:
            strategy = strat_fn()
            r = run_bt(prices, strategy, sname)
            if r:
                all_results.setdefault(sname, []).append(r)
                print(f"  {r['name']:>14} {r['return']:>+9.2f}% {r['sharpe']:>8.3f} "
                      f"{r['drawdown']:>7.2f}% {r['trades']:>6d} {r['avg_holding']:>7.1f}天")

                if "strategy_stats" in r:
                    ss = r["strategy_stats"]
                    if "bull_days" in ss:
                        total = ss["bull_days"] + ss["bear_days"] + ss["sideways_days"]
                        if total > 0:
                            print(f"    牛{ss['bull_days']}({ss['bull_days']/total*100:.0f}%) "
                                  f"熊{ss['bear_days']}({ss['bear_days']/total*100:.0f}%) "
                                  f"震{ss['sideways_days']}({ss['sideways_days']/total*100:.0f}%) "
                                  f"切换{ss['trend_switches']}次")

        print(f"  {'买入持有':>14} {bh:>+9.2f}%")
        all_results.setdefault("买入持有", []).append({"return": bh, "name": "买入持有"})

    # 汇总
    print(f"\n\n{'='*90}")
    print(f"  汇总：各策略平均收益")
    print(f"{'='*90}")

    print(f"\n  {'策略':>14} {'BTC':>10} {'ETH':>10} {'SOL':>10} {'UNI':>10} {'平均':>10} {'夏普':>8} {'回撤%':>8} {'交易':>6}")
    print(f"  {'-'*95}")

    for sname in ["MA200牛熊", "MA200(3日斜率)", "MA200(10日斜率)", "MA150牛熊", "MA250牛熊", "综合最优LR", "双均线20/200", "买入持有"]:
        rets = all_results.get(sname, [])
        if not rets:
            continue

        if sname == "买入持有":
            avg_ret = np.mean([r["return"] for r in rets])
            vals = [r["return"] for r in rets]
            while len(vals) < 4:
                vals.append(0)
            print(f"  {sname:>14} {vals[0]:>+9.2f}% {vals[1]:>+9.2f}% "
                  f"{vals[2]:>+9.2f}% {vals[3]:>+9.2f}% {avg_ret:>+9.2f}%")
            continue

        avg_ret = np.mean([r["return"] for r in rets])
        avg_sharpe = np.mean([r["sharpe"] for r in rets])
        avg_dd = np.mean([r["drawdown"] for r in rets])
        avg_trades = np.mean([r["trades"] for r in rets])

        vals = [r["return"] for r in rets]
        while len(vals) < 4:
            vals.append(0)

        print(f"  {sname:>14} {vals[0]:>+9.2f}% {vals[1]:>+9.2f}% {vals[2]:>+9.2f}% {vals[3]:>+9.2f}% "
              f"{avg_ret:>+9.2f}% {avg_sharpe:>8.3f} {avg_dd:>7.2f}% {avg_trades:>6.0f}")


if __name__ == "__main__":
    main()
