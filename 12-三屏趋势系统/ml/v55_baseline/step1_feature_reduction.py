"""Step 1: 特征精简验证

目标：移除WF验证重要性为0的特征，减少特征维度

保守策略：移除以下3个冗余特征（被标记为ml_redundant=True）
- dip_buy_level: 从weekly_ma200_distance派生，LightGBM偏好连续值
- dip_buy_position_ratio: 与dip_buy_level信息重复
- left_side_buy_signal: 三级派生链末端，信息量极低

预期：28维 → 25维

验证方式：Walk-Forward (12折，训练730天，测试180天)
对比指标：TOP_EXIT AUC, DIP_BUY AUC, 过拟合衰减率

用法：
    cd 12-三屏趋势系统
    python ml/v55_baseline/step1_feature_reduction.py
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, accuracy_score

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from ml.feature_engineer import TrendFeatureEngineer
from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer


def load_btc_data() -> pd.DataFrame:
    """加载BTC日线数据"""
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def generate_labels(closes, lookahead, threshold, mode="drop"):
    """生成标签
    
    Args:
        closes: 收盘价序列
        lookahead: 前瞻天数
        threshold: 阈值
        mode: "drop"=跌幅>"rise"=涨幅
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


def walk_forward_validation(features, labels, feature_names,
                             n_splits=12, train_days=730, test_days=180, step_days=180):
    """Walk-Forward验证
    
    Args:
        features: 特征DataFrame
        labels: 标签数组
        feature_names: 特征名列表
        n_splits: 折数
        train_days: 训练天数
        test_days: 测试天数
        step_days: 步进天数
    
    Returns:
        avg_test_auc: 平均测试AUC
        avg_train_auc: 平均训练AUC
        avg_decay: 平均衰减率
        avg_importance: 平均特征重要性
    """
    n = len(features)
    feature_importances = []
    train_aucs, test_aucs = [], []
    
    # 计算折的划分
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
        
        # 检查标签多样性
        if y_train.sum() < 5 or y_test.sum() < 2:
            continue
        
        # 训练模型
        model = lgb.LGBMClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1,
        )
        model.fit(X_train, y_train)
        
        # 预测
        train_pred = model.predict_proba(X_train)[:, 1]
        test_pred = model.predict_proba(X_test)[:, 1]
        
        # 计算AUC
        if len(set(y_train)) > 1:
            train_aucs.append(roc_auc_score(y_train, train_pred))
        if len(set(y_test)) > 1:
            test_aucs.append(roc_auc_score(y_test, test_pred))
            feature_importances.append(model.feature_importances_)
    
    # 计算平均值
    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0
    avg_imp = np.mean(feature_importances, axis=0) if feature_importances else np.zeros(len(feature_names))
    
    return avg_test, avg_train, float(decay), avg_imp


