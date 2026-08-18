"""V4特征工程整合 Walk-Forward 验证脚本

Stage 1 验证目标：
    确认 V4 的 7 个新哲学特征在 TOP_EXIT 场景下的特征重要性排名前 30%

验证方法：
    1. 加载 BTC 9年日线数据（2017-10 ~ 2026-07）
    2. 生成 TOP_EXIT 标签（未来20日跌幅>15% 或 最大回撤>20%）
    3. 提取 74 维特征（52趋势特征 + 22哲学特征，含V4的7个新特征）
    4. Walk-Forward 滚动验证（训练2年 → 测试6月 → 滚动前进）
    5. 记录每折 LightGBM 特征重要性（gain-based）
    6. 跨折平均后检查 V4 特征排名

成功标准：
    V4 的 7 个特征平均排名在 top 30%（即 74*30% ≈ top 22）
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

# 路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ml.feature_engineer import TrendFeatureEngineer
from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer, FEATURE_METADATA
from ml.four_objective_feature_mapper import FourObjectiveFeatureMapper


# ── V4 新特征列表 ──────────────────────────────────────────────────
V4_FEATURES = [
    "halving_months_after",
    "halving_phase",
    "halving_position_cap",
    "ma128_distance_pct",
    "ma128_below_days",
    "ath_drawdown_pct",
    "bounce_from_low_pct",
]

V2_PHILOSOPHY_FEATURES = [
    "btc_regime_label", "btc_alt_divergence", "is_btc_asset", "alt_short_risk_score",
    "weekly_ma200_distance", "dip_buy_level", "dip_buy_position_ratio", "left_side_buy_signal",
    "bear_short_layer", "fib_tp_remaining_ratio", "layered_position_target", "position_adjustment",
    "btc_bull_confirmed", "self_bull_confirmed", "double_bull_score",
]


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


def generate_top_exit_labels(prices: pd.DataFrame) -> pd.Series:
    """生成 TOP_EXIT 标签

    规则：未来20日跌幅 > 15% 或 期间最大回撤 > 20% → 1（优质逃顶点）
    """
    mapper = FourObjectiveFeatureMapper()
    return mapper.generate_labels(prices, "top_exit")


def extract_all_features(prices: pd.DataFrame) -> pd.DataFrame:
    """提取全部特征（趋势52维 + 哲学22维 = 74维）"""
    # 趋势特征
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    # 去掉标签列
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    # 哲学特征（含V4的7个新特征）
    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    # 合并
    all_features = pd.concat([trend_features, phil_features], axis=1)

    # 填充NaN
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
    """Walk-Forward 滚动验证

    Args:
        features: 特征DataFrame
        labels: 标签Series
        train_window: 训练窗口大小（天）
        test_window: 测试窗口大小（天）
        step_size: 滚动步长（天）

    Returns:
        包含各折结果和汇总信息的字典
    """
    n = len(features)
    feature_names = list(features.columns)
    n_features = len(feature_names)

    folds = []
    all_importances = []

    start = 0
    fold_idx = 0

    while start + train_window + test_window <= n:
        fold_idx += 1
        train_start = start
        train_end = start + train_window
        test_start = train_end
        test_end = test_start + test_window

        X_train = features.iloc[train_start:train_end].values
        y_train = labels.iloc[train_start:train_end].values
        X_test = features.iloc[test_start:test_end].values
        y_test = labels.iloc[test_start:test_end].values

        # 跳过正样本太少的折
        if y_train.sum() < 5 or y_test.sum() < 2:
            start += step_size
            continue

        # LightGBM 参数（与基线模型一致）
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "min_data_in_leaf": 20,
            "max_depth": -1,
            "verbose": -1,
            "random_state": 42,
        }

        train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_names)
        valid_data = lgb.Dataset(X_test, label=y_test, feature_name=feature_names, reference=train_data)

        model = lgb.train(
            params,
            train_data,
            num_boost_round=200,
            valid_sets=[train_data, valid_data],
            valid_names=["train", "valid"],
            callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(0)],
        )

        # 预测
        y_train_pred = model.predict(X_train)
        y_test_pred = model.predict(X_test)

        # 评估
        train_auc = roc_auc_score(y_train, y_train_pred) if len(np.unique(y_train)) > 1 else 0.5
        test_auc = roc_auc_score(y_test, y_test_pred) if len(np.unique(y_test)) > 1 else 0.5

        y_test_binary = (y_test_pred > 0.5).astype(int)
        test_acc = accuracy_score(y_test, y_test_binary)
        test_precision = precision_score(y_test, y_test_binary, zero_division=0)
        test_recall = recall_score(y_test, y_test_binary, zero_division=0)

        # 特征重要性（gain-based）
        importance = model.feature_importance(importance_type="gain")
        importance_dict = dict(zip(feature_names, importance))
        all_importances.append(importance_dict)

        # 训练日期范围
        train_dates = (features.index[train_start], features.index[train_end - 1])
        test_dates = (features.index[test_start], features.index[test_end - 1])

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

        print(f"  Fold {fold_idx}: train_auc={train_auc:.4f} test_auc={test_auc:.4f} "
              f"pos={int(y_test.sum())}/{len(y_test)} iter={model.best_iteration}")

        start += step_size

    # 跨折平均特征重要性
    avg_importance = {}
    for feat in feature_names:
        values = [imp.get(feat, 0) for imp in all_importances]
        avg_importance[feat] = np.mean(values)

    # 排名（降序，1=最重要）
    sorted_features = sorted(avg_importance.items(), key=lambda x: x[1], reverse=True)
    ranking = {feat: rank + 1 for rank, (feat, _) in enumerate(sorted_features)}

    # 汇总
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


def analyze_v4_feature_ranking(summary: dict) -> dict:
    """分析 V4 特征排名

    成功标准：V4 的 7 个特征平均排名在 top 30%
    """
    n_features = summary["n_features"]
    ranking = summary["ranking"]
    avg_importance = summary["avg_importance"]

    top_30_threshold = int(n_features * 0.3)  # top 30% 的排名边界

    v4_ranks = {f: ranking[f] for f in V4_FEATURES}
    v4_importances = {f: avg_importance[f] for f in V4_FEATURES}
    v2_ranks = {f: ranking[f] for f in V2_PHILOSOPHY_FEATURES}

    v4_avg_rank = np.mean(list(v4_ranks.values()))
    v2_avg_rank = np.mean(list(v2_ranks.values()))

    v4_in_top30 = sum(1 for r in v4_ranks.values() if r <= top_30_threshold)
    v2_in_top30 = sum(1 for r in v2_ranks.values() if r <= top_30_threshold)

    # 所有哲学特征的排名
    all_phil_features = V4_FEATURES + V2_PHILOSOPHY_FEATURES
    phil_avg_rank = np.mean([ranking[f] for f in all_phil_features])

    # 趋势特征排名
    trend_features = [f for f in ranking if f not in all_phil_features]
    trend_avg_rank = np.mean([ranking[f] for f in trend_features])

    result = {
        "n_features": n_features,
        "top_30_threshold": top_30_threshold,
        "v4_ranks": v4_ranks,
        "v4_importances": v4_importances,
        "v4_avg_rank": v4_avg_rank,
        "v4_in_top30_count": v4_in_top30,
        "v4_in_top30_pct": v4_in_top30 / len(V4_FEATURES) * 100,
        "v2_ranks": v2_ranks,
        "v2_avg_rank": v2_avg_rank,
        "v2_in_top30_count": v2_in_top30,
        "v2_in_top30_pct": v2_in_top30 / len(V2_PHILOSOPHY_FEATURES) * 100,
        "phil_avg_rank": phil_avg_rank,
        "trend_avg_rank": trend_avg_rank,
        "success": v4_avg_rank <= top_30_threshold,
        "v4_vs_v2_advantage": v2_avg_rank - v4_avg_rank,  # 正值=V4排名更靠前
    }

    return result


def print_report(summary: dict, analysis: dict):
    """打印验证报告"""
    print("\n" + "=" * 80)
    print("  V4特征工程整合 Walk-Forward 验证报告")
    print("  Stage 1: TOP_EXIT 场景特征重要性验证")
    print("=" * 80)

    # 1. Walk-Forward 概况
    print(f"\n【1. Walk-Forward 验证概况】")
    print(f"  总特征数: {summary['n_features']}")
    print(f"  验证折数: {summary['n_folds']}")
    print(f"  训练窗口: {summary['train_window']}天 | 测试窗口: {summary['test_window']}天")
    print(f"  平均训练AUC: {summary['mean_train_auc']:.4f}")
    print(f"  平均测试AUC: {summary['mean_test_auc']:.4f} (±{summary['std_test_auc']:.4f})")
    print(f"  最小测试AUC: {summary['min_test_auc']:.4f}")
    print(f"  最大测试AUC: {summary['max_test_auc']:.4f}")
    print(f"  AUC衰减率: {summary['decay_ratio']:.1f}%")

    # 2. 各折详情
    print(f"\n【2. 各折详情】")
    print(f"  {'Fold':>4} | {'训练期':>25} | {'测试期':>25} | {'TrainAUC':>8} | {'TestAUC':>8} | {'正样本':>6}")
    print(f"  {'-'*4} | {'-'*25} | {'-'*25} | {'-'*8} | {'-'*8} | {'-'*6}")
    for f in summary["folds"]:
        print(f"  {f['fold']:>4} | {f['train_period']:>25} | {f['test_period']:>25} | "
              f"{f['train_auc']:>8.4f} | {f['test_auc']:>8.4f} | {f['test_positives']:>3}/{f['test_samples']}")

    # 3. 特征重要性排名
    print(f"\n【3. 特征重要性排名（Top 30）】")
    print(f"  {'排名':>4} | {'特征名':>30} | {'重要性':>10} | {'类别':>8}")
    print(f"  {'-'*4} | {'-'*30} | {'-'*10} | {'-'*8}")
    for rank, (feat, imp) in enumerate(summary["sorted_features"][:30], 1):
        if feat in V4_FEATURES:
            category = "V4新"
        elif feat in V2_PHILOSOPHY_FEATURES:
            category = "V2哲"
        else:
            category = "趋势"
        print(f"  {rank:>4} | {feat:>30} | {imp:>10.1f} | {category:>8}")

    # 4. V4 特征分析
    print(f"\n【4. V4 特征排名分析】")
    print(f"  Top 30% 阈值: 排名 ≤ {analysis['top_30_threshold']}")
    print(f"\n  V4 新特征（7个）:")
    print(f"  {'特征名':>30} | {'排名':>6} | {'重要性':>10} | {'Top30%':>6}")
    print(f"  {'-'*30} | {'-'*6} | {'-'*10} | {'-'*6}")
    for feat in V4_FEATURES:
        rank = analysis["v4_ranks"][feat]
        imp = analysis["v4_importances"][feat]
        in_top = "✅" if rank <= analysis["top_30_threshold"] else "❌"
        print(f"  {feat:>30} | {rank:>6} | {imp:>10.1f} | {in_top:>6}")
    print(f"\n  V4平均排名: {analysis['v4_avg_rank']:.1f} / {analysis['n_features']}")
    print(f"  V4进入Top30%: {analysis['v4_in_top30_count']}/{len(V4_FEATURES)} ({analysis['v4_in_top30_pct']:.1f}%)")

    # 5. V4 vs V2 对比
    print(f"\n【5. V4 vs V2 哲学特征对比】")
    print(f"  {'类别':>8} | {'平均排名':>8} | {'进入Top30%':>10} | {'占比':>6}")
    print(f"  {'-'*8} | {'-'*8} | {'-'*10} | {'-'*6}")
    print(f"  {'V4新特征':>8} | {analysis['v4_avg_rank']:>8.1f} | {analysis['v4_in_top30_count']:>4}/{len(V4_FEATURES):>2} | {analysis['v4_in_top30_pct']:>5.1f}%")
    print(f"  {'V2哲学':>8} | {analysis['v2_avg_rank']:>8.1f} | {analysis['v2_in_top30_count']:>4}/{len(V2_PHILOSOPHY_FEATURES):>2} | {analysis['v2_in_top30_pct']:>5.1f}%")
    print(f"  {'趋势特征':>8} | {analysis['trend_avg_rank']:>8.1f} | {'—':>10} | {'—':>6}")
    print(f"\n  V4 vs V2 排名优势: {analysis['v4_vs_v2_advantage']:.1f} (正值=V4更靠前)")

    # 6. 结论
    print(f"\n【6. 验证结论】")
    if analysis["success"]:
        print(f"  ✅ 验证通过！V4特征平均排名 {analysis['v4_avg_rank']:.1f} ≤ Top30%阈值 {analysis['top_30_threshold']}")
        print(f"     {analysis['v4_in_top30_count']}/{len(V4_FEATURES)} 个V4特征进入Top30%")
    else:
        print(f"  ⚠️ V4特征平均排名 {analysis['v4_avg_rank']:.1f} > Top30%阈值 {analysis['top_30_threshold']}")
        print(f"     仅 {analysis['v4_in_top30_count']}/{len(V4_FEATURES)} 个V4特征进入Top30%")
        print(f"     需分析原因：可能是特征冗余、标签定义、或训练窗口影响")

    print(f"\n  过拟合检测:")
    if summary["decay_ratio"] < 30:
        print(f"    ✅ AUC衰减率 {summary['decay_ratio']:.1f}% < 30%，过拟合风险低")
    elif summary["decay_ratio"] < 50:
        print(f"    ⚠️ AUC衰减率 {summary['decay_ratio']:.1f}% 在30-50%，中等过拟合风险")
    else:
        print(f"    ❌ AUC衰减率 {summary['decay_ratio']:.1f}% > 50%，高过拟合风险")

    print(f"\n  样本外AUC:")
    if summary["mean_test_auc"] > 0.65:
        print(f"    ✅ 平均测试AUC {summary['mean_test_auc']:.4f} > 0.65，模型预测能力良好")
    elif summary["mean_test_auc"] > 0.55:
        print(f"    ⚠️ 平均测试AUC {summary['mean_test_auc']:.4f} 在0.55-0.65，预测能力一般")
    else:
        print(f"    ❌ 平均测试AUC {summary['mean_test_auc']:.4f} ≤ 0.55，预测能力不足")

    print("\n" + "=" * 80)


def main():
    print("=" * 80)
    print("  V4特征工程整合 Walk-Forward 验证")
    print("  Stage 1: TOP_EXIT 场景特征重要性验证")
    print("=" * 80)

    # 1. 加载数据
    print("\n[1/5] 加载BTC日线数据...")
    prices = load_btc_data()
    print(f"  数据: {len(prices)}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

    # 2. 生成TOP_EXIT标签
    print("\n[2/5] 生成TOP_EXIT标签...")
    labels = generate_top_exit_labels(prices)
    pos_rate = labels.sum() / len(labels) * 100
    print(f"  正样本: {labels.sum()}/{len(labels)} ({pos_rate:.1f}%)")
    print(f"  标签规则: 未来20日跌幅>15% 或 最大回撤>20%")

    # 3. 提取特征
    print("\n[3/5] 提取特征...")
    features = extract_all_features(prices)
    print(f"  总特征数: {features.shape[1]}")
    print(f"  - 趋势特征: ~52维 (TrendFeatureEngineer)")
    print(f"  - 哲学特征: 22维 (含V4新增7维)")
    print(f"  V4新特征: {V4_FEATURES}")

    # 4. Walk-Forward验证
    print("\n[4/5] Walk-Forward滚动验证...")
    print(f"  训练窗口: 730天(2年) | 测试窗口: 180天(6月) | 步长: 180天")
    summary = walk_forward_validation(
        features, labels,
        train_window=730,
        test_window=180,
        step_size=180,
    )

    if summary["n_folds"] == 0:
        print("  ❌ 没有有效的验证折，请检查数据量或标签分布")
        return

    # 5. 分析V4特征排名
    print("\n[5/5] 分析V4特征排名...")
    analysis = analyze_v4_feature_ranking(summary)

    # 打印报告
    print_report(summary, analysis)

    # 保存结果
    result = {
        "stage": "Stage 1",
        "objective": "TOP_EXIT",
        "n_features": summary["n_features"],
        "n_folds": summary["n_folds"],
        "mean_train_auc": summary["mean_train_auc"],
        "mean_test_auc": summary["mean_test_auc"],
        "decay_ratio": summary["decay_ratio"],
        "v4_avg_rank": analysis["v4_avg_rank"],
        "v4_in_top30_count": analysis["v4_in_top30_count"],
        "v4_in_top30_pct": analysis["v4_in_top30_pct"],
        "success": analysis["success"],
        "v4_ranks": analysis["v4_ranks"],
        "v2_avg_rank": analysis["v2_avg_rank"],
        "top_30_threshold": analysis["top_30_threshold"],
    }

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/stage1_walk_forward_result.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n结果已保存: {output_path}")

    return summary, analysis


if __name__ == "__main__":
    main()
