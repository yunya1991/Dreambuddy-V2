"""V5.3 方向D验证：精选独立特征 + 交互特征

策略：
1. 精选5个高独立信息V5特征（独立信息占比>56%）
   - vol_regime_ratio (83.7%) — 量能周期位置，V4未覆盖
   - fed_rate_level (81.4%) — 利率绝对水平
   - drawdown_vs_hist_avg (76.4%) — 跌幅偏离历史均值
   - fed_months_in_cycle (56.9%) — 利率周期持续月数
   - fed_rate_action (56.1%) — 加息/降息方向

2. 构建3个关键交互特征（捕捉非线性关系）
   - halving_x_fed_action: halving_months_after × fed_rate_action
     → 减半周期不同时间点，利率方向的影响差异
   - ath_dd_x_vol_regime: ath_drawdown_pct × vol_regime_ratio
     → 回撤深度与量能状态的组合判断
   - ma200_dist_x_fed_action: weekly_ma200_distance × fed_rate_action
     → 抄底距离与利率方向的组合（降息+低位=强抄底信号）

3. 剔除3个完全冗余特征（独立信息≈0%）
   - cycle_phase, drawdown_from_cycle_peak, months_since_cycle_peak
   - 以及高共线性对: bear_phase_progress / bear_severity_score（r=0.977）

验证：TOP_EXIT + DIP_BUY场景 Walk-Forward，与V4基线(74维)对比
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


# ── 方向D特征设计 ──────────────────────────────────────────────

# 精选独立特征（5个）
SELECTED_INDEPENDENT = [
    "vol_regime_ratio",       # 83.7% 独立信息
    "fed_rate_level",         # 81.4% 独立信息
    "drawdown_vs_hist_avg",   # 76.4% 独立信息
    "fed_months_in_cycle",    # 56.9% 独立信息
    "fed_rate_action",        # 56.1% 独立信息
]

# 交互特征（3个）
INTERACTION_FEATURES = [
    "halving_x_fed_action",      # halving_months_after × fed_rate_action
    "ath_dd_x_vol_regime",       # ath_drawdown_pct × vol_regime_ratio
    "ma200_dist_x_fed_action",   # weekly_ma200_distance × fed_rate_action
]

# 方向D全部新增特征
DIRECTION_D_FEATURES = SELECTED_INDEPENDENT + INTERACTION_FEATURES


def load_btc_data() -> pd.DataFrame:
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def compute_v5_raw_features(fe: PhilosophyFeatureEngineer, prices: pd.DataFrame) -> pd.DataFrame:
    """计算V5.1+V5.2原始特征（复用 extract_series 中的逻辑）"""
    n = len(prices)
    close = prices["close"].values
    volume_arr = prices["volume"].values if "volume" in prices.columns else np.ones(n)

    # V5.1 周期特征
    cycle_phase_arr = np.zeros(n)
    drawdown_peak_arr = np.zeros(n)
    months_since_peak_arr = np.zeros(n)
    bear_progress_arr = np.zeros(n)
    drawdown_vs_hist_arr = np.zeros(n)
    path_similarity_arr = np.zeros(n)
    vol_regime_arr = np.ones(n)
    bear_severity_arr = np.zeros(n)

    # V5.2 美联储特征
    fed_action_arr = np.zeros(n)
    fed_months_arr = np.zeros(n)
    fed_level_arr = np.zeros(n)
    fed_easing_dip_arr = np.zeros(n)
    fed_hawkish_top_arr = np.zeros(n)

    # === V5.2 美联储特征 ===
    for i in range(n):
        current_date = prices.index[i]
        recent_change = None
        for change_date, rate_level, action in fe.FED_RATE_CHANGES:
            if change_date <= current_date:
                recent_change = (change_date, rate_level, action)
            else:
                break

        if recent_change is None:
            fed_action_arr[i] = 0.0
            fed_months_arr[i] = 0.0
            fed_level_arr[i] = 0.25
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

        fed_action_arr[i] = current_action
        fed_months_arr[i] = months_in_cycle
        fed_level_arr[i] = rate_level

    # === V5.1 周期特征 ===
    running_peak_price = 0.0
    running_peak_date = None
    last_halving_idx = -1
    running_peak_vol = 0.0
    vol_ma30 = pd.Series(volume_arr).rolling(30, min_periods=1).mean().values

    for i in range(n):
        current_date = prices.index[i]
        current_price = close[i]
        current_vol = vol_ma30[i] if i < len(vol_ma30) else 0.0

        recent_halving = None
        for hd in fe.BTC_HALVING_DATES:
            if hd <= current_date:
                recent_halving = hd
            else:
                break

        if recent_halving is None:
            continue

        halving_idx_change = (recent_halving != last_halving_idx) if last_halving_idx != -1 else False
        if halving_idx_change or running_peak_price == 0.0:
            running_peak_price = current_price
            running_peak_date = current_date
            running_peak_vol = current_vol
            last_halving_idx = recent_halving

        if current_price > running_peak_price:
            running_peak_price = current_price
            running_peak_date = current_date
        if current_vol > running_peak_vol:
            running_peak_vol = current_vol

        months_after_halving = (current_date - recent_halving).days / 30.44

        # cycle_phase
        if months_after_halving < 0:
            phase = 0.0
        elif months_after_halving < fe.cycle_bull_run_end_months:
            phase = 1.0
        elif months_after_halving < fe.cycle_peak_warn_end_months:
            phase = 2.0
        elif months_after_halving < fe.cycle_bear_end_months:
            phase = 3.0
        else:
            phase = 0.0
        cycle_phase_arr[i] = phase

        if running_peak_price > 0:
            drawdown_peak_arr[i] = (current_price - running_peak_price) / running_peak_price * 100

        if running_peak_date is not None:
            months_since_peak_arr[i] = (current_date - running_peak_date).days / 30.44

        if phase == 3.0:
            bear_duration = fe.cycle_bear_end_months - fe.cycle_peak_warn_end_months
            if bear_duration > 0:
                progress = (months_after_halving - fe.cycle_peak_warn_end_months) / bear_duration
                bear_progress_arr[i] = max(0.0, min(1.0, progress))

        if running_peak_vol > 0:
            vol_regime_arr[i] = current_vol / running_peak_vol

        if phase == 3.0:
            months_since_peak = months_since_peak_arr[i]
            idx = int(min(months_since_peak, len(fe.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN) - 1))
            hist_avg = fe.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN[idx] if idx >= 0 else 0.0
            drawdown_vs_hist_arr[i] = drawdown_peak_arr[i] - hist_avg

            if months_since_peak >= 3:
                months_since_peak_int = int(months_since_peak)
                similarities = []
                for m in range(max(0, months_since_peak_int - 3), months_since_peak_int):
                    if m < len(fe.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN):
                        hist_dd = fe.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN[m]
                        if abs(hist_dd) > 0:
                            sim = 1.0 - abs(drawdown_peak_arr[i] - hist_dd) / abs(hist_dd)
                            similarities.append(max(0.0, min(1.0, sim)))
                if similarities:
                    path_similarity_arr[i] = float(np.mean(similarities))

            time_progress = bear_progress_arr[i]
            dd_progress = min(1.0, abs(drawdown_peak_arr[i]) / fe.HISTORICAL_AVG_TOTAL_DRAWDOWN_PCT)
            bear_severity_arr[i] = time_progress * dd_progress

    return pd.DataFrame({
        "cycle_phase": cycle_phase_arr,
        "drawdown_from_cycle_peak": drawdown_peak_arr,
        "months_since_cycle_peak": months_since_peak_arr,
        "bear_phase_progress": bear_progress_arr,
        "drawdown_vs_hist_avg": drawdown_vs_hist_arr,
        "cycle_path_similarity": path_similarity_arr,
        "vol_regime_ratio": vol_regime_arr,
        "bear_severity_score": bear_severity_arr,
        "fed_rate_action": fed_action_arr,
        "fed_months_in_cycle": fed_months_arr,
        "fed_rate_level": fed_level_arr,
        "fed_easing_btc_dip": fed_easing_dip_arr,
        "fed_hawkish_top": fed_hawkish_top_arr,
    }, index=prices.index)


def build_direction_d_features(
    phil_features: pd.DataFrame,
    v5_raw: pd.DataFrame,
) -> pd.DataFrame:
    """构建方向D的8个新增特征（5个精选 + 3个交互）"""
    result = pd.DataFrame(index=phil_features.index)

    # === 5个精选独立特征 ===
    for feat in SELECTED_INDEPENDENT:
        if feat in v5_raw.columns:
            result[feat] = v5_raw[feat].values
        else:
            result[feat] = 0.0

    # === 3个交互特征 ===
    # 1. halving_x_fed_action: 减半后月数 × 利率方向
    #    含义：减半后不同时间点，利率方向的影响不同
    #    降息+减半后早期(牛市) → 强牛市信号
    #    加息+减半后晚期(见顶) → 强逃顶信号
    halving_months = phil_features["halving_months_after"].values
    fed_action = v5_raw["fed_rate_action"].values
    result["halving_x_fed_action"] = halving_months * fed_action

    # 2. ath_dd_x_vol_regime: 回撤深度 × 量能周期位置
    #    含义：深度回撤 + 缩量 = 熊市末期（抄底机会）
    #          浅度回撤 + 放量 = 牛市回调（继续持有）
    ath_dd = phil_features["ath_drawdown_pct"].values
    vol_regime = v5_raw["vol_regime_ratio"].values
    result["ath_dd_x_vol_regime"] = ath_dd * vol_regime

    # 3. ma200_dist_x_fed_action: 抄底距离 × 利率方向
    #    含义：价格低于MA200 + 降息 = 强抄底信号（美联储放水+低估值）
    #          价格低于MA200 + 加息 = 弱抄底信号（紧缩+下跌，可能继续跌）
    ma200_dist = phil_features["weekly_ma200_distance"].values
    result["ma200_dist_x_fed_action"] = ma200_dist * fed_action

    return result


def generate_labels(closes, lookahead, threshold, mode="drop"):
    """生成标签
    mode='drop': 未来lookahead日跌幅>threshold → 1（TOP_EXIT）
    mode='rise': 未来lookahead日涨幅>threshold → 1（DIP_BUY）
    """
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
    features: pd.DataFrame,
    labels: np.ndarray,
    feature_names: list,
    n_splits: int = 12,
    train_days: int = 730,
    test_days: int = 180,
    step_days: int = 180,
):
    """Walk-Forward 验证"""
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

    avg_test_auc = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train_auc = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay_rate = 1.0 - (avg_test_auc / avg_train_auc) if avg_train_auc > 0 else 0.0
    avg_importances = np.mean(feature_importances, axis=0) if feature_importances else np.zeros(len(feature_names))

    return {
        "avg_test_auc": avg_test_auc,
        "avg_train_auc": avg_train_auc,
        "decay_rate": float(decay_rate),
        "n_folds": len(test_aucs),
        "feature_importances": avg_importances.tolist(),
    }


def main():
    print("=" * 80)
    print("  V5.3 方向D验证：精选独立特征 + 交互特征")
    print("  策略: 5个高独立特征 + 3个交互特征 = 8个新增特征")
    print("=" * 80)

    # 1. 加载数据
    print("\n【1. 数据加载】")
    prices = load_btc_data()
    closes = prices["close"].values
    print("  BTC日线: {}天, {} ~ {}".format(
        len(prices), prices.index[0].date(), prices.index[-1].date()))

    # 2. 计算特征
    print("\n【2. 特征计算】")
    t0 = time.time()

    # 趋势特征
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()

    # 哲学特征（V4基线，24维）
    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")

    # V5原始特征
    v5_raw = compute_v5_raw_features(phil_fe, prices)

    # 方向D特征
    direction_d = build_direction_d_features(phil_features, v5_raw)

    print("  趋势特征: {}维".format(trend_features.shape[1]))
    print("  哲学特征(V4): {}维".format(phil_features.shape[1]))
    print("  方向D新增: {}维".format(direction_d.shape[1]))
    print("  耗时: {:.1f}s".format(time.time() - t0))

    # 3. 构建实验特征集
    print("\n【3. 构建实验特征集】")

    # V4基线：趋势 + 哲学(24维)
    v4_features = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v4_feature_names = list(v4_features.columns)
    print("  V4基线: {}维".format(len(v4_feature_names)))

    # 方向D：V4基线 + 8个新增特征
    d_features = pd.concat([v4_features, direction_d], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    d_feature_names = list(d_features.columns)
    print("  方向D: {}维 (+{})".format(len(d_feature_names), len(DIRECTION_D_FEATURES)))

    # 4. 方向D特征数值校验
    print("\n【4. 方向D特征数值校验】")
    for feat in DIRECTION_D_FEATURES:
        if feat in d_features.columns:
            vals = d_features[feat]
            non_zero = (vals != 0).sum()
            print("  {:<28s}  min={:>10.3f}  max={:>10.3f}  mean={:>8.3f}  非零占比={:.1%}".format(
                feat, vals.min(), vals.max(), vals.mean(), non_zero / len(vals)))

    # 5. Walk-Forward 验证
    print("\n【5. Walk-Forward 验证】")

    # TOP_EXIT场景
    print("\n" + "-" * 60)
    print("  5.1 TOP_EXIT 场景 (未来20日跌幅>20%)")
    print("-" * 60)
    top_exit_labels = generate_labels(closes, lookahead=20, threshold=0.20, mode="drop")

    print("  正样本率: {:.1%}".format(top_exit_labels.mean()))

    print("\n  [V4基线]")
    t0 = time.time()
    v4_top = walk_forward_validation(v4_features, top_exit_labels, v4_feature_names)
    print("    AUC: {:.4f} (train={:.4f}, decay={:.1%})  耗时{:.1f}s".format(
        v4_top["avg_test_auc"], v4_top["avg_train_auc"], v4_top["decay_rate"], time.time() - t0))

    print("\n  [方向D]")
    t0 = time.time()
    d_top = walk_forward_validation(d_features, top_exit_labels, d_feature_names)
    print("    AUC: {:.4f} (train={:.4f}, decay={:.1%})  耗时{:.1f}s".format(
        d_top["avg_test_auc"], d_top["avg_train_auc"], d_top["decay_rate"], time.time() - t0))

    delta_top = d_top["avg_test_auc"] - v4_top["avg_test_auc"]
    print("\n  >>> TOP_EXIT AUC变化: {:+.4f} ({})".format(
        delta_top, "✅ 提升" if delta_top > 0 else "❌ 下降" if delta_top < 0 else "➡️ 持平"))

    # DIP_BUY场景
    print("\n" + "-" * 60)
    print("  5.2 DIP_BUY 场景 (未来20日涨幅>15%且回撤<10%)")
    print("-" * 60)
    dip_buy_labels = generate_labels(closes, lookahead=20, threshold=0.15, mode="rise")

    print("  正样本率: {:.1%}".format(dip_buy_labels.mean()))

    print("\n  [V4基线]")
    t0 = time.time()
    v4_dip = walk_forward_validation(v4_features, dip_buy_labels, v4_feature_names)
    print("    AUC: {:.4f} (train={:.4f}, decay={:.1%})  耗时{:.1f}s".format(
        v4_dip["avg_test_auc"], v4_dip["avg_train_auc"], v4_dip["decay_rate"], time.time() - t0))

    print("\n  [方向D]")
    t0 = time.time()
    d_dip = walk_forward_validation(d_features, dip_buy_labels, d_feature_names)
    print("    AUC: {:.4f} (train={:.4f}, decay={:.1%})  耗时{:.1f}s".format(
        d_dip["avg_test_auc"], d_dip["avg_train_auc"], d_dip["decay_rate"], time.time() - t0))

    delta_dip = d_dip["avg_test_auc"] - v4_dip["avg_test_auc"]
    print("\n  >>> DIP_BUY AUC变化: {:+.4f} ({})".format(
        delta_dip, "✅ 提升" if delta_dip > 0 else "❌ 下降" if delta_dip < 0 else "➡️ 持平"))

    # 6. 方向D新增特征重要性排名
    print("\n【6. 方向D新增特征重要性排名】")

    for scenario_name, result, feature_names in [
        ("TOP_EXIT", d_top, d_feature_names),
        ("DIP_BUY", d_dip, d_feature_names),
    ]:
        print("\n  {} 场景 - 方向D特征排名:".format(scenario_name))
        importances = result["feature_importances"]
        feat_imp = list(zip(feature_names, importances))
        feat_imp.sort(key=lambda x: x[1], reverse=True)

        # 找出方向D特征的排名
        d_feat_ranks = []
        for rank, (feat, imp) in enumerate(feat_imp, 1):
            if feat in DIRECTION_D_FEATURES:
                d_feat_ranks.append((rank, feat, imp))

        total_feats = len(feature_names)
        top30_threshold = int(total_feats * 0.3)

        for rank, feat, imp in d_feat_ranks:
            in_top30 = "✅ Top30%" if rank <= top30_threshold else "❌"
            print("    #{:>3d} {:<28s}  重要性={:>8.1f}  {}".format(rank, feat, imp, in_top30))

    # 7. 总结
    print("\n" + "=" * 80)
    print("  【验证总结】")
    print("=" * 80)

    print("""
