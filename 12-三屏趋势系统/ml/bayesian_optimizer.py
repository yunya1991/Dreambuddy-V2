"""贝叶斯参数优化器

使用 Optuna 对 AI V2 策略的核心参数进行贝叶斯优化，
目标：最大化回测夏普比率，同时约束最大回撤。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import numpy as np
import pandas as pd
import optuna
from optuna.samplers import TPESampler
from typing import Dict, Any, Optional
from datetime import datetime

from ml.lr_feature_engineer import LeastResistanceFeatureEngineer
from ml.lr_ml_strategy_v2 import LeastResistanceAIStrategyV2
from ml.multitask_model import DynamicWeightFusion
from backtest.engine import BacktestEngine


def generate_synthetic_data(n_days: int = 600, seed: int = 42) -> pd.DataFrame:
    """生成合成数据用于回测"""
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


def backtest_with_params(
    prices: pd.DataFrame,
    params: Dict[str, float],
    fundamental_data: Optional[Dict] = None,
) -> Dict[str, float]:
    """使用给定参数运行回测

    返回:
        {'total_return_pct', 'sharpe_ratio', 'max_drawdown_pct', 'win_rate', 'trade_count'}
    """
    strategy = LeastResistanceAIStrategyV2(
        label_lookahead=int(params.get('label_lookahead', 7)),
        train_window=int(params.get('train_window', 200)),
        retrain_interval=int(params.get('retrain_interval', 30)),
        min_ml_confidence=params.get('min_ml_confidence', 0.1),
        min_train_samples=int(params.get('min_train_samples', 40)),
        enable_fundamental=params.get('enable_fundamental', True),
        enable_multitask=params.get('enable_multitask', True),
        enable_dynamic_weight=params.get('enable_dynamic_weight', True),
        enable_feature_selection=params.get('enable_feature_selection', False),
        top_k_features=int(params.get('top_k_features', 40)),
        base_rule_weight=params.get('base_rule_weight', 0.3),
        fundamental_data=fundamental_data,
    )

    # 覆盖动态权重参数
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
        print(f"  [ERROR] 回测失败: {e}")
        return {
            'total_return_pct': -999,
            'sharpe_ratio': -999,
            'max_drawdown_pct': 999,
            'win_rate': 0,
            'trade_count': 0,
        }


def create_objective(prices: pd.DataFrame, fundamental_data: Optional[Dict] = None):
    """创建 Optuna 目标函数"""

    def objective(trial: optuna.Trial) -> float:
        """优化目标：最大化夏普比率，惩罚大回撤"""

        # 动态融合权重参数
        params = {
            # 融合参数
            'fusion_base_rule_weight': trial.suggest_float('fusion_base_rule_weight', 0.3, 0.7),
            'fusion_trend_sensitivity': trial.suggest_float('fusion_trend_sensitivity', 0.0, 0.5),
            'fusion_vol_sensitivity': trial.suggest_float('fusion_vol_sensitivity', 0.0, 0.5),
            'fusion_volume_sensitivity': trial.suggest_float('fusion_volume_sensitivity', 0.0, 0.5),
            'fusion_duration_sensitivity': trial.suggest_float('fusion_duration_sensitivity', 0.0, 0.5),

            # 策略参数
            'min_ml_confidence': trial.suggest_float('min_ml_confidence', 0.05, 0.3),
            'train_window': trial.suggest_int('train_window', 100, 300, step=50),
            'label_lookahead': trial.suggest_int('label_lookahead', 5, 14),
            'base_rule_weight': trial.suggest_float('base_rule_weight', 0.2, 0.5),

            # 固定参数
            'retrain_interval': 30,
            'min_train_samples': 40,
            'enable_fundamental': True,
            'enable_multitask': True,
            'enable_dynamic_weight': True,
            'enable_feature_selection': False,
            'top_k_features': 40,
        }

        # 运行回测
        result = backtest_with_params(prices, params, fundamental_data)

        # 优化目标：收益率为主，兼顾夏普，惩罚大回撤和零交易
        total_ret = result['total_return_pct']
        sharpe = result['sharpe_ratio']
        max_dd = result['max_drawdown_pct']
        trade_count = result['trade_count']

        # 如果回测失败
        if total_ret < -500:
            return -100.0

        # 零交易或极少交易给予重罚
        if trade_count == 0:
            return -50.0
        if trade_count < 3:
            trade_penalty = (3 - trade_count) * 10
        else:
            trade_penalty = 0

        # 惩罚大回撤
        dd_penalty = max(0, (max_dd - 15) * 0.5)

        # 综合得分：收益率权重 60%，夏普 40%
        score = total_ret * 0.6 + sharpe * 4 - dd_penalty - trade_penalty

        # 记录中间结果
        trial.set_user_attr('total_return_pct', result['total_return_pct'])
        trial.set_user_attr('sharpe_ratio', result['sharpe_ratio'])
        trial.set_user_attr('max_drawdown_pct', result['max_drawdown_pct'])
        trial.set_user_attr('win_rate', result['win_rate'])
        trial.set_user_attr('trade_count', result['trade_count'])

        return score

    return objective


def run_optimization(
    n_trials: int = 50,
    n_days: int = 600,
    seed: int = 42,
    output_dir: str = "ml/optimization_results",
) -> Dict[str, Any]:
    """运行贝叶斯优化

    参数:
        n_trials: 优化迭代次数
        n_days: 回测数据天数
        seed: 随机种子
        output_dir: 输出目录

    返回:
        最优参数和结果
    """
    print("=" * 60)
    print("  AI V2 贝叶斯参数优化")
    print("=" * 60)
    print(f"\n优化设置:")
    print(f"  迭代次数: {n_trials}")
    print(f"  回测数据: {n_days} 天")
    print(f"  随机种子: {seed}")

    # 生成数据
    print(f"\n1. 生成合成数据 ({n_days} 天)...")
    prices = generate_synthetic_data(n_days, seed)
    print(f"   价格范围: {prices['close'].min():.2f} ~ {prices['close'].max():.2f}")

    # 模拟基本面数据
    fundamental_data = {
        'screen1': {
            'composite_score': 65.0,
            'momentum_score': 70.0,
            'value_score': 60.0,
            'growth_score': 65.0,
            'quality_score': 68.0,
            'sentiment_score': 55.0,
        },
        'fundamental_9': {
            'pe_ttm': 15.0,
            'pb': 2.0,
            'roe': 12.0,
            'revenue_growth': 20.0,
            'profit_growth': 18.0,
            'debt_ratio': 45.0,
            'cash_ratio': 30.0,
            'gross_margin': 35.0,
            'net_margin': 15.0,
        }
    }

    # 创建优化器
    print(f"\n2. 启动贝叶斯优化 (Optuna TPE)...")
    sampler = TPESampler(seed=seed, n_startup_trials=10)
    study = optuna.create_study(
        direction='maximize',
        sampler=sampler,
        study_name='ai_v2_param_optimization',
    )

    # 运行优化
    objective = create_objective(prices, fundamental_data)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    # 最优结果
    best_trial = study.best_trial
    best_params = best_trial.params

    print(f"\n{'=' * 60}")
    print("  优化完成")
    print(f"{'=' * 60}")
    print(f"\n最优参数 (Trial #{best_trial.number}):")
    print(f"  综合得分: {best_trial.value:.4f}")
    print(f"  夏普比率: {best_trial.user_attrs.get('sharpe_ratio', 'N/A')}")
    print(f"  总收益率: {best_trial.user_attrs.get('total_return_pct', 'N/A')}%")
    print(f"  最大回撤: {best_trial.user_attrs.get('max_drawdown_pct', 'N/A')}%")
    print(f"  胜率: {best_trial.user_attrs.get('win_rate', 'N/A')}%")
    print(f"  交易次数: {best_trial.user_attrs.get('trade_count', 'N/A')}")

    print(f"\n参数详情:")
    for k, v in best_params.items():
        print(f"  {k}: {v}")

    # 保存结果
    os.makedirs(output_dir, exist_ok=True)
    result_file = os.path.join(output_dir, f"optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    result_data = {
        'timestamp': datetime.now().isoformat(),
        'n_trials': n_trials,
        'n_days': n_days,
        'seed': seed,
        'best_trial': {
            'number': best_trial.number,
            'score': best_trial.value,
            'params': best_params,
            'metrics': {
                'total_return_pct': best_trial.user_attrs.get('total_return_pct', 0),
                'sharpe_ratio': best_trial.user_attrs.get('sharpe_ratio', -999),
                'max_drawdown_pct': best_trial.user_attrs.get('max_drawdown_pct', 999),
                'win_rate': best_trial.user_attrs.get('win_rate', 0),
                'trade_count': best_trial.user_attrs.get('trade_count', 0),
            }
        },
        'all_trials': [
            {
                'number': t.number,
                'score': t.value,
                'params': t.params,
                'metrics': {
                    'total_return_pct': t.user_attrs.get('total_return_pct', 0),
                    'sharpe_ratio': t.user_attrs.get('sharpe_ratio', -999),
                    'max_drawdown_pct': t.user_attrs.get('max_drawdown_pct', 999),
                    'win_rate': t.user_attrs.get('win_rate', 0),
                    'trade_count': t.user_attrs.get('trade_count', 0),
                }
            }
            for t in study.trials
        ]
    }

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)

    print(f"\n结果已保存: {result_file}")

    return result_data


def apply_best_params(config_file: str, best_params: Dict[str, Any]) -> None:
    """将最优参数应用到配置文件"""
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 更新动态融合权重参数
    config['dynamic_weight_fusion']['base_rule_weight'] = best_params.get('fusion_base_rule_weight', config['dynamic_weight_fusion']['base_rule_weight'])
    config['dynamic_weight_fusion']['trend_sensitivity'] = best_params.get('fusion_trend_sensitivity', config['dynamic_weight_fusion']['trend_sensitivity'])
    config['dynamic_weight_fusion']['vol_sensitivity'] = best_params.get('fusion_vol_sensitivity', config['dynamic_weight_fusion']['vol_sensitivity'])
    config['dynamic_weight_fusion']['volume_sensitivity'] = best_params.get('fusion_volume_sensitivity', config['dynamic_weight_fusion']['volume_sensitivity'])
    config['dynamic_weight_fusion']['duration_sensitivity'] = best_params.get('fusion_duration_sensitivity', config['dynamic_weight_fusion']['duration_sensitivity'])

    # 更新策略参数
    config['strategy_params']['min_ml_confidence'] = best_params.get('min_ml_confidence', config['strategy_params']['min_ml_confidence'])
    config['strategy_params']['train_window'] = int(best_params.get('train_window', config['strategy_params']['train_window']))
    config['strategy_params']['label_lookahead'] = int(best_params.get('label_lookahead', config['strategy_params']['label_lookahead']))
    config['strategy_params']['base_rule_weight'] = best_params.get('base_rule_weight', config['strategy_params']['base_rule_weight'])

    # 更新版本信息
    config['version'] = 'v2.1.0-optimized'
    config['optimized_at'] = datetime.now().isoformat()

    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"参数已应用到: {config_file}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='AI V2 贝叶斯参数优化')
    parser.add_argument('--trials', type=int, default=30, help='优化迭代次数')
    parser.add_argument('--days', type=int, default=600, help='回测数据天数')
    parser.add_argument('--seed', type=int, default=42, help='随机种子')
    parser.add_argument('--apply', action='store_true', help='应用最优参数到配置文件')
    args = parser.parse_args()

    # 运行优化
    result = run_optimization(
        n_trials=args.trials,
        n_days=args.days,
        seed=args.seed,
    )

    # 应用最优参数
    if args.apply:
        best_params = result['best_trial']['params']
        apply_best_params('ml/baseline_config.json', best_params)


if __name__ == '__main__':
    main()
