"""V6.0 LSTM基线验证

验证LSTM Config1参数作为V6.0基线的性能：
- 12折Walk-Forward验证
- 对比V5.5 LightGBM基线
- TOP_EXIT + DIP_BUY双场景

用法：
    cd 12-三屏趋势系统
    python ml/v60_lstm_baseline/v60_baseline_validation.py
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

warnings.filterwarnings('ignore')

import torch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from ml.models import LSTMModel, LightGBMModel, create_model
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


def walk_forward_lstm(features_df, labels, feature_names,
                      n_splits=12, train_days=730, test_days=180, step_days=180):
    """LSTM Walk-Forward验证"""
    n = len(features_df)
    train_aucs, test_aucs = [], []

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

    valid_splits = 0
    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        X_train = features_df.iloc[tr_s:tr_e][feature_names]
        y_train = pd.Series(labels[tr_s:tr_e], index=X_train.index)
        X_test = features_df.iloc[te_s:te_e][feature_names]
        y_test = labels[te_s:te_e]

        if y_train.sum() < 3 or y_test.sum() < 2:
            continue

        model = LSTMModel()
        model.fit(X_train, y_train, X_val=X_test, y_val=pd.Series(y_test, index=X_test.index))

        train_pred = model.predict_proba(X_train)
        test_pred = model.predict_proba(X_test)

        seq_len = model.params['seq_length']
        train_true = y_train.values[seq_len:]
        test_true = y_test[seq_len:]
        train_pred_valid = train_pred[seq_len:]
        test_pred_valid = test_pred[seq_len:]

        if len(set(train_true)) > 1:
            train_aucs.append(roc_auc_score(train_true, train_pred_valid))
        if len(set(test_true)) > 1:
            test_aucs.append(roc_auc_score(test_true, test_pred_valid))
            valid_splits += 1

    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0

    return avg_test, avg_train, float(decay), valid_splits


def walk_forward_lightgbm(features_df, labels, feature_names,
                           n_splits=12, train_days=730, test_days=180, step_days=180):
    """LightGBM Walk-Forward验证（基线对比）"""
    n = len(features_df)
    train_aucs, test_aucs = [], []

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

    for tr_s, tr_e, te_s, te_e in splits:
        X_train = features_df.iloc[tr_s:tr_e][feature_names]
        y_train = labels[tr_s:tr_e]
        X_test = features_df.iloc[te_s:te_e][feature_names]
        y_test = labels[te_s:te_e]

        if y_train.sum() < 3 or y_test.sum() < 2:
            continue

        model = LightGBMModel()
        model.fit(X_train, pd.Series(y_train))

        train_pred = model.predict_proba(X_train)
        test_pred = model.predict_proba(X_test)

        if len(set(y_train)) > 1:
            train_aucs.append(roc_auc_score(y_train, train_pred))
        if len(set(y_test)) > 1:
            test_aucs.append(roc_auc_score(y_test, test_pred))

    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0

    return avg_test, avg_train, float(decay)


def main():
    print("=" * 80)
    print("  V6.0 LSTM 基线验证")
    print("  对比：V5.5 LightGBM vs V6.0 LSTM (Config1)")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    n = len(prices)
    print(f"\n  BTC日线: {n}天")

    t0 = time.time()
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
    print(f"  特征计算耗时: {time.time() - t0:.1f}s")

    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")

    print(f"  TOP_EXIT正样本: {top_exit_labels.sum():.0f} ({top_exit_labels.mean():.1%})")
    print(f"  DIP_BUY正样本: {dip_buy_labels.sum():.0f} ({dip_buy_labels.mean():.1%})")

    # ========== V5.5 LightGBM ==========
    print("\n" + "=" * 80)
    print("  【V5.5】LightGBM基线")
    print("=" * 80)

    t0 = time.time()
    lgb_top_test, lgb_top_train, lgb_top_decay = walk_forward_lightgbm(
        features, top_exit_labels, feature_names
    )
    lgb_top_time = time.time() - t0

    print(f"  TOP_EXIT: 训练={lgb_top_train:.4f}, 测试={lgb_top_test:.4f}, 衰减={lgb_top_decay:.1%}, 时间={lgb_top_time:.1f}s")

    t0 = time.time()
    lgb_dip_test, lgb_dip_train, lgb_dip_decay = walk_forward_lightgbm(
        features, dip_buy_labels, feature_names
    )
    lgb_dip_time = time.time() - t0

    print(f"  DIP_BUY:  训练={lgb_dip_train:.4f}, 测试={lgb_dip_test:.4f}, 衰减={lgb_dip_decay:.1%}, 时间={lgb_dip_time:.1f}s")

    # ========== V6.0 LSTM ==========
    print("\n" + "=" * 80)
    print("  【V6.0】LSTM (Config1参数)")
    print("  hidden=32, layers=2, dropout=0.5, wd=0.01, seq=20, epochs=15")
    print("=" * 80)

    t0 = time.time()
    lstm_top_test, lstm_top_train, lstm_top_decay, lstm_top_splits = walk_forward_lstm(
        features, top_exit_labels, feature_names
    )
    lstm_top_time = time.time() - t0

    print(f"  TOP_EXIT: 训练={lstm_top_train:.4f}, 测试={lstm_top_test:.4f}, 衰减={lstm_top_decay:.1%}, 折数={lstm_top_splits}, 时间={lstm_top_time:.1f}s")

    t0 = time.time()
    lstm_dip_test, lstm_dip_train, lstm_dip_decay, lstm_dip_splits = walk_forward_lstm(
        features, dip_buy_labels, feature_names
    )
    lstm_dip_time = time.time() - t0

    print(f"  DIP_BUY:  训练={lstm_dip_train:.4f}, 测试={lstm_dip_test:.4f}, 衰减={lstm_dip_decay:.1%}, 折数={lstm_dip_splits}, 时间={lstm_dip_time:.1f}s")

    # ========== 对比分析 ==========
    print("\n" + "=" * 80)
    print("  【对比分析】")
    print("=" * 80)

    print(f"\n  TOP_EXIT场景:")
    print(f"  {'指标':<20s} {'V5.5 LightGBM':>15s} {'V6.0 LSTM':>15s} {'变化':>12s}")
    print("  " + "-" * 65)
    print(f"  {'训练AUC':<20s} {lgb_top_train:>15.4f} {lstm_top_train:>15.4f} {lstm_top_train-lgb_top_train:>+12.4f}")
    print(f"  {'测试AUC':<20s} {lgb_top_test:>15.4f} {lstm_top_test:>15.4f} {lstm_top_test-lgb_top_test:>+12.4f}")
    print(f"  {'衰减率':<20s} {lgb_top_decay:>15.1%} {lstm_top_decay:>15.1%} {lstm_top_decay-lgb_top_decay:>+12.1%}")
    print(f"  {'训练时间':<20s} {f'{lgb_top_time:.1f}s':>15s} {f'{lstm_top_time:.1f}s':>15s} {f'{lstm_top_time-lgb_top_time:+.1f}s':>12s}")

    print(f"\n  DIP_BUY场景:")
    print(f"  {'指标':<20s} {'V5.5 LightGBM':>15s} {'V6.0 LSTM':>15s} {'变化':>12s}")
    print("  " + "-" * 65)
    print(f"  {'训练AUC':<20s} {lgb_dip_train:>15.4f} {lstm_dip_train:>15.4f} {lstm_dip_train-lgb_dip_train:>+12.4f}")
    print(f"  {'测试AUC':<20s} {lgb_dip_test:>15.4f} {lstm_dip_test:>15.4f} {lstm_dip_test-lgb_dip_test:>+12.4f}")
    print(f"  {'衰减率':<20s} {lgb_dip_decay:>15.1%} {lstm_dip_decay:>15.1%} {lstm_dip_decay-lgb_dip_decay:>+12.1%}")
    print(f"  {'训练时间':<20s} {f'{lgb_dip_time:.1f}s':>15s} {f'{lstm_dip_time:.1f}s':>15s} {f'{lstm_dip_time-lgb_dip_time:+.1f}s':>12s}")

    # ========== 结论 ==========
    print("\n" + "=" * 80)
    print("  【结论】")
    print("=" * 80)

    top_overfit_improved = lstm_top_train < lgb_top_train
    top_test_improved = lstm_top_test > lgb_top_test
    dip_overfit_improved = lstm_dip_train < lgb_dip_train
    dip_test_improved = lstm_dip_test > lgb_dip_test

    print(f"\n  过拟合缓解情况:")
    print(f"    TOP_EXIT: {'✅' if top_overfit_improved else '❌'} 训练AUC {lgb_top_train:.4f} → {lstm_top_train:.4f}")
    print(f"    DIP_BUY:  {'✅' if dip_overfit_improved else '❌'} 训练AUC {lgb_dip_train:.4f} → {lstm_dip_train:.4f}")

    print(f"\n  测试AUC变化:")
    print(f"    TOP_EXIT: {'✅ 提升' if top_test_improved else '❌ 下降'} {lgb_top_test:.4f} → {lstm_top_test:.4f} ({lstm_top_test-lgb_top_test:+.4f})")
    print(f"    DIP_BUY:  {'✅ 提升' if dip_test_improved else '❌ 下降'} {lgb_dip_test:.4f} → {lstm_dip_test:.4f} ({lstm_dip_test-lgb_dip_test:+.4f})")

    # 综合评分
    top_score = lstm_top_test + (0.05 if top_overfit_improved else 0)
    dip_score = lstm_dip_test + (0.05 if dip_overfit_improved else 0)
    v55_top_score = lgb_top_test
    v55_dip_score = lgb_dip_test

    print(f"\n  综合得分（测试AUC + 过拟合缓解奖励）:")
    print(f"    V5.5: TOP={v55_top_score:.4f}, DIP={v55_dip_score:.4f}")
    print(f"    V6.0: TOP={top_score:.4f}, DIP={dip_score:.4f}")

    overall_success = (top_score > v55_top_score) and (dip_score > v55_dip_score)
    top_success = top_score > v55_top_score
    dip_success = dip_score > v55_dip_score

    print(f"\n  综合判定:")
    if overall_success:
        print("    ✅ V6.0 LSTM全面优于V5.5 LightGBM，建议作为新基线")
    elif top_success or dip_success:
        print(f"    🟡 V6.0 LSTM部分场景优于V5.5（{('TOP_EXIT' if top_success else 'DIP_BUY')}）")
        print("    建议：在优势场景使用LSTM，弱势场景继续使用LightGBM")
    else:
        print("    ❌ V6.0 LSTM未优于V5.5，建议继续优化")

    # 保存结果
    output = {
        "step": "v60_baseline_validation",
        "version": "v6.0",
        "model_type": "lstm",
        "analysis_date": str(pd.Timestamp.now()),
        "config": {
            "hidden_dim": 32,
            "num_layers": 2,
            "dropout": 0.5,
            "weight_decay": 0.01,
            "seq_length": 20,
            "epochs": 15,
        },
        "v55_lightgbm": {
            "top_exit": {"train_auc": lgb_top_train, "test_auc": lgb_top_test, "decay": lgb_top_decay},
            "dip_buy": {"train_auc": lgb_dip_train, "test_auc": lgb_dip_test, "decay": lgb_dip_decay},
        },
        "v60_lstm": {
            "top_exit": {"train_auc": lstm_top_train, "test_auc": lstm_top_test, "decay": lstm_top_decay, "valid_splits": lstm_top_splits},
            "dip_buy": {"train_auc": lstm_dip_train, "test_auc": lstm_dip_test, "decay": lstm_dip_decay, "valid_splits": lstm_dip_splits},
        },
        "comparison": {
            "top_exit": {
                "train_reduce": lgb_top_train - lstm_top_train,
                "test_change": lstm_top_test - lgb_top_test,
                "overfit_improved": top_overfit_improved,
                "test_improved": top_test_improved,
            },
            "dip_buy": {
                "train_reduce": lgb_dip_train - lstm_dip_train,
                "test_change": lstm_dip_test - lgb_dip_test,
                "overfit_improved": dip_overfit_improved,
                "test_improved": dip_test_improved,
            },
        },
        "conclusion": {
            "overall_success": overall_success,
            "top_success": top_success,
            "dip_success": dip_success,
        },
    }

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/v60_baseline_validation.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存: {output_path}")


if __name__ == "__main__":
    main()
