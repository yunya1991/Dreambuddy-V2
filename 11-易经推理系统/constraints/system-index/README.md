# 系统工程索引

本目录维护系统组件索引、职责边界与依赖关系。

- 基线架构文档：`engineering-architecture.md`
- 震荡市增强器技术文档：`ranging-market-enhancer.md`
- 力学引擎技术文档：`force-engine-architecture.md`
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

### 力学引擎与多源校验层（scripts/memory_l4/bcrm/）

| 模块 | 文件 | 职责 | 依赖库 |
|------|------|------|--------|
| 力学引擎 | `force_engine.py` | 五象力场提取+Verlet辛积分+Langevin随机项+可选Kalman后处理 | numpy |
| 常量定义 | `_constants.py` | 八卦/方向/力学/Ising/TDA常量（26个新增参数） | - |
| 体量自适应 | `scale_engine.py` | 小大之辩体量参数插值（微盘→超大盘） | - |
| 卡尔曼滤波器 | `kalman_filter.py` | 速度-加速度贝叶斯状态估计，过滤市场高频噪声 | pykalman |
| Ising相变检测器 | `ising_phase_detector.py` | 二维Ising模型统计力学相变检测（Onsager精确解） | numpy |
| TDA早期预警器 | `tda_early_warning.py` | Takens嵌入+Vietoris-Rips持久同调，转折点最早预警 | ripser+persim |
| 五角校验器 | `triangle_verifier.py` | BCRM2×力学×A0×Ising×TDA五源交叉验证 | 上述全部 |

### 矛盾分析与门禁层（scripts/memory_l4/）

| 模块 | 文件 | 职责 |
|------|------|------|
| A0矛盾分析引擎 | `a0_contradiction_engine.py` | 七维矛盾分析（多空/时间/信息/流动/情绪/周期/结构）+创伤检测 |
| A7实践论门禁 | `a7_practice_gate.py` | 7项执行前检查（信号+CBR+胜率+风控+纪律+A0+三角校验） |

### 风控与状态

| 数据 | 路径 | 说明 |
|------|------|------|
| 风控状态 | `.workbuddy/memory_l4/risk/risk_state.json` | 连续亏损、日盈亏、暂停状态 |
| 置信度校准 | `data/confidence_calibration.json` | 预测-实际胜率校准表 |
| 卦象校准 | `data/hexagram_calibration.json` | 64卦方向统计 |
| 回测报告 | `data/backtest/enhancer_backtest_*.json` | 各币种回测结果 |

## 力学引擎五角校验架构速览

```
市场快照 + K线数据
  ↓
五象力场提取（时/空/表/里/流）
  ↓
加权合力计算（体量自适应权重）
  ↓
Verlet辛积分 + Langevin随机项 [P0]
  ↓
[可选] 卡尔曼滤波平滑 [P1]
  ↓
趋势判定 + 转折预警 + 置信度
  ↓
五角校验 [P1+P2]:
  BCRM2(ML) × 力学(物理) × A0(矛盾) × Ising(相变) × TDA(拓扑)
  ↓
一致性评分 + 置信度调整 + 三层预警(TDA最早→Ising中期→力学确认)
```

三层预警时序：TDA拓扑突变（最早）→ Ising相变（中期）→ 力学引擎减速（确认）
