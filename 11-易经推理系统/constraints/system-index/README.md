# 系统工程索引

本目录维护系统组件索引、职责边界与依赖关系。

- 基线架构文档：`engineering-architecture.md`
- 震荡市增强器技术文档：`ranging-market-enhancer.md`
- QMM 量化内核约束（可插拔，固定输出契约）：`constraints/qmm/`
- QMM 双轨策略执行计划（研究域与工程域隔离）：`constraints/qmm/execution-plan.md`

## 核心模块索引

### 交易执行层（scripts/memory_l4/）

| 模块 | 文件 | 职责 |
|------|------|------|
| 轮询交易器 | `polling_trader.py` | 主交易循环，集成BCRM2推理+增强器+风控 |
| 震荡市增强器 | `ranging_market_enhancer.py` | 5项优化统一入口（MA200偏向+布林确认+动态止损+置信度校准+状态自适应） |
| 回测引擎 | `enhancer_backtest_engine.py` | 基础策略 vs 增强策略对比回测 |
| 交易工具 | `trading_utils.py` | TradeRecord、RiskManager、持仓管理 |
| 易经监控 | `yijing_monitor.py` | 运行状态监控+飞书告警 |
| 飞书告警 | `yijing_feishu_alert.py` | 交易暂停、开仓、平仓通知 |

### 推理引擎层（scripts/memory_l4/bcrm2/）

| 模块 | 文件 | 职责 |
|------|------|------|
| BCRM2适配器 | `bcrm2_adapter.py` | BCRM2.0推理引擎适配层 |
| 辩证ML引擎 | `dialectical_ml_engine.py` | LightGBM+辩证特征推理 |
| 八卦特征引擎 | `bagua_feature_engine.py` | 64卦特征提取 |
| 增量学习器 | `incremental_learner.py` | 在线增量学习 |
| 市场状态识别 | `market_regime.py` | 市场环境分类 |

### 风控与状态

| 数据 | 路径 | 说明 |
|------|------|------|
| 风控状态 | `.workbuddy/memory_l4/risk/risk_state.json` | 连续亏损、日盈亏、暂停状态 |
| 置信度校准 | `data/confidence_calibration.json` | 预测-实际胜率校准表 |
| 卦象校准 | `data/hexagram_calibration.json` | 64卦方向统计 |
| 回测报告 | `data/backtest/enhancer_backtest_*.json` | 各币种回测结果 |
