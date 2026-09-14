# DreamOS × DeepSeek Harness 全栈对齐调研报告

> **版本**: v0.1
> **状态**: 🔬 调研稿
> **创建日期**: 2026-09-14
> **定位**: 在已有 Harness 调研（`前端设计/RESEARCH_DEEPSEEK_HARNESS.md`）和四维可行性（`dream-harness-bridge/docs/RESEARCH_FEASIBILITY_4DIM.md`）基础上，**扩展到 DreamOS 全栈八大子系统**的统一对齐调研
> **方法论**: 逐子系统现状梳理 → Harness 核心机制对照 → 相似性/差异分析 → 借鉴方向与 ROI 排序
> **前置阅读**:
> - [SYSTEM_ARCHITECTURE_OVERVIEW.md](./SYSTEM_ARCHITECTURE_OVERVIEW.md) v3.0（DreamOS SSoT）
> - [前端设计/RESEARCH_DEEPSEEK_HARNESS.md](./前端设计/RESEARCH_DEEPSEEK_HARNESS.md) v0.1（Harness 机制详解）
> - [dream-harness-bridge/docs/RESEARCH_FEASIBILITY_4DIM.md](./dream-harness-bridge/docs/RESEARCH_FEASIBILITY_4DIM.md) v0.1（四维可行性）

---

## ⚠️ 文档定位

本文件是**全栈对齐调研稿**，不实施任何代码变更。目的：

1. 把 Harness 调研从"SACG 四层对照"扩展到 DreamOS 全栈八大子系统
2. 识别每个子系统与 Harness 的真协同点和假相似点
3. 输出统一的借鉴方向矩阵，避免各子系统各自为战地重复调研
4. 为后续分阶段落地提供优先级依据

---

## 一、DreamOS 全栈八大子系统全景

DreamOS 不是单一系统，而是围绕"意图驱动 + 图编排 + 双认知闭环"构建的**操作系统级全栈架构**。八大子系统如下：

| # | 子系统 | 核心路径 | 定位 | 类比 |
|---|--------|---------|------|------|
| 1 | **DreamOS 操作系统内核** | `dreamos/core/` (S/A/C/G 四层) | 通用 agent 操作系统内核 | OS 内核 |
| 2 | **交易 Skill 系统** | `dreamos/capabilities/trading/nodes/` + `6-TRADING/` | 交易领域特化能力层（A0-A9/C1-C5/F1-F5/G1-G2） | 专用 ASIC |
| 3 | **图编排架构** | `6-图结构上下文压缩/` + `dreamos/core/arrange/` | 双维度编排 + 上下文压缩 + 图状态管理 | 调度器 + 文件系统 |
| 4 | **认知系统** | `4-MEMORY/9-工具与接口/` + `dreamos/core/memory/` | 开发认知闭环 + 交易认知闭环 | 大脑皮层 |
| 5 | **知识库** | `2-KNOWLEDGE/` | 跨领域系统知识蒸馏与索引 | 长期记忆（语义） |
| 6 | **文档管理系统** | `0-系统文档管理/` | 文档导航中枢 + 规范 + 治理 + 自动化 | 元数据管理层 |
| 7 | **前端系统** | `3-FRONTEND/` + `3.1-FRONTEND/` | 用户交互入口（Dashboard/配置/报告/Chat） | 用户态 UI |
| 8 | **中台** | `7-产物中台/` + `中台设计/` | 产物中台 + 网关中台 + 公司中枢 | 中间件层 |

**数据流方向**：

```
用户/定时/信号 → 前端(7) → 网关中台(8) → S层(1)感知意图 → A层(1)编排图
    → C层(1)执行节点(2) → G层(1)图存储(3) → 认知系统(4)反馈进化
    → 知识库(5)沉淀 → 文档管理(6)治理 → 产物中台(8)归档交付
```

---

## 二、Harness 核心机制速查（对照基准）

来自已有调研，列十大核心机制作为对照基准：

| 编号 | Harness 机制 | 一句话本质 |
|------|-------------|-----------|
| HM-1 | **Cordis 微内核** | Everything is a Plugin，挂载/卸载可逆（temporal+spatial composability） |
| HM-2 | **Profiles & Bundles** | 配置即产品，命名组合不同 plugin 形成不同形态 |
| HM-3 | **Capability Seams** | Service Definition / Provider / Consumer 三角色分离 |
| HM-4 | **Append-only Session Log** | 所有 model-visible 内容可追溯，支持 fork/resume/replay |
| HM-5 | **Turn/Step 生命周期** | 三类事件域（Session/Agent/Capability）+ agent/pre-step 拦截点 |
| HM-6 | **Extension Points** | 16+ 标准化扩展点（model/tools/shell/fs/sandbox/webhook/...） |
| HM-7 | **Subagent & Agent Teams** | 外部能力包装为带子代理 ctx 的并行执行单元 |
| HM-8 | **Model-as-Plugin** | 模型适配器也是 plugin，换模型=换 plugin |
| HM-9 | **Trajectory View** | 按来源维度检视执行轨迹 |
| HM-10 | **Creator Mode** | 运行时插件实验 + preset 创作 |

---

## 三、逐子系统对齐分析

### 3.1 DreamOS 操作系统内核（SACG 四层）

#### 现状

| 层 | 核心组件 | 职责 |
|----|---------|------|
| **S 层 Sense** | IntentEngine + RuleBased/LLM/Dynamic Recognizer + TokenBudget + ScenarioClassifier | 意图识别，零 Token 规则优先，自然语言走 LLM |
| **A 层 Arrange** | GraphPlanner + NodeSelector(Registry查询) + BudgetAllocator + ExecutionGraph | 纯编排：选节点 + 分配预算 + 构建执行图 |
| **C 层 Compute** | GraphExecutor + NodeRunner + Reflector(CONTINUE/REDO/JUMP/INSERT/TERMINATE) + Aggregator | 调度执行 + 反射决策 + 结果聚合 |
| **G 层 Graph** | GraphStore + Checkpointer + ContextCompressor(BAC三层) + HistoryReplay | 状态检查点 + 上下文压缩 + 历史回放 |
| **横切** | Registry / Evolution / Budget / Adapters / State / Errors | 节点注册、自进化、预算管控、适配 |

