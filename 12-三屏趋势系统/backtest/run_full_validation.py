"""三屏趋势系统 — 完整回测验证脚本（优化版）

对BTC运行完整验证流程，对ETH只跑基础回测对比。
优化：减少Walk-Forward折数、降低置换次数、添加进度输出。
"""

import sys
import os
import time
import warnings
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
warnings.filterwarnings('ignore')

from backtest import (
    BacktestEngine,
    BacktestResult,
    BuyAndHoldStrategy,
    MovingAverageStrategy,
    TrendScreenStrategy,
    generate_sample_data,
    WalkForwardAnalyzer,
    parameter_sensitivity_analysis,
    format_sensitivity_report,
    permutation_test,
    format_permutation_report,
    cost_sensitivity_test,
    format_cost_report,
    calculate_ece,
    cross_validated_calibration,
    collect_calibration_data,
    format_calibration_report,
    format_comparison_table,
    compare_results,
)
from data.market_data import fetch_candles


def fetch_real_data(symbol: str, limit: int = 300):
    """获取真实K线数据并转为DataFrame"""
    candles = fetch_candles(symbol, '1D', limit)
    if not candles:
        print(f"  ⚠️ {symbol} 数据获取失败，使用合成数据")
        return generate_sample_data(n_days=limit, volatility=0.03, seed=42)

    df = pd.DataFrame([{
        'date': pd.to_datetime(c['ts'], unit='ms'),
        'open': c['o'],
        'high': c['h'],
        'low': c['l'],
        'close': c['c'],
        'volume': c['vol'],
    } for c in candles])
    df = df.sort_values('date').reset_index(drop=True)
    return df