def main():
    print("=" * 80)
    print("  Step 1: 特征精简验证")
    print("  目标：28维 → 25维，移除WF重要性为0的3个冗余特征")
    print("=" * 80)
    
    # 加载数据
    prices = load_btc_data()
    closes = prices["close"].values
    print(f"\n  BTC日线: {len(prices)}天")
    
    # 计算特征
    t0 = time.time()
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()
    
    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")
    
    print(f"  趋势特征: {trend_features.shape[1]}维")
    print(f"  哲学特征: {phil_features.shape[1]}维")
    print(f"  计算耗时: {time.time() - t0:.1f}s")
    
    # ========== V5.5基线（28维）==========
    print("\n" + "=" * 80)
    print("  【V5.5基线】28维特征")
    print("=" * 80)
    
    v55_base = pd.concat([trend_features, phil_features], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    v55_names = list(v55_base.columns)
    
    # 标签
    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")
    
    # V5.5基线验证
    v55_top, v55_top_tr, v55_top_dec, v55_top_imp = walk_forward_validation(v55_base, top_exit_labels, v55_names)
    v55_dip, v55_dip_tr, v55_dip_dec, v55_dip_imp = walk_forward_validation(v55_base, dip_buy_labels, v55_names)
    
    print(f"\n  TOP_EXIT: 测试AUC={v55_top:.4f}, 训练AUC={v55_top_tr:.4f}, 衰减={v55_top_dec:.1%}")
    print(f"  DIP_BUY:  测试AUC={v55_dip:.4f}, 训练AUC={v55_dip_tr:.4f}, 衰减={v55_dip_dec:.1%}")
    
    # ========== V5.6特征精简（25维）==========
    print("\n" + "=" * 80)
    print("  【V5.6特征精简】移除3个冗余特征")
    print("=" * 80)
    
    # 要移除的特征
    redundant_features = [
        "dip_buy_level",         # 从weekly_ma200_distance派生，WF重要性=0
        "dip_buy_position_ratio",  # 与dip_buy_level信息重复
        "left_side_buy_signal",    # 三级派生链末端，信息量极低
    ]
    
    # 检查特征是否存在
    missing = [f for f in redundant_features if f not in v55_names]
    if missing:
        print(f"  ⚠️ 警告：特征不存在: {missing}")
        redundant_features = [f for f in redundant_features if f in v55_names]
    
    print(f"\n  移除特征: {redundant_features}")
    
    # 创建精简后的特征集
    v56_names = [f for f in v55_names if f not in redundant_features]
    v56_base = v55_base[v56_names].copy()
    
    print(f"  特征维度: {len(v55_names)} → {len(v56_names)}")
    
    # V5.6验证
    v56_top, v56_top_tr, v56_top_dec, v56_top_imp = walk_forward_validation(v56_base, top_exit_labels, v56_names)
    v56_dip, v56_dip_tr, v56_dip_dec, v56_dip_imp = walk_forward_validation(v56_base, dip_buy_labels, v56_names)
    
    print(f"\n  TOP_EXIT: 测试AUC={v56_top:.4f}, 训练AUC={v56_top_tr:.4f}, 衰减={v56_top_dec:.1%}")
    print(f"  DIP_BUY:  测试AUC={v56_dip:.4f}, 训练AUC={v56_dip_tr:.4f}, 衰减={v56_dip_dec:.1%}")
    
    # ========== 对比分析 ==========
    print("\n" + "=" * 80)
    print("  【对比分析】")
    print("=" * 80)
    
    delta_top = v56_top - v55_top
    delta_dip = v56_dip - v55_dip
    delta_top_dec = v56_top_dec - v55_top_dec
    delta_dip_dec = v56_dip_dec - v55_dip_dec
    
    print(f"\n  {'指标':<20s} {'V5.5基线':>12s} {'V5.6精简':>12s} {'变化':>12s}")
    print("  " + "-" * 60)
    print(f"  {'TOP_EXIT 测试AUC':<20s} {v55_top:>12.4f} {v56_top:>12.4f} {delta_top:>+12.4f}")
    print(f"  {'TOP_EXIT 训练AUC':<20s} {v55_top_tr:>12.4f} {v56_top_tr:>12.4f} {v56_top_tr-v55_top_tr:>+12.4f}")
    print(f"  {'TOP_EXIT 衰减率':<20s} {v55_top_dec:>12.1%} {v56_top_dec:>12.1%} {delta_top_dec:>+12.1%}")
    print()
    print(f"  {'DIP_BUY 测试AUC':<20s} {v55_dip:>12.4f} {v56_dip:>12.4f} {delta_dip:>+12.4f}")
    print(f"  {'DIP_BUY 训练AUC':<20s} {v55_dip_tr:>12.4f} {v56_dip_tr:>12.4f} {v56_dip_tr-v55_dip_tr:>+12.4f}")
    print(f"  {'DIP_BUY 衰减率':<20s} {v55_dip_dec:>12.1%} {v56_dip_dec:>12.1%} {delta_dip_dec:>+12.1%}")
    
    # 判断结果
    print("\n" + "=" * 80)
    if delta_top > 0 and delta_dip > 0:
        print("  ✅ 结论：特征精简有效，双场景AUC均提升")
        print("  建议：进入Step 2（训练窗口优化）")
    elif delta_top > 0 or delta_dip > 0:
        print("  🟡 结论：特征精简部分有效，单场景AUC提升")
        print("  建议：评估是否继续精简或调整特征选择策略")
    else:
        print("  ❌ 结论：特征精简无效，双场景AUC均下降")
        print("  建议：重新评估特征选择策略，考虑更激进的特征精简")
    print("=" * 80)
    
    # 特征重要性对比
    print("\n  【TOP_EXIT Top-10 特征重要性对比】")
    v55_top_imp_df = pd.DataFrame({'feature': v55_names, 'importance': v55_top_imp}).sort_values('importance', ascending=False)
    v56_top_imp_df = pd.DataFrame({'feature': v56_names, 'importance': v56_top_imp}).sort_values('importance', ascending=False)
    
    print(f"  {'排名':<6s} {'V5.5特征':<30s} {'重要性':>10s} {'V5.6特征':<30s} {'重要性':>10s}")
    for i in range(min(10, len(v56_top_imp_df))):
        v55_row = v55_top_imp_df.iloc[i] if i < len(v55_top_imp_df) else None
        v56_row = v56_top_imp_df.iloc[i] if i < len(v56_top_imp_df) else None
        v55_name = v55_row['feature'] if v55_row is not None else ""
        v55_imp = v55_row['importance'] if v55_row is not None else 0
        v56_name = v56_row['feature'] if v56_row is not None else ""
        v56_imp = v56_row['importance'] if v56_row is not None else 0
        print(f"  {i+1:<6d} {v55_name:<30s} {v55_imp:>10.1f} {v56_name:<30s} {v56_imp:>10.1f}")
    
    # 保存结果
    output = {
        "step": "step1_feature_reduction",
        "analysis_date": str(pd.Timestamp.now()),
        "v55_baseline": {
            "feature_count": len(v55_names),
            "top_exit": {"test_auc": v55_top, "train_auc": v55_top_tr, "decay": v55_top_dec},
            "dip_buy": {"test_auc": v55_dip, "train_auc": v55_dip_tr, "decay": v55_dip_dec},
        },
        "v56_reduced": {
            "feature_count": len(v56_names),
            "removed_features": redundant_features,
            "top_exit": {"test_auc": v56_top, "train_auc": v56_top_tr, "decay": v56_top_dec},
            "dip_buy": {"test_auc": v56_dip, "train_auc": v56_dip_tr, "decay": v56_dip_dec},
        },
        "comparison": {
            "delta_top_exit": delta_top,
            "delta_dip_buy": delta_dip,
            "delta_top_decay": delta_top_dec,
            "delta_dip_decay": delta_dip_dec,
        },
        "conclusion": "success" if delta_top > 0 and delta_dip > 0 else "partial" if delta_top > 0 or delta_dip > 0 else "failed",
    }
    
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/step1_feature_reduction.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存: {output_path}")
    
    return output


if __name__ == "__main__":
    main()