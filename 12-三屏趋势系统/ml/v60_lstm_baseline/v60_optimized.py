"""V6.0 LSTM基线 - 优化版

针对TOP_EXIT场景不稳定问题，优化：
1. 降低标签阈值（0.20→0.15）增加正样本
2. 跳过早期数据（前2折）
3. 优化超参数
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from ml.models import LSTMModel
from ml.feature_engineer import TrendFeatureEngineer
from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer


def load_btc_data():
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def generate_labels(closes, lookahead=20, threshold=0.20, mode="drop"):
    n = len(closes)
    labels = np.zeros(n)
    for i in range(n - lookahead):
        future = closes[i + lookahead]
        if mode == "drop":
            if (closes[i] - future) / closes[i] > threshold:
                labels[i] = 1
        else:
            if (future - closes[i]) / closes[i] > threshold:
                labels[i] = 1
    return labels


def walk_forward_validation(features, feature_names, labels, n_splits=12,
                           train_days=730, test_days=180, step_days=180,
                           seq_length=20, model_params=None, skip_folds=0):
    """Walk-Forward验证"""
    n = len(features)
    splits = []
    test_end = n
    for _ in range(n_splits):
        test_start = test_end - test_days
        train_end = test_start
        train_start = train_end - train_days
        if train_start < 0 or test_start < 0:
            break
        splits.append((train_start, train_end, test_start, test_end))
        test_end -= step_days
    splits = list(reversed(splits))

    if skip_folds > 0:
        splits = splits[skip_folds:]

    train_aucs, test_aucs = [], []
    fold_details = []
    valid_folds = 0

    print(f"\n  Walk-Forward: {len(splits)}折（跳过前{skip_folds}折）")
    print(f"  {'折':<5s} {'训练区间':<20s} {'训练正样本':>12s} {'测试正样本':>12s} {'训练AUC':>10s} {'测试AUC':>10s} {'状态':>10s}")
    print("  " + "-" * 85)

    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        X_train = features.iloc[tr_s:tr_e][feature_names]
        y_train_arr = labels[tr_s:tr_e]
        X_test = features.iloc[te_s:te_e][feature_names]
        y_test_arr = labels[te_s:te_e]

        if y_train_arr.sum() < 3 or y_test_arr.sum() < 2:
            print(f"  {i+1+skip_folds:<5d} [{tr_s:5d}:{tr_e:5d}]  {y_train_arr.sum():>12.0f} ({y_train_arr.mean():.1%}) {y_test_arr.sum():>12.0f} ({y_test_arr.mean():.1%}) {'跳过':>10s} {'跳过':>10s} {'正样本不足':>10s}")
            continue

        torch.manual_seed(42 + i)
        np.random.seed(42 + i)

        model = LSTMModel(model_params)
        try:
            y_train = pd.Series(y_train_arr, index=X_train.index)
            y_val = pd.Series(y_test_arr, index=X_test.index)
            model.fit(X_train, y_train, X_val=X_test, y_val=y_val)

            train_pred = model.predict_proba(X_train)
            test_pred = model.predict_proba(X_test)

            train_true = y_train_arr[seq_length:]
            test_true = y_test_arr[seq_length:]
            train_pred_valid = train_pred[seq_length:]
            test_pred_valid = test_pred[seq_length:]

            if len(set(train_true)) > 1 and len(set(test_true)) > 1:
                train_auc = roc_auc_score(train_true, train_pred_valid)
                test_auc = roc_auc_score(test_true, test_pred_valid)
                train_aucs.append(train_auc)
                test_aucs.append(test_auc)
                valid_folds += 1

                status = "✅ 有效" if test_auc > 0.5 else "❌ 差"
                print(f"  {i+1+skip_folds:<5d} [{tr_s:5d}:{tr_e:5d}]  {y_train_arr.sum():>12.0f} ({y_train_arr.mean():.1%}) {y_test_arr.sum():>12.0f} ({y_test_arr.mean():.1%}) {train_auc:>10.4f} {test_auc:>10.4f} {status:>10s}")
            else:
                print(f"  {i+1+skip_folds:<5d} [{tr_s:5d}:{tr_e:5d}]  {y_train_arr.sum():>12.0f} ({y_train_arr.mean():.1%}) {y_test_arr.sum():>12.0f} ({y_test_arr.mean():.1%}) {'跳过':>10s} {'跳过':>10s} {'标签单一':>10s}")
        except Exception as e:
            print(f"  {i+1+skip_folds:<5d} [{tr_s:5d}:{tr_e:5d}]  错误: {str(e)[:20]}")

    return {
        'valid_folds': valid_folds,
        'total_folds': len(splits),
        'mean_train_auc': np.mean(train_aucs) if train_aucs else 0,
        'std_train_auc': np.std(train_aucs) if train_aucs else 0,
        'mean_test_auc': np.mean(test_aucs) if test_aucs else 0,
        'std_test_auc': np.std(test_aucs) if test_aucs else 0,
        'min_test_auc': np.min(test_aucs) if test_aucs else 0,
        'max_test_auc': np.max(test_aucs) if test_aucs else 0,
        'decay_rate': (1 - np.mean(test_aucs)/np.mean(train_aucs)) if train_aucs and test_aucs and np.mean(train_aucs) > 0 else 0,
        'train_aucs': train_aucs,
        'test_aucs': test_aucs,
    }


def main():
    print("=" * 80)
    print("  V6.0 LSTM基线优化版")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    n = len(prices)
    print(f"\n  BTC日线: {n}天")

    # 特征
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    redundant_features = ["dip_buy_level", "dip_buy_position_ratio", "left_side_buy_signal"]
    v55_names = list(phil_features.columns)
    v56_names = [f for f in v55_names if f not in redundant_features]

    features = pd.concat([trend_features, phil_features[v56_names]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    feature_names = list(features.columns)

    print(f"  特征维度: {len(feature_names)}")

    # ========== 方案1：原参数（基准） ==========
    print("\n" + "=" * 80)
    print("  【方案1】基准：Config1（阈值0.20，12折）")
    print("=" * 80)

    labels_020 = generate_labels(closes, 20, 0.20, "drop")

    config1_params = {
        'hidden_dim': 32, 'num_layers': 2, 'dropout': 0.5,
        'weight_decay': 0.01, 'lr': 0.001, 'batch_size': 32,
        'epochs': 15, 'patience': 5, 'seq_length': 20, 'pos_weight': True
    }

    t0 = time.time()
    result_base = walk_forward_validation(
        features, feature_names, labels_020,
        n_splits=12, train_days=730, test_days=180, step_days=180,
        seq_length=20, model_params=config1_params, skip_folds=0
    )
    t_base = time.time() - t0

    print(f"\n  平均训练AUC: {result_base['mean_train_auc']:.4f} ± {result_base['std_train_auc']:.4f}")
    print(f"  平均测试AUC: {result_base['mean_test_auc']:.4f} ± {result_base['std_test_auc']:.4f}")
    print(f"  测试AUC范围: [{result_base['min_test_auc']:.4f}, {result_base['max_test_auc']:.4f}]")
    print(f"  衰减率: {result_base['decay_rate']:.1%}")
    print(f"  有效折数: {result_base['valid_folds']}/{result_base['total_folds']}")
    print(f"  总耗时: {t_base:.1f}s")

    # ========== 方案2：降低阈值 ==========
    print("\n" + "=" * 80)
    print("  【方案2】降低阈值（0.20→0.15，增加正样本）")
    print("=" * 80)

    labels_015 = generate_labels(closes, 20, 0.15, "drop")

    t0 = time.time()
    result_thresh = walk_forward_validation(
        features, feature_names, labels_015,
        n_splits=12, train_days=730, test_days=180, step_days=180,
        seq_length=20, model_params=config1_params, skip_folds=0
    )
    t_thresh = time.time() - t0

    print(f"\n  平均训练AUC: {result_thresh['mean_train_auc']:.4f} ± {result_thresh['std_train_auc']:.4f}")
    print(f"  平均测试AUC: {result_thresh['mean_test_auc']:.4f} ± {result_thresh['std_test_auc']:.4f}")
    print(f"  测试AUC范围: [{result_thresh['min_test_auc']:.4f}, {result_thresh['max_test_auc']:.4f}]")
    print(f"  衰减率: {result_thresh['decay_rate']:.1%}")
    print(f"  有效折数: {result_thresh['valid_folds']}/{result_thresh['total_folds']}")
    print(f"  总耗时: {t_thresh:.1f}s")

    # ========== 方案3：跳过早期数据 ==========
    print("\n" + "=" * 80)
    print("  【方案3】跳过早期2折（阈值0.20，10折）")
    print("=" * 80)

    t0 = time.time()
    result_skip = walk_forward_validation(
        features, feature_names, labels_020,
        n_splits=12, train_days=730, test_days=180, step_days=180,
        seq_length=20, model_params=config1_params, skip_folds=2
    )
    t_skip = time.time() - t0

    print(f"\n  平均训练AUC: {result_skip['mean_train_auc']:.4f} ± {result_skip['std_train_auc']:.4f}")
    print(f"  平均测试AUC: {result_skip['mean_test_auc']:.4f} ± {result_skip['std_test_auc']:.4f}")
    print(f"  测试AUC范围: [{result_skip['min_test_auc']:.4f}, {result_skip['max_test_auc']:.4f}]")
    print(f"  衰减率: {result_skip['decay_rate']:.1%}")
    print(f"  有效折数: {result_skip['valid_folds']}/{result_skip['total_folds']}")
    print(f"  总耗时: {t_skip:.1f}s")

    # ========== 方案4：降低阈值+跳过早期 ==========
    print("\n" + "=" * 80)
    print("  【方案4】降低阈值+跳过早期2折（阈值0.15，10折）")
    print("=" * 80)

    t0 = time.time()
    result_both = walk_forward_validation(
        features, feature_names, labels_015,
        n_splits=12, train_days=730, test_days=180, step_days=180,
        seq_length=20, model_params=config1_params, skip_folds=2
    )
    t_both = time.time() - t0

    print(f"\n  平均训练AUC: {result_both['mean_train_auc']:.4f} ± {result_both['std_train_auc']:.4f}")
    print(f"  平均测试AUC: {result_both['mean_test_auc']:.4f} ± {result_both['std_test_auc']:.4f}")
    print(f"  测试AUC范围: [{result_both['min_test_auc']:.4f}, {result_both['max_test_auc']:.4f}]")
    print(f"  衰减率: {result_both['decay_rate']:.1%}")
    print(f"  有效折数: {result_both['valid_folds']}/{result_both['total_folds']}")
    print(f"  总耗时: {t_both:.1f}s")

    # ========== 对比汇总 ==========
    print("\n" + "=" * 80)
    print("  【汇总对比】")
    print("=" * 80)

    results = [
        ("方案1: 基准(0.20,12折)", result_base, t_base),
        ("方案2: 降阈值(0.15,12折)", result_thresh, t_thresh),
        ("方案3: 跳早期(0.20,10折)", result_skip, t_skip),
        ("方案4: 降阈值+跳早期(0.15,10折)", result_both, t_both),
    ]

    print(f"\n  {'方案':<35s} {'有效折':>8s} {'训练AUC':>10s} {'测试AUC':>10s} {'衰减率':>8s} {'标准差':>8s}")
    print("  " + "-" * 85)

    for name, res, t in results:
        fold_info = f"{res['valid_folds']}/{res['total_folds']}"
        print(f"  {name:<35s} {fold_info:>8s} {res['mean_train_auc']:>10.4f} {res['mean_test_auc']:>10.4f} {res['decay_rate']:>7.1%} {res['std_test_auc']:>8.4f}")

    # LightGBM基准
    lgbm_train = 1.0
    lgbm_test = 0.7372
    lgbm_decay = 1 - lgbm_test / lgbm_train
    print(f"\n  LightGBM V5.5基准: 训练AUC={lgbm_train:.4f}, 测试AUC={lgbm_test:.4f}, 衰减率={lgbm_decay:.1%}")

    # 综合得分
    print(f"\n  综合得分（测试AUC + 过拟合缓解奖励）:")
    best_score = 0
    best_name = ""
    for name, res, t in results:
        overfit_relief = max(0, (lgbm_decay - res['decay_rate']) * 0.5)
        score = res['mean_test_auc'] + overfit_relief
        print(f"    {name:<35s} 测试AUC={res['mean_test_auc']:.4f}, 缓解奖励={overfit_relief:.4f}, 总分={score:.4f}")
        if score > best_score:
            best_score = score
            best_name = name

    print(f"\n  🏆 最佳方案: {best_name} (得分: {best_score:.4f})")

    # 保存结果
    result_data = {
        'baseline_v55': {
            'model': 'LightGBM',
            'top_exit': {'train_auc': 1.0, 'test_auc': 0.7372, 'decay': lgbm_decay}
        },
        'optimization_configs': [
            {
                'name': name,
                'valid_folds': res['valid_folds'],
                'total_folds': res['total_folds'],
                'train_auc': res['mean_train_auc'],
                'test_auc': res['mean_test_auc'],
                'std_test_auc': res['std_test_auc'],
                'decay': res['decay_rate'],
                'min_test_auc': res['min_test_auc'],
                'max_test_auc': res['max_test_auc'],
            } for name, res, t in results
        ],
        'best_config': {'name': best_name, 'score': best_score}
    }

    out_path = os.path.join(BASE_DIR, "ml/backtest_results/v60_lstm_optimized.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}")


if __name__ == "__main__":
    main()
