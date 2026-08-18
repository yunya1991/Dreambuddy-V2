"""Step 3: 多步标签改进验证

目标：同时预测多个时间尺度的收益方向，减少单一标签的噪声

策略：
- 多步标签：同时预测未来3/7/14/20天的收益方向
- 多任务学习：一个模型同时预测4个标签
- 优势：捕捉不同时间尺度的趋势信号，提高特征稳定性

预期效果：
- 减少单一标签的噪声影响
- 提高特征对不同时间尺度的泛化能力
- 更稳健的预测信号

验证方式：Walk-Forward (12折)
对比指标：各时间尺度的AUC, 平均AUC

用法：
    cd 12-三屏趋势系统
    python ml/v55_baseline/step3_multistep_labels.py
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


def generate_multistep_labels(closes, lookahead_list, threshold=0.15):
    """生成多步标签
    
    Args:
        closes: 收盘价序列
        lookahead_list: 前瞻天数列表，如[3, 7, 14, 20]
        threshold: 收益阈值
    
    Returns:
        labels_dict: {lookahead: labels} 的字典
    """
    n = len(closes)
    labels_dict = {}
    
    for lookahead in lookahead_list:
        labels = np.zeros(n)
        for i in range(n - lookahead):
            future = closes[i + lookahead]
            ret = (future - closes[i]) / closes[i]
            if ret > threshold:
                labels[i] = 1  # 上涨
            elif ret < -threshold:
                labels[i] = 0  # 下跌（可以改为2类或多类）
            else:
                labels[i] = 0.5  # 震荡（标记为中间值，后续处理）
        labels_dict[lookahead] = labels
    
    return labels_dict


def walk_forward_single_label(features, labels, feature_names,
                               n_splits=12, train_days=730, test_days=180, step_days=180):
    """单标签验证（原有方式）
    
    特点：只预测单一时间尺度（20天）
    问题：标签噪声大，容易过拟合
    """
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
        
        # 过滤掉中间值（0.5）
        valid_train = y_train != 0.5
        valid_test = y_test != 0.5
        
        if valid_train.sum() < 5 or valid_test.sum() < 2:
            continue
        
        X_train = X_train[valid_train]
        y_train = y_train[valid_train]
        X_test = X_test[valid_test]
        y_test = y_test[valid_test]
        
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
    
    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0
    
    return avg_test, avg_train, float(decay)


def walk_forward_multistep_vote(features, labels_dict, feature_names,
                                  n_splits=12, train_days=730, test_days=180, step_days=180):
    """多步标签投票验证
    
    特点：训练4个模型（3/7/14/20天），预测时取平均或投票
    优势：减少单一标签噪声，提高预测稳定性
    """
    n = len(features)
    lookahead_list = list(labels_dict.keys())
    
    # 对每个时间尺度分别计算AUC
    results = {}
    
    for lookahead in lookahead_list:
        labels = labels_dict[lookahead]
        test_aucs = []
        
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
            
            # 过滤中间值
            valid_train = y_train != 0.5
            valid_test = y_test != 0.5
            
            if valid_train.sum() < 5 or valid_test.sum() < 2:
                continue
            
            X_train = X_train[valid_train]
            y_train = y_train[valid_train]
            X_test = X_test[valid_test]
            y_test = y_test[valid_test]
            
            model = lgb.LGBMClassifier(
                n_estimators=200, max_depth=6, learning_rate=0.05,
                num_leaves=31, min_child_samples=20,
                subsample=0.8, colsample_bytree=0.8,
                random_state=42, verbose=-1,
            )
            model.fit(X_train, y_train)
            
            test_pred = model.predict_proba(X_test)[:, 1]
            
            if len(set(y_test)) > 1:
                test_aucs.append(roc_auc_score(y_test, test_pred))
        
        results[lookahead] = {
            'test_auc': float(np.mean(test_aucs)) if test_aucs else 0.0,
            'test_aucs': test_aucs,
        }
    
    # 计算平均AUC
    avg_test_aucs = [results[l]['test_auc'] for l in lookahead_list]
    avg_auc = float(np.mean(avg_test_aucs))
    
    return results, avg_auc


def main():
    print("=" * 80)
    print("  Step 3: 多步标签改进验证")
    print("  目标：同时预测3/7/14/20天收益方向，减少标签噪声")
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
    
    # ========== 生成多步标签 ==========
    print("\n" + "=" * 80)
    print("  【多步标签生成】")
    print("=" * 80)
    
    lookahead_list = [3, 7, 14, 20]
    threshold = 0.10  # 降低阈值，增加有效样本
    
    labels_dict = generate_multistep_labels(closes, lookahead_list, threshold)
    
    for lookahead in lookahead_list:
        labels = labels_dict[lookahead]
        up_pct = (labels == 1).sum() / len(labels) * 100
        down_pct = (labels == 0).sum() / len(labels) * 100
        neutral_pct = (labels == 0.5).sum() / len(labels) * 100
        print(f"\n  {lookahead}天标签: 上涨{up_pct:.1f}%, 下跌{down_pct:.1f}%, 震荡{neutral_pct:.1f}%")
    
    # ========== 单标签验证（20天，原有方式）==========
    print("\n" + "=" * 80)
    print("  【方案1】单标签验证（20天）")
    print("=" * 80)
    
    single_test, single_train, single_decay = walk_forward_single_label(
        features, labels_dict[20], feature_names)
    
    print(f"\n  测试AUC={single_test:.4f}, 训练AUC={single_train:.4f}, 衰减={single_decay:.1%}")
    
    # ========== 多步标签验证（3/7/14/20天）==========
    print("\n" + "=" * 80)
    print("  【方案2】多步标签验证（3/7/14/20天）")
    print("=" * 80)
    
    results, avg_auc = walk_forward_multistep_vote(features, labels_dict, feature_names)
    
    print("\n  各时间尺度AUC:")
    for lookahead in lookahead_list:
        print(f"    {lookahead}天: 测试AUC={results[lookahead]['test_auc']:.4f}")
    
    print(f"\n  平均测试AUC={avg_auc:.4f}")
    
    # ========== 对比分析 ==========
    print("\n" + "=" * 80)
    print("  【对比分析】")
    print("=" * 80)
    
    delta = avg_auc - single_test
    
    print(f"\n  {'指标':<25s} {'单标签(20天)':>15s} {'多步平均':>15s} {'变化':>12s}")
    print("  " + "-" * 70)
    print(f"  {'测试AUC':<25s} {single_test:>15.4f} {avg_auc:>15.4f} {delta:>+12.4f}")
    
    # 各时间尺度详细对比
    print("\n  各时间尺度详细对比:")
    for lookahead in lookahead_list:
        auc_val = results[lookahead]['test_auc']
        delta_val = auc_val - single_test
        status = "✓" if auc_val > single_test else "✗"
        print(f"    {lookahead}天: {auc_val:.4f} (vs单标签 {delta_val:+.4f}) {status}")
    
    # 判断结果
    print("\n" + "=" * 80)
    better_count = sum(1 for l in lookahead_list if results[l]['test_auc'] > single_test)
    
    if avg_auc > single_test:
        print("  ✅ 结论：多步标签有效，平均AUC提升")
        print(f"  改善：{delta:+.4f} ({better_count}/4个时间尺度优于单标签)")
    elif better_count >= 2:
        print("  🟡 结论：多步标签部分有效，多个时间尺度优于单标签")
        print(f"  改善时间尺度：{better_count}/4")
    else:
        print("  ❌ 结论：多步标签无效，平均AUC下降")
        print("  建议：重新评估标签生成策略")
    print("=" * 80)
    
    # 最佳时间尺度
    best_lookahead = max(lookahead_list, key=lambda l: results[l]['test_auc'])
    best_auc = results[best_lookahead]['test_auc']
    print(f"\n  最佳时间尺度: {best_lookahead}天, AUC={best_auc:.4f}")
    
    # 保存结果
    output = {
        "step": "step3_multistep_labels",
        "analysis_date": str(pd.Timestamp.now()),
        "single_label": {
            "lookahead": 20,
            "test_auc": single_test,
            "train_auc": single_train,
            "decay": single_decay,
        },
        "multistep_labels": {
            "lookahead_list": lookahead_list,
            "results": {str(k): {"test_auc": v['test_auc']} for k, v in results.items()},
            "avg_test_auc": avg_auc,
        },
        "comparison": {
            "delta": delta,
            "better_count": better_count,
            "best_lookahead": best_lookahead,
            "best_auc": best_auc,
        },
        "conclusion": "success" if avg_auc > single_test else "partial" if better_count >= 2 else "failed",
    }
    
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/step3_multistep_labels.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存: {output_path}")
    
    return output


if __name__ == "__main__":
    main()