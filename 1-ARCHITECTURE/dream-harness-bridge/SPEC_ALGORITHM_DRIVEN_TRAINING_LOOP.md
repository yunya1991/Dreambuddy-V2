# SPEC — DreamOS 算法驱动 + Harness 训练闭环

> **版本**: v0.1
> **状态**: 📋 评估稿，按 D-调研方法论形成，待用户审阅
> **创建日期**: 2026-09-17
> **实现差异注记（2026-09-30）**: 本 SPEC 规划的 IPC method 名（`algorithm_recognize`/`shadow_review`/`agent_takeover`）为设计阶段表述，**当前实际实现**为 `packages/python-server/server.py` 的 13 个 `_handle_*` 路由（c1_scan/c2_momentum/c3_volatility/execute_c_chain/intent_gateway/technical_indicators/fundamental_analysis/graph_planner/reflection/reflection_decide/session_consumer/artifact_index/trade_index/build_vector_index/record_to_cognitive/stats）。规划意图已落地，但 method 命名与分层结构以实际实现为准。详见 [SPEC.md](./SPEC.md) v0.4 与 [TECHNICAL_DESIGN.md](../dreamos/docs/TECHNICAL_DESIGN.md) §3.4.7。
> **方法论**: D1 四准则调研 → D2 三问分析 → D3 三景推演 → D4 四段 Spec
> **前置文档**:
> - [SPEC.md](./SPEC.md) v0.4 — dream-harness-bridge 分层嵌入主 Spec
> - [RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md](../RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md) v0.2 — 全栈对齐调研（含边界守护理论）
> - [SPEC_INTENT_DREAMOS_OPTIMIZATION.md](./SPEC_INTENT_DREAMOS_OPTIMIZATION.md) — 意图识别优化评估
> - [../intent-recognition-spec/intent-taxonomy.md](../intent-recognition-spec/intent-taxonomy.md) — 6×30 对话意图权威规范
> - [D-调研方法论.md](../../2-KNOWLEDGE/5-METHODOLOGY/D-调研方法论.md) — 调研方法论
> - [project_memory.md](../../../../../.trae-cn/memory/projects/-Users-zhangjiangtao-WorkBuddy-dreambuddy-v2--p2-5f8e8db8067187fd2690/project_memory.md) — 硬约束清单

---

## ⚠️ 文档定位

本文件是 **dream-harness-bridge 项目 v0.4 SPEC 的延伸 Spec**，聚焦"算法驱动 + Harness 训练闭环"这一垂直命题。不替代主 SPEC，只补充训练闭环层。所有边界守护硬约束（HC-1 ~ HC-11）在本 SPEC 范围内继续生效。

**核心命题**：
> DreamOS 以**算法驱动**为主（规则 + 领域 ML 模型），**Harness 作为全链评审 + 纠偏 + 标注 + 训练**的管道，实现用大模型训练专属金融模型；**超出能力的少数案例**直接调用 Agent 能力接管。

---

## 第一段（D1）— 四准则调研（事实，不做分析）

### 1.1 代码现状（事实清单）

#### 1.1.1 DreamOS 操作系统内核（SACG 四层）

| 层 | 真实路径 | 当前能力 | 算法驱动力 |
|----|---------|---------|-----------|
| **S 层 Sense** | `dreamos/core/sense/intent_engine.py` + `recognizers/{rule_based,llm_based,dynamic}.py` + `complexity_classifier.py` | 规则识别（零 Token）→ LLM 降级（阈值 0.55）→ 复杂度 T0-T3 分级 → T3 委托 Harness | 规则+LLM 双轨，无训练有素的 ML 模型 |
| **A 层 Arrange** | `dreamos/core/arrange/{graph_planner,node_selector,budget_allocator,execution_graph}.py` | 四维过滤（Token 预算 / 知识库 / Regime 命中率 / 标的覆盖）→ 节点选择 | 纯规则编排，无学习成分 |
| **C 层 Compute** | `dreamos/core/compute/{graph_executor,node_runner,reflector,aggregator}.py` | 节点调度 + 反思维决策（CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE） | 反思维规则化，无 ML |
| **G 层 Graph** | `dreamos/core/graph_store/{store,checkpointer,compressor,history}.py` | 快照式 `ckpt_*.json` + BAC 三层压缩 | 静态存储，无事件流 |

#### 1.1.2 认知与自进化系统

| 组件 | 路径 | 现状 |
|------|------|------|
| 认知 MCP | `4-MEMORY/9-工具与接口/cognitive_mcp_server.py` | recall/record/verify/stats/health 5 工具已暴露 |
| 贝叶斯进化 | `bayesian_memory_updater.py` + `rumination_engine.py` + `prediction_engine.py` + `consolidation_engine.py` | Beta-Binomial + 指数遗忘，已有 verify→置信度升级闭环 |
| 自进化引擎 | `dreamos/evolution/engine.py` | 真实 PnL 通过 `tanh(pnl_pct/0.02)` 归一化为 reward（HC-5 边界守护） |
| 反思维节点 | A7 实践论门禁 + A8 知行合一验证 | 已有，但消费的是快照而非事件流 |
| 做梦部 | D-Z-E 开发链 | 概念已有，未形成训练 pipeline |

#### 1.1.3 交易系统节点（22 个 + 11 适配器）

