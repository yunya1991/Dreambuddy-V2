"""Stage 2: DIP_BUY 抄底优化 — Walk-Forward 验证

目标：
    1. 验证 V2 哲学特征在 DIP_BUY 场景的特征重要性排名
    2. 测试假设 DIP-001: 周线MA200附近 + 日线RSI<30 + 成交量放大 = 高质量抄底点
    3. 与 V4 基线对比，确认抄底优化方向

DIP_BUY 标签规则：
    未来20日涨幅 > 15% 且 期间最大回撤 < 10% → 1（优质抄底点）

V2 哲学抄底特征（核心验证对象）：
    - weekly_ma200_distance: 价格相对周线MA200的距离
    - dip_buy_level: 当前已触发的抄底档位 (0-4)
    - dip_buy_position_ratio: 抄底建议仓位比例
    - left_side_buy_signal: 左侧抄底信号强度

成功标准：
    V2 抄底特征平均排名在 top 30%，且 DIP_BUY 测试 AUC > 0.60
"""

import json
import sys
import os
import warnings
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ml.feature_engineer import TrendFeatureEngineer
from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer
from ml.four_objective_feature_mapper import FourObjectiveFeatureMapper


# ── V2 抄底哲学特征 ──────────────────────────────────────────────
V2_DIP_FEATURES = [
    "weekly_ma200_distance",
    "dip_buy_level",
    "dip_buy_position_ratio",
    "left_side_buy_signal",
]

# Stage 2.1 新增量价抄底特征
DIP_001_FEATURES = [
    "rsi_14",
    "volume_ratio_20d",
]

V2_OTHER_PHILOSOPHY = [
    "btc_regime_label", "btc_alt_divergence", "is_btc_asset", "alt_short_risk_score",
    "bear_short_layer", "fib_tp_remaining_ratio", "layered_position_target", "position_adjustment",
    "btc_bull_confirmed", "self_bull_confirmed", "double_bull_score",
]

V4_FEATURES = [
    "halving_months_after", "halving_phase", "halving_position_cap",
    "ma128_distance_pct", "ma128_below_days",
    "ath_drawdown_pct", "bounce_from_low_pct",
]

ALL_PHILOSOPHY = V2_DIP_FEATURES + DIP_001_FEATURES + V2_OTHER_PHILOSOPHY + V4_FEATURES


def load_btc_data() -> pd.DataFrame:
    """加载 BTC 日线数据"""
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )
    return prices


def extract_all_features(prices: pd.DataFrame) -> pd.DataFrame:
    """提取全部特征（趋势52维 + 哲学22维 = 74维）"""
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    all_features = pd.concat([trend_features, phil_features], axis=1)
    all_features = all_features.fillna(0.0)
    all_features = all_features.replace([np.inf, -np.inf], 0.0)

    return all_features


