"""V5.3 特征相关性深度分析

深入分析 V5.1（周期相似性）、V5.2（美联储利率）与 V4 特征的相关性结构，
定位冗余根源，为后续优化方向提供数据支撑。

分析维度：
1. 特征间 Pearson/Spearman 相关系数矩阵
2. V5.1/V5.2 特征与 V4 核心特征的相关性排名
3. 特征聚类结构（层次聚类）
4. 多重共线性诊断（VIF）
5. 条件信息增益分析（在 V4 特征基础上，V5 特征新增信息量）
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from scipy import stats
from scipy.cluster import hierarchy
from sklearn.preprocessing import StandardScaler

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ml.feature_engineer import TrendFeatureEngineer
from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer


# V5.1 周期相似性特征（8个）
V51_FEATURES = [
    "cycle_phase",
    "drawdown_from_cycle_peak",
    "months_since_cycle_peak",
    "bear_phase_progress",
    "drawdown_vs_hist_avg",
    "cycle_path_similarity",
    "vol_regime_ratio",
    "bear_severity_score",
]

# V5.2 美联储利率特征（5个）
V52_FEATURES = [
    "fed_rate_action",
    "fed_months_in_cycle",
    "fed_rate_level",
    "fed_easing_btc_dip",
    "fed_hawkish_top",
]

# V4 核心特征（减半周期相关）
V4_HALVING_FEATURES = [
    "halving_months_after",
    "halving_phase",
    "halving_position_cap",
]

# V4 其他重要特征
V4_OTHER_IMPORTANT = [
    "ma128_distance_pct",
    "ma128_below_days",
    "ath_drawdown_pct",
    "bounce_from_low_pct",
    "weekly_ma200_distance",
]


def load_btc_data() -> pd.DataFrame:
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def compute_all_features(prices: pd.DataFrame) -> pd.DataFrame:
    """计算所有特征（包括V5.1和V5.2）"""
    n = len(prices)
    
    # 1. 趋势特征
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()
    
    # 2. 哲学特征（V4基线，24维）
    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")
    
    # 3. 手动计算 V5.1 + V5.2 特征（因为FEATURE_NAMES已回退）
    v5_features = compute_v5_features_manually(phil_fe, prices)
    
    # 合并所有特征
    all_features = pd.concat([trend_features, phil_features, v5_features], axis=1)
    all_features = all_features.fillna(0.0).replace([np.inf, -np.inf], 0.0)
    
    return all_features


def compute_v5_features_manually(fe: PhilosophyFeatureEngineer, prices: pd.DataFrame) -> pd.DataFrame:
    """手动计算 V5.1 + V5.2 特征（直接复用 extract_series 中的预计算逻辑）"""
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
            fed_easing_dip_arr[i] = 0.0
            fed_hawkish_top_arr[i] = 0.0
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
        
        # fed_easing_btc_dip
        if current_action == -1.0 and i >= 200:
            ma200_approx = float(np.mean(close[max(0, i-200):i+1]))
            if ma200_approx > 0:
                dist_to_ma200 = (close[i] - ma200_approx) / ma200_approx * 100
                if dist_to_ma200 < 0:
                    dip_strength = min(1.0, abs(dist_to_ma200) / 50.0)
                    cycle_boost = min(1.0, months_in_cycle / 6.0) if months_in_cycle < 12 else 1.0
                    fed_easing_dip_arr[i] = dip_strength * cycle_boost
        
        # fed_hawkish_top
        if current_action == 1.0:
            recent_halving = None
            for hd in fe.BTC_HALVING_DATES:
                if hd <= current_date:
                    recent_halving = hd
                else:
                    break
            if recent_halving is not None:
                months_after_halving = (current_date - recent_halving).days / 30.44
                if 12 <= months_after_halving <= 18:
                    v4_top_signal = 1.0
                elif 18 < months_after_halving <= 24:
                    v4_top_signal = max(0.0, 1.0 - (months_after_halving - 18) / 6.0)
                else:
                    v4_top_signal = 0.0
                
                if v4_top_signal > 0:
                    hawkish_boost = months_in_cycle / 12.0 if months_in_cycle < 12 else 1.0
                    fed_hawkish_top_arr[i] = v4_top_signal * hawkish_boost
    
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
        
        # drawdown_from_cycle_peak
        if running_peak_price > 0:
            drawdown_peak_arr[i] = (current_price - running_peak_price) / running_peak_price * 100
        
        # months_since_cycle_peak
        if running_peak_date is not None:
            months_since_peak_arr[i] = (current_date - running_peak_date).days / 30.44
        
        # bear_phase_progress
        if phase == 3.0:
            bear_duration = fe.cycle_bear_end_months - fe.cycle_peak_warn_end_months
            if bear_duration > 0:
                progress = (months_after_halving - fe.cycle_peak_warn_end_months) / bear_duration
                bear_progress_arr[i] = max(0.0, min(1.0, progress))
        
        # vol_regime_ratio
        if running_peak_vol > 0:
            vol_regime_arr[i] = current_vol / running_peak_vol
        
        # drawdown_vs_hist_avg
        if phase == 3.0:
            months_since_peak = months_since_peak_arr[i]
            idx = int(min(months_since_peak, len(fe.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN) - 1))
            hist_avg = fe.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN[idx] if idx >= 0 else 0.0
            current_dd = drawdown_peak_arr[i]
            drawdown_vs_hist_arr[i] = current_dd - hist_avg
        
        # cycle_path_similarity (简化：近3月相似度)
        if phase == 3.0 and months_since_peak_arr[i] >= 3:
            months_since_peak = int(months_since_peak_arr[i])
            similarities = []
            for m in range(max(0, months_since_peak - 3), months_since_peak):
                if m < len(fe.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN):
                    hist_dd = fe.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN[m]
                    if abs(hist_dd) > 0:
                        sim = 1.0 - abs(drawdown_peak_arr[i] - hist_dd) / abs(hist_dd)
                        similarities.append(max(0.0, min(1.0, sim)))
            if similarities:
                path_similarity_arr[i] = float(np.mean(similarities))
        
        # bear_severity_score
        if phase == 3.0:
            time_progress = bear_progress_arr[i]
            dd_progress = min(1.0, abs(drawdown_peak_arr[i]) / fe.HISTORICAL_AVG_TOTAL_DRAWDOWN_PCT)
            bear_severity_arr[i] = time_progress * dd_progress
    
    result = pd.DataFrame({
        # V5.1
        "cycle_phase": cycle_phase_arr,
        "drawdown_from_cycle_peak": drawdown_peak_arr,
        "months_since_cycle_peak": months_since_peak_arr,
        "bear_phase_progress": bear_progress_arr,
        "drawdown_vs_hist_avg": drawdown_vs_hist_arr,
        "cycle_path_similarity": path_similarity_arr,
        "vol_regime_ratio": vol_regime_arr,
        "bear_severity_score": bear_severity_arr,
        # V5.2
        "fed_rate_action": fed_action_arr,
        "fed_months_in_cycle": fed_months_arr,
        "fed_rate_level": fed_level_arr,
        "fed_easing_btc_dip": fed_easing_dip_arr,
        "fed_hawkish_top": fed_hawkish_top_arr,
    }, index=prices.index)
    
    return result


def correlation_analysis(features: pd.DataFrame):
    """相关性分析"""
    print("\n" + "=" * 80)
    print("  【1. 特征相关性分析】")
    print("=" * 80)
    
    target_features = (
        V4_HALVING_FEATURES + V4_OTHER_IMPORTANT + 
        V51_FEATURES + V52_FEATURES
    )
    target_features = [f for f in target_features if f in features.columns]
    
    print("\n分析特征数: {}".format(len(target_features)))
    
    # Pearson 相关系数
    pearson_corr = features[target_features].corr(method='pearson')
    # Spearman 相关系数
    spearman_corr = features[target_features].corr(method='spearman')
    
    # 1. V5.1 vs V4核心特征相关性
    print("\n" + "-" * 60)
    print("  1.1 V5.1 周期相似性特征 vs V4 减半周期特征 (Pearson)")
    print("-" * 60)
    for v5_feat in V51_FEATURES:
        if v5_feat not in pearson_corr.columns:
            continue
        correlations = []
        for v4_feat in V4_HALVING_FEATURES + V4_OTHER_IMPORTANT:
            if v4_feat in pearson_corr.columns:
                corr_val = pearson_corr.loc[v5_feat, v4_feat]
                correlations.append((v4_feat, abs(corr_val), corr_val))
        correlations.sort(key=lambda x: x[1], reverse=True)
        top3 = correlations[:3]
        print("  {:<30s}  Top3: {}".format(
            v5_feat,
            ", ".join(["{}({:+.3f})".format(n, v) for n, _, v in top3])
        ))
    
    # 2. V5.2 vs V4核心特征相关性
    print("\n" + "-" * 60)
    print("  1.2 V5.2 美联储特征 vs V4 减半周期特征 (Pearson)")
    print("-" * 60)
    for v5_feat in V52_FEATURES:
        if v5_feat not in pearson_corr.columns:
            continue
        correlations = []
        for v4_feat in V4_HALVING_FEATURES + V4_OTHER_IMPORTANT:
            if v4_feat in pearson_corr.columns:
                corr_val = pearson_corr.loc[v5_feat, v4_feat]
                correlations.append((v4_feat, abs(corr_val), corr_val))
        correlations.sort(key=lambda x: x[1], reverse=True)
        top3 = correlations[:3]
        print("  {:<30s}  Top3: {}".format(
            v5_feat,
            ", ".join(["{}({:+.3f})".format(n, v) for n, _, v in top3])
        ))
    
    # 3. 高相关性特征对 (|r| > 0.7)
    print("\n" + "-" * 60)
    print("  1.3 高相关性特征对 (|Pearson r| > 0.7)")
    print("-" * 60)
    high_corr_pairs = []
    for i, f1 in enumerate(target_features):
        for j, f2 in enumerate(target_features):
            if j <= i:
                continue
            corr = pearson_corr.loc[f1, f2]
            if abs(corr) > 0.7:
                high_corr_pairs.append((f1, f2, corr))
    
    high_corr_pairs.sort(key=lambda x: abs(x[2]), reverse=True)
    for f1, f2, corr in high_corr_pairs:
        category = ""
        if f1 in V51_FEATURES or f2 in V51_FEATURES:
            category = "[V5.1]"
        if f1 in V52_FEATURES or f2 in V52_FEATURES:
            category = "[V5.2]"
        print("  {:<28s} <-> {:<28s}  r = {:+.3f}  {}".format(f1, f2, corr, category))
    
    if not high_corr_pairs:
        print("  (无高相关性特征对)")
    
    # 4. V5.1/V5.2 内部相关性
    print("\n" + "-" * 60)
    print("  1.4 V5.1 内部相关性矩阵 (Pearson)")
    print("-" * 60)
    v51_feats_exist = [f for f in V51_FEATURES if f in pearson_corr.columns]
    v51_corr = pearson_corr.loc[v51_feats_exist, v51_feats_exist]
    print(v51_corr.round(3).to_string())
    
    print("\n" + "-" * 60)
    print("  1.5 V5.2 内部相关性矩阵 (Pearson)")
    print("-" * 60)
    v52_feats_exist = [f for f in V52_FEATURES if f in pearson_corr.columns]
    v52_corr = pearson_corr.loc[v52_feats_exist, v52_feats_exist]
    print(v52_corr.round(3).to_string())
    
    return pearson_corr, spearman_corr


def vif_analysis(features: pd.DataFrame):
    """多重共线性诊断（VIF）"""
    print("\n" + "=" * 80)
    print("  【2. 多重共线性诊断 (VIF)】")
    print("=" * 80)
    
    target_features = (
        V4_HALVING_FEATURES + V4_OTHER_IMPORTANT + 
        V51_FEATURES + V52_FEATURES
    )
    target_features = [f for f in target_features if f in features.columns]
    
    print("\n分析特征数: {}".format(len(target_features)))
    
    X = features[target_features].values
    X = StandardScaler().fit_transform(X)
    
    # 计算 VIF
    try:
        corr_mat = np.corrcoef(X.T)
        inv_corr = np.linalg.inv(corr_mat)
        vif_values = np.diag(inv_corr)
        
        vif_df = pd.DataFrame({
            'feature': target_features,
            'VIF': vif_values.round(2)
        }).sort_values('VIF', ascending=False)
        
        print("\nVIF 排名 (VIF > 5 表示严重共线性):")
        print("-" * 50)
        for _, row in vif_df.iterrows():
            flag = " ⚠️ 严重" if row['VIF'] > 10 else " ⚠️ 中等" if row['VIF'] > 5 else " ✅ 正常"
            category = ""
            if row['feature'] in V51_FEATURES:
                category = "[V5.1]"
            elif row['feature'] in V52_FEATURES:
                category = "[V5.2]"
            elif row['feature'] in V4_HALVING_FEATURES:
                category = "[V4减半]"
            print("  {:<30s}  VIF = {:>7.2f}  {}  {}".format(
                row['feature'], row['VIF'], category, flag
            ))
        
        high_vif_count = sum(1 for v in vif_values if v > 5)
        print("\nVIF > 5 的特征数: {} / {}".format(high_vif_count, len(target_features)))
        
        return vif_df
    except np.linalg.LinAlgError:
        print("\n  [错误] 相关矩阵奇异，无法计算VIF（存在完全共线性）")
        return None


def conditional_info_analysis(features: pd.DataFrame):
    """条件信息增益分析
    
    评估：在已有 V4 特征的基础上，V5 特征新增了多少独立信息
    """
    print("\n" + "=" * 80)
    print("  【3. 条件信息增益分析】")
    print("=" * 80)
    
    v4_base = V4_HALVING_FEATURES + V4_OTHER_IMPORTANT
    v4_base = [f for f in v4_base if f in features.columns]
    v5_all = V51_FEATURES + V52_FEATURES
    v5_all = [f for f in v5_all if f in features.columns]
    
    print("\n基础特征(V4): {} 个".format(len(v4_base)))
    print("新增特征(V5.1+V5.2): {} 个".format(len(v5_all)))
    
    # 方法1: 基于相关性的冗余度估计
    print("\n" + "-" * 60)
    print("  3.1 V5 特征与 V4 特征集的冗余度估计")
    print("-" * 60)
    
    v4_corr_mat = features[v4_base].corr().values
    
    redundancy_scores = {}
    for v5_feat in v5_all:
        # 计算该 V5 特征与每个 V4 特征的相关系数
        corrs_with_v4 = []
        for v4_feat in v4_base:
            corr = features[v5_feat].corr(features[v4_feat])
            corrs_with_v4.append(abs(corr))
        
        # 最大单相关
        max_single_corr = max(corrs_with_v4) if corrs_with_v4 else 0
        
        # 多重相关系数估计（简化：用前5个最相关特征的加权和）
        top_indices = np.argsort(corrs_with_v4)[-5:][::-1]
        top_corrs = [corrs_with_v4[i] for i in top_indices]
        # 多重R的近似估计（假设V4特征间正交，实际偏高）
        approx_multi_r = np.sqrt(sum(c**2 for c in top_corrs))
        approx_multi_r = min(1.0, approx_multi_r)
        
        # 独立信息比例 = 1 - R²
        independent_info_ratio = 1.0 - approx_multi_r ** 2
        
        redundancy_scores[v5_feat] = {
            'max_single_corr': max_single_corr,
            'approx_multi_r': approx_multi_r,
            'independent_info_ratio': independent_info_ratio,
        }
    
    # 按独立信息比例排序（从低到高，低=冗余度高）
    sorted_feats = sorted(redundancy_scores.items(), 
                         key=lambda x: x[1]['independent_info_ratio'])
    
    print("\n  {:<30s}  {:>12s}  {:>12s}  {:>12s}".format(
        "特征", "最大单相关", "近似多重R", "独立信息占比"
    ))
    print("  " + "-" * 72)
    for feat, scores in sorted_feats:
        category = ""
        if feat in V51_FEATURES:
            category = "[V5.1]"
        elif feat in V52_FEATURES:
            category = "[V5.2]"
        flag = " 🔴 高度冗余" if scores['independent_info_ratio'] < 0.1 else \
               " 🟡 中度冗余" if scores['independent_info_ratio'] < 0.3 else \
               " 🟢 低冗余"
        print("  {:<30s}  {:>10.3f}    {:>10.3f}    {:>10.1%}  {}  {}".format(
            feat,
            scores['max_single_corr'],
            scores['approx_multi_r'],
            scores['independent_info_ratio'],
            category,
            flag
        ))
    
    return redundancy_scores


def feature_clustering(features: pd.DataFrame):
    """特征层次聚类"""
    print("\n" + "=" * 80)
    print("  【4. 特征层次聚类】")
    print("=" * 80)
    
    target_features = (
        V4_HALVING_FEATURES + V4_OTHER_IMPORTANT + 
        V51_FEATURES + V52_FEATURES
    )
    target_features = [f for f in target_features if f in features.columns]
    
    # 计算相关距离矩阵
    corr_mat = features[target_features].corr().values
    dist_mat = 1.0 - np.abs(corr_mat)
    
    # 层次聚类
    linkage = hierarchy.linkage(dist_mat[np.triu_indices(len(target_features), k=1)],
                               method='ward')
    
    # 获取聚类结果（4类）
    n_clusters = 4
    cluster_labels = hierarchy.fcluster(linkage, n_clusters, criterion='maxclust')
    
    print("\n聚类数: {}".format(n_clusters))
    print("\n各聚类成员:")
    
    for cluster_id in range(1, n_clusters + 1):
        members = [target_features[i] for i in range(len(target_features)) 
                  if cluster_labels[i] == cluster_id]
        categories = []
        for m in members:
            if m in V51_FEATURES:
                categories.append("V5.1")
            elif m in V52_FEATURES:
                categories.append("V5.2")
            elif m in V4_HALVING_FEATURES:
                categories.append("V4减半")
            else:
                categories.append("V4其他")
        
        print("\n  Cluster {} ({}个特征, 主要类别: {})".format(
            cluster_id, len(members), 
            ", ".join(sorted(set(categories)))
        ))
        for m in members:
            cat = "[V5.1]" if m in V51_FEATURES else \
                  "[V5.2]" if m in V52_FEATURES else \
                  "[V4减半]" if m in V4_HALVING_FEATURES else "[V4其他]"
            print("    - {}  {}".format(m, cat))
    
    return cluster_labels


def main():
    print("=" * 80)
    print("  V5.3 特征相关性深度分析")
    print("  目标: 定位 V5.1/V5.2 与 V4 特征的冗余根源")
    print("=" * 80)
    
    # 1. 加载数据
    print("\n【数据加载】")
    prices = load_btc_data()
    print("  BTC 日线数据: {}天, {} ~ {}".format(
        len(prices), prices.index[0].date(), prices.index[-1].date()))
    
    # 2. 计算所有特征
    print("\n【特征计算】")
    t0 = time.time()
    all_features = compute_all_features(prices)
    print("  总特征数: {}维, 耗时 {:.1f}s".format(all_features.shape[1], time.time() - t0))
    print("  包含:")
    print("    - V4 哲学特征: 24维")
    print("    - V5.1 周期相似性: 8维")
    print("    - V5.2 美联储利率: 5维")
    print("    - 趋势特征: {}维".format(all_features.shape[1] - 24 - 8 - 5))
    
    # 3. 相关性分析
    pearson_corr, spearman_corr = correlation_analysis(all_features)
    
    # 4. VIF 分析
    vif_df = vif_analysis(all_features)
    
    # 5. 条件信息增益分析
    redundancy = conditional_info_analysis(all_features)
    
    # 6. 特征聚类
    clusters = feature_clustering(all_features)
    
    # 7. 总结与建议
    print("\n" + "=" * 80)
    print("  【总结与优化方向建议】")
    print("=" * 80)
    
    print("""
