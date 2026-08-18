"""增强版MA200牛熊经验法则 v2 回测（分层做空+斐波那契止盈+小币熊市全空仓）"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import json

from backtest.engine import BacktestEngine
from backtest.strategy import (
    LeastResistanceStrategy,
    MA200TrendFollowingStrategy,
    EnhancedMA200Strategy,
    MovingAverageStrategy,
)


def load_local_data(symbol):
    """加载本地缓存数据"""
    filepath = f"data/historical/{symbol}_1D_730d.json"
    with open(filepath) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


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
        import traceback
        traceback.print_exc()
        return None


def main():
    print("=" * 90)
    print("  增强版MA200牛熊经验法则 v2 — 分层做空 + 斐波那契止盈 + 小币熊市全空仓")
    print("=" * 90)
    print("""
  新法则：
  1. BTC跌破MA200 → 3成空仓；MA200的5日斜率为负 → 加仓至5成
  2. 斐波那契分阶段止盈(23.6%/38.2%/50%/61.8%)，每档减仓25%
  3. 小币熊市完全禁止开仓（不做多也不做空），仅BTC+自身双牛才做多
  4. 价格跌至周线MA200附近 → 分仓抄底（越跌越买，最大8成）
""")

    symbols = [("BTC", "BTC"), ("ETH", "ETH"), ("SOL", "SOL"), ("UNI", "UNI")]

    all_results = {}
    btc_prices = None

    for symbol, name in symbols:
        print(f"\n{'='*90}")
        print(f"  {name}")
        print(f"{'='*90}")

        prices = load_local_data(symbol)
        if prices.empty:
            print(f"  数据获取失败")
            continue

        if symbol == "BTC":
            btc_prices = prices

        n = len(prices)
        bh = (prices["close"].iloc[-1] / prices["close"].iloc[0] - 1) * 100
        print(f"  数据: {n}天 ({prices.index[0].strftime('%Y-%m-%d')} ~ {prices.index[-1].strftime('%Y-%m-%d')})")
        print(f"  买入持有: {bh:+.2f}%")

        is_btc = symbol == "BTC"

        strategies = [
            ("经典MA200(5日斜率)", lambda: MA200TrendFollowingStrategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=210
            )),
            ("v2默认(3/5成+斐波那契)", lambda: EnhancedMA200Strategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=260,
                symbol=symbol, is_btc=is_btc, btc_prices=btc_prices,
                weekly_ma200_dip_buy=True,
                dip_buy_max_position=0.8, dip_buy_levels=4, dip_buy_step_pct=5.0,
                bear_short_level1_pct=0.3, bear_short_level2_pct=0.5,
                fib_take_profit=True,
                fib_levels=[0.236, 0.382, 0.5, 0.618],
                alt_bear_no_trade=True,
            )),
            ("v2无斐波那契止盈", lambda: EnhancedMA200Strategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=260,
                symbol=symbol, is_btc=is_btc, btc_prices=btc_prices,
                weekly_ma200_dip_buy=True,
                dip_buy_max_position=0.8, dip_buy_levels=4, dip_buy_step_pct=5.0,
                bear_short_level1_pct=0.3, bear_short_level2_pct=0.5,
                fib_take_profit=False,
                alt_bear_no_trade=True,
            )),
            ("v2无抄底", lambda: EnhancedMA200Strategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=260,
                symbol=symbol, is_btc=is_btc, btc_prices=btc_prices,
                weekly_ma200_dip_buy=False,
                bear_short_level1_pct=0.3, bear_short_level2_pct=0.5,
                fib_take_profit=True,
                fib_levels=[0.236, 0.382, 0.5, 0.618],
                alt_bear_no_trade=True,
            )),
            ("v2小币无BTC过滤", lambda: EnhancedMA200Strategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=260,
                symbol=symbol, is_btc=is_btc, btc_prices=None,
                weekly_ma200_dip_buy=True,
                dip_buy_max_position=0.8, dip_buy_levels=4, dip_buy_step_pct=5.0,
                bear_short_level1_pct=0.3, bear_short_level2_pct=0.5,
                fib_take_profit=True,
                fib_levels=[0.236, 0.382, 0.5, 0.618],
                alt_bear_no_trade=True,
            )),
            ("v2更激进空仓(5/7成)", lambda: EnhancedMA200Strategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=260,
                symbol=symbol, is_btc=is_btc, btc_prices=btc_prices,
                weekly_ma200_dip_buy=True,
                dip_buy_max_position=0.8, dip_buy_levels=4, dip_buy_step_pct=5.0,
                bear_short_level1_pct=0.5, bear_short_level2_pct=0.7,
                fib_take_profit=True,
                fib_levels=[0.236, 0.382, 0.5, 0.618],
                alt_bear_no_trade=True,
            )),
            ("v1增强版(对比)", lambda: MA200TrendFollowingStrategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=210
            ) if not is_btc else MA200TrendFollowingStrategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=210
            )),
            ("综合最优LR", lambda: LeastResistanceStrategy(
                warmup_periods=min(80, n-10), update_step=1,
                min_holding_bars=15, signal_confirm_bars=4,
                max_position=1.0, enable_trend_filter=True, bear_short_only=True,
            )),
            ("双均线20/200", lambda: MovingAverageStrategy(20, 200)),
        ]

        print(f"\n  {'策略':>22} {'收益%':>10} {'夏普':>8} {'回撤%':>8} {'交易':>6} {'持仓天':>8}")
        print(f"  {'-'*80}")

        for sname, strat_fn in strategies:
            strategy = strat_fn()
            r = run_bt(prices, strategy, sname)
            if r:
                all_results.setdefault(sname, []).append(r)
                print(f"  {r['name']:>22} {r['return']:>+9.2f}% {r['sharpe']:>8.3f} "
                      f"{r['drawdown']:>7.2f}% {r['trades']:>6d} {r['avg_holding']:>7.1f}天")

                if "strategy_stats" in r:
                    ss = r["strategy_stats"]
                    total = sum(ss.get(k, 0) for k in [
                        "bull_days", "bear_short_l1_days", "bear_short_l2_days",
                        "bear_flat_days", "sideways_days", "dip_buy_days"
                    ])
                    if total > 0:
                        parts = []
                        if ss.get("bull_days", 0) > 0:
                            parts.append(f"牛{ss['bull_days']}({ss['bull_days']/total*100:.0f}%)")
                        if ss.get("bear_short_l1_days", 0) > 0:
                            parts.append(f"空3成{ss['bear_short_l1_days']}({ss['bear_short_l1_days']/total*100:.0f}%)")
                        if ss.get("bear_short_l2_days", 0) > 0:
                            parts.append(f"空5成{ss['bear_short_l2_days']}({ss['bear_short_l2_days']/total*100:.0f}%)")
                        if ss.get("dip_buy_days", 0) > 0:
                            parts.append(f"抄底{ss['dip_buy_days']}({ss['dip_buy_days']/total*100:.0f}%)")
                        if ss.get("fib_tp_days", 0) > 0:
                            parts.append(f"斐波止盈{ss['fib_tp_days']}天")
                        if ss.get("bear_flat_days", 0) > 0:
                            parts.append(f"熊空仓{ss['bear_flat_days']}({ss['bear_flat_days']/total*100:.0f}%)")
                        if ss.get("sideways_days", 0) > 0:
                            parts.append(f"震{ss['sideways_days']}({ss['sideways_days']/total*100:.0f}%)")
                        parts.append(f"切换{ss.get('trend_switches', 0)}次")
                        print(f"    " + " ".join(parts))

        print(f"  {'买入持有':>22} {bh:>+9.2f}%")
        all_results.setdefault("买入持有", []).append({"return": bh, "name": "买入持有"})

    print(f"\n\n{'='*90}")
    print(f"  汇总：各策略平均收益")
    print(f"{'='*90}")

    print(f"\n  {'策略':>22} {'BTC':>10} {'ETH':>10} {'SOL':>10} {'UNI':>10} {'平均':>10} {'夏普':>8} {'回撤%':>8} {'交易':>6}")
    print(f"  {'-'*103}")

    strat_names = [
        "经典MA200(5日斜率)",
        "v2默认(3/5成+斐波那契)",
        "v2无斐波那契止盈",
        "v2无抄底",
        "v2小币无BTC过滤",
        "v2更激进空仓(5/7成)",
        "综合最优LR",
        "双均线20/200",
        "买入持有",
    ]

    for sname in strat_names:
        rets = all_results.get(sname, [])
        if not rets:
            continue

        if sname == "买入持有":
            avg_ret = np.mean([r["return"] for r in rets])
            vals = [r["return"] for r in rets]
            while len(vals) < 4:
                vals.append(0)
            print(f"  {sname:>22} {vals[0]:>+9.2f}% {vals[1]:>+9.2f}% "
                  f"{vals[2]:>+9.2f}% {vals[3]:>+9.2f}% {avg_ret:>+9.2f}%")
            continue

        avg_ret = np.mean([r["return"] for r in rets])
        avg_sharpe = np.mean([r["sharpe"] for r in rets])
        avg_dd = np.mean([r["drawdown"] for r in rets])
        avg_trades = np.mean([r["trades"] for r in rets])

        vals = [r["return"] for r in rets]
        while len(vals) < 4:
            vals.append(0)

        print(f"  {sname:>22} {vals[0]:>+9.2f}% {vals[1]:>+9.2f}% {vals[2]:>+9.2f}% {vals[3]:>+9.2f}% "
              f"{avg_ret:>+9.2f}% {avg_sharpe:>8.3f} {avg_dd:>7.2f}% {avg_trades:>6.0f}")

    print(f"\n\n{'='*90}")
    print(f"  关键结论")
    print(f"{'='*90}")
    print(f"""
  v2新逻辑效果分析：
  1. BTC分层做空(3成→5成)：既保留做空收益，又降低初期入场风险
  2. 斐波那契分阶段止盈：在下跌趋势中锁定利润，避免反弹回吐
  3. 小币熊市完全空仓：彻底避免小币熊市做多做空双杀
  4. 周线MA200抄底：熊市末期左侧布局，捕捉大底机会
""")


if __name__ == "__main__":
    main()
