"""最小阻力策略交易行为深度分析

追踪每笔交易详情，分析亏损根因：
1. 交易频率与持仓时间
2. 多空比例与胜率
3. 盈亏比与手续费占比
4. 信号方向与实际价格走势
5. 不同市场环境下的表现
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
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


def analyze_symbol(name, prices, strategy):
    print(f"\n{'='*70}")
    print(f"  {name} 最小阻力策略交易行为分析")
    print(f"{'='*70}")

    n = len(prices)
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    signals = strategy.generate_signals(prices)
    result = engine.run(prices["close"], signals)

    trades = result["trades"]
    equity = result["equity_curve"]
    position = result["position"]
    m = result["metrics"]

    # 1. 整体绩效
    print(f"\n--- 1. 整体绩效 ---")
    print(f"  数据天数: {n}")
    print(f"  总收益: {m['total_return_pct']:.2f}%")
    print(f"  夏普比率: {m['sharpe_ratio']:.3f}")
    print(f"  最大回撤: {m['max_drawdown_pct']:.2f}%")
    print(f"  总交易次数: {m['total_trades']}")

    if trades.empty:
        print("  无交易记录")
        return

    # 2. 交易频率分析
    print(f"\n--- 2. 交易频率分析 ---")
    avg_holding = trades["holding_bars"].mean()
    median_holding = trades["holding_bars"].median()
    total_holding = trades["holding_bars"].sum()
    market_time_pct = total_holding / n * 100

    print(f"  总交易次数: {len(trades)}")
    print(f"  平均持仓天数: {avg_holding:.1f} 天")
    print(f"  中位持仓天数: {median_holding:.1f} 天")
    print(f"  最长持仓: {trades['holding_bars'].max()} 天")
    print(f"  最短持仓: {trades['holding_bars'].min()} 天")
    print(f"  总持仓天数: {total_holding} 天")
    print(f"  市场参与率: {market_time_pct:.1f}%")

    # 3. 多空分析
    print(f"\n--- 3. 多空方向分析 ---")
    long_trades = trades[trades["side"] == "long"]
    short_trades = trades[trades["side"] == "short"]

    long_count = len(long_trades)
    short_count = len(short_trades)
    long_pct = long_count / len(trades) * 100
    short_pct = short_count / len(trades) * 100

    long_pnl = long_trades["pnl_pct"].sum() if long_count > 0 else 0
    short_pnl = short_trades["pnl_pct"].sum() if short_count > 0 else 0

    long_win = (long_trades["pnl_pct"] > 0).sum() if long_count > 0 else 0
    short_win = (short_trades["pnl_pct"] > 0).sum() if short_count > 0 else 0
    long_winrate = long_win / max(long_count, 1) * 100
    short_winrate = short_win / max(short_count, 1) * 100

    print(f"  做多交易: {long_count} 次 ({long_pct:.1f}%) | 盈利 {long_win} 次 | 胜率 {long_winrate:.1f}% | 总盈亏 {long_pnl:+.2f}%")
    print(f"  做空交易: {short_count} 次 ({short_pct:.1f}%) | 盈利 {short_win} 次 | 胜率 {short_winrate:.1f}% | 总盈亏 {short_pnl:+.2f}%")

    # 4. 盈亏分析
    print(f"\n--- 4. 盈亏分布分析 ---")
    wins = trades[trades["pnl_pct"] > 0]
    losses = trades[trades["pnl_pct"] <= 0]

    avg_win = wins["pnl_pct"].mean() if len(wins) > 0 else 0
    avg_loss = losses["pnl_pct"].mean() if len(losses) > 0 else 0
    total_win = wins["pnl_pct"].sum() if len(wins) > 0 else 0
    total_loss = losses["pnl_pct"].sum() if len(losses) > 0 else 0
    profit_factor = abs(total_win / total_loss) if total_loss != 0 else float('inf')
    overall_winrate = len(wins) / len(trades) * 100

    print(f"  盈利交易: {len(wins)} 次 ({overall_winrate:.1f}%)")
    print(f"  亏损交易: {len(losses)} 次 ({100-overall_winrate:.1f}%)")
    print(f"  平均盈利: +{avg_win:.2f}%")
    print(f"  平均亏损: {avg_loss:.2f}%")
    print(f"  盈亏比: {abs(avg_win/avg_loss) if avg_loss != 0 else float('inf'):.2f}")
    print(f"  总盈利: +{total_win:.2f}%")
    print(f"  总亏损: {total_loss:.2f}%")
    print(f"  利润因子: {profit_factor:.2f}")

    # 5. 手续费影响
    print(f"\n--- 5. 手续费影响分析 ---")
    position_changes = position.diff().abs()
    position_changes.iloc[0] = abs(position.iloc[0])
    total_turnover = position_changes.sum()
    total_cost = total_turnover * 0.002  # commission + slippage
    cost_pct = total_cost * 100

    bh_return = (prices["close"].iloc[-1] / prices["close"].iloc[0] - 1) * 100
    gross_return = m["total_return_pct"] + cost_pct

    print(f"  总换手率: {total_turnover:.2f} (每1.0=满仓换一次)")
    print(f"  总手续费+滑点: {cost_pct:.2f}%")
    print(f"  策略净收益: {m['total_return_pct']:.2f}%")
    print(f"  策略毛收益(加回手续费): {gross_return:.2f}%")
    print(f"  手续费占毛收益比: {cost_pct/max(abs(gross_return), 0.01)*100:.1f}%")
    print(f"  买入持有收益: {bh_return:.2f}%")

    # 6. 仓位变动频率
    print(f"\n--- 6. 仓位变动频率 ---")
    pos_changes_count = (position_changes > 0.01).sum()
    large_changes = (position_changes > 0.1).sum()
    sign_changes = 0
    prev_sign = 0
    for p in position:
        curr_sign = 1 if p > 0.01 else (-1 if p < -0.01 else 0)
        if curr_sign != 0 and prev_sign != 0 and curr_sign != prev_sign:
            sign_changes += 1
        if curr_sign != 0:
            prev_sign = curr_sign

    print(f"  仓位变动次数(>1%): {pos_changes_count}")
    print(f"  大幅调仓次数(>10%): {large_changes}")
    print(f"  方向反转次数(多↔空): {sign_changes}")

    # 7. 最大单笔盈亏
    print(f"\n--- 7. 极端交易 ---")
    if len(trades) > 0:
        best_trade = trades.loc[trades["pnl_pct"].idxmax()]
        worst_trade = trades.loc[trades["pnl_pct"].idxmin()]
        print(f"  最佳交易: {best_trade['pnl_pct']:+.2f}% | {best_trade['side']} | 持仓{best_trade['holding_bars']}天")
        print(f"  最差交易: {worst_trade['pnl_pct']:+.2f}% | {worst_trade['side']} | 持仓{worst_trade['holding_bars']}天")

    # 8. 前20笔交易详情
    print(f"\n--- 8. 前20笔交易详情 ---")
    print(f"  {'序号':>4} {'方向':>6} {'入场价':>12} {'出场价':>12} {'盈亏%':>10} {'持仓天数':>8}")
    print(f"  {'-'*60}")
    for i, (_, t) in enumerate(trades.head(20).iterrows()):
        side_str = "做多" if t["side"] == "long" else "做空"
        print(f"  {i+1:>4} {side_str:>6} {t['entry_price']:>12.2f} {t['exit_price']:>12.2f} "
              f"{t['pnl_pct']:>+10.2f} {t['holding_bars']:>8d}")

    # 9. 信号统计
    print(f"\n--- 9. 策略信号统计 ---")
    stats = strategy.get_stats()
    total_bars = stats.get("total_bars", 0)
    if total_bars > 0:
        print(f"  总信号bar数: {total_bars}")
        print(f"  MUST_ENTER信号: {stats.get('must_enter', 0)} ({stats.get('must_enter', 0)/total_bars*100:.1f}%)")
        print(f"  TIMING信号: {stats.get('timing', 0)} ({stats.get('timing', 0)/total_bars*100:.1f}%)")
        print(f"  WAIT信号: {stats.get('wait', 0)} ({stats.get('wait', 0)/total_bars*100:.1f}%)")
        print(f"  累积阶段: {stats.get('accumulation', 0)}")
        print(f"  突破在即: {stats.get('breakthrough_imminent', 0)}")
        print(f"  突破确认: {stats.get('breakthrough_confirmed', 0)}")
        print(f"  延续模式: {stats.get('continuation', 0)}")
        print(f"  后期延续: {stats.get('late_continuation', 0)}")
        print(f"  减弱模式: {stats.get('weakening', 0)}")

    # 10. 仓位时间序列分析
    print(f"\n--- 10. 仓位分布 ---")
    pos_nonzero = position[position.abs() > 0.01]
    if len(pos_nonzero) > 0:
        pos_long = (pos_nonzero > 0.01).sum()
        pos_short = (pos_nonzero < -0.01).sum()
        pos_flat = (position.abs() <= 0.01).sum()
        avg_pos_size = pos_nonzero.abs().mean()
        max_pos_size = pos_nonzero.abs().max()

        print(f"  持仓时间: {len(pos_nonzero)}/{n} 天 ({len(pos_nonzero)/n*100:.1f}%)")
        print(f"  空仓时间: {pos_flat}/{n} 天 ({pos_flat/n*100:.1f}%)")
        print(f"  做多时间: {pos_long} 天 ({pos_long/n*100:.1f}%)")
        print(f"  做空时间: {pos_short} 天 ({pos_short/n*100:.1f}%)")
        print(f"  平均仓位: {avg_pos_size:.3f}")
        print(f"  最大仓位: {max_pos_size:.3f}")

    return {
        "symbol": name,
        "n_days": n,
        "total_return": m["total_return_pct"],
        "total_trades": len(trades),
        "avg_holding": avg_holding,
        "market_time_pct": market_time_pct,
        "long_count": long_count,
        "short_count": short_count,
        "long_winrate": long_winrate,
        "short_winrate": short_winrate,
        "overall_winrate": overall_winrate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "total_cost_pct": cost_pct,
        "gross_return": gross_return,
        "bh_return": bh_return,
        "sign_changes": sign_changes,
    }


def main():
    print("=" * 70)
    print("  最小阻力策略交易行为深度分析")
    print("=" * 70)

    symbols = [("BTC-USDT", "BTC"), ("ETH-USDT", "ETH"), ("SOL-USDT", "SOL"), ("UNI-USDT", "UNI")]

    all_results = []
    for inst_id, name in symbols:
        prices = fetch_real_data(inst_id, days=730)
        if prices.empty:
            print(f"{name} 数据获取失败")
            continue

        n = len(prices)
        strategy = LeastResistanceStrategy(warmup_periods=min(80, n-10), update_step=1)
        result = analyze_symbol(name, prices, strategy)
        if result:
            all_results.append(result)

    # 汇总分析
    print(f"\n\n{'='*70}")
    print(f"  汇总分析")
    print(f"{'='*70}")

    if not all_results:
        return

    print(f"\n{'标的':>6} {'收益%':>8} {'交易数':>6} {'持仓天':>6} {'参与率':>6} {'多头':>6} {'空头':>6} {'胜率':>6} {'盈亏比':>6} {'手续费':>6} {'毛收益':>8}")
    print("-" * 85)

    for r in all_results:
        pf = r["profit_factor"] if r["profit_factor"] != float('inf') else 99.99
        print(f"{r['symbol']:>6} {r['total_return']:>+8.2f} {r['total_trades']:>6d} "
              f"{r['avg_holding']:>6.1f} {r['market_time_pct']:>5.1f}% "
              f"{r['long_count']:>6d} {r['short_count']:>6d} "
              f"{r['overall_winrate']:>5.1f}% {pf:>6.2f} "
              f"{r['total_cost_pct']:>5.1f}% {r['gross_return']:>+8.2f}%")

    # 平均值
    avg_return = np.mean([r["total_return"] for r in all_results])
    avg_trades = np.mean([r["total_trades"] for r in all_results])
    avg_holding = np.mean([r["avg_holding"] for r in all_results])
    avg_market_time = np.mean([r["market_time_pct"] for r in all_results])
    avg_winrate = np.mean([r["overall_winrate"] for r in all_results])
    avg_cost = np.mean([r["total_cost_pct"] for r in all_results])
    avg_gross = np.mean([r["gross_return"] for r in all_results])
    avg_bh = np.mean([r["bh_return"] for r in all_results])

    print("-" * 85)
    print(f"{'平均':>6} {avg_return:>+8.2f} {avg_trades:>6.0f} {avg_holding:>6.1f} "
          f"{avg_market_time:>5.1f}% {'':>6} {'':>6} {avg_winrate:>5.1f}% {'':>6} "
          f"{avg_cost:>5.1f}% {avg_gross:>+8.2f}%")
    print(f"{'买入持有':>6} {avg_bh:>+8.2f}%")


if __name__ == "__main__":
    main()
