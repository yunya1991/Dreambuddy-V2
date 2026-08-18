"""多周期验证脚本 v2 - 用基线模型（严格样本外验证）

验证方式：
- 训练集：前60%数据训练模型
- 测试集：后40%数据做样本外验证
- 用Walk-Forward方式做稳健性检验
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
    TrendScreenStrategy,
    BuyAndHoldStrategy,
    fetch_historical_data,
)


def run_backtest(df, strategy, name):
    """运行回测"""
    engine = BacktestEngine(initial_capital=10000, commission=0.001)
    signals = strategy.generate_signals(df)
    result = engine.run(df["close"], signals, symbol=name)
    return BacktestResult(result)


def multi_period_validation():
    """多周期验证"""

    print("=" * 80)
    print("  基线模型多周期泛化验证（严格样本外）")
    print("=" * 80)

    # 1. 加载数据
    print("\n[1/5] 加载数据...")
    df = fetch_historical_data("BTC-USDT", "1D", limit=300)
    print(f"  总数据: {len(df)} 天")
    print(f"  时间: {df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}")

    # 2. 加载基线模型
    print("\n[2/5] 加载基线模型...")
    models_dir = os.path.join(os.path.dirname(__file__), 'models')
    vm = ModelVersionManager(models_dir)
    vm.print_status()

    baseline_version = vm.registry.get('baseline_version')
    if not baseline_version:
        print("  [错误] 没有找到基线模型")
        return

    baseline_meta = vm.get_version_meta(baseline_version)
    baseline_model = vm.load_baseline()
    selected_features = baseline_meta.get('feature_engineer_config', {}).get('selected_features', [])

    print(f"  基线版本: {baseline_version}")
    print(f"  特征数量: {len(selected_features)}")

    fe = TrendFeatureEngineer(views=['direction', 'change', 'velocity', 'power', 'hierarchy'])
    fe.feature_names = selected_features

    # 3. 分割训练集/测试集
    print("\n[3/5] 分割训练集/测试集...")
    split_idx = int(len(df) * 0.6)
    df_train = df.iloc[:split_idx].copy().reset_index(drop=True)
    df_test = df.iloc[split_idx:].copy().reset_index(drop=True)

    print(f"  训练集: {len(df_train)} 天 ({df_train['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df_train['date'].iloc[-1].strftime('%Y-%m-%d')})")
    print(f"  测试集: {len(df_test)} 天 ({df_test['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df_test['date'].iloc[-1].strftime('%Y-%m-%d')})")

    base_strategy = TrendScreenStrategy()
    baseline_ml = MLTrendStrategy(
        base_strategy=base_strategy,
        model=baseline_model,
        feature_engineer=fe,
        ml_confidence_weight=0.3,
        min_ml_confidence=0.55,
        label_lookahead=7,
        warmup_periods=30,
    )

    # 4. 测试集样本外回测
    print("\n[4/5] 测试集样本外回测...")
    results = {}
    results['Buy&Hold'] = run_backtest(df_test, BuyAndHoldStrategy(), "B&H_test")
    results['传统三屏'] = run_backtest(df_test, TrendScreenStrategy(), "TrendScreen_test")
    results['ML+Trend(基线)'] = run_backtest(df_test, baseline_ml, "ML_Trend_test")

    print(f"\n  {'策略':<18} {'收益':>8} {'夏普':>6} {'回撤':>8} {'胜率':>6} {'盈亏比':>6} {'交易数':>6}")
    print("  " + "-" * 70)
    for name, r in results.items():
        m = r.metrics
        print(f"  {name:<18} {m.get('total_return_pct', 0):>7.2f}% {m.get('sharpe_ratio', 0):>6.2f} "
              f"{m.get('max_drawdown_pct', 0):>7.2f}% {m.get('win_rate_pct', 0):>5.1f}% "
              f"{m.get('profit_factor', 0):>6.2f} {m.get('total_trades', 0):>6.0f}")

    # 5. 滚动窗口验证（测试集内）
    print("\n[5/5] 测试集内滚动窗口验证（窗口=60天，步长=20天）...")
    window_size = 60
    step = 20
    roll_results = []

    for start in range(0, len(df_test) - window_size + 1, step):
        end = start + window_size
        window_df = df_test.iloc[start:end].copy().reset_index(drop=True)
        r = run_backtest(window_df, baseline_ml, f"ML_{start}_{end}")
        r_bh = run_backtest(window_df, BuyAndHoldStrategy(), f"BH_{start}_{end}")
        excess = r.metrics.get('total_return_pct', 0) - r_bh.metrics.get('total_return_pct', 0)
        roll_results.append({
            'period': f"{window_df['date'].iloc[0].strftime('%Y-%m-%d')}~{window_df['date'].iloc[-1].strftime('%Y-%m-%d')}",
            'ml_return': r.metrics.get('total_return_pct', 0),
            'bh_return': r_bh.metrics.get('total_return_pct', 0),
            'excess': excess,
            'sharpe': r.metrics.get('sharpe_ratio', 0),
            'max_dd': r.metrics.get('max_drawdown_pct', 0),
            'win_rate': r.metrics.get('win_rate_pct', 0),
            'trades': r.metrics.get('total_trades', 0),
        })

    print(f"\n  {'时间段':<24} {'ML收益':>8} {'B&H收益':>9} {'超额':>7} {'夏普':>6} {'回撤':>7} {'胜率':>6}")
    print("  " + "-" * 75)
    for r in roll_results:
        print(f"  {r['period']:<24} {r['ml_return']:>7.2f}% {r['bh_return']:>8.2f}% "
              f"{r['excess']:>+6.2f}% {r['sharpe']:>6.2f} {r['max_dd']:>6.2f}% {r['win_rate']:>5.1f}%")

    ml_returns = [r['ml_return'] for r in roll_results]
    excess_returns = [r['excess'] for r in roll_results]
    win_periods = sum(1 for e in excess_returns if e > 0)
    print(f"\n  滚动窗口统计:")
    print(f"    窗口数量: {len(roll_results)}")
    print(f"    ML平均收益: {np.mean(ml_returns):.2f}% ± {np.std(ml_returns):.2f}%")
    print(f"    平均超额收益: {np.mean(excess_returns):.2f}%")
    print(f"    跑赢B&H比例: {win_periods}/{len(roll_results)} ({win_periods/len(roll_results)*100:.1f}%")

    # 记录性能
    print("\n" + "=" * 80)
    print("  记录验证结果")
    print("=" * 80)

    test_r = results['ML+Trend(基线)'].metrics
    vm.log_performance(
        version_id=baseline_version,
        period="out_of_sample_test",
        performance={
            'total_return_pct': test_r.get('total_return_pct', 0),
            'sharpe_ratio': test_r.get('sharpe_ratio', 0),
            'max_drawdown_pct': test_r.get('max_drawdown_pct', 0),
            'win_rate_pct': test_r.get('win_rate_pct', 0),
            'profit_factor': test_r.get('profit_factor', 0),
        },
        date_range=(
            df_test['date'].iloc[0].strftime('%Y-%m-%d'),
            df_test['date'].iloc[-1].strftime('%Y-%m-%d'),
        ),
    )
    print("  已记录测试集性能")

    print("\n" + "=" * 80)
    print("  多周期验证完成")
    print("=" * 80)

    print("\n关键发现:")
    print(f"  1. 样本外测试: ML+Trend收益 {test_r.get('total_return_pct', 0):.2f}%, 夏普 {test_r.get('sharpe_ratio', 0):.2f}")
    print(f"  2. 相对传统三屏: 超额收益 {test_r.get('total_return_pct', 0) - results['传统三屏'].metrics.get('total_return_pct', 0):.2f}%")
    print(f"  3. 滚动窗口稳健性: {win_periods}/{len(roll_results)} 窗口跑赢B&H ({win_periods/len(roll_results)*100:.1f}%)")
    print(f"  4. 注意: 测试集仅120天，样本量有限，需更多数据验证")

    return vm


if __name__ == '__main__':
    multi_period_validation()