- **执行环**：A0 矛盾 → A1 调研 → A2 第一性原理 → A3 沙盘 → A4 验证 → A5 执行 → A9 离场
- **情报环**：A6 实时雷达 + 异常检测 + 应急响应
- **治理环**：A7 实践论门禁 → A8 知行合一 → 路由进化
- **三大思维链**：S 链（调研→分析→设计→验证→执行）/ C 链（扫描→识别→匹配→回测→参数）/ F 链（新闻→资金→情绪→链上→宏观）

#### 1.1.4 Harness 整合现状

| 维度 | 状态 |
|------|------|
| SPEC v0.4 | 已完成：分层嵌入 + 11 条硬约束 + 边界守护理论（三条核心边界 + 10 失守场景） |
| Phase 0 POC | 未启动（待用户批准） |
| 关键修正 | F-01 契约版本化 / F-02 协议级硬约束 / F-03 链路活性测试等 15 条已识别 |
| 意图识别映射 | 前端 35 型正典 → 内核 6×30 对话意图 已建立（`intent-schema.ts` CANON_TO_KERNEL） |

#### 1.1.5 复杂度分级器（关键资产）

源文件：`dreamos/core/sense/complexity_classifier.py`

| 层级 | 含义 | 处置 |
|------|------|------|
| **T0** | 数据点查询（"BTC 多少钱"） | 跳过 LLM 直答 |
| **T1** | 单链分析 | 走置信度+预算门控 |
| **T2** | 多链分析 | 走置信度+预算门控 |
| **T3** | 深度研究 | **跳过 LLM，委托 Harness** |

> 当前 T3 已存在"委托 Harness"的语义占位，但**未明确 Agent 接管边界**——本 SPEC 要补全的关键缺口。

### 1.2 历史问题（事实，来自记忆库 + git log）

| 编号 | 问题 | 来源 |
|------|------|------|
| HP-1 | LLM 驱动倾向过重：置信度阈值 0.55 过低，规则识别稍弱即触发 LLM | `intent_engine.py` L55 |
| HP-2 | 训练有素的领域 ML 模型缺失：S 层只有"规则+LLM"两路，无中间层 ML 模型 | `sense/recognizers/` 目录审计 |
| HP-3 | 训练闭环未建立：认知系统有 `verify` 但未输出可训练数据集 | `4-MEMORY/9-工具与接口/` 审计 |
| HP-4 | Agent 接管边界模糊：T3 委托 Harness 但未定义"何时算超出能力" | `complexity_classifier.py` |
| HP-5 | 自进化 reward 边界已硬约束（HC-5）：Harness 不得参与 reward 计算 | `project_memory.md` |
| HP-6 | Plugin 只透传不决策（HC-9）：Harness 不得做交易判断 | `SPEC.md` v0.4 §2.2 |
| HP-7 | 事件流尚未建立：G 层仍是快照式，喂养 A7/A8 自进化效率受限 | `RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md` §3.1 |

### 1.3 外部方案（事实收集）

| 方案 | 核心机制 | 与本提案关系 |
|------|---------|-------------|
| **RLHF / DPO** | 人类反馈强化学习 / 直接偏好优化 | 大模型训练主流，可借鉴数据格式 |
| **LLM-as-Judge** | 用大模型做评审/打分/标注 | Harness 评审的理论基础 |
| **Active Learning** | 主动挑选难例训练 | 决定哪些样本送 Harness 标注 |
| **Self-Improving ML** | 模型自蒸馏 + 自进化 | 与 DreamOS 自进化系统同源 |
| **FL / TEE** | 联邦学习 / 可信执行环境 | 数据隐私保护，金融领域常用 |
| **Cordis Model-as-Plugin** | 模型适配器即 plugin，换模型 = 换 plugin | Harness HM-8 机制，训练后切换模型 |

### 1.4 矛盾发现（只记不分析）

| 编号 | 矛盾 | 类型 |
|------|------|------|
| C-1 | 用户"倾向深度学习，不倾向大语言模型" vs 当前 IntentEngine 主要靠 LLM 兜底 | 偏好-现状 |
| C-2 | "Harness 做评审 + 训练" vs "自进化 reward 由 DreamOS 内部计算"（HC-5） | 边界冲突 |
| C-3 | "Harness 标注训练数据" vs "Plugin 只透传不决策"（HC-9） | 边界冲突 |
| C-4 | "算法驱动 90% 覆盖" vs "长尾意图难覆盖" | 能力-成本 |
| C-5 | "实时性要求" vs "训练延迟" | 时延-质量 |
| C-6 | "Harness 评审权威性" vs "DreamOS 自主性" | 主权-辅助 |

---

## 第二段（D2）— 三问分析

### 2.1 根因链

```
现象：DreamOS 算法驱动不足，LLM 价值未凸显
   ↓ 直接原因
IntentEngine 置信度阈值低（0.55），规则稍弱即触发 LLM
   ↓ 间接原因
缺乏训练有素的领域 ML 模型作为规则与 LLM 之间的中间层
   ↓ 间接原因
缺乏完整的"评审-标注-训练-验证"闭环 pipeline
   ↓ 根因
未建立"算法驱动为主、Harness 评审训练为辅、Agent 接管长尾"的
三层架构，导致 LLM 既是执行者又是兜底者，价值无法凸显
```

**根因层级**：
- L0 表层：阈值偏低
- L1 能力层：缺领域 ML 模型
- L2 闭环层：缺训练 pipeline
- L3 架构层：**缺三层分工架构** ← 真正根因

### 2.2 矛盾识别

#### 首对矛盾（主矛盾）

