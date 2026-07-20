"""全策略版本统一回测对比 — 确定最终基线

对比12-三屏趋势系统中所有可回测的规则策略版本，
在9年历史数据（BTC/ETH/SOL/UNI）上进行统一对比，
确定EnhancedMA200Strategy v2是否可作为最终基线。

对比策略清单：
1. BuyAndHoldStrategy      — 买入持有基准
2. MovingAverageStrategy   — 双均线20/200基准
3. MA200TrendFollowingStrategy — 经典MA200牛熊法则
4. EnhancedMA200Strategy   — v2增强版MA200（候选基线）
5. LeastResistanceStrategy — 最小阻力方向策略
6. AdaptiveLeastResistanceStrategy — 自适应最小阻力策略
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import json
import time

from backtest.engine import BacktestEngine
from backtest.strategy import (
    BuyAndHoldStrategy,
    MovingAverageStrategy,
    MA200TrendFollowingStrategy,
    EnhancedMA200Strategy,
    LeastResistanceStrategy,
    AdaptiveLeastResistanceStrategy,
)


def load_local_data(symbol):
    """加载本地9年缓存数据"""
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
    """运行单个策略回测"""
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    try:
        signals = strategy.generate_signals(prices)
        result = engine.run(prices["close"], signals)
        m = result["metrics"]
        trades = result["trades"]
        n_trades = len(trades) if not trades.empty else 0
        avg_hold = trades["holding_bars"].mean() if n_trades > 0 else 0

        # 计算额外指标
        equity = result.get("equity_curve")
        max_dd_duration = 0
        if equity is not None and len(equity) > 0:
            peak = equity.cummax()
            dd = (equity - peak) / peak
            in_dd = dd < 0
            # 最长回撤持续期
            max_dd_duration = 0
            current_dd = 0
            for v in in_dd:
                if v:
                    current_dd += 1
                    max_dd_duration = max(max_dd_duration, current_dd)
                else:
                    current_dd = 0

        return {
            "name": name,
            "return": m["total_return_pct"],
            "sharpe": m["sharpe_ratio"],
            "drawdown": m["max_drawdown_pct"],
            "max_dd_duration": max_dd_duration,
            "trades": n_trades,
            "avg_holding": avg_hold,
            "win_rate": m.get("win_rate", 0),
        }
    except Exception as e:
        print(f"  [ERROR] {name}: {e}")
        return None


def main():
    start_time = time.time()

    print("=" * 100)
    print("  全策略版本统一回测对比 — 确定最终基线")
    print("=" * 100)
    print("""
  对比策略：
  1. BuyAndHoldStrategy         — 买入持有基准
  2. MovingAverageStrategy      — 双均线20/200
  3. MA200TrendFollowingStrategy — 经典MA200牛熊法则
  4. EnhancedMA200Strategy v2   — 增强版MA200（候选基线）
  5. LeastResistanceStrategy    — 最小阻力方向
  6. AdaptiveLeastResistanceStrategy — 自适应最小阻力

  数据：9年历史数据（BTC/ETH/SOL/UNI）
  初始资金：$10,000
  手续费：0.1% + 滑点0.1%
