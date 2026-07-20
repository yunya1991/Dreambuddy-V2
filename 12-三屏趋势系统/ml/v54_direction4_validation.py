"""V5.4 方向4验证：V5.3 + 美联储精选特征

在V5.3（drawdown_vs_hist_avg + cycle_path_similarity）基础上，
添加美联储精选特征，验证是否能进一步提升。

测试组合：
1. V5.3基线：2特征（当前最优）
2. V5.4a：+ fed_rate_level（3特征）
3. V5.4b：+ fed_rate_level + fed_rate_action（4特征）
4. V5.4c：+ fed_rate_level + rate_change_speed（新增：最近6月利率变化幅度）
5. V5.4d：交互特征 fed_rate_level × drawdown_vs_hist_avg
6. V5.4e：交互特征 ma200_distance × fed_rate_action（降息+低位抄底）
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


def load_btc_data() -> pd.DataFrame:
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def compute_fed_features(fe: PhilosophyFeatureEngineer, prices: pd.DataFrame) -> pd.DataFrame:
    """计算美联储特征（复用V5.2逻辑，但仅计算精选特征）"""
    n = len(prices)
    fed_action = np.zeros(n)
    fed_months = np.zeros(n)
    fed_level = np.zeros(n)
    rate_change_6m = np.zeros(n)  # 最近6个月利率变化
    rate_change_12m = np.zeros(n)  # 最近12个月利率变化

    for i in range(n):
        current_date = prices.index[i]
        recent_change = None
        for change_date, rate_level, action in fe.FED_RATE_CHANGES:
            if change_date <= current_date:
                recent_change = (change_date, rate_level, action)
            else:
                break

        if recent_change is None:
            fed_level[i] = 0.25
            continue

        change_date, rate_level, action_at_change = recent_change
        months_in_cycle = (current_date - change_date).days / 30.44

        # 当前利率方向
        if action_at_change == +1:
            current_action = 1.0
        elif action_at_change == -1:
            current_action = -1.0
        else:
            prev_action = 0
            for prev_change_date, _, prev_act in reversed(fe.FED_RATE_CHANGES):
                if prev_change_date < change_date and prev_act != 0:
                    prev_action = prev_act
                    break
            current_action = float(prev_action) if prev_action != 0 else 0.0

        fed_action[i] = current_action
        fed_months[i] = months_in_cycle
        fed_level[i] = rate_level

        # 最近6/12个月利率变化
        six_months_ago = current_date - pd.Timedelta(days=183)
        twelve_months_ago = current_date - pd.Timedelta(days=365)

        rate_6m_ago = rate_level
        rate_12m_ago = rate_level
        for change_date_hist, rate_level_hist, _ in fe.FED_RATE_CHANGES:
            if change_date_hist <= six_months_ago:
                rate_6m_ago = rate_level_hist
            if change_date_hist <= twelve_months_ago:
                rate_12m_ago = rate_level_hist

        rate_change_6m[i] = rate_level - rate_6m_ago
        rate_change_12m[i] = rate_level - rate_12m_ago

    return pd.DataFrame({
        "fed_rate_action": fed_action,
        "fed_months_in_cycle": fed_months,
        "fed_rate_level": fed_level,
        "rate_change_6m": rate_change_6m,
        "rate_change_12m": rate_change_12m,
    }, index=prices.index)


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
    print("  V5.4 方向4验证：V5.3 + 美联储精选特征")
    print("=" * 80)

    # 1. 加载数据
    prices = load_btc_data()
    closes = prices["close"].values
    print("\n BTC日线: {}天".format(len(prices)))

    # 2. 计算特征
    t0 = time.time()

    # 趋势特征
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    # 哲学特征（V5.3，已集成2个周期相似性特征）
    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    # 美联储精选特征
    fed_features = compute_fed_features(phil_fe, prices)

    print("  趋势特征: {}维".format(trend_features.shape[1]))
    print("  哲学特征(V5.3): {}维".format(phil_features.shape[1]))
    print("  美联储精选: {}维".format(fed_features.shape[1]))
    print("  计算耗时: {:.1f}s".format(time.time() - t0))

    # 3. V4基线（不含V5.3+美联储）
    v4_phil = phil_features.drop(columns=["drawdown_vs_hist_avg", "cycle_path_similarity"])
    v4_base = pd.concat([trend_features, v4_phil], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v4_names = list(v4_base.columns)

    # V5.3基线（当前最优：+2个周期相似性特征）
    v53_base = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v53_names = list(v53_base.columns)

    print("\n  V4基线: {}维".format(len(v4_names)))
    print("  V5.3基线: {}维 (+2周期相似)".format(len(v53_names)))

    # 4. 美联储特征数值校验
    print("\n  美联储特征数值:")
    for col in fed_features.columns:
        v = fed_features[col]
        print("    {:<20s} min={:>7.2f}  max={:>7.2f}  mean={:>7.2f}".format(
            col, v.min(), v.max(), v.mean()))

    # 5. 标签
    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")

    # 6. 定义测试组合
    combos = [
        ("V5.3基线 (2周期)", []),
        ("+ fed_rate_level", ["fed_rate_level"]),
        ("+ fed_rate_level + fed_rate_action", ["fed_rate_level", "fed_rate_action"]),
        ("+ rate_change_6m", ["rate_change_6m"]),
        ("+ rate_change_12m", ["rate_change_12m"]),
        ("+ fed_rate_level + rate_change_6m", ["fed_rate_level", "rate_change_6m"]),
        ("+ fed_level + rate_6m + rate_12m", ["fed_rate_level", "rate_change_6m", "rate_change_12m"]),
        ("+ fed_level + action + rate_6m", ["fed_rate_level", "fed_rate_action", "rate_change_6m"]),
    ]

    # 添加交互特征组合
    interaction_combos = [
        ("+ fed_level × dd_vs_hist (交互)", {
            "fed_lvl_x_dd_hist": lambda pf, ff: ff["fed_rate_level"] * pf["drawdown_vs_hist_avg"],
        }),
        ("+ ma200_dist × fed_action (交互)", {
            "ma200_x_fed_act": lambda pf, ff: pf["weekly_ma200_distance"] * ff["fed_rate_action"],
        }),
        ("+ ath_dd × fed_level (交互)", {
            "ath_dd_x_fed_lvl": lambda pf, ff: pf["ath_drawdown_pct"] * ff["fed_rate_level"],
        }),
        ("+ fed_level + 2交互", {
            "fed_lvl_x_dd_hist": lambda pf, ff: ff["fed_rate_level"] * pf["drawdown_vs_hist_avg"],
            "ma200_x_fed_act": lambda pf, ff: pf["weekly_ma200_distance"] * ff["fed_rate_action"],
            "fed_rate_level": lambda pf, ff: ff["fed_rate_level"],
        }),
    ]

    # 7. 运行基础组合测试
    print("\n" + "=" * 80)
    print("  【基础组合测试】")
    print("=" * 80)
    print("  {:<40s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}  {:>6s}".format(
        "组合", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP", "综合"))
    print("  " + "-" * 90)

    results = []
    for name, fed_feat_names in combos:
        if not fed_feat_names:
            # V5.3基线
            exp_feats = v53_base.copy()
            exp_names = v53_names[:]
        else:
            available = [f for f in fed_feat_names if f in fed_features.columns]
            exp_feats = pd.concat([v53_base, fed_features[available]], axis=1)
            exp_feats = exp_feats.fillna(0.0).replace([np.inf, -np.inf], 0.0)
            exp_names = list(exp_feats.columns)

        top_auc, top_tr, top_decay, top_imp = walk_forward_validation(
            exp_feats, top_exit_labels, exp_names)
        dip_auc, dip_tr, dip_decay, dip_imp = walk_forward_validation(
            exp_feats, dip_buy_labels, exp_names)

        results.append({
            "name": name,
            "n_features": len(exp_names),
            "top_auc": top_auc,
            "top_train": top_tr,
            "top_decay": top_decay,
            "dip_auc": dip_auc,
            "dip_train": dip_tr,
            "dip_decay": dip_decay,
            "top_imp": top_imp,
            "dip_imp": dip_imp,
        })

    # 交互特征组合
    print("\n" + "=" * 80)
    print("  【交互特征组合测试】")
    print("=" * 80)
    print("  {:<40s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}  {:>6s}".format(
        "组合", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP", "综合"))
    print("  " + "-" * 90)

    for name, interaction_dict in interaction_combos:
        inter_df = pd.DataFrame(index=phil_features.index)
        for feat_name, calc_fn in interaction_dict.items():
            if feat_name in fed_features.columns:
                inter_df[feat_name] = fed_features[feat_name].values
            else:
                inter_df[feat_name] = calc_fn(phil_features, fed_features)

        exp_feats = pd.concat([v53_base, inter_df], axis=1)
        exp_feats = exp_feats.fillna(0.0).replace([np.inf, -np.inf], 0.0)
        exp_names = list(exp_feats.columns)

        top_auc, top_tr, top_decay, top_imp = walk_forward_validation(
            exp_feats, top_exit_labels, exp_names)
        dip_auc, dip_tr, dip_decay, dip_imp = walk_forward_validation(
            exp_feats, dip_buy_labels, exp_names)

        results.append({
            "name": name,
            "n_features": len(exp_names),
            "top_auc": top_auc,
            "top_train": top_tr,
            "top_decay": top_decay,
            "dip_auc": dip_auc,
            "dip_train": dip_tr,
            "dip_decay": dip_decay,
            "top_imp": top_imp,
            "dip_imp": dip_imp,
        })

    # V4基线对比
    v4_top_auc, v4_top_tr, v4_top_decay, _ = walk_forward_validation(
        v4_base, top_exit_labels, v4_names)
    v4_dip_auc, v4_dip_tr, v4_dip_decay, _ = walk_forward_validation(
        v4_base, dip_buy_labels, v4_names)

    # 8. 输出结果
    v53_top_auc = results[0]["top_auc"]
    v53_dip_auc = results[0]["dip_auc"]

    all_results_for_print = []
    for r in results:
        delta_top = r["top_auc"] - v53_top_auc
        delta_dip = r["dip_auc"] - v53_dip_auc
        composite = (delta_top + delta_dip) / 2

        if delta_top > 0 and delta_dip > 0:
            verdict = "✅✅"
        elif delta_top > 0 or delta_dip > 0:
            verdict = "🟡"
        else:
            verdict = "❌❌"

        all_results_for_print.append((r["name"], r["n_features"], r["top_auc"], delta_top,
                                       r["dip_auc"], delta_dip, composite, verdict, r))

    # 全部打印
    for name, n_feat, top_auc, d_top, dip_auc, d_dip, comp, verdict, _ in all_results_for_print:
        print("  {:<40s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            name, top_auc, d_top, dip_auc, d_dip, verdict))

    # 9. 排名
    sorted_results = sorted(all_results_for_print, key=lambda x: x[6], reverse=True)
    print("\n" + "=" * 80)
    print("  【综合排名（Top 5）】")
    print("=" * 80)
    for i, (name, n_feat, top_auc, d_top, dip_auc, d_dip, comp, verdict, r) in enumerate(sorted_results[:5], 1):
        print("  #{} {} ({}) → 综合={:+.4f} (TOP {:+.4f}, DIP {:+.4f}) decay: TOP={:.1%} DIP={:.1%}".format(
            i, name, verdict, comp, d_top, d_dip, r["top_decay"], r["dip_decay"]))

    # 10. V4 vs V5.3 vs 最佳
    best = sorted_results[0]
    print("\n" + "=" * 80)
    print("  【三级对比：V4 → V5.3 → 最佳组合】")
    print("=" * 80)

    print("""