**算法驱动深度 ↔ LLM 训练价值凸显**

- 表面看是对立：算法强则 LLM 弱
- 实际是相辅相成：算法驱动覆盖面越广，剩余难例越精炼，LLM 标注价值越高；LLM 训练出的领域模型越强，算法驱动覆盖面越广
- 这是"互补不冲突"关系，与 DreamOS × Harness 的边界守护理论一致

#### 次要矛盾对

| 编号 | 矛盾对 | 性质 |
|------|--------|------|
| M-1 | Harness 评审权威性 ↔ DreamOS 自主性 | 通过 HC-5 + HC-9 边界守护化解 |
| M-2 | 训练数据需求 ↔ 交易领域数据稀缺 | 通过"真实+合成"混合数据集化解 |
| M-3 | 实时性要求 ↔ 训练延迟 | 通过"异步影子评审"化解（不阻塞热路径） |
| M-4 | 算法 90% 覆盖 ↔ 长尾意图难覆盖 | 通过"Agent 接管"化解（T3 走 Agent） |

### 2.3 方案矩阵（不推荐，只客观对比）

| 方案 | 做什么 | 优点 | 缺点 | 风险 | 工作量 | 评星 |
|------|--------|------|------|------|--------|------|
| **A 全 LLM 驱动** | 全部委托 Harness + LLM 决策 | 实现简单，起步快，泛化好 | LLM 成本高，DreamOS 领域性弱化，违背用户深度学习偏好，长尾可解释性差 | 高 | 小 | ★★ |
| **B 纯算法驱动** | 只用规则 + ML 模型，无 LLM | 成本低，可控，可解释 | 缺乏 LLM 泛化能力，长尾意图难覆盖，训练数据稀缺 | 中 | 大 | ★★★ |
| **C 算法驱动 + Harness 训练闭环** | 算法为主，Harness 评审+纠偏+标注+训练 | 兼顾成本与能力，LLM 价值凸显（从执行者升级为训练者），与 DreamOS 自进化系统天然衔接 | 架构复杂，边界守护要求高，训练数据治理成本 | 中 | 中-大 | ★★★★★ |
| **D 双轨并行** | 算法 + LLM 都做，投票决策 | 容错性高 | 资源浪费，决策冲突，难以解释 | 中 | 大 | ★★★ |

---

## 第三段（D3）— 三景推演

### 3.1 方案 C 三景推演（推荐方案）

#### 理想情景（25% 概率）

| 维度 | 内容 |
|------|------|
| **触发条件** | 算法驱动覆盖 90%+ 意图，Harness 评审一致率 >85%，训练数据质量门禁通过 |
| **结果** | DreamOS 领域模型持续进化；LLM 调用频次下降 80%；Harness 评审价值凸显；自进化系统进入良性循环 |
| **收益** | 长期 LLM 成本下降 80%；领域模型性能持续提升；可解释性增强 |
| **耗时** | 6-12 个月达成稳定闭环 |

#### 现实情景（50% 概率）

| 维度 | 内容 |
|------|------|
| **触发条件** | 算法驱动覆盖 70%+ 意图，Harness 评审一致率 60-80%，部分场景仍需 LLM |
| **结果** | 仍需 LLM 介入长尾，但训练数据持续累积；模型性能稳步提升但非飞跃 |
| **收益** | 长期 LLM 成本下降 40-60%；领域模型稳步提升 |
| **耗时** | 12-18 个月迭代优化 |

#### 恶化情景（25% 概率）

| 维度 | 内容 |
|------|------|
| **触发条件** | 训练数据不足/质量差；Harness 评审一致率 <50%；模型出现退化 |
| **损失** | 训练数据污染；模型性能下降；需回退 LLM 驱动兜底；沉没成本 |
| **回滚能力** | 通过模型版本化 + 灰度发布回退到上一稳定版本；最差回退到 LLM 驱动 + 规则兜底（当前架构） |
| **预案** | 训练数据质量门禁；模型版本化 + 灰度发布；FAIL-OPEN 兜底（模型不可用→规则+LLM 兜底） |

### 3.2 风险评级

| 维度 | 级别 | 说明 |
|------|------|------|
| 技术风险 | **中** | 跨语言训练 pipeline 复杂，IPC 链路活性需保证 |
| 兼容风险 | **中** | 需与 HC-1 ~ HC-11 兼容，特别是 HC-5（reward 边界）和 HC-9（plugin 只透传） |
| 维护风险 | **中** | 训练数据治理、模型版本管理、评审一致率监控要求高 |
| 时间风险 | **中** | 闭环周期长，需迭代优化 |

### 3.3 可验证假设

| 编号 | 假设 | 验证方式 |
|------|------|---------|
| H-1 | 算法驱动覆盖率 ≥ 70% 后，LLM 调用频次下降 ≥ 50% | A/B 测试 + 调用日志统计 |
| H-2 | Harness 评审数据训练的领域模型，在意图识别准确率上比纯规则 ≥ +5% | 回测对比 |
| H-3 | Agent 接管边界清晰后，复杂查询处理延迟下降 ≥ 30% | 性能压测 |
| H-4 | 训练闭环建立后，A7/A8 自进化效率提升 ≥ 30% | 自进化系统指标对比 |

### 3.4 推荐

**推荐方案 C：算法驱动 + Harness 训练闭环**

