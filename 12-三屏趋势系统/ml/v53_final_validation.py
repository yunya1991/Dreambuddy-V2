"""V5.3 最终验证：最佳组合精调

基于消融实验发现：
- 最佳TOP_EXIT组合: fed_rate_level + drawdown_vs_hist_avg → Δ=+0.0458
- 最佳DIP_BUY单特征: ma200_dist_x_fed_action → Δ=+0.0454
- drawdown_vs_hist_avg 单独: TOP +0.0276, DIP +0.0241（双场景均提升）

本脚本验证：
1. fed_rate_level + drawdown_vs_hist_avg + ma200_dist_x_fed_action 三特征组合
2. 仅 drawdown_vs_hist_avg + ma200_dist_x_fed_action 双特征组合
3. 扩展搜索：drawdown_vs_hist_avg 与其他特征的组合
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
from ml.v53_direction_d_validation import (
    load_btc_data,
    compute_v5_raw_features,
    build_direction_d_features,
    generate_labels,
    walk_forward_validation,
    DIRECTION_D_FEATURES,
)


def main():
    print("=" * 80)
    print("  V5.3 最终验证：最佳组合精调")
    print("=" * 80)

    # 1. 加载数据
    prices = load_btc_data()
    closes = prices["close"].values
    print("  BTC日线: {}天".format(len(prices)))

    # 2. 计算特征
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    v5_raw = compute_v5_raw_features(phil_fe, prices)
    direction_d = build_direction_d_features(phil_features, v5_raw)

    v4_features = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v4_feature_names = list(v4_features.columns)

    # 标签
    top_exit_labels = generate_labels(closes, lookahead=20, threshold=0.20, mode="drop")
    dip_buy_labels = generate_labels(closes, lookahead=20, threshold=0.15, mode="rise")

    # V4基线
    v4_top = walk_forward_validation(v4_features, top_exit_labels, v4_feature_names)
    v4_dip = walk_forward_validation(v4_features, dip_buy_labels, v4_feature_names)
    v4_top_auc = v4_top["avg_test_auc"]
    v4_dip_auc = v4_dip["avg_test_auc"]

    print("\n  V4基线: TOP={:.4f}, DIP={:.4f}".format(v4_top_auc, v4_dip_auc))

    # 3. 候选组合
    print("\n【候选组合验证】")

    all_d_features = DIRECTION_D_FEATURES  # 全部8个可用特征
    # 还可加入V5原始特征中未选入的
    extra_v5 = ["cycle_path_similarity", "fed_easing_btc_dip", "fed_hawkish_top",
                "bear_severity_score", "bear_phase_progress"]

    combos = [
        # 核心候选（消融实验最佳）
        ("drawdown_vs_hist_avg only", ["drawdown_vs_hist_avg"]),
        ("fed_rate_level + drawdown_vs_hist", ["fed_rate_level", "drawdown_vs_hist_avg"]),
        ("drawdown + ma200_dist_x_fed", ["drawdown_vs_hist_avg", "ma200_dist_x_fed_action"]),
        ("fed_level + drawdown + ma200_inter", ["fed_rate_level", "drawdown_vs_hist_avg", "ma200_dist_x_fed_action"]),

        # 扩展搜索
        ("drawdown + cycle_path_sim", ["drawdown_vs_hist_avg", "cycle_path_similarity"]),
        ("fed_level + drawdown + cycle_path", ["fed_rate_level", "drawdown_vs_hist_avg", "cycle_path_similarity"]),
        ("drawdown + fed_easing_dip", ["drawdown_vs_hist_avg", "fed_easing_btc_dip"]),
        ("fed_level + drawdown + fed_easing", ["fed_rate_level", "drawdown_vs_hist_avg", "fed_easing_btc_dip"]),
        ("drawdown + ma200_inter + fed_easing", ["drawdown_vs_hist_avg", "ma200_dist_x_fed_action", "fed_easing_btc_dip"]),

        # 4特征组合
        ("fed_level + drawdown + ma200_inter + cycle_path",
         ["fed_rate_level", "drawdown_vs_hist_avg", "ma200_dist_x_fed_action", "cycle_path_similarity"]),
        ("fed_level + drawdown + ma200_inter + fed_easing",
         ["fed_rate_level", "drawdown_vs_hist_avg", "ma200_dist_x_fed_action", "fed_easing_btc_dip"]),
    ]

    print("  {:<45s}  {:>10s}  {:>10s}  {:>10s}  {:>10s}  {:>8s}".format(
        "组合", "TOP_EXIT", "Δ TOP", "DIP_BUY", "Δ DIP", "综合"))
    print("  " + "-" * 100)

    best_combo = None
    best_score = -999

    results = []
    for name, feats in combos:
        # 确保特征都存在
        available = []
        for f in feats:
            if f in direction_d.columns:
                available.append(f)
            elif f in v5_raw.columns:
                # 从v5_raw中取
                pass
            else:
                continue

        # 构建特征DataFrame
        feat_dict = {}
        for f in feats:
            if f in direction_d.columns:
                feat_dict[f] = direction_d[f]
            elif f in v5_raw.columns:
                feat_dict[f] = v5_raw[f]

        if not feat_dict:
            continue

        feat_df = pd.DataFrame(feat_dict, index=v4_features.index)
        exp_features = pd.concat([v4_features, feat_df], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_features.columns)

        top_result = walk_forward_validation(exp_features, top_exit_labels, exp_names)
        dip_result = walk_forward_validation(exp_features, dip_buy_labels, exp_names)

        delta_top = top_result["avg_test_auc"] - v4_top_auc
        delta_dip = dip_result["avg_test_auc"] - v4_dip_auc

        # 综合得分：两个场景的平均提升
        composite = (delta_top + delta_dip) / 2

        # 判定
        if delta_top > 0 and delta_dip > 0:
            verdict = "✅双✅"
        elif delta_top > 0 or delta_dip > 0:
            verdict = "🟡单✅"
        else:
            verdict = "❌"

        print("  {:<45s}  {:>10.4f}  {:>+10.4f}  {:>10.4f}  {:>+10.4f}  {}".format(
            name, top_result["avg_test_auc"], delta_top,
            dip_result["avg_test_auc"], delta_dip, verdict))

        results.append({
            "name": name,
            "features": feats,
            "top_auc": top_result["avg_test_auc"],
            "dip_auc": dip_result["avg_test_auc"],
            "delta_top": delta_top,
            "delta_dip": delta_dip,
            "composite": composite,
            "top_decay": top_result["decay_rate"],
            "dip_decay": dip_result["decay_rate"],
        })

        if composite > best_score:
            best_score = composite
            best_combo = results[-1]

    # 4. 最佳组合详情
    print("\n" + "=" * 80)
    print("  【最佳组合详情】")
    print("=" * 80)

    if best_combo:
        print("\n  组合名: {}".format(best_combo["name"]))
        print("  特征: {}".format(best_combo["features"]))
        print("  TOP_EXIT: {:.4f} (Δ={:+.4f}, decay={:.1%})".format(
            best_combo["top_auc"], best_combo["delta_top"], best_combo["top_decay"]))
        print("  DIP_BUY:  {:.4f} (Δ={:+.4f}, decay={:.1%})".format(
            best_combo["dip_auc"], best_combo["delta_dip"], best_combo["dip_decay"]))
        print("  综合: {:+.4f}".format(best_combo["composite"]))

        # 决策
        dt = best_combo["delta_top"]
        dd = best_combo["delta_dip"]
        if dt > 0 and dd > 0:
            decision = "✅ 采纳：两个场景均提升"
        elif (dt > 0 and dd >= -0.005) or (dd > 0 and dt >= -0.005):
            decision = "🟡 部分采纳：一个场景提升，另一个持平"
        elif dt > 0 or dd > 0:
            decision = "🟡 观望：一个场景提升但另一个下降"
        else:
            decision = "❌ 回退"

        print("  决策: {}".format(decision))

    # 5. 按综合得分排序
    print("\n【全部组合排名（按综合得分）】")
    sorted_results = sorted(results, key=lambda x: x["composite"], reverse=True)
    for i, r in enumerate(sorted_results, 1):
        print("  #{} {:<40s}  综合={:+.4f}  (TOP {:+.4f}, DIP {:+.4f})".format(
            i, r["name"], r["composite"], r["delta_top"], r["delta_dip"]))

    # 保存
    output = {
        "analysis_date": str(pd.Timestamp.now()),
        "v4_baseline": {"top_exit": v4_top_auc, "dip_buy": v4_dip_auc},
        "best_combo": best_combo,
        "all_results": sorted_results,
    }
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/v53_final_validation.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print("\n  结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
