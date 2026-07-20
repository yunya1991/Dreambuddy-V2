"""Step 4 替代方案: LightGBM强化正则化验证

目标：通过大幅强化正则化参数，降低训练AUC

策略：
- 增大min_child_samples: 强制叶子节点最小样本数
- 减小num_leaves: 限制模型复杂度
- 加大lambda_l1/lambda_l2: L1/L2正则化
- 降低max_depth: 限制树的深度

预期效果：
- 训练AUC显著降低（目标<0.95）
- 减少过拟合

用法：
    cd 12-三屏趋势系统
    python ml/v55_baseline/step4_regularization.py
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


def load_btc_data():
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


def walk_forward_validation(features, labels, feature_names, params,
                             n_splits=12, train_days=730, test_days=180, step_days=180):
    """Walk-Forward验证"""
    n = len(features)
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
        
        model = lgb.LGBMClassifier(**params, random_state=42, verbose=-1)
        model.fit(X_train, y_train)
        
        train_pred = model.predict_proba(X_train)[:, 1]
        test_pred = model.predict_proba(X_test)[:, 1]
        
        if len(set(y_train)) > 1:
            train_aucs.append(roc_auc_score(y_train, train_pred))
        if len(set(y_test)) > 1:
            test_aucs.append(roc_auc_score(y_test, test_pred))
    
    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0
    
    return avg_test, avg_train, float(decay)


def main():
    print("=" * 80)
    print("  Step 4 替代方案: LightGBM强化正则化验证")
    print("  目标：通过正则化降低训练AUC，缓解过拟合")
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
    
    redundant_features = ["dip_buy_level", "dip_buy_position_ratio", "left_side_buy_signal"]
    v55_names = list(phil_features.columns)
    v56_names = [f for f in v55_names if f not in redundant_features]
    
    features = pd.concat([trend_features, phil_features[v56_names]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    feature_names = list(features.columns)
    
    print(f"  特征维度: {len(feature_names)}")
    print(f"  计算耗时: {time.time() - t0:.1f}s")
    
    # 标签
    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    
    # 定义不同的参数配置
    configs = [
        {
            "name": "V5.5基线（弱正则化）",
            "params": {
                "n_estimators": 200,
                "max_depth": 6,
                "learning_rate": 0.05,
                "num_leaves": 31,
                "min_child_samples": 20,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
            }
        },
        {
            "name": "中等正则化",
            "params": {
                "n_estimators": 200,
                "max_depth": 4,
                "learning_rate": 0.05,
                "num_leaves": 15,
                "min_child_samples": 50,
                "subsample": 0.7,
                "colsample_bytree": 0.7,
                "reg_alpha": 0.1,
                "reg_lambda": 0.1,
            }
        },
        {
            "name": "强化正则化",
            "params": {
                "n_estimators": 200,
                "max_depth": 3,
                "learning_rate": 0.05,
                "num_leaves": 7,
                "min_child_samples": 100,
                "subsample": 0.6,
                "colsample_bytree": 0.6,
                "reg_alpha": 0.5,
                "reg_lambda": 0.5,
            }
        },
        {
            "name": "极强正则化",
            "params": {
                "n_estimators": 200,
                "max_depth": 2,
                "learning_rate": 0.05,
                "num_leaves": 3,
                "min_child_samples": 200,
                "subsample": 0.5,
                "colsample_bytree": 0.5,
                "reg_alpha": 1.0,
                "reg_lambda": 1.0,
            }
        },
    ]
    
    # 运行验证
    results = []
    
    for config in configs:
        print(f"\n{'=' * 80}")
        print(f"  【{config['name']}】")
        print(f"{'=' * 80}")
        
        print(f"  参数:")
        for k, v in config['params'].items():
            print(f"    {k}: {v}")
        
        test_auc, train_auc, decay = walk_forward_validation(
            features, top_exit_labels, feature_names, config['params']
        )
        
        print(f"\n  结果:")
        print(f"    训练AUC: {train_auc:.4f}")
        print(f"    测试AUC: {test_auc:.4f}")
        print(f"    衰减率:  {decay:.1%}")
        
        results.append({
            "name": config['name'],
            "params": config['params'],
            "train_auc": train_auc,
            "test_auc": test_auc,
            "decay": decay,
        })
    
    # 对比分析
    print(f"\n{'=' * 80}")
    print(f"  【对比分析】")
    print(f"{'=' * 80}")
    
    print(f"\n  {'配置':<25s} {'训练AUC':>10s} {'测试AUC':>10s} {'衰减率':>8s} {'训练AUC降低':>12s}")
    print("  " + "-" * 70)
    
    baseline_train = results[0]['train_auc']
    for r in results:
        train_reduce = baseline_train - r['train_auc']
        print(f"  {r['name']:<25s} {r['train_auc']:>10.4f} {r['test_auc']:>10.4f} {r['decay']:>8.1%} {train_reduce:>+12.4f}")
    
    # 结论
    print(f"\n{'=' * 80}")
    print(f"  【结论】")
    print(f"{'=' * 80}")
    
    # 找最佳配置
    best = max(results, key=lambda x: x['test_auc'])
    
    if best['train_auc'] < 0.95:
        print(f"\n  ✅ 最佳配置【{best['name']}】有效降低过拟合:")
        print(f"     训练AUC: {best['train_auc']:.4f} < 0.95")
        print(f"     测试AUC: {best['test_auc']:.4f}")
        print(f"     衰减率: {best['decay']:.1%}")
    else:
        print(f"\n  ⚠️ 所有配置训练AUC仍≥0.95，正则化效果有限")
        print(f"     建议考虑其他方法（时序模型、特征工程重构）")
    
    # 推荐配置
    print(f"\n  【推荐配置】")
    if best['train_auc'] < 0.95:
        print(f"  ✅ 使用【{best['name']}】参数配置")
        for k, v in best['params'].items():
            print(f"     {k}: {v}")
    else:
        print(f"  🟡 当前正则化策略效果有限，建议:")
        print(f"     1. 迁移到时序模型（LSTM/Transformer）")
        print(f"     2. 重新设计特征工程")
        print(f"     3. 扩充训练数据")
    
    # 保存结果
    output = {
        "step": "step4_regularization",
        "analysis_date": str(pd.Timestamp.now()),
        "results": results,
        "best_config": best,
        "conclusion": "success" if best['train_auc'] < 0.95 else "failed",
    }
    
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/step4_regularization.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存: {output_path}")


if __name__ == "__main__":
    main()