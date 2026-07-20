"""Stage 2.4: 清理冗余派生特征 — Walk-Forward 验证

目标：
    验证移除三个零重要性派生特征后，DIP_BUY 模型预测能力是否提升

冗余特征（WF验证重要性=0.0，从 weekly_ma200_distance 派生）：
    - dip_buy_level:            抄底档位 (0-4)，离散化丢失信息
    - dip_buy_position_ratio:   抄底仓位比例，从 weekly_ma200_distance 派生
    - left_side_buy_signal:     左侧抄底信号强度，三级派生链末端

基线对比：
    Stage 2.0 (74特征): AUC=0.5929, 衰减率=37.5%
    Stage 2.1 (76特征): AUC=0.5540, 衰减率=41.5% (RSI+volume_ratio无增益)
    Stage 2.4 (73特征): 待验证 (移除3个冗余特征)

成功标准：
    AUC >= 0.5929 (不劣于Stage 2.0基线) 且 衰减率 <= 37.5%
"""

import json
import sys
import os
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# 重用 Stage 2.0/2.1 验证脚本的函数
from ml.stage2_dip_buy_validation import (
    load_btc_data,
    extract_all_features,
    walk_forward_validation,
    V2_DIP_FEATURES,
    DIP_001_FEATURES,
    V2_OTHER_PHILOSOPHY,
    V4_FEATURES,
)
from ml.four_objective_feature_mapper import FourObjectiveFeatureMapper

# ── Stage 2.4 待清理的冗余特征 ──────────────────────────────────────
# WF验证证据：
#   Stage 2.0: dip_buy_level#71(0.0), dip_buy_position_ratio#43(3.7), left_side_buy_signal#72(0.0)
#   Stage 2.1: dip_buy_level#56(0.0), dip_buy_position_ratio#74(0.0), left_side_buy_signal#75(0.0)
# 均从 weekly_ma200_distance 派生，LightGBM 偏好连续值而非离散档位
REDUNDANT_FEATURES = [
    "dip_buy_level",
    "dip_buy_position_ratio",
    "left_side_buy_signal",
]

# 保留的有效V2抄底特征
EFFECTIVE_V2_DIP = ["weekly_ma200_distance"]


def analyze_features_after_cleanup(summary: dict) -> dict:
    """分析清理后的特征排名"""
    ranking = summary["ranking"]
    importance = summary["avg_importance"]
    n_features = summary["n_features"]
    top_30_threshold = int(n_features * 0.3)

    # 保留的V2抄底特征
    effective_ranks = {f: ranking[f] for f in EFFECTIVE_V2_DIP if f in ranking}
    effective_imps = {f: importance[f] for f in EFFECTIVE_V2_DIP if f in importance}

    # DIP-001 特征
    dip001_ranks = {f: ranking[f] for f in DIP_001_FEATURES if f in ranking}
    dip001_imps = {f: importance[f] for f in DIP_001_FEATURES if f in importance}

    # V4 特征
    v4_ranks = {f: ranking[f] for f in V4_FEATURES if f in ranking}
    v4_avg_rank = np.mean(list(v4_ranks.values())) if v4_ranks else 0.0
    v4_in_top30 = sum(1 for r in v4_ranks.values() if r <= top_30_threshold)

    # 抄底特征合集（清理后：weekly_ma200_distance + DIP-001）
    remaining_dip = EFFECTIVE_V2_DIP + DIP_001_FEATURES
    remaining_dip_ranks = {f: ranking[f] for f in remaining_dip if f in ranking}
    remaining_dip_avg = np.mean(list(remaining_dip_ranks.values())) if remaining_dip_ranks else 0.0
    remaining_dip_in_top30 = sum(1 for r in remaining_dip_ranks.values() if r <= top_30_threshold)

    return {
        "n_features": n_features,
        "top_30_threshold": top_30_threshold,
        "removed_features": REDUNDANT_FEATURES,
        "effective_v2_dip_ranks": effective_ranks,
        "effective_v2_dip_importances": effective_imps,
        "dip001_ranks": dip001_ranks,
        "dip001_importances": dip001_imps,
        "v4_ranks": v4_ranks,
        "v4_avg_rank": v4_avg_rank,
        "v4_in_top30": v4_in_top30,
        "remaining_dip_avg_rank": remaining_dip_avg,
        "remaining_dip_in_top30": remaining_dip_in_top30,
    }


