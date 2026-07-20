"""PITD Phase 3 验证: 势能场层

1. 物理意义检验（理论4：市场沿阻力最小方向运动）
2. 四类关键价位分量验证
3. Walk-Forward验证：V5.5基线 vs V5.5+势能场(12维)
4. 消融实验：逐个分量测试

基线: V5.5 (TOP_EXIT 0.7433, DIP_BUY 0.6935)
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
from ml.pitd_potential_field import PotentialFieldEngineer


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


def walk_forward_validation(
    features, labels, feature_names,
    n_splits=12, train_days=730, test_days=180, step_days=180,
):
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

    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0
    avg_imp = np.mean(feature_importances, axis=0) if feature_importances else np.zeros(len(feature_names))
    return avg_test, avg_train, float(decay), avg_imp


def main():
    print("=" * 80)
    print("  PITD Phase 3 验证: 势能场层 (Potential Field)")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    print("\n  BTC日线: {}天, {} ~ {}".format(
        len(prices), prices.index[0].date(), prices.index[-1].date()))

    # 1. 计算势能场特征
    print("\n【1. 势能场特征计算】")
    t0 = time.time()
    pf_fe = PotentialFieldEngineer()
    pf_features = pf_fe.extract_series(prices)
    print("  势能场特征: {}维  {:.2f}s".format(pf_features.shape[1], time.time() - t0))
    print("  特征名: {}".format(pf_fe.FEATURE_NAMES))

    # 2. 物理意义检验（理论4）
    print("\n【2. 物理意义检验（理论4：市场沿阻力最小方向运动）】")
    check = pf_fe.physics_sanity_check(prices, future_days=5)
    print("  阻力最小方向正确率:  {:.1%} (未来5日)".format(check["direction_match_rate"]))
    print("  负梯度平均收益:      {:+.3%} (梯度负→阻力向上)".format(check["return_neg_gradient"]))
    print("  正梯度平均收益:      {:+.3%} (梯度正→阻力向下)".format(check["return_pos_gradient"]))
    print("  各分量方向正确率:")
    for comp, rate in check["component_match_rates"].items():
        print("    {:<35s}  {:.1%}".format(comp, rate))
    print("  势能范围: [{:.4f}, {:.4f}]".format(*check["potential_range"]))
    print("  梯度范围: [{:.4f}, {:.4f}]".format(*check["gradient_range"]))
    print("  上方阻力均值: {:.4f}".format(check["up_resistance_mean"]))
    print("  下方支撑均值: {:.4f}".format(check["down_support_mean"]))
    print("  结论: {}".format(check["verdict"]))

    # 3. 特征数值校验
    print("\n【3. 特征数值校验】")
    for col in pf_features.columns:
        v = pf_features[col]
        non_zero = (v != 0).sum()
        print("  {:<35s}  min={:>10.4f}  max={:>10.4f}  mean={:>10.4f}  非零={}/{:.0%}".format(
            col, v.min(), v.max(), v.mean(), non_zero, non_zero / len(v)))

    # 4. 构建V5.5基线
    print("\n【4. 构建V5.5基线】")
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    v55_base = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v55_names = list(v55_base.columns)
    print("  V5.5基线: {}维".format(len(v55_names)))

    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")

    # 5. Walk-Forward验证
    print("\n【5. Walk-Forward验证】")

    print("\n  5.1 V5.5基线")
    v55_top, v55_top_tr, v55_top_dec, _ = walk_forward_validation(v55_base, top_exit_labels, v55_names)
    v55_dip, v55_dip_tr, v55_dip_dec, _ = walk_forward_validation(v55_base, dip_buy_labels, v55_names)
    print("    TOP_EXIT: {:.4f} (decay={:.1%})".format(v55_top, v55_top_dec))
    print("    DIP_BUY:  {:.4f} (decay={:.1%})".format(v55_dip, v55_dip_dec))

    print("\n  5.2 V5.5 + 势能场(全部12维)")
    t0 = time.time()
    exp_feats = pd.concat([v55_base, pf_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    exp_names = list(exp_feats.columns)
    pf_top, pf_top_tr, pf_top_dec, pf_top_imp = walk_forward_validation(exp_feats, top_exit_labels, exp_names)
    pf_dip, pf_dip_tr, pf_dip_dec, pf_dip_imp = walk_forward_validation(exp_feats, dip_buy_labels, exp_names)
    d_top = pf_top - v55_top
    d_dip = pf_dip - v55_dip
    verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
    print("    TOP_EXIT: {:.4f} (Δ{:+.4f}, decay={:.1%})".format(pf_top, d_top, pf_top_dec))
    print("    DIP_BUY:  {:.4f} (Δ{:+.4f}, decay={:.1%})  {:.1f}s {}".format(
        pf_dip, d_dip, pf_dip_dec, time.time() - t0, verdict))

    # 6. 特征重要性排名
    print("\n【6. 势能场特征重要性排名】")
    for scenario, imp, names in [
        ("TOP_EXIT", pf_top_imp, exp_names),
        ("DIP_BUY", pf_dip_imp, exp_names),
    ]:
        print("\n  {} 场景:".format(scenario))
        fi = sorted(zip(names, imp), key=lambda x: x[1], reverse=True)
        total = len(names)
        for rank, (feat, importance) in enumerate(fi, 1):
            if feat in pf_features.columns:
                pct = int(rank / total * 100)
                print("    #{:>3d} {:<35s}  重要性={:>8.1f}  Top{}%".format(
                    rank, feat, importance, pct))

    # 7. 消融实验：分量测试
    print("\n【7. 消融实验：四类分量单独测试】")

    component_groups = {
        "均线分量(2维)": ["field_gradient_ma"],
        "成交密集区分量(1维)": ["field_gradient_volume"],
        "前高前低分量(1维)": ["field_gradient_swing"],
        "斐波那契分量(1维)": ["field_gradient_fib"],
        "总梯度(3维)": ["field_potential_total", "field_gradient_total", "field_direction"],
        "距离特征(3维)": ["field_dist_to_nearest_min", "field_nearest_min_potential", "field_potential_vs_avg"],
        "不对称性(2维)": ["field_up_resistance", "field_down_support"],
    }

    print("  {:<25s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "分量组合", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 75)

    component_results = []
    for name, feats in component_groups.items():
        available = [f for f in feats if f in pf_features.columns]
        if not available:
            continue
        exp_feats = pd.concat([v55_base, pf_features[available]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_feats.columns)
        top_auc, _, _, _ = walk_forward_validation(exp_feats, top_exit_labels, exp_names)
        dip_auc, _, _, _ = walk_forward_validation(exp_feats, dip_buy_labels, exp_names)
        d_top = top_auc - v55_top
        d_dip = dip_auc - v55_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("  {:<25s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            name, top_auc, d_top, dip_auc, d_dip, verdict))
        component_results.append({"name": name, "feats": available, "d_top": d_top, "d_dip": d_dip,
                                   "top_auc": top_auc, "dip_auc": dip_auc})

    # 8. 组合测试
    print("\n【8. 精选组合测试】")

    best_components = [r for r in component_results if r["d_top"] + r["d_dip"] > -0.01]
    best_components.sort(key=lambda x: x["d_top"] + x["d_dip"], reverse=True)

    combos = [
        ("梯度4分量", ["field_gradient_ma", "field_gradient_volume", "field_gradient_swing", "field_gradient_fib"]),
        ("总梯度+不对称", ["field_gradient_total", "field_up_resistance", "field_down_support"]),
        ("距离+方向", ["field_dist_to_nearest_min", "field_direction", "field_potential_vs_avg"]),
        ("精选5维", ["field_gradient_total", "field_dist_to_nearest_min", "field_up_resistance",
                   "field_down_support", "field_potential_vs_avg"]),
        ("全部12维", list(pf_features.columns)),
    ]

    print("  {:<25s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "组合", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 75)

    combo_results = []
    for name, feats in combos:
        available = [f for f in feats if f in pf_features.columns]
        if not available:
            continue
        exp_feats = pd.concat([v55_base, pf_features[available]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_feats.columns)
        top_auc, _, top_dec, _ = walk_forward_validation(exp_feats, top_exit_labels, exp_names)
        dip_auc, _, dip_dec, _ = walk_forward_validation(exp_feats, dip_buy_labels, exp_names)
        d_top = top_auc - v55_top
        d_dip = dip_auc - v55_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("  {:<25s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            name, top_auc, d_top, dip_auc, d_dip, verdict))
        combo_results.append({
            "name": name, "feats": available,
            "top_auc": top_auc, "dip_auc": dip_auc,
            "d_top": d_top, "d_dip": d_dip,
            "top_decay": top_dec, "dip_decay": dip_dec,
        })

    # 9. 总结
    print("\n" + "=" * 80)
    print("  【Phase 3 验证总结】")
    print("=" * 80)

    both_positive = [r for r in combo_results if r["d_top"] > 0 and r["d_dip"] > 0]
    both_positive.sort(key=lambda x: (x["d_top"] + x["d_dip"]) / 2, reverse=True)

    print("\n  双场景提升的组合 ({}个):".format(len(both_positive)))
    for r in both_positive[:5]:
        comp = (r["d_top"] + r["d_dip"]) / 2
        print("  综合={:+.4f} {:<25s} TOP {:+.4f} DIP {:+.4f} decay:{:.1%}/{:.1%}".format(
            comp, r["name"], r["d_top"], r["d_dip"], r["top_decay"], r["dip_decay"]))

    if both_positive:
        best = both_positive[0]
        if best["d_top"] > 0.005 and best["d_dip"] > 0.005:
            decision = "✅ 采纳：双场景显著提升"
        elif (best["d_top"] + best["d_dip"]) / 2 > 0.002:
            decision = "🟡 部分采纳：有提升但幅度有限"
        else:
            decision = "🟡 观望：提升不显著"
    else:
        single_positive = [r for r in combo_results if r["d_top"] > 0 or r["d_dip"] > 0]
        if single_positive:
            decision = "🟡 观望：仅单场景提升"
        else:
            decision = "❌ 回退：无提升"

    print("\n  决策: {}".format(decision))

    # 保存结果
    output = {
        "analysis_date": str(pd.Timestamp.now()),
        "phase": "Phase 3 - Potential Field",
        "physics_check": check,
        "v55_baseline": {"top_exit": v55_top, "dip_buy": v55_dip},
        "full_potential_field": {
            "top_exit": pf_top, "dip_buy": pf_dip,
            "delta_top": d_top, "delta_dip": d_dip,
            "top_decay": pf_top_dec, "dip_decay": pf_dip_dec,
        },
        "component_results": component_results,
        "combo_results": combo_results,
        "best_combo": both_positive[0] if both_positive else None,
        "decision": decision,
    }
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/pitd_phase3_result.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print("\n  结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