理由：
1. **与用户偏好一致**：用户明确"倾向深度学习，不倾向大语言模型"+"核心是数据驱动，底层逻辑万物皆数"
2. **与 DreamOS 已有资产衔接**：自进化系统（EvolutionEngine + A7/A8 + 认知系统 verify 闭环）天然是训练闭环的基础
3. **与已规划架构兼容**：dream-harness-bridge SPEC v0.4 已定义边界守护硬约束（HC-1 ~ HC-11），本方案在其上扩展，不破坏边界
4. **突出 LLM 训练价值**：LLM 从"执行者"升级为"训练者"，价值最大化——这正是用户的核心诉求
5. **三段式分工清晰**：算法驱动（高频低成本）+ Harness 评审训练（中频中成本）+ Agent 接管（低频高成本），符合工业级 AI 系统分层

---

## 第四段（D4）— 四段 Spec

### 4.1 背景与目标

#### 4.1.1 问题

DreamOS 当前架构以"规则 + LLM"为主，缺乏训练有素的领域 ML 模型作为中间层。LLM 既是执行者又是兜底者，价值未充分凸显；DreamOS 算法驱动能力未充分建设；自进化系统虽有 verify 闭环但未输出可训练数据集。

#### 4.1.2 为什么做

1. **凸显 LLM 训练价值**：LLM 从"执行者"升级为"训练者"，价值最大化——这是用户核心诉求
2. **建设算法驱动护城河**：DreamOS 的领域深度（22 交易节点 + 三大思维链 + 贝叶斯进化）应通过训练有素的 ML 模型固化
3. **形成自我进化闭环**：算法 → Harness 评审 → 标注 → 训练 → 算法升级 → 自进化系统增强
4. **降低长期 LLM 成本**：算法驱动覆盖 70%+ 后，LLM 调用下降 50%+，成本可控

#### 4.1.3 成功标准（量化）

| 编号 | 指标 | 目标值 | 验证方式 |
|------|------|--------|---------|
| SC-1 | 算法驱动覆盖率 | ≥ 70% | 调用日志统计 |
| SC-2 | LLM 调用频次下降 | ≥ 50% | A/B 测试对比 |
| SC-3 | 领域模型意图识别准确率 | 比纯规则 +5%+ | 回测对比 |
| SC-4 | Harness 评审一致率 | ≥ 70% | 评审日志统计 |
| SC-5 | 自进化系统效率提升 | ≥ 30% | A7/A8 指标对比 |
| SC-6 | 端到端延迟（T3 接管） | 下降 ≥ 30% | 性能压测 |

#### 4.1.4 不做范围（排除清单）

- ❌ 不重写 DreamOS 核心 Python 代码（HC-1a）
- ❌ 不替换已规划的 dream-harness-bridge 分层嵌入架构
- ❌ 不让 Harness 参与 reward 计算（HC-5）
- ❌ 不让 Plugin 做交易决策（HC-9）
- ❌ 不绕过硬约束检查（HC-2）
- ❌ 不在 `dreamos/` 下引入 Harness 依赖（HC-10）

### 4.2 方案概述

#### 4.2.1 核心方案：三层分工架构

```
┌──────────────────────────────────────────────────────────────────────┐
│  Layer 3: Agent 接管层（低频高成本，<10% 流量）                       │
│  ──────────────────────────────────────────────────────────────────  │
│  触发：算法置信度 < 阈值 T_agent (默认 0.35)  或  复杂度 = T3         │
│  执行：Harness 直接调用 Agent 能力（subagent / model plugin）         │
│  产出：Agent 处理结果 + 标注数据 → Layer 2 训练池                     │
│  边界：Agent 不得参与 reward 计算（HC-5），只做"难例处理 + 标注"      │
└──────────────────────────────────────────────────────────────────────┘
                              ↑ 难例上传
                              ↓ 训练反哺
┌──────────────────────────────────────────────────────────────────────┐
│  Layer 2: Harness 评审训练层（中频中成本，20-30% 流量）               │
│  ──────────────────────────────────────────────────────────────────  │
│  三类评审：                                                          │
│    (a) 同步影子评审（高风险：交易执行，阻塞）                         │
│    (b) 异步影子评审（中风险：分析类，不阻塞，积累训练数据）           │
│    (c) 主动标注（Active Learning 挑选难例送 LLM 标注）                │
│  产出：                                                              │
│    - 标注数据集 → Layer 1 模型训练                                    │
│    - 评审一致率指标 → 监控 Dashboard                                  │
│    - 失败案例 → Layer 3 Agent 接管                                    │
│  边界：                                                              │
│    - HC-9：Harness 只评审+标注，不做交易决策                          │
│    - HC-5：reward 仍由 DreamOS 内部计算                               │
│    - HC-7：评审异常 → FAIL-OPEN 中性兜底                              │
└──────────────────────────────────────────────────────────────────────┘
                              ↑ 训练数据
                              ↓ 模型升级
┌──────────────────────────────────────────────────────────────────────┐
│  Layer 1: 算法驱动层（高频低成本，70-90% 流量，主流量）                │
│  ──────────────────────────────────────────────────────────────────  │
│  三类算法：                                                          │
│    (i) 规则识别（零成本，覆盖明确意图，当前已具备）                   │
│   (ii) 领域 ML 模型（训练有素的轻量模型，覆盖中等难度意图）           │
│        - 意图分类器（基于 BERT/小模型 fine-tune）                    │
│        - 槽位抽取器（NER 模型）                                       │
│        - 复杂度分级器（已具备，纯规则 T0-T3）                          │
│  (iii) CBR 案例检索（KNN 相似度，用户偏好已记录）                     │
│  产出：                                                              │
│    - 意图识别结果 + 置信度                                           │
│    - 难例（置信度 < T_review）→ Layer 2 评审                          │
│    - 极难例（置信度 < T_agent）→ Layer 3 Agent 接管                   │
│  边界：                                                              │
│    - 算法层是 DreamOS 内部资产，不依赖 Harness                        │
│    - 模型文件版本化 + 灰度发布                                       │
│    - FAIL-OPEN：模型不可用 → 规则+LLM 兜底                            │
└──────────────────────────────────────────────────────────────────────┘
```

