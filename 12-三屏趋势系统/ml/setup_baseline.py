"""设置基线模型并保存

将当前调优后的模型保存为v1基线版本，用于后续回退参考。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from ml.feature_engineer import TrendFeatureEngineer
from ml.models import create_model
from ml.tuner import ModelTuner
from ml.version_manager import ModelVersionManager
from ml.ml_strategy import MLTrendStrategy
from backtest import (
    BacktestEngine,
    BaseStrategy,
    TrendScreenStrategy,
    fetch_historical_data,
)


def feature_selection(X_train, y_train, model_type='lightgbm', top_k=25):
    """基于特征重要性的特征选择"""
    fs_params = {
        'n_estimators': 100,
        'early_stopping_rounds': None,
        'verbose': -1,
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.9,
        'lambda_l1': 0.1,
        'lambda_l2': 0.1,
        'min_data_in_leaf': 10,
    }
    model = create_model(model_type, fs_params)
    model.fit(X_train, y_train)
    importance = model.feature_importance()

    if len(importance) == 0 or importance.sum() == 0:
        print("  [警告] 特征重要性全为0，使用皮尔逊相关系数选择特征")
        correlations = []
        for col in X_train.columns:
            corr = abs(np.corrcoef(X_train[col].values, y_train.values)[0, 1])
            if np.isnan(corr):
                corr = 0
            correlations.append((col, corr))
        correlations.sort(key=lambda x: x[1], reverse=True)
        top_features = [c[0] for c in correlations[:top_k]]
        return top_features

    top_features = importance.head(top_k).index.tolist()
    print(f"  从 {len(X_train.columns)} → {len(top_features)} 个特征")
    return top_features


def run_tuning_and_save_baseline():
    """运行调优并保存基线模型"""

    print("=" * 70)
    print("  设置基线模型 v1")
    print("  基于趋势延续理论的ML增强三屏策略")
    print("=" * 70)

    # 1. 获取数据
    print("\n[1/6] 获取数据...")
    df = fetch_historical_data("BTC-USDT", "1D", limit=300)
    print(f"  数据量: {len(df)} 天")
    print(f"  时间范围: {df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}")

    # 2. 特征工程
    print("\n[2/6] 特征工程...")
    fe = TrendFeatureEngineer(views=['direction', 'change', 'velocity', 'power', 'hierarchy'])
    features_df = fe.create_features(df, label_lookahead=7)
    valid_data = fe.get_valid_data(features_df)

    X = valid_data[fe.feature_names]
    y = valid_data['label']
    print(f"  有效样本: {len(X)}, 特征数: {len(fe.feature_names)}")

    # 3. 特征选择
    print("\n[3/6] 特征选择 (Top 25)...")
    selected_features = feature_selection(X, y, model_type='lightgbm', top_k=25)
    X_sel = X[selected_features]

    # 更新特征工程师的特征列表
    fe_selected = TrendFeatureEngineer(views=['direction', 'change', 'velocity', 'power', 'hierarchy'])
    fe_selected.feature_names = selected_features

    # 4. 超参调优
    print("\n[4/6] 超参调优 (Walk-Forward + Optuna)...")
    tuner = ModelTuner(
        model_type='lightgbm',
        metric='roc_auc',
        n_trials=30,
        train_window=120,
        test_window=36,
        step_size=24,
    )
    result = tuner.tune(X_sel, y)
    best_params = result['best_params']
    best_score = result['best_score']
    print(f"  最佳AUC: {best_score:.4f}")
    print(f"  最佳参数: {best_params}")

    # 5. 训练最终模型
    print("\n[5/6] 训练最终模型...")
    final_model = create_model('lightgbm', best_params)
    final_model.fit(X_sel, y)
    print(f"  训练完成，特征数: {len(final_model.feature_names)}")

    # 6. 保存为基线版本
    print("\n[6/6] 保存基线模型...")
    models_dir = os.path.join(os.path.dirname(__file__), 'models')
    vm = ModelVersionManager(models_dir)

    # 计算训练集性能
    train_preds = final_model.predict_proba(X_sel)
    from sklearn.metrics import roc_auc_score, accuracy_score
    train_auc = roc_auc_score(y.values, train_preds)
    train_acc = accuracy_score(y.values, (train_preds > 0.5).astype(int))

    performance = {
        'roc_auc': float(best_score),
        'accuracy': float(train_acc),
        'train_roc_auc': float(train_auc),
        'num_features': len(selected_features),
    }

    train_date_range = (
        df['date'].iloc[0].strftime('%Y-%m-%d'),
        df['date'].iloc[-1].strftime('%Y-%m-%d'),
    )

    feature_engineer_config = {
        'views': ['direction', 'change', 'velocity', 'power', 'hierarchy'],
        'label_lookahead': 7,
        'selected_features': selected_features,
    }

    metadata = {
        'description': '基线模型 v1 - 基于趋势延续理论的五维特征工程',
        'trend_theory': '方向 + 变化方向 + 变化速率 + Elder-ray力量 + 多尺度层级',
        'data_source': 'BTC-USDT 日线 300天',
        'validation_method': 'Walk-Forward (120/36/24)',
    }

    version_id = vm.save_version(
        model=final_model,
        performance=performance,
        train_date_range=train_date_range,
        feature_engineer_config=feature_engineer_config,
        metadata=metadata,
    )

    # 设置为当前版本和基线版本
    vm.promote(version_id)
    vm.set_baseline(version_id)

    # 打印状态
    vm.print_status()

    # 7. 策略回测验证
    print("\n" + "=" * 70)
    print("  基线模型策略回测验证")
    print("=" * 70)

    base_strategy = TrendScreenStrategy()

    baseline_strategy = MLTrendStrategy(
        base_strategy=base_strategy,
        model=final_model,
        feature_engineer=fe_selected,
        ml_confidence_weight=0.3,
        min_ml_confidence=0.55,
        label_lookahead=7,
        warmup_periods=100,
    )

    engine = BacktestEngine(initial_capital=10000, commission=0.001)
    result = engine.run(df, baseline_strategy)

    print(f"\n  基线策略回测结果:")
    print(f"    总收益: {result['total_return_pct']:.2f}%")
    print(f"    年化收益: {result['annualized_return_pct']:.2f}%")
    print(f"    夏普比率: {result['sharpe_ratio']:.2f}")
    print(f"    最大回撤: {result['max_drawdown_pct']:.2f}%")
    print(f"    胜率: {result['win_rate_pct']:.2f}%")
    print(f"    盈亏比: {result['profit_factor']:.2f}")
    print(f"    交易次数: {result['total_trades']}")

    # 更新元数据中的回测收益
    meta = vm.get_version_meta(version_id)
    if meta:
        meta['metadata']['backtest_return'] = f"{result['total_return_pct']:.2f}%"
        meta['metadata']['backtest_sharpe'] = f"{result['sharpe_ratio']:.2f}"
        meta['metadata']['backtest_max_drawdown'] = f"{result['max_drawdown_pct']:.2f}%"
        version_dir = os.path.join(models_dir, 'versions', version_id)
        with open(os.path.join(version_dir, 'meta.json'), 'w') as f:
            import json
            json.dump(meta, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print(f"  基线模型 {version_id} 设置完成!")
    print("=" * 70)
    print(f"\n模型保存在: {models_dir}")
    print(f"\n使用方式:")
    print(f"  from ml.version_manager import ModelVersionManager")
    print(f"  vm = ModelVersionManager('models')")
    print(f"  model = vm.load_baseline()  # 加载基线模型")
    print(f"  model = vm.load_current()   # 加载当前版本")
    print(f"  vm.rollback(to_baseline=True)  # 回退到基线")

    return version_id, vm


if __name__ == '__main__':
    run_tuning_and_save_baseline()