""")

    symbols = [("BTC", "BTC"), ("ETH", "ETH"), ("SOL", "SOL"), ("UNI", "UNI")]

    all_results = {}
    btc_prices = None

    for symbol, name in symbols:
        print(f"\n{'='*100}")
        print(f"  {name}")
        print(f"{'='*100}")

        prices = load_local_data(symbol)
        if prices.empty:
            print(f"  数据加载失败")
            continue

        if symbol == "BTC":
            btc_prices = prices

        n = len(prices)
        bh = (prices["close"].iloc[-1] / prices["close"].iloc[0] - 1) * 100
        print(f"  数据: {n}天 ({prices.index[0].strftime('%Y-%m-%d')} ~ {prices.index[-1].strftime('%Y-%m-%d')})")
        print(f"  买入持有: {bh:+.2f}%")

        is_btc = symbol == "BTC"

        # 构建策略列表
        strategies = [
            ("买入持有", lambda: BuyAndHoldStrategy()),
            ("双均线20/200", lambda: MovingAverageStrategy(20, 200)),
            ("经典MA200", lambda: MA200TrendFollowingStrategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=210
            )),
            ("v2增强版MA200", lambda: EnhancedMA200Strategy(
                ma_period=200, slope_period=5, max_position=1.0, warmup_periods=260,
                symbol=symbol, is_btc=is_btc, btc_prices=btc_prices,
                weekly_ma200_dip_buy=True,
                dip_buy_max_position=0.8, dip_buy_levels=4, dip_buy_step_pct=5.0,
                bear_short_level1_pct=0.3, bear_short_level2_pct=0.5,
                fib_take_profit=True,
                fib_levels=[0.236, 0.382, 0.5, 0.618],
                alt_bear_no_trade=True,
            )),
            ("最小阻力LR", lambda: LeastResistanceStrategy(
                warmup_periods=min(80, n-10), update_step=1,
                min_holding_bars=15, signal_confirm_bars=4,
                max_position=1.0, enable_trend_filter=True, bear_short_only=True,
            )),
            ("自适应最小阻力", lambda: AdaptiveLeastResistanceStrategy(
                warmup_periods=min(80, n-10), update_step=1,
                enable_trend_filter=True,
            )),
        ]

        print(f"\n  {'策略':>16} {'收益%':>10} {'夏普':>8} {'回撤%':>8} {'回撤持续':>8} {'交易':>6} {'持仓天':>8} {'胜率%':>7}")
        print(f"  {'-'*90}")

        for sname, strat_fn in strategies:
            strategy = strat_fn()
            r = run_bt(prices, strategy, sname)
            if r:
                all_results.setdefault(sname, []).append(r)
                print(f"  {r['name']:>16} {r['return']:>+9.2f}% {r['sharpe']:>8.3f} "
                      f"{r['drawdown']:>7.2f}% {r['max_dd_duration']:>7d}天 "
                      f"{r['trades']:>6d} {r['avg_holding']:>7.1f}天 {r['win_rate']:>6.1f}%")

    # 汇总对比
    print(f"\n\n{'='*100}")
    print(f"  汇总：各策略9年平均表现对比")
    print(f"{'='*100}")

    print(f"\n  {'策略':>16} {'BTC':>10} {'ETH':>10} {'SOL':>10} {'UNI':>10} {'平均':>10} {'夏普':>8} {'回撤%':>8} {'回撤持续':>8} {'交易':>6} {'胜率%':>7}")
    print(f"  {'-'*115}")

    strat_names = [
        "买入持有", "双均线20/200", "经典MA200", "v2增强版MA200",
        "最小阻力LR", "自适应最小阻力",
    ]

    summary_stats = {}

    for sname in strat_names:
        rets = all_results.get(sname, [])
        if not rets:
            continue

        avg_ret = np.mean([r["return"] for r in rets])
        avg_sharpe = np.mean([r["sharpe"] for r in rets])
        avg_dd = np.mean([r["drawdown"] for r in rets])
        avg_dd_dur = np.mean([r["max_dd_duration"] for r in rets])
        avg_trades = np.mean([r["trades"] for r in rets])
        avg_win = np.mean([r["win_rate"] for r in rets])

        vals = [r["return"] for r in rets]
        while len(vals) < 4:
            vals.append(0)

        summary_stats[sname] = {
            "avg_return": avg_ret,
            "avg_sharpe": avg_sharpe,
            "avg_drawdown": avg_dd,
            "avg_dd_duration": avg_dd_dur,
            "avg_trades": avg_trades,
            "avg_win_rate": avg_win,
        }

        print(f"  {sname:>16} {vals[0]:>+9.2f}% {vals[1]:>+9.2f}% {vals[2]:>+9.2f}% {vals[3]:>+9.2f}% "
              f"{avg_ret:>+9.2f}% {avg_sharpe:>8.3f} {avg_dd:>7.2f}% {avg_dd_dur:>7.0f}天 {avg_trades:>6.0f} {avg_win:>6.1f}%")

    # 综合排名
    print(f"\n\n{'='*100}")
    print(f"  综合排名（按平均收益排序）")
    print(f"{'='*100}")

    ranked = sorted(summary_stats.items(), key=lambda x: -x[1]["avg_return"])

    print(f"\n  {'排名':>4} {'策略':>16} {'平均收益':>10} {'夏普':>8} {'回撤%':>8} {'回撤持续':>8} {'胜率%':>7} {'综合评价':>10}")
    print(f"  {'-'*90}")

    for rank, (sname, stats) in enumerate(ranked, 1):
        # 综合评分：收益权重40% + 夏普权重30% + 回撤权重20% + 胜率权重10%
        # 归一化处理
        max_ret = max(s["avg_return"] for s in summary_stats.values())
        min_dd = min(s["avg_drawdown"] for s in summary_stats.values())

        ret_score = stats["avg_return"] / max(max_ret, 1) * 40 if max_ret > 0 else 0
        sharpe_score = max(stats["avg_sharpe"], 0) / max(
            max(s["avg_sharpe"] for s in summary_stats.values()), 0.1) * 30
        dd_score = (100 - stats["avg_drawdown"]) / 100 * 20
        win_score = stats["avg_win_rate"] / 100 * 10
        total_score = ret_score + sharpe_score + dd_score + win_score

        evaluation = ""
        if rank == 1:
            evaluation = "⭐最优"
        elif rank == 2:
            evaluation = "优秀"
        elif rank == 3:
            evaluation = "良好"
        elif stats["avg_return"] > 0:
            evaluation = "可用"
        else:
            evaluation = "不佳"

        print(f"  {rank:>4} {sname:>16} {stats['avg_return']:>+9.2f}% {stats['avg_sharpe']:>8.3f} "
              f"{stats['avg_drawdown']:>7.2f}% {stats['avg_dd_duration']:>7.0f}天 "
              f"{stats['avg_win_rate']:>6.1f}% {evaluation:>10}")

    # v2基线评估
    print(f"\n\n{'='*100}")
    print(f"  v2增强版MA200 — 最终基线评估")
    print(f"{'='*100}")

    v2_stats = summary_stats.get("v2增强版MA200")
    classic_stats = summary_stats.get("经典MA200")
    lr_stats = summary_stats.get("最小阻力LR")

    if v2_stats:
        print(f"""
  v2增强版MA200核心指标：
  - 平均收益:  {v2_stats['avg_return']:+.2f}%
  - 夏普比率:  {v2_stats['avg_sharpe']:.3f}
  - 最大回撤:  {v2_stats['avg_drawdown']:.2f}%
  - 回撤持续:  {v2_stats['avg_dd_duration']:.0f}天
  - 平均交易:  {v2_stats['avg_trades']:.0f}次
  - 胜率:      {v2_stats['avg_win_rate']:.1f}%