def run_backtest(symbol: str, df: pd.DataFrame, full_validation: bool = True):
    """运行回测验证"""
    prices = df.set_index('date')
    close = prices['close']

    engine = BacktestEngine(initial_capital=10000.0, commission=0.0005, slippage=0.0005)

    # ========== 1. 基础回测 ==========
    print(f"\n{'='*70}")
    print(f"  [{symbol}] 基础回测")
    print(f"{'='*70}")
    print(f"数据: {len(df)} 天, 价格 {close.iloc[0]:.2f} → {close.iloc[-1]:.2f}")

    strategies = {
        'Buy&Hold': BuyAndHoldStrategy(),
        'MA20/200': MovingAverageStrategy(20, 200),
        'TrendScreen': TrendScreenStrategy(
            min_confidence=40.0, trial_confidence=45.0,
            trial_position_ratio=0.3, max_position=1.0,
            warmup_periods=50,
        ),
    }

    results = {}
    for name, strategy in strategies.items():
        t0 = time.time()
        print(f"\n运行 {name} ...", end='', flush=True)
        try:
            signals = strategy.generate_signals(prices)
            n_active = int((signals.abs() > 0.01).sum())
            result = engine.run(close, signals, symbol=name)
            results[name] = BacktestResult(result)
            r = results[name]
            elapsed = time.time() - t0
            print(f" ({elapsed:.1f}s)")
            print(f"  信号: {n_active}天有仓位 | "
                  f"收益: {r.total_return_pct:>7.2f}% | "
                  f"夏普: {r.sharpe_ratio:>5.2f} | "
                  f"回撤: {r.max_drawdown_pct:>6.2f}% | "
                  f"交易: {r.metrics.get('total_trades', 0)}次")
        except Exception as e:
            print(f" ❌ {e}")

    if len(results) >= 2:
        print(f"\n--- 策略对比 ---")
        comp = compare_results(results)
        print(format_comparison_table(comp))

    if 'TrendScreen' in results:
        print(f"\n--- TrendScreen 详细报告 ---")
        print(results['TrendScreen'].summary())

    if not full_validation:
        return results

    # ========== 2. Walk-Forward (仅MA，TrendScreen太慢) ==========
    print(f"\n{'='*70}")
    print(f"  [{symbol}] Walk-Forward 滚动验证 (MA20/200)")
    print(f"{'='*70}")

    wf_engine = BacktestEngine(initial_capital=10000.0, commission=0.0005, slippage=0.0005)
    wf_analyzer = WalkForwardAnalyzer(train_window=150, test_window=30)
    wf_result = wf_analyzer.run(prices, MovingAverageStrategy(20, 200), engine=wf_engine)
    print(wf_analyzer.format_report(wf_result))

    # ========== 3. 参数敏感性 ==========
    print(f"\n{'='*70}")
    print(f"  [{symbol}] 参数敏感性分析 (MA fast_window)")
    print(f"{'='*70}")

    sens_result = parameter_sensitivity_analysis(
        prices,
        strategy_factory=lambda fast_window: MovingAverageStrategy(fast_window, 200),
        param_name='fast_window',
        param_values=[5, 10, 15, 20, 25, 30, 40, 50],
        engine=engine,
    )
    print(format_sensitivity_report(sens_result))

    # ========== 4. 置换检验 ==========
    print(f"\n{'='*70}")
    print(f"  [{symbol}] 置换检验 (MA20/200, 300次)")
    print(f"{'='*70}")

    perm_result = permutation_test(
        prices, MovingAverageStrategy(20, 200), engine=engine, n_permutations=300
    )
    print(format_permutation_report(perm_result))

    # ========== 5. 交易成本敏感性 ==========
    print(f"\n{'='*70}")
    print(f"  [{symbol}] 交易成本敏感性 (MA20/200)")
    print(f"{'='*70}")

    cost_result = cost_sensitivity_test(
        prices, MovingAverageStrategy(20, 200), engine=engine
    )
    print(format_cost_report(cost_result))

    # ========== 6. 置信度校准 ==========
    print(f"\n{'='*70}")
    print(f"  [{symbol}] 置信度校准分析 (TrendScreen)")
    print(f"{'='*70}")

    ts_strategy = TrendScreenStrategy(
        min_confidence=30.0, trial_confidence=35.0,
        trial_position_ratio=0.3, max_position=1.0,
        warmup_periods=50,
    )
    print("  收集校准数据...", end='', flush=True)
    cal_data = collect_calibration_data(prices, ts_strategy, lookahead=7)
    print(f" {cal_data['n_samples']} 样本")

    if cal_data["n_samples"] >= 20:
        ece_result = calculate_ece(
            cal_data["confidences"], cal_data["outcomes"], n_bins=10
        )
        cv_result = cross_validated_calibration(
            cal_data["confidences"], cal_data["outcomes"],
            method='platt', cv=5
        )
        print(format_calibration_report(ece_result, cv_result))
    else:
        print(f"  样本不足: {cal_data['n_samples']} (需≥20)")

    return results


if __name__ == "__main__":
    print("="*70)
    print("  三屏趋势系统 — 完整回测验证")
    print("="*70)

    # BTC — 完整验证
    print("\n>>> 获取 BTC-USDT 数据")
    btc_df = fetch_real_data("BTC-USDT", 300)
    if len(btc_df) >= 50:
        btc_results = run_backtest("BTC-USDT", btc_df, full_validation=True)

    # ETH — 基础回测对比
    print("\n\n>>> 获取 ETH-USDT 数据")
    eth_df = fetch_real_data("ETH-USDT", 300)
    if len(eth_df) >= 50:
        eth_results = run_backtest("ETH-USDT", eth_df, full_validation=False)

    # 汇总
    print(f"\n{'#'*70}")
    print(f"#  回测验证完成")
    print(f"{'#'*70}")
    print(f"\nBTC: {'收益' + str(btc_results.get('TrendScreen', BacktestResult({})).total_return_pct) + '%' if 'TrendScreen' in btc_results else 'N/A'}")
    if 'eth_results' in dir():
        print(f"ETH: {'收益' + str(eth_results.get('TrendScreen', BacktestResult({})).total_return_pct) + '%' if 'TrendScreen' in eth_results else 'N/A'}")
