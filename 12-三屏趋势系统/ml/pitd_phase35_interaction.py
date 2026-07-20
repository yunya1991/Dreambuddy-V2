"""PITD Phase 3.5: 物理-哲学交互特征验证

基于Phase 1-3的物理量与V5.5哲学特征构建交互特征，
借鉴V5.5 fed_level_x_cycle_sim的成功模式：
让物理量"调制"哲学特征，而非独立作为特征输入。

物理量来源（已验证有物理意义）：
- η (dyn_coupling_eta): 理论1验证成功，2.86x单调递增
- field_gradient (势能梯度): DIP场景有提升信号
- momentum_W (周线动量): Phase 2重要性Top30%
- kinetic_energy (动能): Phase 2重要性Top21%

哲学量来源（V5.5已验证有效）：
- halving_months_after: V4核心特征
- drawdown_vs_hist_avg: V5.3精选特征（独立信息76.4%）
- cycle_path_similarity: V5.3精选特征
- fed_rate_level: V5.4精选特征
- ath_drawdown_pct: V2核心特征

交互逻辑：
- η × drawdown_vs_hist: 趋势弱+周期偏离 → 反转信号增强
- η × halving_months: 趋势强+减半周期 → 顺势信号增强
- field_gradient × cycle_path_similarity: 阻力方向+周期相似 → 路径确认
- momentum_W × fed_rate_level: 宏观动量+利率 → 流动性驱动

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
from ml.pitd_kinematics_engineer import KinematicsEngineer
from ml.pitd_dynamics_engineer import DynamicsEngineer
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


def build_interaction_features(phil_feats, kin_feats, dyn_feats, pf_feats) -> pd.DataFrame:
    """构建物理-哲学交互特征

    设计原则：
    1. 物理量"调制"哲学量，捕捉非线性关系
    2. 借鉴V5.5 fed_level_x_cycle_sim成功模式（乘法交互）
    3. 重点使用已验证有物理意义的量（η, 梯度, 动量, 动能）
    """
    interactions = {}

    # === η (耦合效率) × 哲学特征 ===
    # 理论1：η高=趋势强(顺势), η低=趋势弱(反转)
    eta = dyn_feats["dyn_coupling_eta"]
    interactions["eta_x_halving_months"] = eta * phil_feats["halving_months_after"]
    interactions["eta_x_drawdown_vs_hist"] = eta * phil_feats["drawdown_vs_hist_avg"]
    interactions["eta_x_cycle_path_sim"] = eta * phil_feats["cycle_path_similarity"]
    interactions["eta_x_ath_drawdown"] = eta * phil_feats["ath_drawdown_pct"]
    interactions["eta_x_fed_rate_level"] = eta * phil_feats["fed_rate_level"]

    # === 势能梯度 × 哲学特征 ===
    # 阻力方向与周期信号的交互
    grad_total = pf_feats["field_gradient_total"]
    interactions["grad_x_halving_months"] = grad_total * phil_feats["halving_months_after"]
    interactions["grad_x_drawdown_vs_hist"] = grad_total * phil_feats["drawdown_vs_hist_avg"]
    interactions["grad_x_cycle_path_sim"] = grad_total * phil_feats["cycle_path_similarity"]

    # 均线梯度（Phase 3中Top4%重要性）
    grad_ma = pf_feats["field_gradient_ma"]
    interactions["grad_ma_x_halving_months"] = grad_ma * phil_feats["halving_months_after"]
    interactions["grad_ma_x_cycle_path_sim"] = grad_ma * phil_feats["cycle_path_similarity"]

    # === 动量/动能 × 哲学特征 ===
    momentum_W = dyn_feats["dyn_momentum_W"]
    kinetic_energy = dyn_feats["dyn_kinetic_energy"]
    interactions["momW_x_halving_months"] = momentum_W * phil_feats["halving_months_after"]
    interactions["momW_x_fed_rate_level"] = momentum_W * phil_feats["fed_rate_level"]
    interactions["kinetic_x_drawdown_vs_hist"] = kinetic_energy * phil_feats["drawdown_vs_hist_avg"]
    interactions["kinetic_x_cycle_path_sim"] = kinetic_energy * phil_feats["cycle_path_similarity"]

    # === 运动学量 × 哲学特征 ===
    # jerk（突变）在周期特定阶段的意义
    jerk_W = kin_feats["kin_jerk_W"]
    interactions["jerkW_x_halving_months"] = jerk_W * phil_feats["halving_months_after"]
    interactions["jerkW_x_drawdown_vs_hist"] = jerk_W * phil_feats["drawdown_vs_hist_avg"]

    # 速度比（大小周期速度比）×周期偏离
    speed_ratio = kin_feats["kin_speed_ratio_WD"]
    interactions["speed_ratio_x_drawdown_vs_hist"] = speed_ratio * phil_feats["drawdown_vs_hist_avg"]

    # === 非对称交互 ===
    # (1-η) × drawdown: 趋势弱 + 周期偏离 → 反转预警
    interactions["decoupling_x_drawdown"] = (1 - eta) * phil_feats["drawdown_vs_hist_avg"]
    # (1-η) × ath_drawdown: 趋势弱 + 深跌 → 抄底信号
    interactions["decoupling_x_ath_dd"] = (1 - eta) * phil_feats["ath_drawdown_pct"]

    # === 条件交互（分段） ===
    # η > 0.2（强趋势）时的动量增强
    strong_trend_mask = (eta > 0.2).astype(float)
    interactions["strong_trend_momentum"] = strong_trend_mask * momentum_W
    # η < 0.1（弱趋势）时的势能增强
    weak_trend_mask = (eta < 0.1).astype(float)
    interactions["weak_trend_gradient"] = weak_trend_mask * grad_total.abs()

    return pd.DataFrame(interactions, index=phil_feats.index)


def main():
    print("=" * 80)
    print("  PITD Phase 3.5: 物理-哲学交互特征验证")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    print("\n  BTC日线: {}天".format(len(prices)))

    # 1. 计算所有特征
    print("\n【1. 特征计算】")
    t0 = time.time()

    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    kin_fe = KinematicsEngineer()
    kin_features = kin_fe.extract_series(prices)

    dyn_fe = DynamicsEngineer(mass_mode="constant")  # Phase 2中constant模式DIP最佳
    dyn_features = dyn_fe.extract_series(prices, kin_features)

    pf_fe = PotentialFieldEngineer()
    pf_features = pf_fe.extract_series(prices)

    interaction_features = build_interaction_features(
        phil_features, kin_features, dyn_features, pf_features
    )

    print("  趋势特征: {}维".format(trend_features.shape[1]))
    print("  哲学特征(V5.5): {}维".format(phil_features.shape[1]))
    print("  运动学特征: {}维".format(kin_features.shape[1]))
    print("  动力学特征: {}维".format(dyn_features.shape[1]))
    print("  势能场特征: {}维".format(pf_features.shape[1]))
    print("  交互特征: {}维".format(interaction_features.shape[1]))
    print("  计算耗时: {:.2f}s".format(time.time() - t0))

    # 2. 构建基线
    v55_base = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v55_names = list(v55_base.columns)

    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")

    # 3. Walk-Forward验证
    print("\n【2. Walk-Forward验证】")

    print("\n  2.1 V5.5基线")
    v55_top, v55_top_tr, v55_top_dec, _ = walk_forward_validation(v55_base, top_exit_labels, v55_names)
    v55_dip, v55_dip_tr, v55_dip_dec, _ = walk_forward_validation(v55_base, dip_buy_labels, v55_names)
    print("    TOP_EXIT: {:.4f} (decay={:.1%})".format(v55_top, v55_top_dec))
    print("    DIP_BUY:  {:.4f} (decay={:.1%})".format(v55_dip, v55_dip_dec))

    # 4. 逐个交互特征消融实验
    print("\n【3. 逐个交互特征消融实验】")
    print("  {:<35s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "交互特征", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 85)

    single_results = []
    interaction_features = interaction_features.fillna(0.0).replace([np.inf, -np.inf], 0.0)

    for feat in interaction_features.columns:
        exp_feats = pd.concat([v55_base, interaction_features[[feat]]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_feats.columns)
        top_auc, _, _, _ = walk_forward_validation(exp_feats, top_exit_labels, exp_names)
        dip_auc, _, _, _ = walk_forward_validation(exp_feats, dip_buy_labels, exp_names)
        d_top = top_auc - v55_top
        d_dip = dip_auc - v55_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("  {:<35s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            feat, top_auc, d_top, dip_auc, d_dip, verdict))
        single_results.append({"feat": feat, "d_top": d_top, "d_dip": d_dip,
                               "top_auc": top_auc, "dip_auc": dip_auc})

    # 5. 按物理量分组测试
    print("\n【4. 按物理量分组测试】")

    groups = {
        "η交互(5维)": [f for f in interaction_features.columns if f.startswith("eta_")],
        "梯度交互(5维)": [f for f in interaction_features.columns if f.startswith("grad")],
        "动量交互(4维)": [f for f in interaction_features.columns if f.startswith("mom") or f.startswith("kinetic")],
        "运动学交互(3维)": [f for f in interaction_features.columns if f.startswith("jerk") or f.startswith("speed")],
        "非对称交互(2维)": [f for f in interaction_features.columns if f.startswith("decoupling")],
        "条件交互(2维)": [f for f in interaction_features.columns if f.startswith("strong") or f.startswith("weak")],
    }

    print("  {:<25s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "分组", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 75)

    group_results = []
    for name, feats in groups.items():
        available = [f for f in feats if f in interaction_features.columns]
        if not available:
            continue
        exp_feats = pd.concat([v55_base, interaction_features[available]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_feats.columns)
        top_auc, _, top_dec, _ = walk_forward_validation(exp_feats, top_exit_labels, exp_names)
        dip_auc, _, dip_dec, _ = walk_forward_validation(exp_feats, dip_buy_labels, exp_names)
        d_top = top_auc - v55_top
        d_dip = dip_auc - v55_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("  {:<25s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            name, top_auc, d_top, dip_auc, d_dip, verdict))
        group_results.append({"name": name, "feats": available, "d_top": d_top, "d_dip": d_dip,
                              "top_auc": top_auc, "dip_auc": dip_auc,
                              "top_decay": top_dec, "dip_decay": dip_dec})

    # 6. 精选最佳交互特征组合
    print("\n【5. 精选组合测试】")

    # 选出单特征测试中双场景提升或接近提升的
    promising = [r for r in single_results if r["d_top"] > -0.005 and r["d_dip"] > -0.005]
    promising.sort(key=lambda x: x["d_top"] + x["d_dip"], reverse=True)
    print("  有潜力的交互特征({}个): {}".format(
        len(promising), [r["feat"] for r in promising[:10]]))

    combos = [
        ("全部交互特征", list(interaction_features.columns)),
        ("Top5潜力", [r["feat"] for r in promising[:5]]),
        ("Top10潜力", [r["feat"] for r in promising[:10]]),
        ("η交互Top3", [r["feat"] for r in promising if r["feat"].startswith("eta_")][:3]),
        ("梯度交互Top3", [r["feat"] for r in promising if r["feat"].startswith("grad")][:3]),
    ]

    print("\n  {:<25s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "组合", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 75)

    combo_results = []
    for name, feats in combos:
        available = [f for f in feats if f in interaction_features.columns]
        if not available:
            continue
        exp_feats = pd.concat([v55_base, interaction_features[available]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_feats.columns)
        top_auc, _, top_dec, top_imp = walk_forward_validation(exp_feats, top_exit_labels, exp_names)
        dip_auc, _, dip_dec, dip_imp = walk_forward_validation(exp_feats, dip_buy_labels, exp_names)
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
            "top_imp": top_imp.tolist() if hasattr(top_imp, 'tolist') else list(top_imp),
            "dip_imp": dip_imp.tolist() if hasattr(dip_imp, 'tolist') else list(dip_imp),
            "exp_names": exp_names,
        })

    # 7. 特征重要性排名（最佳组合）
    if combo_results:
        # 找最佳组合
        both_positive = [r for r in combo_results if r["d_top"] > 0 and r["d_dip"] > 0]
        if both_positive:
            best = max(both_positive, key=lambda x: (x["d_top"] + x["d_dip"]) / 2)
        else:
            best = max(combo_results, key=lambda x: (x["d_top"] + x["d_dip"]) / 2)

        print("\n【6. 最佳组合特征重要性排名】")
        print("  最佳组合: {} (TOP {:+.4f}, DIP {:+.4f})".format(
            best["name"], best["d_top"], best["d_dip"]))

        for scenario, imp_key in [("TOP_EXIT", "top_imp"), ("DIP_BUY", "dip_imp")]:
            print("\n  {} 场景:".format(scenario))
            imp = best[imp_key]
            names = best["exp_names"]
            fi = sorted(zip(names, imp), key=lambda x: x[1], reverse=True)
            total = len(names)
            for rank, (feat, importance) in enumerate(fi, 1):
                if feat in interaction_features.columns:
                    pct = int(rank / total * 100)
                    print("    #{:>3d} {:<35s}  重要性={:>8.1f}  Top{}%".format(
                        rank, feat, importance, pct))

    # 8. 总结
    print("\n" + "=" * 80)
    print("  【Phase 3.5 交互特征验证总结】")
    print("=" * 80)

    both_positive = [r for r in combo_results if r["d_top"] > 0 and r["d_dip"] > 0]
    both_positive.sort(key=lambda x: (x["d_top"] + x["d_dip"]) / 2, reverse=True)

    print("\n  双场景提升的组合 ({}个):".format(len(both_positive)))
    for r in both_positive[:5]:
        comp = (r["d_top"] + r["d_dip"]) / 2
        print("  综合={:+.4f} {:<25s} TOP {:+.4f} DIP {:+.4f} decay:{:.1%}/{:.1%}".format(
            comp, r["name"], r["d_top"], r["d_dip"], r["top_decay"], r["dip_decay"]))

    # 单特征双场景提升
    single_both_pos = [r for r in single_results if r["d_top"] > 0 and r["d_dip"] > 0]
    if single_both_pos:
        print("\n  单特征双场景提升 ({}个):".format(len(single_both_pos)))
        for r in single_both_pos:
            print("  {:<35s} TOP {:+.4f} DIP {:+.4f}".format(r["feat"], r["d_top"], r["d_dip"]))

    if both_positive:
        best = both_positive[0]
        if best["d_top"] > 0.005 and best["d_dip"] > 0.005:
            decision = "✅ 采纳：双场景显著提升"
        elif (best["d_top"] + best["d_dip"]) / 2 > 0.002:
            decision = "🟡 部分采纳：有提升但幅度有限"
        else:
            decision = "🟡 观望：提升不显著"
    elif single_both_pos:
        decision = "🟡 观望：单特征有提升但组合未通过"
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
        "phase": "Phase 3.5 - Physics-Philosophy Interaction",
        "v55_baseline": {"top_exit": v55_top, "dip_buy": v55_dip},
        "single_results": single_results,
        "group_results": [{k: v for k, v in r.items()} for r in group_results],
        "combo_results": [{k: v for k, v in r.items() if k not in ["top_imp", "dip_imp", "exp_names"]}
                          for r in combo_results],
        "best_combo": both_positive[0] if both_positive else None,
        "decision": decision,
    }
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/pitd_phase35_interaction_result.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print("\n  结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