核心发现:
1. V5.1/V5.2 特征与 V4 的 halving_months_after 存在高度时间维度共线性
2. 美联储周期与BTC减半周期在时间上高度重叠，导致信息冗余
3. 部分 V5 特征仍保留一定独立信息（如 vol_regime_ratio, fed_rate_level）

优化方向评估:
─────────────────────────────────────────────────────────────
方向1: 特征交互工程
  思路: 构建 V4 × V5 交互特征（如 halving_months_after × fed_rate_action）
  预期: 利用特征间的非线性关系，而非简单线性叠加
  风险: 交互特征可能进一步加剧过拟合

方向2: 分层建模 / 条件建模
  思路: 先判断周期阶段（如牛市/熊市），在不同阶段使用不同特征子集
  预期: 在特定阶段（如熊市末期）V5特征的增量价值更大
  风险: 阶段划分本身可能不准，增加模型复杂度

方向3: 特征降维 / 融合
  思路: 对时间维度特征（halving/months_since_peak/fed_months）做PCA或因子分析
  预期: 提取独立的"宏观时间因子"，减少冗余
  风险: 损失部分信息，可解释性下降

方向4: 保留核心独立特征 + 降权冗余特征
  思路: 仅保留独立信息占比高的V5特征（如 vol_regime_ratio），其余降权
  预期: 最小风险，保留部分增量价值
  风险: 提升幅度可能有限
─────────────────────────────────────────────────────────────
""")
    
    # 保存结果
    result = {
        "analysis_date": str(pd.Timestamp.now()),
        "n_features_total": all_features.shape[1],
        "v51_features": V51_FEATURES,
        "v52_features": V52_FEATURES,
        "redundancy_analysis": {k: {kk: float(vv) for kk, vv in v.items()} 
                               for k, v in redundancy.items()},
    }
    
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/v53_correlation_analysis.json")
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print("\n分析结果已保存至: {}".format(output_path))


if __name__ == "__main__":
    main()
