"""PITD Phase 1 验证: 运动学层

1. 物理意义检验：验证v/a/j的物理合理性
2. 特征数值校验：检查范围、非零占比
3. Walk-Forward验证：V5.5基线 vs V5.5+运动学(12维)
4. 消融实验：逐个添加运动学特征，定位有效特征

基线: V5.5 (28维哲学特征, TOP_EXIT 0.7433, DIP_BUY 0.6935)
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
from ml.pitd_kinematics_engineer import KinematicsEngineer


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
    print("  PITD Phase 1 验证: 运动学层 (Kinematics)")
    print("=" * 80)

    # 1. 加载数据
    prices = load_btc_data()
    closes = prices["close"].values
    print("\n  BTC日线: {}天, {} ~ {}".format(
        len(prices), prices.index[0].date(), prices.index[-1].date()))

    # 2. 计算运动学特征
    print("\n【1. 运动学特征计算】")
    t0 = time.time()
    kin_fe = KinematicsEngineer()
    kin_features = kin_fe.extract_series(prices)
    print("  运动学特征: {}维".format(kin_features.shape[1]))
    print("  特征名: {}".format(kin_fe.FEATURE_NAMES))
    print("  计算耗时: {:.2f}s".format(time.time() - t0))

    # 3. 物理意义检验
    print("\n【2. 物理意义检验】")
    check = kin_fe.physics_sanity_check(prices)
    print("  v符号正确率:      {:.1%} (期望>70%)".format(check["v_sign_correct_rate"]))
    print("  a符号正确率:      {:.1%} (趋势加强时sign(a)==sign(v))".format(check["a_sign_correct_rate"]))
    print("  周线日线方向一致:  {:.1%} (期望>50%)".format(check["direction_consistency_WD"]))
    print("  反转点jerk放大倍数: {:.2f}x (期望>1.0)".format(check["jerk_reversal_ratio"]))
    print("  v_D范围: [{:.5f}, {:.5f}]".format(*check["v_D_range"]))
    print("  a_D范围: [{:.5f}, {:.5f}]".format(*check["a_D_range"]))
    print("  j_D范围: [{:.5f}, {:.5f}]".format(*check["j_D_range"]))
    print("  v_W范围: [{:.5f}, {:.5f}]".format(*check["v_W_range"]))
    print("  a_W范围: [{:.6f}, {:.6f}]".format(*check["a_W_range"]))
    print("  j_W范围: [{:.6f}, {:.6f}]".format(*check["j_W_range"]))
    print("  结论: {}".format(check["verdict"]))

    # 4. 特征数值校验
    print("\n【3. 特征数值校验】")
    for col in kin_features.columns:
        v = kin_features[col]
        non_zero = (v != 0).sum()
        print("  {:<32s}  min={:>10.5f}  max={:>10.5f}  mean={:>10.5f}  非零={}/{:.0%}".format(
            col, v.min(), v.max(), v.mean(), non_zero, non_zero / len(v)))

    # 5. 构建V5.5基线
    print("\n【4. 构建V5.5基线】")
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    v55_base = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v55_names = list(v55_base.columns)
    print("  V5.5基线: {}维 (趋势{}+哲学{})".format(
        len(v55_names), len(trend_cols), len(phil_features.columns)))

    # V5.5 + 运动学
    v55_kin = pd.concat([v55_base, kin_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v55_kin_names = list(v55_kin.columns)
    print("  V5.5+运动学: {}维 (+{})".format(len(v55_kin_names), len(kin_features.columns)))

    # 6. 标签
    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")

    # 7. Walk-Forward验证
    print("\n【5. Walk-Forward验证】")

    print("\n  5.1 V5.5基线")
    t0 = time.time()
    v55_top, v55_top_tr, v55_top_dec, _ = walk_forward_validation(v55_base, top_exit_labels, v55_names)
    v55_dip, v55_dip_tr, v55_dip_dec, _ = walk_forward_validation(v55_base, dip_buy_labels, v55_names)
    print("    TOP_EXIT: {:.4f} (train={:.4f}, decay={:.1%})  {:.1f}s".format(
        v55_top, v55_top_tr, v55_top_dec, time.time() - t0))
    print("    DIP_BUY:  {:.4f} (train={:.4f}, decay={:.1%})".format(
        v55_dip, v55_dip_tr, v55_dip_dec))

    print("\n  5.2 V5.5 + 运动学(12维)")
    t0 = time.time()
    kin_top, kin_top_tr, kin_top_dec, kin_top_imp = walk_forward_validation(v55_kin, top_exit_labels, v55_kin_names)
    kin_dip, kin_dip_tr, kin_dip_dec, kin_dip_imp = walk_forward_validation(v55_kin, dip_buy_labels, v55_kin_names)
    print("    TOP_EXIT: {:.4f} (train={:.4f}, decay={:.1%})  {:.1f}s".format(
        kin_top, kin_top_tr, kin_top_dec, time.time() - t0))
    print("    DIP_BUY:  {:.4f} (train={:.4f}, decay={:.1%})".format(
        kin_dip, kin_dip_tr, kin_dip_dec))

    delta_top = kin_top - v55_top
    delta_dip = kin_dip - v55_dip
    print("\n  >>> TOP_EXIT AUC变化: {:+.4f} ({})".format(
        delta_top, "✅提升" if delta_top > 0 else "❌下降" if delta_top < 0 else "➡️持平"))
    print("  >>> DIP_BUY  AUC变化: {:+.4f} ({})".format(
        delta_dip, "✅提升" if delta_dip > 0 else "❌下降" if delta_dip < 0 else "➡️持平"))

    # 8. 运动学特征重要性排名
    print("\n【6. 运动学特征重要性排名】")
    for scenario, imp, names in [
        ("TOP_EXIT", kin_top_imp, v55_kin_names),
        ("DIP_BUY", kin_dip_imp, v55_kin_names),
    ]:
        print("\n  {} 场景:".format(scenario))
        fi = sorted(zip(names, imp), key=lambda x: x[1], reverse=True)
        total = len(names)
        top30_threshold = int(total * 0.3)
        for rank, (feat, importance) in enumerate(fi, 1):
            if feat in kin_features.columns:
                in_top30 = "✅Top30%" if rank <= top30_threshold else "  Top{}%".format(int(rank/total*100))
                print("    #{:>3d} {:<32s}  重要性={:>8.1f}  {}".format(
                    rank, feat, importance, in_top30))

    # 9. 消融实验：逐个添加运动学特征
    print("\n【7. 消融实验：逐个添加运动学特征】")
    print("  {:<35s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "添加特征", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 80)

    single_results = []
    for feat in kin_features.columns:
        exp_feats = pd.concat([v55_base, kin_features[[feat]]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_feats.columns)
        top_auc, _, _, _ = walk_forward_validation(exp_feats, top_exit_labels, exp_names)
        dip_auc, _, _, _ = walk_forward_validation(exp_feats, dip_buy_labels, exp_names)
        d_top = top_auc - v55_top
        d_dip = dip_auc - v55_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("  {:<35s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            feat, top_auc, d_top, dip_auc, d_dip, verdict))
        single_results.append({"feat": feat, "d_top": d_top, "d_dip": d_dip})

    # 10. 组合测试
    print("\n【8. 组合测试】")

    combos = [
        ("日线3维", ["kin_velocity_D", "kin_acceleration_D", "kin_jerk_D"]),
        ("周线3维", ["kin_velocity_W", "kin_acceleration_W", "kin_jerk_W"]),
        ("速度+加速度(日+周)", ["kin_velocity_D", "kin_acceleration_D", "kin_velocity_W", "kin_acceleration_W"]),
        ("全部12维", list(kin_features.columns)),
        ("方向一致性2维", ["kin_velocity_sign_consistency", "kin_accel_sign_consistency"]),
        ("突变强度2维", ["kin_jerk_abs_D", "kin_jerk_abs_W"]),
        ("比率2维", ["kin_speed_ratio_WD", "kin_accel_ratio_WD"]),
    ]

    print("  {:<35s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "组合", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 80)

    combo_results = []
    for name, feats in combos:
        available = [f for f in feats if f in kin_features.columns]
        if not available:
            continue
        exp_feats = pd.concat([v55_base, kin_features[available]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_feats.columns)
        top_auc, _, top_dec, _ = walk_forward_validation(exp_feats, top_exit_labels, exp_names)
        dip_auc, _, dip_dec, _ = walk_forward_validation(exp_feats, dip_buy_labels, exp_names)
        d_top = top_auc - v55_top
        d_dip = dip_auc - v55_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("  {:<35s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            name, top_auc, d_top, dip_auc, d_dip, verdict))
        combo_results.append({
            "name": name, "feats": available,
            "top_auc": top_auc, "dip_auc": dip_auc,
            "d_top": d_top, "d_dip": d_dip,
            "top_decay": top_dec, "dip_decay": dip_dec,
        })

    # 11. 总结
    print("\n" + "=" * 80)
    print("  【Phase 1 验证总结】")
    print("=" * 80)

    both_positive = [r for r in combo_results if r["d_top"] > 0 and r["d_dip"] > 0]
    both_positive.sort(key=lambda x: (x["d_top"] + x["d_dip"]) / 2, reverse=True)

    print("\n  双场景提升的组合 ({}个):".format(len(both_positive)))
    for r in both_positive[:5]:
        comp = (r["d_top"] + r["d_dip"]) / 2
        print("  综合={:+.4f} {:<35s} TOP {:+.4f} DIP {:+.4f} decay:{:.1%}/{:.1%}".format(
            comp, r["name"], r["d_top"], r["d_dip"], r["top_decay"], r["dip_decay"]))

    # 决策
    if both_positive:
        best = both_positive[0]
        if best["d_top"] > 0.005 and best["d_dip"] > 0.005:
            decision = "✅ 采纳：双场景显著提升"
        elif (best["d_top"] + best["d_dip"]) / 2 > 0.002:
            decision = "🟡 部分采纳：有提升但幅度有限"
        else:
            decision = "🟡 观望：提升不显著"
    else:
        # 检查是否有单场景提升
        single_positive = [r for r in combo_results if r["d_top"] > 0 or r["d_dip"] > 0]
        if single_positive:
            decision = "🟡 观望：仅单场景提升"
        else:
            decision = "❌ 回退：无提升"

    print("\n  决策: {}".format(decision))

    # 保存结果
    output = {
        "analysis_date": str(pd.Timestamp.now()),
        "phase": "Phase 1 - Kinematics",
        "physics_check": check,
        "v55_baseline": {
            "top_exit_auc": v55_top,
            "dip_buy_auc": v55_dip,
            "top_decay": v55_top_dec,
            "dip_decay": v55_dip_dec,
        },
        "kinematics_full": {
            "top_exit_auc": kin_top,
            "dip_buy_auc": kin_dip,
            "delta_top": delta_top,
            "delta_dip": delta_dip,
            "top_decay": kin_top_dec,
            "dip_decay": kin_dip_dec,
        },
        "single_feature_results": single_results,
        "combo_results": combo_results,
        "best_combo": both_positive[0] if both_positive else None,
        "decision": decision,
    }

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/pitd_phase1_result.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print("\n  结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