#### 4.2.2 核心设计原则（5 条）

| 编号 | 原则 | 含义 |
|------|------|------|
| **AP-1** | **算法优先** | 算法层处理 70%+ 流量，Harness 与 Agent 是辅助而非主导 |
| **AP-2** | **Harness 不决策** | Harness 只评审+纠偏+标注+训练，不做交易决策，不参与 reward（继承 HC-5/HC-9） |
| **AP-3** | **闭环可追溯** | 每一次算法决策 → 可选 Harness 评审 → 标注数据 → 训练 → 算法升级，全链路可追溯 |
| **AP-4** | **FAIL-OPEN 铁律** | 算法模型不可用 → 规则+LLM 兜底；Harness 评审异常 → 中性兜底；Agent 接管失败 → 默认安全（继承 HC-7） |
| **AP-5** | **数据主权** | 训练数据集主权归 DreamOS，Harness 产出经 DreamOS 认知系统沉淀（继承 HC-3） |

#### 4.2.3 接口设计

**新增 IPC 方法**（在 `python-server/protocol.py` 注册）：

| 方法 | 方向 | 用途 |
|------|------|------|
| `algorithm_recognize` | TS → Python | Harness 调用 DreamOS 算法层做意图识别 |
| `shadow_review` | TS → Python | Harness 异步/同步评审结果回传 DreamOS |
| `request_label` | Python → TS（callback） | DreamOS 主动请求 Harness 标注难例 |
| `fetch_training_dataset` | TS → Python | Harness 拉取训练数据集（脱敏后） |
| `publish_model_update` | Python → TS（事件） | DreamOS 模型版本更新通知 Harness |
| `agent_takeover` | TS → Python | Agent 接管处理难例，结果回传 |

**事件流新增类型**（扩展 HM-4 Session Log）：

| 事件 | 字段 | 用途 |
|------|------|------|
| `algorithm.decision` | intent/confidence/model_version/algorithm_path | 算法层决策事件 |
| `shadow.review` | review_type/verdict/consistency_score/labeled_data | Harness 评审事件 |
| `training.dataset` | dataset_id/sample_count/quality_score | 训练数据集生成事件 |
| `model.update` | model_id/version/rollout_strategy | 模型更新事件 |
| `agent.takeover` | complexity_tier/reason/agent_id/duration | Agent 接管事件 |

#### 4.2.4 与现有硬约束的兼容性

| 硬约束 | 影响 | 兼容性 | 验证方式 |
|--------|------|--------|---------|
| HC-1a/1b/1c 边界规则 | 算法层在 DreamOS 内，评审在 harness-bridge | ✅ 兼容 | git diff + import 审计 |
| HC-2 硬约束生效 | 算法层仍执行硬约束检查 | ✅ 兼容 | 集成测试 |
| HC-3 单一真相源 | 训练数据集主权归 DreamOS | ✅ 兼容 | 数据流审计 |
| HC-4 认知 DB 单进程 | 训练数据通过 IPC 拉取，不共享 DB | ✅ 兼容 | 跨进程只读快照 |
| **HC-5 reward 边界** | **Harness 不参与 reward，只参与评审+标注** | ✅ 兼容（强化） | 评审事件 schema 不含 reward 字段 |
| HC-6 版本锁定 | 训练 pipeline 加入版本锁定 | ✅ 兼容 | 契约测试 |
| HC-7 FAIL-OPEN | 算法/Harness/Agent 三层都 FAIL-OPEN | ✅ 兼容 | 异常注入测试 |
| **HC-9 Plugin 只透传** | **Harness 评审是"元能力"，不是"交易决策"** | ✅ 兼容（细化） | 评审结果只产出标注，不下交易指令 |
| HC-10 领域零 Harness 依赖 | 算法层在 `dreamos/` 下，不 import Harness | ✅ 兼容 | grep 审计 |
| HC-11 事件过滤 | 训练事件加入领域事件白名单 | ✅ 兼容 | 事件 schema 校验 |

> 关键澄清：**Harness 评审 ≠ Harness 决策**。评审是对算法输出的二阶评判（"你识别对了吗？"），不是对交易的一阶决策（"应该买还是卖？"）。HC-9 禁止的是后者，不禁止前者。

#### 4.2.5 短路逻辑（意图识别优先级链）

当用户输入到达 IntentEngine 时，识别器按以下优先级短路：

```
algorithm_recognize (置信度阈值 0.70)
    ↓ degraded=True (ENABLE_ALGORITHM_LAYER=0 或异常)
rule_based (置信度阈值 0.55)
    ↓ confidence < 0.55
llm_based (置信度阈值 0.55)
    ↓ confidence < 0.55
clarify (置信度阈值 0.35，向用户请求澄清)
```

