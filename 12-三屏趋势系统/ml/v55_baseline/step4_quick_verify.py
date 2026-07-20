"""Step 4 简化版: LSTM/Transformer快速验证（单折）

目标：快速验证时序模型是否能降低训练AUC

用法：
    cd 12-三屏趋势系统
    python ml/v55_baseline/step4_quick_verify.py
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from ml.feature_engineer import TrendFeatureEngineer
from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer


class LSTMModel(nn.Module):
    def __init__(self, input_dim, hidden_dim=32, num_layers=2, dropout=0.3):
        super(LSTMModel, self).__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True, dropout=dropout if num_layers > 1 else 0)
        self.fc1 = nn.Linear(hidden_dim, 16)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(dropout)
        self.fc2 = nn.Linear(16, 1)
        self.sigmoid = nn.Sigmoid()
    
    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        lstm_out = lstm_out[:, -1, :]
        out = self.fc1(lstm_out)
        out = self.relu(out)
        out = self.dropout(out)
        out = self.fc2(out)
        return self.sigmoid(out).squeeze()


def main():
    print("=" * 80)
    print("  Step 4 简化版: LSTM/Transformer快速验证")
    print("=" * 80)
    
    # 加载数据
    with open(os.path.join(BASE_DIR, "data/historical/BTC_1D_730d.json")) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"})
    
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
    
    # 标签
    labels = np.zeros(n)
    for i in range(n - 20):
        future = closes[i + 20]
        if (closes[i] - future) / closes[i] > 0.20:
            labels[i] = 1
    
    # 标准化
    scaler = StandardScaler()
    features_scaled = pd.DataFrame(scaler.fit_transform(features[feature_names]), columns=feature_names, index=features.index)
    
    # 创建序列样本（单折：最近730天训练，最近180天测试）
    seq_length = 20
    train_start = n - 730 - 180
    train_end = n - 180
    test_start = n - 180
    test_end = n
    
    print(f"\n  训练区间: {train_start}-{train_end} ({train_end-train_start}天)")
    print(f"  测试区间: {test_start}-{test_end} ({test_end-test_start}天)")
    
    # 创建序列
    X_train, y_train = [], []
    for i in range(train_start + seq_length, train_end):
        X_train.append(features_scaled.iloc[i-seq_length:i].values)
        y_train.append(labels[i])
    X_train = np.array(X_train)
    y_train = np.array(y_train)
    
    X_test, y_test = [], []
    for i in range(test_start + seq_length, test_end):
        X_test.append(features_scaled.iloc[i-seq_length:i].values)
        y_test.append(labels[i])
    X_test = np.array(X_test)
    y_test = np.array(y_test)
    
    print(f"  训练样本: {len(X_train)}, 测试样本: {len(X_test)}")
    
    # ========== LightGBM对比 ==========
    print("\n" + "=" * 80)
    print("  【LightGBM基线】")
    print("=" * 80)
    
    import lightgbm as lgb
    
    # LightGBM不使用序列，直接使用单点特征
    X_train_lgb = features.iloc[train_start+seq_length:train_end][feature_names].values
    y_train_lgb = labels[train_start+seq_length:train_end]
    X_test_lgb = features.iloc[test_start+seq_length:test_end][feature_names].values
    y_test_lgb = labels[test_start+seq_length:test_end]
    
    model_lgb = lgb.LGBMClassifier(n_estimators=200, max_depth=6, learning_rate=0.05, random_state=42, verbose=-1)
    model_lgb.fit(X_train_lgb, y_train_lgb)
    
    train_pred_lgb = model_lgb.predict_proba(X_train_lgb)[:, 1]
    test_pred_lgb = model_lgb.predict_proba(X_test_lgb)[:, 1]
    
    train_auc_lgb = roc_auc_score(y_train_lgb, train_pred_lgb)
    test_auc_lgb = roc_auc_score(y_test_lgb, test_pred_lgb)
    decay_lgb = 1.0 - (test_auc_lgb / train_auc_lgb)
    
    print(f"  训练AUC: {train_auc_lgb:.4f}")
    print(f"  测试AUC: {test_auc_lgb:.4f}")
    print(f"  衰减率:  {decay_lgb:.1%}")
    print(f"  ⚠️ 训练AUC={train_auc_lgb:.4f}，严重过拟合")
    
    # ========== LSTM ==========
    print("\n" + "=" * 80)
    print("  【LSTM】")
    print("=" * 80)
    
    X_train_t = torch.FloatTensor(X_train)
    y_train_t = torch.FloatTensor(y_train)
    X_test_t = torch.FloatTensor(X_test)
    y_test_t = torch.FloatTensor(y_test)
    
    train_dataset = TensorDataset(X_train_t, y_train_t)
    test_dataset = TensorDataset(X_test_t, y_test_t)
    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)
    
    model = LSTMModel(len(feature_names), hidden_dim=32, num_layers=2, dropout=0.3)
    criterion = nn.BCELoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    
    # 训练
    print("  训练中...")
    for epoch in range(20):
        model.train()
        for X_batch, y_batch in train_loader:
            optimizer.zero_grad()
            outputs = model(X_batch)
            loss = criterion(outputs, y_batch)
            loss.backward()
            optimizer.step()
    
    # 评估
    model.eval()
    with torch.no_grad():
        train_pred_lstm = model(X_train_t).numpy()
        test_pred_lstm = model(X_test_t).numpy()
    
    train_auc_lstm = roc_auc_score(y_train, train_pred_lstm)
    test_auc_lstm = roc_auc_score(y_test, test_pred_lstm)
    decay_lstm = 1.0 - (test_auc_lstm / train_auc_lstm)
    
    print(f"  训练AUC: {train_auc_lstm:.4f}")
    print(f"  测试AUC: {test_auc_lstm:.4f}")
    print(f"  衰减率:  {decay_lstm:.1%}")
    
    # ========== 对比分析 ==========
    print("\n" + "=" * 80)
    print("  【对比分析】")
    print("=" * 80)
    
    print(f"\n  {'模型':<15s} {'训练AUC':>12s} {'测试AUC':>12s} {'衰减率':>10s}")
    print("  " + "-" * 55)
    print(f"  {'LightGBM':<15s} {train_auc_lgb:>12.4f} {test_auc_lgb:>12.4f} {decay_lgb:>10.1%}")
    print(f"  {'LSTM':<15s} {train_auc_lstm:>12.4f} {test_auc_lstm:>12.4f} {decay_lstm:>10.1%}")
    
    # 判断
    print("\n" + "=" * 80)
    print("  【结论】")
    print("=" * 80)
    
    train_reduce = train_auc_lgb - train_auc_lstm
    test_change = test_auc_lstm - test_auc_lgb
    
    if train_auc_lstm < 0.95:
        print(f"\n  ✅ LSTM有效降低训练AUC:")
        print(f"     LightGBM: {train_auc_lgb:.4f} → LSTM: {train_auc_lstm:.4f} (降低{train_reduce:.4f})")
        print(f"     过拟合问题得到缓解")
    else:
        print(f"\n  ❌ LSTM未能降低训练AUC:")
        print(f"     LSTM训练AUC={train_auc_lstm:.4f}，仍然过拟合")
    
    if test_auc_lstm > test_auc_lgb:
        print(f"\n  ✅ LSTM测试AUC提升:")
        print(f"     LightGBM: {test_auc_lgb:.4f} → LSTM: {test_auc_lstm:.4f} (提升{test_change:.4f})")
    else:
        print(f"\n  ⚠️ LSTM测试AUC未提升:")
        print(f"     LSTM={test_auc_lstm:.4f} vs LightGBM={test_auc_lgb:.4f} (变化{test_change:.4f})")
    
    # 保存结果
    output = {
        "step": "step4_quick_verify",
        "analysis_date": str(pd.Timestamp.now()),
        "lightgbm": {"train_auc": train_auc_lgb, "test_auc": test_auc_lgb, "decay": decay_lgb},
        "lstm": {"train_auc": train_auc_lstm, "test_auc": test_auc_lstm, "decay": decay_lstm},
        "comparison": {"train_reduce": train_reduce, "test_change": test_change},
        "conclusion": "success" if train_auc_lstm < 0.95 else "failed",
    }
    
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/step4_quick_verify.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存: {output_path}")


if __name__ == "__main__":
    main()