┌──────────┬────────────┬────────────┬────────────┬────────────┐
│          │   V4基线   │   V5.3     │  最佳:{} │
│          │   ({}维)   │   ({}维)   │    ({}维)   │
├──────────┼────────────┼────────────┼────────────┼────────────┤
│ TOP_EXIT │   {:.4f}   │   {:.4f}   │   {:.4f}   │
│  Δvs V4  │            │  {:+.4f}   │  {:+.4f}   │
│  decay   │   {:.1%}   │   {:.1%}   │   {:.1%}   │
├──────────┼────────────┼────────────┼────────────┼────────────┤
│ DIP_BUY  │   {:.4f}   │   {:.4f}   │   {:.4f}   │
│  Δvs V4  │            │  {:+.4f}   │  {:+.4f}   │
│  decay   │   {:.1%}   │   {:.1%}   │   {:.1%}   │
└──────────┴────────────┴────────────┴────────────┴────────────┘
""".format(
    best[0][:8], len(v4_names), len(v53_names), best[1],
    v4_top_auc, v53_top_auc, best[2],
    v53_top_auc - v4_top_auc, best[2] - v4_top_auc,
    v4_top_decay, results[0]["top_decay"], best[8]["top_decay"],
    v4_dip_auc, v53_dip_auc, best[4],
    v53_dip_auc - v4_dip_auc, best[4] - v4_dip_auc,
    v4_dip_decay, results[0]["dip_decay"], best[8]["dip_decay"],
))

    # 11. 最佳组合的新增特征重要性排名
    best_name = best[0]
    best_result = best[8]
    print("  最佳组合: {}".format(best_name))
    print("  新增特征重要性排名(TOP_EXIT):")
    fi_top = sorted(zip(best[8]["top_imp"], range(len(best[8]["top_imp"]))), reverse=True)
    all_feat_names = list(range(len(best[8]["top_imp"])))
    # 需要特征名列表，从v53 + 新增特征推导
    # 简化：打印新增特征在总排名中的位置

    # 保存结果
    output = {
        "analysis_date": str(pd.Timestamp.now()),
        "v4_baseline": {
            "features": len(v4_names),
            "top_exit_auc": v4_top_auc,
            "dip_buy_auc": v4_dip_auc,
        },
        "v53_baseline": {
            "features": len(v53_names),
            "top_exit_auc": v53_top_auc,
            "dip_buy_auc": v53_dip_auc,
            "delta_top": v53_top_auc - v4_top_auc,
            "delta_dip": v53_dip_auc - v4_dip_auc,
        },
        "best_combo": {
            "name": best_name,
            "features": best[1],
            "top_exit_auc": best[2],
            "dip_buy_auc": best[4],
            "delta_top_vs_v53": best[3],
            "delta_dip_vs_v53": best[5],
            "composite_score": best[6],
        },
        "all_results": [
            {k: v for k, v in r[8].items() if k not in ["top_imp", "dip_imp"]}
            | {"name": r[0], "delta_top_vs_v53": r[3], "delta_dip_vs_v53": r[5], "composite": r[6]}
            for r in all_results_for_print
        ],
    }

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/v54_direction4_result.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("  结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
