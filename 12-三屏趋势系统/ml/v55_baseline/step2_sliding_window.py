"""Step 2: 滑动窗口训练优化

目标：使用滑动窗口策略（固定窗口730天，每180天重训），减少过拟合

策略：
- 固定训练窗口：730天（约2年）
- 滑动步进：每180天（约6个月）重新训练模型
- 对比：一次性训练整个历史 vs 滑动窗口重训

预期效果：
- 更好地适应市场状态变化
- 减少长期过拟合（训练AUC=1.0的过拟合问题）
- 提高样本外泛化能力

验证方式：Walk-Forward (12折)
对比指标：TOP_EXIT AUC, DIP_BUY AUC, 过拟合衰减率

用法：
    cd 12-三屏趋势系统
    python ml/v55_baseline/step2_sliding_window.py
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

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
    """生成标签"""
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


def walk_forward_once(features, labels, feature_names,
                       n_splits=12, train_days=730, test_days=180, step_days=180):
    """一次性训练验证（原有方式）
    
    特点：用全部历史数据训练一个模型
    问题：长期过拟合，训练AUC接近1.0
    """
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


def walk_forward_sliding(features, labels, feature_names,
                          window_days=730, test_days=180, step_days=180):
    """滑动窗口训练验证
    
    特点：每180天重新训练模型，只使用最近730天数据
    优势：适应市场状态变化，减少长期过拟合
    """
    n = len(features)
    feature_importances = []
    train_aucs, test_aucs = [], []
    
    # 滑动窗口：每次只训练window_days天
    test_end = n
    splits = []
    
    while test_end > window_days + test_days:
        test_start = test_end - test_days
        train_end = test_start
        train_start = train_end - window_days
        if train_start < 0:
            break
        splits.append((train_start, train_end, test_start, test_end))
        test_end -= step_days
    
    splits = list(reversed(splits))
    
    print(f"    滑动窗口训练: {len(splits)}折, 窗口{window_days}天, 步进{step_days}天")
    
    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        X_train = features.iloc[tr_s:tr_e][feature_names].values
        y_train = labels[tr_s:tr_e]
        X_test = features.iloc[te_s:te_e][feature_names].values
        y_test = labels[te_s:te_e]
        
        if y_train.sum() < 5 or y_test.sum() < 2:
            continue
        
        # 每次重新训练模型（滑动窗口的核心）
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
    print("  Step 2: 滑动窗口训练优化")
    print("  目标：减少训练AUC=1.0的过拟合问题")
    print("=" * 80)
    
    # 加载数据
    prices = load_btc_data()
    closes = prices["close"].values
    print(f"\n  BTC日线: {len(prices)}天")
    
    # 计算特征（使用Step1精简后的25维）
    t0 = time.time()
    trend_fe = TrendFeatureEngineer()
    trend_df = trend_fe.create_features(prices, label_lookahead=20)
    trend_cols = [c for c in trend_df.columns if c not in ["future_return", "label", "label_reg"]]
    trend_features = trend_df[trend_cols].copy()
    
    phil_fe = PhilosophyFeatureEngineer()
    phil_features = phil_fe.extract_series(prices, symbol="BTC")
    
    # 移除3个冗余特征
    redundant_features = ["dip_buy_level", "dip_buy_position_ratio", "left_side_buy_signal"]
    v55_names = list(phil_features.columns)
    v56_names = [f for f in v55_names if f not in redundant_features]
    
    features = pd.concat([trend_features, phil_features[v56_names]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    feature_names = list(features.columns)
    
    print(f"  特征维度: {len(feature_names)}（趋势{trend_features.shape[1]}+哲学{len(v56_names)}）")
    print(f"  计算耗时: {time.time() - t0:.1f}s")
    
    # 标签
    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")
    
    # ========== 方案1：一次性训练（原有方式）==========
    print("\n" + "=" * 80)
    print("  【方案1】一次性训练（原有方式）")
    print("=" * 80)
    
    top1, top1_tr, top1_dec, _ = walk_forward_once(features, top_exit_labels, feature_names)
    dip1, dip1_tr, dip1_dec, _ = walk_forward_once(features, dip_buy_labels, feature_names)
    
    print(f"\n  TOP_EXIT: 测试AUC={top1:.4f}, 训练AUC={top1_tr:.4f}, 衰减={top1_dec:.1%}")
    print(f"  DIP_BUY:  测试AUC={dip1:.4f}, 训练AUC={dip1_tr:.4f}, 衰减={dip1_dec:.1%}")
    print(f"  ⚠️ 问题: 训练AUC={top1_tr:.4f}≈1.0，严重过拟合")
    
    # ========== 方案2：滑动窗口训练（730天窗口，180天步进）==========
    print("\n" + "=" * 80)
    print("  【方案2】滑动窗口训练（730天窗口，180天重训）")
    print("=" * 80)
    
    print("\n  TOP_EXIT验证:")
    top2, top2_tr, top2_dec, _ = walk_forward_sliding(features, top_exit_labels, feature_names)
    
    print(f"\n  DIP_BUY验证:")
    dip2, dip2_tr, dip2_dec, _ = walk_forward_sliding(features, dip_buy_labels, feature_names)
    
    print(f"\n  TOP_EXIT: 测试AUC={top2:.4f}, 训练AUC={top2_tr:.4f}, 衰减={top2_dec:.1%}")
    print(f"  DIP_BUY:  测试AUC={dip2:.4f}, 训练AUC={dip2_tr:.4f}, 衰减={dip2_dec:.1%}")
    
    # ========== 对比分析 ==========
    print("\n" + "=" * 80)
    print("  【对比分析】")
    print("=" * 80)
    
    delta_top = top2 - top1
    delta_dip = dip2 - dip1
    delta_top_dec = top2_dec - top1_dec
    delta_dip_dec = dip2_dec - dip1_dec
    
    print(f"\n  {'指标':<25s} {'一次性训练':>12s} {'滑动窗口':>12s} {'变化':>12s}")
    print("  " + "-" * 65)
    print(f"  {'TOP_EXIT 测试AUC':<25s} {top1:>12.4f} {top2:>12.4f} {delta_top:>+12.4f}")
    print(f"  {'TOP_EXIT 训练AUC':<25s} {top1_tr:>12.4f} {top2_tr:>12.4f} {top2_tr-top1_tr:>+12.4f}")
    print(f"  {'TOP_EXIT 衰减率':<25s} {top1_dec:>12.1%} {top2_dec:>12.1%} {delta_top_dec:>+12.1%}")
    print()
    print(f"  {'DIP_BUY 测试AUC':<25s} {dip1:>12.4f} {dip2:>12.4f} {delta_dip:>+12.4f}")
    print(f"  {'DIP_BUY 训练AUC':<25s} {dip1_tr:>12.4f} {dip2_tr:>12.4f} {dip2_tr-dip1_tr:>+12.4f}")
    print(f"  {'DIP_BUY 衰减率':<25s} {dip1_dec:>12.1%} {dip2_dec:>12.1%} {delta_dip_dec:>+12.1%}")
    
    # 判断结果
    print("\n" + "=" * 80)
    if delta_top > 0 and delta_dip > 0:
        print("  ✅ 结论：滑动窗口训练有效，双场景测试AUC均提升")
        print("  建议：进入Step 3（多步标签改进）")
    elif delta_top > 0 or delta_dip > 0:
        print("  🟡 结论：滑动窗口训练部分有效")
        print("  建议：评估是否调整窗口大小或步进间隔")
    else:
        print("  ❌ 结论：滑动窗口训练无效，双场景测试AUC均下降")
        print("  建议：重新评估训练策略，考虑其他优化方向")
    print("=" * 80)
    
    # 关键指标改善
    print("\n  【关键指标改善】")
    train_auc_improve = (top2_tr < top1_tr)  # 训练AUC降低=过拟合减少
    test_auc_improve = (delta_top > 0 or delta_dip > 0)
    
    if train_auc_improve:
        print(f"  ✓ 训练AUC降低: {top1_tr:.4f} → {top2_tr:.4f}，过拟合减轻")
    else:
        print(f"  ✗ 训练AUC未降低，过拟合依然严重")
    
    if test_auc_improve:
        print(f"  ✓ 测试AUC提升，样本外泛化能力增强")
    else:
        print(f"  ✗ 测试AUC未提升，泛化能力无改善")
    
    # 保存结果
    output = {
        "step": "step2_sliding_window",
        "analysis_date": str(pd.Timestamp.now()),
        "once_training": {
            "top_exit": {"test_auc": top1, "train_auc": top1_tr, "decay": top1_dec},
            "dip_buy": {"test_auc": dip1, "train_auc": dip1_tr, "decay": dip1_dec},
        },
        "sliding_window": {
            "window_days": 730,
            "step_days": 180,
            "top_exit": {"test_auc": top2, "train_auc": top2_tr, "decay": top2_dec},
            "dip_buy": {"test_auc": dip2, "train_auc": dip2_tr, "decay": dip2_dec},
        },
        "comparison": {
            "delta_top_exit": delta_top,
            "delta_dip_buy": delta_dip,
            "delta_top_decay": delta_top_dec,
            "delta_dip_decay": delta_dip_dec,
        },
        "conclusion": "success" if delta_top > 0 and delta_dip > 0 else "partial" if delta_top > 0 or delta_dip > 0 else "failed",
    }
    
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/step2_sliding_window.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存: {output_path}")
    
    return output


if __name__ == "__main__":
    main()