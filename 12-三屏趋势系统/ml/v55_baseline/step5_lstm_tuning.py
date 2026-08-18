"""Step 5 调优版: LSTM参数调优

目标：找到训练AUC<0.95 且 测试AUC接近LightGBM的最优配置

策略：
- 更大的Dropout（0.5）
- 更小的hidden_dim（32）
- 加大weight_decay（L2正则化）
- 减少epochs
- 使用序列长度30（更长上下文）

用法：
    cd 12-三屏趋势系统
    python ml/v55_baseline/step5_lstm_tuning.py
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

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


def generate_labels(closes, lookahead=20, threshold=0.20, mode="drop"):
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


def create_sequences(features_arr, labels, seq_length):
    X, y = [], []
    n = len(features_arr)
    for i in range(seq_length, n):
        X.append(features_arr[i-seq_length:i])
        y.append(labels[i])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


class RegularizedLSTM(nn.Module):
    """带强正则化的LSTM"""
    def __init__(self, input_dim, hidden_dim=32, num_layers=2, dropout=0.5):
        super(RegularizedLSTM, self).__init__()
        
        # 输入Dropout
        self.input_dropout = nn.Dropout(dropout * 0.5)
        
        self.lstm = nn.LSTM(
            input_dim, hidden_dim, num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0
        )
        
        # 输出层带强正则化
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim, 16),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(16, 1),
            nn.Sigmoid()
        )
    
    def forward(self, x):
        x = self.input_dropout(x)
        out, _ = self.lstm(x)
        out = out[:, -1, :]
        return self.fc(out).squeeze()


def train_model_with_reg(model, X_train, y_train, X_val, y_val,
                          epochs=20, lr=0.001, batch_size=32, patience=5, weight_decay=0.01):
    """带L2正则化的训练"""
    model = model.to('cpu')
    
    criterion = nn.BCELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    
    pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    
    train_dataset = TensorDataset(
        torch.FloatTensor(X_train), torch.FloatTensor(y_train)
    )
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    
    best_val_loss = float('inf')
    patience_counter = 0
    best_state = None
    
    for epoch in range(epochs):
        model.train()
        for X_batch, y_batch in train_loader:
            optimizer.zero_grad()
            outputs = model(X_batch)
            weight = torch.where(y_batch > 0.5, 
                                  torch.tensor([pos_weight], dtype=torch.float32),
                                  torch.ones_like(y_batch))
            loss = nn.functional.binary_cross_entropy(outputs, y_batch, weight=weight)
            loss.backward()
            optimizer.step()
        
        model.eval()
        with torch.no_grad():
            val_outputs = model(torch.FloatTensor(X_val))
            val_loss = nn.functional.binary_cross_entropy(
                val_outputs, torch.FloatTensor(y_val)
            ).item()
        
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            patience_counter += 1
            if patience_counter >= patience:
                break
    
    if best_state is not None:
        model.load_state_dict(best_state)
    
    return model


def evaluate_model(model, X, y):
    model.eval()
    with torch.no_grad():
        preds = model(torch.FloatTensor(X)).numpy()
    if len(set(y)) > 1:
        return roc_auc_score(y, preds)
    return 0.5


def walk_forward(features_arr, labels, config, seq_length=20,
                 n_splits=12, train_days=730, test_days=180, step_days=180):
    """Walk-Forward验证"""
    n = len(features_arr)
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
    
    input_dim = features_arr.shape[1]
    valid_splits = 0
    
    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        X_train, y_train = create_sequences(features_arr[tr_s:tr_e], labels[tr_s:tr_e], seq_length)
        X_test, y_test = create_sequences(features_arr[te_s:te_e], labels[te_s:te_e], seq_length)
        
        if len(X_train) < 50 or len(X_test) < 10:
            continue
        if y_train.sum() < 3 or y_test.sum() < 2:
            continue
        
        model = RegularizedLSTM(
            input_dim=input_dim,
            hidden_dim=config['hidden_dim'],
            num_layers=config['num_layers'],
            dropout=config['dropout']
        )
        
        model = train_model_with_reg(
            model, X_train, y_train, X_test, y_test,
            epochs=config['epochs'], lr=config['lr'],
            batch_size=config['batch_size'], patience=config['patience'],
            weight_decay=config['weight_decay']
        )
        
        train_auc = evaluate_model(model, X_train, y_train)
        test_auc = evaluate_model(model, X_test, y_test)
        
        train_aucs.append(train_auc)
        test_aucs.append(test_auc)
        valid_splits += 1
    
    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0
    
    return avg_test, avg_train, float(decay), valid_splits


def main():
    print("=" * 80)
    print("  Step 5 调优版: LSTM参数调优")
    print("  目标：训练AUC<0.95 且 测试AUC接近LightGBM")
    print("=" * 80)
    
    prices = load_btc_data()
    closes = prices["close"].values
    n = len(prices)
    print(f"\n  BTC日线: {n}天")
    
    # 计算特征
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
    
    # 标准化
    scaler = StandardScaler()
    features_arr = scaler.fit_transform(features[feature_names]).astype(np.float32)
    
    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")
    
    # 不同超参配置
    configs = [
        {
            'name': 'Config1: 强Dropout',
            'hidden_dim': 32, 'num_layers': 2, 'dropout': 0.5,
            'epochs': 15, 'lr': 0.001, 'batch_size': 32,
            'patience': 5, 'weight_decay': 0.01,
            'seq_length': 20
        },
        {
            'name': 'Config2: 小模型+长序列',
            'hidden_dim': 16, 'num_layers': 1, 'dropout': 0.4,
            'epochs': 15, 'lr': 0.001, 'batch_size': 16,
            'patience': 5, 'weight_decay': 0.05,
            'seq_length': 30
        },
        {
            'name': 'Config3: 极强L2正则化',
            'hidden_dim': 32, 'num_layers': 2, 'dropout': 0.4,
            'epochs': 10, 'lr': 0.0005, 'batch_size': 64,
            'patience': 3, 'weight_decay': 0.1,
            'seq_length': 20
        },
        {
            'name': 'Config4: 极简模型',
            'hidden_dim': 8, 'num_layers': 1, 'dropout': 0.5,
            'epochs': 10, 'lr': 0.001, 'batch_size': 32,
            'patience': 3, 'weight_decay': 0.02,
            'seq_length': 20
        },
    ]
    
    results = []
    
    for config in configs:
        print(f"\n{'=' * 80}")
        print(f"  【{config['name']}】")
        print(f"  hidden={config['hidden_dim']}, layers={config['num_layers']}, dropout={config['dropout']}, "
              f"wd={config['weight_decay']}, seq={config['seq_length']}")
        print(f"{'=' * 80}")
        
        # TOP_EXIT
        t0 = time.time()
        top_test, top_train, top_decay, top_splits = walk_forward(
            features_arr, top_exit_labels, config, seq_length=config['seq_length']
        )
        top_time = time.time() - t0
        
        print(f"  TOP_EXIT: train={top_train:.4f}, test={top_test:.4f}, decay={top_decay:.1%}, "
              f"splits={top_splits}, time={top_time:.1f}s")
        
        # DIP_BUY
        t0 = time.time()
        dip_test, dip_train, dip_decay, dip_splits = walk_forward(
            features_arr, dip_buy_labels, config, seq_length=config['seq_length']
        )
        dip_time = time.time() - t0
        
        print(f"  DIP_BUY:  train={dip_train:.4f}, test={dip_test:.4f}, decay={dip_decay:.1%}, "
              f"splits={dip_splits}, time={dip_time:.1f}s")
        
        results.append({
            'name': config['name'],
            'config': config,
            'top_exit': {'train_auc': top_train, 'test_auc': top_test, 'decay': top_decay},
            'dip_buy': {'train_auc': dip_train, 'test_auc': dip_test, 'decay': dip_decay},
        })
    
    # ========== 对比分析 ==========
    print(f"\n{'=' * 80}")
    print(f"  【对比分析】")
    print(f"{'=' * 80}")
    
    # LightGBM基线
    lgb_top = {'train': 1.0000, 'test': 0.7372, 'decay': 0.263}
    lgb_dip = {'train': 1.0000, 'test': 0.6981, 'decay': 0.302}
    
    print(f"\n  TOP_EXIT场景:")
    print(f"  {'配置':<30s} {'训练AUC':>10s} {'测试AUC':>10s} {'衰减率':>8s} {'过拟合缓解':>12s}")
    print("  " + "-" * 75)
    print(f"  {'LightGBM基线':<30s} {lgb_top['train']:>10.4f} {lgb_top['test']:>10.4f} {lgb_top['decay']:>8.1%} {'❌':>12s}")
    
    for r in results:
        resolved = '✅' if r['top_exit']['train_auc'] < 0.95 else '❌'
        print(f"  {r['name']:<30s} {r['top_exit']['train_auc']:>10.4f} {r['top_exit']['test_auc']:>10.4f} "
              f"{r['top_exit']['decay']:>8.1%} {resolved:>12s}")
    
    print(f"\n  DIP_BUY场景:")
    print(f"  {'配置':<30s} {'训练AUC':>10s} {'测试AUC':>10s} {'衰减率':>8s} {'过拟合缓解':>12s}")
    print("  " + "-" * 75)
    print(f"  {'LightGBM基线':<30s} {lgb_dip['train']:>10.4f} {lgb_dip['test']:>10.4f} {lgb_dip['decay']:>8.1%} {'❌':>12s}")
    
    for r in results:
        resolved = '✅' if r['dip_buy']['train_auc'] < 0.95 else '❌'
        print(f"  {r['name']:<30s} {r['dip_buy']['train_auc']:>10.4f} {r['dip_buy']['test_auc']:>10.4f} "
              f"{r['dip_buy']['decay']:>8.1%} {resolved:>12s}")
    
    # 找最佳配置
    print(f"\n{'=' * 80}")
    print(f"  【结论】")
    print(f"{'=' * 80}")
    
    # TOP_EXIT最佳
    top_resolved = [r for r in results if r['top_exit']['train_auc'] < 0.95]
    dip_resolved = [r for r in results if r['dip_buy']['train_auc'] < 0.95]
    
    print(f"\n  过拟合缓解（训练AUC<0.95）:")
    print(f"    TOP_EXIT: {len(top_resolved)}/{len(results)} 配置成功")
    print(f"    DIP_BUY:  {len(dip_resolved)}/{len(results)} 配置成功")
    
    if top_resolved:
        best_top = max(top_resolved, key=lambda x: x['top_exit']['test_auc'])
        print(f"\n  TOP_EXIT最佳配置:")
        print(f"    {best_top['name']}")
        print(f"    训练AUC: {best_top['top_exit']['train_auc']:.4f}")
        print(f"    测试AUC: {best_top['top_exit']['test_auc']:.4f} (vs LightGBM {lgb_top['test']:.4f})")
    
    if dip_resolved:
        best_dip = max(dip_resolved, key=lambda x: x['dip_buy']['test_auc'])
        print(f"\n  DIP_BUY最佳配置:")
        print(f"    {best_dip['name']}")
        print(f"    训练AUC: {best_dip['dip_buy']['train_auc']:.4f}")
        print(f"    测试AUC: {best_dip['dip_buy']['test_auc']:.4f} (vs LightGBM {lgb_dip['test']:.4f})")
    
    # 总体推荐
    print(f"\n  【总体推荐】")
    # 计算综合得分：测试AUC + 过拟合缓解奖励
    for r in results:
        score_top = r['top_exit']['test_auc'] + (0.05 if r['top_exit']['train_auc'] < 0.95 else 0)
        score_dip = r['dip_buy']['test_auc'] + (0.05 if r['dip_buy']['train_auc'] < 0.95 else 0)
        r['total_score'] = score_top + score_dip
    
    best = max(results, key=lambda x: x['total_score'])
    print(f"  综合最佳: {best['name']}")
    print(f"  总分: {best['total_score']:.4f}")
    
    # 保存结果
    output = {
        "step": "step5_lstm_tuning",
        "analysis_date": str(pd.Timestamp.now()),
        "lightgbm_baseline": {
            "top_exit": {"train_auc": lgb_top['train'], "test_auc": lgb_top['test'], "decay": lgb_top['decay']},
            "dip_buy": {"train_auc": lgb_dip['train'], "test_auc": lgb_dip['test'], "decay": lgb_dip['decay']},
        },
        "configs": results,
        "best_config": {
            "name": best['name'],
            "total_score": best['total_score'],
        },
    }
    
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/step5_lstm_tuning.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  结果已保存: {output_path}")


if __name__ == "__main__":
    main()