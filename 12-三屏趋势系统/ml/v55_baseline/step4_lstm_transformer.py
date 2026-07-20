"""Step 4: LSTM/Transformer时序模型验证

目标：使用时序模型替代LightGBM，解决训练AUC=1.0的过拟合问题

策略：
- LSTM：长短期记忆网络，通过门控机制减少过拟合
- Transformer：自注意力机制，捕捉长距离依赖
- 对比：LightGBM（严重过拟合） vs LSTM vs Transformer

预期效果：
- 训练AUC显著降低（目标<0.95）
- 测试AUC提升或持平
- 过拟合衰减率降低

验证方式：Walk-Forward (12折)
对比指标：训练AUC, 测试AUC, 衰减率

用法：
    cd 12-三屏趋势系统
    python ml/v55_baseline/step4_lstm_transformer.py
    
依赖：
    pip install torch
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

# PyTorch
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

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


def create_sequences(features, labels, seq_length):
    """创建时序样本
    
    Args:
        features: 特征DataFrame
        labels: 标签数组
        seq_length: 序列长度（使用过去seq_length天的特征预测）
    
    Returns:
        X: (n_samples, seq_length, n_features)
        y: (n_samples,)
    """
    X, y = [], []
    n = len(features)
    
    for i in range(seq_length, n):
        X.append(features.iloc[i-seq_length:i].values)
        y.append(labels[i])
    
    return np.array(X), np.array(y)


# ============ LSTM模型 ============

class LSTMModel(nn.Module):
    """LSTM二分类模型
    
    架构：
    - LSTM层：捕捉时序依赖
    - 全连接层：二分类输出
    """
    def __init__(self, input_dim, hidden_dim=64, num_layers=2, dropout=0.3):
        super(LSTMModel, self).__init__()
        
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        
        # LSTM层
        self.lstm = nn.LSTM(
            input_dim, hidden_dim, num_layers,
            batch_first=True, dropout=dropout if num_layers > 1 else 0
        )
        
        # 全连接层
        self.fc1 = nn.Linear(hidden_dim, 32)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(dropout)
        self.fc2 = nn.Linear(32, 1)
        self.sigmoid = nn.Sigmoid()
    
    def forward(self, x):
        # LSTM
        lstm_out, _ = self.lstm(x)  # (batch, seq_len, hidden_dim)
        
        # 取最后一个时间步
        lstm_out = lstm_out[:, -1, :]  # (batch, hidden_dim)
        
        # 全连接
        out = self.fc1(lstm_out)
        out = self.relu(out)
        out = self.dropout(out)
        out = self.fc2(out)
        out = self.sigmoid(out)
        
        return out.squeeze()


# ============ Transformer模型 ============

class TransformerModel(nn.Module):
    """Transformer二分类模型
    
    架构：
    - 位置编码
    - Transformer Encoder层
    - 全连接层
    """
    def __init__(self, input_dim, d_model=64, nhead=4, num_layers=2, dropout=0.3):
        super(TransformerModel, self).__init__()
        
        self.d_model = d_model
        
        # 输入嵌入
        self.input_embedding = nn.Linear(input_dim, d_model)
        
        # 位置编码（简化版）
        self.pos_encoder = PositionalEncoding(d_model, dropout)
        
        # Transformer Encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=128, dropout=dropout, batch_first=True
        )
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        
        # 全连接层
        self.fc1 = nn.Linear(d_model, 32)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(dropout)
        self.fc2 = nn.Linear(32, 1)
        self.sigmoid = nn.Sigmoid()
    
    def forward(self, x):
        # 输入嵌入
        x = self.input_embedding(x)  # (batch, seq_len, d_model)
        
        # 位置编码
        x = self.pos_encoder(x)
        
        # Transformer Encoder
        x = self.transformer_encoder(x)  # (batch, seq_len, d_model)
        
        # 取最后一个时间步
        x = x[:, -1, :]  # (batch, d_model)
        
        # 全连接
        out = self.fc1(x)
        out = self.relu(out)
        out = self.dropout(out)
        out = self.fc2(out)
        out = self.sigmoid(out)
        
        return out.squeeze()


class PositionalEncoding(nn.Module):
    """位置编码"""
    def __init__(self, d_model, dropout=0.1, max_len=100):
        super(PositionalEncoding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)
        
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)  # (1, max_len, d_model)
        self.register_buffer('pe', pe)
    
    def forward(self, x):
        # x: (batch, seq_len, d_model)
        x = x + self.pe[:, :x.size(1), :]
        return self.dropout(x)


def train_pytorch_model(model, train_loader, val_loader, epochs=50, lr=0.001, patience=5):
    """训练PyTorch模型
    
    Args:
        model: PyTorch模型
        train_loader: 训练数据加载器
        val_loader: 验证数据加载器
        epochs: 最大训练轮数
        lr: 学习率
        patience: 早停耐心值
    
    Returns:
        model: 训练好的模型
        train_loss: 训练损失历史
        val_loss: 验证损失历史
    """
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = model.to(device)
    
    criterion = nn.BCELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)
    
    train_loss_history = []
    val_loss_history = []
    best_val_loss = float('inf')
    patience_counter = 0
    
    for epoch in range(epochs):
        # 训练
        model.train()
        train_loss = 0.0
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
            
            optimizer.zero_grad()
            outputs = model(X_batch)
            loss = criterion(outputs, y_batch)
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item()
        
        train_loss /= len(train_loader)
        train_loss_history.append(train_loss)
        
        # 验证
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for X_batch, y_batch in val_loader:
                X_batch, y_batch = X_batch.to(device), y_batch.to(device)
                outputs = model(X_batch)
                loss = criterion(outputs, y_batch)
                val_loss += loss.item()
        
        val_loss /= len(val_loader)
        val_loss_history.append(val_loss)
        
        # 早停
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            best_model_state = model.state_dict()
        else:
            patience_counter += 1
            if patience_counter >= patience:
                break
    
    # 加载最佳模型
    model.load_state_dict(best_model_state)
    
    return model, train_loss_history, val_loss_history


def evaluate_pytorch_model(model, data_loader):
    """评估PyTorch模型
    
    Returns:
        auc: AUC值
        predictions: 预测概率
        labels: 真实标签
    """
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = model.to(device)
    model.eval()
    
    all_preds = []
    all_labels = []
    
    with torch.no_grad():
        for X_batch, y_batch in data_loader:
            X_batch = X_batch.to(device)
            outputs = model(X_batch)
            all_preds.extend(outputs.cpu().numpy())
            all_labels.extend(y_batch.numpy())
    
    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)
    
    if len(set(all_labels)) > 1:
        auc = roc_auc_score(all_labels, all_preds)
    else:
        auc = 0.5
    
    return auc, all_preds, all_labels


def walk_forward_lstm(features, labels, feature_names,
                       seq_length=20, n_splits=12, train_days=730, test_days=180, step_days=180):
    """LSTM Walk-Forward验证"""
    n = len(features)
    train_aucs, test_aucs = [], []
    
    # 标准化
    scaler = StandardScaler()
    features_scaled = pd.DataFrame(scaler.fit_transform(features[feature_names]), 
                                    columns=feature_names, index=features.index)
    
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
    
    print(f"    LSTM训练: {len(splits)}折, 序列长度{seq_length}")
    
    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        # 创建序列样本
        X_train, y_train = create_sequences(features_scaled.iloc[tr_s:tr_e], labels[tr_s:tr_e], seq_length)
        X_test, y_test = create_sequences(features_scaled.iloc[te_s:te_e], labels[te_s:te_e], seq_length)
        
        if len(X_train) < 50 or len(X_test) < 10:
            continue
        
        # 转换为PyTorch张量
        X_train_t = torch.FloatTensor(X_train)
        y_train_t = torch.FloatTensor(y_train)
        X_test_t = torch.FloatTensor(X_test)
        y_test_t = torch.FloatTensor(y_test)
        
        # 数据加载器
        train_dataset = TensorDataset(X_train_t, y_train_t)
        test_dataset = TensorDataset(X_test_t, y_test_t)
        train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
        test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)
        
        # 创建模型
        input_dim = len(feature_names)
        model = LSTMModel(input_dim, hidden_dim=64, num_layers=2, dropout=0.3)
        
        # 训练
        model, _, _ = train_pytorch_model(model, train_loader, test_loader, epochs=30, lr=0.001, patience=5)
        
        # 评估
        train_auc, _, _ = evaluate_pytorch_model(model, train_loader)
        test_auc, _, _ = evaluate_pytorch_model(model, test_loader)
        
        train_aucs.append(train_auc)
        test_aucs.append(test_auc)
    
    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0
    
    return avg_test, avg_train, float(decay)


def walk_forward_transformer(features, labels, feature_names,
                               seq_length=20, n_splits=12, train_days=730, test_days=180, step_days=180):
    """Transformer Walk-Forward验证"""
    n = len(features)
    train_aucs, test_aucs = [], []
    
    # 标准化
    scaler = StandardScaler()
    features_scaled = pd.DataFrame(scaler.fit_transform(features[feature_names]), 
                                    columns=feature_names, index=features.index)
    
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
    
    print(f"    Transformer训练: {len(splits)}折, 序列长度{seq_length}")
    
    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        # 创建序列样本
        X_train, y_train = create_sequences(features_scaled.iloc[tr_s:tr_e], labels[tr_s:tr_e], seq_length)
        X_test, y_test = create_sequences(features_scaled.iloc[te_s:te_e], labels[te_s:te_e], seq_length)
        
        if len(X_train) < 50 or len(X_test) < 10:
            continue
        
        # 转换为PyTorch张量
        X_train_t = torch.FloatTensor(X_train)
        y_train_t = torch.FloatTensor(y_train)
        X_test_t = torch.FloatTensor(X_test)
        y_test_t = torch.FloatTensor(y_test)
        
        # 数据加载器
        train_dataset = TensorDataset(X_train_t, y_train_t)
        test_dataset = TensorDataset(X_test_t, y_test_t)
        train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
        test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)
        
        # 创建模型
        input_dim = len(feature_names)
        model = TransformerModel(input_dim, d_model=64, nhead=4, num_layers=2, dropout=0.3)
        
        # 训练
        model, _, _ = train_pytorch_model(model, train_loader, test_loader, epochs=30, lr=0.001, patience=5)
        
        # 评估
        train_auc, _, _ = evaluate_pytorch_model(model, train_loader)
        test_auc, _, _ = evaluate_pytorch_model(model, test_loader)
        
        train_aucs.append(train_auc)
        test_aucs.append(test_auc)
    
    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0
    
    return avg_test, avg_train, float(decay)


def walk_forward_lightgbm(features, labels, feature_names,
                            n_splits=12, train_days=730, test_days=180, step_days=180):
    """LightGBM对比验证（基线）"""
    import lightgbm as lgb
    
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


def main():
    print("=" * 80)
    print("  Step 4: LSTM/Transformer时序模型验证")
    print("  目标：解决训练AUC=1.0的过拟合问题")
    print("=" * 80)
    
    # 检查PyTorch
    print(f"\n  PyTorch版本: {torch.__version__}")
    print(f"  设备: {'cuda' if torch.cuda.is_available() else 'cpu'}")
    
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
    
    # 移除冗余特征
    redundant_features = ["dip_buy_level", "dip_buy_position_ratio", "left_side_buy_signal"]
    v55_names = list(phil_features.columns)
    v56_names = [f for f in v55_names if f not in redundant_features]
    
    features = pd.concat([trend_features, phil_features[v56_names]], axis=1).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    feature_names = list(features.columns)
    
    print(f"  特征维度: {len(feature_names)}")
    print(f"  计算耗时: {time.time() - t0:.1f}s")
    
    # 标签
    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    
    # ========== LightGBM基线 ==========
    print("\n" + "=" * 80)
    print("  【模型1】LightGBM（基线）")
    print("=" * 80)
    
    t0 = time.time()
    lgb_test, lgb_train, lgb_decay = walk_forward_lightgbm(features, top_exit_labels, feature_names)
    lgb_time = time.time() - t0
    
    print(f"\n  TOP_EXIT: 测试AUC={lgb_test:.4f}, 训练AUC={lgb_train:.4f}, 衰减={lgb_decay:.1%}")
    print(f"  训练耗时: {lgb_time:.1f}s")
    print(f"  ⚠️ 问题: 训练AUC={lgb_train:.4f}，严重过拟合")
    
    # ========== LSTM ==========
    print("\n" + "=" * 80)
    print("  【模型2】LSTM")
    print("=" * 80)
    
    t0 = time.time()
    lstm_test, lstm_train, lstm_decay = walk_forward_lstm(features, top_exit_labels, feature_names, seq_length=20)
    lstm_time = time.time() - t0
    
    print(f"\n  TOP_EXIT: 测试AUC={lstm_test:.4f}, 训练AUC={lstm_train:.4f}, 衰减={lstm_decay:.1%}")
    print(f"  训练耗时: {lstm_time:.1f}s")
    
    # ========== Transformer ==========
    print("\n" + "=" * 80)
    print("  【模型3】Transformer")
    print("=" * 80)
    
    t0 = time.time()
    trans_test, trans_train, trans_decay = walk_forward_transformer(features, top_exit_labels, feature_names, seq_length=20)
    trans_time = time.time() - t0
    
    print(f"\n  TOP_EXIT: 测试AUC={trans_test:.4f}, 训练AUC={trans_train:.4f}, 衰减={trans_decay:.1%}")
    print(f"  训练耗时: {trans_time:.1f}s")
    
    # ========== 对比分析 ==========
    print("\n" + "=" * 80)
    print("  【对比分析】")
    print("=" * 80)
    
    print(f"\n  {'模型':<20s} {'训练AUC':>12s} {'测试AUC':>12s} {'衰减率':>10s} {'训练耗时':>10s}")
    print("  " + "-" * 70)
    print(f"  {'LightGBM（基线）':<20s} {lgb_train:>12.4f} {lgb_test:>12.4f} {lgb_decay:>10.1%} {lgb_time:>10.1f}s")
    print(f"  {'LSTM':<20s} {lstm_train:>12.4f} {lstm_test:>12.4f} {lstm_decay:>10.1%} {lstm_time:>10.1f}s")
    print(f"  {'Transformer':<20s} {trans_train:>12.4f} {trans_test:>12.4f} {trans_decay:>10.1%} {trans_time:>10.1f}s")
    
    # 判断结果
    print("\n" + "=" * 80)
    print("  【结论】")
    print("=" * 80)
    
    # 检查训练AUC是否降低
    lstm_improve = lstm_train < 0.95
    trans_improve = trans_train < 0.95
    
    if lstm_improve or trans_improve:
        print(f"\n  ✅ 时序模型有效降低训练AUC:")
        if lstm_improve:
            print(f"     LSTM: 训练AUC={lstm_train:.4f}（vs LightGBM {lgb_train:.4f}）")
        if trans_improve:
            print(f"     Transformer: 训练AUC={trans_train:.4f}（vs LightGBM {lgb_train:.4f}）")
    
    # 检查测试AUC
    best_model = "LSTM" if lstm_test > trans_test else "Transformer"
    best_test = max(lstm_test, trans_test)
    
    if best_test > lgb_test:
        print(f"\n  ✅ 测试AUC提升: {best_model} AUC={best_test:.4f}（vs LightGBM {lgb_test:.4f}）")
    else:
        print(f"\n  ⚠️ 测试AUC未提升: 最佳={best_test:.4f}（vs LightGBM {lgb_test:.4f}）")
    
    # 推荐
    print(f"\n  【推荐】: {best_model}")
    print(f"     训练AUC降低: {'是' if (lstm_improve if best_model == 'LSTM' else trans_improve) else '否'}")
    print(f"     测试AUC: {best_test:.4f}")
    print(f"     过拟合衰减: {(lstm_decay if best_model == 'LSTM' else trans_decay):.1%}")
    
    # 保存结果
    output = {
        "step": "step4_lstm_transformer",
        "analysis_date": str(pd.Timestamp.now()),
        "lightgbm": {
            "train_auc": lgb_train,
            "test_auc": lgb_test,
            "decay": lgb_decay,
            "train_time": lgb_time,
        },
        "lstm": {
            "train_auc": lstm_train,
            "test_auc": lstm_test,
            "decay": lstm_decay,
            "train_time": lstm_time,
        },
        "transformer": {
            "train_auc": trans_train,
            "test_auc": trans_test,
            "decay": trans_decay,
            "train_time": trans_time,
        },
        "comparison": {
            "best_model": best_model,
            "lstm_train_reduce": lgb_train - lstm_train,
            "trans_train_reduce": lgb_train - trans_train,
        },
        "conclusion": "success" if best_test > lgb_test else "partial" if (lstm_improve or trans_improve) else "failed",
    }
    
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/step4_lstm_transformer.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存: {output_path}")
    
    return output


if __name__ == "__main__":
    main()