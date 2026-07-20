"""V5.1 周期相似性特征验证脚本

验证内容：
1. 特征计算正确性（8个新特征）
2. Walk-Forward 回测验证（TOP_EXIT + BEAR_EXIT 场景）
3. 与V4基线对比，决定是否保留
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
sys.path.insert(0, os.path.dirname(BASE_DIR))

from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer
from ml.four_objective_feature_mapper import FourObjectiveFeatureMapper, ObjectiveType


def load_btc_data() -> pd.DataFrame:
    """加载BTC日线数据"""
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )
    return prices


def load_trend_features(prices: pd.DataFrame) -> pd.DataFrame:
    """加载趋势特征（三重滤网）"""
    try:
        from ml.feature_engineer import TrendFeatureEngineer
        trend_fe = TrendFeatureEngineer()
        trend_df = trend_fe.create_features(prices, label_lookahead=20)
        trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
        trend_features = trend_df[trend_cols].copy()
        return trend_features
    except Exception as e:
        print("  [警告] 无法加载趋势特征: {}".format(e))
        return pd.DataFrame(index=prices.index)


def generate_top_exit_labels(closes: np.ndarray, lookahead: int = 20, threshold: float = 0.20) -> np.ndarray:
    """TOP_EXIT标签：未来20日收盘价跌幅>20% → 1"""
    n = len(closes)
    labels = np.zeros(n)
    for i in range(n - lookahead):
        future_close = closes[i + lookahead]
        drop_pct = (closes[i] - future_close) / closes[i]
        if drop_pct > threshold:
            labels[i] = 1
    return labels


def generate_bear_exit_labels(closes: np.ndarray, lookahead: int = 30, threshold: float = 0.30) -> np.ndarray:
    """BEAR_EXIT标签：未来30日涨幅>30% → 1（做空平仓信号）"""
    n = len(closes)
    labels = np.zeros(n)
    for i in range(n - lookahead):
        future_close = closes[i + lookahead]
        rise_pct = (future_close - closes[i]) / closes[i]
        if rise_pct > threshold:
            labels[i] = 1
    return labels


def walk_forward_validation(
    features: pd.DataFrame,
    labels: np.ndarray,
    feature_names: list,
    n_splits: int = 12,
    train_days: int = 730,
    test_days: int = 180,
    step_days: int = 180,
):
    """Walk-Forward 验证"""
    n = len(features)
    feature_importances = []
    train_aucs = []
    test_aucs = []

    # 倒序生成折（最近的放在最后）
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

    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        X_train = features.iloc[tr_s:tr_e][feature_names].values
        y_train = labels[tr_s:tr_e]
        X_test = features.iloc[te_s:te_e][feature_names].values
        y_test = labels[te_s:te_e]

        # 跳过正样本不足的折
        if y_train.sum() < 5 or y_test.sum() < 2:
            continue

        model = lgb.LGBMClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1,
        )
        model.fit(X_train, y_train)

        # 训练集AUC
        train_pred = model.predict_proba(X_train)[:, 1]
        if len(set(y_train)) > 1:
            train_auc = roc_auc_score(y_train, train_pred)
        else:
            train_auc = 0.5

        # 测试集AUC
        test_pred = model.predict_proba(X_test)[:, 1]
        if len(set(y_test)) > 1:
            test_auc = roc_auc_score(y_test, test_pred)
        else:
            test_auc = 0.5

        train_aucs.append(train_auc)
        test_aucs.append(test_auc)
        feature_importances.append(model.feature_importances_)

    avg_test_auc = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train_auc = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay_rate = 1.0 - (avg_test_auc / avg_train_auc) if avg_train_auc > 0 else 0.0

    # 跨折平均特征重要性
    avg_importances = np.mean(feature_importances, axis=0) if feature_importances else np.zeros(len(feature_names))
    importance_rank = np.argsort(-avg_importances)

    return {
        "avg_test_auc": avg_test_auc,
        "avg_train_auc": avg_train_auc,
        "decay_rate": float(decay_rate),
        "n_folds": len(test_aucs),
        "feature_importances": avg_importances.tolist(),
        "feature_ranking": importance_rank.tolist(),
    }


def main():
    print("=" * 80)
    print("  V5.1 周期相似性特征 Walk-Forward 验证")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    print("\n数据: {}天, {} ~ {}".format(
        len(prices), prices.index[0].date(), prices.index[-1].date()))

    # 1. 计算哲学特征（含V5.1新增8个）
    print("\n【1. 计算哲学特征（V5.1 = 24 + 8 = 32维）】")
    t0 = time.time()
    philosopher = PhilosophyFeatureEngineer()
    phil_feats = philosopher.extract_series(prices, symbol="BTC")
    print("  哲学特征: {}维, 耗时 {:.1f}s".format(phil_feats.shape[1], time.time() - t0))

    # 2. 计算趋势特征
    print("\n【2. 计算趋势特征】")
    t0 = time.time()
    trend_feats = load_trend_features(prices)
    print("  趋势特征: {}维, 耗时 {:.1f}s".format(trend_feats.shape[1], time.time() - t0))

    # 3. 合并特征
    all_feats = pd.concat([trend_feats, phil_feats], axis=1)
    all_feats = all_feats.fillna(0.0)
    all_feats = all_feats.replace([np.inf, -np.inf], 0.0)
    closes_valid = closes  # 完整序列，特征已对齐
    print("\n【3. 合并特征】总维度: {}, 有效行: {}".format(all_feats.shape[1], all_feats.shape[0]))

    # 4. V5.1新增特征数值合理性校验
    print("\n【4. V5.1新增特征数值合理性校验】")
    v51_features = [
        "cycle_phase", "drawdown_from_cycle_peak", "months_since_cycle_peak", "bear_phase_progress",
        "drawdown_vs_hist_avg", "cycle_path_similarity", "vol_regime_ratio", "bear_severity_score",
    ]
    for fname in v51_features:
        if fname in all_feats.columns:
            vals = all_feats[fname]
            print("  {:>30}: min={:>8.2f}, max={:>8.2f}, mean={:>8.2f}".format(
                fname, vals.min(), vals.max(), vals.mean()))

    # 当前时点特征值
    print("\n  当前时点({})特征值:".format(str(prices.index[-1].date())))
    for fname in v51_features:
        if fname in all_feats.columns:
            val = all_feats[fname].iloc[-1]
            print("    {:>30}: {:.4f}".format(fname, val))

    # 5. TOP_EXIT场景 Walk-Forward
    print("\n【5. TOP_EXIT场景 Walk-Forward验证】")
    top_exit_labels = generate_top_exit_labels(closes_valid, lookahead=20, threshold=0.20)
    pos_rate = top_exit_labels.sum() / len(top_exit_labels) * 100
    print("  正样本率: {:.1f}%".format(pos_rate))

    feature_names = all_feats.columns.tolist()
    t0 = time.time()
    top_exit_result = walk_forward_validation(
        all_feats, top_exit_labels, feature_names,
        n_splits=12, train_days=730, test_days=180, step_days=180
    )
    print("  平均训练AUC: {:.4f}".format(top_exit_result["avg_train_auc"]))
    print("  平均测试AUC: {:.4f}".format(top_exit_result["avg_test_auc"]))
    print("  AUC衰减率: {:.1f}%".format(top_exit_result["decay_rate"] * 100))
    print("  有效折数: {}".format(top_exit_result["n_folds"]))
    print("  耗时: {:.1f}s".format(time.time() - t0))

    # V5.1特征在TOP_EXIT场景的排名
    print("\n  V5.1特征在TOP_EXIT场景的重要性排名:")
    importances = np.array(top_exit_result["feature_importances"])
    ranking = np.argsort(-importances)
    for fname in v51_features:
        if fname in feature_names:
            idx = feature_names.index(fname)
            rank = np.where(ranking == idx)[0][0] + 1
            imp = importances[idx]
            print("    {:>30}: 排名#{:>3}, 重要性 {:.1f}".format(fname, rank, imp))

    # 6. BEAR_EXIT场景 Walk-Forward
    print("\n【6. BEAR_EXIT场景 Walk-Forward验证】")
    bear_exit_labels = generate_bear_exit_labels(closes_valid, lookahead=30, threshold=0.30)
    pos_rate_be = bear_exit_labels.sum() / len(bear_exit_labels) * 100
    print("  正样本率: {:.1f}%".format(pos_rate_be))

    t0 = time.time()
    bear_exit_result = walk_forward_validation(
        all_feats, bear_exit_labels, feature_names,
        n_splits=12, train_days=730, test_days=180, step_days=180
    )
    print("  平均训练AUC: {:.4f}".format(bear_exit_result["avg_train_auc"]))
    print("  平均测试AUC: {:.4f}".format(bear_exit_result["avg_test_auc"]))
    print("  AUC衰减率: {:.1f}%".format(bear_exit_result["decay_rate"] * 100))
    print("  有效折数: {}".format(bear_exit_result["n_folds"]))
    print("  耗时: {:.1f}s".format(time.time() - t0))

    # V5.1特征在BEAR_EXIT场景的排名
    print("\n  V5.1特征在BEAR_EXIT场景的重要性排名:")
    importances_be = np.array(bear_exit_result["feature_importances"])
    ranking_be = np.argsort(-importances_be)
    for fname in v51_features:
        if fname in feature_names:
            idx = feature_names.index(fname)
            rank = np.where(ranking_be == idx)[0][0] + 1
            imp = importances_be[idx]
            print("    {:>30}: 排名#{:>3}, 重要性 {:.1f}".format(fname, rank, imp))

    # 7. 保存结果
    result = {
        "validation_date": str(prices.index[-1].date()),
        "total_features": len(feature_names),
        "v51_features": v51_features,
        "top_exit": {
            "avg_test_auc": top_exit_result["avg_test_auc"],
            "avg_train_auc": top_exit_result["avg_train_auc"],
            "decay_rate": top_exit_result["decay_rate"],
            "n_folds": top_exit_result["n_folds"],
            "positive_rate": float(pos_rate),
        },
        "bear_exit": {
            "avg_test_auc": bear_exit_result["avg_test_auc"],
            "avg_train_auc": bear_exit_result["avg_train_auc"],
            "decay_rate": bear_exit_result["decay_rate"],
            "n_folds": bear_exit_result["n_folds"],
            "positive_rate": float(pos_rate_be),
        },
        "v51_top_exit_ranks": {
            fname: int(np.where(ranking == feature_names.index(fname))[0][0] + 1)
            for fname in v51_features if fname in feature_names
        },
        "v51_bear_exit_ranks": {
            fname: int(np.where(ranking_be == feature_names.index(fname))[0][0] + 1)
            for fname in v51_features if fname in feature_names
        },
    }

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/v51_cycle_similarity_result.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print("\n结果已保存: {}".format(output_path))

    # 8. 决策结论
    print("\n" + "=" * 80)
    print("  V5.1 验证结论")
    print("=" * 80)
    # 基线参考：Stage 1 TOP_EXIT改进标签 AUC=0.69
    baseline_top_exit_auc = 0.69
    cur_top_exit_auc = top_exit_result["avg_test_auc"]
    if cur_top_exit_auc >= baseline_top_exit_auc:
        print("  TOP_EXIT AUC: {:.4f} >= 基线 {:.4f} → ✅ 保留V5.1特征".format(
            cur_top_exit_auc, baseline_top_exit_auc))
    else:
        print("  TOP_EXIT AUC: {:.4f} < 基线 {:.4f} → ❌ 建议回退V5.1特征".format(
            cur_top_exit_auc, baseline_top_exit_auc))


if __name__ == "__main__":
    main()