def walk_forward_validation(
    features: pd.DataFrame,
    labels: pd.Series,
    train_window: int = 730,
    test_window: int = 180,
    step_size: int = 180,
) -> dict:
    """Walk-Forward 滚动验证"""
    n = len(features)
    feature_names = list(features.columns)
    n_features = len(feature_names)

    folds = []
    all_importances = []

    start = 0
    fold_idx = 0

    while start + train_window + test_window <= n:
        fold_idx += 1
        train_end = start + train_window
        test_end = train_end + test_window

        X_train = features.iloc[start:train_end].values
        y_train = labels.iloc[start:train_end].values
        X_test = features.iloc[train_end:test_end].values
        y_test = labels.iloc[train_end:test_end].values

        if y_train.sum() < 5 or y_test.sum() < 2:
            start += step_size
            continue

        params = {
            "objective": "binary", "metric": "binary_logloss", "boosting_type": "gbdt",
            "num_leaves": 31, "learning_rate": 0.05, "feature_fraction": 0.8,
            "bagging_fraction": 0.8, "bagging_freq": 5, "min_data_in_leaf": 20,
            "verbose": -1, "random_state": 42,
        }

        train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_names)
        valid_data = lgb.Dataset(X_test, label=y_test, feature_name=feature_names, reference=train_data)

        model = lgb.train(
            params, train_data, num_boost_round=200,
            valid_sets=[train_data, valid_data], valid_names=["train", "valid"],
            callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(0)],
        )

        y_train_pred = model.predict(X_train)
        y_test_pred = model.predict(X_test)

        train_auc = roc_auc_score(y_train, y_train_pred) if len(np.unique(y_train)) > 1 else 0.5
        test_auc = roc_auc_score(y_test, y_test_pred) if len(np.unique(y_test)) > 1 else 0.5

        y_test_binary = (y_test_pred > 0.5).astype(int)
        test_acc = accuracy_score(y_test, y_test_binary)
        test_precision = precision_score(y_test, y_test_binary, zero_division=0)
        test_recall = recall_score(y_test, y_test_binary, zero_division=0)

        importance = model.feature_importance(importance_type="gain")
        importance_dict = dict(zip(feature_names, importance))
        all_importances.append(importance_dict)

        train_dates = (features.index[start], features.index[train_end - 1])
        test_dates = (features.index[train_end], features.index[test_end - 1])

        fold_result = {
            "fold": fold_idx,
            "train_period": f"{train_dates[0].date()} ~ {train_dates[1].date()}",
            "test_period": f"{test_dates[0].date()} ~ {test_dates[1].date()}",
            "train_samples": len(y_train),
            "test_samples": len(y_test),
            "train_positives": int(y_train.sum()),
            "test_positives": int(y_test.sum()),
            "train_auc": train_auc,
            "test_auc": test_auc,
            "test_accuracy": test_acc,
            "test_precision": test_precision,
            "test_recall": test_recall,
            "best_iteration": model.best_iteration,
        }
        folds.append(fold_result)

        print("  Fold {}: {}~{} | train_auc={:.4f} test_auc={:.4f} | pos={}/{} | iter={}".format(
            fold_idx, test_dates[0].date(), test_dates[1].date(),
            train_auc, test_auc, int(y_test.sum()), len(y_test), model.best_iteration))

        start += step_size

    # 跨折平均特征重要性
    avg_importance = {}
    for feat in feature_names:
        values = [imp.get(feat, 0) for imp in all_importances]
        avg_importance[feat] = np.mean(values)

    sorted_features = sorted(avg_importance.items(), key=lambda x: x[1], reverse=True)
    ranking = {feat: rank + 1 for rank, (feat, _) in enumerate(sorted_features)}

    oos_aucs = [f["test_auc"] for f in folds]
    is_aucs = [f["train_auc"] for f in folds]

    summary = {
        "n_folds": len(folds),
        "n_features": n_features,
        "train_window": train_window,
        "test_window": test_window,
        "folds": folds,
        "avg_importance": avg_importance,
        "ranking": ranking,
        "sorted_features": sorted_features,
        "mean_train_auc": np.mean(is_aucs) if is_aucs else 0,
        "mean_test_auc": np.mean(oos_aucs) if oos_aucs else 0,
        "std_test_auc": np.std(oos_aucs) if oos_aucs else 0,
        "min_test_auc": np.min(oos_aucs) if oos_aucs else 0,
        "max_test_auc": np.max(oos_aucs) if oos_aucs else 0,
        "decay_ratio": (np.mean(is_aucs) - np.mean(oos_aucs)) / np.mean(is_aucs) * 100 if is_aucs and np.mean(is_aucs) > 0 else 0,
    }

    return summary


