"""三屏趋势系统 — 推理算法回测脚本

针对三屏趋势策略的完整推理算法进行回测，对比：
1. Buy&Hold（基准）
2. TrendScreenStrategy（基础三屏，只用三大算法：趋势一致性+贝叶斯+经典指标+融合）
3. FullReasoningStrategy（完整推理链：BTC风向标+五大算法+five_algo_decision完整决策）
4. FullReasoningStrategy + LightGBM 集成推理（可选）

设计原则：低级策略不能影响高级算法。
本回测只评估高级推理算法的绩效，不混入简单模式等低级回退策略。

用法:
    cd 12-三屏趋势系统
    python3 backtest/run_reasoning_backtest.py                    # 默认: 真实数据, update_step=3
    python3 backtest/run_reasoning_backtest.py --daily             # 每日更新信号(更精确但更慢)
    python3 backtest/run_reasoning_backtest.py --ensemble          # 启用 LightGBM 集成推理
    python3 backtest/run_reasoning_backtest.py --symbol ETH-USDT  # 回测其他币种
    python3 backtest/run_reasoning_backtest.py --synthetic 1500    # 使用1500天合成数据
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest import (
    BacktestEngine,
    BacktestResult,
    BuyAndHoldStrategy,
    MovingAverageStrategy,
    TrendScreenStrategy,
    fetch_historical_data,
    generate_sample_data,
    compare_results,
    format_comparison_table,
)
from backtest.strategy import FullReasoningStrategy


def parse_args():
    parser = argparse.ArgumentParser(description="三屏推理算法回测")
    parser.add_argument("--symbol", default="BTC-USDT", help="交易对")
    parser.add_argument("--limit", type=int, default=1000, help="K线数量")
    parser.add_argument("--synthetic", type=int, default=0, help="使用合成数据(指定天数,0=真实数据)")
    parser.add_argument("--daily", action="store_true", help="每日更新信号(默认每3天)")
    parser.add_argument("--ensemble", action="store_true", help="启用LightGBM集成推理")
    parser.add_argument("--no-wind-vane", action="store_true", help="禁用BTC风向标闸门")
    parser.add_argument("--capital", type=float, default=10000.0, help="初始资金")
    parser.add_argument("--commission", type=float, default=0.0005, help="手续费率")
    parser.add_argument("--slippage", type=float, default=0.0005, help="滑点率")
    parser.add_argument("--leverage", type=float, default=1.0, help="杠杆倍数")
    return parser.parse_args()


def fetch_data(args):
    """获取回测数据"""
    if args.synthetic > 0:
        print(f"使用合成数据: {args.synthetic} 天")
        df = generate_sample_data(n_days=args.synthetic, start_price=100.0, volatility=0.03)
        return df, "synthetic"

    print(f"获取真实数据: {args.symbol} 日线 {args.limit} 根")
    try:
        df = fetch_historical_data(args.symbol, "1D", args.limit)
        if len(df) < 250:
            print(f"  数据不足({len(df)}根)，需要至少250根日线，降级到合成数据")
            df = generate_sample_data(n_days=1000, start_price=100.0, volatility=0.03)
            return df, "synthetic_fallback"
        print(f"  获取成功: {len(df)} 天")
        return df, "real"
    except Exception as e:
        print(f"  获取失败: {e}，降级到合成数据")
        df = generate_sample_data(n_days=1000, start_price=100.0, volatility=0.03)
        return df, "synthetic_fallback"


def run_strategy_backtest(engine, strategy, prices, name):
    """运行单个策略回测"""
    print(f"\n运行 {name} ...")
    try:
        signals = strategy.generate_signals(prices)
        result = engine.run(prices["close"], signals, symbol=name)
        bt_result = BacktestResult(result)
        n_trades = bt_result.metrics.get("total_trades", 0)
        print(f"  完成: 收益 {bt_result.total_return_pct:.2f}%, "
              f"夏普 {bt_result.sharpe_ratio:.2f}, "
              f"回撤 {bt_result.max_drawdown_pct:.2f}%, "
              f"交易 {n_trades}")
        return bt_result, strategy
    except Exception as e:
        print(f"  失败: {e}")
        import traceback
        traceback.print_exc()
        return None, strategy


def print_reasoning_stats(strategy, name):
    """打印推理算法统计信息"""
    if not isinstance(strategy, FullReasoningStrategy):
        return

    stats = strategy.get_stats()
    total = stats["total_bars"]
    if total == 0:
        return

    print(f"\n--- {name} 推理统计 ---")
    print(f"  评估总次数: {total}")
    print(f"  入场信号: 多={stats['enter_long']} | 空={stats['enter_short']} | "
          f"观望={stats['wait']}")
    enter_total = stats["enter_long"] + stats["enter_short"]
    enter_rate = enter_total / total * 100 if total > 0 else 0
    print(f"  入场率: {enter_rate:.1f}% ({enter_total}/{total})")
    print(f"  风向标硬拦截: {stats['wind_vane_blocked']} 次 "
          f"({stats['wind_vane_blocked']/total*100:.1f}%)")
    # P0 新增统计
    if stats.get("wind_vane_soft_blocked", 0) > 0:
        print(f"  风向标软拦截(P0): {stats['wind_vane_soft_blocked']} 次 "
              f"({stats['wind_vane_soft_blocked']/total*100:.1f}%)")
    if stats.get("reversal_trial", 0) > 0:
        print(f"  逆转轻仓试探入场(P0): {stats['reversal_trial']} 次 "
              f"({stats['reversal_trial']/total*100:.1f}%)")
    if stats.get("strong_consistent", 0) > 0:
        print(f"  强一致入场(P0): {stats['strong_consistent']} 次 "
              f"({stats['strong_consistent']/total*100:.1f}%)")
    # P1 新增统计
    if stats.get("dynamic_timing_entry", 0) > 0:
        print(f"  动态时机入场(P1): {stats['dynamic_timing_entry']} 次 "
              f"({stats['dynamic_timing_entry']/total*100:.1f}%)")
    # P2 新增统计：趋势阶段分布
    if stats.get("phase_early", 0) + stats.get("phase_accelerating", 0) + stats.get("phase_maturing", 0) + stats.get("phase_reversing", 0) > 0:
        print(f"  趋势阶段分布(P2): 启动={stats['phase_early']} | 加速={stats['phase_accelerating']} | "
              f"衰竭={stats['phase_maturing']} | 逆转={stats['phase_reversing']} | 未知={stats['phase_unknown']}")
        if stats.get("phase_adjusted", 0) > 0:
            print(f"  阶段调整生效(P2): {stats['phase_adjusted']} 次 "
                  f"({stats['phase_adjusted']/total*100:.1f}%)")
    # P2-v2 新增统计：Elder-ray 背离
    if stats.get("elder_bull_divergence", 0) + stats.get("elder_bear_divergence", 0) > 0:
        print(f"  Elder-ray背离(P2-v2): 看涨={stats['elder_bull_divergence']} | 看跌={stats['elder_bear_divergence']}")
        if stats.get("elder_divergence_entry", 0) > 0:
            print(f"  Elder-ray背离入场(P2-v2): {stats['elder_divergence_entry']} 次 "
                  f"({stats['elder_divergence_entry']/total*100:.1f}%)")
    print(f"  趋势不一致: {stats['trend_inconsistent']} 次 "
          f"({stats['trend_inconsistent']/total*100:.1f}%)")
    # BTC趋势方向过滤统计
    if stats.get("btc_direction_blocked", 0) > 0:
        print(f"  BTC方向过滤拦截: {stats['btc_direction_blocked']} 次 "
              f"({stats['btc_direction_blocked']/total*100:.1f}%)")
    print(f"  方向中性: {stats['neutral']} 次 "
          f"({stats['neutral']/total*100:.1f}%)")
    if stats["no_freqtrade_fallback"] > 0:
        print(f"  降级入场(无Freqtrade): {stats['no_freqtrade_fallback']} 次")
    if stats.get("ensemble_used", 0) > 0 or stats.get("ensemble_fallback", 0) > 0:
        print(f"  集成推理: 使用={stats['ensemble_used']} | 回退={stats['ensemble_fallback']}")


def main():
    args = parse_args()
    update_step = 1 if args.daily else 3
    use_wind_vane = not args.no_wind_vane
    symbol_base = args.symbol.split("-")[0]
    is_btc = symbol_base == "BTC"

    print("=" * 70)
    print("  三屏趋势系统 — 推理算法回测")
    print("=" * 70)
    print(f"  标的: {args.symbol} | 更新步长: {update_step}天 | 风向标: {use_wind_vane}")
    print(f"  集成推理: {args.ensemble} | 杠杆: {args.leverage}x")

    df, data_source = fetch_data(args)
    print(f"\n数据概况:")
    print(f"  来源: {data_source}")
    print(f"  天数: {len(df)}")
    print(f"  价格范围: {df['close'].min():.2f} ~ {df['close'].max():.2f}")
    print(f"  时间跨度: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")

    # 风向标数据充足性检查
    if use_wind_vane and is_btc and data_source in ("real",):
        weekly_count = len(df) // 7
        if weekly_count < 200:
            print(f"\n  [警告] 周线数据不足({weekly_count}周 < 200周)，风向标MA200可能无法计算")
            print(f"  风向标将退化为'数据不足，默认全开'模式")

    engine = BacktestEngine(
        initial_capital=args.capital,
        commission=args.commission,
        slippage=args.slippage,
        leverage=args.leverage,
    )

    results = {}
    strategies = {}

    # 策略1: Buy&Hold（基准）
    bt, strat = run_strategy_backtest(engine, BuyAndHoldStrategy(), df, "Buy&Hold")
    if bt:
        results["Buy&Hold"] = bt
        strategies["Buy&Hold"] = strat

    # 策略2: 双均线（趋势基准）
    bt, strat = run_strategy_backtest(engine, MovingAverageStrategy(20, 200), df, "MA20/200")
    if bt:
        results["MA20/200"] = bt
        strategies["MA20/200"] = strat

    # 策略3: 基础三屏（只用三大算法，无风向标，无完整决策链）
    bt, strat = run_strategy_backtest(
        engine,
        TrendScreenStrategy(
            min_confidence=45.0,
            warmup_periods=210,
            update_step=update_step,
            use_counter_indicators=False,  # 关闭反方指标，隔离推理算法效果
            use_risk_control=False,        # 关闭风控，隔离推理算法效果
        ),
        df,
        "基础三屏(三大算法)",
    )
    if bt:
        results["基础三屏"] = bt
        strategies["基础三屏"] = strat

    # ── 获取 BTC 数据（非 BTC 币种趋势跟随过滤用）──
    btc_df = None
    if not is_btc:
        try:
            btc_df = fetch_historical_data("BTC-USDT", "1D", args.limit)
            print(f"  BTC数据(趋势跟随): {len(btc_df)} 天")
        except Exception:
            print("  [警告] BTC数据获取失败，无法启用趋势跟随过滤")

    # 策略4: 完整推理算法（含风向标+五大算法+five_algo_decision）
    bt, strat = run_strategy_backtest(
        engine,
        FullReasoningStrategy(
            use_wind_vane=use_wind_vane,
            use_ensemble=False,
            max_position=0.60,
            warmup_periods=210,
            update_step=update_step,
            symbol=symbol_base,
            is_btc=is_btc,
            require_freqtrade=False,
            btc_prices=btc_df,
            use_btc_direction_filter=True,
        ),
        df,
        "完整推理(五大算法+风向标)",
    )
    if bt:
        results["完整推理"] = bt
        strategies["完整推理"] = strat

    # 策略5: 完整推理 + LightGBM 集成推理（可选）
    if args.ensemble:
        bt, strat = run_strategy_backtest(
            engine,
            FullReasoningStrategy(
                use_wind_vane=use_wind_vane,
                use_ensemble=True,
                max_position=0.60,
                warmup_periods=210,
                update_step=update_step,
                symbol=symbol_base,
                is_btc=is_btc,
                require_freqtrade=False,
            ),
            df,
            "完整推理+集成推理",
        )
        if bt:
            results["完整推理+集成"] = bt
            strategies["完整推理+集成"] = strat

    # 策略6: 禁用风向标的完整推理（对比风向标效果）
    if use_wind_vane:
        bt, strat = run_strategy_backtest(
            engine,
            FullReasoningStrategy(
                use_wind_vane=False,
                use_ensemble=False,
                max_position=0.60,
                warmup_periods=210,
                update_step=update_step,
                symbol=symbol_base,
                is_btc=is_btc,
                require_freqtrade=False,
                btc_prices=btc_df,
                use_btc_direction_filter=True,
            ),
            df,
            "完整推理(无风向标)",
        )
        if bt:
            results["完整推理(无风向标)"] = bt
            strategies["完整推理(无风向标)"] = strat

    # 输出对比结果
    print("\n" + "=" * 70)
    print("  策略对比汇总")
    print("=" * 70)
    if results:
        comp = compare_results(results)
        print(format_comparison_table(comp))

    # 输出推理统计
    print("\n" + "=" * 70)
    print("  推理算法统计")
    print("=" * 70)
    for name, strat in strategies.items():
        print_reasoning_stats(strat, name)

    # 输出风向标效果对比
    if "完整推理" in results and "完整推理(无风向标)" in results:
        print("\n" + "-" * 50)
        print("  BTC 风向标效果对比")
        print("-" * 50)
        r_with = results["完整推理"]
        r_without = results["完整推理(无风向标)"]
        print(f"  收益: {r_with.total_return_pct:.2f}% vs {r_without.total_return_pct:.2f}% "
              f"(差异: {r_with.total_return_pct - r_without.total_return_pct:.2f}%)")
        print(f"  夏普: {r_with.sharpe_ratio:.2f} vs {r_without.sharpe_ratio:.2f}")
        print(f"  回撤: {r_with.max_drawdown_pct:.2f}% vs {r_without.max_drawdown_pct:.2f}%")

        strat_with = strategies.get("完整推理")
        if strat_with and isinstance(strat_with, FullReasoningStrategy):
            stats = strat_with.get_stats()
            print(f"  风向标拦截次数: {stats['wind_vane_blocked']}")

    print("\n" + "=" * 70)
    print("  回测完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
