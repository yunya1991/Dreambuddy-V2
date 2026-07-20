"""V5.2 美联储利率周期特征 Walk-Forward 验证

验证内容：
1. 特征计算正确性（5个美联储特征）
2. DIP_BUY + TOP_EXIT 场景 Walk-Forward 验证
3. 与V4基线对比（74维 vs 79维），决定是否保留
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


# V5.2 新增特征
V52_FEATURES = [
    "fed_rate_action",
    "fed_months_in_cycle",
    "fed_rate_level",
    "fed_easing_btc_dip",
    "fed_hawkish_top",
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


def generate_labels(closes, lookahead, threshold, mode="drop"):
    """生成标签
    mode='drop': 未来lookahead日跌幅>threshold → 1（TOP_EXIT）
    mode='rise': 未来lookahead日涨幅>threshold → 1（DIP_BUY/BEAR_EXIT）
    """
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
    print("  V5.2 美联储利率周期特征 Walk-Forward 验证")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    print("\n数据: {}天, {} ~ {}".format(
        len(prices), prices.index[0].date(), prices.index[-1].date()))

    # 1. 提取特征
    print("\n【1. 提取特征】")
    t0 = time.time()
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()
    print("  趋势特征: {}维, {:.1f}s".format(trend_features.shape[1], time.time() - t0))

    t0 = time.time()
    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")
    print("  哲学特征: {}维, {:.1f}s".format(phil_features.shape[1], time.time() - t0))

    all_features = pd.concat([trend_features, phil_features], axis=1)
    all_features = all_features.fillna(0.0).replace([np.inf, -np.inf], 0.0)
    print("  总特征: {}维".format(all_features.shape[1]))

    # 2. V5.2特征数值校验
    print("\n【2. V5.2特征数值校验】")
    for fname in V52_FEATURES:
        if fname in all_features.columns:
            vals = all_features[fname]
            print("  {:>25}: min={:>8.2f}, max={:>8.2f}, mean={:>8.2f}, 非零占比={:.1f}%".format(
                fname, vals.min(), vals.max(), vals.mean(),
                (vals != 0).sum() / len(vals) * 100))

    # 3. 三组对比实验
    print("\n【3. 三组对比实验】")

    # V4基线：不含V5.2的5个特征
    v4_features = [c for c in all_features.columns if c not in V52_FEATURES]
    # V5.2全部：含5个美联储特征
    v52_features = all_features.columns.tolist()

    experiments = {
        "V4基线(74维)": v4_features,
        "V5.2全部(79维)": v52_features,
    }

    # 场景列表
    scenarios = [
        ("TOP_EXIT", "drop", 20, 0.20),
        ("DIP_BUY", "rise", 30, 0.30),
    ]

    all_results = {}
    for scenario_name, mode, lookahead, threshold in scenarios:
        print("\n--- {} 场景 ---".format(scenario_name))
        labels = generate_labels(closes, lookahead, threshold, mode)
        pos_rate = labels.sum() / len(labels) * 100
        print("  正样本率: {:.1f}%".format(pos_rate))

        print("  {:<20} | {:>8} | {:>10} | {:>10} | {:>8}".format(
            "实验", "特征数", "测试AUC", "训练AUC", "衰减率"))
        print("  " + "-" * 65)

        scenario_results = {}
        for name, feat_names in experiments.items():
            t0 = time.time()
            result = walk_forward_validation(all_features, labels, feat_names)
            elapsed = time.time() - t0
            print("  {:<20} | {:>8} | {:>10.4f} | {:>10.4f} | {:>7.1f}%  ({:.1f}s)".format(
                name, len(feat_names), result["avg_test_auc"], result["avg_train_auc"],
                result["decay_rate"] * 100, elapsed))
            scenario_results[name] = result

        # V5.2特征重要性排名
        print("\n  V5.2特征在{}场景的重要性排名:".format(scenario_name))
        v52_result = scenario_results["V5.2全部(79维)"]
        importances = np.array(v52_result["feature_importances"])
        ranking = np.argsort(-importances)
        for fname in V52_FEATURES:
            if fname in v52_features:
                idx = v52_features.index(fname)
                rank = np.where(ranking == idx)[0][0] + 1
                imp = importances[idx]
                print("    {:>25}: 排名#{:>3}, 重要性 {:.1f}".format(fname, rank, imp))

        all_results[scenario_name] = scenario_results

    # 4. 决策
    print("\n" + "=" * 80)
    print("  V5.2 验证结论")
    print("=" * 80)

    for scenario_name in ["TOP_EXIT", "DIP_BUY"]:
        baseline_auc = all_results[scenario_name]["V4基线(74维)"]["avg_test_auc"]
        v52_auc = all_results[scenario_name]["V5.2全部(79维)"]["avg_test_auc"]
        diff = v52_auc - baseline_auc
        status = "✅ 保留" if diff >= 0 else "❌ 回退"
        print("  {} AUC: V4基线={:.4f}, V5.2={:.4f}, Δ={:+.4f} → {}".format(
            scenario_name, baseline_auc, v52_auc, diff, status))

    # 5. 保存结果
    output = {
        "validation_date": str(prices.index[-1].date()),
        "v52_features": V52_FEATURES,
        "scenarios": {},
    }
    for scenario_name, scenario_results in all_results.items():
        output["scenarios"][scenario_name] = {
            name: {
                "avg_test_auc": r["avg_test_auc"],
                "avg_train_auc": r["avg_train_auc"],
                "decay_rate": r["decay_rate"],
                "n_folds": r["n_folds"],
            }
            for name, r in scenario_results.items()
        }

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/v52_fed_rate_result.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print("\n结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
