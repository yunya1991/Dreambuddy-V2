"""模型调优实验

完整的认识-实践闭环调优流程：
1. 特征选择（基于特征重要性，减少过拟合）
2. Optuna超参搜索 + Walk-Forward交叉验证
3. 调优前后模型性能对比
4. 调优前后策略回测对比

理论指导：
- 过拟合防护：特征选择 + 正则化 + 滚动验证
- 趋势延续理论：特征必须可解释，符合趋势三要素
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional

from backtest import (
    BacktestEngine,
    BacktestResult,
    BuyAndHoldStrategy,
    TrendScreenStrategy,
    generate_sample_data,
    fetch_historical_data,
    compare_results,
    format_comparison_table,
)

from ml.feature_engineer import TrendFeatureEngineer
from ml.models import MLModel, create_model, LightGBMModel
from ml.tuner import ModelTuner
from ml.ml_strategy import MLTrendStrategy


def load_data(use_real: bool = True, symbol: str = "BTC-USDT",
              n_days: int = 500) -> pd.DataFrame:
    """加载数据"""
    if use_real:
        try:
            df = fetch_historical_data(symbol, "1D", n_days)
            if len(df) >= 200:
                print(f"[数据] 真实数据: {symbol} {len(df)} 天")
                return df
        except Exception as e:
            print(f"[数据] 真实数据获取失败: {e}，使用合成数据")
    df = generate_sample_data(n_days=n_days, start_price=100.0, volatility=0.02)
    print(f"[数据] 合成数据: {len(df)} 天")
    return df


def feature_selection(X_train: pd.DataFrame, y_train: pd.Series,
                      model_type: str = 'lightgbm',
                      top_k: int = 20) -> List[str]:
    """基于特征重要性的特征选择

    减少特征数量 = 降低过拟合风险
    使用较轻的正则化来获取有意义的特征重要性
    """
    # 用较温和的参数训练，确保特征重要性有意义
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
        # 回退方案：用与标签的相关系数绝对值排序
        correlations = []
        for col in X_train.columns:
            corr = abs(np.corrcoef(X_train[col].values, y_train.values)[0, 1])
            if np.isnan(corr):
                corr = 0
            correlations.append((col, corr))
        correlations.sort(key=lambda x: x[1], reverse=True)
        top_features = [c[0] for c in correlations[:top_k]]
        print(f"  Top 10 (按相关系数): {[f[0] for f in correlations[:10]]}")
        return top_features

    top_features = importance.head(top_k).index.tolist()
    print(f"[特征选择] 从 {len(X_train.columns)} → {len(top_features)} 个特征")
    print(f"  Top 10: {list(importance.head(10).index)}")
    return top_features


def walk_forward_evaluation(
    X: pd.DataFrame,
    y: pd.Series,
    model_type: str = 'lightgbm',
    params: Optional[Dict] = None,
    train_window: int = 180,
    test_window: int = 30,
    step_size: int = 30,
) -> Dict:
    """Walk-Forward模型性能评估

    返回多个窗口的平均指标，更接近实盘表现
    """
    n = len(X)
    if n <= train_window + test_window:
        return {'accuracy': 0.5, 'roc_auc': 0.5, 'n_folds': 0}

    from sklearn.metrics import accuracy_score, roc_auc_score

    accuracies = []
    roc_aucs = []
    fold_preds = []
    fold_y_true = []

    start = 0
    fold_idx = 0
    while start + train_window + test_window <= n:
        train_end = start + train_window
        test_end = min(train_end + test_window, n)

        X_train_fold = X.iloc[start:train_end]
        y_train_fold = y.iloc[start:train_end]
        X_test_fold = X.iloc[train_end:test_end]
        y_test_fold = y.iloc[train_end:test_end]

        if len(np.unique(y_train_fold)) < 2 or len(np.unique(y_test_fold)) < 2:
            start += step_size
            continue

        model = create_model(model_type, params or {})
        try:
            model.fit(X_train_fold, y_train_fold, X_test_fold, y_test_fold)
            preds_proba = model.predict_proba(X_test_fold)
            preds = (preds_proba > 0.5).astype(int)

            acc = accuracy_score(y_test_fold, preds)
            try:
                auc = roc_auc_score(y_test_fold, preds_proba)
            except Exception:
                auc = 0.5

            accuracies.append(acc)
            roc_aucs.append(auc)
            fold_preds.extend(preds_proba)
            fold_y_true.extend(y_test_fold.values)

            fold_idx += 1
        except Exception as e:
            pass

        start += step_size

    result = {
        'accuracy': np.mean(accuracies) if accuracies else 0.5,
        'roc_auc': np.mean(roc_aucs) if roc_aucs else 0.5,
        'n_folds': len(accuracies),
        'accuracy_std': np.std(accuracies) if accuracies else 0.0,
    }
    return result


def run_tuning_experiment(
    df: pd.DataFrame,
    model_type: str = 'lightgbm',
    label_lookahead: int = 7,
    n_trials: int = 30,
    use_feature_selection: bool = True,
    top_k_features: int = 25,
) -> Dict:
    """运行完整调优实验

    返回: 调优前后对比结果
    """
    print("\n" + "=" * 70)
    print("  模型调优实验")
    print("=" * 70)

    # 1. 特征工程
    print("\n[1/6] 特征工程...")
    fe = TrendFeatureEngineer()
    features_df = fe.create_features(df, label_lookahead=label_lookahead)
    valid = fe.get_valid_data(features_df)
    feature_names = fe.get_feature_names()
    print(f"  有效样本: {len(valid)}, 特征数: {len(feature_names)}")

    # 调整窗口以适应数据量
    n = len(valid)
    if n < 250:
        train_window = int(n * 0.5)
        test_window = int(n * 0.15)
        step_size = int(n * 0.1)
    else:
        train_window = 180
        test_window = 30
        step_size = 30
    print(f"  Walk-Forward窗口: train={train_window}, test={test_window}, step={step_size}")

    X = valid[feature_names]
    y = valid['label']

    # 2. 基准模型（默认参数，禁用early stopping避免训练不足）
    print("\n[2/6] 基准模型评估（默认参数，全部特征）...")
    default_params = {
        'n_estimators': 100,
        'early_stopping_rounds': None,
        'verbose': -1,
    }
    baseline_result = walk_forward_evaluation(
        X, y, model_type=model_type,
        params=default_params,
        train_window=train_window, test_window=test_window, step_size=step_size
    )
    print(f"  准确率: {baseline_result['accuracy']:.4f} ± {baseline_result['accuracy_std']:.4f}")
    print(f"  ROC-AUC: {baseline_result['roc_auc']:.4f}")
    print(f"  验证折数: {baseline_result['n_folds']}")

    # 训练集过拟合检测
    train_size = int(n * 0.6)
    X_train_full = X.iloc[:train_size]
    y_train_full = y.iloc[:train_size]
    X_test_full = X.iloc[train_size:]
    y_test_full = y.iloc[train_size:]

    model_check = create_model(model_type, default_params)
    model_check.fit(X_train_full, y_train_full)
    from sklearn.metrics import accuracy_score, roc_auc_score
    train_pred = model_check.predict_proba(X_train_full)
    test_pred = model_check.predict_proba(X_test_full)
    train_acc = accuracy_score(y_train_full, train_pred > 0.5)
    test_acc = accuracy_score(y_test_full, test_pred > 0.5)
    print(f"  过拟合检测: 训练集准确率={train_acc:.4f}, 测试集准确率={test_acc:.4f}, gap={train_acc-test_acc:.4f}")

    # 3. 特征选择
    selected_features = feature_names
    fs_baseline_result = None
    if use_feature_selection:
        print(f"\n[3/6] 特征选择（Top {top_k_features}）...")
        selected_features = feature_selection(
            X_train_full, y_train_full,
            model_type=model_type, top_k=top_k_features
        )

        # 特征选择后的基准
        print(f"  特征选择后模型评估...")
        fs_baseline_result = walk_forward_evaluation(
            X[selected_features], y, model_type=model_type,
            params=default_params,
            train_window=train_window, test_window=test_window, step_size=step_size
        )
        print(f"  准确率: {fs_baseline_result['accuracy']:.4f} ± {fs_baseline_result['accuracy_std']:.4f}")
        print(f"  ROC-AUC: {fs_baseline_result['roc_auc']:.4f}")

    # 4. Optuna超参调优
    print(f"\n[4/6] Optuna超参调优（{n_trials} 次试验）...")
    X_tune = X[selected_features]

    tuner = ModelTuner(
        model_type=model_type,
        n_trials=n_trials,
        direction='maximize',
        metric='roc_auc',
        train_window=train_window,
        test_window=test_window,
        step_size=step_size,
    )
    # 覆盖默认参数，禁用early_stopping
    tuner._default_params_override = default_params

    tune_result = tuner.tune(X_tune, y)
    print(f"  最佳 ROC-AUC: {tune_result['best_score']:.4f}")
    print(f"  最佳参数:")
    for k, v in tune_result['best_params'].items():
        if k not in ['n_estimators', 'early_stopping_rounds', 'verbose', 'objective', 'metric', 'boosting_type', 'random_state']:
            print(f"    {k}: {v}")

    # 5. 调优后模型评估
    print("\n[5/6] 调优后模型 Walk-Forward 评估...")
    best_params = dict(tuner.best_params)
    best_params['n_estimators'] = 100
    best_params['early_stopping_rounds'] = None
    best_params['verbose'] = -1

    tuned_result = walk_forward_evaluation(
        X_tune, y, model_type=model_type,
        params=best_params,
        train_window=train_window, test_window=test_window, step_size=step_size
    )
    print(f"  准确率: {tuned_result['accuracy']:.4f} ± {tuned_result['accuracy_std']:.4f}")
    print(f"  ROC-AUC: {tuned_result['roc_auc']:.4f}")
    print(f"  验证折数: {tuned_result['n_folds']}")

    # 调优后过拟合检测
    model_tuned = create_model(model_type, best_params)
    model_tuned.fit(X_train_full[selected_features], y_train_full)
    train_pred_t = model_tuned.predict_proba(X_train_full[selected_features])
    test_pred_t = model_tuned.predict_proba(X_test_full[selected_features])
    train_acc_t = accuracy_score(y_train_full, train_pred_t > 0.5)
    test_acc_t = accuracy_score(y_test_full, test_pred_t > 0.5)
    print(f"  调优后过拟合检测: 训练集={train_acc_t:.4f}, 测试集={test_acc_t:.4f}, gap={train_acc_t-test_acc_t:.4f}")

    # 6. 训练最终模型（用全部训练数据）
    print("\n[6/6] 训练最终模型（全部训练数据）...")
    final_model = create_model(model_type, best_params)
    final_model.fit(X[selected_features], y)

    # 汇总对比
    print("\n" + "=" * 70)
    print("  调优前后对比")
    print("=" * 70)
    print(f"{'指标':<20} {'基准(默认)':>12} {'特征选择':>12} {'调优后':>12}")
    print("-" * 70)
    fs_acc = fs_baseline_result['accuracy'] if fs_baseline_result else 0
    fs_auc = fs_baseline_result['roc_auc'] if fs_baseline_result else 0
    print(f"{'准确率':<20} {baseline_result['accuracy']:>12.4f} {fs_acc:>12.4f} {tuned_result['accuracy']:>12.4f}")
    print(f"{'ROC-AUC':<20} {baseline_result['roc_auc']:>12.4f} {fs_auc:>12.4f} {tuned_result['roc_auc']:>12.4f}")
    if baseline_result['accuracy'] > 0:
        acc_improve = (tuned_result['accuracy'] - baseline_result['accuracy']) / baseline_result['accuracy'] * 100
        auc_improve = (tuned_result['roc_auc'] - baseline_result['roc_auc']) / baseline_result['roc_auc'] * 100
        print(f"{'准确率提升':<20} {'':>12} {'':>12} {acc_improve:>+11.1f}%")
        print(f"{'AUC提升':<20} {'':>12} {'':>12} {auc_improve:>+11.1f}%")

    return {
        'feature_names': feature_names,
        'selected_features': selected_features,
        'best_params': best_params,
        'best_score': tune_result['best_score'],
        'baseline_result': baseline_result,
        'fs_baseline_result': fs_baseline_result,
        'tuned_result': tuned_result,
        'feature_engineer': fe,
        'final_model': final_model,
    }


def run_backtest_comparison(
    df: pd.DataFrame,
    tune_result: Dict,
    model_type: str = 'lightgbm',
    label_lookahead: int = 7,
) -> Dict:
    """策略回测对比：传统三屏 vs 默认ML vs 调优后ML"""
    print("\n" + "=" * 70)
    print("  策略回测对比")
    print("=" * 70)

    engine = BacktestEngine(
        initial_capital=10000.0,
        commission=0.0005,
        slippage=0.0005,
    )

    base_strategy = TrendScreenStrategy(min_confidence=45.0, update_step=7)

    # 用调优后的模型和特征创建策略
    selected_features = tune_result['selected_features']
    final_model = tune_result['final_model']
    fe = tune_result['feature_engineer']

    # 创建使用选定特征的feature engineer
    class SelectedFeatureEngineer:
        def __init__(self, base_fe, selected):
            self.base_fe = base_fe
            self.selected = selected
            self.feature_names = selected

        def create_features(self, df, label_lookahead=7):
            result = self.base_fe.create_features(df, label_lookahead)
            return result

        def get_valid_data(self, features_df):
            return features_df.dropna(subset=self.selected + ['label'])

        def get_feature_names(self):
            return self.selected

    sel_fe = SelectedFeatureEngineer(fe, selected_features)

    strategies = {
        "Buy&Hold": BuyAndHoldStrategy(),
        "TrendScreen": base_strategy,
        "ML+Trend (默认)": MLTrendStrategy(
            base_strategy=base_strategy,
            model_type=model_type,
            ml_confidence_weight=0.3,
            label_lookahead=label_lookahead,
            warmup_periods=100,
            train_ratio=0.5,
        ),
        "ML+Trend (调优)": MLTrendStrategy(
            base_strategy=base_strategy,
            model_type=model_type,
            model=final_model,
            feature_engineer=sel_fe,
            ml_confidence_weight=0.3,
            label_lookahead=label_lookahead,
            warmup_periods=100,
            train_ratio=0.5,
        ),
    }

    results = {}
    for name, strategy in strategies.items():
        print(f"\n运行 {name} ...")
        try:
            signals = strategy.generate_signals(df)
            result = engine.run(df["close"], signals, symbol=name)
            results[name] = BacktestResult(result)
            print(f"  收益: {results[name].total_return_pct:>8.2f}%  "
                  f"夏普: {results[name].sharpe_ratio:>6.2f}  "
                  f"回撤: {results[name].max_drawdown_pct:>7.2f}%  "
                  f"胜率: {results[name].win_rate_pct:>5.1f}%")
        except Exception as e:
            print(f"  失败: {e}")
            import traceback
            traceback.print_exc()

    if results:
        print("\n" + "=" * 70)
        print("  策略对比汇总")
        print("=" * 70)
        comp = compare_results(results)
        print(format_comparison_table(comp))

    return results


def main():
    print("\n" + "=" * 70)
    print("  Phase 3: 模型调优与认识-实践闭环")
    print("  理论基础：趋势延续三要素（方向 + 变化方向 + 变化速率）")
    print("  调优目标：解决过拟合，提升泛化能力")
    print("=" * 70)

    # 加载数据
    df = load_data(use_real=True, symbol="BTC-USDT", n_days=500)

    # 运行调优实验
    tune_result = run_tuning_experiment(
        df,
        model_type='lightgbm',
        label_lookahead=7,
        n_trials=30,
        use_feature_selection=True,
        top_k_features=25,
    )

    # 策略回测对比
    backtest_results = run_backtest_comparison(
        df,
        tune_result,
        model_type='lightgbm',
        label_lookahead=7,
    )

    # 特征重要性分析（用相关系数，避免正则化太强导致重要性为0）
    print("\n" + "=" * 70)
    print("  特征重要性分析（趋势理论视角）")
    print("=" * 70)

    fe = tune_result['feature_engineer']
    groups = fe.get_feature_groups()
    selected = tune_result['selected_features']

    # 用皮尔逊相关系数作为特征重要性的代理
    valid_data = fe.get_valid_data(fe.create_features(df, label_lookahead=7))
    correlations = []
    for col in selected:
        corr = abs(np.corrcoef(valid_data[col].values, valid_data['label'].values)[0, 1])
        if np.isnan(corr):
            corr = 0
        correlations.append((col, corr))
    correlations.sort(key=lambda x: x[1], reverse=True)

    print(f"\n各理论维度特征重要性分布（按平均相关系数）:")
    for group, feats in groups.items():
        group_feats = [f for f in feats if f in selected]
        if group_feats:
            group_corrs = [c[1] for c in correlations if c[0] in group_feats]
            avg_corr = np.mean(group_corrs) if group_corrs else 0
            print(f"  {group:<15} {len(group_feats):>3} 个特征, 平均相关系数: {avg_corr:.4f}")

    print(f"\nTop 15 最重要特征（按与标签的相关系数）:")
    for i, (feat, corr) in enumerate(correlations[:15]):
        group_name = "other"
        for g, feats in groups.items():
            if feat in feats:
                group_name = g
                break
        print(f"  {i+1:>2}. {feat:<30} [{group_name:<12}] {corr:.4f}")

    print("\n" + "=" * 70)
    print("  调优实验完成")
    print("=" * 70)
    print("关键发现:")
    print(f"  1. 调优后ROC-AUC: {tune_result['tuned_result']['roc_auc']:.4f} "
          f"(提升 {(tune_result['tuned_result']['roc_auc'] - tune_result['baseline_result']['roc_auc'])/tune_result['baseline_result']['roc_auc']*100:+.1f}%)")
    print(f"  2. 特征选择: {len(tune_result['feature_names'])} → {len(tune_result['selected_features'])} 个")
    print(f"  3. 验证方式: Walk-Forward ({tune_result['tuned_result']['n_folds']} 折滚动验证)")
    print("\n下一步: 将调优后的模型参数固化，用于实盘推理")


if __name__ == "__main__":
    main()
