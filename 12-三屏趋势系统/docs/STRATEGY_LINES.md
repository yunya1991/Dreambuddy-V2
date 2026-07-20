# 策略线管理总纲

> **版本**: v1.0 | **更新日期**: 2026-07-19
> **适用范围**: 12-三屏趋势系统 全部策略代码
> **核心原则**: 主副策略线物理隔离，禁止串味，独立演进

---

## 1. 双线策略架构

三屏趋势系统维护两条可持续演进的策略线，互不干扰、独立优化、统一对比。

### 1.1 策略线定义

| 策略线 | 代号 | 定位 | 用途 | 状态 |
|--------|------|------|------|------|
| **主策略线** | `MAIN` | V4 + 波浪互斥融合 | 实盘交易、生产部署 | ✅ 生产 |
| **机器学习基线** | `ML_BASELINE` | V5.5 LightGBM 特征工程 | 探索验证、特征工程实验 | 🔬 实验 |

### 1.2 策略线对比

| 维度 | 主策略线 (MAIN) | 机器学习基线 (ML_BASELINE) |
|------|------------------|---------------------------|
| **核心算法** | V4 减半周期 + 波浪互斥融合 | LightGBM + Walk-Forward |
| **入口文件** | `engine.py` → `compute_trend_signal_from_dataframes()` | `ml/v55_baseline/` 下验证脚本 |
| **主策略文件** | `ml/halving_top_exit_strategy.py` | `ml/philosophy_feature_engineer.py` |
| **特征工程** | 无（纯规则+物理） | 28维哲学特征 + 价格特征 |
| **回测年化（BTC 9年）** | **56.43%** | 4.31% |
| **回测夏普** | **1.4112** | 0.3024 |
| **回测回撤** | **-43.31%** | -56.48% |
| **实盘部署** | ✅ 已部署 | ❌ 仅实验 |
| **当前问题** | 无（持续优化中） | 严重过拟合，需重新设计特征工程 |

### 1.3 策略线演进原则

```
主策略线 (MAIN):
  - 持续优化 V4 减半周期参数
  - 优化波浪识别和互斥融合规则
  - 优化物理置信度调节
  - 任何变更必须通过 9年回测验证 ≥ 纯V4基线

机器学习基线 (ML_BASELINE):
  - 重新设计特征工程解决过拟合
  - 探索新的标签生成策略
  - 探索新的模型架构（如时序模型）
  - 任何变更必须通过 Walk-Forward 验证
  - 验证通过后可申请晋升为主策略线
```

---

## 2. 代码隔离规则

### 2.1 文件归属分类

所有 `ml/` 下的文件分为三类：

| 类别 | 标签 | 说明 | 修改规则 |
|------|------|------|----------|
| 主线代码 | `[MAIN]` | V4+波浪+物理，实盘部署 | ⚠️ 修改需回测验证，禁止引入 ML 依赖 |
| 副线代码 | `[ML_BASELINE]` | V5.5 ML 探索性代码 | 🔬 自由修改，禁止反向影响主线 |
| 共享基础设施 | `[SHARED]` | 被两条线共同依赖 | ⚠️ 修改需同时验证两条线 |

### 2.2 隔离纪律

**主线代码（MAIN）禁止**：
- ❌ 引入 LightGBM/XGBoost 等 ML 模型依赖
- ❌ 引入 `philosophy_feature_engineer.py` 等 V5.5 特征工程
- ❌ 引入 `v51_*/v52_*/v53_*/v54_*/v55_*` 验证脚本
- ❌ 在 `engine.py` 主路径中调用 V5.5 ML 推理

**副线代码（ML_BASELINE）禁止**：
- ❌ 修改 `engine.py` 的主决策路径
- ❌ 修改 `halving_top_exit_strategy.py` V4 主策略
- ❌ 修改 `ewave_strategy_adapter.py` 波浪互斥融合规则
- ❌ 直接接入实盘交易系统

**共享基础设施（SHARED）修改要求**：
- ⚠️ 修改前必须评估对两条线的影响
- ⚠️ 修改后必须运行两条线的测试
- ⚠️ 物理引擎（pitd_*）的修改需特别谨慎

### 2.3 文件归属清单

#### 主线代码 [MAIN]