#### 与 Harness 对照

| Harness 机制 | DreamOS 对应 | 相似度 | 分析 |
|-------------|-------------|-------|------|
| HM-1 Cordis 微内核 | NodeRegistry + Adapter(Skill/API/Function) | ★★★★☆ | 同理念不同实现。DreamOS 是 Python 注册表，Harness 是 TS 微内核，可逆挂载/卸载 DreamOS 较弱 |
| HM-2 Profiles & Bundles | budget_mode (lean/standard/full) | ★★★☆☆ | DreamOS 只有 Token 三档，未打包硬约束为命名 profile |
| HM-3 Capability Seams | Adapter 三分类 | ★★☆☆☆ | DreamOS 有 Function/Skill/API 三适配器，但 Service Definition/Provider/Consumer 三角色未明确分离 |
| HM-4 Append-only Session Log | G 层 ckpt_*.json 快照式 | ★★★★☆ | DreamOS 有图但缺事件流，快照不利于增量消费 |
| HM-5 Turn/Step 生命周期 | S→A→C→G 流水线 + Reflector | ★★★★☆ | 概念相通，但 DreamOS 缺标准化事件域和 agent/pre-step 拦截点 |
| HM-6 Extension Points | Registry register/unregister | ★★☆☆☆ | DreamOS 扩展点粒度粗（只有节点注册），缺 16+ 标准化扩展点 |
| HM-7 Subagent | 无显式概念 | ★☆☆☆☆ | DreamOS 35 节点分工，但无并行子代理编排 |
| HM-8 Model-as-Plugin | LLMClient 注入式单例 | ★★☆☆☆ | LLM 降级链已有但偏耦合，非显式 plugin |
| HM-9 Trajectory View | G 层 GraphCompressor | ★★★☆☆ | 有压缩但缺可视化审计 UI |
| HM-10 Creator Mode | 做梦部 + D-Z-E 开发链 | ★★★★☆ | DreamOS 领域特化更深，但缺"内存中实验"模式 |

#### 关键结论

- **真协同点**：HM-4（事件流升级 G 层）、HM-2（profile 化）、HM-10（Creator 模式整合做梦部）
- **假相似点**：HM-1（微内核理念相同但实现差异大，不可直接复用）、HM-7（子代理概念 DreamOS 不需要嵌套外部编码 agent）
- **最高价值**：P0-1 事件流升级 G 层（喂养 A7/A8 自进化）+ P0-2 profile 化打包硬约束

---

### 3.2 交易 Skill 系统（A0-A9 / C1-C5 / F1-F5 / G1-G2）

#### 现状

**三大核心闭环**：
- **执行环**：A0矛盾 → A1调研 → A2第一性原理 → A3沙盘 → A4验证 → A5执行 → A9离场
- **情报环**：A6 实时雷达 + 异常检测 + 应急响应
- **治理环**：A7实践论门禁 → A8知行合一验证 → 路由进化

**三大思维链**（骨架，不映射到节点）：
- S链：调研→分析→设计→验证→执行
- C链：扫描→识别→匹配→回测→参数
- F链：新闻→资金→情绪→链上→宏观

**节点总数**：A0-A9（10）+ C1-C5（5）+ F1-F5（5）+ G1-G2（2）= 22 个核心节点 + 11 个本地子系统适配器

#### 与 Harness 对照

| Harness 机制 | 交易系统对应 | 相似度 | 分析 |
|-------------|-------------|-------|------|
| HM-1 Plugin 化 | NodeRegistry 节点注册 | ★★★★☆ | 节点=plugin 理念一致，DreamOS 节点通过 Registry 动态接入 |
| HM-3 Capability Seams | BaseNode 模板方法（validate→execute_core→fallback） | ★★★☆☆ | BaseNode 有模板方法但三角色未分离，Provider/Consumer 边界模糊 |
| HM-7 Subagent | 外部 API（经典指标 8092 / 基本面 3456）固定 HTTP 调用 | ★★☆☆☆ | 可借鉴 Subagent 化外部 API，并行化 + 降级 |
| HM-4 Session Log | 交易执行报告（dynamic_orchestration_*.json） | ★★★☆☆ | 有报告但是快照式，不是事件流 |
| HM-9 Trajectory View | 无可视化 | ★☆☆☆☆ | 可借鉴 Trajectory 可视化审计交易决策轨迹 |
| HM-2 Profiles | 无命名 profile，硬约束散落各处 | ★★☆☆☆ | 可定义 trial/standard/aggressive/freeze profile |

#### 关键结论

- **真协同点**：HM-7（Subagent 化外部 API 并行调用）、HM-2（profile 打包交易硬约束）
- **不可复用**：Harness 的编码 tool（文件编辑/shell）与交易领域无关
- **领域深度优势**：DreamOS 交易节点的领域深度（矛盾论/第一性原理/大师研讨/易经推理）远超 Harness 通用能力，这是 DreamOS 的护城河，不应被 Harness 通用能力稀释

---

### 3.3 图编排架构（双维度编排 + 上下文压缩）

#### 现状

**双维度编排三层**：
- **L1 思维框架**：S/C/F 三条链 = 固定五步思维顺序（骨架，不含实现）
- **L2 AI 推理引擎**：每个思维步骤内动态决策（问题定义→技能选择→执行→置信度评估→分支→写图）
- **L3 技能库**：A/C/F/G 系列节点，统一契约（输入→处理→输出+置信度）

