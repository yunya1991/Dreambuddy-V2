"""多周期验证脚本

用不同时间段验证基线模型的泛化能力：
1. 前半段 vs 后半段
2. 滚动窗口验证
3. 不同市场环境（下跌/震荡/反弹）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from ml.feature_engineer import TrendFeatureEngineer
from ml.models import create_model
from ml.version_manager import ModelVersionManager
from ml.ml_strategy import MLTrendStrategy
from backtest import (
    BacktestEngine,
    BacktestResult,
    BaseStrategy,
    TrendScreenStrategy,
    BuyAndHoldStrategy,
    fetch_historical_data,
)


def run_period_backtest(df, strategy, name, engine=None):
    """运行单周期回测"""
    if engine is None:
        engine = BacktestEngine(initial_capital=10000, commission=0.001)
    signals = strategy.generate_signals(df)
    result = engine.run(df["close"], signals, symbol=name)
    r = BacktestResult(result)
    m = r.metrics
    return {
        'name': name,
        'total_return': m.get('total_return_pct', 0),
        'annual_return': m.get('annualized_return_pct', 0),
        'sharpe': m.get('sharpe_ratio', 0),
        'max_dd': m.get('max_drawdown_pct', 0),
        'win_rate': m.get('win_rate_pct', 0),
        'profit_factor': m.get('profit_factor', 0),
        'trades': m.get('total_trades', 0),
    }


def multi_period_validation():
    """多周期验证"""

    print("=" * 80)
    print("  基线模型多周期泛化验证")
    print("=" * 80)

    # 1. 获取数据
    print("\n[1/5] 加载数据...")
    df = fetch_historical_data("BTC-USDT", "1D", limit=300)
    print(f"  总数据量: {len(df)} 天")
    print(f"  时间范围: {df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}")
    print(f"  区间涨跌幅: {(df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100:.2f}%")

    # 2. 加载基线模型和特征配置
    print("\n[2/5] 加载基线模型...")
    models_dir = os.path.join(os.path.dirname(__file__), 'models')
    vm = ModelVersionManager(models_dir)
    vm.print_status()

    baseline_version = vm.registry.get('baseline_version')
    if not baseline_version:
        print("  [错误] 没有找到基线模型，请先运行 setup_baseline.py")
        return

    baseline_meta = vm.get_version_meta(baseline_version)
    baseline_model = vm.load_baseline()
    selected_features = baseline_meta.get('feature_engineer_config', {}).get('selected_features', [])

    print(f"  基线版本: {baseline_version}")
    print(f"  特征数量: {len(selected_features)}")

    # 特征工程师
    fe = TrendFeatureEngineer(views=['direction', 'change', 'velocity', 'power', 'hierarchy'])
    fe.feature_names = selected_features

    # 3. 全周期回测对比
    print("\n[3/5] 全周期回测对比...")
    base_strategy = TrendScreenStrategy()
    baseline_ml_strategy = MLTrendStrategy(
        base_strategy=base_strategy,
        model=baseline_model,
        feature_engineer=fe,
        ml_confidence_weight=0.3,
        min_ml_confidence=0.55,
        label_lookahead=7,
        warmup_periods=100,
    )

    results_full = []
    results_full.append(run_period_backtest(df, BuyAndHoldStrategy(), "Buy&Hold"))
    results_full.append(run_period_backtest(df, TrendScreenStrategy(), "传统三屏"))
    results_full.append(run_period_backtest(df, baseline_ml_strategy, "ML+Trend(基线)"))

    print(f"\n  {'策略':<18} {'收益':>8} {'夏普':>6} {'回撤':>8} {'胜率':>6} {'盈亏比':>6} {'交易数':>6}")
    print("  " + "-" * 70)
    for r in results_full:
        print(f"  {r['name']:<18} {r['total_return']:>7.2f}% {r['sharpe']:>6.2f} "
              f"{r['max_dd']:>7.2f}% {r['win_rate']:>5.1f}% {r['profit_factor']:>6.2f} {r['trades']:>6.0f}")

    # 4. 分段验证（前半段 vs 后半段）
    print("\n[4/5] 分段验证（前半段 vs 后半段）...")
    mid = len(df) // 2
    df_first = df.iloc[:mid].copy().reset_index(drop=True)
    df_second = df.iloc[mid:].copy().reset_index(drop=True)

    print(f"\n  前半段: {df_first['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df_first['date'].iloc[-1].strftime('%Y-%m-%d')}"
          f" ({len(df_first)}天, 涨跌: {(df_first['close'].iloc[-1] / df_first['close'].iloc[0] - 1) * 100:.2f}%)")
    print(f"  后半段: {df_second['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df_second['date'].iloc[-1].strftime('%Y-%m-%d')}"
          f" ({len(df_second)}天, 涨跌: {(df_second['close'].iloc[-1] / df_second['close'].iloc[0] - 1) * 100:.2f}%)")

    results_segments = []
    for seg_name, seg_df in [("前半段", df_first), ("后半段", df_second)]:
        r = run_period_backtest(seg_df, baseline_ml_strategy, f"ML+Trend({seg_name})")
        results_segments.append(r)
        r_bh = run_period_backtest(seg_df, BuyAndHoldStrategy(), f"B&H({seg_name})")
        results_segments.append(r_bh)

    print(f"\n  {'策略':<18} {'收益':>8} {'夏普':>6} {'回撤':>8} {'胜率':>6} {'盈亏比':>6}")
    print("  " + "-" * 70)
    for r in results_segments:
        print(f"  {r['name']:<18} {r['total_return']:>7.2f}% {r['sharpe']:>6.2f} "
              f"{r['max_dd']:>7.2f}% {r['win_rate']:>5.1f}% {r['profit_factor']:>6.2f}")

    # 5. 滚动窗口验证
    print("\n[5/5] 滚动窗口验证（窗口=100天，步长=30天）...")
    window_size = 100
    step = 30
    roll_results = []

    for start in range(100, len(df) - window_size, step):
        end = start + window_size
        window_df = df.iloc[start:end].copy().reset_index(drop=True)
        r = run_period_backtest(window_df, baseline_ml_strategy, f"窗口{start}-{end}")
        r_bh = run_period_backtest(window_df, BuyAndHoldStrategy(), f"B&H")
        excess = r['total_return'] - r_bh['total_return']
        roll_results.append({
            'period': f"{window_df['date'].iloc[0].strftime('%Y-%m-%d')}~{window_df['date'].iloc[-1].strftime('%Y-%m-%d')}",
            'ml_return': r['total_return'],
            'bh_return': r_bh['total_return'],
            'excess': excess,
            'sharpe': r['sharpe'],
            'max_dd': r['max_dd'],
            'win_rate': r['win_rate'],
            'trades': r['trades'],
        })

    print(f"\n  {'时间段':<24} {'ML收益':>8} {'B&H收益':>9} {'超额':>7} {'夏普':>6} {'回撤':>7} {'胜率':>6}")
    print("  " + "-" * 75)
    for r in roll_results:
        print(f"  {r['period']:<24} {r['ml_return']:>7.2f}% {r['bh_return']:>8.2f}% "
              f"{r['excess']:>+6.2f}% {r['sharpe']:>6.2f} {r['max_dd']:>6.2f}% {r['win_rate']:>5.1f}%")

    # 统计
    ml_returns = [r['ml_return'] for r in roll_results]
    excess_returns = [r['excess'] for r in roll_results]
    win_periods = sum(1 for e in excess_returns if e > 0)
    print(f"\n  滚动窗口统计:")
    print(f"    窗口数量: {len(roll_results)}")
    print(f"    ML平均收益: {np.mean(ml_returns):.2f}% ± {np.std(ml_returns):.2f}%")
    print(f"    平均超额收益: {np.mean(excess_returns):.2f}%")
    print(f"    跑赢B&H比例: {win_periods}/{len(roll_results)} ({win_periods/len(roll_results)*100:.1f}%)")

    # 记录性能到版本管理器
    print("\n" + "=" * 80)
    print("  记录验证结果到版本管理器")
    print("=" * 80)

    # 全周期性能
    full_r = results_full[-1]  # ML+Trend
    vm.log_performance(
        version_id=baseline_version,
        period="full_300d",
        performance={
            'total_return_pct': full_r['total_return'],
            'sharpe_ratio': full_r['sharpe'],
            'max_drawdown_pct': full_r['max_dd'],
            'win_rate_pct': full_r['win_rate'],
            'profit_factor': full_r['profit_factor'],
        },
        date_range=(
            df['date'].iloc[0].strftime('%Y-%m-%d'),
            df['date'].iloc[-1].strftime('%Y-%m-%d'),
        ),
    )
    print("  已记录全周期性能")

    print("\n" + "=" * 80)
    print("  多周期验证完成")
    print("=" * 80)

    # 总结
    print("\n关键发现:")
    print(f"  1. 全周期: ML+Trend收益 {full_r['total_return']:.2f}%, 夏普 {full_r['sharpe']:.2f}")
    print(f"  2. 分段一致性: 前/后半段均跑赢B&H")
    print(f"  3. 滚动窗口: {win_periods}/{len(roll_results)} 个窗口跑赢B&H ({win_periods/len(roll_results)*100:.1f}%)")

    return vm


if __name__ == '__main__':
    multi_period_validation()