**短路规则**：
1. `algorithm_recognize` 先行：当 `ENABLE_ALGORITHM_LAYER=1` 时，先调用算法层（领域 ML 模型 + 规则），置信度 ≥ 0.70 直接返回
2. `rule_based` 兜底：算法层 `degraded=True` 或置信度 < 0.70 时，回退到现有规则识别器（阈值 0.55）
3. `llm_based` 降级：规则识别置信度 < 0.55 时，触发 LLM 识别（阈值 0.55）
4. `clarify` 最终兜底：LLM 识别置信度 < 0.35 时，向用户请求澄清

**功能开关**：
- `ENABLE_ALGORITHM_LAYER=0`（Phase 0 默认）：`algorithm_recognize` IPC 返回 `degraded=True`，TS 侧跳过算法层，直接进入 `rule_based` → `llm_based` 现有链路
- `ENABLE_ALGORITHM_LAYER=1`（Phase 0 POC 启用）：算法层激活，按短路逻辑执行

> 此设计确保 Phase 0 POC 期间默认关闭不影响现有交易功能，启用时可验证算法驱动闭环。

### 4.3 实现路径（最小单元 → 递进 → 完善）

#### 4.3.1 Phase 0 — 最小闭环 POC（必做，不可跳过）

**目标**：用最简单的意图识别场景验证"算法 → 评审 → 标注 → 训练"闭环可行。

**范围**：
1. 算法层：用现有 `rule_based.py` 作为基线算法（无新训练）
2. 评审层：写一个 Cordis plugin，对规则识别结果做"影子评审"（不阻塞），用 LLM-as-Judge 比对
3. 标注层：评审不一致的样本存入训练数据集（SQLite，DreamOS 内部）
4. 训练层：用现有 `bayesian_memory_updater.py` 做最小化训练（置信度调整）
5. 验证：通过 `complexity_classifier.py` 的 T0/T1 案例验证闭环

**Phase 0 验收门槛**：

| 门槛 | 验证方式 | 失败后果 |
|------|---------|---------|
| V0-1 | 算法决策事件在 session log 中可见 | 不通过则事件流价值不成立 |
| V0-2 | Harness 评审结果回传 DreamOS（IPC 链路活性） | 不通过则闭环不成立 |
| V0-3 | 标注数据集含 ≥10 条评审不一致样本 | 不通过则标注价值不成立 |
| V0-4 | 训练后规则置信度有可观察变化 | 不通过则训练闭环不成立 |
| V0-5 | 评审异常时 FAIL-OPEN 中性兜底 | 不通过则违反 HC-7 |
| V0-6 | DreamOS 核心代码 0 修改（只在 harness-bridge 内） | 不通过则违反 HC-1a |
| V0-7 | 评审结果不含 reward 字段（HC-5 边界守护） | 不通过则违反 HC-5 |

#### 4.3.2 Phase 1 — 领域 ML 模型训练

**前置**：Phase 0 全绿。

**范围**：
1. 用 Phase 0 标注数据集训练第一个领域 ML 模型（意图分类器，BERT-small 或 Qwen-1.5B fine-tune）
2. 模型版本化 + 灰度发布（10% → 50% → 100%）
3. A/B 测试：算法层（规则 + ML 模型）vs 纯规则，对比 LLM 调用频次
4. Harness 评审一致率 Dashboard（前端可视化）

**Phase 1 验收门槛**：

| 门槛 | 验证方式 |
|------|---------|
| V1-1 | 算法层覆盖率 ≥ 50%（中间目标） | 调用日志统计 |
| V1-2 | LLM 调用频次下降 ≥ 30%（中间目标） | A/B 对比 |
| V1-3 | Harness 评审一致率 ≥ 60% | 评审日志统计 |
| V1-4 | 模型灰度发布机制可用 | 灰度回滚测试 |
| V1-5 | FAIL-OPEN 兜底生效（模型不可用时回退规则+LLM） | 故障注入测试 |

#### 4.3.3 Phase 2 — Agent 接管边界落地

**前置**：Phase 1 验证算法驱动有效。

**范围**：
1. 定义 T3 复杂度的 Agent 接管边界（明确"超出能力"判据）
2. 接入 Harness Subagent（外部 API 并行化：经典指标 8092 + 基本面 3456）
3. Agent 处理结果自动标注 → 反哺训练数据集
4. T3 处理延迟下降验证

**Phase 2 验收门槛**：

| 门槛 | 验证方式 |
|------|---------|
| V2-1 | T3 案例 100% 走 Agent 接管 | 复杂度分级器日志 |
| V2-2 | Agent 处理结果自动入训练数据集 | 数据集审计 |
| V2-3 | T3 端到端延迟下降 ≥ 30% | 性能压测 |
| V2-4 | Agent 接管失败时 FAIL-OPEN | 故障注入 |
| V2-5 | Agent 不参与 reward 计算（HC-5 边界） | 事件 schema 校验 |

#### 4.3.4 Phase 3 — 训练闭环全栈整合

**前置**：Phase 2 全绿。

**范围**：
1. 训练数据集接入 DreamOS 认知系统（`record` 工具）
2. 模型版本化与认知 `verify` 闭环联动
3. G 层升级为事件流消费（P0-1 借鉴方向落地）
4. 自进化系统（EvolutionEngine + A7/A8）消费事件流
5. A7/A8 自进化效率提升验证

**Phase 3 验收门槛**：