def print_report(summary: dict, analysis: dict, pos_rate: float):
    """打印 Stage 2.4 验证报告"""
    print("\n" + "=" * 80)
    print("  Stage 2.4: 清理冗余派生特征 — Walk-Forward 验证报告")
    print("  移除3个零重要性派生特征后的DIP_BUY模型预测力验证")
    print("=" * 80)

    # 1. 概况
    print("\n【1. 清理配置】")
    print("  移除特征 ({}个):".format(len(REDUNDANT_FEATURES)))
    for f in REDUNDANT_FEATURES:
        print("    - {} (派生自 weekly_ma200_distance)".format(f))
    print("  保留特征: weekly_ma200_distance (唯一有效的V2抄底特征)")
    print("  特征总数: 76 → {} (减少3个)".format(summary["n_features"]))

    # 2. Walk-Forward 概况
    print("\n【2. Walk-Forward 验证概况】")
    print("  总特征数: {}".format(summary["n_features"]))
    print("  验证折数: {}".format(summary["n_folds"]))
    print("  训练窗口: {}天 | 测试窗口: {}天".format(summary["train_window"], summary["test_window"]))
    print("  DIP_BUY正样本率: {:.1f}%".format(pos_rate))
    print("  平均训练AUC: {:.4f}".format(summary["mean_train_auc"]))
    print("  平均测试AUC: {:.4f} (+/-{:.4f})".format(summary["mean_test_auc"], summary["std_test_auc"]))
    print("  最小测试AUC: {:.4f}".format(summary["min_test_auc"]))
    print("  最大测试AUC: {:.4f}".format(summary["max_test_auc"]))
    print("  AUC衰减率: {:.1f}%".format(summary["decay_ratio"]))

    # 3. 各折详情
    print("\n【3. 各折详情】")
    print("  {:>4} | {:>25} | {:>25} | {:>8} | {:>8} | {:>6}".format(
        "Fold", "训练期", "测试期", "TrainAUC", "TestAUC", "正样本"))
    print("  {} | {} | {} | {} | {} | {}".format("-"*4, "-"*25, "-"*25, "-"*8, "-"*8, "-"*6))
    for f in summary["folds"]:
        print("  {:>4} | {:>25} | {:>25} | {:>8.4f} | {:>8.4f} | {}/{}".format(
            f["fold"], f["train_period"], f["test_period"],
            f["train_auc"], f["test_auc"], f["test_positives"], f["test_samples"]))

    # 4. 特征重要性排名 Top 20
    print("\n【4. 特征重要性排名（Top 20）】")
    print("  {:>4} | {:>30} | {:>10} | {:>8}".format("排名", "特征名", "重要性", "类别"))
    print("  {} | {} | {} | {}".format("-"*4, "-"*30, "-"*10, "-"*8))
    for rank, (feat, imp) in enumerate(summary["sorted_features"][:20], 1):
        if feat in EFFECTIVE_V2_DIP:
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

    # 5. 保留的抄底特征分析
    print("\n【5. 清理后抄底特征排名分析】")
    print("  Top 30% 阈值: 排名 <= {}".format(analysis["top_30_threshold"]))

    print("\n  保留的V2抄底特征（1个）:")
    print("  {:>30} | {:>6} | {:>10} | {:>6}".format("特征名", "排名", "重要性", "Top30%"))
    print("  {} | {} | {} | {}".format("-"*30, "-"*6, "-"*10, "-"*6))
    for f in EFFECTIVE_V2_DIP:
        if f in analysis["effective_v2_dip_ranks"]:
            r = analysis["effective_v2_dip_ranks"][f]
            imp = analysis["effective_v2_dip_importances"][f]
            in_top = "YES" if r <= analysis["top_30_threshold"] else "NO"
            print("  {:>30} | {:>6} | {:>10.1f} | {:>6}".format(f, r, imp, in_top))

    print("\n  DIP-001 特征（2个）:")
    for f in DIP_001_FEATURES:
        if f in analysis["dip001_ranks"]:
            r = analysis["dip001_ranks"][f]
            imp = analysis["dip001_importances"][f]
            in_top = "YES" if r <= analysis["top_30_threshold"] else "NO"
            print("  {:>30} | {:>6} | {:>10.1f} | {:>6}".format(f, r, imp, in_top))

    print("\n  抄底特征合集（3个）平均排名: {:.1f} / {}".format(
        analysis["remaining_dip_avg_rank"], summary["n_features"]))
    print("  进入Top30%: {}/3".format(analysis["remaining_dip_in_top30"]))

    # 6. Stage 2.4 vs Stage 2.0/2.1 对比
    print("\n【6. Stage 2.4 vs Stage 2.0/2.1 对比】")
    print("  {:>12} | {:>10} | {:>10} | {:>10}".format("指标", "Stage 2.0", "Stage 2.1", "Stage 2.4"))
    print("  {} | {} | {} | {}".format("-"*12, "-"*10, "-"*10, "-"*10))
    print("  {:>12} | {:>10} | {:>10} | {:>10}".format(
        "特征总数", "74", "76", str(summary["n_features"])))
    print("  {:>12} | {:>10.4f} | {:>10.4f} | {:>10.4f}".format(
        "平均测试AUC", 0.5929, 0.5540, summary["mean_test_auc"]))
    print("  {:>12} | {:>10.1f} | {:>10.1f} | {:>10.1f}".format(
        "AUC衰减率%", 37.5, 41.5, summary["decay_ratio"]))

    auc_24 = summary["mean_test_auc"]
    auc_20 = 0.5929
    auc_21 = 0.5540
    print("\n  AUC变化:")
    print("    vs Stage 2.0: {:+.4f} {}".format(
        auc_24 - auc_20, "✅ 提升" if auc_24 >= auc_20 else "❌ 下降"))
    print("    vs Stage 2.1: {:+.4f} {}".format(
        auc_24 - auc_21, "✅ 提升" if auc_24 >= auc_21 else "❌ 下降"))

    # 7. 结论
    print("\n【7. 验证结论】")
    success = (auc_24 >= auc_20) and (summary["decay_ratio"] <= 37.5)
    if success:
        print("  [PASS] 清理冗余特征后模型预测力提升或不劣于基线")
        print("     AUC >= 0.5929 且 衰减率 <= 37.5%")
    else:
        print("  [WARN] 清理冗余特征后模型预测力未达预期")
        if auc_24 < auc_20:
            print("     AUC {0:.4f} < 0.5929 (下降{1:.4f})".format(auc_24, auc_20 - auc_24))
        if summary["decay_ratio"] > 37.5:
            print("     衰减率 {0:.1f}% > 37.5%".format(summary["decay_ratio"]))

    print("\n  清理决策:")
    print("    移除特征: {}".format(", ".join(REDUNDANT_FEATURES)))
    print("    保留特征: weekly_ma200_distance (V2抄底唯一有效特征)")
    if success:
        print("    建议: 在ML训练管线中默认排除这3个冗余特征")