**图状态管理**（`6-图结构上下文压缩/`）：
- `graph-state.ts`：图状态管理
- `graph-checkpointer.ts`：图检查点
- `graph-parallel.ts`：图并行执行
- `graph-hitl.ts`：图人机交互
- `graph-executor.ts`：图执行器
- `compressor.ts`：BAC 三层压缩（Chronicle→Architecture→Blueprint）
- `chronicle.ts` / `architecture.ts` / `blueprint.ts`：三层结构
- `blueprint-registry.ts`：跨 session 架构模板注册表

**DreamOS G 层**（Python，`dreamos/core/graph_store/`）：
- `store.py` / `checkpointer.py` / `compressor.py` / `history.py`
- 快照式 `ckpt_*.json` 存储

#### 与 Harness 对照

| Harness 机制 | 图编排对应 | 相似度 | 分析 |
|-------------|----------|-------|------|
| HM-4 Append-only Session Log | BAC 三层压缩 + ckpt 快照 | ★★★★☆ | DreamOS 有更强的图结构压缩，但缺事件流 |
| HM-5 Turn/Step 生命周期 | L2 推理引擎的决策循环 | ★★★★☆ | 概念高度相通，DreamOS 有置信度评估和分支决策 |
| HM-9 Trajectory View | visualization.ts（压缩前后三层图对比） | ★★★★☆ | DreamOS 已有可视化能力，可与 Harness Trajectory 互补 |
| HM-1 Plugin 化 | blueprint-registry（跨 session 模板注册） | ★★★☆☆ | 蓝图注册表≈plugin 注册，但可逆挂载较弱 |
| HM-2 Profiles | 蓝图模板按意图路由 | ★★★☆☆ | 蓝图模板≈profile，但未打包硬约束 |

#### 关键结论

- **DreamOS 图编排的优势**：BAC 三层压缩（Chronicle 细粒度→Architecture 中间层→Blueprint 摘要）比 Harness 单维 Session Log 更有层次结构
- **可借鉴**：HM-4 的 append-only 事件流作为 Chronicle 层的数据源，BAC 压缩在事件流之上做 projection
- **注意**：DreamOS 有两套图实现（TS 的 `6-图结构上下文压缩/` + Python 的 `dreamos/core/graph_store/`），需统一，SSoT 应是 Python G 层

---

### 3.4 认知系统（双闭环 + 贝叶斯进化）

#### 现状

**双层架构**（`4-MEMORY/MEMORY_SYSTEM_ARCHITECTURE.md` v5.0）：
- **总记忆系统（Global Memory）**：MU-DEV / MU-TRD / MU-DOC / MU-INF，程序记忆(S) + 语义记忆(A)
- **应用记忆系统（Application Memory）**：L4 交易记忆 / 风控记忆 / 运维记忆，语义记忆(A) + 情景记忆(B/C)

**神经传递机制**：
- 上升路径：应用记忆→蒸馏→验证达标→语义记忆→再验证→程序记忆
- 下降路径：总记忆检索激活→路由到应用记忆→查询详情
- 阈值公式：`confidence = (verify_count × quality_weight × time_decay) / (conflict_count × 2 + 1)`

**认知 MCP 工具**（`4-MEMORY/9-工具与接口/cognitive_mcp_server.py`）：
- `recall`：检索相关历史经验
- `record`：写入新经验
- `verify`：贝叶斯置信度更新
- `stats`：记忆统计
- `health`：健康检查

**核心引擎**：
- `cognitive_daemon.py`：实时监听（5s mtime 轮询）
- `cognitive_hook.py`：git post-commit 延迟触发
- `bayesian_memory_updater.py`：贝叶斯 v2 进化（Beta-Binomial + 指数遗忘）
- `rumination_engine.py`：反刍引擎
- `prediction_engine.py`：预测引擎
- `consolidation_engine.py`：记忆巩固
- `cognitive_backtest.py`：认知回测门禁

#### 与 Harness 对照

| Harness 机制 | 认知系统对应 | 相似度 | 分析 |
|-------------|-------------|-------|------|
| HM-4 Session Log | 认知记忆 DB（SQLite + bayesian_memories.json） | ★★★★☆ | Harness Session Log 是通用事件流，认知系统是领域特化记忆库 |
| HM-9 Trajectory View | recall 检索 + verify 验证 + stats 统计 | ★★★☆☆ | 认知系统有检索验证但缺可视化轨迹 |
| HM-10 Creator Mode | 做梦部 + D-Z-E 开发链 + 认知回测 | ★★★★☆ | DreamOS 认知系统的自进化深度远超 Harness |
| HM-1 Plugin 化 | 认知 MCP（recall/record/verify/stats/health） | ★★★★☆ | 认知系统已标准化为 5 个 MCP 工具，plugin 化程度高 |

#### 关键结论

- **DreamOS 认知系统的护城河**：双闭环对称（交易闭环+开发闭环）、贝叶斯进化、神经传递架构、认知回测门禁——这些是 Harness 完全没有的领域深度
- **可借鉴**：HM-4 的 append-only 事件流作为认知系统的输入源（当前认知系统靠 daemon 监听文件变更，事件流可提供更结构化的输入）
- **不可替代**：认知系统的 verify/record/recall 闭环是 DreamOS 独有资产，Harness 无法替代

---

### 3.5 知识库（2-KNOWLEDGE/）

#### 现状

**8 大域**：
1. **1-TRADING**（19 文件）：A系列调度链、CBR案例检索、三屏系统、五计庙算、风控体系等
2. **2-TECHNICAL**（5 文件）：数据管道、部署维护、飞书集成
3. **3-THEORY**（4 文件）：大师谱系、矛盾分析法、第一性原理
4. **4-OPERATIONS**（6 文件）：OKR管理、三段式门禁、审批工作流
5. **5-CHAIN-DEVELOPMENT**（5 文件）：D/Z/E 方法论、三链接力协议
6. **6-PRODUCT-BUSINESS**（7 文件）：产品定位、系统工作流程
7. **7-EXTERNAL-RESEARCH**：外部资料素材库（finance/github/technical）
8. **8-AI-COGNITION**（4 文件）：认知系统架构、记忆类型映射

