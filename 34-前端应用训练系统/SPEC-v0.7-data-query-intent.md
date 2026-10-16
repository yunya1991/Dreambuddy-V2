# SPEC v0.7 — 数据查询与动态解读意图训练（data_query / data_insight）

> 版本: v0.7 | 日期: 2026-10-15 | 状态: 已确认，落地推进中

## 1. 背景与动机

前端最基础的能力是查询能力：当用户问『某个数据是什么』时，意图识别层（S 层）应快速识别并路由到 18-数据获取中心直接取数回复。

当前缺口（2026-10-15 评估结论）：

1. S 层意图模型现有 12 种意图类型（RAG检索、strategy_layer、BCRM2、BDSM、硬约束、运维、部署等），**没有 data_query / data_insight 类意图**；
2. 18 中心相关的采集器（data_fetch_route_collector / dal_route_collector）只采集路由链路序列喂 DSH 层，对 S 层意图识别零贡献；
3. S 层训练数据唯一来源是 session_memory 的 (message, intent) 对，属于被动数据源，查询类问法从未被训练过。

## 2. 两层能力定义

### 2.1 第一层：静态查询能力（data_query）

- **意图类型**: `data_query`
- **能力**: 用户询问某项数据的当前值/最新值/历史值时，S 层识别为 data_query，路由到 18 中心查询接口直接返回数据。
- **典型问法**: 『BTC 现在什么价』『恐惧贪婪指数多少』『最新 CPI 数据』『defillama TVL 多少』

### 2.2 第二层：动态变化解读能力（data_insight）

- **意图类型**: `data_insight`
- **能力**: 用户询问数据变化背后的金融市场含义时，S 层识别为 data_insight，结合 9-基本面分析系统的计算逻辑（事件映射、叙事、情绪、信号、最小阻力引擎）给出解读。
- **典型问法**: 『CPI 超预期意味着什么』『恐惧贪婪指数转贪婪说明什么』『稳定币市值下降对市场有什么影响』
- **价值定位**: 查询是静态，动态变化的训练更具备价值——这是查询能力之上的第二层能力。

## 3. 数据源

### 3.1 data_query 采集器（DataQueryIntentCollector）

- **数据来源**: 18 中心 `data_center.db` 的 records 表（source / category / sub_category / metrics / events / timeseries）
- **样本生成**: 基于实际数据源目录（defillama、ccxt、yfinance、fred、fear_greed、coinglass 等 15+ 来源）+ 问法模板，生成 (message, intent_type='data_query') 训练案例
- **样本字段**: message（问法）、intent_type（data_query）、quality（B）、layer_tags（['S']）、metadata（source/category/sub_category，供后续路由）

### 3.2 data_insight 采集器（DataInsightCollector）

- **数据来源**: 9-基本面分析系统的计算引擎逻辑（event_mapping_engine 事件→市场含义映射、sentiment_engine 情绪、signal_engine 信号、least_resistance 最小阻力）
- **样本生成**: 基于『数据变化模式 → 金融市场含义』知识对，生成 (message, intent_type='data_insight') 训练案例
- **样本字段**: message（问法）、intent_type（data_insight）、quality（B）、layer_tags（['S']）、metadata（engine/变化模式）

## 4. 接入方式

1. 两个采集器实现 `TrainingDataProvider` 接口（collect(limit) → List[TrainingCase]），与其他 19 个采集器同构；
2. 注册到 `run_continual_training.py` 的采集器列表，纳入持续训练调度；
3. FAIL-OPEN：数据库不可用/引擎导入失败时返回空列表，不阻塞训练。

## 5. 验收标准

1. 持续训练运行后，S 层意图模型 weights 中出现 `data_query` 和 `data_insight` 意图类型；
2. 两个采集器在阶段 1 采集中产出 ≥ 10 条样本/源；
3. 喂入 S 层全部成功（失败 0）；
4. SPEC v0.5 §5.4 P3 既有验收项不回退（EWMA / Checkpoint / 持续训练均通过）。

## 6. 边界与非目标

- 本 SPEC 只覆盖意图识别训练与数据采集，不含查询执行链路（识别为 data_query 后调用 18 中心接口并返回数据）——该闭环属于后续版本；
- 不修改 S 层训练循环核心逻辑（IntentTrainingLoop），仅新增训练数据源。