| 文件 | 职责 | 修改入口 |
|------|------|----------|
| [engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py) | 主引擎，V4+波浪互斥融合编排 | `compute_trend_signal_from_dataframes()` |
| [ml/halving_top_exit_strategy.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/halving_top_exit_strategy.py) | V4 减半周期逃顶策略（BTC专用） | `HalvingTopExitStrategy` |
| [ml/altcoin_trend_strategy.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/altcoin_trend_strategy.py) | 非BTC趋势跟踪策略（自身MA200+减半影子仓位） | `AltcoinTrendStrategy` |
| [ml/ewave_strategy_adapter.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/ewave_strategy_adapter.py) | 波浪策略适配器（互斥融合） | `EWaveStrategyAdapter` |
| [ml/ewave_recognizer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/ewave_recognizer.py) | 波浪识别器 | `ElliottWaveRecognizer` |
| [ml/ewave_backtest.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/ewave_backtest.py) | 波浪策略回测 | 独立回测脚本 |
| [ml/v4_wave_fusion_comparison.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v4_wave_fusion_comparison.py) | V4+波浪融合对比 | 验证脚本 |
| [ml/v4_wave_smart_fusion.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v4_wave_smart_fusion.py) | V4+波浪智能融合 | 验证脚本 |
| [ml/comprehensive_strategy_comparison.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/comprehensive_strategy_comparison.py) | 综合策略对比回测 | 验证脚本 |
| [ml/9year_strategy_comparison.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/9year_strategy_comparison.py) | 9年策略对比 | 验证脚本 |
| [ml/walk_forward_v4_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/walk_forward_v4_validation.py) | V4 Walk-Forward 验证 | 验证脚本 |

#### 副线代码 [ML_BASELINE]

| 文件 | 职责 | 归属目录 |
|------|------|----------|
| [ml/philosophy_feature_engineer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/philosophy_feature_engineer.py) | V5.5 28维哲学特征工程 | `ml/`（保留，被多文件引用） |
| [ml/feature_engineer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/feature_engineer.py) | 价格特征工程（V5.5 使用） | `ml/`（保留） |
| [ml/v51_ablation_experiment.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v51_ablation_experiment.py) | V5.1 消融实验 | `ml/v55_baseline/`（建议） |
| [ml/v51_cycle_similarity_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v51_cycle_similarity_validation.py) | V5.1 周期相似性验证 | `ml/v55_baseline/`（建议） |
| [ml/v52_ablation_experiment.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v52_ablation_experiment.py) | V5.2 消融实验 | `ml/v55_baseline/`（建议） |
| [ml/v52_fed_rate_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v52_fed_rate_validation.py) | V5.2 联邦利率验证 | `ml/v55_baseline/`（建议） |
| [ml/v53_*.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/) | V5.3 系列验证（4个文件） | `ml/v55_baseline/`（建议） |
| [ml/v54_direction4_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v54_direction4_validation.py) | V5.4 方向4验证 | `ml/v55_baseline/`（建议） |
| [ml/v55_direction123_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v55_direction123_validation.py) | V5.5 方向123验证 | `ml/v55_baseline/`（建议） |
| [ml/ewave_vs_v55_comparison.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/ewave_vs_v55_comparison.py) | 波浪 vs V5.5 对比 | `ml/v55_baseline/`（建议） |
| [ml/philosophy_feature_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/philosophy_feature_validation.py) | 哲学特征验证 | `ml/v55_baseline/`（建议） |
| [ml/stage2_dip_buy_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/stage2_dip_buy_validation.py) | Stage2 抄底验证 | `ml/v55_baseline/`（建议） |
| [ml/multitask_model.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/multitask_model.py) | 多任务学习模型 | `ml/`（保留） |
| [ml/lr_ml_strategy*.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/) | LR ML 策略 | `ml/`（保留） |

#### 共享基础设施 [SHARED]

| 文件 | 职责 | 使用方 |
|------|------|--------|
| [ml/pitd_confidence_scorer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/pitd_confidence_scorer.py) | 物理置信度评估器 | MAIN + ML_BASELINE |
| [ml/pitd_kinematics_engineer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/pitd_kinematics_engineer.py) | 运动学特征工程 | MAIN + ML_BASELINE |
| [ml/pitd_dynamics_engineer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/pitd_dynamics_engineer.py) | 动力学特征工程 | MAIN + ML_BASELINE |
| [ml/pitd_potential_field.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/pitd_potential_field.py) | 势场计算 | MAIN + ML_BASELINE |
| [ml/pitd_reasoning_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/pitd_reasoning_engine.py) | 物理推理引擎 | MAIN + ML_BASELINE |
| [ml/physics_enhancer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/physics_enhancer.py) | 物理增强器 | MAIN（主线使用） |
| [ml/algo_ensemble.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py) | LightGBM 集成推理 | 集成推理层（独立） |
| [ml/llm_reasoning.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/llm_reasoning.py) | LLM 辩证推理 | 集成推理层（独立） |
| [ml/models.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/models.py) | ML 模型定义 | ML_BASELINE |
| [ml/label_samples.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/label_samples.py) | 样本标注工具 | 集成推理层 |
| [backtest/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/backtest/) | 回测引擎 | MAIN + ML_BASELINE |
| [data/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/) | 数据获取层 | MAIN + ML_BASELINE |
| [core/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/) | 核心算法层 | MAIN + ML_BASELINE |

---

## 3. 副线目录规划

### 3.1 ml/v55_baseline/ 目录

创建 `ml/v55_baseline/` 作为 V5.5 ML 副线的独立工作区：

```
ml/v55_baseline/
├── README.md                    # 副线说明文档
├── __init__.py                  # 包入口
├── experiments/                 # 实验记录（未来）
└── (建议迁移的 V5.5 验证脚本)
```

**当前阶段**：仅创建目录和 README，不强制迁移文件。后续优化时逐步将 V5.5 验证脚本迁移至此。