**建设原则**：
- Source of Truth = Skills（每个 SKILL.md 是单域权威来源）
- 原子化存储（每文件解决一个独立问题）
- 两向同步（本地 MD ↔ 飞书 Doc）
- 仅保留精华（不复制原始数据）

#### 与 Harness 对照

| Harness 机制 | 知识库对应 | 相似度 | 分析 |
|-------------|----------|-------|------|
| HM-4 Session Log | 知识库文档（蒸馏后的精华） | ★★☆☆☆ | Harness 是原始事件流，知识库是蒸馏后的语义知识 |
| HM-9 Trajectory View | 知识库按域索引 | ★★☆☆☆ | 概念不同，知识库是静态文档，Trajectory 是动态轨迹 |
| HM-6 Extension Points | 知识库 8 域分类 | ★☆☆☆☆ | 无直接对应 |
| — | 知识库 + RAG（`2-KNOWLEDGE/9-RAG-INFRA/`） | — | DreamOS 有 RAG 基础设施规划，Harness 无内置 RAG |

#### 关键结论

- **知识库是 DreamOS 独有资产**：8 大域 50+ 文件的领域知识蒸馏，Harness 完全没有
- **与 Harness 的衔接点**：Harness Session Log（事件流）→ DreamOS 认知系统蒸馏 → 知识库沉淀。这是一个完整的知识生产链
- **不可复用**：知识库的领域内容是 DreamOS 多年积累，Harness 无法替代

---

### 3.6 文档管理系统（0-系统文档管理/）

#### 现状

**视角 B 文档分层模型**：
- **L0 顶层元文档**：项目入口、文档管理中枢、文档规范、技术债
- **L1 顶层架构与治理**：SSoT 架构总览、治理章程、知识库、记忆系统
- **L2 子系统文档**：7 个交易子系统（10-16）各 5 文档标准
- **L3 模块文档**：子系统内模块级文档
- **L4 片段文档**：临时片段

**核心组件**：
- 三张地图：`SYSTEM_MAP` / `ARCHITECTURE_MAP` / `TOPIC_MAP`
- 文档规范：`DOC_STANDARD.md`（5 套模板）+ `DOC_CLASSIFICATION.md`（L0-L4 分级 + A/B/C 质量分级）
- 文档治理：`DOC_LIFECYCLE.md` + `DOC_DEBT_INDEX.md` + `QUALITY_AUDIT.md`
- 自动化工具：`doc_coverage.py` / `doc_lint.py` / `link_checker.py`

#### 与 Harness 对照

| Harness 机制 | 文档管理对应 | 相似度 | 分析 |
|-------------|------------|-------|------|
| HM-4 Session Log | 文档变更历史（git） | ★☆☆☆☆ | 概念不同，文档管理是静态治理，Session Log 是动态事件 |
| HM-9 Trajectory View | 文档地图（SYSTEM_MAP/ARCHITECTURE_MAP/TOPIC_MAP） | ★★☆☆☆ | 都是"导航"概念，但维度不同 |
| HM-6 Extension Points | 文档规范体系（5 套模板 + L0-L4 分级） | ★★☆☆☆ | 都是"标准化"概念 |
| — | 自动化工具（doc_coverage/doc_lint/link_checker） | — | DreamOS 独有，Harness 无文档治理 |

#### 关键结论

- **文档管理是 DreamOS 的工程治理优势**：视角 B 分层模型 + 三张地图 + 自动化校验，这是工业级工程治理，Harness 作为通用框架不涉及
- **与 Harness 的衔接**：无直接借鉴，但 Harness 的 Session Log 可为文档变更提供更细粒度的事件源
- **不可复用**：文档管理体系是 DreamOS 工程文化的体现，Harness 无法替代

---

### 3.7 前端系统（3-FRONTEND / 3.1-FRONTEND）

#### 现状

**Dream Universal Gateway**（Next.js 14 + TypeScript）：
- **UI 层**：Dashboard / Settings（API配置/交易参数/策略设置/渠道）/ Reports / Chat
- **状态管理**：Zustand（auth / chat / config / credits / ui / session）
- **API 层**：Next.js API Routes（/auth /task /chat）
- **外部服务**：WorkBuddy 任务调度 / 产物中台 / 百炼 API

**前端设计文档**（`1-ARCHITECTURE/前端设计/`）：
- 18 个设计文档：FRONTEND_ARCHITECTURE / UI_SPEC / UI_ROADMAP / INTENT_ROUTER / CHAIN_ORCHESTRATOR / USER_SYSTEM_DESIGN / TRADING_CONFIG_DESIGN / STRATEGY_CONFIG_DESIGN / API_CONFIG_DESIGN / CHANNEL_DESIGN 等

#### 与 Harness 对照

| Harness 机制 | 前端对应 | 相似度 | 分析 |
|-------------|---------|-------|------|
| HM-5 Turn/Step 生命周期 | Chat 模块 + session 状态管理 | ★★★☆☆ | Harness 有标准化 turn/step，前端 Chat 可借鉴 |
| HM-9 Trajectory View | Reports 模块 + 报告展示 | ★★★★☆ | Trajectory View 可直接增强前端的决策轨迹可视化 |
| HM-7 Subagent | Chat 多轮对话 + 工具调用 | ★★☆☆☆ | 前端可展示 Subagent 并行调用状态 |
| HM-2 Profiles | Settings 配置管理 | ★★★☆☆ | Profile 化可直接映射到前端配置 UI |
| HM-10 Creator Mode | 策略配置 / 实验功能 | ★★☆☆☆ | Creator 模式可映射到前端的策略实验 UI |

#### 关键结论

