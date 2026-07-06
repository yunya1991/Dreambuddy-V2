# L4记忆架构与工作流核心设计（v1.1）

Date: 2026-05-12  
Status: Draft (Architecture Baseline, Updated)  
Scope: 仅形成 L4 记忆核心文档，不改动现有业务代码  
Applies to: `workflows/memory/`、`workflows/memory/memory_engine/`、`scripts/memory_l4/`、`artifacts/`

## 1. 文档目标

本文档用于将现有实现与升级规划统一为一套可执行的 L4 记忆核心架构与工作流规范，作为后续自动化升级与治理审计的唯一设计依据。

本文档回答三个问题：

- L4 记忆系统“是什么”：系统边界、分层职责、核心对象。
- L4 记忆系统“为什么”：服务交易闭环复用与进化，不做黑箱升级。
- L4 记忆系统“怎么做”：状态机、数据契约、工作流、门禁与阶段路线图。

## 2. 设计原则

- `constraints` 仍是唯一规则源（SSOT），`memory` 不直接改写约束。
- L1~L4 入口层保持薄封装，复杂能力下沉到 `MemoryEngine` 和 `scripts/memory_l4/`。
- 所有关键产物必须可追溯：`trace_id`、`evidence_refs`、`stage_id`、`constraint_version`。
- 任何自动化升级都必须 fail-closed，失败即停止推进并产出结构化审计。
- 记忆沉淀到约束必须经过 `memory -> evolution -> constraints` 唯一通道。

## 3. L4 在整体中的定位

在当前体系中：

- L1：检索与相关性排序（实时支持决策）。
- L2：短期反馈与健康检查（Bandit + 一致性）。
- L3：长期索引维护与质量巡检（向量文档与索引资产）。
- L4：归档层分析与进化输入（失败分析、迁移映射、共享图谱、元学习任务）。

L4 不是“另一个检索层”，而是经验升格与跨周期进化的中台输入层。

## 4. 核心对象模型（L4最小集合）

### 4.1 TradeCase（完整交易闭环事件）

每笔交易必须沉淀为完整闭环事件，包含：

- 结果链：收益率、回撤、离场原因、是否达成目标。
- 证据链：引用的行情、策略、报告、episode 文件。
- 思维链：A0-A9 全链路决策轨迹与阶段结论。

核心要求：

- 必须可定位到 `case_id` 与 `trace_id`。
- 必须包含 `execution.episode_refs[]` 和 `evidence_refs[]`。
- 必须可被后续索引、复盘、蒸馏、统计复用。

为承载 A0-A9 思维链，定义 `TradeCase.vNext` 的增量字段（向后兼容）：

- `thinking_chain[]`：按实际执行阶段记录，不要求固定 10 阶段全填。
- `evidence_chain[]`：证据节点与阶段关系的结构化串联（非仅引用列表）。
- `decision_outcome`：交易评估结论（收益率、回撤、离场逻辑、是否达成目标）。

`thinking_chain[]` 最小字段建议：

- `stage_id`（如 `A0`、`A1`、...）
- `decision`
- `contradiction`（识别/分析/利用结果）
- `evidence_refs[]`
- `timestamp`

### 4.2 ReviewRecord（复盘记录）

围绕 TradeCase 的理论-实践复盘对象，必须回答：

- 做错了什么，为什么错（根因、误判信号、约束缺口）。
- 做对了什么，哪里对（有效信号、正确机制、可复用动作）。

输出要求：

- 理论修订建议（Theory）。
- 实践动作建议（Practice）。
- 理论与实践一致性评分（用于蒸馏优先级）。

补充要求（对错双向）：

- `mistakes[]`：做错了什么、为什么错。
- `successes[]`：做对了什么、哪里对。
- `theory_practice_gap`：A7/A8 交叉验证后的差距结论。

### 4.3 DistillRecord（逻辑蒸馏记录）

围绕事件闭环与复盘结果的抽象对象，必须覆盖固定链路：

`意图 -> 调研 -> 理论 -> 假设 -> 测试观测 -> 结论 -> 落地 -> 监控 -> 复盘 -> 做梦 -> 更新优化`

每次蒸馏必须回答三问：

- 是什么（定义与边界）。
- 为什么（证据与因果）。
- 怎么做（可执行规则与触发条件）。

补充结构（向后兼容）：

- `what_is_it`：定义、分类、核心结论。
- `why_it_works`：因果链、理论依据、证据链、矛盾解法。
- `how_to_apply`：可执行规则、触发条件、风险警戒、退出条件。
- `process_trace`：11 步流程追溯记录。

兼容策略：

- 保留 `claim` 与 `actionable_rules` 字段。
- `claim` 视为 `what_is_it.claim` 的快捷映射。
- `actionable_rules` 视为 `how_to_apply.rules` 的快捷映射。

