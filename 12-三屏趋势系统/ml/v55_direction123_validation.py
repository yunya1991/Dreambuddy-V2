"""V5.5 方向1/2/3 美联储特征深度探索

基于已集成的V5.4基线（V5.3 + fed_rate_level，27维哲学特征），
分别探索三个方向的衍生特征：

方向1：利率状态特征（纯状态，无时间编码）
- real_rate_proxy: 利率水平 - BTC年度涨幅代理（高利率+高涨幅=过热）
- rate_zscore: 当前利率相对历史均值的标准化值
- rate_change_6m: 最近6个月利率变化幅度
- rate_volatility: 利率变化频率（过去12个月变动次数）

方向2：利率×价格交互特征
- fed_level_x_ath_dd: 利率水平 × 回撤深度
- fed_level_x_ma200_dist: 利率水平 × MA200距离
- fed_level_x_halving_months: 利率水平 × 减半后月数
- fed_action_x_btc_bull: 利率方向 × BTC牛市状态

方向3：利率周期阶段分类特征
- rate_cycle_phase: 利率周期阶段（0=宽松期/1=加息期/2=高位期/3=降息期）
- rate_cycle_progress: 当前阶段进度[0,1]
- is_tightening: 是否处于加息周期(1/0)
- is_easing: 是否处于降息周期(1/0)
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


def compute_all_fed_features(fe: PhilosophyFeatureEngineer, prices: pd.DataFrame) -> pd.DataFrame:
    """计算全部美联储衍生特征"""
    n = len(prices)
    dates = prices.index

    # 基础变量
    fed_action = np.zeros(n)
    fed_months = np.zeros(n)
    fed_level = np.zeros(n)

    # 方向1：利率状态特征
    rate_change_6m = np.zeros(n)
    rate_change_12m = np.zeros(n)
    rate_zscore = np.zeros(n)
    rate_change_freq = np.zeros(n)  # 过去12个月变动次数

    # 方向3：利率周期阶段
    rate_cycle_phase = np.zeros(n)  # 0=宽松/1=加息/2=高位/3=降息
    rate_cycle_progress = np.zeros(n)
    is_tightening = np.zeros(n)
    is_easing = np.zeros(n)

    # 先计算每个时间点的利率水平和方向
    for i in range(n):
        current_date = dates[i]
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

        # 方向1：最近6/12个月利率变化
        six_months_ago = current_date - pd.Timedelta(days=183)
        twelve_months_ago = current_date - pd.Timedelta(days=365)
        rate_6m_ago = rate_level
        rate_12m_ago = rate_level
        for cd, rl, _ in fe.FED_RATE_CHANGES:
            if cd <= six_months_ago:
                rate_6m_ago = rl
            if cd <= twelve_months_ago:
                rate_12m_ago = rl
        rate_change_6m[i] = rate_level - rate_6m_ago
        rate_change_12m[i] = rate_level - rate_12m_ago

        # 过去12个月变动次数
        change_count = 0
        for cd, _, act in fe.FED_RATE_CHANGES:
            if twelve_months_ago < cd <= current_date and act != 0:
                change_count += 1
        rate_change_freq[i] = change_count

        # 方向3：利率周期阶段
        # 判断当前处于加息/降息/高位/宽松
        if current_action == 1.0:
            rate_cycle_phase[i] = 1.0  # 加息期
            is_tightening[i] = 1.0
        elif current_action == -1.0:
            rate_cycle_phase[i] = 3.0  # 降息期
            is_easing[i] = 1.0
        else:
            # 持平期：判断是高位还是宽松
            if rate_level >= 2.0:
                rate_cycle_phase[i] = 2.0  # 高位期
            else:
                rate_cycle_phase[i] = 0.0  # 宽松期

        # 阶段进度：当前方向持续的月数 / 历史平均持续时间
        if current_action != 0:
            avg_duration = 24.0  # 假设平均加息/降息周期24个月
            rate_cycle_progress[i] = min(1.0, months_in_cycle / avg_duration)

    # 利率z-score（相对历史均值）
    level_mean = np.mean(fed_level)
    level_std = np.std(fed_level)
    if level_std > 0:
        rate_zscore = (fed_level - level_mean) / level_std

    return pd.DataFrame({
        "fed_rate_action": fed_action,
        "fed_months_in_cycle": fed_months,
        "fed_rate_level": fed_level,
        # 方向1：利率状态特征
        "rate_change_6m": rate_change_6m,
        "rate_change_12m": rate_change_12m,
        "rate_zscore": rate_zscore,
        "rate_change_freq": rate_change_freq,
        # 方向3：利率周期阶段
        "rate_cycle_phase": rate_cycle_phase,
        "rate_cycle_progress": rate_cycle_progress,
        "is_tightening": is_tightening,
        "is_easing": is_easing,
    }, index=prices.index)


def compute_interaction_features(phil_features: pd.DataFrame, fed_features: pd.DataFrame) -> pd.DataFrame:
    """方向2：利率×价格交互特征"""
    return pd.DataFrame({
        "fed_level_x_ath_dd": fed_features["fed_rate_level"] * phil_features["ath_drawdown_pct"],
        "fed_level_x_ma200_dist": fed_features["fed_rate_level"] * phil_features["weekly_ma200_distance"],
        "fed_level_x_halving": fed_features["fed_rate_level"] * phil_features["halving_months_after"],
        "fed_action_x_btc_bull": fed_features["fed_rate_action"] * phil_features["btc_bull_confirmed"],
        "fed_level_x_dd_vs_hist": fed_features["fed_rate_level"] * phil_features["drawdown_vs_hist_avg"],
        "fed_level_x_cycle_sim": fed_features["fed_rate_level"] * phil_features["cycle_path_similarity"],
        "rate_change6m_x_ath_dd": fed_features["rate_change_6m"] * phil_features["ath_drawdown_pct"],
        "is_easing_x_ma200_below": fed_features["is_easing"] * (phil_features["weekly_ma200_distance"] < 0).astype(float),
    }, index=phil_features.index)


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


def walk_forward_validation(features, labels, feature_names,
                            n_splits=12, train_days=730, test_days=180, step_days=180):
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


def run_combo(v53_base, v53_names, extra_df, extra_feats, top_labels, dip_labels, combo_name):
    """运行单个组合"""
    if extra_feats:
        available = [f for f in extra_feats if f in extra_df.columns]
        if available:
            exp_feats = pd.concat([v53_base, extra_df[available]], axis=1)
        else:
            exp_feats = v53_base.copy()
    else:
        exp_feats = v53_base.copy()
    exp_feats = exp_feats.fillna(0.0).replace([np.inf, -np.inf], 0.0)
    exp_names = list(exp_feats.columns)

    top_auc, top_tr, top_dec, top_imp = walk_forward_validation(exp_feats, top_labels, exp_names)
    dip_auc, dip_tr, dip_dec, dip_imp = walk_forward_validation(exp_feats, dip_labels, exp_names)
    return top_auc, dip_auc, top_dec, dip_dec, top_imp, dip_imp, exp_names


def main():
    print("=" * 80)
    print("  V5.5 方向1/2/3 美联储特征深度探索")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    print("\n  BTC日线: {}天".format(len(prices)))

    # 计算特征
    t0 = time.time()
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    fed_features = compute_all_fed_features(phil_fe, prices)
    interaction_features = compute_interaction_features(phil_features, fed_features)

    # V5.4基线（已包含fed_rate_level）
    v54_base = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v54_names = list(v54_base.columns)

    print("  趋势特征: {}维".format(trend_features.shape[1]))
    print("  哲学特征(V5.4): {}维 (含fed_rate_level)".format(phil_features.shape[1]))
    print("  美联储衍生: {}维".format(fed_features.shape[1]))
    print("  交互特征: {}维".format(interaction_features.shape[1]))
    print("  V5.4基线: {}维".format(len(v54_names)))
    print("  计算耗时: {:.1f}s".format(time.time() - t0))

    # 标签
    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")

    # V5.4基线AUC
    print("\n【V5.4基线】")
    v54_top, v54_top_tr, v54_top_dec, _ = walk_forward_validation(v54_base, top_exit_labels, v54_names)
    v54_dip, v54_dip_tr, v54_dip_dec, _ = walk_forward_validation(v54_base, dip_buy_labels, v54_names)
    print("  TOP_EXIT: {:.4f} (decay={:.1%})".format(v54_top, v54_top_dec))
    print("  DIP_BUY:  {:.4f} (decay={:.1%})".format(v54_dip, v54_dip_dec))

    # ========== 方向1：利率状态特征 ==========
    print("\n" + "=" * 80)
    print("  【方向1：利率状态特征】")
    print("=" * 80)

    direction1_feats = ["rate_change_6m", "rate_change_12m", "rate_zscore", "rate_change_freq"]
    direction1_combos = [
        ("D1: + rate_zscore", ["rate_zscore"]),
        ("D1: + rate_change_6m", ["rate_change_6m"]),
        ("D1: + rate_change_12m", ["rate_change_12m"]),
        ("D1: + rate_change_freq", ["rate_change_freq"]),
        ("D1: + rate_zscore + rate_change_6m", ["rate_zscore", "rate_change_6m"]),
        ("D1: + rate_zscore + rate_change_freq", ["rate_zscore", "rate_change_freq"]),
        ("D1: 全部4个", direction1_feats),
    ]

    print("  {:<40s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "组合", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 80)

    d1_results = []
    for name, feats in direction1_combos:
        top_auc, dip_auc, top_dec, dip_dec, _, _, _ = run_combo(
            v54_base, v54_names, fed_features, feats, top_exit_labels, dip_buy_labels, name)
        d_top = top_auc - v54_top
        d_dip = dip_auc - v54_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("  {:<40s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            name, top_auc, d_top, dip_auc, d_dip, verdict))
        d1_results.append({"name": name, "features": feats, "top_auc": top_auc, "dip_auc": dip_auc,
                           "delta_top": d_top, "delta_dip": d_dip, "top_decay": top_dec, "dip_decay": dip_dec})

    # ========== 方向2：利率×价格交互特征 ==========
    print("\n" + "=" * 80)
    print("  【方向2：利率×价格交互特征】")
    print("=" * 80)

    direction2_feats = list(interaction_features.columns)
    direction2_combos = [
        ("D2: + fed_level_x_ath_dd", ["fed_level_x_ath_dd"]),
        ("D2: + fed_level_x_ma200_dist", ["fed_level_x_ma200_dist"]),
        ("D2: + fed_level_x_halving", ["fed_level_x_halving"]),
        ("D2: + fed_action_x_btc_bull", ["fed_action_x_btc_bull"]),
        ("D2: + fed_level_x_dd_vs_hist", ["fed_level_x_dd_vs_hist"]),
        ("D2: + fed_level_x_cycle_sim", ["fed_level_x_cycle_sim"]),
        ("D2: + rate_change6m_x_ath_dd", ["rate_change6m_x_ath_dd"]),
        ("D2: + is_easing_x_ma200_below", ["is_easing_x_ma200_below"]),
        ("D2: 全部8个", direction2_feats),
        ("D2: 精选3个", ["fed_level_x_ath_dd", "fed_level_x_dd_vs_hist", "is_easing_x_ma200_below"]),
    ]

    print("  {:<40s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "组合", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 80)

    d2_results = []
    for name, feats in direction2_combos:
        top_auc, dip_auc, top_dec, dip_dec, _, _, _ = run_combo(
            v54_base, v54_names, interaction_features, feats, top_exit_labels, dip_buy_labels, name)
        d_top = top_auc - v54_top
        d_dip = dip_auc - v54_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("  {:<40s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            name, top_auc, d_top, dip_auc, d_dip, verdict))
        d2_results.append({"name": name, "features": feats, "top_auc": top_auc, "dip_auc": dip_auc,
                          "delta_top": d_top, "delta_dip": d_dip, "top_decay": top_dec, "dip_decay": dip_dec})

    # ========== 方向3：利率周期阶段分类特征 ==========
    print("\n" + "=" * 80)
    print("  【方向3：利率周期阶段分类特征】")
    print("=" * 80)

    direction3_feats = ["rate_cycle_phase", "rate_cycle_progress", "is_tightening", "is_easing"]
    direction3_combos = [
        ("D3: + rate_cycle_phase", ["rate_cycle_phase"]),
        ("D3: + rate_cycle_progress", ["rate_cycle_progress"]),
        ("D3: + is_tightening", ["is_tightening"]),
        ("D3: + is_easing", ["is_easing"]),
        ("D3: + is_tightening + is_easing", ["is_tightening", "is_easing"]),
        ("D3: + phase + progress", ["rate_cycle_phase", "rate_cycle_progress"]),
        ("D3: 全部4个", direction3_feats),
    ]

    print("  {:<40s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "组合", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 80)

    d3_results = []
    for name, feats in direction3_combos:
        top_auc, dip_auc, top_dec, dip_dec, _, _, _ = run_combo(
            v54_base, v54_names, fed_features, feats, top_exit_labels, dip_buy_labels, name)
        d_top = top_auc - v54_top
        d_dip = dip_auc - v54_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("  {:<40s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            name, top_auc, d_top, dip_auc, d_dip, verdict))
        d3_results.append({"name": name, "features": feats, "top_auc": top_auc, "dip_auc": dip_auc,
                          "delta_top": d_top, "delta_dip": d_dip, "top_decay": top_dec, "dip_decay": dip_dec})

    # ========== 跨方向组合 ==========
    print("\n" + "=" * 80)
    print("  【跨方向组合：方向1+2+3精选】")
    print("=" * 80)

    # 从每个方向选最佳1-2个
    cross_combos = [
        ("跨: D1最佳 + D2最佳", None),  # 动态填充
        ("跨: rate_zscore + is_easing + fed_level_x_dd_vs_hist",
         {"rate_zscore": fed_features, "is_easing": fed_features, "fed_level_x_dd_vs_hist": interaction_features}),
        ("跨: rate_change_freq + is_easing + is_easing_x_ma200_below",
         {"rate_change_freq": fed_features, "is_easing": fed_features, "is_easing_x_ma200_below": interaction_features}),
        ("跨: rate_zscore + rate_change_freq + is_easing + fed_level_x_dd_vs_hist",
         {"rate_zscore": fed_features, "rate_change_freq": fed_features,
          "is_easing": fed_features, "fed_level_x_dd_vs_hist": interaction_features}),
    ]

    print("  {:<55s}  {:>9s}  {:>9s}  {:>9s}  {:>9s}".format(
        "组合", "TOP_AUC", "ΔTOP", "DIP_AUC", "ΔDIP"))
    print("  " + "-" * 95)

    cross_results = []
    for name, feat_sources in cross_combos:
        if feat_sources is None:
            continue
        extra_df = pd.DataFrame(index=phil_features.index)
        for feat_name, source_df in feat_sources.items():
            if feat_name in source_df.columns:
                extra_df[feat_name] = source_df[feat_name]

        top_auc, dip_auc, top_dec, dip_dec, _, _, _ = run_combo(
            v54_base, v54_names, extra_df, list(extra_df.columns), top_exit_labels, dip_buy_labels, name)
        d_top = top_auc - v54_top
        d_dip = dip_auc - v54_dip
        verdict = "✅✅" if d_top > 0 and d_dip > 0 else "🟡" if d_top > 0 or d_dip > 0 else "❌"
        print("  {:<55s}  {:>9.4f}  {:>+9.4f}  {:>9.4f}  {:>+9.4f}  {}".format(
            name, top_auc, d_top, dip_auc, d_dip, verdict))
        cross_results.append({"name": name, "features": list(extra_df.columns),
                             "top_auc": top_auc, "dip_auc": dip_auc,
                             "delta_top": d_top, "delta_dip": d_dip,
                             "top_decay": top_dec, "dip_decay": dip_dec})

    # ========== 总结 ==========
    print("\n" + "=" * 80)
    print("  【总结】")
    print("=" * 80)

    all_results = d1_results + d2_results + d3_results + cross_results
    # 只保留双场景提升的
    both_positive = [r for r in all_results if r["delta_top"] > 0 and r["delta_dip"] > 0]
    both_positive.sort(key=lambda x: (x["delta_top"] + x["delta_dip"]) / 2, reverse=True)

    print("\n  双场景均提升的组合 ({}个):".format(len(both_positive)))
    for r in both_positive[:10]:
        comp = (r["delta_top"] + r["delta_dip"]) / 2
        print("  综合={:+.4f} {:<45s} TOP {:+.4f} DIP {:+.4f} decay:{:.1%}/{:.1%}".format(
            comp, r["name"], r["delta_top"], r["delta_dip"], r["top_decay"], r["dip_decay"]))

    # 保存结果
    output = {
        "analysis_date": str(pd.Timestamp.now()),
        "v54_baseline": {"top_exit": v54_top, "dip_buy": v54_dip, "top_decay": v54_top_dec, "dip_decay": v54_dip_dec},
        "direction1_results": d1_results,
        "direction2_results": d2_results,
        "direction3_results": d3_results,
        "cross_results": cross_results,
        "best_both_positive": both_positive[:5] if both_positive else [],
    }
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/v55_direction123_result.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("\n  结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
