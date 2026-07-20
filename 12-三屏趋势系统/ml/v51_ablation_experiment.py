"""V5.1 消融实验：仅保留3个核心特征，移除5个低效特征

核心特征（保留）：
  - vol_regime_ratio        (#1, 238.7)
  - months_since_cycle_peak (#2, 183.3)
  - drawdown_vs_hist_avg    (#4, 178.5)

低效特征（移除）：
  - cycle_phase             (#59, 5.5)
  - drawdown_from_cycle_peak (#36, 37.8)
  - bear_phase_progress     (#19, 64.3)
  - cycle_path_similarity   (#47, 21.5)
  - bear_severity_score     (#41, 33.3)
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


# V5.1 核心特征（保留）
V51_CORE_FEATURES = [
    "vol_regime_ratio",
    "months_since_cycle_peak",
    "drawdown_vs_hist_avg",
]

# V5.1 低效特征（移除）
V51_LOW_EFFICACY_FEATURES = [
    "cycle_phase",
    "drawdown_from_cycle_peak",
    "bear_phase_progress",
    "cycle_path_similarity",
    "bear_severity_score",
]


def load_btc_data() -> pd.DataFrame:
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def generate_top_exit_labels(closes, lookahead=20, threshold=0.20):
    n = len(closes)
    labels = np.zeros(n)
    for i in range(n - lookahead):
        future = closes[i + lookahead]
        if (closes[i] - future) / closes[i] > threshold:
            labels[i] = 1
    return labels


def walk_forward_validation(features, labels, feature_names,
                            n_splits=12, train_days=730, test_days=180, step_days=180):
    n = len(features)
    feature_importances = []
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
        X_train = features.iloc[tr_s:tr_e][feature_names].values
        y_train = labels[tr_s:tr_e]
        X_test = features.iloc[te_s:te_e][feature_names].values
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
            feature_importances.append(model.feature_importances_)

    avg_test_auc = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train_auc = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay_rate = 1.0 - (avg_test_auc / avg_train_auc) if avg_train_auc > 0 else 0.0
    avg_importances = np.mean(feature_importances, axis=0) if feature_importances else np.zeros(len(feature_names))

    return {
        "avg_test_auc": avg_test_auc,
        "avg_train_auc": avg_train_auc,
        "decay_rate": float(decay_rate),
        "n_folds": len(test_aucs),
        "feature_importances": avg_importances.tolist(),
    }


def main():
    print("=" * 80)
    print("  V5.1 消融实验：核心3特征 vs 全部8特征 vs V4基线")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values

    # 提取全部特征
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    all_features = pd.concat([trend_features, phil_features], axis=1)
    all_features = all_features.fillna(0.0).replace([np.inf, -np.inf], 0.0)

    labels = generate_top_exit_labels(closes, lookahead=20, threshold=0.20)
    print("\n数据: {}天, 正样本率: {:.1f}%".format(len(prices), labels.sum() / len(labels) * 100))

    # 三组对比
    experiments = {
        "V4基线(74维)": [c for c in all_features.columns
                        if c not in V51_LOW_EFFICACY_FEATURES + V51_CORE_FEATURES + ["rsi_14", "volume_ratio_20d"]],
        "V5.1全部(84维)": all_features.columns.tolist(),
        "V5.1核心3特征(77维)": [c for c in all_features.columns
                              if c not in V51_LOW_EFFICACY_FEATURES],
    }

    print("\n{:<25} | {:>10} | {:>10} | {:>10} | {:>8}".format(
        "实验", "特征数", "测试AUC", "训练AUC", "衰减率"))
    print("-" * 75)

    results = {}
    for name, feat_names in experiments.items():
        t0 = time.time()
        result = walk_forward_validation(all_features, labels, feat_names)
        elapsed = time.time() - t0
        print("{:<25} | {:>10} | {:>10.4f} | {:>10.4f} | {:>7.1f}%  ({:.1f}s)".format(
            name, len(feat_names), result["avg_test_auc"], result["avg_train_auc"],
            result["decay_rate"] * 100, elapsed))
        results[name] = result

    # 核心特征重要性
    print("\n【V5.1核心3特征在77维模型中的重要性】")
    core_result = results["V5.1核心3特征(77维)"]
    importances = np.array(core_result["feature_importances"])
    feat_names = experiments["V5.1核心3特征(77维)"]
    ranking = np.argsort(-importances)
    for fname in V51_CORE_FEATURES:
        if fname in feat_names:
            idx = feat_names.index(fname)
            rank = np.where(ranking == idx)[0][0] + 1
            print("  {:>30}: 排名#{:>3}, 重要性 {:.1f}".format(
                fname, rank, importances[idx]))

    # 决策
    print("\n" + "=" * 80)
    print("  消融实验结论")
    print("=" * 80)
    baseline_auc = results["V4基线(74维)"]["avg_test_auc"]
    full_auc = results["V5.1全部(84维)"]["avg_test_auc"]
    core_auc = results["V5.1核心3特征(77维)"]["avg_test_auc"]

    print("  V4基线 AUC:      {:.4f}".format(baseline_auc))
    print("  V5.1全部 AUC:    {:.4f} (Δ{:+.4f})".format(full_auc, full_auc - baseline_auc))
    print("  V5.1核心3 AUC:   {:.4f} (Δ{:+.4f})".format(core_auc, core_auc - baseline_auc))

    if core_auc >= baseline_auc:
        print("\n  ✅ 决策：保留3个核心V5.1特征，移除5个低效特征")
        print("     理由：核心3特征模型 AUC >= V4基线，特征有效")
    elif core_auc > full_auc:
        print("\n  ⚠️ 决策：保留3个核心V5.1特征，但AUC仍低于V4基线")
        print("     建议：进一步优化或回退")
    else:
        print("\n  ❌ 决策：回退V5.1特征")

    # 保存结果
    output = {
        "baseline_auc": baseline_auc,
        "full_v51_auc": full_auc,
        "core_v51_auc": core_auc,
        "core_features": V51_CORE_FEATURES,
        "low_efficacy_features": V51_LOW_EFFICACY_FEATURES,
        "decision": "keep_core" if core_auc >= baseline_auc else ("keep_core_warn" if core_auc > full_auc else "rollback"),
    }
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/v51_ablation_result.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print("\n结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
