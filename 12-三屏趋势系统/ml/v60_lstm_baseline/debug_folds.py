"""诊断：12折每折详细结果

查看每一折的训练/测试AUC，找出差异来源
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


def main():
    print("=" * 80)
    print("  诊断：12折每折详细结果")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    n = len(prices)

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

    labels = generate_labels(closes, 20, 0.20, "drop")

    # 12折划分
    seq_length = 20
    n_splits = 12
    train_days = 730
    test_days = 180
    step_days = 180

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

    print(f"\n  总折数: {len(splits)}")
    print(f"  {'折':<5s} {'训练区间':<20s} {'训练样本':>10s} {'训练正样本':>12s} {'测试样本':>10s} {'测试正样本':>12s}")
    print("  " + "-" * 75)

    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        y_tr = labels[tr_s:tr_e]
        y_te = labels[te_s:te_e]
        print(f"  {i+1:<5d} [{tr_s:5d}:{tr_e:5d}]    {tr_e-tr_s:>10d} {y_tr.sum():>12.0f} ({y_tr.mean():.1%}) {te_e-te_s:>10d} {y_te.sum():>12.0f} ({y_te.mean():.1%})")

    # 训练每折并记录结果
    print(f"\n  各折训练结果:")
    print(f"  {'折':<5s} {'训练AUC':>10s} {'测试AUC':>10s} {'状态':>10s}")
    print("  " + "-" * 40)

    train_aucs = []
    test_aucs = []
    valid_folds = 0

    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        X_train = features.iloc[tr_s:tr_e][feature_names]
        y_train = pd.Series(labels[tr_s:tr_e], index=X_train.index)
        X_test = features.iloc[te_s:te_e][feature_names]
        y_test = labels[te_s:te_e]

        if y_train.sum() < 3 or y_test.sum() < 2:
            print(f"  {i+1:<5d} {'跳过':>10s} {'跳过':>10s} {'正样本不足':>10s}")
            continue

        torch.manual_seed(42 + i)
        np.random.seed(42 + i)

        model = LSTMModel()
        try:
            model.fit(X_train, y_train, X_val=X_test, y_val=pd.Series(y_test, index=X_test.index))

            train_pred = model.predict_proba(X_train)
            test_pred = model.predict_proba(X_test)

            train_true = y_train.values[seq_length:]
            test_true = y_test[seq_length:]
            train_pred_valid = train_pred[seq_length:]
            test_pred_valid = test_pred[seq_length:]

            if len(set(train_true)) > 1 and len(set(test_true)) > 1:
                train_auc = roc_auc_score(train_true, train_pred_valid)
                test_auc = roc_auc_score(test_true, test_pred_valid)
                train_aucs.append(train_auc)
                test_aucs.append(test_auc)
                valid_folds += 1

                status = "✅ 有效" if test_auc > 0.5 else "❌ 差"
                print(f"  {i+1:<5d} {train_auc:>10.4f} {test_auc:>10.4f} {status:>10s}")
            else:
                print(f"  {i+1:<5d} {'跳过':>10s} {'跳过':>10s} {'标签单一':>10s}")
        except Exception as e:
            print(f"  {i+1:<5d} {'错误':>10s} {'错误':>10s} {str(e)[:10]:>10s}")

    # 统计
    print(f"\n  有效折数: {valid_folds}/{len(splits)}")
    if train_aucs:
        print(f"  平均训练AUC: {np.mean(train_aucs):.4f} ± {np.std(train_aucs):.4f}")
        print(f"  平均测试AUC: {np.mean(test_aucs):.4f} ± {np.std(test_aucs):.4f}")
        print(f"  测试AUC范围: [{np.min(test_aucs):.4f}, {np.max(test_aucs):.4f}]")

        # 与Step5对比
        step5_top_test = 0.7455
        step5_top_train = 0.9735
        print(f"\n  与Step5 Config1对比:")
        print(f"    Step5 训练AUC: {step5_top_train:.4f}")
        print(f"    当前 训练AUC: {np.mean(train_aucs):.4f}")
        print(f"    Step5 测试AUC: {step5_top_test:.4f}")
        print(f"    当前 测试AUC: {np.mean(test_aucs):.4f}")


if __name__ == "__main__":
    main()
