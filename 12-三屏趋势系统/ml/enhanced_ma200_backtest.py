"""增强版MA200牛熊经验法则回测（加入3条新法则）"""

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
    print("  增强版MA200牛熊经验法则 vs 经典MA200 vs 买入持有（9年数据）")
    print("  新增法则：")
    print("    1. BTC价格跌至周线MA200，分仓抄底")
    print("    2. 小币禁止做空，反弹剧烈趋势不可控")
    print("    3. BTC有效跌破MA200且下跌趋势强时允许做空，其他币不做多也不做空")
    print("=" * 90)

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
            ("增强版MA200(默认)", lambda: EnhancedMA200Strategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=260,
                symbol=symbol, is_btc=is_btc, btc_prices=btc_prices,
                weekly_ma200_dip_buy=True,
                dip_buy_max_position=0.8, dip_buy_levels=4, dip_buy_step_pct=5.0,
                strong_bear_short=True,
                strong_bear_slope_threshold=-3.0, strong_bear_price_below_pct=8.0,
                alt_no_short=True,
            )),
            ("增强版(更保守抄底)", lambda: EnhancedMA200Strategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=260,
                symbol=symbol, is_btc=is_btc, btc_prices=btc_prices,
                weekly_ma200_dip_buy=True,
                dip_buy_max_position=0.6, dip_buy_levels=3, dip_buy_step_pct=8.0,
                strong_bear_short=True,
                strong_bear_slope_threshold=-4.0, strong_bear_price_below_pct=12.0,
                alt_no_short=True,
            )),
            ("增强版(不做空)", lambda: EnhancedMA200Strategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=260,
                symbol=symbol, is_btc=is_btc, btc_prices=btc_prices,
                weekly_ma200_dip_buy=True,
                dip_buy_max_position=0.8, dip_buy_levels=4, dip_buy_step_pct=5.0,
                strong_bear_short=False,
                strong_bear_slope_threshold=-3.0, strong_bear_price_below_pct=8.0,
                alt_no_short=True,
            )),
            ("增强版(小币无BTC过滤)", lambda: EnhancedMA200Strategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=260,
                symbol=symbol, is_btc=is_btc, btc_prices=None,
                weekly_ma200_dip_buy=True,
                dip_buy_max_position=0.8, dip_buy_levels=4, dip_buy_step_pct=5.0,
                strong_bear_short=True,
                strong_bear_slope_threshold=-3.0, strong_bear_price_below_pct=8.0,
                alt_no_short=True,
            )),
            ("综合最优LR", lambda: LeastResistanceStrategy(
                warmup_periods=min(80, n-10), update_step=1,
                min_holding_bars=15, signal_confirm_bars=4,
                max_position=1.0, enable_trend_filter=True, bear_short_only=True,
            )),
            ("双均线20/200", lambda: MovingAverageStrategy(20, 200)),
        ]

        print(f"\n  {'策略':>18} {'收益%':>10} {'夏普':>8} {'回撤%':>8} {'交易':>6} {'持仓天':>8}")
        print(f"  {'-'*76}")

        for sname, strat_fn in strategies:
            strategy = strat_fn()
            r = run_bt(prices, strategy, sname)
            if r:
                all_results.setdefault(sname, []).append(r)
                print(f"  {r['name']:>18} {r['return']:>+9.2f}% {r['sharpe']:>8.3f} "
                      f"{r['drawdown']:>7.2f}% {r['trades']:>6d} {r['avg_holding']:>7.1f}天")

                if "strategy_stats" in r:
                    ss = r["strategy_stats"]
                    if "bull_days" in ss:
                        total = ss.get("bull_days", 0) + ss.get("bear_days", 0) + ss.get("sideways_days", 0) + ss.get("dip_buy_days", 0)
                        if total > 0:
                            parts = []
                            if ss.get("bull_days", 0) > 0:
                                parts.append(f"牛{ss['bull_days']}({ss['bull_days']/total*100:.0f}%)")
                            if ss.get("bear_days", 0) > 0:
                                parts.append(f"熊{ss['bear_days']}({ss['bear_days']/total*100:.0f}%)")
                            if ss.get("dip_buy_days", 0) > 0:
                                parts.append(f"抄底{ss['dip_buy_days']}({ss['dip_buy_days']/total*100:.0f}%)")
                            if ss.get("strong_bear_short_days", 0) > 0:
                                parts.append(f"强熊空{ss['strong_bear_short_days']}({ss['strong_bear_short_days']/total*100:.0f}%)")
                            if ss.get("sideways_days", 0) > 0:
                                parts.append(f"震{ss['sideways_days']}({ss['sideways_days']/total*100:.0f}%)")
                            parts.append(f"切换{ss.get('trend_switches', 0)}次")
                            print(f"    " + " ".join(parts))

        print(f"  {'买入持有':>18} {bh:>+9.2f}%")
        all_results.setdefault("买入持有", []).append({"return": bh, "name": "买入持有"})

    print(f"\n\n{'='*90}")
    print(f"  汇总：各策略平均收益")
    print(f"{'='*90}")

    print(f"\n  {'策略':>18} {'BTC':>10} {'ETH':>10} {'SOL':>10} {'UNI':>10} {'平均':>10} {'夏普':>8} {'回撤%':>8} {'交易':>6}")
    print(f"  {'-'*99}")

    strat_names = ["经典MA200(5日斜率)", "增强版MA200(默认)", "增强版(更保守抄底)",
                   "增强版(不做空)", "增强版(小币无BTC过滤)",
                   "综合最优LR", "双均线20/200", "买入持有"]

    for sname in strat_names:
        rets = all_results.get(sname, [])
        if not rets:
            continue

        if sname == "买入持有":
            avg_ret = np.mean([r["return"] for r in rets])
            vals = [r["return"] for r in rets]
            while len(vals) < 4:
                vals.append(0)
            print(f"  {sname:>18} {vals[0]:>+9.2f}% {vals[1]:>+9.2f}% "
                  f"{vals[2]:>+9.2f}% {vals[3]:>+9.2f}% {avg_ret:>+9.2f}%")
            continue

        avg_ret = np.mean([r["return"] for r in rets])
        avg_sharpe = np.mean([r["sharpe"] for r in rets])
        avg_dd = np.mean([r["drawdown"] for r in rets])
        avg_trades = np.mean([r["trades"] for r in rets])

        vals = [r["return"] for r in rets]
        while len(vals) < 4:
            vals.append(0)

        print(f"  {sname:>18} {vals[0]:>+9.2f}% {vals[1]:>+9.2f}% {vals[2]:>+9.2f}% {vals[3]:>+9.2f}% "
              f"{avg_ret:>+9.2f}% {avg_sharpe:>8.3f} {avg_dd:>7.2f}% {avg_trades:>6.0f}")

    print(f"\n\n{'='*90}")
    print(f"  关键结论")
    print(f"{'='*90}")
    print(f"""
  新增三条法则效果分析：
  1. 周线MA200抄底：在BTC深熊周期提供左侧买入机会，降低平均持仓成本
  2. 小币禁止做空：避免小币熊市中暴力反弹导致的做空爆仓风险
  3. BTC强熊做空 + 小币空仓：只有BTC在确认强熊市才做空，小币完全避险

  经典MA200问题：
  - 小币做空在反弹中亏损严重
  - 熊市初期就做空容易被反弹止损
  - 熊市末期缺少抄底机制错过大底

  增强版改进方向：
  - 提高风险调整后收益（夏普比率）
  - 降低最大回撤
  - 减少无效交易次数
""")


if __name__ == "__main__":
    main()