def analyze_dip_buy_features(summary: dict) -> dict:
    """分析 DIP_BUY 场景下 V2 抄底特征和 Stage 2.1 新特征的排名"""
    n_features = summary["n_features"]
    ranking = summary["ranking"]
    avg_importance = summary["avg_importance"]

    top_30_threshold = int(n_features * 0.3)

    v2_dip_ranks = {f: ranking[f] for f in V2_DIP_FEATURES}
    dip001_ranks = {f: ranking[f] for f in DIP_001_FEATURES}
    v2_other_ranks = {f: ranking[f] for f in V2_OTHER_PHILOSOPHY}
    v4_ranks = {f: ranking[f] for f in V4_FEATURES}

    v2_dip_avg = np.mean(list(v2_dip_ranks.values()))
    dip001_avg = np.mean(list(dip001_ranks.values()))
    v2_other_avg = np.mean(list(v2_other_ranks.values()))
    v4_avg = np.mean(list(v4_ranks.values()))

    v2_dip_in_top30 = sum(1 for r in v2_dip_ranks.values() if r <= top_30_threshold)
    dip001_in_top30 = sum(1 for r in dip001_ranks.values() if r <= top_30_threshold)
    v2_other_in_top30 = sum(1 for r in v2_other_ranks.values() if r <= top_30_threshold)
    v4_in_top30 = sum(1 for r in v4_ranks.values() if r <= top_30_threshold)

    # 抄底特征合集（V2抄底 + DIP-001新增）
    all_dip_features = V2_DIP_FEATURES + DIP_001_FEATURES
    all_dip_avg = np.mean([ranking[f] for f in all_dip_features])
    all_dip_in_top30 = sum(1 for f in all_dip_features if ranking[f] <= top_30_threshold)

    # 趋势特征排名
    trend_features = [f for f in ranking if f not in ALL_PHILOSOPHY]
    trend_avg_rank = np.mean([ranking[f] for f in trend_features])

    result = {
        "n_features": n_features,
        "top_30_threshold": top_30_threshold,
        "v2_dip_ranks": v2_dip_ranks,
        "v2_dip_importances": {f: avg_importance[f] for f in V2_DIP_FEATURES},
        "v2_dip_avg_rank": v2_dip_avg,
        "v2_dip_in_top30": v2_dip_in_top30,
        "dip001_ranks": dip001_ranks,
        "dip001_importances": {f: avg_importance[f] for f in DIP_001_FEATURES},
        "dip001_avg_rank": dip001_avg,
        "dip001_in_top30": dip001_in_top30,
        "all_dip_avg_rank": all_dip_avg,
        "all_dip_in_top30": all_dip_in_top30,
        "v2_other_ranks": v2_other_ranks,
        "v2_other_avg_rank": v2_other_avg,
        "v2_other_in_top30": v2_other_in_top30,
        "v4_ranks": v4_ranks,
        "v4_avg_rank": v4_avg,
        "v4_in_top30": v4_in_top30,
        "trend_avg_rank": trend_avg_rank,
        "success": all_dip_avg <= top_30_threshold,
    }

    return result