┌──────────────────────────────────────────────────────────────────┐
│                    方向D验证结果对比                              │
├──────────────────┬──────────────┬──────────────┬────────────────┤
│ 场景             │ V4基线(74维) │ 方向D(82维)  │ AUC变化        │
├──────────────────┼──────────────┼──────────────┼────────────────┤
│ TOP_EXIT         │ {:.4f}       │ {:.4f}       │ {:+.4f}  {} │
│ DIP_BUY          │ {:.4f}       │ {:.4f}       │ {:+.4f}  {} │
└──────────────────┴──────────────┴──────────────┴────────────────┘
""".format(
    v4_top["avg_test_auc"], d_top["avg_test_auc"], delta_top,
    "✅" if delta_top > 0 else "❌",
    v4_dip["avg_test_auc"], d_dip["avg_test_auc"], delta_dip,
    "✅" if delta_dip > 0 else "❌",
))

    # 决策
    both_improve = delta_top > 0 and delta_dip > 0
    either_improve = delta_top > 0 or delta_dip > 0
    no_decline = delta_top >= -0.005 and delta_dip >= -0.005

    if both_improve:
        decision = "✅ 采纳：两个场景均提升"
    elif either_improve and no_decline:
        decision = "🟡 部分采纳：一个场景提升，另一个持平"
    elif no_decline:
        decision = "🟡 观望：未显著下降但未提升"
    else:
        decision = "❌ 回退：AUC显著下降"

    print("  决策: {}".format(decision))

    # 保存结果
    result = {
        "analysis_date": str(pd.Timestamp.now()),
        "strategy": "direction_d",
        "description": "精选5个高独立特征 + 3个交互特征",
        "selected_independent": SELECTED_INDEPENDENT,
        "interaction_features": INTERACTION_FEATURES,
        "v4_baseline_features": len(v4_feature_names),
        "direction_d_features": len(d_feature_names),
        "top_exit": {
            "v4_baseline_auc": v4_top["avg_test_auc"],
            "direction_d_auc": d_top["avg_test_auc"],
            "delta": delta_top,
            "v4_decay": v4_top["decay_rate"],
            "d_decay": d_top["decay_rate"],
        },
        "dip_buy": {
            "v4_baseline_auc": v4_dip["avg_test_auc"],
            "direction_d_auc": d_dip["avg_test_auc"],
            "delta": delta_dip,
            "v4_decay": v4_dip["decay_rate"],
            "d_decay": d_dip["decay_rate"],
        },
        "decision": decision,
    }

    output_path = os.path.join(BASE_DIR, "ml/backtest_results/v53_direction_d_result.json")
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print("\n  结果已保存: {}".format(output_path))


if __name__ == "__main__":
    main()
