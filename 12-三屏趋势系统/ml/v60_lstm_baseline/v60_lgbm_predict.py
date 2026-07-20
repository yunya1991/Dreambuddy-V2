"""LightGBM TOP_EXIT 概率预测（独立进程，避免与PyTorch的OpenMP冲突）

输出: ml/backtest_results/v60_lgbm_proba_{symbol}.json
"""

import os
import sys
import json
import time
import argparse
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '12-三屏趋势系统'))

from ml.v60_lstm_baseline.v60_common import (
    load_coin_data, generate_labels, build_features, walk_forward_splits,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="BTC")
    parser.add_argument("--train-days", type=int, default=730)
    parser.add_argument("--test-days", type=int, default=180)
    parser.add_argument("--step-days", type=int, default=180)
    parser.add_argument("--lookahead", type=int, default=20)
    args = parser.parse_args()

    print(f"  [LightGBM] TOP_EXIT概率预测 - {args.symbol}")

    prices = load_coin_data(args.symbol)
    n = len(prices)
    closes = prices["close"].values
    print(f"  数据: {n}天")

    features = build_features(prices)
    feature_names = list(features.columns)
    print(f"  特征维度: {len(feature_names)}")

    labels = generate_labels(closes, args.lookahead, 0.20, "drop")

    splits = walk_forward_splits(n, args.train_days, args.test_days, args.step_days, args.lookahead)
    print(f"  Walk-Forward: {len(splits)}个窗口")

    top_proba = np.full(n, 0.5)

    from ml.models import LightGBMModel

    lgbm_params = {
        'n_estimators': 200, 'learning_rate': 0.05, 'num_leaves': 31,
        'min_data_in_leaf': 20, 'lambda_l2': 0.1,
        'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 5,
        'early_stopping_rounds': 30, 'verbose': -1, 'random_state': 42,
    }

    t0 = time.time()
    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        X_train = features.iloc[tr_s:tr_e][feature_names]
        y_train = pd.Series(labels[tr_s:tr_e], index=X_train.index)
        X_test = features.iloc[te_s:te_e][feature_names]

        valid_train_n = len(X_train) - args.lookahead
        X_train_valid = X_train.iloc[:valid_train_n]
        y_train_valid = y_train.iloc[:valid_train_n]

        val_n = max(int(valid_train_n * 0.2), 30)
        X_val = X_train_valid.iloc[-val_n:]
        y_val = y_train_valid.iloc[-val_n:]

        try:
            model = LightGBMModel(lgbm_params)
            model.fit(X_train_valid, y_train_valid, X_val=X_val, y_val=y_val)
            top_proba[te_s:te_e] = model.predict_proba(X_test)
            pos_n = int(y_train_valid.sum())
            print(f"    窗口{i+1}: train=[{tr_s}:{tr_e}], test=[{te_s}:{te_e}], 正样本={pos_n}")
        except Exception as e:
            print(f"    窗口{i+1} 失败: {e}")

    print(f"  LightGBM预测完成, 耗时: {time.time()-t0:.1f}s")
    print(f"  概率: 均值={np.mean(top_proba):.3f}, 最大={np.max(top_proba):.3f}")

    out_path = os.path.join(BASE_DIR, f"ml/backtest_results/v60_lgbm_proba_{args.symbol}.json")
    with open(out_path, 'w') as f:
        json.dump({
            'symbol': args.symbol,
            'model': 'LightGBM',
            'task': 'TOP_EXIT',
            'n': int(n),
            'proba': top_proba.tolist(),
        }, f)
    print(f"  已保存: {out_path}")


if __name__ == "__main__":
    main()
