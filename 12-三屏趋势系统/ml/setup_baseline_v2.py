"""设置基线模型 v2 - 严格的样本外验证

修复数据泄漏问题：
- 训练集：前 60% 数据
- 测试集：后 40% 数据（样本外，模型从未见过）
- 基线模型只用训练集数据训练
- 回测只在测试集上评估，确保结果真实可信
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
    BacktestResult,
    TrendScreenStrategy,
    BuyAndHoldStrategy,
    fetch_historical_data,
)


def feature_selection(X_train, y_train, model_type='lightgbm', top_k=25):
    """基于特征重要性的特征选择（只用训练集）"""
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


def run_backtest(df, strategy, name):
    """运行回测"""
    engine = BacktestEngine(initial_capital=10000, commission=0.001)
    signals = strategy.generate_signals(df)
    result = engine.run(df["close"], signals, symbol=name)
    return BacktestResult(result)


def setup_baseline_v2():
    """设置基线模型 v2 - 严格样本外验证"""

    print("=" * 80)
    print("  设置基线模型 v2 - 严格样本外验证")
    print("  修复数据泄漏：训练集/测试集严格分离")
    print("=" * 80)

    # 1. 获取数据
    print("\n[1/8] 获取数据...")
    df = fetch_historical_data("BTC-USDT", "1D", limit=300)
    print(f"  总数据: {len(df)} 天")
    print(f"  时间范围: {df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}")
    print(f"  区间涨跌: {(df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100:.2f}%")

    # 2. 分割训练集/测试集
    print("\n[2/8] 分割训练集/测试集 (60%/40%)...")
    split_idx = int(len(df) * 0.6)
    df_train = df.iloc[:split_idx].copy().reset_index(drop=True)
    df_test = df.iloc[split_idx:].copy().reset_index(drop=True)

    print(f"  训练集: {len(df_train)} 天 ({df_train['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df_train['date'].iloc[-1].strftime('%Y-%m-%d')})")
    print(f"    涨跌: {(df_train['close'].iloc[-1] / df_train['close'].iloc[0] - 1) * 100:.2f}%")
    print(f"  测试集: {len(df_test)} 天 ({df_test['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df_test['date'].iloc[-1].strftime('%Y-%m-%d')})")
    print(f"    涨跌: {(df_test['close'].iloc[-1] / df_test['close'].iloc[0] - 1) * 100:.2f}%")

    # 3. 训练集上做特征工程
    print("\n[3/8] 训练集特征工程...")
    fe = TrendFeatureEngineer(views=['direction', 'change', 'velocity', 'power', 'hierarchy'])
    train_features = fe.create_features(df_train, label_lookahead=7)
    train_valid = fe.get_valid_data(train_features)
    X_train_full = train_valid[fe.feature_names]
    y_train = train_valid['label']
    print(f"  有效训练样本: {len(X_train_full)}, 特征数: {len(fe.feature_names)}")

    # 4. 训练集上做特征选择
    print("\n[4/8] 训练集特征选择 (Top 25)...")
    selected_features = feature_selection(X_train_full, y_train, top_k=25)
    X_train = X_train_full[selected_features]

    # 5. 训练集上做超参调优（Walk-Forward）
    print("\n[5/8] 训练集超参调优 (Walk-Forward)...")
    tuner = ModelTuner(
        model_type='lightgbm',
        metric='roc_auc',
        n_trials=30,
        train_window=int(len(X_train) * 0.5),
        test_window=int(len(X_train) * 0.2),
        step_size=int(len(X_train) * 0.1),
    )
    result = tuner.tune(X_train, y_train)
    best_params = result['best_params']
    best_score = result['best_score']
    print(f"  训练集Walk-Forward最佳AUC: {best_score:.4f}")
    print(f"  最佳参数: {best_params}")

    # 6. 用全部训练集训练最终模型
    print("\n[6/8] 训练最终模型（仅用训练集）...")
    final_model = create_model('lightgbm', best_params)
    final_model.fit(X_train, y_train)

    # 训练集上的表现（用于对比过拟合）
    train_preds = final_model.predict_proba(X_train)
    from sklearn.metrics import roc_auc_score, accuracy_score
    train_auc = roc_auc_score(y_train.values, train_preds)
    train_acc = accuracy_score(y_train.values, (train_preds > 0.5).astype(int))
    print(f"  训练集AUC: {train_auc:.4f}, 准确率: {train_acc:.4f}")

    # 7. 测试集上验证（样本外！）
    print("\n[7/8] 测试集验证（样本外）...")
    fe_test = TrendFeatureEngineer(views=['direction', 'change', 'velocity', 'power', 'hierarchy'])
    fe_test.feature_names = selected_features

    # 测试集特征
    test_features = fe_test.create_features(df_test, label_lookahead=7)
    test_valid = fe_test.get_valid_data(test_features)
    if len(test_valid) > 0:
        X_test = test_valid[selected_features]
        y_test = test_valid['label']
        test_preds = final_model.predict_proba(X_test)
        test_auc = roc_auc_score(y_test.values, test_preds)
        test_acc = accuracy_score(y_test.values, (test_preds > 0.5).astype(int))
        print(f"  测试集AUC: {test_auc:.4f}, 准确率: {test_acc:.4f}")
        print(f"  过拟合gap (准确率): {train_acc - test_acc:.4f}")
    else:
        test_auc = 0.5
        test_acc = 0.5
        print("  测试集有效样本不足，跳过AUC验证")

    # 8. 保存基线模型 + 测试集回测
    print("\n[8/8] 保存基线模型并回测验证...")
    models_dir = os.path.join(os.path.dirname(__file__), 'models')
    vm = ModelVersionManager(models_dir)

    performance = {
        'train_roc_auc': float(train_auc),
        'train_accuracy': float(train_acc),
        'test_roc_auc': float(test_auc),
        'test_accuracy': float(test_acc),
        'walk_forward_roc_auc': float(best_score),
        'overfit_gap_accuracy': float(train_acc - test_acc),
        'num_features': len(selected_features),
    }

    train_date_range = (
        df_train['date'].iloc[0].strftime('%Y-%m-%d'),
        df_train['date'].iloc[-1].strftime('%Y-%m-%d'),
    )

    feature_engineer_config = {
        'views': ['direction', 'change', 'velocity', 'power', 'hierarchy'],
        'label_lookahead': 7,
        'selected_features': selected_features,
    }

    metadata = {
        'description': '基线模型 v2 - 严格样本外验证，修复数据泄漏',
        'trend_theory': '方向 + 变化方向 + 变化速率 + Elder-ray力量 + 多尺度层级',
        'data_source': 'BTC-USDT 日线 300天',
        'validation_method': '训练集Walk-Forward调优 + 测试集样本外验证',
        'train_test_split': '60%/40%',
    }

    version_id = vm.save_version(
        model=final_model,
        performance=performance,
        train_date_range=train_date_range,
        feature_engineer_config=feature_engineer_config,
        metadata=metadata,
    )

    # 设置为基线
    vm.promote(version_id)
    vm.set_baseline(version_id)
    vm.print_status()

    # 测试集上的策略回测（这才是真实的样本外表现）
    print("\n" + "=" * 80)
    print("  测试集策略回测对比（样本外，真实可信）")
    print("=" * 80)

    base_strategy = TrendScreenStrategy()
    baseline_ml = MLTrendStrategy(
        base_strategy=base_strategy,
        model=final_model,
        feature_engineer=fe_test,
        ml_confidence_weight=0.3,
        min_ml_confidence=0.55,
        label_lookahead=7,
        warmup_periods=30,  # 测试集短，减少预热期
    )

    results = {}
    results['Buy&Hold'] = run_backtest(df_test, BuyAndHoldStrategy(), "B&H")
    results['传统三屏'] = run_backtest(df_test, TrendScreenStrategy(), "TrendScreen")
    results['ML+Trend(基线)'] = run_backtest(df_test, baseline_ml, "ML_Trend_Baseline")

    print(f"\n  {'策略':<18} {'收益':>8} {'夏普':>6} {'回撤':>8} {'胜率':>6} {'盈亏比':>6} {'交易数':>6}")
    print("  " + "-" * 70)
    for name, r in results.items():
        m = r.metrics
        print(f"  {name:<18} {m.get('total_return_pct', 0):>7.2f}% {m.get('sharpe_ratio', 0):>6.2f} "
              f"{m.get('max_drawdown_pct', 0):>7.2f}% {m.get('win_rate_pct', 0):>5.1f}% "
              f"{m.get('profit_factor', 0):>6.2f} {m.get('total_trades', 0):>6.0f}")

    # 记录测试集性能
    ml_metrics = results['ML+Trend(基线)'].metrics
    vm.log_performance(
        version_id=version_id,
        period="test_set_out_of_sample",
        performance={
            'total_return_pct': ml_metrics.get('total_return_pct', 0),
            'sharpe_ratio': ml_metrics.get('sharpe_ratio', 0),
            'max_drawdown_pct': ml_metrics.get('max_drawdown_pct', 0),
            'win_rate_pct': ml_metrics.get('win_rate_pct', 0),
            'profit_factor': ml_metrics.get('profit_factor', 0),
        },
        date_range=(
            df_test['date'].iloc[0].strftime('%Y-%m-%d'),
            df_test['date'].iloc[-1].strftime('%Y-%m-%d'),
        ),
    )

    # 更新元数据
    meta = vm.get_version_meta(version_id)
    if meta:
        meta['metadata']['test_backtest_return'] = f"{ml_metrics.get('total_return_pct', 0):.2f}%"
        meta['metadata']['test_backtest_sharpe'] = f"{ml_metrics.get('sharpe_ratio', 0):.2f}"
        meta['metadata']['test_backtest_max_dd'] = f"{ml_metrics.get('max_drawdown_pct', 0):.2f}%"
        version_dir = os.path.join(models_dir, 'versions', version_id)
        with open(os.path.join(version_dir, 'meta.json'), 'w') as f:
            import json
            json.dump(meta, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print(f"  基线模型 {version_id} 设置完成!")
    print("=" * 80)
    print("\n重要说明:")
    print("  - 之前 72% 的收益是数据泄漏导致的虚高（全量数据训练+全量数据回测）")
    print("  - 当前基线模型严格分离训练/测试集，测试集结果真实可信")
    print("  - 测试集样本量较小（约120天），后续需要更多数据验证")
    print(f"\n模型保存在: {models_dir}")

    return version_id, vm


if __name__ == '__main__':
    setup_baseline_v2()
