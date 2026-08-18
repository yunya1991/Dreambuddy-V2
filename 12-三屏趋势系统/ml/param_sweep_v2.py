"""AI V2 参数扫描

基于 ai_backtest_comparison.py 的相同数据，测试不同参数组合。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from typing import Dict, Any

from ml.lr_feature_engineer import LeastResistanceFeatureEngineer
from ml.lr_ml_strategy_v2 import LeastResistanceAIStrategyV2
from backtest.engine import BacktestEngine


def generate_data(n_days=600, seed=42):
    np.random.seed(seed)
    dates = pd.date_range('2023-01-01', periods=n_days, freq='D')
    t = np.arange(n_days)
    log_ret = 0.0007 + 0.015*np.sin(2*np.pi*t/180) + 0.008*np.sin(2*np.pi*t/30) + np.random.randn(n_days)*0.02
    log_ret = np.clip(log_ret, -0.08, 0.08)
    close = 100 * np.exp(np.cumsum(log_ret))
    prices = pd.DataFrame({
        'open': close * (1 + np.random.randn(n_days) * 0.003),
        'high': close * (1 + np.abs(np.random.randn(n_days) * 0.01)),
        'low': close * (1 - np.abs(np.random.randn(n_days) * 0.01)),
        'close': close,
        'volume': np.random.rand(n_days) * 1000 + 100,
    }, index=dates)
    prices['high'] = prices[['high', 'open', 'close']].max(axis=1)
    prices['low'] = prices[['low', 'open', 'close']].min(axis=1)
    return prices


def test_params(prices, params: Dict[str, Any]) -> Dict[str, float]:
    fundamental_data = {
        'screen1': {
            'composite_score': 65.0, 'momentum_score': 70.0,
            'value_score': 60.0, 'growth_score': 65.0,
            'quality_score': 68.0, 'sentiment_score': 55.0,
        },
        'fundamental_9': {
            'pe_ttm': 15.0, 'pb': 2.0, 'roe': 12.0,
            'revenue_growth': 20.0, 'profit_growth': 18.0,
            'debt_ratio': 45.0, 'cash_ratio': 30.0,
            'gross_margin': 35.0, 'net_margin': 15.0,
        }
    }

    strategy = LeastResistanceAIStrategyV2(
        label_lookahead=7,
        train_window=params.get('train_window', 200),
        retrain_interval=30,
        min_ml_confidence=params.get('min_ml_confidence', 0.1),
        enable_fundamental=True,
        enable_multitask=True,
        enable_dynamic_weight=True,
        enable_feature_selection=False,
        base_rule_weight=params.get('base_rule_weight', 0.3),
        fundamental_data=fundamental_data,
    )

    # 修改动态权重参数
    if strategy.dynamic_fusion:
        strategy.dynamic_fusion.base_rule_weight = params.get('fusion_base_rule_weight', 0.55)
        strategy.dynamic_fusion.trend_sensitivity = params.get('fusion_trend_sensitivity', 0.25)
        strategy.dynamic_fusion.vol_sensitivity = params.get('fusion_vol_sensitivity', 0.25)
        strategy.dynamic_fusion.volume_sensitivity = params.get('fusion_volume_sensitivity', 0.2)
        strategy.dynamic_fusion.duration_sensitivity = params.get('fusion_duration_sensitivity', 0.25)

    signals = strategy.generate_signals(prices)
    engine = BacktestEngine(initial_capital=10000)
    result = engine.run(prices['close'], signals)
    m = result['metrics']
    return {
        'return': m.get('total_return_pct', 0),
        'sharpe': m.get('sharpe_ratio', 0),
        'dd': m.get('max_drawdown_pct', 0),
        'trades': m.get('trade_count', 0),
    }


def main():
    prices = generate_data(600, 42)
    print("=" * 70)
    print("  AI V2 参数扫描")
    print("=" * 70)

    # 基线
    print("\n[基线] 默认参数")
    baseline = test_params(prices, {})
    print(f"  收益: {baseline['return']:.2f}%, 夏普: {baseline['sharpe']:.3f}, "
          f"回撤: {baseline['dd']:.2f}%, 交易: {baseline['trades']}")

    # 扫描关键参数
    test_cases = [
        # (描述, 参数)
        ("高规则权重", {'fusion_base_rule_weight': 0.7, 'fusion_trend_sensitivity': 0.4}),
        ("低规则权重", {'fusion_base_rule_weight': 0.3, 'fusion_trend_sensitivity': 0.1}),
        ("高波动敏感", {'fusion_vol_sensitivity': 0.4}),
        ("低波动敏感", {'fusion_vol_sensitivity': 0.05}),
        ("高量敏感", {'fusion_volume_sensitivity': 0.4}),
        ("低量敏感", {'fusion_volume_sensitivity': 0.05}),
        ("高时长敏感", {'fusion_duration_sensitivity': 0.4}),
        ("低时长敏感", {'fusion_duration_sensitivity': 0.05}),
        ("高置信阈值", {'min_ml_confidence': 0.2}),
        ("低置信阈值", {'min_ml_confidence': 0.05}),
        ("大窗口", {'train_window': 300}),
        ("小窗口", {'train_window': 100}),
    ]

    results = []
    for desc, p in test_cases:
        print(f"\n[{desc}] {p}")
        r = test_params(prices, p)
        print(f"  收益: {r['return']:.2f}%, 夏普: {r['sharpe']:.3f}, "
              f"回撤: {r['dd']:.2f}%, 交易: {r['trades']}")
        results.append((desc, p, r))

    # 打印排名
    print(f"\n{'=' * 70}")
    print("  参数排名 (按收益)")
    print(f"{'=' * 70}")
    results.sort(key=lambda x: -x[2]['return'])
    for i, (desc, p, r) in enumerate(results[:10], 1):
        print(f"{i}. {desc:12s} 收益: {r['return']:7.2f}%  夏普: {r['sharpe']:6.3f}  交易: {r['trades']:3d}")


if __name__ == '__main__':
    main()