### 4.4 StatsSnapshot（四象限统计快照）

统计驱动对象，用于：

- 静态库：形成四象限分类与程度分层，支持 A0-A9 检索参考。
- 动态演化：通过量变与迁移趋势发现可验证进化候选。

四象限坐标体系保持不变（`x/y` 不改），增加过滤维度用于精细检索：

- `regime`：市场状态（如 bull/bear/range）。
- `category`：交易类型（如 trend/reversal/arbitrage）。
- `severity`：影响程度（可由 PnL 与风险暴露推导）。

## 5. L4 工作流总览

### 5.1 主流程

```text
A0-A9 决策执行
  -> 生成 episode 与证据
  -> 注册 TradeCase（完整闭环）
  -> L4 失败分析/成功分析（review 引擎）
  -> A7/A8 结果适配并汇入 review_record
  -> 迁移分析/共享图构建/元任务入队
  -> 复盘（理论-实践）
  -> 蒸馏（三问闭环）
  -> 四象限统计聚合
  -> 输出 evolution 候选（非直接发布）
```

### 5.2 L4 子能力映射（与现有实现对齐）

- 失败分析：`analyze_failure_memory`
- 跨市场迁移：`analyze_cross_market_migration`
- 共享记忆图：`build_shared_memory_graph`
- 元学习任务：`enqueue_meta_learning_tasks`

在不改代码阶段，新增“目标能力定义”：

- 复盘引擎目标：`review_engine`（失败与成功双向分析）。
- 适配层目标：`a7_a8_adapter`（A7/A8 输出转译为 L4 可消费记录）。

入口映射保持不变，继续通过 `workflows/memory/L4_archive/entrypoint.py` 调用。

## 6. 索引底座设计（记忆核心基础设施）

### 6.1 索引目标

- 支持“结构化相似 + 语义相似”的统一检索。
- 支持按 case、distill、阶段、市场、风险标签的组合检索。
- 支持同类历史事件快速引用，服务 A0-A9 当前决策。
- 支持思维链特征检索（按 A0-A9 阶段与矛盾类型定位历史案例）。

### 6.2 索引分层

- 结构化索引：`case_features` / `distill_features`（字段匹配、规则可解释）。
- 语义索引：向量文档（案例文本、蒸馏结论、可执行规则）。
- 统一融合：输出统一实体 ID 的排序结果，保留文档级追踪信息。
- 过滤索引：`regime/category/severity/stage_id` 组合过滤，支撑 A0-A9 精细调用。

### 6.3 索引一致性要求

- 案例存在即必须可索引（`CASE_NOT_INDEXED` 视为问题）。
- 索引引用不得悬空（`INDEX_CASE_NOT_FOUND`）。
- 索引构建必须产出版本化 metadata（snapshot_ts、feature_version、weights）。

## 7. 复盘与蒸馏标准化工作流

### 7.1 复盘（Review）标准流程

- 输入：完整 TradeCase + episode + evidence。
- 分析：理论与实践双维度交叉分析（失败与成功双向）。
- 输出：错因、对因、改进行动、理论实践一致性评分。
- 产物：结构化 ReviewRecord（可审计，可被蒸馏消费）。

补充要求：

- 失败分析能力可保留为子模块（兼容现有 `failure_analyzer`）。
- Review 引擎作为上层编排，统一输出 `mistakes/successes/theory_practice_gap`。

### 7.2 蒸馏（Distill）标准流程

- 输入：ReviewRecord + 历史同类 case + 理论知识源。
- 处理：11 步固定链路与三问校验。
- 输出：DistillRecord（三层结构 `what/why/how` + `process_trace`）。
- 校验：必须可解释、可执行、可回测、可失败归因。

## 8. 数据统计驱动与四象限演化

### 8.1 静态事件库目标

- 按四象限构建“类型 + 程度”分层参考库。
- 为 A0-A9 每阶段提供可引用的历史先例。
- 支持查询样式：`regime + category + x/y + severity`。

### 8.2 动态演化目标

- 基于样本堆积观察迁移方向与稳定性变化。
- 将量变信号转化为 `evolution candidate`，进入验证门禁。

### 8.3 关键统计指标（最小集）

- 事件分布：市场、策略、情景、象限密度。
- 绩效结构：收益、回撤、胜率、尾部风险暴露。
- 一致性结构：理论-实践一致性、复盘有效率。
- 迁移结构：象限迁移率、迁移后表现稳定性。

## 9. 运行状态机与失败语义

### 9.1 L4 内部状态（建议）

- `M0_CASE_REGISTERED`
- `M1_REVIEW_COMPLETED`
- `M2_DISTILL_COMPLETED`
- `M3_STATS_UPDATED`
- `M4_CANDIDATE_EMITTED`
- `M_FAIL`（附 reason_code）