""")

        if classic_stats:
            print(f"  vs 经典MA200:")
            print(f"    收益提升:  {v2_stats['avg_return'] - classic_stats['avg_return']:+.2f}pp")
            print(f"    夏普提升:  {v2_stats['avg_sharpe'] - classic_stats['avg_sharpe']:+.3f}")
            print(f"    回撤改善:  {v2_stats['avg_drawdown'] - classic_stats['avg_drawdown']:+.2f}pp")

        if lr_stats:
            print(f"  vs 最小阻力LR:")
            print(f"    收益提升:  {v2_stats['avg_return'] - lr_stats['avg_return']:+.2f}pp")
            print(f"    夏普提升:  {v2_stats['avg_sharpe'] - lr_stats['avg_sharpe']:+.3f}")
            print(f"    回撤改善:  {v2_stats['avg_drawdown'] - lr_stats['avg_drawdown']:+.2f}pp")

        # 基线评估结论
        is_best_return = ranked[0][0] == "v2增强版MA200"
        is_best_sharpe = v2_stats["avg_sharpe"] == max(s["avg_sharpe"] for s in summary_stats.values())
        is_best_dd = v2_stats["avg_drawdown"] == min(s["avg_drawdown"] for s in summary_stats.values())

        print(f"\n  基线评估结论:")
        print(f"    收益排名:   {'第1名 ✅' if is_best_return else '非第1名 ❌'}")
        print(f"    夏普最高:   {'是 ✅' if is_best_sharpe else '否 ❌'}")
        print(f"    回撤最低:   {'是 ✅' if is_best_dd else '否 ❌'}")

        if is_best_return and (is_best_sharpe or is_best_dd):
            print(f"\n  ✅ 结论：v2增强版MA200在9年回测中表现最优，建议作为最终基线策略")
        elif is_best_return:
            print(f"\n  ✅ 结论：v2增强版MA200收益最高，建议作为最终基线策略（夏普/回撤可进一步优化）")
        else:
            print(f"\n  ⚠️ 结论：v2增强版MA200未全面领先，需进一步分析是否作为基线")

    elapsed = time.time() - start_time
    print(f"\n  回测耗时: {elapsed:.1f}秒")


if __name__ == "__main__":
    main()
