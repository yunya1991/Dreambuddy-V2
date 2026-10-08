# DreamOS SKILL 选择编排架构 SPEC (SPEC-SKILL-ORCH)

> **版本**: v0.2 (评审修改稿)
> **日期**: 2026-10-08
> **状态**: 🟡 同行评审已完成 · 5 Major 已修改 · 待用户复审 · 不含实现代码
> **作者**: dreambuddy-v2 架构组（基于多 Agent 辩论 + 代码审计 + 加权框架对比）
> **定位**: 将 DreamOS SACG 从"细粒度节点编排"演进为"粗粒度 SKILL 选择编排"，DSH 驱动执行时优先调用系统节点能力，缺失才降级 LLM 推理，解决"编排机械 + 大模型驱动编排过度复杂"两大痛点
> **调研方法**: recall 认知记忆（命中 8 条）+ 4 维度并行代码审计（SACG编排 / 三大SKILL支柱 / DSH驱动 / 意图链路）+ 6 角色多 Agent 辩论 + 6 维加权框架对比
>
> **与既有文档关系**:
> | 既有文档 | 维度 | 关系 |
> |----------|------|------|
> | [FRONTEND3_DREAMOS_DSH_GLOBAL_ARCH_SPEC.md](./FRONTEND3_DREAMOS_DSH_GLOBAL_ARCH_SPEC.md) (v1.2, 2026-09-29) | 三层 OS 架构 + 11 缺口现状 | **本 SPEC 是其§三 DreamOS SACG 编排层的演进方案**，不否定三层架构，只调整编排粒度 |
> | [SYSTEM_ARCHITECTURE_OVERVIEW.md](../SYSTEM_ARCHITECTURE_OVERVIEW.md) (v2.3, 2026-07-03) | DreamOS 三层+SACG 四层职责表 | **本 SPEC §三 重定义 S/A 层职责**，C/G 层职责不变 |
> | [DSH_SUBAGENT_ARCHITECTURE_SPEC.md](../dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md) (v0.2) | DSH 8 Subagent 详设 | **本 SPEC §四 复用其降级链模式**，不改动 subagent 实现 |
> | [dream-science-framework-research](../skills/dream-science-framework-research/SKILL.md) | 多 Agent 辩论框架研究 | **本 SPEC 的论证方法论来源** |
> | 框架研究记忆 VM-1791390096373 | 节点编排 vs SKILL 编排评估结论 | **本 SPEC 的决策依据**（加权 6.55 vs 4.55） |
>
> **后续**: 同行评审通过 → 用户批准 → 进入阶段 1 实施（仅本 SPEC §六 范围）

---

## 一、现状与问题

### 1.1 编排"机械"的三大根源（代码证据）

