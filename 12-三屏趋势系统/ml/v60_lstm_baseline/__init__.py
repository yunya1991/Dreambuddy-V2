"""V6.0 LSTM 时序模型基线

策略线归属：[ML_BASELINE] 机器学习基线
定位：探索性代码，不接入实盘
模型：LSTM（Config1参数）- 缓解过拟合，提升测试AUC

核心改进（vs V5.5 LightGBM）：
- 模型架构：LightGBM → LSTM时序模型
- 过拟合：训练AUC 1.0 → 0.97（缓解）
- TOP_EXIT测试AUC：0.7372 → 0.7455（+0.0083）
- 正则化：Dropout=0.5 + WeightDecay=0.01 + 早停

参见：docs/STRATEGY_LINES.md 策略线管理总纲
"""

VERSION = "v6.0"
MODEL_TYPE = "lstm"
DESCRIPTION = "V6.0 LSTM时序模型基线（Config1参数）"