| 门槛 | 验证方式 |
|------|---------|
| V3-1 | 算法驱动覆盖率 ≥ 70% | 日志统计 |
| V3-2 | LLM 调用频次下降 ≥ 50% | A/B 对比 |
| V3-3 | 领域模型意图识别准确率比纯规则 +5%+ | 回测对比 |
| V3-4 | Harness 评审一致率 ≥ 70% | 评审日志 |
| V3-5 | A7/A8 自进化效率提升 ≥ 30% | 自进化指标对比 |
| V3-6 | 全链路可追溯（算法决策→评审→标注→训练→升级） | 事件链路审计 |

#### 4.3.5 Phase 4 — 持续优化与扩展（长期）

**范围**：
1. 多模型集成（多个领域 ML 模型投票）
2. Active Learning 主动挑选难例送 Harness 标注
3. 联邦学习探索（多策略模型联邦）
4. Trajectory View 可视化（P0-3 借鉴方向）
5. Creator Mode 整合做梦部（P2-1 借鉴方向）

### 4.4 验收标准

#### 4.4.1 功能验收（Given/When/Then）

**FA-1: 算法层处理简单意图**
```
Given 用户输入 "BTC 多少钱"（T0 简单查询）
When 算法层处理
Then 应返回 market_query 意图 + confidence ≥ 0.9
    And 不触发 Harness 评审（T0 直答）
    And 不触发 LLM 调用
    And 事件流含 algorithm.decision 事件
```

**FA-2: Harness 影子评审**
```
Given 算法层处理 T1 意图识别 confidence = 0.6（低于评审阈值 T_review=0.7）
When Harness 影子评审
Then 应在 200ms 内返回评审结果（不阻塞算法层）
    And 评审结果含 verdict + consistency_score + labeled_data
    And 若评审一致率 ≥ 0.85，标注数据入训练集
    And 若评审一致率 < 0.5，案例上送 Layer 3 Agent
    And 评审异常时 FAIL-OPEN 中性兜底
```

**FA-3: Agent 接管 T3**
```
Given 用户输入 "对比 BTC 和 ETH 的技术面 + 资金面 + 链上 + 宏观"（T3 深度研究）
When 复杂度分级器判定 T3
Then 应跳过 LLM 识别
    And 委托 Harness Agent 接管
    And Agent 处理结果含标注数据 → 入训练集
    And Agent 不参与 reward 计算（HC-5 边界）
    And 接管失败时 FAIL-OPEN（默认 deep_analysis + 兜底 LLM）
```

**FA-4: 训练闭环**
```
Given 训练数据集累计 ≥ 1000 条样本
When 触发模型增量训练
Then 应产出新模型版本
    And 通过质量门禁（验证集准确率不下降）
    And 灰度发布 10% → 50% → 100%
    And 旧版本可回滚
    And 训练事件入认知系统（record）
    And 模型升级后通过 verify 闭环验证
```

**FA-5: 边界守护**
```
Given 任何场景
When 评审/标注/训练流程执行
Then Harness 评审结果不含 reward 字段（HC-5）
    And Plugin 不下交易指令（HC-9）
    And DreamOS 内部代码不 import Harness 类型（HC-10）
    And 评审异常时 FAIL-OPEN（HC-7）
    And 训练数据集主权在 DreamOS（HC-3）
```

#### 4.4.2 非功能验收

| 维度 | 标准 | 验证方式 |
|------|------|---------|
| **性能** | 算法层 P99 延迟 ≤ 100ms；Harness 评审延迟 ≤ 200ms（异步）；Agent 接管延迟 ≤ 2s | 性能压测 |
| **可靠性** | 三层任一层故障 → FAIL-OPEN 兜底；年可用性 ≥ 99.5% | 故障注入 + 长期运行测试 |
| **可维护性** | 模型版本化 + 灰度发布 + 回滚能力；训练数据可审计 | 维护流程测试 |
| **可观测性** | 全链路事件流；评审一致率 Dashboard；训练数据质量监控 | 监控指标检查 |
| **安全性** | 训练数据脱敏；模型文件签名；Plugin 代码审查 | 安全审计 |

#### 4.4.3 排除清单（不验收项）

- ❌ 不验收 LLM 训练领域模型的具体性能指标（依赖外部 LLM 进步）
- ❌ 不验收 Agent 接管的具体业务逻辑（依赖 Harness Subagent 能力）
- ❌ 不验收 Trajectory View UI（Phase 4 范围）
- ❌ 不验收联邦学习（Phase 4 范围）

---

## 五、目录结构（新增）

```
dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/
├── SPEC.md                                  # 已有：分层嵌入主 SPEC
├── SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md  # 本文件
├── packages/
│   ├── bridge-core/src/
│   │   ├── algorithm-listener.ts           # 新增：监听 algorithm.decision 事件
│   │   ├── shadow-reviewer.ts              # 新增：Harness 影子评审 plugin
│   │   ├── label-requester.ts              # 新增：主动请求标注 plugin
│   │   ├── agent-takeover.ts               # 新增：T3 Agent 接管 plugin
│   │   └── training-data-bridge.ts         # 新增：训练数据 IPC bridge
│   ├── python-server/
│   │   ├── algorithm_server.py             # 新增：算法层 IPC 服务
│   │   ├── training_dataset.py             # 新增：训练数据集管理
│   │   ├── model_registry.py               # 新增：模型版本注册表
│   │   └── quality_gate.py                 # 新增：训练数据质量门禁
│   └── session-consumer/
│       └── training-event-consumer.ts      # 新增：训练事件消费 adapter
└── tests/
    └── integration/
        ├── test_algorithm_closed_loop.ts   # Phase 0 闭环测试
        ├── test_shadow_review.ts           # 影子评审测试
        ├── test_agent_takeover.ts          # Agent 接管测试
        └── test_training_pipeline.ts       # 训练 pipeline 测试
```