| # | 问题 | 证据 | 影响 |
|---|------|------|------|
| P1 | 编排器是硬编码线性流水线 | [orchestrator_v2.py:172-268](../dreamos/capabilities/trading/orchestrator_v2.py#L172-L268) `run_cycle()` 无论意图如何都走 CoinSelector→YijingSignal→V15Executor→SignalRouter→CognitiveReviewer | SACG 动态编排能力未被使用，所有意图走同一条链路 |
| P2 | 意图→链路映射是静态表 | [smart-router.ts:92-160](../../3.1-FRONTEND/src/lib/intent/smart-router.ts#L92-L160) `ROUTE_MAP` + [graph_planner.py:76-135](../dreamos/core/arrange/graph_planner.py#L76-L135) 依赖 `intent.recommended_chain` | 新增意图/链路需改多处映射表，耦合度高 |
| P3 | SKILL 执行是纯 LLM Prompt，不调系统节点 | [skill_adapter.py:120-150](../dreamos/adapters/skill_adapter.py#L120-L150) `SkillNode` 把 SKILL.md 全文喂给 LLM 生成结构化输出 | 无真实数据支撑，易产生幻觉，且单次 2000+ token |

### 1.2 "大模型驱动编排过度复杂"的本质

当前设计意图是让 LLM 从 A0-A9 + C0-C8 + F1-F5 约 **25+ 节点**中选择执行链路，但：
- 决策空间过大（25 节点的组合爆炸）
- LLM 输出不稳定，难以保证编排正确性
- 实际落地退化为 P2 的硬编码映射表，LLM 编排形同虚设
- 全链路至少 3 次 LLM 调用（意图 LLM + 编排 LLM + 节点 LLM），延迟 ~30s

### 1.3 已就绪的基础设施（可直接复用）

| 能力 | 现状 | 复用方式 |
|------|------|---------|
| 三大 SKILL 支柱 | 6-Trading 32 个 + 1-ARCHITECTURE 25 个 + 科研 dream-science-* 系列 | 统一注册到 SKILL 能力中心 |
| Autonomy Boundary | 124 个 SKILL 100% 覆盖（VM-1791226814783） | 作为 SKILL 执行的权限边界 |
| DSH 8 Subagent | technical/sentiment/macro/flow/valuation/onchain/risk/portfolio | 作为系统节点能力的执行入口 |
| 算法短路降级链 | [algorithm_enhanced_agent.py:72-156](../dream-harness-bridge/integration/algorithm_enhanced_agent.py#L72-L156) | 复用到 DSH 执行引擎 |
| SkillsRegistry | [skills-registry.ts:36-78](../../24-图结构上下文压缩/planner/skills-registry.ts#L36-L78) 支持按 chain/category/stage/tag 查询 | 扩展为统一 SKILL 能力注册中心 |

### 1.4 替代方案评估（排除框架锁定）

| 方案 | 描述 | 不选理由 |
|------|------|---------|
| **方案 A（本方案）**: SKILL 选择编排 | 编排粒度上移到 SKILL 级，DSH 执行时节点优先 + LLM 兜底 | — |
| 方案 B: 精简节点 + 保留节点编排 | 将 25+ 节点精简到 8-10 个，保留 GraphPlanner 节点选择逻辑 | 节点精简后仍然是"意图→节点"硬编码映射，本质问题未解决；且节点拆分涉及大量代码改动 |
| 方案 C: 混合编排（意图级规则 + 节点级 LLM） | 意图→链路用规则，链路内节点选择用 LLM | 仍然依赖 LLM 做节点选择，"过度复杂"问题未根除；且 LLM 节点选择的不稳定性依然存在 |
| 方案 D: 完全去中心化（每个 SKILL 自主决定） | 去掉中心编排器，SKILL 之间通过消息传递自主协作 | 复杂度更高，调试困难，违反"编排层纯编排"硬约束；适合极复杂场景，当前阶段过度设计 |

**结论**: 方案 A 在"降低编排复杂度"和"保留系统节点能力"之间取得最佳平衡，且复用现有基础设施最多，迁移成本最低。

---

## 二、目标架构

### 2.0 部署边界（M1 澄清）

**现有代码边界**：
- 前端侧（TypeScript / Next.js）：`/api/task/stream` → [task-manager.ts](../../3.1-FRONTEND/src/lib/task-manager.ts) → 意图识别 + 链路路由
- 后端侧（Python / DreamOS）：[orchestrator_v2.py](../dreamos/capabilities/trading/orchestrator_v2.py) → 五层交易流水线 + [intent_engine.py](../dreamos/core/sense/intent_engine.py) → 意图识别

**本方案部署决策**：编排层（S+A）和执行层（C）均部署在**前端侧（TypeScript）**，与现有 task-manager.ts 同进程。理由：
1. 现有 `/api/task/stream` + task-manager.ts 已是编排入口，改动最小
2. DSH Subagent 通过 IPC NDJSON 调用（已有 [algorithm_layer_bridge.py](../dream-harness-bridge/integration/algorithm_layer_bridge.py)），前端 TS 通过 HTTP/IPC 调用 Python 系统节点
3. 意图识别复用现有 [fallback-engine.ts](../../3.1-FRONTEND/src/lib/intent/fallback-engine.ts)（TS 实现），不引入 Python 依赖
4. DreamOS Python 侧的 orchestrator_v2 作为被调用的系统节点能力，通过 HTTP API 暴露

**调用链**：前端 ChatPanel → `/api/task/stream` → IntentAndSkillSelector（TS）→ DSHExecutionEngine（TS）→ IPC/HTTP → DSH Subagent（Python）/ orchestrator_v2（Python）

### 2.1 核心设计原则

1. **编排粒度上移**：SACG 从"选节点"变为"选 SKILL"，决策空间从 25+ 节点 → ~30 SKILL（语义更粗、更明确）
2. **系统节点优先**：DSH 执行时优先调用已验证的系统节点能力（C1-C8, F1-F5），LLM 仅在能力缺失时兜底
3. **不用 LLM 做编排决策**：SKILL 选择基于元数据语义匹配（规则 + 向量），避免"大模型驱动编排过度复杂"
4. **逻辑四层、物理两层**：S+A 合并为 IntentAndSkillSelector，C+G 保留独立（执行/状态分离是硬约束）
5. **渐进迁移、不破坏闭环**：现有 orchestrator_v2 五层流水线包装为 SKILL，双轨运行
6. **大认知系统整合**（新增）：意图识别后并行调用认知系统、知识库、索引系统，构建"认知上下文"注入 SKILL 执行

### 2.2 大认知系统整合（核心扩展）

**设计理念**：意图识别后，不是只选 SKILL，而是同步获取四类认知资源，构建完整的"认知上下文"注入 SKILL 执行：

| 认知资源 | 来源系统 | 提供什么 | 已有能力 |
|---------|---------|---------|---------|
| **经验** | 认知系统（4-MEMORY/） | 历史经验、踩坑记录、验证过的解决方案 | recall/record/verify MCP，贝叶斯置信度，向量检索 |
| **流程** | SKILL 管理系统（6-Trading + 1-ARCHITECTURE） | 做事的方法和步骤 | skill-registry.json，Autonomy Boundary 100% 覆盖 |
| **知识** | 知识库系统（2-KNOWLEDGE/） | 领域知识、策略文档、CBR 案例、硬约束 | RAG 三阶段（向量+混合+结构化）已实现，ChromaDB 3699 chunks |
| **索引** | 索引系统（0-系统文档管理 + INDEX 体系） | 文档/代码/模块的快速定位 | INDEX.md + skill-registry.json，但缺统一查询 API |

**架构图（扩展）**：

```
意图识别结果 (intent_type, entities, confidence)
  ↓
┌─────────────────────────────────────────────────────────────────────┐
│  认知上下文构建层 (Cognitive Context Builder)  [TypeScript]          │
│  并行调用四大系统，构建统一认知上下文：                                │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────────┐ │
│  │ 认知系统     │ │ 知识库 RAG    │ │ 索引系统      │ │ SKILL 注册   │ │
│  │ recall(经验)│ │ search(知识)  │ │ query(定位)   │ │ match(流程) │ │
│  └──────┬──────┘ └──────┬───────┘ └──────┬───────┘ └──────┬──────┘ │
│         └───────────────┴────────────────┴────────────────┘        │
│                          ↓                                          │
│            CognitiveContext { experiences, knowledge,              │
│                                references, skill_candidates }       │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ 认知上下文
┌───────────────────────────────▼─────────────────────────────────────┐
│  SKILL 选择 + 执行（注入认知上下文）                                  │
│  → SKILL 选择时参考认知上下文（经验匹配度、知识相关性）               │
│  → SKILL 执行时认知上下文作为 prompt 上下文注入                      │
└─────────────────────────────────────────────────────────────────────┘
```

**四大系统现状与集成点**：

| 系统 | 现状 | 集成方式 | 工作量 |
|------|------|---------|--------|
| 认知系统 | MCP recall/record/verify 已运行，向量接口已有，RAG↔认知桥接(memory_bridge.py)已运行 | 通过 MCP 调用 recall，将结果注入 CognitiveContext | 低（接口已有） |
| 知识库 RAG | 三阶段全部实现，ChromaDB 3699 chunks，CBR 200条，混合检索+权重反哺 | 通过 RAG search API 检索相关知识 | 低（接口已有） |
| 索引系统 | INDEX.md + skill-registry.json 静态索引，无统一查询 API | 新建 IndexQueryService，对索引做语义向量化（复用 bge-small-zh） | 中（需建查询层） |
| SKILL 系统 | registry 已有，选择算法已设计 | 复用现有 SkillRegistry.query | 低（已有） |

**知识沉淀闭环（新增）**：

```
SKILL 执行完成（特别是调研类 SKILL）
  ↓
知识沉淀 SKILL (knowledge-ingest)
  ├─ 1. 分类：将调研案例按领域存入 2-KNOWLEDGE/7-EXTERNAL-RESEARCH/
  ├─ 2. 向量化：自动构建 RAG 向量索引（已有 build_index.py）
  ├─ 3. 认知记录：record 到认知系统（B 级，tags 含知识分类）
  └─ 4. 索引更新：更新 INDEX.md + skill-registry.json
```

**索引系统 Transformer 方案（评估）**：

当前索引系统（INDEX.md / skill-registry.json）是静态文件，查询只能全文搜索。引入轻量 Transformer 做语义索引：

| 方案 | 描述 | 可行性 | 推荐 |
|------|------|--------|------|
| A. 复用 bge-small-zh（RAG 已用） | 对索引条目做向量化，支持语义检索 | 高，模型已部署 | ✅ 推荐 |
| B. 专用索引 Transformer（如 ColBERT） | 端到端索引+检索，效果更好 | 中，需引入新模型 | 后期考虑 |
| C. 纯 TF-IDF + 关键词 | 无 Transformer，纯统计 | 高，但语义能力弱 | 兜底方案 |

**推荐方案 A**：复用 RAG 已部署的 bge-small-zh 模型，对 INDEX.md 条目和 skill-registry.json 做向量化，存入 ChromaDB 的独立 collection。这样索引系统也具备语义检索能力，且零新模型依赖。

### 2.3 目标架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│  应用层 — 前端3.1 (Next.js, port 3001)  [TypeScript]                  │
│  ChatPanel → /api/task/stream → createAndExecuteTask                  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ 用户消息
┌───────────────────────────────▼──────────────────────────────────────┐
│  S 层 — IntentEngine  [TypeScript]                                    │
│  意图识别 (规则优先 + LLM 兜底, 复用 fallback-engine.ts)              │
│    → intent_type, entities, confidence                                 │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ 意图识别结果
┌───────────────────────────────▼──────────────────────────────────────┐
│  认知上下文构建层 — CognitiveContextBuilder  [TypeScript]              │
│  并行调用四大系统，构建统一认知上下文：                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                  │
│  │ 认知系统  │ │ 知识库RAG │ │ 索引系统  │ │ SKILL注册 │                  │
│  │ recall   │ │ search   │ │ query    │ │ match    │                  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘                  │
│       └─────────────┴─────────────┴─────────────┘                    │
│  索引层 + Transformer(bge-small-zh) 语义匹配 → 相关任务               │
│  → CognitiveContext { experiences, knowledge, references, skills }   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ 认知上下文
┌───────────────────────────────▼──────────────────────────────────────┐
│  A 层 — SkillSelector  [TypeScript]                                   │
│  SKILL 选择 (规则优先 + 向量兜底, 不用 LLM, HC-1)                      │
│  选择时参考认知上下文（经验匹配度、知识相关性）                         │
│    → SkillExecutionPlan (skill_ids, order, params, context)           │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ SkillExecutionPlan + 认知上下文
┌───────────────────────────────▼──────────────────────────────────────┐
│  DSH SubAgent 执行层  [Python]                                        │
│  按 SKILL 的 node_dependencies 调度 8 个 SubAgent：                    │
│  technical/sentiment/macro/flow/valuation/onchain/risk/portfolio      │
│  优先调用系统子节点能力 (0 token, 确定性)                              │
│  节点缺失 → LLM 推理兜底 (数据采集/联网探索)                           │
│    → 各 SubAgent 独立结果 + source 标记                                │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ SubAgent 结果集
┌───────────────────────────────▼──────────────────────────────────────┐
│  C 层 — C-Drive  [TypeScript/Python]   ← 核心计算/反射驱动层          │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ 1. Reflector 反射决策:                                          │  │
│  │    置信度低→REDO | 矛盾→INSERT_BEFORE | 预算不足→JUMP_TO         │  │
│  │    高置信+后期→EARLY_TERMINATE | 正常→CONTINUE                   │  │
│  ├────────────────────────────────────────────────────────────────┤  │
│  │ 2. Aggregator 聚合:                                             │  │
│  │    方向投票 + 置信度加权 + 分歧检测 → 中间结论                    │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  循环：SubAgent 结果 → C-Drive 反射 → 决定继续/重做/终止              │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ 中间结论 + 执行轨迹
┌───────────────────────────────▼──────────────────────────────────────┐
│  G 层 — GraphStore + Checkpointer  [TypeScript]   ← 笔记本/账本       │
│  记录所有 SubAgent 结果、反射决策、检查点、执行轨迹                     │
│  作为复盘和认知反馈的数据源                                            │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ 全部结果 + 账本记录
┌───────────────────────────────▼──────────────────────────────────────┐
│  DSH 汇总 Agent  [Python]   ← 新增                                    │
│  汇总所有 SubAgent 结果 + C-Drive 中间结论 → 最终输出                  │
│  - 交易类: 方向(LONG/SHORT/HOLD) + 置信度 + rationale + risk          │
│  - 调研类: 结构化报告 + 引用来源 + 置信度                              │
│  - 通用类: 结果摘要 + 数据来源标注                                     │
│    → FinalOutput (内容 + 置信度 + 来源 + 执行时间)                     │
└──────────────────────────────────────────────────────────────────────┘
                                │ 最终输出 + 账本历史数据
┌───────────────────────────────▼──────────────────────────────────────┐
│  DSH 自进化 Agent  [Python]   ← 新增（可选触发，不阻塞主流程）         │
│  当 C-Drive 检测到停滞/低置信度/连续失败时，触发大认知系统自进化       │
│  三大进化能力（复用现有系统）：                                        │
│  ① 认知进化调度器: Evolution提案→Critic批评→Verifier验证→Gardener修剪  │
│  ② L4自进化引擎: A8理论验证→做梦部反思→联网学习                        │
│  ③ SKILL进化: hard-case挖掘→skill优化/新增→回测验证                    │
│  产物: 候选记忆/参数/SKILL → 人工审核后 APPLIED（不自动改交易逻辑）     │
└──────────────────────────────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  知识沉淀 (后置)                                                       │
│  调研类结果 → knowledge-ingest SKILL → 入库 + 向量化 + 认知记录       │
└──────────────────────────────────────────────────────────────────────┘
```

**完整执行闭环**：
```
S(意图) → 认知上下文(经验/知识/索引/流程) → A(选SKILL) 
  → DSH SubAgent(调系统节点) → C-Drive(反射+聚合) → G(账本记录) 
  → DSH汇总Agent(最终输出) → 知识沉淀(后置)
  ↓ [可选，停滞/低置信时触发]
  DSH自进化Agent → 认知系统进化(记忆/SKILL/参数) → 人工审核后采纳
```

### 2.4 与现有三层架构的关系

| 层 | 现有职责 | 调整后职责 | 变更 |
|----|---------|-----------|------|
| 前端3.1 | 用户交互+可视化 | 不变 | 无 |
| **SACG S** | 意图识别 | 意图识别（不变） | 无 |
| **新增：认知上下文构建层** | — | **并行调用认知/知识库/索引/SKILL四系统，构建认知上下文** | 新增 |
| **SACG A** | 节点级图编排 | **SKILL 选择编排（参考认知上下文）** | 编排粒度上移 |
| **SACG C（C-Drive）** | 图执行器 + 反射 + 聚合 | **反射决策（Reflector）+ 结果聚合（Aggregator），驱动 DSH SubAgent 执行循环** | 明确为核心计算/反射驱动层 |
| **SACG G** | 图存储 + 检查点 | **笔记本/账本：记录所有结果、反射决策、执行轨迹** | 明确为账本定位 |
| DSH | 8 Subagent 隔离执行 | **8 Subagent + 汇总 Agent + 自进化 Agent** | 新增汇总 Agent 和自进化 Agent |
| **新增：知识沉淀** | — | **调研结果分类入库 + 向量化 + 认知记录** | 新增 |
| **新增：自进化** | — | **停滞时触发认知系统进化（记忆/SKILL/参数），人工审核后采纳** | 新增 |

---

## 三、核心模块设计

### 3.0 认知上下文构建层（CognitiveContextBuilder）— 新增

**职责**：意图识别后，并行调用认知系统、知识库 RAG、索引系统、SKILL 注册中心，构建统一的认知上下文，注入后续 SKILL 选择和执行。

**数据模型**：
```typescript
interface CognitiveContext {
  experiences: CognitiveExperience[];   // 认知系统 recall 结果（历史经验）
  knowledge: KnowledgeChunk[];          // 知识库 RAG 检索结果（相关知识）
  references: IndexReference[];         // 索引系统查询结果（文档/代码定位）
  skill_candidates: SkillCapability[];  // SKILL 候选列表
  built_at: number;                     // 构建时间戳
  intent_type: string;                  // 关联的意图类型
}

interface CognitiveExperience {
  memory_id: string;
  content: string;
  quality_level: 'S'|'A'|'B'|'C'|'D';
  confidence: number;
  relevance_score: number;              // 与当前意图的相关度
}

interface KnowledgeChunk {
  chunk_id: string;
  content: string;
  source_type: 'strategy_doc'|'cbr_case'|'hard_constraint'|'external_research';
  domain: string;
  score: number;
}

interface IndexReference {
  ref_id: string;
  title: string;
  path: string;
  category: 'doc'|'skill'|'module'|'code';
  description: string;
}
```

**执行流程**：
```
意图识别结果 (intent_type, entities, confidence)
  ↓
并行调用（Promise.all，超时 ≤ 2s）：
  ├─ 认知系统: recall(context=intent+entities, top_k=5, min_quality='C')
  ├─ 知识库 RAG: search(query=intent, domain_filter=intent_type, top_k=5)
  ├─ 索引系统: IndexQueryService.query(intent, top_k=5)
  └─ SKILL 注册: SkillRegistry.query({intent_type, top_k=10})
  ↓
聚合 + 去重 + 按相关度排序
  ↓
输出: CognitiveContext
```

**关键约束**：
- 四系统**并行调用**，总延迟 ≤ 2s（任一系统超时则跳过，不阻塞）
- 认知上下文**只读**，不修改任何源系统数据
- 经验/知识/引用数量受限（各 top_k=5），避免上下文膨胀
- 上下文注入 SKILL 执行时，需标注来源（experience/knowledge/reference）

**与现有系统的集成**：
- 认知系统：通过 MCP `recall` 调用（已有接口）
- 知识库 RAG：通过 `2-KNOWLEDGE/9-RAG-INFRA/rag_engine/hybrid_retriever.py` 调用（已有接口）
- 索引系统：新建 `IndexQueryService`（需建设，见 §3.5）
- SKILL 注册：复用 `SkillRegistry.query`（已有）

### 3.1 SKILL 能力注册中心

**职责**：统一管理三大支柱 SKILL 的元数据，提供语义匹配查询。

**数据模型**：
```typescript
interface SkillCapability {
  skill_id: string;              // 唯一标识，如 "dream-strategy-designer"
  name: string;                  // 显示名
  capability_id: 'trading' | 'research' | 'dev';  // 三大支柱分类
  chain?: 'A' | 'C' | 'F' | 'G' | 'T';            // 可选，对应 DreamOS 链
  tags: string[];                // 能力标签，如 ['backtest','validation']
  description: string;           // 语义描述（用于向量匹配）
  autonomy_boundary: string;     // 权限边界声明
  node_dependencies: string[];   // 依赖的系统节点 ID，如 ['C1','C2','F1']
  estimated_tokens: number;      // LLM 兜底时的预估 token
  status: 'active' | 'shadow' | 'proposed';
  skill_path: string;            // SKILL.md 路径
}
```

**注册机制**：
- 扫描目录：`6-Trading/skills/*/SKILL.md` + `1-ARCHITECTURE/skills/*/SKILL.md` + `.trae/skills/dream-science-*/SKILL.md`
- 解析 frontmatter + `## Autonomy Boundary` 段落
- 生成 `skill-registry.json`（已有基础，扩展字段）
- 支持热更新（新增 SKILL 自动注册）

**查询接口**：
```typescript
interface SkillQuery {
  intent_type: string;           // 意图类型
  capability_id?: 'trading'|'research'|'dev';
  tags?: string[];
  semantic_query?: string;       // 语义描述（向量匹配用）
  top_k?: number;
}

querySkills(query: SkillQuery): SkillCapability[]
```

**node_id → DSH Subagent 映射表（m2 补充）**：

SKILL 声明的 `node_dependencies` 使用 DreamOS 节点 ID（如 C1, F1），执行引擎通过此映射表找到对应的 DSH Subagent：

| node_id | 对应 DSH Subagent | capability_id | 说明 |
|---------|------------------|---------------|------|
| C1, C2, C3 | DSH_TECHNICAL | analysis.technical | 技术指标（EMA/RSI/MACD） |
| F1 | DSH_SENTIMENT | analysis.sentiment | 情绪面（新闻/FGI） |
| F5 | DSH_MACRO | analysis.macro | 宏观面（利率/通胀/GDP） |
| F2 | DSH_FLOW | analysis.flow | 资金面（主力/北向资金） |
| F3 | DSH_VALUATION | analysis.valuation | 估值面（PE/PB/DCF） |
| F4 | DSH_ONCHAIN | analysis.onchain | 链上面（活跃地址/余额） |
| — | DSH_RISK | analysis.risk | 风险面（VaR，纯算法，HC-3） |
| — | DSH_PORTFOLIO | analysis.portfolio | 组合面（仓位/再平衡） |
| A_ORCH | orchestrator_v2 | trading.execution | 五层交易流水线（A→B→C→D→E） |
| A0-A9 | (无直接 subagent) | — | A 链方法论节点，走 LLM 兜底 |
| G1, G2 | (无直接 subagent) | — | G 链治理节点，走 LLM 兜底 |

### 3.2 IntentAndSkillSelector（S+A 合并）

**职责**：接收用户消息，识别意图，选择 SKILL，输出执行计划。

**意图识别准确率基线（M4 补充）**：
- 现有 [fallback-engine.ts](../../3.1-FRONTEND/src/lib/intent/fallback-engine.ts) 规则匹配准确率约 **85%**（基于 10 类意图的关键词/正则）
- LLM 兜底后整体准确率约 **92%**
- SKILL 选择准确率（F2 ≥ 80%）的前置条件：意图识别置信度 ≥ 0.7
- **意图错误容错**：当意图识别置信度 < 0.7 时，SKILL 选择返回 top-3 候选并请求用户澄清，而非直接执行

**执行流程**：
```
用户消息
  ↓
S: 意图识别
  ├─ 规则匹配（关键词/正则）→ 置信度 ≥ 0.7 直接返回
  └─ LLM 兜底（仅规则置信度 < 0.7 时）
  ↓ 输出: IntentResult { type, entities, confidence }
  ↓
置信度检查:
  ├─ confidence ≥ 0.7 → 进入 SKILL 选择
  └─ confidence < 0.7 → 返回 top-3 SKILL 候选 + 澄清请求
  ↓
A: SKILL 选择 (HC-1: 不用 LLM)
  ├─ 1. 按 capability_id 粗筛（trading/research/dev）
  ├─ 2. 按 tags 规则匹配（命中 ≥1 个 tag），命中数 ≥ 1 → 返回
  ├─ 3. 按 description 向量匹配（仅规则无命中时，见下方方案）
  └─ 4. 排序（tag 命中数 > 向量相似度 > autonomy_boundary 优先级）
  ↓ 输出: SkillExecutionPlan { skill_ids, order, params, match_reasons }
```

**SKILL 选择向量匹配方案（M2 补充）**：
- **向量库**: 不引入外部向量数据库，使用内存中的 TF-IDF + cosine similarity（SKILL 数量 < 100，内存方案足够且零依赖）
- **Embedding 来源**: 对每个 SKILL 的 `description` + `tags` 构建 TF-IDF 向量，启动时一次性计算并缓存
- **相似度阈值**: cosine ≥ 0.3 视为匹配（低于阈值则返回空，触发"无匹配 SKILL"兜底）
- **降级条件**: 向量匹配返回空时，返回通用 SKILL（如 simple_qa）并记录日志，不阻塞流程
- **性能**: 内存计算，单次 ≤ 50ms

**关键约束**：
- SKILL 选择**不使用 LLM**（HC-1），纯规则 + TF-IDF 向量
- 选择结果可解释（`match_reasons` 记录命中的 tags/向量分数）
- 单次选择 ≤ 50ms（规则匹配）/ ≤ 100ms（向量匹配）

**与现有代码的关系**：
- 复用 [fallback-engine.ts](../../3.1-FRONTEND/src/lib/intent/fallback-engine.ts) 的意图识别（TS 实现，与部署边界一致）
- 替换 [smart-router.ts](../../3.1-FRONTEND/src/lib/intent/smart-router.ts) 的 `ROUTE_MAP` 硬编码映射
- 替换 [graph_planner.py](../dreamos/core/arrange/graph_planner.py) 的节点选择逻辑（Python 侧保留用于 orchestrator_v2 内部）

### 3.3 DSH 执行引擎（系统节点优先 + LLM 兜底）

**职责**：执行 SkillExecutionPlan，调度 DSH SubAgent，优先调系统节点，缺失才 LLM。执行结果交由 C-Drive 反射处理。

**node_dependencies 为空的处理（M5 补充）**：
- A 链方法论 SKILL（矛盾论、第一性原理等）和 G 链治理 SKILL 的 `node_dependencies` 为空
- 这些 SKILL **直接走 LLM 推理**（不违反 HC-2，因为没有对应的系统节点能力）
- LLM prompt 中需明确："你正在执行 {skill_name} SKILL，当前无系统节点数据可用，请基于方法论框架进行推理，不要编造具体数据"
- 此类 SKILL 的输出需经 C-Drive 反射额外校验（标注 confidence ≤ 0.6）

**执行流程（每个 SKILL，由 C-Drive 驱动循环）**：
```
SKILL 执行
  ↓
1. 解析 node_dependencies
  ↓
2. 对每个依赖节点:
   ├─ 节点存在且可用 → 调用 DSH Subagent → 系统节点（确定性，0 token）
   └─ 节点缺失/失败 → 降级标记
  ↓
3. 判断降级程度:
   ├─ 全部节点命中 → 聚合节点输出，SKILL 完成（不调 LLM）
   ├─ 部分节点命中 → LLM 基于已有输出做补充推理
   └─ 全部缺失 → LLM 全量推理（数据采集/联网探索）
  ↓
4. 输出 SubAgent 结果集 → 交由 C-Drive（§3.4）反射决策
   ├─ CONTINUE → 继续下一个 SKILL
   ├─ REDO → 重新执行当前 SKILL（≤2次）
   ├─ INSERT_BEFORE → 插入补充 SKILL/SubAgent
   ├─ JUMP_TO → 跳转到其他 SKILL
   └─ EARLY_TERMINATE → 终止，进入汇总
  ↓
5. 所有 SKILL 完成 → 进入 DSH 汇总 Agent（§3.7）
```

**降级链优先级**（从高到低）：
1. 系统节点（DSH Subagent → C/F 链节点）
2. 已有缓存数据（G 层账本中的历史执行结果）
3. LLM 推理（受限 prompt，明确告知可用数据范围）
4. FAIL-OPEN 中性兜底（返回"无法完成"，不编造数据）

**与现有代码的关系**：
- 复用 [algorithm_enhanced_agent.py:72-156](../dream-harness-bridge/integration/algorithm_enhanced_agent.py#L72-L156) 的短路逻辑
- 复用 [subagent_registry.py:30-112](../dream-harness-bridge/packages/python-server/subagent_registry.py#L30-L112) 的 8 Subagent
- 复用 [skill_adapter.py](../dreamos/adapters/skill_adapter.py) 的 SKILL.md 解析（但执行逻辑改为节点优先）

### 3.4 C-Drive（反射 + 聚合）+ G 层账本 — 核心驱动层

**C-Drive 定位**：C 层是整个执行循环的**核心驱动层**，不是简单的执行器。它通过反射决策驱动 DSH SubAgent 的执行流程，并通过聚合器形成中间结论。

**C-Drive 组件**（复用现有 DreamOS 实现）：

| 组件 | 现有实现 | 职责 |
|------|---------|------|
| **Reflector** | [reflector.py](../dreamos/core/compute/reflector.py) | 反射决策：CONTINUE / REDO / INSERT_BEFORE / JUMP_TO / EARLY_TERMINATE / SKIP |
| **Aggregator** | [aggregator.py](../dreamos/core/compute/aggregator.py) | 结果聚合：方向投票 + 置信度加权 + 分歧检测 |

**Reflector 反射决策规则**（复用现有启发式，补充 SKILL/SubAgent 粒度语义）：

| 决策 | 节点粒度语义（现有） | SKILL/SubAgent 粒度语义（新增） | 触发条件 |
|------|---------------------|-------------------------------|---------|
| CONTINUE | 继续下一个节点 | 继续下一个 SKILL 或 SubAgent | 置信度正常、无矛盾 |
| REDO | 重新执行当前节点 | 重新执行当前 SKILL（≤2次）或重新调用当前 SubAgent | confidence < 0.3 |
| INSERT_BEFORE | 在当前节点前插入节点 | **插入补充 SubAgent**（如矛盾时补充数据采集 SubAgent），不插入新 SKILL | 与前序结果矛盾、数据不足 |
| JUMP_TO | 跳转到指定节点 | 跳过当前 SKILL，跳转到计划中的其他 SKILL | budget < 20% |
| EARLY_TERMINATE | 提前终止执行 | 终止剩余 SKILL，直接进入汇总 Agent | confidence > 0.85 且已执行后期 SKILL，或连续 3 个方向一致 |
| SKIP | 跳过当前节点 | 跳过当前 SubAgent（不跳过整个 SKILL） | SubAgent 结果冗余或已被其他 SubAgent 覆盖 |

**关键说明**：
- REDO 在 SKILL 粒度下重新执行整个 SKILL，在 SubAgent 粒度下只重新调用单个 SubAgent
- INSERT_BEFORE **只能插入 SubAgent**，不能插入新 SKILL（避免运行时改变执行计划）
- EARLY_TERMINATE 触发后直接进入汇总 Agent，不再执行剩余 SKILL

**C-Drive 驱动循环**：
```
DSH SubAgent 结果集
  ↓
Reflector.decide()
  ├─ CONTINUE → 继续下一个 SKILL/SubAgent
  ├─ REDO → 重新执行（≤2次）
  ├─ INSERT_BEFORE → 插入补充 SubAgent（如矛盾时补充数据）
  ├─ JUMP_TO → 跳过当前路径
  ├─ EARLY_TERMINATE → 终止，进入汇总
  └─ SKIP → 跳过当前
  ↓
Aggregator.aggregate() → 中间结论（方向 + 置信度 + 分歧度）
  ↓
循环直到所有 SKILL 完成或提前终止
```

**G 层账本定位**：G 层是**笔记本/账本**，完整记录执行过程：

| 记录内容 | 用途 |
|---------|------|
| 每个 SubAgent 的结果 + source 标记 | 复盘和溯源 |
| Reflector 的每次决策 + 理由 | 反射决策审计 |
| 检查点（每 N 步自动保存） | 崩溃恢复 |
| 执行轨迹（SKILL 调用链 + 时间线） | 性能分析和认知反馈 |
| Aggregator 的中间结论 | 汇总 Agent 的输入 |

**与现有代码的关系**：
- 复用 [graph_executor.py](../dreamos/core/compute/graph_executor.py) 的执行循环 + Reflector + Aggregator + GraphStore
- 反射对象从"节点执行结果"变为"DSH SubAgent 执行结果"
- 新增：SKILL 选择准确率反馈（选错 SKILL 时记录到 G 层，用于优化匹配规则）

### 3.5 索引查询服务（IndexQueryService）— 新增

**职责**：为静态索引系统（INDEX.md / skill-registry.json）提供统一的语义查询 API，复用 RAG 已部署的 bge-small-zh 模型做向量化。

**数据模型**：
```typescript
interface IndexEntry {
  entry_id: string;
  title: string;
  path: string;                      // 文件路径
  category: 'doc'|'skill'|'module'|'code';
  description: string;               // 语义描述
  tags: string[];
  source_index: string;              // 来源索引文件
}
```

**索引来源**：
- `0-系统文档管理/INDEX.md`（文档索引）
- `1-ARCHITECTURE/工作索引/skill_registry_output/registry.json`（SKILL 索引）
- `2-KNOWLEDGE/INDEX.md` + 各子目录 INDEX.md（知识库索引）
- `4-MEMORY/0-元记忆/MEMORY_TYPES.md`（认知记忆索引）

**实现方案**（复用 RAG 基础设施）：
1. 启动时扫描上述索引文件，提取条目
2. 用 `bge-small-zh`（RAG 已部署）对 `title + description + tags` 做向量化
3. 存入 ChromaDB 的独立 collection（`index_entries`）
4. 查询时支持：关键词匹配 + 语义向量匹配 + category 过滤

**接口**：
```typescript
class IndexQueryService {
  query(query: string, options?: { category?: string; top_k?: number }): IndexReference[]
  reload(): void  // 重新扫描索引文件
}
```

**与 Transformer 的关系**：
- 当前阶段：复用 bge-small-zh（轻量 Transformer encoder），不引入新模型
- 后期可选：引入 ColBERT 等专用索引 Transformer，支持端到端索引+检索
- 不建议：自研 Transformer 索引算法（ROI 低，现有成熟方案足够）

### 3.6 知识沉淀 SKILL（knowledge-ingest）— 新增

**职责**：SKILL 执行完成后（特别是调研类），将产出的知识/案例分类存入知识库 + 向量化 + 认知记录 + 索引更新，形成"执行→沉淀→复用"闭环。

**触发条件**：
- 调研类 SKILL（dream-research-workflow, dream-science-* 系列）执行完成
- 认知 record 的 tags 含 `knowledge-ingest`
- 显式调用 `knowledge-ingest` SKILL

**执行流程**：
```
SKILL 执行产出（调研报告/案例/经验）
  ↓
1. 分类
   ├─ 交易策略类 → 2-KNOWLEDGE/1-TRADING/
   ├─ 外部调研类 → 2-KNOWLEDGE/7-EXTERNAL-RESEARCH/<domain>/
   ├─ 方法论类 → 2-KNOWLEDGE/5-CHAIN-DEVELOPMENT/
   └─ AI认知类 → 2-KNOWLEDGE/8-AI-COGNITION/
  ↓
2. 原子化存储
   ├─ 按知识颗粒度拆分为独立 .md 文件
   ├─ 每个文件包含 frontmatter（title, domain, tags, source, created_at）
  ↓
3. 向量化
   └─ 调用 RAG build_index.py，自动构建 ChromaDB 向量索引
  ↓
4. 认知记录
   └─ record(content=知识摘要, quality_level='B', tags='knowledge-ingest,<domain>')
  ↓
5. 索引更新
   └─ 更新对应目录的 INDEX.md + 触发 IndexQueryService.reload()
```

**关键约束**：
- 知识沉淀**不修改已有知识**，只新增
- 每条知识必须有 `source` 字段（来源 SKILL/调研）
- 交易决策类知识不自动入库（需人工审核，避免错误决策沉淀）

**与现有机制的关系**：
- 复用 `dream-doc-sync-workflow` 的索引更新逻辑
- 复用 `wiki-ingest-trigger` 的认知→Wiki 同步
- 补充了现有 `dream-research-workflow` 只 record 不入库的缺口

### 3.7 DSH 汇总 Agent（SummarizerAgent）— 新增

**职责**：在 C-Drive 驱动循环结束后，汇总所有 DSH SubAgent 结果 + C-Drive 中间结论 + G 层账本记录，生成最终输出。是整个执行链路的"最后一公里"。

**定位**：
- 与 C 层 Aggregator 的关系：Aggregator 做**交易方向投票**（面向交易决策），汇总 Agent 做**通用结果格式化**（面向所有意图类型）
- 与 G 层的关系：汇总 Agent 从 G 层账本读取完整执行轨迹，生成可追溯的最终输出

**输出类型（按意图分类）**：

| 意图类型 | 输出结构 | 关键内容 |
|---------|---------|---------|
| 交易决策类 | `{ action, confidence, rationale, risk, signals }` | LONG/SHORT/HOLD + 置信度 + 理由 + 风险 + 各 SubAgent 信号 |
| 市场查询类 | `{ summary, data_points, sources, confidence }` | 摘要 + 关键数据 + 来源 + 置信度 |
| 深度分析类 | `{ report, dimensions, consensus, disagreements, confidence }` | 报告 + 多维度分析 + 共识 + 分歧 + 置信度 |
| 调研类 | `{ findings, references, methodology, confidence }` | 发现 + 引用来源 + 方法 + 置信度 |
| 通用问答 | `{ answer, sources, confidence }` | 答案 + 来源 + 置信度 |

**执行流程**：
```
C-Drive 循环结束（所有 SKILL 完成或 EARLY_TERMINATE）
  ↓
1. 从 G 层账本读取:
   ├─ 所有 SubAgent 结果（含 source 标记）
   ├─ Aggregator 中间结论（方向 + 置信度 + 分歧度）
   ├─ Reflector 决策记录
   └─ 认知上下文（经验/知识/引用）
  ↓
2. 按意图类型选择汇总模板
  ↓
3. 汇总逻辑:
   ├─ 交易类: 复用 Aggregator 的方向投票结果，补充 rationale 和 risk
   ├─ 数据类: 聚合各 SubAgent 数据点，标注来源和时效性
   ├─ 分析类: 综合各维度结论，标注共识和分歧
   └─ 调研类: 汇总发现，整理引用来源
  ↓
4. 置信度校准:
   ├─ 基于各 SubAgent 的 source（node > llm）加权
   ├─ 基于 SubAgent 数量和一致性
   └─ 基于 Aggregator 分歧度（分歧大则降低置信度）
  ↓
输出: FinalOutput
```

**关键约束**：
- 汇总 Agent **不重新执行**任何 SubAgent，只做结果整合和格式化
- 输出必须标注每个结论的**数据来源**（哪个 SubAgent、系统节点还是 LLM）
- 交易类输出必须经过 Autonomy Boundary 校验（HC-3）
- 置信度 ≤ 0.4 时，输出必须包含"建议人工复核"提示

**与现有代码的关系**：
- 复用 [aggregator.py](../dreamos/core/compute/aggregator.py) 的方向投票和置信度加权逻辑
- 新增通用汇总逻辑（现有 Aggregator 仅面向交易方向）
- **注册定位**：汇总 Agent 是**流程控制 Agent**，**不与 8 个领域 SubAgent 平级注册**到 `subagent_registry.py`。它在 DSH 执行引擎内部作为最后一步被调用，注册在独立的 `control_agents` 注册表中

### 3.8 DSH 自进化 Agent（EvolutionAgent）— 新增

**职责**：每次任务执行完成后，自动触发大认知系统的自进化。核心是让**认知系统、SKILL 系统、知识库**三大系统"越用越聪明"，而不是交易策略进化。

**定位**：
- 与汇总 Agent 的关系：汇总 Agent 负责本次任务的最终输出；自进化 Agent 负责从本次任务中**沉淀和进化**三大认知系统
- 触发时机：每次任务执行完成后自动触发（不阻塞最终输出，可异步执行）
- 安全约束：进化产物不自动修改交易逻辑，需人工审核（HC-8 延伸）

**三大进化维度**：

#### 维度 1：认知系统进化（记忆蒸馏 + 质量升降级）

**复用现有能力**：[cognitive_evolution_scheduler.py](../../4-MEMORY/9-工具与接口/cognitive_evolution_scheduler.py)

| 进化动作 | 机制 | 触发条件 |
|---------|------|---------|
| **记忆蒸馏** | 按 domain+tags 聚类 bayesian_memories，合并重复、提炼宏观规律 | 每次任务后 |
| **质量升降级** | S/A/B/C/D 五级 + 宽限期（C级3次verify内不降权） | `verify()` 触发 |
| **贝叶斯置信度更新** | success: `conf += (1-conf)×0.3`；fail: `conf × 0.7` | `verify(success)` 触发 |
| **记忆修剪** | 扫描低置信+高verify_count的负向记忆，标记归档 | Gardener 角色 |
| **过时检测** | confidence < 0.3 且 verify_count ≥ 5 → 标记过时 | 每次任务后 |

**四角色 Pipeline**（复用现有调度器）：
```
Evolution(提案) → Critic(批评+宪法红线) → Verifier(验证) → Gardener(修剪)
PROPOSED        → CRITIQUED              → VALIDATED      → APPLIED
```
- 全部支持 `--no-llm` 降级为规则基线（FAIL-OPEN）
- `--dry-run` 只写 PROPOSED/CRITIQUED/VALIDATED，不写 APPLIED、不删除

#### 维度 2：SKILL 系统进化（生命周期 + 置信度）

**复用现有能力**：[dream-skill-index-governance/SKILL.md](../skills/dream-skill-index-governance/SKILL.md)

| 进化动作 | 机制 | 触发条件 |
|---------|------|---------|
| **生命周期流转** | proposed → shadow → active → deprecated → archived | 每次任务后 |
| **shadow → active 升级** | 需 `shadow_verified=true` + 至少 1 条 verify success | `verify(success=True)` |
| **SKILL 置信度更新** | 复用贝叶斯规则（与认知记忆一致） | 每次 SKILL 执行后 |
| **使用计数更新** | `apply_count++`，`last_verified` 更新 | 每次 SKILL 执行后 |
| **冲突/漂移检测** | 检测重叠 SKILL、过期依赖 | 每次任务后 |
| **新 SKILL 衍生** | hermes 反思决定是否从本次任务衍生新 SKILL | 任务完成后 |

#### 维度 3：知识库进化（入库 + 向量化 + 质量评估）

**复用现有能力**：`knowledge-ingest` SKILL（§3.6）+ RAG 基础设施

| 进化动作 | 机制 | 触发条件 |
|---------|------|---------|
| **新知识入库** | 按 domain 分类存储到 2-KNOWLEDGE/ | 调研类任务完成后 |
| **向量化** | bge-small-zh 编码 → ChromaDB | 入库后自动 |
| **索引更新** | 更新 INDEX.md + skill-registry.json 向量索引 | 入库后自动 |
| **知识质量评估** | 基于引用次数 + 相关性反馈更新质量分 | 每次任务后 |
| **过时知识标记** | 长期未被检索 + 低质量分 → 标记归档 | 定期 |

**执行流程**：
```
任务执行完成（汇总 Agent 输出 FinalOutput）
  ↓
自进化 Agent 触发（异步，不阻塞最终输出）
  ↓
1. 认知系统进化:
   ├─ 对本次任务中调用的 recall 结果执行 verify（成功/失败）
   ├─ 触发认知进化调度器（四角色 Pipeline）
   └─ 输出: bayesian_memories.json 更新 + 蒸馏报告
  ↓
2. SKILL 系统进化:
   ├─ 更新本次执行的 SKILL 的 apply_count + last_verified
   ├─ 根据执行结果执行 verify（成功→升级置信度/生命周期）
   ├─ 运行 SKILL 冲突/漂移检测
   └─ hermes 反思：是否衍生新 SKILL（proposed 阶段）
  ↓
3. 知识库进化:
   ├─ 若为调研类任务 → knowledge-ingest（入库+向量化+索引更新）
   ├─ 更新被引用知识的质量分
   └─ 标记过时知识
  ↓
输出: EvolutionReport（三大系统各自的进化摘要 + 待人工审核项）
```

**关键约束**：
- 自进化 Agent **不修改交易逻辑和策略参数**（那是 L4 自进化引擎的职责，不在此 Agent 范围）
- 进化产物中涉及记忆/知识/SKILL 的**新增/修改/删除**，需进入人工审核队列（APPLIED 需审批）
- 全部进化操作支持 `dry-run` 和 `--no-llm` 降级
- 自进化执行**不阻塞**用户看到最终输出（汇总 Agent 先返回，自进化异步跑）

**与现有代码的关系**：
- 认知系统：复用 [cognitive_evolution_scheduler.py](../../4-MEMORY/9-工具与接口/cognitive_evolution_scheduler.py) 四角色 + [role_separation.py](../../4-MEMORY/9-工具与接口/role_separation.py) 质量升降级
- SKILL 系统：复用 [dream-skill-index-governance](../skills/dream-skill-index-governance/SKILL.md) 生命周期 + `verify` MCP 工具
- 知识库：复用 `knowledge-ingest` SKILL（§3.6）+ RAG ChromaDB
- **注册定位**：自进化 Agent 是**流程控制 Agent**，**不与 8 个领域 SubAgent 平级注册**。它在汇总 Agent 输出后异步触发，注册在独立的 `control_agents` 注册表中

**与 L4 自进化引擎的边界**：
- 本 Agent 只进化**认知系统、SKILL 系统、知识库**（记忆蒸馏、SKILL 生命周期、知识入库）
- L4 自进化引擎（`self_evolution_engine.py`）进化**策略参数**（胜率停滞时调整阈值）
- 两者**互不越界**：本 Agent 不修改策略参数，L4 引擎不修改认知/SKILL/知识
- 若本 Agent 检测到策略层面停滞（如连续低置信度），**可触发 L4 引擎**，但 L4 的产物（参数变更）需单独人工审核

### 3.9 架构调研编排 SKILL（dream-arch-research-orchestrator）— 新增

**职责**：架构问题的标准闭环调度器。当用户提出问题或发现架构问题时，自动编排"调研 → SPEC → 评审 → Plan"四阶段流程，每阶段结束调用对应子 SKILL 输出结果，用户确认后明确推荐下一步。

**定位**：
- 本质是**元 SKILL（SKILL 调度器）**，自身不做具体调研/设计/评审/计划，而是调度子 SKILL
- 与 `IntentAndSkillSelector` 的区别：Selector 是运行时意图→SKILL 的自动选择器；本 SKILL 是**架构问题解决流程**的显式编排器，带用户确认门
- 解决用户痛点：每次不用自己判断"现在该调研还是该写 SPEC"，SKILL 会明确推荐下一步

**四阶段闭环 + 子 SKILL 调度**：

| 阶段 | 子 SKILL | 输入 | 输出 | 用户确认门 |
|------|---------|------|------|-----------|
| **1. 问题定义** | `dream-contradiction-theory`（矛盾论拆解） | 用户原始问题 | 问题陈述 + 主要矛盾 + 约束 + 调研域 | ✅ 确认问题定义 |
| **2. 调研** | `dream-research-workflow`（多源调研）或 `dream-qwen-eval-collab`（千问二轮） | 问题定义包 | 调研报告（含4维交叉验证） | ✅ 确认调研结论 |
| **3. SPEC 形成** | `dream-qwen-eval-collab` 步骤4（spec合成） | 调研报告 | SPEC 文档（含接口/数据/验收） | ✅ 确认 SPEC |
| **4. 评审** | `dream-science-peer-review`（同行评审）或 `dream-qwen-eval-collab` 评估 | SPEC 文档 | 评审报告（含通过/修改建议/P0-P2） | ✅ 确认评审结论 |
| **5. Plan** | `dream-eng-mgmt-workflow`（工程管理） | 评审通过的 SPEC | 执行计划（里程碑/依赖/调度/风险） | ✅ 确认 Plan，进入执行 |

**执行流程**：
```
用户提出问题 / 发现架构问题
  ↓
[阶段1] 问题定义
  ├─ 调用 dream-contradiction-theory 拆解
  ├─ 输出: 问题定义包
  └─ → 推荐下一步：「建议进入调研阶段，调用 dream-research-workflow」
       ↓ [用户确认]
[阶段2] 调研
  ├─ 调用 dream-research-workflow（本地4维）
  │   或 dream-qwen-eval-collab（千问二轮评估）
  ├─ 输出: 调研报告 + 交叉验证
  └─ → 推荐下一步：「调研结论已就绪，建议进入 SPEC 形成阶段」
       ↓ [用户确认]
[阶段3] SPEC 形成
  ├─ 调用 dream-qwen-eval-collab 步骤4（spec合成）
  ├─ 输出: SPEC 文档
  └─ → 推荐下一步：「SPEC 已生成，建议进入评审阶段」
       ↓ [用户确认]
[阶段4] 评审
  ├─ 调用 dream-science-peer-review（Devil's Advocate + 7模式阻断）
  │   或 dream-qwen-eval-collab 步骤3（trae评估）
  ├─ 输出: 评审报告（通过/修改建议）
  ├─ 若需修改 → 回退到阶段3（SPEC修订）
  └─ → 推荐下一步：「评审通过，建议进入 Plan 阶段」
       ↓ [用户确认]
[阶段5] Plan
  ├─ 调用 dream-eng-mgmt-workflow（里程碑/依赖/调度/风险）
  ├─ 输出: 执行计划
  └─ → 推荐下一步：「Plan 已就绪，可开始执行」
       ↓ [用户确认]
进入执行（TDD / 实施 / 验证）
```

**关键设计**：

1. **每步强制用户确认门**：阶段间不可跳过，必须用户显式确认才进入下一步（避免调研不充分就写 SPEC，或 SPEC 未评审就 Plan）
2. **可回退**：评审阶段若发现问题，可回退到 SPEC 阶段修订（支持阶段回退）
3. **子 SKILL 选择策略**：
   - 调研：简单问题用 `dream-research-workflow`（本地，快）；复杂问题用 `dream-qwen-eval-collab`（千问，深）
   - 评审：严谨架构用 `dream-science-peer-review`（Devil's Advocate）；快速评估用 `dream-qwen-eval-collab` 步骤3
4. **认知闭环**：每个阶段结束后调用 `record` 记录经验，整个流程结束后调用 `verify` 验证
5. **状态机**：内部维护阶段状态机（problem → research → spec → review → plan），支持回退和重启

**与现有 SKILL 的关系**：
- **不替代**现有 SKILL，而是**编排**它们
- `dream-research-workflow` 负责调研执行（本 SKILL 只负责调用它的时机）
- `dream-qwen-eval-collab` 负责 SPEC 合成和千问评估（本 SKILL 只负责调度）
- `dream-science-peer-review` 负责同行评审（本 SKILL 只负责触发）
- `dream-eng-mgmt-workflow` 负责计划（本 SKILL 只负责衔接）

**适用场景**：
- 用户提出架构设计问题
- 发现现有架构缺陷需要修复
- 新功能落地前的调研+设计
- 任何需要"调研→SPEC→评审→Plan"标准闭环的场景

**关键约束**：
- 本 SKILL **不自动执行**任何阶段，必须用户确认
- 阶段间**不可跳过**（除非用户显式要求）
- 评审不通过**必须回退**，不能强行进入 Plan

---

## 四、接口定义

### 4.1 前端 → 编排层

```
POST /api/task/stream
Body: { message, thinking_mode, session_id, intent_method, lang, trading_mode }
SSE Events:
  - started: 任务开始
  - intent: 意图识别结果 { type, confidence, entities }
  - context_built: 认知上下文构建结果 { experiences_count, knowledge_count, references_count }
  - skill_selected: SKILL 选择结果 { skill_ids, match_reasons }
  - progress: 执行进度 { skill_id, status, source: 'node'|'llm'|'mixed' }
  - knowledge_ingested: 知识沉淀结果 { knowledge_path, memory_id }
  - done: 最终结果 { content, chain_trace, execution_time_ms }
  - error: 错误
```

### 4.2 认知上下文构建层接口

```typescript
class CognitiveContextBuilder {
  build(intent: IntentResult): Promise<CognitiveContext>
  /** 并行调用认知/RAG/索引/SKILL四系统，构建认知上下文 */
}

interface IntentResult {
  type: string;
  entities: string[];
  confidence: number;
}
```

### 4.3 IntentAndSkillSelector 内部接口

```typescript
class SkillSelector {
  select(intent: IntentResult, context: CognitiveContext): SkillExecutionPlan
  /** 基于意图 + 认知上下文选择 SKILL */
}

interface SkillExecutionPlan {
  skill_ids: string[];             // 选中的 SKILL ID 列表
  order: string[];                 // 执行顺序
  params: Record<string, any>;     // 传递给 SKILL 的参数
  match_reasons: string[];         // 选择理由（可解释性）
  context: CognitiveContext;       // 认知上下文（注入执行）
}
```

### 4.4 DSH 执行引擎接口

```typescript
class DSHExecutionEngine {
  execute_skill(skill_id: string, params: Record<string, any>, context: CognitiveContext): SkillResult
  /** 执行单个 SKILL：节点优先 + LLM 兜底 + 认知上下文注入 */

  execute_plan(plan: SkillExecutionPlan): SkillResult[]
  /** 执行完整计划 */
}

interface SkillResult {
  skill_id: string;
  content: any;
  confidence: number;
  source: 'node' | 'llm' | 'mixed';   // 输出来源
  node_outputs: Record<string, any>;   // 系统节点输出
  llm_output: string | null;           // LLM 输出（如有）
  context_used: boolean;               // 是否使用了认知上下文
  latency_ms: number;
}
```

### 4.5 SKILL 能力注册中心接口

```typescript
class SkillRegistry {
  register(skill: SkillCapability): void
  query(query: SkillQuery): SkillCapability[]
  get(skill_id: string): SkillCapability | null
  reload(): void  // 重新扫描 SKILL.md
}
```

### 4.6 索引查询服务接口

```typescript
class IndexQueryService {
  query(query: string, options?: { category?: string; top_k?: number }): IndexReference[]
  reload(): void  // 重新扫描索引文件并向量化
}
```

### 4.7 知识沉淀 SKILL 接口

```typescript
class KnowledgeIngestSkill {
  ingest(skill_result: SkillResult, source_skill_id: string): IngestResult
  /** 分类入库 + 向量化 + 认知记录 + 索引更新 */
}

interface IngestResult {
  knowledge_path: string;      // 入库路径
  memory_id: string;           // 认知记忆 ID
  indexed: boolean;            // 是否已向量化
}
```

### 4.8 DSH 汇总 Agent 接口

```typescript
class SummarizerAgent {
  summarize(
    intent_type: string,
    subagent_results: SubAgentResult[],
    aggregator_conclusion: AggregatorConclusion,
    ledger: LedgerRecord[],
    context: CognitiveContext
  ): FinalOutput
  /** 汇总所有 SubAgent 结果 + C-Drive 结论 + G 层账本 → 最终输出 */
}

interface FinalOutput {
  intent_type: string;
  content: any;                          // 按意图类型结构化（见§3.7输出类型表）
  confidence: number;                    // 0.0 ~ 1.0
  sources: SourceRef[];                  // 数据来源列表
  execution_time_ms: number;
  human_review_required: boolean;        // 置信度 ≤ 0.4 时为 true
}

interface SourceRef {
  subagent_id: string;                   // 来源 SubAgent
  source_type: 'node' | 'llm' | 'mixed'; // 数据来源类型
  description: string;                   // 来源说明
}
```

### 4.9 DSH 自进化 Agent 接口

```typescript
class EvolutionAgent {
  /**
   * 触发大认知系统自进化（认知系统 + SKILL 系统 + 知识库）
   * 异步执行，不阻塞最终输出
   */
  evolve(
    task_result: FinalOutput,
    ledger: LedgerRecord[],
    context: CognitiveContext,
    options: EvolutionOptions
  ): Promise<EvolutionReport>
}

interface EvolutionOptions {
  async: boolean;               // true=异步不阻塞，false=同步等待
  dry_run: boolean;             // 只输出报告，不写 APPLIED/删除
  no_llm: boolean;              // 全部角色禁用 LLM，走规则基线
  dimensions: ('cognitive' | 'skill' | 'knowledge')[];  // 可选进化维度
}

interface EvolutionReport {
  cognitive: {
    distilled_count: number;       // 蒸馏记忆数
    upgraded: string[];            // 升级的记忆 ID
    downgraded: string[];          // 降级的记忆 ID
    pending_review: string[];      // 待人工审核项
  };
  skill: {
    lifecycle_changes: Array<{skill_id, from, to}>;  // 生命周期变更
    confidence_updated: string[];  // 置信度更新的 SKILL
    new_skill_proposals: string[]; // 新 SKILL 提案（proposed 阶段）
    pending_review: string[];      // 待人工审核项
  };
  knowledge: {
    ingested_count: number;        // 新入库知识数
    vectorized: boolean;           // 是否已向量化
    quality_updated: string[];     // 质量分更新的知识
    pending_review: string[];      // 待人工审核项
  };
  execution_time_ms: number;
}
```

### 4.10 架构调研编排 SKILL 接口

```typescript
class ArchResearchOrchestrator {
  /**
   * 启动架构问题解决闭环
   * 阶段状态机: problem → research → spec → review → plan
   */
  start(question: string): OrchestratorState

  /**
   * 执行当前阶段（调用对应子 SKILL）
   * 返回当前阶段输出 + 推荐下一步
   */
  executeCurrentPhase(state: OrchestratorState): PhaseResult

  /**
   * 用户确认，推进到下一阶段
   */
  confirmAndAdvance(state: OrchestratorState, confirmed: boolean): OrchestratorState

  /**
   * 回退到指定阶段（如评审不通过回退到 SPEC）
   */
  rollbackTo(state: OrchestratorState, phase: Phase): OrchestratorState
}

type Phase = 'problem' | 'research' | 'spec' | 'review' | 'plan'

interface OrchestratorState {
  current_phase: Phase
  question: string
  phase_outputs: Record<Phase, any>      // 各阶段输出
  history: Array<{phase, action, timestamp}>
}

interface PhaseResult {
  phase: Phase
  output: any                            // 当前阶段输出（调研报告/SPEC/评审报告/Plan）
  recommended_next: Phase                // 推荐的下一阶段
  recommended_skill: string              // 推荐调用的子 SKILL
  requires_confirmation: boolean         // 是否需要用户确认
  rollback_available: boolean            // 是否可回退
}
```

---

## 五、与现有系统的兼容策略

### 5.1 双轨运行开关

```python
# 环境变量控制
USE_SKILL_ORCHESTRATION = os.environ.get("USE_SKILL_ORCHESTRATION", "0") == "1"

if USE_SKILL_ORCHESTRATION:
    selector = IntentAndSkillSelector()  # 新路径
    plan = selector.process(message)
    results = DSHExecutionEngine().execute_plan(plan)
else:
    # 现有路径: orchestrator_v2.run_cycle() / graph_planner.plan()
    ...
```

### 5.2 orchestrator_v2 包装为 SKILL

将 [orchestrator_v2.run_cycle()](../dreamos/capabilities/trading/orchestrator_v2.py#L172) 包装为 `dream-tactical-executor` SKILL 的底层实现：
- SKILL.md 声明 `node_dependencies: ['A_ORCH']`（映射到 orchestrator_v2）
- 选中该 SKILL 时，执行引擎直接调用 `orchestrator_v2.run_cycle()`
- 保持实盘闭环不变，只是调用入口变化

**过渡态说明（m6 补充）**：
- 此为**过渡方案**，目的是在不破坏实盘闭环的前提下接入新编排
- 长期路线图（阶段 5 之后）：将 orchestrator_v2 内部五层逐步拆分为独立 SKILL（coin-selector / yijing-signal / v15-executor / signal-router / cognitive-reviewer），使交易执行类意图也能享受 SKILL 级编排灵活性
- 拆分前置条件：各层独立 SKILL 经过回测验证 + 实盘闭环验证

### 5.3 现有映射表的处理

| 现有映射表 | 处理方式 |
|-----------|---------|
| [smart-router.ts ROUTE_MAP](../../3.1-FRONTEND/src/lib/intent/smart-router.ts#L92) | 阶段 5 废弃，统一走 SKILL 选择 |
| [graph_planner.py INTENT_CHAIN_MAP](../dreamos/core/arrange/graph_planner.py) | 阶段 5 废弃 |
| [skill_adapter.py SkillNode](../dreamos/adapters/skill_adapter.py#L153) | 保留，但执行逻辑改为节点优先（阶段 3） |

---

## 六、演进路径（7 阶段）

### 阶段 1: SKILL 能力注册中心建设（2-3 周）

| 项 | 内容 |
|----|------|
| **目标** | 统一扫描三大支柱 SKILL，补全元数据，建成可查询的注册中心 |
| **变更** | 扩展 [skills-registry.ts](../../24-图结构上下文压缩/planner/skills-registry.ts)，新增 `capability_id`, `node_dependencies`, `autonomy_boundary` 字段；补全所有 SKILL 的元数据 |
| **关键** | 每个 SKILL 必须标注 `capability_id`（trading/research/dev）和 `tags` |
| **工作量拆解（m3 补充）** | ① Registry 扩展 + 扫描脚本（3 天）② 交易类 32 个 SKILL 元数据补全（3 天，重点：node_dependencies 映射到 DSH Subagent）③ 工程类 25 个 SKILL 元数据补全（2 天，多为 dev 类，node_dependencies 多为空）④ 科研类 10 个 SKILL 元数据补全（1 天）⑤ 测试 + 文档（2 天） |
| **分批策略（M5 补充）** | 第 1 批：交易类中有明确系统节点对应关系的 SKILL（如 dream-backtest→C3, dream-screen1-first→C1/C2）；第 2 批：交易类方法论 SKILL（A 链，node_dependencies 为空）；第 3 批：工程 + 科研类 |
| **验证** | registry 覆盖率 ≥ 90%；每个 SKILL 可被 `query()` 发现；元数据完整度 ≥ 80% |
| **风险** | 部分 SKILL 元数据缺失，需人工补全 |
| **回滚** | 不影响现有编排，registry 是只读索引 |

### 阶段 1.5: 认知上下文构建层 + 索引查询服务（2 周）— 新增

| 项 | 内容 |
|----|------|
| **目标** | 建成 CognitiveContextBuilder（并行调用认知/RAG/索引/SKILL）和 IndexQueryService（索引语义查询） |
| **变更** | 新建 CognitiveContextBuilder 类；新建 IndexQueryService（复用 bge-small-zh 向量化 INDEX.md/registry.json） |
| **关键** | 四系统并行调用 ≤ 2s；认知上下文只读（HC-7）；超时不阻塞（HC-9） |
| **工作量拆解** | ① CognitiveContextBuilder 框架 + 四系统适配器（3 天）② IndexQueryService 扫描+向量化（3 天）③ 并行调用 + 超时控制（2 天）④ 集成测试（2 天） |
| **验证** | 四系统调用成功率 ≥ 95%；认知上下文构建延迟 ≤ 2s（P95）；索引查询返回相关结果 |
| **风险** | 认知系统 MCP 调用延迟不稳定；RAG 检索结果相关性不足 |
| **回滚** | 认知上下文构建失败时降级为仅用 SKILL 注册（不阻塞主流程） |

### 阶段 2: SkillSelector 替换节点编排器（2-3 周）

| 项 | 内容 |
|----|------|
| **目标** | 新编排器可基于意图 + 认知上下文选择 SKILL，与现有编排器双轨运行 |
| **变更** | 新建 `SkillSelector` 类（接收 CognitiveContext 作为输入）；通过 `USE_SKILL_ORCHESTRATION` 开关切换 |
| **关键** | SKILL 选择算法：规则优先（capability_id + tags）+ TF-IDF 向量兜底，不用 LLM；选择时参考认知上下文中的经验匹配度和知识相关性 |
| **工作量拆解（m3 补充）** | ① 意图识别模块迁移（复用 fallback-engine.ts，2 天）② 规则匹配引擎（capability_id + tags，3 天）③ TF-IDF 向量匹配（3 天）④ 认知上下文注入选择逻辑（1 天）⑤ 30 个典型意图标注 + 测试集（2 天）⑥ 双轨开关 + 集成测试（2 天） |
| **验证** | 30 个典型意图测试，SKILL 选择准确率 ≥ 80%；选择延迟 ≤ 100ms |
| **风险** | SKILL 选择准确率不足，能力错配 |
| **回滚** | 开关切回现有 `graph_planner.plan()` |

### 阶段 3: DSH 执行 + C-Drive 驱动 + 汇总 Agent（3-4 周）

| 项 | 内容 |
|----|------|
| **目标** | DSH SubAgent 优先调系统节点；C-Drive 反射驱动执行循环；DSH 汇总 Agent 输出最终结果 |
| **变更** | 改造 `SkillNode` 执行逻辑；新建 `DSHExecutionEngine`；集成 C-Drive（Reflector+Aggregator）；新建 `SummarizerAgent`；认知上下文注入 |
| **关键** | 复用 Reflector 6 种决策 + Aggregator 方向投票；汇总 Agent 不重新执行只做格式化；降级链 FAIL-OPEN |
| **工作量拆解** | ① node_id→subagent 映射层（2 天）② DSH Subagent IPC 调用封装（3 天）③ 降级链实现（节点→缓存→LLM→FAIL-OPEN，3 天）④ C-Drive 集成：Reflector 反射循环 + Aggregator 聚合（3 天）⑤ SummarizerAgent 通用汇总（3 天）⑥ 认知上下文 prompt 注入（2 天）⑦ 集成测试 + 性能测试（2 天） |
| **验证** | market_query 系统节点覆盖率 ≥ 70%；端到端延迟 < 10s；token 消耗降低 ≥ 50%；汇总输出含来源标注；置信度 ≤ 0.4 时触发人工复核提示 |
| **风险** | 系统节点覆盖不全；C-Drive 反射决策误判；汇总格式不符合预期 |
| **回滚** | 保留 LLM 优先旧路径；C-Drive 可降级为直接透传结果 |

### 阶段 4: orchestrator_v2 包装为 SKILL + 全量切换（1-2 周）

| 项 | 内容 |
|----|------|
| **目标** | 现有五层流水线作为 SKILL 接入新编排，全量切换到新路径 |
| **变更** | 包装 `orchestrator_v2.run_cycle()` 为 `dream-tactical-executor` SKILL；`USE_SKILL_ORCHESTRATION` 默认开启 |
| **关键** | 保持实盘闭环 A→B→C→D→E 不变；单账本/单 PRNG 不破坏 |
| **工作量拆解（m3 补充）** | ① orchestrator_v2 HTTP API 封装（2 天）② dream-tactical-executor SKILL 包装（2 天）③ 全量切换 + 灰度验证（3 天） |
| **验证** | 实盘闭环正常；PnL 无回归；切换后 7 天无异常 |
| **风险** | 包装引入性能开销或状态漂移 |
| **回滚** | 开关切回直接调用 orchestrator_v2 |

### 阶段 5: 清理硬编码映射表（1 周）

| 项 | 内容 |
|----|------|
| **目标** | 废弃 ROUTE_MAP / INTENT_CHAIN_MAP，统一走 SKILL 选择 |
| **变更** | 删除 [smart-router.ts ROUTE_MAP](../../3.1-FRONTEND/src/lib/intent/smart-router.ts#L92)；删除后端 INTENT_CHAIN_MAP；清理 graph_planner 节点选择逻辑 |
| **关键** | 所有意图类型都有对应 SKILL 匹配；无功能回归 |
| **工作量拆解（m3 补充）** | ① 全量意图测试覆盖验证（2 天）② 删除旧映射表 + 清理 import（2 天）③ 回归测试（1 天） |
| **验证** | 全量意图测试通过；代码删除后无 import 错误 |
| **风险** | 前端路由逻辑改动大，可能遗漏 |
| **回滚** | 保留旧映射表代码分支，开关切换 |

### 阶段 6: 知识沉淀 SKILL + 闭环优化（1-2 周）— 新增

| 项 | 内容 |
|----|------|
| **目标** | 建成 knowledge-ingest SKILL，形成"执行→沉淀→复用"闭环；优化认知上下文质量 |
| **变更** | 新建 knowledge-ingest SKILL（分类入库 + 向量化 + 认知记录 + 索引更新）；在调研类 SKILL 执行后自动触发 |
| **关键** | 知识只新增不修改（HC-8）；交易决策类知识需人工审核；复用 RAG build_index.py |
| **工作量拆解** | ① 分类逻辑 + 入库模板（2 天）② RAG 向量化集成（1 天）③ 认知 record + 索引更新（2 天）④ 调研类 SKILL 触发集成（1 天）⑤ 测试 + 知识质量审计（2 天） |
| **验证** | 调研案例入库率 ≥ 90%；入库知识可被 RAG 检索到；入库知识无重复/无错误决策 |
| **风险** | 知识分类错误；低质量知识污染知识库 |
| **回滚** | 知识沉淀可开关关闭，不影响执行主流程 |

### 阶段 7: DSH 自进化 Agent + 三大系统自动进化（2-3 周）— 新增

| 项 | 内容 |
|----|------|
| **目标** | 建成 DSH 自进化 Agent，每次任务后自动触发认知系统、SKILL 系统、知识库三大系统的进化，实现"越用越聪明" |
| **变更** | 新建 EvolutionAgent；集成认知进化调度器（四角色 Pipeline）；集成 SKILL 生命周期治理；集成 knowledge-ingest；每次任务完成后异步触发 |
| **关键** | 进化不修改交易逻辑（只进化认知/SKILL/知识）；APPLIED 需人工审核；支持 dry-run + --no-llm 降级；异步不阻塞最终输出 |
| **工作量拆解** | ① EvolutionAgent 框架 + 异步触发（2 天）② 认知系统进化集成（四角色调度器 + verify，3 天）③ SKILL 系统进化集成（生命周期 + 置信度 + 漂移检测，3 天）④ 知识库进化集成（knowledge-ingest + 质量评估，2 天）⑤ EvolutionReport + 人工审核队列（2 天）⑥ 集成测试 + 进化效果验证（2 天） |
| **验证** | 每次任务后自进化触发率 = 100%；认知记忆 verify 调用率 ≥ 80%；SKILL 生命周期正确流转；知识库入库无回归；进化产物 100% 进入人工审核队列 |
| **风险** | 进化频率过高导致系统开销大；进化产物质量不稳定 |
| **回滚** | 自进化可开关关闭，不影响执行主流程和最终输出 |

### 阶段 8: 架构调研编排 SKILL（调研→SPEC→评审→Plan 闭环）（1-2 周）— 新增

| 项 | 内容 |
|----|------|
| **目标** | 建成 `dream-arch-research-orchestrator` 元 SKILL，自动编排"问题定义→调研→SPEC→评审→Plan"五阶段闭环，每步明确推荐下一步，用户确认后推进 |
| **变更** | 新建 SKILL.md + 状态机；集成 dream-contradiction-theory / dream-research-workflow / dream-qwen-eval-collab / dream-science-peer-review / dream-eng-mgmt-workflow 五个子 SKILL；阶段间强制用户确认门 + 支持回退 |
| **关键** | 自身不做具体工作，只调度子 SKILL；阶段不可跳过（除非用户显式要求）；评审不通过必须回退到 SPEC；每步结束 record，流程结束 verify |
| **工作量拆解** | ① SKILL.md + 状态机定义（1 天）② 五阶段子 SKILL 调度集成（3 天）③ 用户确认门 + 回退机制（2 天）④ 认知闭环（record/verify）（1 天）⑤ 端到端测试（2 天） |
| **验证** | 五阶段状态机流转正确；每步输出包含 recommended_next + recommended_skill；用户确认门 100% 生效；评审不通过可回退到 SPEC；子 SKILL 调用成功率 ≥ 90% |
| **风险** | 子 SKILL 输出格式不一致导致衔接困难；用户确认门过于繁琐影响体验 |
| **回滚** | 该 SKILL 可选调用，不影响其他 SKILL 和主流程 |

---

## 七、风险与约束

### 7.1 硬约束（不可违反）

| HC | 约束 | 来源 |
|----|------|------|
| HC-1 | SKILL 选择不使用 LLM | 避免"大模型驱动编排过度复杂" |
| HC-2 | DSH 执行优先调系统节点，LLM 仅兜底 | 数据驱动避幻觉 |
| HC-3 | 交易类 SKILL 必须有 Autonomy Boundary | 风控底线（VM-1791226814783） |
| HC-4 | C/G 层物理分离（执行/状态分离） | 架构硬约束 |
| HC-5 | orchestrator_v2 渐进迁移，不直接废弃 | 实盘闭环已验证 |
| HC-6 | 降级链必须 FAIL-OPEN | 系统韧性 |
| HC-7 | 认知上下文构建只读，不修改源系统数据 | 避免编排层副作用 |
| HC-8 | 知识沉淀只新增不修改；交易决策类知识需人工审核 | 防止错误知识污染知识库 |
| HC-9 | 认知上下文四系统并行调用，任一超时不阻塞整体 | 保证首答延迟 |

### 7.2 主要风险

| # | 风险 | 概率 | 影响 | 缓解措施 |
|---|------|------|------|---------|
| R1 | SKILL 元数据完整度不足，匹配准确率低 | 中 | 高 | 阶段 1 先做元数据补全；设置准确率阈值（≥80%）才进入阶段 2 |
| R2 | A 链（矛盾论/第一性原理）和 G 链（治理）的系统节点能力覆盖不足 | 中 | 中 | 这些 SKILL 允许走 LLM 兜底（方法论类无确定性节点）；逐步建设节点能力。**LLM 兜底白名单见下方** |
| R3 | LLM 兜底边界不清，导致幻觉 | 中 | 高 | LLM prompt 中明确告知可用数据范围；C 层反射校验输出一致性 |
| R4 | 包装 orchestrator_v2 引入性能开销 | 低 | 中 | 直接调用底层方法，不走完整 SKILL 解析 |
| R5 | 阶段 5 清理映射表时遗漏导致功能回归 | 中 | 高 | 全量意图测试覆盖；保留代码分支一个版本后再删除 |

**LLM 兜底白名单（m4 补充，解决 R2 与 HC-2 的边界冲突）**：

以下 SKILL 允许在无系统节点时走 LLM 推理（不违反 HC-2，因为没有对应系统节点能力）：

| 类别 | SKILL 示例 | 原因 | LLM 约束 |
|------|-----------|------|---------|
| A 链方法论 | dream-contradiction-theory, dream-first-principles, A7-practice-theory, A8-theory-practice-verification | 本质是思维框架，无确定性系统节点 | 不编造具体行情数据，仅输出分析框架 |
| G 链治理 | dream-doc-sync-gate, system-maintenance, dream-skill-index-governance | 治理流程类，依赖人工决策 | 不自动执行，仅输出建议 |
| 科研类 | dream-science-literature-review, dream-science-framework-research | 调研类，需联网/文献检索 | 允许联网探索，但需标注信息来源 |
| 工程类 | dream-tdd-dev-workflow, dream-bugfix-workflow | 代码开发流程 | 不直接修改代码，输出步骤指引 |

**以下 SKILL 禁止 LLM 兜底，必须走系统节点或 FAIL-OPEN**：
- dream-tactical-executor（交易执行，必须走 orchestrator_v2）
- dream-exit-skill-v2（离场，必须走系统风控节点）
- dream-risk-position-sizing（仓位，必须走 DSH_RISK 纯算法节点）
- dream-backtest（回测，必须走 C3 回测引擎）

### 7.3 未决问题（需 human-in-the-loop）

1. ~~**SKILL 选择的向量匹配方案**~~ → **已解决**（§3.2）：内存 TF-IDF + cosine similarity，不引入外部向量库
2. **LLM 兜底的范围**：白名单已定义（上方），但需逐 SKILL 确认是否在白名单内
3. **编排记忆的反馈机制**：SKILL 选择错误时如何自动优化匹配规则？（阶段 2 后续迭代）

---

## 八、验收标准

### 8.1 功能验收

| # | 验收项 | 标准 | 验证方法 | 测量定义（M3 补充） |
|---|--------|------|---------|---------------------|
| F1 | SKILL 注册中心覆盖率 | ≥ 90% SKILL 已注册且元数据完整 | 脚本扫描校验 | 覆盖率 = 已注册且元数据完整的 SKILL 数 / SKILL 总数；元数据完整 = capability_id + tags + description + autonomy_boundary 均非空 |
| F2 | SKILL 选择准确率 | 30 个典型意图 ≥ 80% | 人工标注 + 自动化测试 | **准确率 = 选择结果与 ground truth 一致的意图数 / 30**。ground truth 由架构组人工标注（每个意图对应 1~3 个正确 SKILL）；选择结果命中任一正确 SKILL 即算正确 |
| F3 | 系统节点优先调用率 | market_query 类 ≥ 70% 执行走节点 | 执行日志统计 source 字段 | **调用率 = source='node' 的 market_query 执行次数 / market_query 总执行次数**。统计窗口：阶段 3 验收前连续 100 次 market_query 执行 |
| F4 | 端到端延迟 | market_query < 10s | 压测 | 延迟 = 从 /api/task/stream 收到请求到 done 事件发出的时间；取 P95 |
| F5 | Token 消耗降低 | 相比现有 ≥ 50% | 对比测试 | 降低率 = (现有路径 token 消耗 - 新路径 token 消耗) / 现有路径 token 消耗；对比相同 30 个意图的执行 |
| F6 | 实盘闭环无回归 | orchestrator_v2 包装后 A→B→C→D→E 正常 | 实盘冒烟测试 | 闭环正常 = 五层均无 ERROR，PnL 计算一致，账本状态正确 |
| F7 | 认知上下文构建 | 四系统调用成功率 ≥ 95%，延迟 ≤ 2s（P95） | 集成测试 + 压测 | 成功率 = 成功返回的系统数 / 4；延迟 = 从 build() 调用到返回 CognitiveContext 的时间 |
| F8 | 认知上下文使用率 | SKILL 执行中认知上下文注入率 ≥ 60% | 执行日志统计 context_used 字段 | 注入率 = context_used=true 的执行次数 / 总执行次数 |
| F9 | 知识沉淀入库率 | 调研案例入库率 ≥ 90%，可被 RAG 检索 | 知识质量审计 | 入库率 = 成功入库的调研案例数 / 应入库案例数；可检索 = RAG search 能返回该知识 |
| F10 | 索引语义查询 | IndexQueryService 返回相关结果，延迟 ≤ 500ms | 集成测试 | 相关性 = 人工评估 top-5 结果与 query 的相关度 ≥ 3/5 |
| F11 | DSH 汇总 Agent | 5 类意图输出结构正确，含来源标注 | 集成测试 | 结构正确 = 输出字段与§3.7输出类型表一致；来源标注 = sources 数组非空且每项有 subagent_id |
| F12 | C-Drive 反射 | Reflector 6 种决策均可触发，Aggregator 输出分歧度 | 单元测试 + 集成测试 | 反射覆盖 = 至少触发一次每种决策；Aggregator 输出含 direction + confidence + disagreement |
| F13 | 低置信度人工复核 | 置信度 ≤ 0.4 时 human_review_required=true | 集成测试 | 触发率 = 置信度≤0.4 的输出中 human_review_required=true 的比例 = 100% |
| F14 | 自进化触发 | 每次任务后自进化触发率 = 100% | 执行日志统计 | 触发率 = 自进化 Agent 被调用的任务数 / 总任务数 |
| F15 | 认知系统进化 | verify 调用率 ≥ 80%，记忆蒸馏正常产出 | 进化日志统计 | verify 调用率 = 调用 verify 的任务数 / 总任务数；蒸馏产出 = bayesian_memories.json 有更新 |
| F16 | SKILL 系统进化 | SKILL 生命周期正确流转，置信度更新 | SKILL 注册表审计 | 流转正确 = shadow→active 需 verify success；置信度 = apply_count 增加且 confidence 按贝叶斯更新 |
| F17 | 知识库进化 | 调研类任务知识入库率 ≥ 90%，向量化完成 | 知识质量审计 | 入库率 = 成功入库数 / 应入库数；向量化 = ChromaDB 新增 chunk |
| F18 | 架构调研编排 | 五阶段状态机流转正确，每步推荐下一步 | 集成测试 | 流转正确 = problem→research→spec→review→plan 顺序正确；推荐 = 每步输出含 recommended_next + recommended_skill |
| F19 | 用户确认门 | 阶段间 100% 需用户确认，不可跳过 | 集成测试 | 确认门生效 = 未确认时无法推进到下一阶段 |
| F20 | 评审回退 | 评审不通过可回退到 SPEC 阶段 | 集成测试 | 回退可用 = rollbackTo(spec) 后状态回到 spec 阶段且输出保留 |

### 8.2 架构验收

| # | 验收项 | 标准 |
|---|--------|------|
| A1 | 编排粒度 | SACG 只做 SKILL 选择，不做节点级编排 |
| A2 | LLM 使用边界 | LLM 仅用于意图识别兜底和执行兜底，不用于编排决策 |
| A3 | 可解释性 | SKILL 选择结果包含 match_reasons |
| A4 | 渐进迁移 | 全阶段可通过开关回退到现有路径 |
| A5 | 汇总 Agent 职责 | DSH 汇总 Agent 不重新执行 SubAgent，只做结果整合和格式化 |
| A6 | C-Drive 定位 | C 层为核心驱动层，通过 Reflector 驱动 DSH SubAgent 执行循环 |
| A7 | 自进化边界 | 自进化 Agent 只进化认知系统/SKILL/知识库，不修改交易逻辑和策略参数 |
| A8 | 异步非阻塞 | 自进化执行不阻塞最终输出（汇总 Agent 先返回，自进化异步跑） |
| A9 | 调研编排定位 | dream-arch-research-orchestrator 是元 SKILL，只调度子 SKILL 不做具体工作 |

### 8.3 质量验收

| # | 验收项 | 标准 |
|---|--------|------|
| Q1 | 降级链 | 所有降级路径 FAIL-OPEN，无阻塞 |
| Q2 | 反射守门 | C 层反射校验所有 SKILL 输出 |
| Q3 | Autonomy Boundary | 交易类 SKILL 100% 声明且执行时校验 |
| Q4 | 来源可追溯 | 汇总输出每个结论标注数据来源（SubAgent + node/llm/mixed） |
| Q5 | G 层账本完整性 | 每次执行完整记录 SubAgent 结果 + 反射决策 + 检查点 |
| Q6 | 进化安全 | 进化产物中新增/修改/删除项 100% 进入人工审核队列，不自动 APPLIED |
| Q7 | 进化可降级 | 自进化支持 dry-run 和 --no-llm 降级，不影响主流程 |
| Q8 | 调研闭环严谨性 | 调研编排阶段间不可跳过，评审不通过必须回退 |

---

## 九、附录

### 9.1 现有 SKILL 清单（三大支柱）

**交易类（6-Trading/skills/，32 个）**：
A7-practice-theory, A8-theory-practice-verification, asset-research, dream-attention-radar, dream-backtest, dream-bailian-integration, dream-bayesian-opt, dream-contradiction-theory, dream-data-analysis, dream-doc-sync-gate, dream-exit-skill-v2, dream-first-principles, dream-intelligence-monitor, dream-knowledge, dream-oneirology, dream-pretrade-gatekeeper, dream-regime-detector, dream-risk-position-sizing, dream-screen1-first, dream-screen2-second, dream-screen3-third, dream-signal-scoring-spec, dream-strategy-designer, dream-strategy-parser, dream-strategy-research, dream-systematic-trading, dream-tactical-executor, dream-tactical-validator, dual-agent-conflict-gate, learning-episode-writer, master-seminar, system-maintenance

**开发/工程类（1-ARCHITECTURE/skills/，25 个）**：
dream-arch-collaboration-workflow, dream-arch-gap-analysis-workflow, dream-backtest-verify, dream-bugfix-workflow, dream-classic-pipeline-tdd-migration, dream-code-commit-sync-workflow, dream-code-sync-orphan-scan-workflow, dream-doc-sync-workflow, dream-eng-mgmt-workflow, dream-feature-landing-workflow, dream-genome-factor-workflow, dream-module-post-dev-verify-workflow, dream-qwen-eval-collab, dream-research-workflow, dream-scattered-file-cleanup, dream-self-iteration-workflow, dream-skill-index-governance, dream-subagent-tdd-workflow, dream-tdd-dev-workflow, dreambuddy-os, evolution-case-ingest, skill-creator, tee-red-green-progress, wiki-ingest-trigger

**科研类（.trae/skills/dream-science-*）**：
dream-science-cross-disciplinary, dream-science-framework-research, dream-science-hypothesis-verification, dream-science-literature-review, dream-science-peer-review, dream-science-statistics-check, dream-science-uncertainty-reasoning, drawio, nature-figure, nature-shared

### 9.2 框架对比加权评分（决策依据）

| 维度 | 现有（节点编排） | 新方案（SKILL编排） | 权重 |
|------|----------------|-------------------|------|
| 复杂度 | 7（高） | 3（低） | 0.20 |
| 性能 | 3（低） | 8（高） | 0.25 |
| 稳健性 | 5（中） | 7（中高） | 0.20 |
| 可扩展性 | 3（低） | 8（高） | 0.15 |
| 可维护性 | 4（低） | 7（高） | 0.10 |
| 理论基础 | 5（中） | 7（中高） | 0.10 |
| **加权总分** | **4.55** | **6.55** | 1.00 |
