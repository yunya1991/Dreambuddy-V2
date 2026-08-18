"""Step 5: LSTM/Transformer时序模型验证（PyTorch环境诊断版）

目标：使用时序模型替代LightGBM，解决训练AUC=1.0的过拟合问题

策略：
- 独立运行，避免与lightgbm混用导致段错误
- LSTM + Transformer对比
- Walk-Forward 12折验证

用法：
    cd 12-三屏趋势系统
    python ml/v55_baseline/step5_lstm_transformer.py
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

# 必须在import lightgbm之前import torch，避免段错误
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

# torch导入后再导入自定义模块
from ml.feature_engineer import TrendFeatureEngineer
from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer


# ============ 数据加载 ============

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
    """创建时序样本: (n_samples, seq_length, n_features)"""
    X, y = [], []
    n = len(features_arr)
    for i in range(seq_length, n):
        X.append(features_arr[i-seq_length:i])
        y.append(labels[i])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


# ============ LSTM模型 ============

class LSTMModel(nn.Module):
    def __init__(self, input_dim, hidden_dim=64, num_layers=2, dropout=0.3):
        super(LSTMModel, self).__init__()
        self.lstm = nn.LSTM(
            input_dim, hidden_dim, num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 1),
            nn.Sigmoid()
        )
    
    def forward(self, x):
        out, _ = self.lstm(x)
        out = out[:, -1, :]
        return self.fc(out).squeeze()


class TransformerModel(nn.Module):
    """简化版Transformer"""
    def __init__(self, input_dim, d_model=64, nhead=4, num_layers=2, dropout=0.3):
        super(TransformerModel, self).__init__()
        self.input_embedding = nn.Linear(input_dim, d_model)
        
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=128,
            dropout=dropout, batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        
        self.fc = nn.Sequential(
            nn.Linear(d_model, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 1),
            nn.Sigmoid()
        )
    
    def forward(self, x):
        x = self.input_embedding(x)
        x = self.transformer(x)
        x = x[:, -1, :]
        return self.fc(x).squeeze()


# ============ 训练函数 ============

def train_model(model, X_train, y_train, X_val, y_val, epochs=30, lr=0.001, batch_size=32, patience=5):
    """训练PyTorch模型，带早停"""
    device = torch.device('cpu')
    model = model.to(device)
    
    criterion = nn.BCELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)
    
    # 处理类别不平衡：加权损失
    pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    pos_weight_tensor = torch.tensor([pos_weight], dtype=torch.float32)
    
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
            # 加权BCE
            weight = torch.where(y_batch > 0.5, pos_weight_tensor, torch.ones_like(y_batch))
            loss = nn.functional.binary_cross_entropy(outputs, y_batch, weight=weight)
            loss.backward()
            optimizer.step()
        
        # 验证
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
    """评估模型，返回AUC"""
    model.eval()
    with torch.no_grad():
        preds = model(torch.FloatTensor(X)).numpy()
    
    if len(set(y)) > 1:
        return roc_auc_score(y, preds)
    return 0.5


# ============ Walk-Forward验证 ============

def walk_forward(features_arr, labels, model_type='lstm', seq_length=20,
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
    
    print(f"    {model_type.upper()}训练: {len(splits)}折, 序列长度={seq_length}")
    
    input_dim = features_arr.shape[1]
    
    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        # 创建序列样本
        X_train, y_train = create_sequences(features_arr[tr_s:tr_e], labels[tr_s:tr_e], seq_length)
        X_test, y_test = create_sequences(features_arr[te_s:te_e], labels[te_s:te_e], seq_length)
        
        if len(X_train) < 50 or len(X_test) < 10:
            continue
        
        # 标签多样性检查
        if y_train.sum() < 3 or y_test.sum() < 2:
            continue
        
        # 创建模型
        if model_type == 'lstm':
            model = LSTMModel(input_dim, hidden_dim=64, num_layers=2, dropout=0.3)
        else:
            model = TransformerModel(input_dim, d_model=64, nhead=4, num_layers=2, dropout=0.3)
        
        # 训练
        model = train_model(model, X_train, y_train, X_test, y_test,
                           epochs=30, lr=0.001, batch_size=32, patience=5)
        
        # 评估
        train_auc = evaluate_model(model, X_train, y_train)
        test_auc = evaluate_model(model, X_test, y_test)
        
        train_aucs.append(train_auc)
        test_aucs.append(test_auc)
        
        if (i + 1) % 3 == 0:
            print(f"      折{i+1}/{len(splits)}: train={train_auc:.4f}, test={test_auc:.4f}")
    
    avg_test = float(np.mean(test_aucs)) if test_aucs else 0.0
    avg_train = float(np.mean(train_aucs)) if train_aucs else 0.0
    decay = 1.0 - (avg_test / avg_train) if avg_train > 0 else 0.0
    
    return avg_test, avg_train, float(decay)


# ============ 主函数 ============

def main():
    print("=" * 80)
    print("  Step 5: LSTM/Transformer时序模型验证")
    print("  目标：解决训练AUC=1.0的过拟合问题")
    print("=" * 80)
    
    # 环境信息
    print(f"\n  PyTorch版本: {torch.__version__}")
    print(f"  设备: CPU")
    
    # 加载数据
    prices = load_btc_data()
    closes = prices["close"].values
    n = len(prices)
    print(f"\n  BTC日线: {n}天")
    
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
    print(f"  特征计算耗时: {time.time() - t0:.1f}s")
    
    # 标准化
    scaler = StandardScaler()
    features_arr = scaler.fit_transform(features[feature_names]).astype(np.float32)
    
    # 标签
    top_exit_labels = generate_labels(closes, 20, 0.20, "drop")
    dip_buy_labels = generate_labels(closes, 20, 0.15, "rise")
    
    pos_pct_top = top_exit_labels.sum() / n * 100
    pos_pct_dip = dip_buy_labels.sum() / n * 100
    print(f"  TOP_EXIT正样本: {pos_pct_top:.1f}%")
    print(f"  DIP_BUY正样本: {pos_pct_dip:.1f}%")
    
    # ========== LSTM验证 ==========
    print("\n" + "=" * 80)
    print("  【模型1】LSTM - TOP_EXIT")
    print("=" * 80)
    
    t0 = time.time()
    lstm_top_test, lstm_top_train, lstm_top_decay = walk_forward(
        features_arr, top_exit_labels, model_type='lstm', seq_length=20
    )
    lstm_top_time = time.time() - t0
    
    print(f"\n  LSTM TOP_EXIT结果:")
    print(f"    训练AUC: {lstm_top_train:.4f}")
    print(f"    测试AUC: {lstm_top_test:.4f}")
    print(f"    衰减率:  {lstm_top_decay:.1%}")
    print(f"    训练耗时: {lstm_top_time:.1f}s")
    
    # ========== Transformer验证 ==========
    print("\n" + "=" * 80)
    print("  【模型2】Transformer - TOP_EXIT")
    print("=" * 80)
    
    t0 = time.time()
    trans_top_test, trans_top_train, trans_top_decay = walk_forward(
        features_arr, top_exit_labels, model_type='transformer', seq_length=20
    )
    trans_top_time = time.time() - t0
    
    print(f"\n  Transformer TOP_EXIT结果:")
    print(f"    训练AUC: {trans_top_train:.4f}")
    print(f"    测试AUC: {trans_top_test:.4f}")
    print(f"    衰减率:  {trans_top_decay:.1%}")
    print(f"    训练耗时: {trans_top_time:.1f}s")
    
    # ========== LSTM DIP_BUY验证 ==========
    print("\n" + "=" * 80)
    print("  【模型3】LSTM - DIP_BUY")
    print("=" * 80)
    
    t0 = time.time()
    lstm_dip_test, lstm_dip_train, lstm_dip_decay = walk_forward(
        features_arr, dip_buy_labels, model_type='lstm', seq_length=20
    )
    lstm_dip_time = time.time() - t0
    
    print(f"\n  LSTM DIP_BUY结果:")
    print(f"    训练AUC: {lstm_dip_train:.4f}")
    print(f"    测试AUC: {lstm_dip_test:.4f}")
    print(f"    衰减率:  {lstm_dip_decay:.1%}")
    print(f"    训练耗时: {lstm_dip_time:.1f}s")
    
    # ========== 对比分析（含LightGBM基线）==========
    print("\n" + "=" * 80)
    print("  【对比分析】")
    print("=" * 80)
    
    # LightGBM基线（从之前的Step4结果）
    lgb_top_test, lgb_top_train, lgb_top_decay = 0.7372, 1.0000, 0.263
    lgb_dip_test, lgb_dip_train, lgb_dip_decay = 0.6981, 1.0000, 0.302
    
    print(f"\n  TOP_EXIT场景:")
    print(f"  {'模型':<15s} {'训练AUC':>10s} {'测试AUC':>10s} {'衰减率':>8s} {'训练耗时':>10s}")
    print("  " + "-" * 60)
    print(f"  {'LightGBM':<15s} {lgb_top_train:>10.4f} {lgb_top_test:>10.4f} {lgb_top_decay:>8.1%} {'~2s':>10s}")
    print(f"  {'LSTM':<15s} {lstm_top_train:>10.4f} {lstm_top_test:>10.4f} {lstm_top_decay:>8.1%} {lstm_top_time:>10.1f}s")
    print(f"  {'Transformer':<15s} {trans_top_train:>10.4f} {trans_top_test:>10.4f} {trans_top_decay:>8.1%} {trans_top_time:>10.1f}s")
    
    print(f"\n  DIP_BUY场景:")
    print(f"  {'模型':<15s} {'训练AUC':>10s} {'测试AUC':>10s} {'衰减率':>8s} {'训练耗时':>10s}")
    print("  " + "-" * 60)
    print(f"  {'LightGBM':<15s} {lgb_dip_train:>10.4f} {lgb_dip_test:>10.4f} {lgb_dip_decay:>8.1%} {'~2s':>10s}")
    print(f"  {'LSTM':<15s} {lstm_dip_train:>10.4f} {lstm_dip_test:>10.4f} {lstm_dip_decay:>8.1%} {lstm_dip_time:>10.1f}s")
    
    # ========== 结论 ==========
    print("\n" + "=" * 80)
    print("  【结论】")
    print("=" * 80)
    
    # 训练AUC降低情况
    lstm_train_reduce = lgb_top_train - lstm_top_train
    trans_train_reduce = lgb_top_train - trans_top_train
    
    print(f"\n  训练AUC降低情况（LightGBM=1.0000）:")
    print(f"    LSTM:        {lstm_top_train:.4f} (降低{lstm_train_reduce:.4f})")
    print(f"    Transformer: {trans_top_train:.4f} (降低{trans_train_reduce:.4f})")
    
    # 测试AUC对比
    print(f"\n  测试AUC对比（TOP_EXIT）:")
    print(f"    LightGBM:    {lgb_top_test:.4f}")
    print(f"    LSTM:        {lstm_top_test:.4f} (变化{lstm_top_test-lgb_top_test:+.4f})")
    print(f"    Transformer: {trans_top_test:.4f} (变化{trans_top_test-lgb_top_test:+.4f})")
    
    # 过拟合缓解判断
    lstm_overfit_resolved = lstm_top_train < 0.95
    trans_overfit_resolved = trans_top_train < 0.95
    
    print(f"\n  过拟合缓解情况（目标: 训练AUC<0.95）:")
    print(f"    LSTM: {'✅ 是' if lstm_overfit_resolved else '❌ 否'} (训练AUC={lstm_top_train:.4f})")
    print(f"    Transformer: {'✅ 是' if trans_overfit_resolved else '❌ 否'} (训练AUC={trans_top_train:.4f})")
    
    # 推荐最佳模型
    best_model = "LSTM" if lstm_top_test > trans_top_test else "Transformer"
    best_test = max(lstm_top_test, trans_top_test)
    best_overfit = lstm_overfit_resolved if best_model == "LSTM" else trans_overfit_resolved
    
    print(f"\n  【推荐】")
    if lstm_overfit_resolved or trans_overfit_resolved:
        print(f"  ✅ 时序模型有效缓解过拟合")
        print(f"     推荐: {best_model}")
        print(f"     训练AUC: {lstm_top_train if best_model == 'LSTM' else trans_top_train:.4f}")
        print(f"     测试AUC: {best_test:.4f}")
        
        if best_test > lgb_top_test:
            print(f"  ✅ 测试AUC也提升: {best_test:.4f} > {lgb_top_test:.4f}")
        else:
            print(f"  🟡 测试AUC未提升: {best_test:.4f} < {lgb_top_test:.4f}")
            print(f"     但过拟合显著缓解，可继续调优")
    else:
        print(f"  🟡 时序模型训练AUC仍较高，需要进一步调优")
        print(f"     建议: 增加dropout、减小hidden_dim、加大L1/L2正则化")
    
    # 保存结果
    output = {
        "step": "step5_lstm_transformer",
        "analysis_date": str(pd.Timestamp.now()),
        "pytorch_version": torch.__version__,
        "lightgbm_baseline": {
            "top_exit": {"train_auc": lgb_top_train, "test_auc": lgb_top_test, "decay": lgb_top_decay},
            "dip_buy": {"train_auc": lgb_dip_train, "test_auc": lgb_dip_test, "decay": lgb_dip_decay},
        },
        "lstm": {
            "top_exit": {
                "train_auc": lstm_top_train, "test_auc": lstm_top_test, "decay": lstm_top_decay,
                "train_time": lstm_top_time,
            },
            "dip_buy": {
                "train_auc": lstm_dip_train, "test_auc": lstm_dip_test, "decay": lstm_dip_decay,
                "train_time": lstm_dip_time,
            },
        },
        "transformer": {
            "top_exit": {
                "train_auc": trans_top_train, "test_auc": trans_top_test, "decay": trans_top_decay,
                "train_time": trans_top_time,
            },
        },
        "conclusion": {
            "lstm_overfit_resolved": lstm_overfit_resolved,
            "trans_overfit_resolved": trans_overfit_resolved,
            "best_model": best_model,
            "best_test_auc": best_test,
        },
    }
    
    output_path = os.path.join(BASE_DIR, "ml/backtest_results/step5_lstm_transformer.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存: {output_path}")


if __name__ == "__main__":
    main()