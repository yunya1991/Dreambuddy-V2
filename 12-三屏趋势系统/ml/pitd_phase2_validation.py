"""PITD Phase 2 验证: 动力学层

1. 物理意义检验（质量m、动量P、动能E_k、耦合效率η）
2. 理论1验证：趋势强时η高，趋势弱时η低
3. Walk-Forward验证：V5.5基线 vs V5.5+动力学(9维)
4. 消融实验：逐个添加动力学特征
5. 三种质量模式对比（stablecoin_mcap / volume_normalized / constant）

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
from ml.pitd_dynamics_engineer import DynamicsEngineer


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
    print("  PITD Phase 2 验证: 动力学层 (Dynamics)")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    print("\n  BTC日线: {}天, {} ~ {}".format(
        len(prices), prices.index[0].date(), prices.index[-1].date()))

    # 1. 计算运动学和动力学特征
    print("\n【1. 特征计算】")
    kin_fe = KinematicsEngineer()
    kin_features = kin_fe.extract_series(prices)
    print("  运动学特征: {}维".format(kin_features.shape[1]))

    # 三种质量模式对比
    mass_modes = ["stablecoin_mcap", "volume_normalized", "constant"]
    dyn_features_by_mode = {}
    for mode in mass_modes:
        t0 = time.time()
        dyn_fe = DynamicsEngineer(mass_mode=mode)
        dyn_feats = dyn_fe.extract_series(prices, kin_features)
        dyn_features_by_mode[mode] = (dyn_fe, dyn_feats)
        print("  动力学特征({:20s}): {}维  {:.2f}s".format(mode, dyn_feats.shape[1], time.time() - t0))

    # 2. 物理意义检验
    print("\n【2. 物理意义检验】")
    for mode in mass_modes:
        dyn_fe, dyn_feats = dyn_features_by_mode[mode]
        check = dyn_fe.physics_sanity_check(prices, kin_features)
        print("\n  质量模式: {}".format(mode))
        print("    质量m>0占比:      {:.1%}".format(check["mass_positive_rate"]))
        print("    质量变异系数CV:    {:.3f} (>0.1表示有变化)".format(check["mass_cv"]))
        print("    动量方向正确率:    {:.1%} (sign(P)==sign(v))".format(check["momentum_sign_correct"]))
        print("    动能非负率:        {:.1%}".format(check["kinetic_energy_nonneg"]))
        print("    η在[0,1]占比:     {:.1%}".format(check["eta_in_range"]))
        print("    强趋势η:          {:.4f}".format(check["eta_strong_trend"]))
        print("    弱趋势η:          {:.4f}".format(check["eta_weak_trend"]))
        print("    强弱η比:          {:.2f}x (>1.0验证理论1)".format(check["eta_strong_weak_ratio"]))
        print("    m范围: [{:.3f}, {:.3f}]".format(*check["mass_range"]))
        print("    η范围: [{:.4f}, {:.4f}]".format(*check["eta_range"]))
        print("    结论: {}".format(check["verdict"]))

    # 3. 理论1验证：动量传递效率η
    print("\n【3. 理论1验证：大周期驱动小周期】")
    print("  理论：趋势强时η高（大周期驱动），趋势弱时η低（小周期独立）")
    dyn_fe_sc, dyn_feats_sc = dyn_features_by_mode["stablecoin_mcap"]
    eta = dyn_feats_sc["dyn_coupling_eta"].values
    v_W = kin_features["kin_velocity_W"].values

    # 按周线速度分5档
    abs_vW = np.abs(v_W)
    pct_bins = np.percentile(abs_vW[abs_vW > 0], [0, 20, 40, 60, 80, 100])
    print("\n  按周线速度分档的η值:")
    print("  {:<15s}  {:>10s}  {:>10s}  {:>10s}".format("速度档位", "v_W范围", "η均值", "样本数"))
    for i in range(5):
        lo = pct_bins[i]
        hi = pct_bins[i + 1]
        mask = (abs_vW >= lo) & (abs_vW <= hi if i == 4 else abs_vW < hi)
        if mask.sum() > 0:
            eta_mean = eta[mask].mean()
            print("  {:<15s}  {:>10.5f}  {:>10.4f}  {:>10d}".format(
                "档{}({:.0%})".format(i + 1, (i + 1) / 5), abs_vW[mask].mean(), eta_mean, mask.sum()))

    # 4. 构建基线
    print("\n【4. 构建基线】")
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

    # 三种质量模式对比
    mode_results = {}
    for mode in mass_modes:
        print("\n  5.2 V5.5 + 动力学({})".format(mode))
        _, dyn_feats = dyn_features_by_mode[mode]
        exp_feats = pd.concat([v55_base, dyn_feats], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_feats.columns)

        t0 = time.time()
        top_auc, top_tr, top_dec, top_imp = walk_forward_validation(exp_feats, top_exit_labels, exp_names)
        dip_auc, dip_tr, dip_dec, dip_imp = walk_forward_validation(exp_feats, dip_buy_labels, exp_names)
        d_top = top_auc - v55_top
        d_dip = dip_auc - v55_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("    TOP_EXIT: {:.4f} (Δ{:+.4f}, decay={:.1%})".format(top_auc, d_top, top_dec))
        print("    DIP_BUY:  {:.4f} (Δ{:+.4f}, decay={:.1%})  {:.1f}s {}".format(
            dip_auc, d_dip, dip_dec, time.time() - t0, verdict))

        mode_results[mode] = {
            "top_auc": top_auc, "dip_auc": dip_auc,
            "d_top": d_top, "d_dip": d_dip,
            "top_decay": top_dec, "dip_decay": dip_dec,
            "top_imp": top_imp, "dip_imp": dip_imp,
            "exp_names": exp_names,
        }

    # 6. 选最佳质量模式做消融实验
    best_mode = max(mode_results.keys(),
                    key=lambda m: (mode_results[m]["d_top"] + mode_results[m]["d_dip"]) / 2)
    print("\n【6. 消融实验（最佳质量模式: {}）】".format(best_mode))

    _, best_dyn_feats = dyn_features_by_mode[best_mode]
    print("  {:<35s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "添加特征", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 80)

    single_results = []
    for feat in best_dyn_feats.columns:
        exp_feats = pd.concat([v55_base, best_dyn_feats[[feat]]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_feats.columns)
        top_auc, _, _, _ = walk_forward_validation(exp_feats, top_exit_labels, exp_names)
        dip_auc, _, _, _ = walk_forward_validation(exp_feats, dip_buy_labels, exp_names)
        d_top = top_auc - v55_top
        d_dip = dip_auc - v55_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("  {:<35s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            feat, top_auc, d_top, dip_auc, d_dip, verdict))
        single_results.append({"feat": feat, "d_top": d_top, "d_dip": d_dip})

    # 7. 组合测试
    print("\n【7. 组合测试】")
    combos = [
        ("基础4维", ["dyn_force_net", "dyn_momentum", "dyn_kinetic_energy", "dyn_mass"]),
        ("耦合3维", ["dyn_coupling_eta", "dyn_force_ratio_WD", "dyn_friction_ratio"]),
        ("动量+耦合", ["dyn_momentum", "dyn_momentum_W", "dyn_coupling_eta"]),
        ("力+耦合", ["dyn_force_net", "dyn_force_W", "dyn_coupling_eta"]),
        ("全部9维", list(best_dyn_feats.columns)),
        ("η单独", ["dyn_coupling_eta"]),
        ("动量2维", ["dyn_momentum", "dyn_momentum_W"]),
        ("动能+质量", ["dyn_kinetic_energy", "dyn_mass"]),
    ]

    print("  {:<35s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "组合", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 80)

    combo_results = []
    for name, feats in combos:
        available = [f for f in feats if f in best_dyn_feats.columns]
        if not available:
            continue
        exp_feats = pd.concat([v55_base, best_dyn_feats[available]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
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

    # 8. 动力学特征重要性排名
    print("\n【8. 动力学特征重要性排名】")
    best_result = mode_results[best_mode]
    for scenario, imp, names in [
        ("TOP_EXIT", best_result["top_imp"], best_result["exp_names"]),
        ("DIP_BUY", best_result["dip_imp"], best_result["exp_names"]),
    ]:
        print("\n  {} 场景:".format(scenario))
        fi = sorted(zip(names, imp), key=lambda x: x[1], reverse=True)
        total = len(names)
        for rank, (feat, importance) in enumerate(fi, 1):
            if feat in best_dyn_feats.columns:
                pct = int(rank / total * 100)
                print("    #{:>3d} {:<32s}  重要性={:>8.1f}  Top{}%".format(
                    rank, feat, importance, pct))

    # 9. 总结
    print("\n" + "=" * 80)
    print("  【Phase 2 验证总结】")
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
        single_positive = [r for r in combo_results if r["d_top"] > 0 or r["d_dip"] > 0]
        if single_positive:
            decision = "🟡 观望：仅单场景提升"
        else:
            decision = "❌ 回退：无提升"

    print("\n  最佳质量模式: {}".format(best_mode))
    print("  决策: {}".format(decision))

    # 保存结果
    output = {
        "analysis_date": str(pd.Timestamp.now()),
        "phase": "Phase 2 - Dynamics",
        "best_mass_mode": best_mode,
        "v55_baseline": {"top_exit": v55_top, "dip_buy": v55_dip},
        "mode_results": {k: {kk: vv for kk, vv in v.items() if kk not in ["top_imp", "dip_imp", "exp_names"]}
                         for k, v in mode_results.items()},
        "single_results": single_results,
        "combo_results": combo_results,
        "best_combo": both_positive[0] if both_positive else None,
        "decision": decision,
    }
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/pitd_phase2_result.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print("\n  结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
