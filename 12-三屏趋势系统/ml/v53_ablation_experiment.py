"""V5.3 消融实验：定位方向D AUC下降根因

逐步消融策略：
1. 仅加1个特征（8个单独测试）→ 找出哪些特征单独有害
2. 仅保留Top 2-3个最低相关性特征 → 最小化干扰
3. 仅保留交互特征 → 测试交互是否有效
4. 逐个添加测试 → 定位"害群之马"
"""

import os
import sys
import json
import time
import copy
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
    SELECTED_INDEPENDENT,
    INTERACTION_FEATURES,
)


def main():
    print("=" * 80)
    print("  V5.3 消融实验：定位方向D AUC下降根因")
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

    # V4基线
    v4_features = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v4_feature_names = list(v4_features.columns)

    # 标签
    top_exit_labels = generate_labels(closes, lookahead=20, threshold=0.20, mode="drop")
    dip_buy_labels = generate_labels(closes, lookahead=20, threshold=0.15, mode="rise")

    # V4基线AUC
    print("\n【V4基线】")
    v4_top = walk_forward_validation(v4_features, top_exit_labels, v4_feature_names)
    v4_dip = walk_forward_validation(v4_features, dip_buy_labels, v4_feature_names)
    print("  TOP_EXIT AUC: {:.4f}".format(v4_top["avg_test_auc"]))
    print("  DIP_BUY  AUC: {:.4f}".format(v4_dip["avg_test_auc"]))

    v4_top_auc = v4_top["avg_test_auc"]
    v4_dip_auc = v4_dip["avg_test_auc"]

    # 3. 实验1：逐个单独添加每个方向D特征
    print("\n" + "=" * 80)
    print("  【实验1：逐个单独添加每个方向D特征】")
    print("=" * 80)
    print("  {:<28s}  {:>10s}  {:>10s}  {:>10s}  {:>10s}".format(
        "添加特征", "TOP_EXIT", "Δ TOP", "DIP_BUY", "Δ DIP"))
    print("  " + "-" * 72)

    single_results = {}
    for feat in DIRECTION_D_FEATURES:
        exp_features = pd.concat([v4_features, direction_d[[feat]]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_features.columns)

        top_result = walk_forward_validation(exp_features, top_exit_labels, exp_names)
        dip_result = walk_forward_validation(exp_features, dip_buy_labels, exp_names)

        delta_top = top_result["avg_test_auc"] - v4_top_auc
        delta_dip = dip_result["avg_test_auc"] - v4_dip_auc

        single_results[feat] = {
            "top_auc": top_result["avg_test_auc"],
            "dip_auc": dip_result["avg_test_auc"],
            "delta_top": delta_top,
            "delta_dip": delta_dip,
        }

        flag_top = "✅" if delta_top > 0 else "❌"
        flag_dip = "✅" if delta_dip > 0 else "❌"
        print("  {:<28s}  {:>10.4f}  {:>+10.4f}{} {:>10.4f}  {:>+10.4f}{}".format(
            feat, top_result["avg_test_auc"], delta_top, flag_top,
            dip_result["avg_test_auc"], delta_dip, flag_dip))

    # 4. 实验2：组合测试
    print("\n" + "=" * 80)
    print("  【实验2：组合测试】")
    print("=" * 80)

    combos = [
        ("仅vol_regime_ratio", ["vol_regime_ratio"]),
        ("仅fed_rate_level", ["fed_rate_level"]),
        ("仅drawdown_vs_hist_avg", ["drawdown_vs_hist_avg"]),
        ("vol_regime + fed_rate_level", ["vol_regime_ratio", "fed_rate_level"]),
        ("vol_regime + drawdown_vs_hist", ["vol_regime_ratio", "drawdown_vs_hist_avg"]),
        ("fed_rate_level + drawdown_vs_hist", ["fed_rate_level", "drawdown_vs_hist_avg"]),
        ("3个精选独立(无fed_months)", ["vol_regime_ratio", "fed_rate_level", "drawdown_vs_hist_avg"]),
        ("仅交互特征(3个)", INTERACTION_FEATURES),
        ("vol_regime + 3交互", ["vol_regime_ratio"] + INTERACTION_FEATURES),
        ("fed_months + vol_regime(2个)", ["fed_months_in_cycle", "vol_regime_ratio"]),
    ]

    print("  {:<35s}  {:>10s}  {:>10s}  {:>10s}  {:>10s}".format(
        "组合", "TOP_EXIT", "Δ TOP", "DIP_BUY", "Δ DIP"))
    print("  " + "-" * 80)

    combo_results = {}
    for name, feats in combos:
        available = [f for f in feats if f in direction_d.columns]
        if not available:
            continue

        exp_features = pd.concat([v4_features, direction_d[available]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_features.columns)

        top_result = walk_forward_validation(exp_features, top_exit_labels, exp_names)
        dip_result = walk_forward_validation(exp_features, dip_buy_labels, exp_names)

        delta_top = top_result["avg_test_auc"] - v4_top_auc
        delta_dip = dip_result["avg_test_auc"] - v4_dip_auc

        combo_results[name] = {
            "features": available,
            "top_auc": top_result["avg_test_auc"],
            "dip_auc": dip_result["avg_test_auc"],
            "delta_top": delta_top,
            "delta_dip": delta_dip,
        }

        flag_top = "✅" if delta_top > 0 else "❌"
        flag_dip = "✅" if delta_dip > 0 else "❌"
        print("  {:<35s}  {:>10.4f}  {:>+10.4f}{} {:>10.4f}  {:>+10.4f}{}".format(
            name, top_result["avg_test_auc"], delta_top, flag_top,
            dip_result["avg_test_auc"], delta_dip, flag_dip))

    # 5. 实验3：反向消融 - 全部8个特征中逐个移除
    print("\n" + "=" * 80)
    print("  【实验3：反向消融 - 从8个中逐个移除】")
    print("=" * 80)

    # 先建全部8个的基线
    all_d = pd.concat([v4_features, direction_d[DIRECTION_D_FEATURES]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    all_d_names = list(all_d.columns)
    all_top = walk_forward_validation(all_d, top_exit_labels, all_d_names)
    all_dip = walk_forward_validation(all_d, dip_buy_labels, all_d_names)
    all_top_auc = all_top["avg_test_auc"]
    all_dip_auc = all_d["avg_test_auc"] if False else all_dip["avg_test_auc"]

    print("  8个全量: TOP={:.4f}, DIP={:.4f}".format(all_top_auc, all_dip_auc))

    print("\n  {:<28s}  {:>10s}  {:>10s}  {:>10s}  {:>10s}".format(
        "移除特征", "TOP_EXIT", "Δ TOP", "DIP_BUY", "Δ DIP"))
    print("  " + "-" * 72)

    for feat in DIRECTION_D_FEATURES:
        remaining = [f for f in DIRECTION_D_FEATURES if f != feat]
        exp_features = pd.concat([v4_features, direction_d[remaining]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_features.columns)

        top_result = walk_forward_validation(exp_features, top_exit_labels, exp_names)
        dip_result = walk_forward_validation(exp_features, dip_buy_labels, exp_names)

        delta_top = top_result["avg_test_auc"] - all_top_auc
        delta_dip = dip_result["avg_test_auc"] - all_dip_auc

        flag_top = "✅提升" if delta_top > 0 else "❌下降"
        flag_dip = "✅提升" if delta_dip > 0 else "❌下降"
        print("  移除 {:<22s}  {:>10.4f}  {:>+10.4f}{} {:>10.4f}  {:>+10.4f}{}".format(
            feat, top_result["avg_test_auc"], delta_top, flag_top,
            dip_result["avg_test_auc"], delta_dip, flag_dip))

    # 6. 总结
    print("\n" + "=" * 80)
    print("  【消融实验总结】")
    print("=" * 80)

    # 找出最佳单特征
    best_single_top = max(single_results.items(), key=lambda x: x[1]["delta_top"])
    best_single_dip = max(single_results.items(), key=lambda x: x[1]["delta_dip"])
    best_combo_top = max(combo_results.items(), key=lambda x: x[1]["delta_top"])
    best_combo_dip = max(combo_results.items(), key=lambda x: x[1]["delta_dip"])

    print("\n  单特征最佳(TOP_EXIT): {} → Δ={:+.4f}".format(best_single_top[0], best_single_top[1]["delta_top"]))
    print("  单特征最佳(DIP_BUY):  {} → Δ={:+.4f}".format(best_single_dip[0], best_single_dip[1]["delta_dip"]))
    print("  组合最佳(TOP_EXIT):   {} → Δ={:+.4f}".format(best_combo_top[0], best_combo_top[1]["delta_top"]))
    print("  组合最佳(DIP_BUY):    {} → Δ={:+.4f}".format(best_combo_dip[0], best_combo_dip[1]["delta_dip"]))

    # 保存
    result = {
        "analysis_date": str(pd.Timestamp.now()),
        "v4_baseline": {"top_exit": v4_top_auc, "dip_buy": v4_dip_auc},
        "single_feature_results": single_results,
        "combo_results": combo_results,
        "best_single_top": best_single_top[0],
        "best_single_dip": best_single_dip[0],
        "best_combo_top": best_combo_top[0],
        "best_combo_dip": best_combo_dip[0],
    }

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/v53_ablation_result.json")
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print("\n  结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