### 3.2 命名约定

| 前缀 | 归属 | 说明 |
|------|------|------|
| `v4_*` / `halving_*` | MAIN | V4 主策略相关 |
| `ewave_*` | MAIN | 波浪策略相关 |
| `v5*_*` | ML_BASELINE | V5.x ML 探索相关 |
| `pitd_*` | SHARED | 物理引擎基础设施 |
| `physics_*` | MAIN | 物理增强器（主线使用） |

---

## 4. 修改与验证流程

### 4.1 主线修改流程

```
1. 修改主线代码 [MAIN]
2. 运行核心测试：python -m pytest tests/test_core.py -x -q
3. 运行主线回测：python ml/comprehensive_strategy_comparison.py --symbol BTC
4. 验证：年化 ≥ 53.34%（纯V4基线）且 ≥ 56.43%（V4+波浪融合基线）
5. 通过 → 合并；未通过 → 回退
```

### 4.2 副线修改流程

```
1. 修改副线代码 [ML_BASELINE]
2. 运行 Walk-Forward 验证：python ml/v55_baseline/walk_forward_validation.py
3. 运行对比回测：python ml/ewave_vs_v55_comparison.py
4. 验证：样本外 AUC ≥ 0.55，无显著过拟合
5. 若显著优于主线 → 申请晋升为主线（需评审）
```

### 4.3 共享基础设施修改流程

```
1. 修改共享代码 [SHARED]
2. 运行主线测试：python -m pytest tests/test_core.py -x -q
3. 运行主线回测：python ml/comprehensive_strategy_comparison.py --symbol BTC
4. 运行副线验证：python ml/v55_baseline/run_validation.py
5. 两条线均通过 → 合并；任一失败 → 评估影响并修复
```

---

## 5. 晋升机制

### 5.1 副线晋升为主线

**触发条件**（需同时满足）：
1. 9年回测年化收益 ≥ V4+波浪融合基线（56.43%）
2. 9年回测夏普 ≥ 1.41
3. 9年回测最大回撤 ≤ -43.31%
4. Walk-Forward 样本外 AUC ≥ 0.60
5. 多币种验证（BTC + ETH + SOL）均优于主线

**晋升流程**：
```
1. 副线提交晋升申请（含完整回测报告）
2. 评审：代码质量 + 回测结果 + 风险评估
3. 通过 → 创建新的主线版本，旧主线归档
4. 未通过 → 继续优化，记录失败原因
```

### 5.2 主线回退机制

**触发条件**（任一满足）：
1. 实盘连续 3 个月跑输纯 V4 基线
2. 最大回撤超过 V4 基线的 120%（即 > 53.24%）
3. 减半周期预测失败（2025年10月后 BTC 未见顶）

**回退操作**：
```
1. 标记当前主线版本为失败
2. 配置回退到纯 V4 基线（禁用波浪融合）
3. 分析失败原因并记录
4. 修复后重新申请晋升
```

---

## 6. 版本基线快照

### 6.1 当前主线基线（2026-07-19）

| 指标 | 纯V4 | V4+波浪互斥融合 | 买入持有 |
|------|------|-----------------|----------|
| 年化收益 | 53.34% | **56.43%** | 34.80% |
| 总收益 | 1708.54% | **1970.42%** | 655.68% |
| 夏普比率 | 1.3744 | **1.4112** | 0.8024 |
| 最大回撤 | -44.37% | **-43.31%** | -76.40% |
| Calmar | 1.2022 | **1.3031** | 0.4555 |

**主线配置**：
- V4 主策略：`HalvingTopExitStrategy`（默认参数）
- 波浪互斥融合：`EWaveStrategyAdapter(WaveConfig())`
- 物理置信度调节：弱趋势 η<0.10 时启用
- 波浪参数：ZigZag=0.05, wave_weight=0.3, confirm_threshold=0.6

### 6.2 当前副线基线（2026-07-19）

| 指标 | V5.5 ML | 备注 |
|------|---------|------|
| 年化收益 | 4.31% | 严重过拟合 |
| 夏普比率 | 0.3024 | 远低于主线 |
| 最大回撤 | -56.48% | 风险偏高 |
| 特征维度 | 28维 | 需重新设计 |
| 主要问题 | 长期过拟合 | 训练窗口+特征工程 |

**副线优化方向**：
1. 重新设计特征工程（解决过拟合）
2. 探索更长的训练窗口
3. 探索时序模型（LSTM/Transformer）
4. 探索多任务学习
5. 改进标签生成策略

---

## 7. 变更记录

| 日期 | 版本 | 变更内容 | 影响策略线 |
|------|------|----------|------------|
| 2026-07-19 | v1.0 | 创建策略线管理总纲，确立双线架构 | MAIN + ML_BASELINE |
| 2026-07-19 | v1.0 | 主线从 V5.5 ML 切换为 V4+波浪互斥融合 | MAIN |
| 2026-07-19 | v1.0 | V5.5 ML 降级为副线，进入实验状态 | ML_BASELINE |
