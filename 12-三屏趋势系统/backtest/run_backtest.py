"""三屏趋势系统 — 回测示例脚本

演示如何使用回测框架：
1. 基础回测（买入持有、双均线、三屏趋势）
2. 多策略对比
3. 样本内/样本外分割

用法:
    cd 12-三屏趋势系统
    python3 backtest/run_backtest.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest import (
    BacktestEngine,
    BacktestResult,
    BuyAndHoldStrategy,
    MovingAverageStrategy,
    TrendScreenStrategy,
    generate_sample_data,
    fetch_historical_data,
    train_test_split,
    compare_results,
    format_comparison_table,
)


def demo_sample_data_backtest():
    """演示1：使用合成数据进行基础回测"""
    print("=" * 60)
    print("  演示1：合成数据基础回测")
    print("=" * 60)

    df = generate_sample_data(n_days=1000, start_price=100.0, volatility=0.02)
    print(f"合成数据: {len(df)} 天, 起始价: {df['close'].iloc[0]:.2f}, 最终价: {df['close'].iloc[-1]:.2f}")

    engine = BacktestEngine(
        initial_capital=10000.0,
        commission=0.0005,
        slippage=0.0005,
    )

    strategies = {
        "Buy&Hold": BuyAndHoldStrategy(),
        "MA20/200": MovingAverageStrategy(20, 200),
    }

    results = {}
    for name, strategy in strategies.items():
        signals = strategy.generate_signals(df)
        result = engine.run(df["close"], signals, symbol=name)
        results[name] = BacktestResult(result)
        print(f"\n--- {name} ---")
        print(results[name].summary())

    print("\n" + "=" * 60)
    print("  策略对比")
    print("=" * 60)
    comp = compare_results(results)
    print(format_comparison_table(comp))


def demo_real_data_backtest():
    """演示2：使用真实数据回测（需要OKX数据）"""
    print("\n" + "=" * 60)
    print("  演示2：真实数据回测 (BTC-USDT 日线)")
    print("=" * 60)

    try:
        df = fetch_historical_data("BTC-USDT", "1D", 500)
        if len(df) < 100:
            print("数据不足，跳过真实数据回测")
            return
    except Exception as e:
        print(f"获取真实数据失败: {e}")
        return

    print(f"获取数据: {len(df)} 天")
    print(f"价格范围: {df['close'].min():.2f} ~ {df['close'].max():.2f}")

    engine = BacktestEngine(
        initial_capital=10000.0,
        commission=0.0005,
        slippage=0.0005,
    )

    strategies = {
        "Buy&Hold": BuyAndHoldStrategy(),
        "MA20/200": MovingAverageStrategy(20, 200),
        "TrendScreen": TrendScreenStrategy(min_confidence=45.0),
    }

    results = {}
    for name, strategy in strategies.items():
        print(f"\n运行 {name} ...")
        try:
            signals = strategy.generate_signals(df)
            result = engine.run(df["close"], signals, symbol=name)
            results[name] = BacktestResult(result)
            print(f"  完成: 收益 {results[name].total_return_pct:.2f}%, "
                  f"夏普 {results[name].sharpe_ratio:.2f}")
        except Exception as e:
            print(f"  失败: {e}")

    if results:
        print("\n" + "=" * 60)
        print("  策略对比")
        print("=" * 60)
        comp = compare_results(results)
        print(format_comparison_table(comp))


def demo_train_test_split():
    """演示3：样本内/样本外分割回测"""
    print("\n" + "=" * 60)
    print("  演示3：样本内/样本外分割")
    print("=" * 60)

    df = generate_sample_data(n_days=1000, start_price=100.0, volatility=0.02)
    train_df, test_df = train_test_split(df, train_ratio=0.7, by_date=True)

    print(f"训练集: {len(train_df)} 天 ({len(train_df)/len(df)*100:.0f}%)")
    print(f"测试集: {len(test_df)} 天 ({len(test_df)/len(df)*100:.0f}%)")

    engine = BacktestEngine(initial_capital=10000.0)
    strategy = MovingAverageStrategy(20, 200)

    train_signals = strategy.generate_signals(train_df)
    train_result = BacktestResult(
        engine.run(train_df["close"], train_signals, symbol="Train")
    )

    test_signals = strategy.generate_signals(test_df)
    test_result = BacktestResult(
        engine.run(test_df["close"], test_signals, symbol="Test")
    )

    print("\n--- 训练集表现 ---")
    print(f"  累计收益: {train_result.total_return_pct:.2f}%")
    print(f"  夏普比率: {train_result.sharpe_ratio:.2f}")
    print(f"  最大回撤: {train_result.max_drawdown_pct:.2f}%")

    print("\n--- 测试集表现 ---")
    print(f"  累计收益: {test_result.total_return_pct:.2f}%")
    print(f"  夏普比率: {test_result.sharpe_ratio:.2f}")
    print(f"  最大回撤: {test_result.max_drawdown_pct:.2f}%")

    decay = 0
    if train_result.sharpe_ratio > 0:
        decay = (train_result.sharpe_ratio - test_result.sharpe_ratio) / train_result.sharpe_ratio * 100
    print(f"\n夏普衰减: {decay:.1f}% (越低越好，>50%可能过拟合)")


if __name__ == "__main__":
    demo_sample_data_backtest()
    demo_real_data_backtest()
    demo_train_test_split()