- **前端是 Harness 价值最直接的展示层**：Trajectory View、Turn/Step 生命周期、Subagent 状态都需要前端可视化
- **可借鉴**：HM-9（Trajectory View 增强报告页）、HM-2（profile 化配置 UI）、HM-5（turn/step 可视化 Chat 交互）
- **DreamOS 前端优势**：交易领域特化 UI（三屏交易、配置管理、积分系统），Harness 前端是通用编码 UI

---

### 3.8 中台（产物中台 + 网关中台 + 公司中枢）

#### 现状

**产物中台（Artifact Hub）**：
- 统一管理所有 AI 执行产物
- 产物投递验证与归档
- 邮件路由系统
- 跨部门交付物流转

**网关中台（Gateway Hub）**：
- 用户认证与授权
- API 配置管理
- 交易参数设置
- 积分系统

**公司中枢**：
- 六部门模型 + 六人董事会
- 双中台：研究中台 + 市场化中台
- 双交易工作流：投资研究 + 交易运营
- 治理与执行中枢层：Route/Trace / Task/Result / Audit/Approval

#### 与 Harness 对照

| Harness 机制 | 中台对应 | 相似度 | 分析 |
|-------------|---------|-------|------|
| HM-1 Plugin 化 | 产物中台的产物注册/投递 | ★★☆☆☆ | 都是"注册-投递"模式 |
| HM-4 Session Log | 产物归档 + 审计日志 | ★★★☆☆ | Session Log 可作为产物归档的事件源 |
| HM-6 Extension Points | 网关中台的 API 配置管理 | ★★☆☆☆ | 都是"扩展点"概念 |
| HM-2 Profiles | 公司中枢的六部门 + 双中台 | ★★☆☆☆ | Profile 化可映射到部门级配置 |
| HM-9 Trajectory View | 治理与执行中枢的 Trace | ★★★★☆ | Trajectory View 可增强中台的 Trace/Audit 能力 |

#### 关键结论

- **中台是 DreamOS 的企业级治理层**：六部门 + 双中台 + 四层合规，这是企业级架构，Harness 作为通用框架不涉及
- **可借鉴**：HM-9（Trajectory View 增强 Trace/Audit）、HM-4（Session Log 作为产物归档事件源）
- **不可复用**：公司中枢的治理模型是 DreamOS 业务特化，Harness 无法替代

---

## 四、统一借鉴方向矩阵

综合八大子系统分析，输出统一的借鉴方向矩阵：

### P0 — 高价值低成本（推荐优先评估）

| 编号 | 借鉴方向 | 涉及子系统 | Harness 机制 | ROI | 落地条件 |
|------|---------|----------|-------------|-----|---------|
| P0-1 | **Append-only 事件流升级 G 层** | OS内核、图编排、认知系统 | HM-4 | ★★★★★ | 需研究 Harness vN→vN+1 迁移包 |
| P0-2 | **Profile/Bundle 模式升级 budget_mode** | OS内核、交易系统、前端、中台 | HM-2 | ★★★★☆ | 硬约束与 Token 预算打包为命名 profile |
| P0-3 | **Trajectory View 增强决策可视化** | 前端、中台、图编排 | HM-9 | ★★★★☆ | 基于事件流构建可视化审计 UI |

### P1 — 中价值中成本

| 编号 | 借鉴方向 | 涉及子系统 | Harness 机制 | ROI | 落地条件 |
|------|---------|----------|-------------|-----|---------|
| P1-1 | **Capability Seams 三角色分离** | OS内核、交易系统 | HM-3 | ★★★☆☆ | 拆 Service Definition/Provider/Consumer |
| P1-2 | **Model-as-Plugin 彻底化** | OS内核 | HM-8 | ★★★☆☆ | LLM 降级链从硬编码升级为配置驱动 |
| P1-3 | **Subagent 化外部 API** | 交易系统 | HM-7 | ★★★☆☆ | 经典指标/基本面 API 并行化 + 降级 |
| P1-4 | **Turn/Step 标准化事件域** | OS内核、前端 | HM-5 | ★★★☆☆ | 定义 Session/Agent/Capability 三类事件 |

### P2 — 探索性

| 编号 | 借鉴方向 | 涉及子系统 | Harness 机制 | ROI | 落地条件 |
|------|---------|----------|-------------|-----|---------|
| P2-1 | **Creator Mode 整合做梦部** | OS内核、认知系统 | HM-10 | ★★★☆☆ | 做梦部 + D-Z-E + 认知回测整合为实验模式 |
| P2-2 | **Extension Points 标准化** | OS内核 | HM-6 | ★★☆☆☆ | 从节点注册扩展到 16+ 标准化扩展点 |
| P2-3 | **Cordis 可逆挂载机制** | OS内核 | HM-1 | ★★☆☆☆ | NodeRegistry 增加可逆挂载/卸载 |

### 不建议采用

| 项目 | 不采用原因 |
|------|-----------|
| Cordis 微内核整体迁移 | TS/Node.js 与 Python 不兼容，重写成本 >> 收益 |
| Docker 沙箱隔离 | DreamOS 不执行任意代码，无需 |
| Subagent 编排 Claude Code/Codex | DreamOS 是交易系统，不需要嵌套外部编码 agent |
| 直接依赖 developer preview API | v0.1.x 仍有 breaking changes，作为参考即可 |
| TypeScript Tool Contracts | DreamOS 用 Python，工具契约应保持 Python 风格 |

---

## 五、全栈协同架构图

基于上述分析，DreamOS × Harness 的全栈协同架构如下：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        应用层（前端 + 中台）                                    │
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ 前端 (3-FRONTEND)│  │ 产物中台         │  │ 网关中台         │              │
│  │ Dashboard/Chat  │  │ Artifact Hub    │  │ Gateway Hub     │              │
│  │ Reports/Setting │  │ 产物归档/投递    │  │ 认证/API/积分    │              │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘              │
└───────────┼────────────────────┼─────────────────────┼──────────────────────┘
            │                    │                     │
            ▼                    ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              Harness (Cordis) 通用 agent runtime 层（可选基座）                 │
