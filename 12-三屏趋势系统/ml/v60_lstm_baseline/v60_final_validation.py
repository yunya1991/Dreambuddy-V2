"""V6.0 LSTM基线 - DIP_BUY场景验证

验证LSTM在DIP_BUY（抄底）场景的表现
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import torch

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


def generate_labels(closes, lookahead=20, threshold=0.15, mode="rise"):
    n = len(closes)
    labels = np.zeros(n)
    for i in range(n - lookahead):
        future = closes[i + lookahead]
        if mode == "rise":
            if (future - closes[i]) / closes[i] > threshold:
                labels[i] = 1
        else:
            if (closes[i] - future) / closes[i] > threshold:
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
    valid_folds = 0

    print(f"\n  Walk-Forward: {len(splits)}折")
    print(f"  {'折':<5s} {'训练正样本':>12s} {'测试正样本':>12s} {'训练AUC':>10s} {'测试AUC':>10s} {'状态':>10s}")
    print("  " + "-" * 65)

    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        X_train = features.iloc[tr_s:tr_e][feature_names]
        y_train_arr = labels[tr_s:tr_e]
        X_test = features.iloc[te_s:te_e][feature_names]
        y_test_arr = labels[te_s:te_e]

        if y_train_arr.sum() < 3 or y_test_arr.sum() < 2:
            print(f"  {i+1+skip_folds:<5d} {y_train_arr.sum():>12.0f} ({y_train_arr.mean():.1%}) {y_test_arr.sum():>12.0f} ({y_test_arr.mean():.1%}) {'跳过':>10s} {'跳过':>10s} {'正样本不足':>10s}")
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
                print(f"  {i+1+skip_folds:<5d} {y_train_arr.sum():>12.0f} ({y_train_arr.mean():.1%}) {y_test_arr.sum():>12.0f} ({y_test_arr.mean():.1%}) {train_auc:>10.4f} {test_auc:>10.4f} {status:>10s}")
            else:
                print(f"  {i+1+skip_folds:<5d} {y_train_arr.sum():>12.0f} ({y_train_arr.mean():.1%}) {y_test_arr.sum():>12.0f} ({y_test_arr.mean():.1%}) {'跳过':>10s} {'跳过':>10s} {'标签单一':>10s}")
        except Exception as e:
            print(f"  {i+1+skip_folds:<5d} 错误: {str(e)[:20]}")

    return {
        'valid_folds': valid_folds,
        'total_folds': len(splits),
        'mean_train_auc': np.mean(train_aucs) if train_aucs else 0,
        'std_train_auc': np.std(train_aucs) if train_aucs else 0,
        'mean_test_auc': np.mean(test_aucs) if test_aucs else 0,
        'std_test_auc': np.std(test_aucs) if test_aucs else 0,
        'decay_rate': (1 - np.mean(test_aucs)/np.mean(train_aucs)) if train_aucs and test_aucs and np.mean(train_aucs) > 0 else 0,
        'train_aucs': train_aucs,
        'test_aucs': test_aucs,
    }


def main():
    print("=" * 80)
    print("  V6.0 LSTM基线 - DIP_BUY场景验证")
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

    config1_params = {
        'hidden_dim': 32, 'num_layers': 2, 'dropout': 0.5,
        'weight_decay': 0.01, 'lr': 0.001, 'batch_size': 32,
        'epochs': 15, 'patience': 5, 'seq_length': 20, 'pos_weight': True
    }

    # ========== DIP_BUY 场景 ==========
    print("\n" + "=" * 80)
    print("  DIP_BUY场景（上涨阈值15%，20天）")
    print("=" * 80)

    labels_rise = generate_labels(closes, 20, 0.15, "rise")

    t0 = time.time()
    result_dip = walk_forward_validation(
        features, feature_names, labels_rise,
        n_splits=12, train_days=730, test_days=180, step_days=180,
        seq_length=20, model_params=config1_params, skip_folds=0
    )
    t_dip = time.time() - t0

    print(f"\n  平均训练AUC: {result_dip['mean_train_auc']:.4f} ± {result_dip['std_train_auc']:.4f}")
    print(f"  平均测试AUC: {result_dip['mean_test_auc']:.4f} ± {result_dip['std_test_auc']:.4f}")
    print(f"  衰减率: {result_dip['decay_rate']:.1%}")
    print(f"  有效折数: {result_dip['valid_folds']}/{result_dip['total_folds']}")
    print(f"  总耗时: {t_dip:.1f}s")

    # ========== TOP_EXIT 场景 ==========
    print("\n" + "=" * 80)
    print("  TOP_EXIT场景（下跌阈值20%，20天）")
    print("=" * 80)

    labels_drop = generate_labels(closes, 20, 0.20, "drop")

    t0 = time.time()
    result_top = walk_forward_validation(
        features, feature_names, labels_drop,
        n_splits=12, train_days=730, test_days=180, step_days=180,
        seq_length=20, model_params=config1_params, skip_folds=0
    )
    t_top = time.time() - t0

    print(f"\n  平均训练AUC: {result_top['mean_train_auc']:.4f} ± {result_top['std_train_auc']:.4f}")
    print(f"  平均测试AUC: {result_top['mean_test_auc']:.4f} ± {result_top['std_test_auc']:.4f}")
    print(f"  衰减率: {result_top['decay_rate']:.1%}")
    print(f"  有效折数: {result_top['valid_folds']}/{result_top['total_folds']}")
    print(f"  总耗时: {t_top:.1f}s")

    # ========== 综合对比 ==========
    print("\n" + "=" * 80)
    print("  综合对比（LSTM vs LightGBM V5.5）")
    print("=" * 80)

    lgbm = {
        'top_exit': {'train_auc': 1.0, 'test_auc': 0.7372, 'decay': 0.263},
        'dip_buy': {'train_auc': 1.0, 'test_auc': 0.6981, 'decay': 0.302},
    }

    print(f"\n  {'场景':<15s} {'模型':<12s} {'训练AUC':>10s} {'测试AUC':>10s} {'衰减率':>8s} {'综合得分':>10s}")
    print("  " + "-" * 70)

    top_lgbm_score = lgbm['top_exit']['test_auc']
    top_lstm_score = result_top['mean_test_auc']
    dip_lgbm_score = lgbm['dip_buy']['test_auc']
    dip_lstm_score = result_dip['mean_test_auc']

    # 综合得分：测试AUC + 过拟合缓解奖励
    top_lstm_relief = max(0, (lgbm['top_exit']['decay'] - result_top['decay_rate']) * 0.5)
    dip_lstm_relief = max(0, (lgbm['dip_buy']['decay'] - result_dip['decay_rate']) * 0.5)

    print(f"  {'TOP_EXIT':<15s} {'LightGBM':<12s} {lgbm['top_exit']['train_auc']:>10.4f} {lgbm['top_exit']['test_auc']:>10.4f} {lgbm['top_exit']['decay']:>7.1%} {top_lgbm_score:>10.4f}")
    print(f"  {'TOP_EXIT':<15s} {'LSTM':<12s} {result_top['mean_train_auc']:>10.4f} {result_top['mean_test_auc']:>10.4f} {result_top['decay_rate']:>7.1%} {top_lstm_score + top_lstm_relief:>10.4f}")
    print(f"  {'DIP_BUY':<15s} {'LightGBM':<12s} {lgbm['dip_buy']['train_auc']:>10.4f} {lgbm['dip_buy']['test_auc']:>10.4f} {lgbm['dip_buy']['decay']:>7.1%} {dip_lgbm_score:>10.4f}")
    print(f"  {'DIP_BUY':<15s} {'LSTM':<12s} {result_dip['mean_train_auc']:>10.4f} {result_dip['mean_test_auc']:>10.4f} {result_dip['decay_rate']:>7.1%} {dip_lstm_score + dip_lstm_relief:>10.4f}")

    # 结论
    print(f"\n  结论:")
    if top_lgbm_score > top_lstm_score:
        print(f"    TOP_EXIT: LightGBM更优 (0.7372 vs {result_top['mean_test_auc']:.4f})")
    else:
        print(f"    TOP_EXIT: LSTM更优 ({result_top['mean_test_auc']:.4f} vs 0.7372)")

    if dip_lgbm_score > dip_lstm_score:
        print(f"    DIP_BUY: LightGBM更优 (0.6981 vs {result_dip['mean_test_auc']:.4f})")
    else:
        print(f"    DIP_BUY: LSTM更优 ({result_dip['mean_test_auc']:.4f} vs 0.6981)")

    # 保存结果
    result_data = {
        'model': 'LSTM',
        'version': 'v6.0',
        'config': config1_params,
        'top_exit': {
            'train_auc': result_top['mean_train_auc'],
            'test_auc': result_top['mean_test_auc'],
            'std_test_auc': result_top['std_test_auc'],
            'decay': result_top['decay_rate'],
            'valid_folds': result_top['valid_folds'],
            'total_folds': result_top['total_folds'],
        },
        'dip_buy': {
            'train_auc': result_dip['mean_train_auc'],
            'test_auc': result_dip['mean_test_auc'],
            'std_test_auc': result_dip['std_test_auc'],
            'decay': result_dip['decay_rate'],
            'valid_folds': result_dip['valid_folds'],
            'total_folds': result_dip['total_folds'],
        },
        'lightgbm_v55_baseline': lgbm,
    }

    out_path = os.path.join(BASE_DIR, "ml/backtest_results/v60_lstm_final.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}")


if __name__ == "__main__":
    main()
