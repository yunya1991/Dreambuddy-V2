"""参数网格搜索

对 AI V2 关键参数进行网格搜索，找到最优组合。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import numpy as np
import pandas as pd
from itertools import product
from typing import Dict, Any
from datetime import datetime

from ml.lr_ml_strategy_v2 import LeastResistanceAIStrategyV2
from backtest.engine import BacktestEngine


def generate_synthetic_data(n_days: int = 600, seed: int = 42) -> pd.DataFrame:
    """生成合成数据"""
    np.random.seed(seed)
    dates = pd.date_range('2023-01-01', periods=n_days, freq='D')
    t = np.arange(n_days)

    daily_trend = 0.0007
    cycle = 0.015 * np.sin(2 * np.pi * t / 180)
    mid_cycle = 0.008 * np.sin(2 * np.pi * t / 30)
    noise = np.random.randn(n_days) * 0.02

    log_ret = daily_trend + cycle + mid_cycle + noise
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


def run_backtest(prices: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, float]:
    """运行回测"""
    strategy = LeastResistanceAIStrategyV2(
        label_lookahead=int(params.get('label_lookahead', 7)),
        train_window=int(params.get('train_window', 200)),
        retrain_interval=30,
        min_ml_confidence=params.get('min_ml_confidence', 0.1),
        min_train_samples=40,
        enable_fundamental=True,
        enable_multitask=True,
        enable_dynamic_weight=True,
        enable_feature_selection=False,
        top_k_features=40,
        base_rule_weight=params.get('base_rule_weight', 0.3),
    )

    if strategy.dynamic_fusion:
        strategy.dynamic_fusion.base_rule_weight = params.get('fusion_base_rule_weight', 0.55)
        strategy.dynamic_fusion.trend_sensitivity = params.get('fusion_trend_sensitivity', 0.25)
        strategy.dynamic_fusion.vol_sensitivity = params.get('fusion_vol_sensitivity', 0.25)
        strategy.dynamic_fusion.volume_sensitivity = params.get('fusion_volume_sensitivity', 0.2)
        strategy.dynamic_fusion.duration_sensitivity = params.get('fusion_duration_sensitivity', 0.25)

    try:
        signals = strategy.generate_signals(prices)
        engine = BacktestEngine(initial_capital=10000)
        result = engine.run(prices['close'], signals)
        metrics = result.get('metrics', {})
        return {
            'total_return_pct': metrics.get('total_return_pct', 0),
            'sharpe_ratio': metrics.get('sharpe_ratio', 0),
            'max_drawdown_pct': metrics.get('max_drawdown_pct', 0),
            'win_rate': metrics.get('win_rate', 0),
            'trade_count': metrics.get('trade_count', 0),
        }
    except Exception as e:
        print(f"  [ERROR] {e}")
        return {
            'total_return_pct': -999,
            'sharpe_ratio': -999,
            'max_drawdown_pct': 999,
            'win_rate': 0,
            'trade_count': 0,
        }


def grid_search():
    """网格搜索"""
    print("=" * 70)
    print("  AI V2 参数网格搜索")
    print("=" * 70)

    prices = generate_synthetic_data(600, 42)
    print(f"\n数据: {len(prices)} 天, 价格 {prices['close'].min():.2f} ~ {prices['close'].max():.2f}")

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

    # 搜索空间（关键参数）
    search_space = {
        'fusion_base_rule_weight': [0.45, 0.55, 0.65],
        'fusion_trend_sensitivity': [0.15, 0.25, 0.35],
        'fusion_vol_sensitivity': [0.15, 0.25, 0.35],
        'min_ml_confidence': [0.05, 0.1, 0.15],
        'train_window': [150, 200, 250],
    }

    keys = list(search_space.keys())
    values = list(search_space.values())
    total = 1
    for v in values:
        total *= len(v)

    print(f"\n搜索空间: {total} 种组合")
    print(f"参数: {keys}")

    results = []
    for i, combo in enumerate(product(*values)):
        params = dict(zip(keys, combo))
        params.update({
            'label_lookahead': 7,
            'retrain_interval': 30,
            'base_rule_weight': 0.3,
            'fusion_volume_sensitivity': 0.2,
            'fusion_duration_sensitivity': 0.25,
        })

        print(f"\n[{i+1}/{total}] 测试: {params}")
        metrics = run_backtest(prices, params)
        print(f"  收益: {metrics['total_return_pct']:.2f}%, 夏普: {metrics['sharpe_ratio']:.3f}, "
              f"回撤: {metrics['max_drawdown_pct']:.2f}%, 交易: {metrics['trade_count']}")

        results.append({
            'params': params,
            'metrics': metrics,
        })

    # 排序：优先收益率，其次夏普
    results.sort(key=lambda x: (x['metrics']['trade_count'] == 0, -x['metrics']['total_return_pct'], -x['metrics']['sharpe_ratio']))

    print(f"\n{'=' * 70}")
    print("  TOP 5 结果")
    print(f"{'=' * 70}")

    for i, r in enumerate(results[:5], 1):
        m = r['metrics']
        p = r['params']
        print(f"\n{i}. 收益: {m['total_return_pct']:.2f}%, 夏普: {m['sharpe_ratio']:.3f}, "
              f"回撤: {m['max_drawdown_pct']:.2f}%, 交易: {m['trade_count']}")
        print(f"   参数: base_rule={p['fusion_base_rule_weight']:.2f}, "
              f"trend_sens={p['fusion_trend_sensitivity']:.2f}, "
              f"vol_sens={p['fusion_vol_sensitivity']:.2f}, "
              f"min_conf={p['min_ml_confidence']:.2f}, "
              f"window={p['train_window']}")

    # 保存
    os.makedirs('ml/optimization_results', exist_ok=True)
    out_file = f"ml/optimization_results/grid_search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'search_space': {k: list(v) for k, v in search_space.items()},
            'results': results,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n结果保存: {out_file}")

    return results[0] if results else None


if __name__ == '__main__':
    grid_search()