│                                                                             │
│  Cordis 微内核 · Profiles&Bundles · Capability Seams · Session Log          │
│  Turn/Step 生命周期 · Extension Points · Subagent · Model-as-Plugin         │
│  Trajectory View · Creator Mode                                             │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ 分层嵌入（plugin 接入点）
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              DreamOS 操作系统内核（SACG 四层）— 不可替代的核心                    │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ S 层 Sense  — IntentEngine · Recognizers · TokenBudget                │ │
│  │ A 层 Arrange — GraphPlanner · NodeSelector · BudgetAllocator          │ │
│  │ C 层 Compute — GraphExecutor · NodeRunner · Reflector · Aggregator     │ │
│  │ G 层 Graph   — GraphStore · Checkpointer · ContextCompressor(BAC)      │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│ 交易 Skill 系统        │ │ 认知系统              │ │ 知识库 + 文档管理      │
│ A0-A9/C1-C5/F1-F5/G1-G2│ │ 双闭环 + 贝叶斯进化    │ │ 8域知识 + 视角B治理    │
│ 三大思维链 + 三大闭环   │ │ recall/record/verify  │ │ 三张地图 + 自动化工具  │
│ 22+节点领域深度         │ │ 神经传递架构           │ │ 工业级文档治理         │
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘
```

**关键判断**：
1. **Harness 是可选基座**，不是必须的。DreamOS 八大子系统可以独立运行
2. **SACG 四层 + 交易 Skill + 认知系统 + 知识库 + 文档管理**是 DreamOS 的护城河，不可被 Harness 替代
3. **Harness 的价值在于**：事件流、profile 化、Trajectory View、Subagent 并行——这些是工程机制，不是领域能力
4. **前端和中台是 Harness 价值最直接的展示层**

---

## 六、与现有硬约束的兼容性评估

| 硬约束 | 受影响的借鉴方向 | 兼容性 | 说明 |
|--------|----------------|--------|------|
| BDSM direction_constraint (三层矛盾感知) | P0-2 profile | ✅ | profile 内嵌 direction_constraint |
| BCRM2.0 测试仓上限 MAX_TRIAL_POSITIONS=2 | P0-2 profile | ✅ | trial_profile 内嵌此约束 |
| 战略层模块化开关 enable_five_domain | P0-2 profile | ✅ | aggressive_profile 启用开关 |
| SL/TP 价格空间下限保护 (SL≥4%/TP≥12%) | P0-2 profile | ✅ | 各 profile 内嵌对应下限 |
| 数据清洗 Medallion Architecture | P0-1 事件流 | ✅ | 事件流作为 Gold 层下游消费者 |
| FAIL-OPEN 铁律 | P0-1/P1-1/P1-3 | ✅ | 所有借鉴方向均需遵守 FAIL-OPEN |
| 自进化 reward 信号由 DreamBuddy 内部计算 | P0-1 事件流 | ✅ 增强 | 事件流提供更细粒度 reward 来源 |
| 认知记忆系统 DB 单进程独占 | P0-1 事件流 | ✅ | 跨进程只读快照，不共享 DB 句柄 |
| G-05 不可逆级联熔断 | P0-1 事件流 | ✅ 增强 | 事件流可记录 G-05 判据触发历史 |
| dream-harness-bridge 不修改其他目录代码 (HC-1a) | 全部 | ✅ | 借鉴方向在 dream-harness-bridge 内或独立模块 |

**结论**：所有借鉴方向与现有硬约束兼容，部分（自进化/G-05/认知系统）会被增强。

---

## 七、开放问题与后续研究

### 7.1 待深挖机制

| 编号 | 问题 | 涉及子系统 | 优先级 |
|------|------|----------|--------|
| OQ-1 | Harness session log 的 vN→vN+1 迁移包具体实现 | OS内核、图编排 | 高（P0-1 落地前） |
| OQ-2 | Capability Seams 在 Python 中如何等价实现 | OS内核、交易系统 | 中 |
| OQ-3 | Subagent 化外部 API 后的并行调度与降级策略 | 交易系统 | 中 |
| OQ-4 | Trajectory View 与 DreamOS BAC 三层压缩的融合方式 | 图编排、前端 | 中 |
| OQ-5 | Profile 化后硬约束的一致性执行验证 | 交易系统、前端 | 高（P0-2 落地前） |
| OQ-6 | 事件流作为认知系统输入源的数据契约 | 认知系统 | 中 |
| OQ-7 | 公司中枢六部门模型如何映射到 Harness Profile | 中台 | 低 |

### 7.2 待实证验证

| 编号 | 待验证项 | 验证方式 |
|------|---------|---------|
| EV-1 | P0-1 事件流升级后，A7/A8 自进化数据喂养效率提升 | A/B 回测对比 |
| EV-2 | P0-2 profile 化后硬约束一致性执行 | 单元测试 + 集成测试 |
| EV-3 | P1-3 subagent 化外部 API 后端到端延迟降低 | 性能压测 |
| EV-4 | P0-3 Trajectory View 对决策可解释性的提升 | 用户调研 |

### 7.3 待持续跟踪

| 编号 | 跟踪项 | 频率 |
|------|--------|------|
| TR-1 | DeepSeek Harness 版本演进与 breaking changes | 月度 |
| TR-2 | Cordis 论文引用与社区反馈 | 季度 |
| TR-3 | Harness 在交易/金融领域的应用案例 | 季度 |
| TR-4 | DreamOS 各子系统与 Harness 的协同落地进展 | 月度 |

---

## 八、调研结论

1. **相似性为真，但集中在工程机制层**：SACG 四层与 Harness 在"纯编排、不重复建设"哲学上高度一致，但 DreamOS 的领域深度（交易 Skill、认知系统、知识库）是 Harness 无法替代的护城河

2. **八大子系统分三类**：
   - **不可替代（护城河）**：交易 Skill 系统、认知系统、知识库、文档管理系统——领域深度和多年积累，Harness 无法替代
   - **可增强（工程机制）**：OS 内核 SACG、图编排——可借鉴 Harness 的事件流、profile 化、Trajectory View 等工程机制
   - **展示层（价值直接）**：前端、中台——Harness 的 Trajectory View、turn/step 可视化可直接增强前端体验

3. **最高价值借鉴**：P0-1（事件流升级 G 层）+ P0-2（profile 化打包硬约束）+ P0-3（Trajectory View 增强可视化），三者形成"事件流→压缩→可视化"的完整链路

4. **落地策略**：先 P0 后 P1，每个方向独立评估、独立落地，不捆绑。所有落地必须通过硬约束验证和 FAIL-OPEN 测试

5. **DreamOS 不应被 Harness 反向定义**：Harness 是通用 agent runtime，DreamOS 是交易领域操作系统。借鉴 Harness 的工程机制，但保持 DreamOS 的领域独立性

---

## 八-A、边界守护理论：互补如何不变成冲突

> **本附录回答核心问题**：DreamOS 与 Harness 在什么条件下互补，什么条件下会变成冲突？如何守住边界？

### A.1 三条核心边界

互补关系建立在三条边界之上，任何一条失守都会让互补变成冲突：

| 边界 | 规则 | 失守后果 |
|------|------|---------|
| **层间边界** | Harness 只管"通用运行时"，不侵入交易逻辑；DreamOS 只管"交易领域"，不重写通用 runtime | 交易逻辑碎片化 / 双轨维护 / 概念污染 |
| **状态边界** | 交易状态（仓位/订单/持仓）单一真相源在 DreamOS，Harness 不持有不缓存 | 状态不一致 → 硬约束失效 → 资金风险 |
| **认知边界** | 自进化 reward 由 DreamOS 内部计算，Harness 只编排不参与 | reward 信号失真 → 进化方向偏离 → 系统退化 |

### A.2 层间边界失守场景

#### 风险 L-1：Harness 侵入交易逻辑

**场景**：为"快速验证"，直接在 TS Cordis plugin 中写交易判断，绕过 DreamOS A 系列节点。

```
❌ 危险写法（plugin 内）:
if (rsi > 70 && macd < 0) { return "SELL"; }  // 交易逻辑泄漏到 Harness
```

**触发路径**：快速验证 → 懒得包装成 DreamOS 节点 → 直接在 plugin 写 → 交易逻辑碎片化

**早期信号**：
- TS plugin 中出现 `if rsi > 70`、`if position_size > x` 等交易判断
- 同一交易信号有两条实现路径（Python 节点 + TS plugin）

**后果**：硬约束（SL/TP 下限、BDSM direction）只在 Python 侧生效，TS 侧绕过

**缓解**：所有交易判断必须走 DreamOS 节点，plugin 只做**透传**（IPC 调用 + 结果翻译）

#### 风险 L-2：DreamOS 重写通用 runtime

**场景**：觉得 Harness 的 session log / subagent 不好用，在 `dreamos/core/` 下自己实现一套。

**早期信号**：`dreamos/core/` 下出现 `session_log.py`、`subagent_manager.py` 等通用机制文件

**后果**：不危险但浪费——双轨并行，两套机制逐渐漂移

**缓解**：通用机制优先用 Harness；不够用就给 Harness 提 issue/PR，而非自建

#### 风险 L-3：概念泄漏（最隐蔽、长期危害最大）

**场景**：Harness 概念（`turn`/`step`/`agent`/`tool`）渗透到 DreamOS 领域代码。

```
❌ 危险写法（DreamOS 交易节点内）:
from harness.types import AgentTurn, ToolResult  # 领域代码依赖 Harness 概念
```

**早期信号**：
- `dreamos/capabilities/trading/nodes/` 下的文件 import 了 Harness/Cordis 类型
- 节点代码中出现 `agent.turn`、`tool.result` 等 Harness 原生概念

**后果**：DreamOS 失去领域独立性，变成"Harness 的交易插件"

**缓解**：ACL（防腐层）只在 `dream-harness-bridge/` 的 adapter 层翻译概念，领域代码**零 Harness 依赖**

### A.3 状态边界失守场景

#### 风险 S-1：Harness 缓存交易状态（最危险，直接影响资金）

**场景**：为"优化性能"，TS plugin 缓存仓位/订单数据，IPC 失败时静默返回缓存。

```
❌ 危险写法:
let positionCache = null;
async function getPosition() {
  try { positionCache = await ipcCall(); }
  catch { return positionCache; }  // IPC 失败返回旧缓存！
}
```

**后果链**：
```
缓存旧仓位(SOL 1个) → 实际已平仓 → Harness 认为还有仓位 →
BDSM 同方向集中度检查误判 → 拦截新开仓 或 重复开仓 → 硬约束失效
```

**缓解**：HC-3 零状态审计 + IPC 失败一律 **FAIL-OPEN**（返回 neutral default），绝不返回缓存

#### 风险 S-2：双写状态冲突

**场景**：SL/TP 修改同时存在两条路径——Harness 直接调交易所 API，DreamOS 也调交易所 API。

**缓解**：所有交易状态变更**只能通过 DreamOS 执行**，Harness 只触发不执行

#### 风险 S-3：硬约束被缓存绕过

**场景**：`MAX_TRIAL_POSITIONS=2` 等硬约束在 DreamOS 侧检查，但 Harness 用缓存的旧仓位计数。

**缓解**：硬约束检查必须在 DreamOS 侧执行，且每次开仓前实时查询当前仓位数

### A.4 认知边界失守场景

#### 风险 C-1：Reward 计算泄漏到 Harness

**场景**：自进化 reward 在 TS plugin 中计算（如简单 `pnl_pct`），绕过 DreamOS 的 `tanh(pnl/0.02)` 归一化。

```
❌ 危险写法（plugin 内）:
const reward = pnlPct;  // 直接用 PnL 当 reward
```

**后果**：大盈亏被线性放大（tanh 会压缩极值），权重更新过激，进化不稳定

**缓解**：HC-5 reward 只能由 DreamOS 内部计算，plugin 只透传**原始 PnL**

#### 风险 C-2：认知系统被通用事件污染

**场景**：把 Harness session log 的所有事件（含 file edit、shell command）未经过滤喂给认知记忆 DB。

**缓解**：`session_consumer` 只消费**交易领域事件**（node_execution / node_result / graph_node / intent_gate）

#### 风险 C-3：进化目标被反向引导

**场景**：用 Harness 的通用指标（token 效率、响应速度）评估 DreamOS 节点进化优劣。

**缓解**：进化评估**只用交易指标**（PnL、胜率、风险调整收益、最大回撤）

### A.5 跨边界级联风险

| 风险 | 场景 | 缓解 |
|------|------|------|
| **版本冲突** | Harness 升级 breaking change，所有 plugin 失效 | HC-6：版本锁定 + 契约测试 + fork 准备 |
| **故障域扩大** | Harness 崩溃 → DreamOS 交易系统也不可用 | F-09 降级演练：DreamOS 独立运行 |
| **性能瓶颈** | Harness 单线程拖慢 A6 实时路径 | 高频路径走 DreamOS 内部直连，Harness 只做低频编排 |

### A.6 边界失守滑坡模式

所有边界失守都遵循同一个滑坡模式：

```
"图省事" → "临时方案" → "没人反对" → "成为惯例" → 边界消失
```

### A.7 三条铁律守住边界

1. **Plugin 只透传，不决策** — 所有交易判断、状态变更、reward 计算必须在 DreamOS Python 侧
2. **IPC 失败即 FAIL-OPEN** — 绝不返回缓存，宁可 neutral default
3. **领域代码零 Harness 依赖** — `dreamos/` 下任何文件不得 import Harness/Cordis 类型

### A.8 风险矩阵

| 风险 | 边界 | 严重度 | 发生概率 | 防护状态 |
|------|------|--------|---------|---------|
| S-1 状态缓存 | 状态 | 极高 | 中 | 🔴 需 HC-3 + FAIL-OPEN 兜底 |
| S-3 硬约束绕过 | 状态 | 极高 | 中低 | 🔴 需硬约束在 DreamOS 侧执行 |
| L-1 交易逻辑侵入 | 层间 | 高 | 高 | 🟡 需代码审查拦截 |
| L-3 概念泄漏 | 层间 | 高 | 中高 | 🟡 需 import 审计 |
| C-1 Reward 泄漏 | 认知 | 高 | 中低 | 🟡 需 HC-5 验证 |
| 版本冲突 | 跨边界 | 高 | 中 | 🟡 需 HC-6 |
| L-2 重写 runtime | 层间 | 中 | 中 | 🟣 定期审计 |
| C-2 认知污染 | 认知 | 中 | 中 | 🟣 需事件过滤 |
| 性能瓶颈 | 跨边界 | 中 | 中 | 🟣 路径分离 |
| 故障域扩大 | 跨边界 | 高 | 低 | 🟣 需降级演练 |

**高危区（立即防护）**：S-1、S-3、L-1
**中危区（持续监控）**：L-3、C-1、版本冲突
**低危区（定期审计）**：L-2、C-2、性能瓶颈、故障域扩大

---

## 九、参考来源

### DreamOS 内部
- [SYSTEM_ARCHITECTURE_OVERVIEW.md](./SYSTEM_ARCHITECTURE_OVERVIEW.md) v3.0 — DreamOS SSoT
- [前端设计/RESEARCH_DEEPSEEK_HARNESS.md](./前端设计/RESEARCH_DEEPSEEK_HARNESS.md) v0.1 — Harness 机制详解
- [dream-harness-bridge/SPEC.md](./dream-harness-bridge/SPEC.md) v0.3 — 分层嵌入 Spec
- [dream-harness-bridge/docs/RESEARCH_FEASIBILITY_4DIM.md](./dream-harness-bridge/docs/RESEARCH_FEASIBILITY_4DIM.md) v0.1 — 四维可行性
- [dream-harness-bridge/PHASE0_REPORT.md](./dream-harness-bridge/PHASE0_REPORT.md) v2.0 — Phase 0 POC 验收
- [RESEARCH_SACG_HARNESS_MAPPING.md](./RESEARCH_SACG_HARNESS_MAPPING.md) v0.1 — SACG 四层 → Harness 扩展点详细映射设计
- [6-TRADING/TRADING_SYSTEM.md](../6-TRADING/TRADING_SYSTEM.md) v2.2 — 交易系统
- [6-图结构上下文压缩/SPEC.md](../6-图结构上下文压缩/SPEC.md) v1.0 — 双维度编排
- [4-MEMORY/MEMORY_SYSTEM_ARCHITECTURE.md](../4-MEMORY/MEMORY_SYSTEM_ARCHITECTURE.md) v5.0 — 认知系统
- [2-KNOWLEDGE/INDEX.md](../2-KNOWLEDGE/INDEX.md) — 知识库
- [0-系统文档管理/INDEX.md](../0-系统文档管理/INDEX.md) v2.2 — 文档管理
- [3-FRONTEND/FRONTEND_SYSTEM.md](../3-FRONTEND/FRONTEND_SYSTEM.md) v2.0 — 前端
- [中台设计/README.md](./中台设计/README.md) — 中台

### DeepSeek Harness 外部
- 官方仓库: https://github.com/deepseek-ai/deepseek-harness
- 官方文档: https://deepseek.com/harness/en/
- Cordis 论文: https://arxiv.org/abs/2608.25512

---

## 十、变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-09-14 | 首次全栈对齐调研，覆盖八大子系统 + 统一借鉴方向矩阵 |
| v0.2 | 2026-09-14 | 新增附录 A「边界守护理论」：三条核心边界 + 10 个失守场景 + 风险矩阵 + 三条铁律 |
