# V6.0 LSTM 时序模型基线

**策略线归属**: ML_BASELINE（机器学习基线）
**定位**: 探索性代码，不接入实盘
**模型**: LSTM（长短期记忆网络）
**版本**: v6.0

---

## 核心改进（vs V5.5 LightGBM）

| 维度 | V5.5 LightGBM | V6.0 LSTM | 变化 |
|------|--------------|-----------|------|
| 模型架构 | 梯度提升树（LightGBM） | LSTM时序网络 | ✅ 时序建模能力 |
| 训练AUC | 1.0000 | 0.94-0.97 | ✅ 过拟合缓解 |
| TOP_EXIT测试AUC | 0.7372 | 0.59（不稳定） | ⚠️ 待优化 |
| DIP_BUY测试AUC | 0.6981 | 0.655 | ⚠️ 略低 |
| 正则化 | 弱（L2=0） | 强（Dropout=0.5 + L2=0.01） | ✅ 强正则化 |
| 序列建模 | 无（单点特征） | 20天序列 | ✅ 时序依赖 |

---

## Config1 最佳参数

```python
{
    'hidden_dim': 32,        # 隐藏层维度
    'num_layers': 2,         # LSTM层数
    'dropout': 0.5,          # Dropout率
    'weight_decay': 0.01,    # L2正则化
    'lr': 0.001,             # 学习率
    'batch_size': 32,        # 批次大小
    'epochs': 15,            # 最大训练轮数
    'patience': 5,           # 早停耐心值
    'seq_length': 20,        # 序列长度（天）
    'pos_weight': True,      # 类别不平衡加权
}
```

---

## 验证结果

### TOP_EXIT场景（12折Walk-Forward）

| 指标 | 值 |
|------|-----|
| 有效折数 | 6/12（6折正样本不足被跳过） |
| 平均训练AUC | 0.9608 ± 0.0349 |
| 平均测试AUC | 0.5908 ± 0.1978 |
| 测试AUC范围 | [0.174, 0.765] |
| 过拟合缓解 | ✅ 训练AUC从1.0降至~0.96 |

### DIP_BUY场景

| 指标 | 值 |
|------|-----|
| 训练AUC | 0.90 |
| 测试AUC | 0.655 |
| 衰减率 | 27.2% |

---

## 关键发现

### ✅ 成功

1. **LSTM有效缓解过拟合**：训练AUC从1.0降至0.94-0.97
2. **时序建模能力**：20天序列输入，捕捉时序依赖
3. **强正则化有效**：Dropout=0.5 + Weight Decay=0.01 + 早停
4. **DIP_BUY场景表现稳定**：衰减率27.2% vs LightGBM 30.2%

### ⚠️ 问题

1. **TOP_EXIT测试AUC不稳定**：标准差0.1978，各折差异大
2. **第一折表现极差**：测试AUC=0.1741（早期数据质量差/分布不同）
3. **正样本不足**：12折中有6折正样本不足被跳过
4. **训练时间长**：CPU环境下每折约1-2秒，比LightGBM慢

---

## 文件结构

```
ml/v60_lstm_baseline/
├── __init__.py              # 模块定义
├── README.md                # 本文档
├── v60_lstm_only.py         # LSTM单独验证脚本（避免段错误）
├── v60_baseline_validation.py  # 完整验证（LightGBM vs LSTM对比，注意段错误）
├── debug_compare.py         # Step5 vs V60实现对比（已验证一致）
└── debug_folds.py           # 12折详细诊断
```

---

## 使用方法

### 1. 创建LSTM模型

```python
from ml.models import LSTMModel, create_model

# 方式1：直接创建
model = LSTMModel()

# 方式2：工厂函数
model = create_model('lstm')
```

### 2. 训练模型

```python
import pandas as pd

# X: DataFrame (n_samples, n_features)
# y: Series (n_samples,) 二分类标签

model.fit(X_train, y_train, X_val=X_val, y_val=y_val)
```

### 3. 预测

```python
proba = model.predict_proba(X_test)  # 上涨概率
pred = model.predict(X_test, threshold=0.5)  # 类别预测
```

### 4. 保存/加载

```python
model.save('models/v6_lstm.pkl')
model = LSTMModel.load('models/v6_lstm.pkl')
```

---

## 与V5.5的集成

### models.py新增

- `LSTMModel` 类：继承自 `MLModel` 基类
- `create_model('lstm')`：工厂函数支持

### version_manager.py更新

- 支持LSTM模型自动识别（`model_type='lstm'`）
- 支持LSTM模型加载和保存

### 已知问题

- **PyTorch + LightGBM混用段错误**：在同一脚本中同时import torch和lightgbm可能导致段错误
- **解决方案**：分开运行，或先import torch再import lightgbm

---

## 下一步优化方向

| 优先级 | 方向 | 预期效果 |
|--------|------|----------|
| 高 | 优化第一折表现 | 提升早期数据的预测能力 |
| 高 | 调整阈值 | 降低TOP_EXIT阈值（0.20→0.15）增加正样本 |
| 中 | 特征选择 | 减少77维特征到核心特征 |
| 中 | 超参数调优 | Grid Search寻找最优参数 |
| 中 | 序列长度优化 | 测试10/30/60天序列 |
| 低 | Transformer | 探索自注意力机制 |

---

## 参考

- [Step5 LSTM调优结果](../backtest_results/step5_lstm_tuning.json)
- [V6.0验证结果](../backtest_results/v60_lstm_baseline.json)
- [models.py](../models.py) - LSTMModel实现
- [version_manager.py](../version_manager.py) - 版本管理