def print_report(summary: dict, analysis: dict, pos_rate: float):
    """打印验证报告"""
    print("\n" + "=" * 80)
    print("  Stage 2: DIP_BUY 抄底优化 Walk-Forward 验证报告")
    print("  V2 哲学特征在抄底场景的特征重要性验证")
    print("=" * 80)

    # 1. Walk-Forward 概况
    print("\n【1. Walk-Forward 验证概况】")
    print("  总特征数: {}".format(summary["n_features"]))
    print("  验证折数: {}".format(summary["n_folds"]))
    print("  训练窗口: {}天 | 测试窗口: {}天".format(summary["train_window"], summary["test_window"]))
    print("  DIP_BUY正样本率: {:.1f}%".format(pos_rate))
    print("  平均训练AUC: {:.4f}".format(summary["mean_train_auc"]))
    print("  平均测试AUC: {:.4f} (+/-{:.4f})".format(summary["mean_test_auc"], summary["std_test_auc"]))
    print("  最小测试AUC: {:.4f}".format(summary["min_test_auc"]))
    print("  最大测试AUC: {:.4f}".format(summary["max_test_auc"]))
    print("  AUC衰减率: {:.1f}%".format(summary["decay_ratio"]))

    # 2. 各折详情
    print("\n【2. 各折详情】")
    print("  {:>4} | {:>25} | {:>25} | {:>8} | {:>8} | {:>6}".format(
        "Fold", "训练期", "测试期", "TrainAUC", "TestAUC", "正样本"))
    print("  {} | {} | {} | {} | {} | {}".format("-"*4, "-"*25, "-"*25, "-"*8, "-"*8, "-"*6))
    for f in summary["folds"]:
        print("  {:>4} | {:>25} | {:>25} | {:>8.4f} | {:>8.4f} | {}/{}".format(
            f["fold"], f["train_period"], f["test_period"],
            f["train_auc"], f["test_auc"], f["test_positives"], f["test_samples"]))

    # 3. 特征重要性排名 Top 30
    print("\n【3. 特征重要性排名（Top 30）】")
    print("  {:>4} | {:>30} | {:>10} | {:>8}".format("排名", "特征名", "重要性", "类别"))
    print("  {} | {} | {} | {}".format("-"*4, "-"*30, "-"*10, "-"*8))
    for rank, (feat, imp) in enumerate(summary["sorted_features"][:30], 1):
        if feat in V2_DIP_FEATURES:
            category = "V2抄底"
        elif feat in DIP_001_FEATURES:
            category = "DIP001"
        elif feat in V2_OTHER_PHILOSOPHY:
            category = "V2其他"
        elif feat in V4_FEATURES:
            category = "V4新"
        else:
            category = "趋势"
        print("  {:>4} | {:>30} | {:>10.1f} | {:>8}".format(rank, feat, imp, category))

    # 4. 抄底特征分析（V2 + DIP-001）
    print("\n【4. 抄底特征排名分析（V2 + Stage 2.1新增）】")
    print("  Top 30% 阈值: 排名 <= {}".format(analysis["top_30_threshold"]))

    print("\n  V2 抄底特征（4个）:")
    print("  {:>30} | {:>6} | {:>10} | {:>6}".format("特征名", "排名", "重要性", "Top30%"))
    print("  {} | {} | {} | {}".format("-"*30, "-"*6, "-"*10, "-"*6))
    for feat in V2_DIP_FEATURES:
        rank = analysis["v2_dip_ranks"][feat]
        imp = analysis["v2_dip_importances"][feat]
        in_top = "YES" if rank <= analysis["top_30_threshold"] else "NO"
        print("  {:>30} | {:>6} | {:>10.1f} | {:>6}".format(feat, rank, imp, in_top))

    print("\n  Stage 2.1 DIP-001 新增特征（2个）:")
    print("  {:>30} | {:>6} | {:>10} | {:>6}".format("特征名", "排名", "重要性", "Top30%"))
    print("  {} | {} | {} | {}".format("-"*30, "-"*6, "-"*10, "-"*6))
    for feat in DIP_001_FEATURES:
        rank = analysis["dip001_ranks"][feat]
        imp = analysis["dip001_importances"][feat]
        in_top = "YES" if rank <= analysis["top_30_threshold"] else "NO"
        print("  {:>30} | {:>6} | {:>10.1f} | {:>6}".format(feat, rank, imp, in_top))

    all_dip = V2_DIP_FEATURES + DIP_001_FEATURES
    print("\n  抄底特征合集（6个）平均排名: {:.1f} / {}".format(analysis["all_dip_avg_rank"], analysis["n_features"]))
    print("  进入Top30%: {}/{}".format(analysis["all_dip_in_top30"], len(all_dip)))

    # 5. 四类特征对比
    print("\n【5. 四类哲学特征对比】")
    print("  {:>10} | {:>8} | {:>10} | {:>6}".format("类别", "平均排名", "进入Top30%", "占比"))
    print("  {} | {} | {} | {}".format("-"*10, "-"*8, "-"*10, "-"*6))
    print("  {:>10} | {:>8.1f} | {:>4}/{} | {:.1f}%".format(
        "V2抄底", analysis["v2_dip_avg_rank"], analysis["v2_dip_in_top30"], len(V2_DIP_FEATURES),
        analysis["v2_dip_in_top30"]/len(V2_DIP_FEATURES)*100))
    print("  {:>10} | {:>8.1f} | {:>4}/{} | {:.1f}%".format(
        "DIP001新", analysis["dip001_avg_rank"], analysis["dip001_in_top30"], len(DIP_001_FEATURES),
        analysis["dip001_in_top30"]/len(DIP_001_FEATURES)*100))
    print("  {:>10} | {:>8.1f} | {:>4}/{} | {:.1f}%".format(
        "V2其他", analysis["v2_other_avg_rank"], analysis["v2_other_in_top30"], len(V2_OTHER_PHILOSOPHY),
        analysis["v2_other_in_top30"]/len(V2_OTHER_PHILOSOPHY)*100))
    print("  {:>10} | {:>8.1f} | {:>4}/{} | {:.1f}%".format(
        "V4新", analysis["v4_avg_rank"], analysis["v4_in_top30"], len(V4_FEATURES),
        analysis["v4_in_top30"]/len(V4_FEATURES)*100))
    print("  {:>10} | {:>8.1f} | {:>10} | {}".format("趋势特征", analysis["trend_avg_rank"], "—", "—"))

    # 6. 结论
    print("\n【6. 验证结论】")
    if analysis["success"]:
        print("  [PASS] 抄底特征合集平均排名 {:.1f} <= Top30%阈值 {}".format(
            analysis["all_dip_avg_rank"], analysis["top_30_threshold"]))
        print("     {}/{} 个抄底特征进入Top30%".format(analysis["all_dip_in_top30"], len(all_dip)))
    else:
        print("  [WARN] 抄底特征合集平均排名 {:.1f} > Top30%阈值 {}".format(
            analysis["all_dip_avg_rank"], analysis["top_30_threshold"]))
        print("     仅 {}/{} 个抄底特征进入Top30%".format(analysis["all_dip_in_top30"], len(all_dip)))

    print("\n  样本外AUC:")
    if summary["mean_test_auc"] > 0.65:
        print("    [GOOD] 平均测试AUC {:.4f} > 0.65，模型预测能力良好".format(summary["mean_test_auc"]))
    elif summary["mean_test_auc"] > 0.55:
        print("    [OK] 平均测试AUC {:.4f} 在0.55-0.65，预测能力一般".format(summary["mean_test_auc"]))
    else:
        print("    [WEAK] 平均测试AUC {:.4f} <= 0.55，预测能力不足".format(summary["mean_test_auc"]))

    print("\n  过拟合检测:")
    if summary["decay_ratio"] < 30:
        print("    [GOOD] AUC衰减率 {:.1f}% < 30%，过拟合风险低".format(summary["decay_ratio"]))
    elif summary["decay_ratio"] < 50:
        print("    [WARN] AUC衰减率 {:.1f}% 在30-50%，中等过拟合风险".format(summary["decay_ratio"]))
    else:
        print("    [HIGH] AUC衰减率 {:.1f}% > 50%，高过拟合风险".format(summary["decay_ratio"]))

    # 7. 与Stage 2.0基线对比
    print("\n【7. Stage 2.1 vs Stage 2.0 对比】")
    print("  特征总数: {} → {} (新增RSI+volume_ratio)".format(
        summary["n_features"] - 2, summary["n_features"]))
    print("  注: Stage 2.0基线 AUC=0.5929, 衰减率=37.5%")
    print("  本轮: AUC={:.4f}, 衰减率={:.1f}%".format(summary["mean_test_auc"], summary["decay_ratio"]))
    auc_delta = summary["mean_test_auc"] - 0.5929
    if auc_delta > 0:
        print("  AUC提升: +{:.4f} → 假设DIP-001特征有效".format(auc_delta))
    else:
        print("  AUC变化: {:.4f} → 需进一步分析".format(auc_delta))

    # 8. 下一步建议
    print("\n【8. 下一步建议】")
    dip_top = [f for f in all_dip if analysis["v2_dip_ranks"].get(f, analysis["dip001_ranks"].get(f, 999)) <= analysis["top_30_threshold"]]
    dip_weak = [f for f in all_dip if analysis["v2_dip_ranks"].get(f, analysis["dip001_ranks"].get(f, 999)) > analysis["top_30_threshold"]]

    if dip_top:
        print("  有效抄底特征: {} → 保留并强化".format(", ".join(dip_top)))
    if dip_weak:
        print("  弱抄底特征: {} → 考虑降权或引入新特征".format(", ".join(dip_weak)))

    print("\n  假设DIP-001验证状态:")
    rsi_rank = analysis["dip001_ranks"]["rsi_14"]
    vol_rank = analysis["dip001_ranks"]["volume_ratio_20d"]
    if rsi_rank <= analysis["top_30_threshold"] and vol_rank <= analysis["top_30_threshold"]:
        print("    [VALIDATED] RSI和volume_ratio均进入Top30%，假设DIP-001验证通过")
    elif rsi_rank <= analysis["top_30_threshold"] or vol_rank <= analysis["top_30_threshold"]:
        print("    [PARTIAL] 部分验证通过，RSI排名#{} volume_ratio排名#{}".format(rsi_rank, vol_rank))
    else:
        print("    [REJECTED] RSI排名#{} volume_ratio排名#{} 均未进入Top30%".format(rsi_rank, vol_rank))

    print("\n" + "=" * 80)