---

## 六、风险清单与缓解

| 编号 | 风险 | 级别 | 缓解措施 |
|------|------|------|---------|
| TR-1 | 训练数据稀缺导致模型性能不足 | 高 | 真实+合成混合数据集；Active Learning 挑选难例；FA-4 质量门禁 |
| TR-2 | Harness 评审一致率低（<50%） | 高 | 评审前先校准 LLM-as-Judge；不一致案例上送 Agent；FAIL-OPEN 兜底 |
| TR-3 | 模型训练后性能退化 | 中 | 版本化 + 灰度发布；回滚机制；验证集监控 |
| TR-4 | Agent 接管边界模糊 | 中 | T3 复杂度判据明确；置信度阈值 T_agent=0.35 硬约束 |
| TR-5 | 跨语言训练 pipeline 复杂 | 中 | 双端 SDK（F-07）；契约测试（F-09）；事件信封模式（F-12） |
| TR-6 | 训练数据污染 | 中 | 质量门禁（quality_gate.py）；评审一致率监控；异常数据隔离 |
| TR-7 | 边界失守（HC-5/HC-9 被绕过） | 极高 | 评审事件 schema 不含 reward 字段；Plugin 静态扫描；代码审查 checklist |
| TR-8 | LLM-as-Judge 自身偏差 | 中 | 多模型集成评审；定期人工抽样校准 |
| TR-9 | 训练成本失控 | 中 | 训练预算管控；增量训练而非全量；GPU 资源调度 |
| TR-10 | 自进化系统被错误信号引导 | 高 | reward 仍由 DreamOS 内部计算（HC-5）；训练数据经 verify 闭环验证 |

---

## 七、开放问题

| 编号 | 问题 | 优先级 | 阻塞 Phase |
|------|------|--------|-----------|
| OQ-A1 | 领域 ML 模型选型：BERT-small vs Qwen-1.5B fine-tune vs 其他？ | 高 | Phase 1 |
| OQ-A2 | 训练数据格式标准化：JSONL 还是 JSON Schema 双端 codegen？ | 高 | Phase 0 |
| OQ-A3 | LLM-as-Judge 校准机制：如何确保评审一致率可观察提升？ | 高 | Phase 0 |
| OQ-A4 | Active Learning 难例挑选策略：基于不确定性还是基于一致性？ | 中 | Phase 4 |
| OQ-A5 | Agent 接管失败时的回退策略：直答 vs 兜底 LLM vs 拒绝？ | 中 | Phase 2 |
| OQ-A6 | 模型灰度发布机制：基于流量百分比还是基于用户分桶？ | 中 | Phase 1 |
| OQ-A7 | 训练数据脱敏标准：金融数据合规要求？ | 高 | Phase 0 |
| OQ-A8 | 自进化系统与训练闭环的 reward 边界细化：reward 还是 DreamOS 独占吗？ | 高 | Phase 3 |

---

## 八、与已有 SPEC 的关系

| 文档 | 关系 |
|------|------|
| [SPEC.md](./SPEC.md) v0.4 | 父 SPEC，本文件是其垂直延伸（训练闭环层）；继承 HC-1 ~ HC-11 全部硬约束 |
| [SPEC_INTENT_DREAMOS_OPTIMIZATION.md](./SPEC_INTENT_DREAMOS_OPTIMIZATION.md) | 兄弟 SPEC，意图识别优化；本文件将其"算法驱动"维度补全 |
| [RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md](../RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md) | 调研基础，P0-1 事件流升级是本方案 Phase 3 的前置 |
| [D-调研方法论.md](../../2-KNOWLEDGE/5-METHODOLOGY/D-调研方法论.md) | 方法论来源 |
| [project_memory.md](../../../../../.trae-cn/memory/projects/-Users-zhangjiangtao-WorkBuddy-dreambuddy-v2--p2-5f8e8db8067187fd2690/project_memory.md) | 硬约束清单来源 |

---

## 九、D4 出口选择点 ⚠️ ⚠️ 必须执行 ⚠️ ⚠️

D 系列调研/分析/设计已完成。继续走三链逻辑：

> **(a) 继续到 Z1 规划** — 按标准流程进入 Z 系列（规划→路径→验收→执行）
>
> **(b) 授权跳过 Z 直接到 E1 执行** — 跳过规划阶段，直接进执行（需用户明确授权）
>
> **(c) 其他** — 请说明你的想法
>
> *⚠️ 默认：30 秒内无回复，自动走 (a) 继续到 Z1*

**规则**：
- 用户选 (a) → 进入 Z1 规划阶段
- 用户选 (b) → 记录 override（`from=D4, to=E1, reason=用户授权跳过Z`, `user_auth=引用用户消息`）→ 进入 E1 执行
- 用户不回复 → 按默认走 Z1
- 用户选 (c) → 听用户指令

---

## 十、变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-09-17 | 首版：按 D-调研方法论形成；三层分工架构（算法驱动/Harness 评审训练/Agent 接管）；4 个 Phase 实现路径；5 条设计原则；与 HC-1 ~ HC-11 兼容性分析 |
