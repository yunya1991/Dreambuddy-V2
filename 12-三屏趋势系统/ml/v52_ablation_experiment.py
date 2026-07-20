"""V5.2 消融实验：仅保留核心美联储特征

核心特征（保留）：
  - fed_months_in_cycle  (TOP_EXIT #1, DIP_BUY #1)
  - fed_easing_btc_dip   (DIP_BUY #24, 抄底信号)

低效特征（移除）：
  - fed_rate_action      (TOP_EXIT #61, DIP_BUY #59)
  - fed_rate_level       (TOP_EXIT #38, DIP_BUY #46)
  - fed_hawkish_top      (TOP_EXIT #48, DIP_BUY #77, 非零占比仅2.2%)
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ml.feature_engineer import TrendFeatureEngineer
from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer


V52_CORE = ["fed_months_in_cycle", "fed_easing_btc_dip"]
V52_LOW = ["fed_rate_action", "fed_rate_level", "fed_hawkish_top"]


def load_btc_data():
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def generate_labels(closes, lookahead, threshold, mode="drop"):
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


def walk_forward(features, labels, feat_names,
                 n_splits=12, train_days=730, test_days=180, step_days=180):
    n = len(features)
    importances = []
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
        X_train = features.iloc[tr_s:tr_e][feat_names].values
        y_train = labels[tr_s:tr_e]
        X_test = features.iloc[te_s:te_e][feat_names].values
        y_test = labels[te_s:te_e]

        if y_train.sum() < 5 or y_test.sum() < 2:
            continue

        model = lgb.LGBMClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.05,
            num_leaves=31, min_child_samples=20,
            subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbose=-1,
        )
        model.fit(X_train, y_train)

        train_pred = model.predict_proba(X_train)[:, 1]
        test_pred = model.predict_proba(X_test)[:, 1]

        if len(set(y_train)) > 1:
            train_aucs.append(roc_auc_score(y_train, train_pred))
        if len(set(y_test)) > 1:
            test_aucs.append(roc_auc_score(y_test, test_pred))
            importances.append(model.feature_importances_)

    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0
    avg_imp = np.mean(importances, axis=0) if importances else np.zeros(len(feat_names))

    return {"avg_test_auc": avg_test, "avg_train_auc": avg_train,
            "decay_rate": float(decay), "n_folds": len(test_aucs),
            "feature_importances": avg_imp.tolist()}


def main():
    print("=" * 80)
    print("  V5.2 消融实验：核心2特征 vs 全部5特征 vs V4基线")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values

    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    all_features = pd.concat([trend_features, phil_features], axis=1)
    all_features = all_features.fillna(0.0).replace([np.inf, -np.inf], 0.0)

    experiments = {
        "V4基线": [c for c in all_features.columns if c not in V52_CORE + V52_LOW],
        "V5.2全部": all_features.columns.tolist(),
        "V5.2核心2特征": [c for c in all_features.columns if c not in V52_LOW],
    }

    scenarios = [
        ("TOP_EXIT", "drop", 20, 0.20),
        ("DIP_BUY", "rise", 30, 0.30),
    ]

    all_results = {}
    for scenario_name, mode, lookahead, threshold in scenarios:
        print("\n--- {} 场景 ---".format(scenario_name))
        labels = generate_labels(closes, lookahead, threshold, mode)
        print("  正样本率: {:.1f}%".format(labels.sum() / len(labels) * 100))

        print("  {:<20} | {:>6} | {:>10} | {:>10} | {:>8}".format(
            "实验", "特征数", "测试AUC", "训练AUC", "衰减率"))
        print("  " + "-" * 62)

        scenario_results = {}
        for name, feat_names in experiments.items():
            t0 = time.time()
            r = walk_forward(all_features, labels, feat_names)
            elapsed = time.time() - t0
            print("  {:<20} | {:>6} | {:>10.4f} | {:>10.4f} | {:>7.1f}%  ({:.1f}s)".format(
                name, len(feat_names), r["avg_test_auc"], r["avg_train_auc"],
                r["decay_rate"] * 100, elapsed))
            scenario_results[name] = r

        all_results[scenario_name] = scenario_results

    # 决策
    print("\n" + "=" * 80)
    print("  消融实验结论")
    print("=" * 80)

    for scenario_name in ["TOP_EXIT", "DIP_BUY"]:
        baseline = all_results[scenario_name]["V4基线"]["avg_test_auc"]
        full = all_results[scenario_name]["V5.2全部"]["avg_test_auc"]
        core = all_results[scenario_name]["V5.2核心2特征"]["avg_test_auc"]
        print("\n  {} 场景:".format(scenario_name))
        print("    V4基线      AUC: {:.4f}".format(baseline))
        print("    V5.2全部    AUC: {:.4f} (Δ{:+.4f})".format(full, full - baseline))
        print("    V5.2核心2   AUC: {:.4f} (Δ{:+.4f})".format(core, core - baseline))

        if core >= baseline:
            print("    → ✅ 保留核心2特征（fed_months_in_cycle + fed_easing_btc_dip）")
        elif full >= baseline:
            print("    → ⚠️ 保留全部5特征")
        else:
            print("    → ❌ 回退V5.2特征")

    # 保存
    output = {
        "experiments": {s: {n: {"avg_test_auc": r["avg_test_auc"], "avg_train_auc": r["avg_train_auc"],
                                 "decay_rate": r["decay_rate"], "n_folds": r["n_folds"]}
                             for n, r in rs.items()} for s, rs in all_results.items()},
        "core_features": V52_CORE,
        "low_efficacy_features": V52_LOW,
    }
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/v52_ablation_result.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print("\n结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