def main():
    print("=" * 80)
    print("  Stage 2.4: 清理冗余派生特征 — Walk-Forward 验证")
    print("=" * 80)

    # 1. 加载数据
    print("\n[1/4] 加载BTC日线数据...")
    prices = load_btc_data()
    print("  数据: {}天, {} ~ {}".format(
        len(prices), prices.index[0].date(), prices.index[-1].date()))

    # 2. 生成标签
    print("\n[2/4] 生成DIP_BUY标签...")
    mapper = FourObjectiveFeatureMapper()
    labels = mapper.generate_labels(prices, "dip_buy")
    pos_rate = labels.sum() / len(labels) * 100
    print("  正样本: {}/{} ({:.1f}%)".format(labels.sum(), len(labels), pos_rate))
    ldef = mapper.get_label_def("dip_buy")
    print("  标签规则: {}".format(ldef.get("label_rule")))

    # 3. 提取特征并移除冗余
    print("\n[3/4] 提取特征 + 移除冗余特征...")
    features = extract_all_features(prices)
    n_before = len(features.columns)
    print("  原始特征数: {}".format(n_before))

    # 移除冗余特征
    features_clean = features.drop(columns=[c for c in REDUNDANT_FEATURES if c in features.columns])
    n_after = len(features_clean.columns)
    print("  移除特征: {}".format(", ".join(REDUNDANT_FEATURES)))
    print("  清理后特征数: {} (减少{}个)".format(n_after, n_before - n_after))

    # 4. Walk-Forward 验证
    print("\n[4/4] Walk-Forward验证...")
    print("  训练窗口: 730天(2年) | 测试窗口: 180天(6月) | 步长: 180天")
    summary = walk_forward_validation(features_clean, labels)

    # 5. 分析
    analysis = analyze_features_after_cleanup(summary)

    # 6. 打印报告
    print_report(summary, analysis, pos_rate)

    # 7. 保存结果
    result = {
        "stage": "Stage 2.4",
        "objective": "DIP_BUY",
        "task": "cleanup_redundant_features",
        "removed_features": REDUNDANT_FEATURES,
        "n_features_before": n_before,
        "n_features_after": n_after,
        "n_folds": summary["n_folds"],
        "pos_rate": pos_rate,
        "mean_train_auc": summary["mean_train_auc"],
        "mean_test_auc": summary["mean_test_auc"],
        "std_test_auc": summary["std_test_auc"],
        "min_test_auc": summary["min_test_auc"],
        "max_test_auc": summary["max_test_auc"],
        "decay_ratio": summary["decay_ratio"],
        "effective_v2_dip_ranks": analysis["effective_v2_dip_ranks"],
        "effective_v2_dip_importances": analysis["effective_v2_dip_importances"],
        "dip001_ranks": analysis["dip001_ranks"],
        "dip001_importances": analysis["dip001_importances"],
        "v4_ranks": analysis["v4_ranks"],
        "v4_avg_rank": analysis["v4_avg_rank"],
        "v4_in_top30": analysis["v4_in_top30"],
        "remaining_dip_avg_rank": analysis["remaining_dip_avg_rank"],
        "remaining_dip_in_top30": analysis["remaining_dip_in_top30"],
        "baseline_comparison": {
            "stage_2_0": {"auc": 0.5929, "decay_ratio": 37.5, "n_features": 74},
            "stage_2_1": {"auc": 0.5540, "decay_ratio": 41.5, "n_features": 76},
            "stage_2_4": {"auc": summary["mean_test_auc"], "decay_ratio": summary["decay_ratio"], "n_features": n_after},
        },
        "success": (summary["mean_test_auc"] >= 0.5929) and (summary["decay_ratio"] <= 37.5),
    }

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/stage2_4_cleanup_result.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print("\n结果已保存: {}".format(output_path))

    return summary, analysis


if __name__ == "__main__":
    main()
