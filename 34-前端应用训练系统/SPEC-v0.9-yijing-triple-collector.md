# SPEC v0.9 — 易经推理系统三类采集器意图训练（technical_analysis / fundamental_valuation / asset_class_trend）

> 版本: v0.9 | 日期: 2026-10-15 | 状态: 评估完成，SPEC 已形成
> 前置: SPEC-v0.7（第一/二层）、SPEC-v0.8（第三层）

## 1. 背景与能力定位

11-易经推理系统是交易决策的核心推理层，包含三个分析维度。将其纳入意图训练后，前端可回答三个维度的推理类问题，与既有三层能力互补：

| 采集器 | 对应维度 | 分析模式 | 数据来源（已验证） |
|---|---|---|---|
| BCRM2.0 技术指标采集器 | 技术分析 | 根据技术指标推理运算（卦象/方向/置信度） | data/bcrm2/bcrm2_hourly_summary.json（逐币种 direction/confidence/hexagram，如 BTC UP 0.743 泽地萃） |
| BDSM 基本面采集器 | 单币种基本面 | 估值等维度分析单一币种 | .workbuddy/bdsm/bdsm_snapshot_YYYYMMDD.json（每日快照） |
| 资产类别分析采集器 | 战略层 | 跨资产趋势分析 | polling_trader 日志 [战略层影子] 行（crypto_usdt / us_stock / precious_metal 三资产类别维度） |

## 2. 评估结论（基于数据事实）

1. **三个维度的数据输出真实存在且持续更新**：BCRM2 汇总含 10 个币种的方向/置信度/卦象（wdh 特征、Merrill 时钟、增量学习均启用）；BDSM 每日快照连续存在（最新 20261015）；战略层影子日志实时输出三资产类别的 dimension_veto / front_layer_band / forced_close 状态（22:13 仍在产出）；
2. **三类问法语义可区分**：技术指标推理（『BTC 技术面怎么算的』）、单币种估值（『ETH 估值怎么样』）、跨资产趋势（『美股和加密货币趋势对比』），适合独立意图类型；
3. **与既有意图不冲突**：data_query 查静态值、data_insight 单数据变化含义、contradiction/path 多维交汇；本 SPEC 三个意图聚焦『推理运算过程与结论』。

## 3. 意图定义

### 3.1 technical_analysis（技术指标推理意图）
- **典型问法**: 『BTC 技术面方向是什么』『技术指标怎么算的』『BTC 卦象是什么』『技术面置信度多少』

### 3.2 fundamental_valuation（单币种估值意图）
- **典型问法**: 『ETH 估值怎么样』『BTC 基本面分析』『这个币估值高不高』『单币种基本面结论』

### 3.3 asset_class_trend（跨资产趋势意图）
- **典型问法**: 『美股和加密货币趋势对比』『跨资产现在什么状态』『贵金属和加密一致吗』『战略层怎么看各类资产』

## 4. 采集器设计

### 4.1 bcrm2_technical_collector
- 解析 bcrm2_hourly_summary.json：逐币种生成 (message, intent_type='technical_analysis') 样本，metadata 含 symbol/direction/confidence/hexagram；

### 4.2 bdsm_fundamental_collector
- 解析最新 bdsm_snapshot_YYYYMMDD.json：逐币种生成 (message, intent_type='fundamental_valuation') 样本，metadata 含 symbol/估值维度结论；

### 4.3 asset_class_collector
- 解析 polling_trader 最新日志的 [战略层影子] 行：按资产类别组合生成 (message, intent_type='asset_class_trend') 样本，metadata 含三资产类别状态；

### 4.4 共同约束
- 实现 TrainingDataProvider 协议；FAIL-OPEN；增量采集（按文件修改时间）；每采集器产出 ≥ 10 条/次。

## 5. 接入与验收

1. 三个采集器注册到持续训练（v0.8 后为 25 个数据源）；
2. 验收：S 层出现三个新意图、喂入 0 失败、既有验收不回退；
3. 执行闭环（后续版本）：technical_analysis → 查 BCRM2 汇总返回方向/卦象/置信度；fundamental_valuation → 查 BDSM 快照返回估值结论；asset_class_trend → 查战略层日志返回跨资产状态。

## 6. 边界与非目标

- 只读取 11 系统数据输出，不修改其代码；
- 本 SPEC 覆盖采集与意图训练，执行闭环为后续版本。