### 9.2 失败语义（建议最小集）

- `CASE_INCOMPLETE`
- `EVIDENCE_MISSING`
- `REVIEW_INCONSISTENT`
- `DISTILL_INVALID`
- `STATS_INTEGRITY_FAILED`
- `CANDIDATE_EMIT_BLOCKED`

失败处置规则：

- 任一步失败立即停止后续自动推进。
- 必须写入结构化审计产物（含 `stage + reason_code + evidence_refs`）。
- 允许人工修复后重试，不允许无证据强制通过。

## 10. 与现有代码的映射关系（不改代码）

当前目录职责保持：

- `workflows/memory/L1~L4_archive/entrypoint.py`：入口薄封装。
- `workflows/memory/memory_engine/engine.py`：核心编排与组合逻辑。
- `scripts/memory_l4/case_registry.py`：TradeCase 注册。
- `scripts/memory_l4/index_builder.py` / `query_similar.py`：索引构建与检索。
- `scripts/memory_l4/failure_analyzer.py`：失败分析。
- `scripts/memory_l4/migration_mapper.py`：跨市场迁移分析。
- `scripts/memory_l4/memory_graph.py`：共享记忆图构建。
- `scripts/memory_l4/meta_learning_tasks.py`：元学习任务入队。
- `scripts/memory_l4/stats_builder.py`：统计快照与聚合。

目标新增组件（当前阶段仅文档定义，不落代码）：

- `review_engine.py`：对错双向复盘编排。
- `a7_a8_adapter.py`：A7/A8 到 L4 结构化适配。
- `thinking_chain_index_extension`：思维链特征提取与索引扩展。

## 11. 分阶段升级路线图（文档先行）

### P0（规范固化）

- 固化 TradeCase / ReviewRecord / DistillRecord / StatsSnapshot 契约。
- 固化 `thinking_chain/evidence_chain/decision_outcome` 字段定义与兼容策略。
- 固化 L4 状态机与失败语义字典。
- 固化三问蒸馏模板与复盘模板。

验收标准：文档契约完整、无冲突、可审计字段齐全。

### P1（链路打通）

- 打通 “事件入库 -> 复盘 -> 蒸馏 -> 统计 -> 候选” 完整链路。
- 增加 A7/A8 到 L4 的适配通道定义与产物映射规范。
- 统一产物目录与命名规范。
- 增加最小门禁（字段完整性、证据完整性、可追溯性）。

验收标准：至少 1 条样本能闭环跑通并完整产出 artifacts。

### P2（演化强化）

- 四象限动态演化指标接入候选生成。
- 在不改变 `x/y` 坐标的前提下，引入 `regime/category/severity` 过滤维度。
- 候选优先级评分（风险/收益/覆盖）。
- 与 evolution 验证门禁联动，形成可回滚升级流程。

验收标准：候选可批量入队、可验证、可拒绝、可回滚。

### P3（认知强化，可选）

- 思维链检索能力接入索引服务。
- 蒸馏知识源扩展（知识库/历史事件/联网检索）策略文档化。
- 形成稳定的“理论-实践-约束”闭环运营节律。

验收标准：A0-A9 可按阶段与矛盾类型检索高相关历史链路。

## 12. 冲突与兼容策略（评估结论吸收）

| 冲突点 | 严重度 | 吸收策略（文档阶段） |
|---|---|---|
| `plan.steps` 无法承载 A0-A9 思维链 | 高 | 新增 `thinking_chain[]`，保留 `plan.steps` 兼容旧数据 |
| 失败分析单向，缺少成功经验复盘 | 中 | 设定 `review_engine` 目标模型，`failure_analyzer` 作为子模块 |
| A7/A8 与 L4 数据不兼容 | 中 | 新增适配层契约，定义字段映射与最小输入输出 |
| Distill 结构过扁平 | 高 | 升级到 `what/why/how + process_trace`，保留旧字段映射 |
| 四象限检索粒度不足 | 低 | `x/y` 不改，补 `regime/category/severity` 过滤维度 |
| 索引不支持思维链检索 | 中 | 先定义扩展字段与检索契约，后续再实施 |

## 13. DoD（核心文档完成定义）

当以下条件满足，本文档视为 L4 核心文档可用版本：

- 明确 L4 系统边界、对象模型、工作流与状态机。
- 明确索引底座、复盘与蒸馏标准、统计驱动逻辑。
- 明确与现有代码目录和能力映射关系。
- 明确阶段升级路线与验收标准。
- 全文不要求修改现有代码即可作为后续实施依据。

## 14. 非目标（本阶段不做）

- 不在本阶段新增或修改业务代码。
- 不在本阶段变更主链交易协议。
- 不在本阶段上线自动约束升级执行器。
