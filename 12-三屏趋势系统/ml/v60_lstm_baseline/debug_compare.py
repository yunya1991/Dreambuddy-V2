"""诊断：Step5 Config1 vs V60 LSTMModel结果差异对比

用相同数据、相同参数，对比两种实现的差异
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

from ml.models import LSTMModel
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


# Step5风格的实现
class Step5LSTM:
    def __init__(self, hidden_dim=32, num_layers=2, dropout=0.5, weight_decay=0.01):
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.dropout = dropout
        self.weight_decay = weight_decay
        self.model = None

    def build_model(self, input_dim):
        class RegularizedLSTM(nn.Module):
            def __init__(self, input_dim, hidden_dim, num_layers, dropout):
                super(RegularizedLSTM, self).__init__()
                self.input_dropout = nn.Dropout(dropout * 0.5)
                self.lstm = nn.LSTM(
                    input_dim, hidden_dim, num_layers,
                    batch_first=True,
                    dropout=dropout if num_layers > 1 else 0
                )
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

        return RegularizedLSTM(input_dim, self.hidden_dim, self.num_layers, self.dropout)

    def train(self, X_train_seqs, y_train_seqs, X_val_seqs, y_val_seqs,
              epochs=15, lr=0.001, batch_size=32, patience=5):
        input_dim = X_train_seqs.shape[2]
        self.model = self.build_model(input_dim)

        pos_count = max((y_train_seqs > 0.5).sum(), 1)
        neg_count = len(y_train_seqs) - pos_count
        pos_weight_val = neg_count / pos_count

        optimizer = optim.Adam(self.model.parameters(), lr=lr, weight_decay=self.weight_decay)
        pos_weight_tensor = torch.tensor([pos_weight_val], dtype=torch.float32)

        train_dataset = TensorDataset(
            torch.FloatTensor(X_train_seqs),
            torch.FloatTensor(y_train_seqs)
        )
        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)

        best_val_loss = float('inf')
        patience_counter = 0
        best_state = None

        for epoch in range(epochs):
            self.model.train()
            for X_batch, y_batch in train_loader:
                optimizer.zero_grad()
                outputs = self.model(X_batch)
                weight = torch.where(y_batch > 0.5, pos_weight_tensor, torch.ones_like(y_batch))
                loss = nn.functional.binary_cross_entropy(outputs, y_batch, weight=weight)
                loss.backward()
                optimizer.step()

            self.model.eval()
            with torch.no_grad():
                val_outputs = self.model(torch.FloatTensor(X_val_seqs))
                val_loss = nn.functional.binary_cross_entropy(
                    val_outputs, torch.FloatTensor(y_val_seqs)
                ).item()

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                best_state = {k: v.clone() for k, v in self.model.state_dict().items()}
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    break

        if best_state is not None:
            self.model.load_state_dict(best_state)

    def predict(self, X_seqs):
        self.model.eval()
        with torch.no_grad():
            return self.model(torch.FloatTensor(X_seqs)).numpy()


def create_sequences(features_arr, labels, seq_length):
    X, y = [], []
    n = len(features_arr)
    for i in range(seq_length, n):
        X.append(features_arr[i-seq_length:i])
        y.append(labels[i])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


def main():
    print("=" * 80)
    print("  诊断：Step5 Config1 vs V60 LSTMModel 结果对比")
    print("=" * 80)

    prices = load_btc_data()
    closes = prices["close"].values
    n = len(prices)
    print(f"\n  BTC日线: {n}天")

    # 特征
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

    labels = generate_labels(closes, 20, 0.20, "drop")

    # 取一个折做对比（最后一折）
    seq_length = 20
    train_days = 730
    test_days = 180

    tr_s = n - train_days - test_days
    tr_e = n - test_days
    te_s = n - test_days
    te_e = n

    print(f"\n  使用最后一折: train=[{tr_s}:{tr_e}], test=[{te_s}:{te_e}]")

    X_train_df = features.iloc[tr_s:tr_e][feature_names]
    y_train_arr = labels[tr_s:tr_e]
    X_test_df = features.iloc[te_s:te_e][feature_names]
    y_test_arr = labels[te_s:te_e]

    print(f"  训练集: {len(X_train_df)}天, 正样本={y_train_arr.sum():.0f} ({y_train_arr.mean():.1%})")
    print(f"  测试集: {len(X_test_df)}天, 正样本={y_test_arr.sum():.0f} ({y_test_arr.mean():.1%})")

    # ========== Step5风格 ==========
    print("\n" + "=" * 80)
    print("  【方法1】Step5风格实现")
    print("=" * 80)

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train_df.values)
    X_test_scaled = scaler.transform(X_test_df.values)

    X_train_seqs, y_train_seqs = create_sequences(X_train_scaled, y_train_arr, seq_length)
    X_test_seqs, y_test_seqs = create_sequences(X_test_scaled, y_test_arr, seq_length)

    print(f"  训练序列: {X_train_seqs.shape}")
    print(f"  测试序列: {X_test_seqs.shape}")

    torch.manual_seed(42)
    np.random.seed(42)

    step5_model = Step5LSTM(hidden_dim=32, num_layers=2, dropout=0.5, weight_decay=0.01)
    t0 = time.time()
    step5_model.train(X_train_seqs, y_train_seqs, X_test_seqs, y_test_seqs,
                      epochs=15, lr=0.001, batch_size=32, patience=5)
    step5_time = time.time() - t0

    train_pred_step5 = step5_model.predict(X_train_seqs)
    test_pred_step5 = step5_model.predict(X_test_seqs)

    step5_train_auc = roc_auc_score(y_train_seqs, train_pred_step5)
    step5_test_auc = roc_auc_score(y_test_seqs, test_pred_step5)

    print(f"  Step5结果: train_auc={step5_train_auc:.4f}, test_auc={step5_test_auc:.4f}, time={step5_time:.1f}s")

    # ========== V60 LSTMModel ==========
    print("\n" + "=" * 80)
    print("  【方法2】V60 LSTMModel实现")
    print("=" * 80)

    torch.manual_seed(42)
    np.random.seed(42)

    v60_model = LSTMModel()
    t0 = time.time()
    v60_model.fit(X_train_df, pd.Series(y_train_arr, index=X_train_df.index),
                  X_val=X_test_df, y_val=pd.Series(y_test_arr, index=X_test_df.index))
    v60_time = time.time() - t0

    train_pred_v60 = v60_model.predict_proba(X_train_df)
    test_pred_v60 = v60_model.predict_proba(X_test_df)

    # 对齐序列（跳过前seq_length个）
    train_true_v60 = y_train_arr[seq_length:]
    test_true_v60 = y_test_arr[seq_length:]
    train_pred_v60_valid = train_pred_v60[seq_length:]
    test_pred_v60_valid = test_pred_v60[seq_length:]

    v60_train_auc = roc_auc_score(train_true_v60, train_pred_v60_valid)
    v60_test_auc = roc_auc_score(test_true_v60, test_pred_v60_valid)

    print(f"  V60结果: train_auc={v60_train_auc:.4f}, test_auc={v60_test_auc:.4f}, time={v60_time:.1f}s")

    # ========== 对比 ==========
    print("\n" + "=" * 80)
    print("  【对比】")
    print("=" * 80)

    print(f"\n  {'指标':<20s} {'Step5风格':>15s} {'V60 LSTMModel':>15s} {'差异':>12s}")
    print("  " + "-" * 65)
    print(f"  {'训练AUC':<20s} {step5_train_auc:>15.4f} {v60_train_auc:>15.4f} {v60_train_auc-step5_train_auc:>+12.4f}")
    print(f"  {'测试AUC':<20s} {step5_test_auc:>15.4f} {v60_test_auc:>15.4f} {v60_test_auc-step5_test_auc:>+12.4f}")
    print(f"  {'训练时间':<20s} {f'{step5_time:.1f}s':>15s} {f'{v60_time:.1f}s':>15s} {f'{v60_time-step5_time:+.1f}s':>12s}")

    # 检查模型结构是否一致
    print(f"\n  模型结构对比:")
    step5_params = sum(p.numel() for p in step5_model.model.parameters())
    v60_params = sum(p.numel() for p in v60_model.model.parameters())
    print(f"    Step5参数数量: {step5_params}")
    print(f"    V60参数数量: {v60_params}")
    print(f"    差异: {v60_params - step5_params}")

    # 检查scaler是否一致
    print(f"\n  Scaler对比:")
    print(f"    Step5 scaler mean[0]: {scaler.mean_[0]:.6f}")
    print(f"    V60 scaler mean[0]: {v60_model.scaler.mean_[0]:.6f}")
    print(f"    Step5 scaler scale[0]: {scaler.scale_[0]:.6f}")
    print(f"    V60 scaler scale[0]: {v60_model.scaler.scale_[0]:.6f}")

    print(f"\n  诊断完成！")


if __name__ == "__main__":
    main()