def main():
    print("=" * 80)
    print("  Stage 2: DIP_BUY 抄底优化 Walk-Forward 验证")
    print("=" * 80)

    # 1. 加载数据
    print("\n[1/4] 加载BTC日线数据...")
    prices = load_btc_data()
    print("  数据: {}天, {} ~ {}".format(len(prices), prices.index[0].date(), prices.index[-1].date()))

    # 2. 生成DIP_BUY标签
    print("\n[2/4] 生成DIP_BUY标签...")
    mapper = FourObjectiveFeatureMapper()
    labels = mapper.generate_labels(prices, "dip_buy")
    pos_rate = labels.sum() / len(labels) * 100
    print("  正样本: {}/{} ({:.1f}%)".format(labels.sum(), len(labels), pos_rate))
    ldef = mapper.get_label_def("dip_buy")
    print("  标签规则: {}".format(ldef.get("label_rule")))

    # 3. 提取特征并Walk-Forward验证
    print("\n[3/4] 提取特征 + Walk-Forward验证...")
    features = extract_all_features(prices)
    print("  总特征数: {}".format(features.shape[1]))
    print("  训练窗口: 730天(2年) | 测试窗口: 180天(6月) | 步长: 180天")

    summary = walk_forward_validation(features, labels, train_window=730, test_window=180, step_size=180)

    if summary["n_folds"] == 0:
        print("  [ERROR] 没有有效的验证折")
        return

    # 4. 分析V2抄底特征排名
    print("\n[4/4] 分析V2抄底特征排名...")
    analysis = analyze_dip_buy_features(summary)

    # 打印报告
    print_report(summary, analysis, pos_rate)

    # 保存结果
    result = {
        "stage": "Stage 2.1",
        "objective": "DIP_BUY",
        "hypothesis": "DIP-001",
        "n_features": summary["n_features"],
        "n_folds": summary["n_folds"],
        "pos_rate": pos_rate,
        "mean_train_auc": summary["mean_train_auc"],
        "mean_test_auc": summary["mean_test_auc"],
        "decay_ratio": summary["decay_ratio"],
        "v2_dip_avg_rank": analysis["v2_dip_avg_rank"],
        "v2_dip_in_top30": analysis["v2_dip_in_top30"],
        "v2_dip_ranks": analysis["v2_dip_ranks"],
        "v2_dip_importances": analysis["v2_dip_importances"],
        "dip001_ranks": analysis["dip001_ranks"],
        "dip001_importances": analysis["dip001_importances"],
        "dip001_avg_rank": analysis["dip001_avg_rank"],
        "dip001_in_top30": analysis["dip001_in_top30"],
        "all_dip_avg_rank": analysis["all_dip_avg_rank"],
        "all_dip_in_top30": analysis["all_dip_in_top30"],
        "v4_ranks": analysis["v4_ranks"],
        "v4_avg_rank": analysis["v4_avg_rank"],
        "v4_in_top30": analysis["v4_in_top30"],
        "top_30_threshold": analysis["top_30_threshold"],
        "success": analysis["success"],
    }

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/stage2_dip_buy_result.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print("\n结果已保存: {}".format(output_path))

    return summary, analysis


if __name__ == "__main__":
    main()
