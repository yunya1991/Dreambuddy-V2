# DreamBuddy v2 系统总体架构

> **版本**: v3.0 (DRAFT)
> **更新日期**: 2026-07-31
> **文档分工（视角 B）**: **本文档 = 架构内容（唯一事实源 SSoT）**；「到哪里找文档」由 [0-系统文档管理/](../0-系统文档管理/) 的三张地图（ARCHITECTURE_MAP / SYSTEM_MAP / TOPIC_MAP）负责，不在本文档重复。
> **维护说明**: 本文档为全项目架构的唯一事实来源（SSoT）。任何架构层面的变更必须先更新本文档，再实施代码修改；文档内容与代码不一致时，先修文档再修代码。
> **核心理念**: 意图驱动 + 图编排 + 高度模块化 + OS内核 + 适配器接入 + 双认知闭环对称
> **实现状态**: 🟢 已实现 / 🟡 部分实现 / 🔴 规划中
> **关联索引**: [0-系统文档管理/INDEX.md v2.0](../0-系统文档管理/INDEX.md) · [0-系统文档管理/ARCHITECTURE_MAP.md v2.0](../0-系统文档管理/2-文档地图/ARCHITECTURE_MAP.md) · [DEBT_INDEX.md v2.4](../DEBT_INDEX.md)

---

## 一、架构总览

### 1.1 设计哲学

DreamBuddy v2 是一个**AI驱动的交易决策与开发认知双闭环操作系统**，采用 **"OS内核 + 能力层 + 应用层"** 三层操作系统级架构设计。

核心设计理念：

1. **纯编排层，不重复建设能力** — OS内核只负责"调度"，所有具体能力通过适配器接入，不改核心代码
2. **两个认知层面，对称闭环** — 交易决策闭环（A系列节点）+ 开发认知闭环（认知系统），两个闭环各自螺旋上升，通过记忆系统互通
3. **意图驱动的三层递进** — 自然语言→意图识别→图编排执行，三层递进
4. **图是一等公民** — 所有执行以图结构组织，可追溯、可压缩、可展开、可回放
5. **模块化是基础** — 统一契约，独立优化，按领域分类（A/C/F/G/T）
6. **动态是常态** — AI驱动，根据置信度动态调整执行路径
7. **上下文压缩是内置特性** — G层作为操作系统原生功能，不是外挂

---

### 1.2 三层架构全景

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          应用层 (Applications) 🟢                                   │
│                                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ TradingAgent │  │ HTTP API     │  │ CLI 工具     │  │ 7个交易子系统前端     │  │
│  │ 交易Agent     │  │ REST API     │  │ 命令行       │  │ (10/11/12/13/14/16/17)│  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                  │                  │                     │               │
│  ┌──────┴──────────────────┴──────────────────┴─────────────────────┴───────────┐  │
│  │ 开发认知入口：IDE (Claude Code/TRAE/Cursor) + Git Hooks + Daemon              │  │
│  │ 人机协作入口：8-FEISHU (飞书群组/审批/Bitable/Wiki/Cron)                       │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────┬─────────────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                       能力层 (Capabilities) 🟡                                      │
│                                                                                  │
│  ┌─────────────────────────── A_domain (AI交易能力) ──────────────────────────┐   │
│  │ 三屏交易系统 │ 执行闭环(A1-A9) │ 情报闭环(A6) │ 治理进化环(A7/A8/做梦部)  │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────── C_domain (经典量化能力) ────────────────────────┐   │
│  │ 指标库(C1-C5) │ 策略库 │ 回测引擎 │ 执行引擎                               │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────── F_domain (基本面能力) ──────────────────────────┐   │
│  │ 新闻聚合(F1) │ 资金流(F2) │ 情绪分析(F3) │ 链上指标(F4) │ 宏观数据(F5)     │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────── G_domain (治理能力) ────────────────────────────┐   │
│  │ 宪法校验(G1) │ 合规审查(G2) │ 成本控制 │ 性能评估 │ 风控(G3)                │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────── T_domain (工具能力) ────────────────────────────┐   │
│  │ Tavily搜索 │ 产物中台 │ 记忆系统(4-MEMORY) │ 系统维护 │ 监控告警             │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  （通过适配器接入 OS：SkillAdapter / APIAdapter / FunctionAdapter）               │
└────────────────────────────────────┬─────────────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                    Dreambuddy OS 内核 (Core Kernel) 🟢                             │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐   │
│  │  S层 Sense 感知层 — 操作系统用户态 🟢                                         │   │
│  │  IntentEngine → Recognizers(规则/LLM/动态) → TokenBudget → IntentResult     │   │
│  └──────────────────────────────────┬─────────────────────────────────────────┘   │
│                                     ▼                                              │
│  ┌────────────────────────────────────────────────────────────────────────────┐   │
│  │  A层 Arrange 编排层 — 操作系统调度器 🟢                                       │   │
│  │  GraphPlanner → NodeSelector(Registry查询) → BudgetAllocator → ExecGraph   │   │
│  │  纯编排：选节点 + 分配预算 + 构建执行图，不执行业务逻辑                       │   │
│  └──────────────────────────────────┬─────────────────────────────────────────┘   │
│                                     ▼                                              │
│  ┌────────────────────────────────────────────────────────────────────────────┐   │
│  │  C层 Compute 执行层 — 操作系统内核态 🟢                                       │   │
│  │  GraphExecutor → NodeRunner(适配器调度) → Reflector → Aggregator           │   │
│  │  调度执行：节点来自Registry，反射决策(CONTINUE/REDO/JUMP/INSERT/TERMINATE)   │   │
│  └──────────────────────────────────┬─────────────────────────────────────────┘   │
│                                     ▼                                              │
│  ┌────────────────────────────────────────────────────────────────────────────┐   │
│  │  G层 Graph 图存储层 — 操作系统文件系统 🟢                                     │   │
│  │  GraphStore → Checkpointer → ContextCompressor → HistoryReplay             │   │
│  └────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ Registry │ │Evolution │ │ Budget   │ │ Adapters │ │ State    │ │ Errors   │ │
│  │ 节点注册表│ │自我进化   │ │预算管理   │ │适配器框架 │ │全局状态  │ │错误码体系│ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘

          ▲                                    ▲
          │ 交易数据/执行结果                   │ 文件变更/Git事件
          │                                    │
┌─────────┴────────────────────────────┐  ┌────┴───────────────────────────────────────┐
│ 6大交易子系统（10/11/12/13/14/16）🟢 │  │ 认知系统（4-MEMORY/9-工具与接口/）🟢       │
│ · 10-经典指标系统：16层信号+离场       │  │ · daemon 实时监听（5s mtime轮询）           │
│ · 11-易经推理系统：BCRM 2.0+辩证ML    │  │ · git hook 延迟触发（post-commit）          │
│ · 12-三屏趋势系统：V4+波浪互斥融合    │  │ · 跨进程会话恢复（.current文件机制）        │
│ · 13-通用风控模块：三层风控+L1+ML     │  │ · 双层流程模板：元认知↔应用认知             │
│ · 14-V15经典马丁：马丁格尔标杆        │  │ · 贝叶斯v2进化（Beta-Binomial+指数遗忘）     │
│ · 16-调控系统：跨系统宏观离场决策     │  │ · 交易领域感知：infer_task_type / rich_tags │
└──────────────────────────────────────┘  └────────────────────────────────────────────┘

          ▲                                    ▲
          │ 产物归档/监控数据                   │ 记忆读写
          │                                    │
┌─────────┴────────────────────────────┐  ┌────┴───────────────────────────────────────┐
│ 公司中枢 + 治理体系 🟡                 │  │ 4-MEMORY 记忆系统 🟡                       │
│ · 六部门模型 + 六人董事会             │  │ · L0 工作记忆（单次任务生命周期）          │
│ · 双中台：研究中台 + 市场化中台        │  │ · L1 应用记忆（MU-TRD/RSK/OPS/EXP/DEV）   │
│ · 双交易工作流：投资研究+交易运营      │  │ · L2 总记忆（全局索引+蒸馏聚合）          │
│ · 2-GOVERNANCE：宪法/合规/审计         │  │ · 质量分级：S/A/B/C/D（贝叶斯v2驱动）     │
│ · 15-监控告警系统                      │  │ · 7标准接口：search/add/update/get/...    │
└──────────────────────────────────────┘  └────────────────────────────────────────────┘
```

| 层级 | 类比 | 核心组件 | 作用 | 实现位置 | 状态 |
|------|------|---------|------|---------|------|
| **应用层** | 用户程序 | TradingAgent / API / CLI / 子系统前端 | 面向用户的交互入口 | `dreamos/apps/` + `3-FRONTEND/` | 🟢 已实现 |
| **能力层** | 硬件驱动 | A/C/F/G/T 五大领域（50+模块） | 具体专业能力，通过适配器接入 | `6-TRADING/skills/` + `10-16各子系统` | 🟡 持续扩充 |
| **S层 (感知层)** | OS用户态 | IntentEngine + Recognizers | 理解用户意图，产出结构化意图 | `dreamos/core/sense/` | 🟢 已实现 |
| **A层 (编排层)** | OS调度器 | GraphPlanner + NodeSelector | 动态编排执行图，纯编排无业务 | `dreamos/core/arrange/` | 🟢 已实现 |
| **C层 (执行层)** | OS内核态 | GraphExecutor + NodeRunner | 调度执行、反射决策、结果聚合 | `dreamos/core/compute/` | 🟢 已实现 |
| **G层 (存储层)** | OS文件系统 | GraphStore + Compressor | 状态检查点、上下文压缩、回放 | `dreamos/core/graph_store/` | 🟢 已实现 |
| **横切关注点** | OS系统服务 | Registry / Evolution / Budget / Adapters / Errors | 节点注册、自我进化、预算管控、适配 | `dreamos/registry/` 等 | 🟢 已实现 |
| **交易子系统** | 专用ASIC | 10/11/12/13/14/16（6个） | 具体交易策略与风控实现 | `10-经典指标系统/` 等 | 🟢 已实现 |
| **认知系统** | 大脑皮层 | daemon + git hook + 会话管理器 | 开发认知闭环，驱动代码与记忆进化 | `4-MEMORY/9-工具与接口/` | 🟢 已实现 |
| **公司中枢** | CEO办公室 | 六部门 + 双中台 + 治理体系 | 宏观治理、跨系统协调、合规管控 | `1-ARCHITECTURE/中台设计/` | 🟡 部分实现 |
| **记忆系统** | 长期记忆 | L0/L1/L2 三层 | 存储+检索+蒸馏+质量分级 | `4-MEMORY/` | 🟡 部分实现 |

---

### 1.3 关键概念澄清（重要！）

> 本系统存在多套易混淆的命名体系。阅读前务必先理解本节。

#### 1.3.1 四大命名体系的关系

| 命名体系 | 定义层级 | 定位 | 核心成员 | 说明 |
|---------|---------|------|---------|------|
| **SACG 四层** | OS内核级 | 系统如何组织（架构分层） | Sense / Arrange / Compute / Graph | 操作系统内核的职责边界，**不包含业务逻辑** |
| **A/C/F/G/T 五大领域** | 能力层级 | 能力如何分类（业务模块） | A(AI交易)/C(量化)/F(基本面)/G(治理)/T(工具) | 能力层的模块分类，通过注册表动态接入OS内核 |
| **三大思维链 S/C/F** | 骨架层级 | 思考的框架和顺序 | S(调研→分析→设计→验证→执行) / C(扫描→识别→匹配→回测→参数) / F(新闻→资金→情绪→链上→宏观) | 思维骨架，不定义实现；主链+另外两链交叉验证 |
| **三大核心闭环** | 业务逻辑级 | A系列节点如何组织 | 执行环(A1→A9) / 情报环(A6) / 治理环(A7→A8→路由) | A系列节点的具体组织方式，定义交易决策的业务流 |

**数据流方向**：
```
用户请求 → 应用层 → S层(识别意图) → A层(编排执行图，选节点来自A/C/F/G/T领域)
    → C层(调度执行，通过适配器调用能力层) → G层(记录全过程) → 返回结果
```

**A层 ≠ A领域 ≠ A系列节点 ≠ S链**：
- A层 = OS内核的编排层（纯调度，不包含业务节点）
- A_domain = 能力层的AI交易能力分类（节点的归属）
- A系列节点 = A_domain中的具体实现（A0-A9，通过Registry被A层选中执行）
- S链 = 思维骨架，A系列节点是其"血肉"模块

#### 1.3.2 两个认知闭环的区分

| 维度 | 交易决策闭环 | 开发认知闭环 |
|------|------------|------------|
| **定位** | 回答"怎么交易" | 回答"怎么写代码" |
| **核心组件** | A系列节点 + 6个交易子系统 | daemon + git hook + 会话管理器 |
| **触发源** | 用户请求 / 定时调度 / 监控告警 | 文件变更(mtime) / git post-commit |
| **闭环流程** | 发现矛盾→辩证→策略→执行→离场→复盘→进化 | 文件变更→recall→record→commit→verify→模板沉淀→元反馈 |
| **记忆系统交互** | L0工作记忆(信号/仓位) + L1应用记忆(MU-TRD) | L0工作记忆(会话) + L1应用记忆(MU-DEV) + L2总记忆 |
| **进化机制** | A8知行合一 gap_score路由 + EvolutionEngine | 贝叶斯v2 + 应用/元模板双向反馈(1/√N加权衰减) |
| **代码位置** | `dreamos/capabilities/trading/nodes/` + `10-16/` | `4-MEMORY/9-工具与接口/cognitive_*.py` |

---

### 1.4 核心设计原则

1. **用户意图驱动** — 从自然语言到意图识别再到图编排执行，三层递进
2. **图是一等公民** — 所有执行以图结构组织，可追溯、可压缩、可展开、可回放
3. **纯编排层** — OS内核只做调度，具体能力通过适配器接入，不改核心代码
4. **模块化是基础** — 统一契约，独立优化，按领域分类（A/C/F/G/T）
5. **动态是常态** — AI驱动，根据置信度动态调整执行路径
6. **原生压缩能力** — G层作为操作系统原生功能，上下文压缩是内置特性
7. **前后端分工** — 后端负责核心逻辑和执行，前端负责展示和交互
8. **元层不越权** — 0号系统管"文档怎么管"，1-ARCHITECTURE管"架构设计本身"
9. **双闭环对称** — 交易闭环和开发闭环各自螺旋上升，通过4-MEMORY记忆系统互通

---

## 二、Dreambuddy OS 内核

> 内核代码位置：`1-ARCHITECTURE/dreamos/core/`。
>
> 主实现语言：Python（`dreamos/` 目录）。历史参考实现：TypeScript（`6-图结构上下文压缩/`，仅供参考，不维护）。

### 2.1 S层 Sense 感知层（操作系统用户态）

**定位**：理解用户意图，决定"做什么"，产出结构化意图（IntentResult）。零Token的规则识别优先，自然语言理解走LLM识别，中间态走动态识别渐进升级。

**核心组件清单**：

| 组件 | 文件路径 | 职责说明 | 状态 |
|------|---------|---------|------|
| **IntentEngine** | [intent_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/sense/intent_engine.py) | 意图识别主入口，协调多个识别器 | 🟢 |
| RuleBasedRecognizer | [rule_based.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/sense/recognizers/rule_based.py) | 规则识别器（市场数据+关键词，零Token） | 🟢 |
| LLMBasedRecognizer | [llm_based.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/sense/recognizers/llm_based.py) | LLM识别器（自然语言深度理解） | 🟢 |
| DynamicRecognizer | [dynamic.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/sense/recognizers/dynamic.py) | 动态识别器（规则→LLM渐进升级） | 🟢 |
| TokenBudget | [token_budget.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/sense/token_budget.py) | Token预算管控（三层模式+四层健康度） | 🟢 |
| IntentResult / ScenarioClassifier | [types.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/sense/types.py) + [scenario_classifier.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/sense/scenario_classifier.py) | 意图结果结构 + 场景分类器 | 🟢 |

**硬约束**（来自 `project_memory.md`）：
- S链（S1-S5）应作为**思维阶段框架**在S层用于意图识别，**不映射到A层节点**
- 模糊用户问题当置信度低于35%阈值时（`IntentEngine.clarify_threshold`），必须触发意图澄清，提示用户确认意图

**识别器协作流程**：
```
用户输入
    │
    ▼
RuleBasedRecognizer ──► 命中(conf≥0.85) ──► 直接返回IntentResult（零Token）
    │
    │ 未命中(conf<0.85)
    ▼
DynamicRecognizer ──► 混合模式(规则筛选+LLM精判) ──► conf≥0.60 → 返回
    │
    │ 仍然模糊
    ▼
LLMBasedRecognizer ──► 自然语言深度理解 ──► 返回
    │
    │ conf < 0.35（澄清阈值）
    ▼
触发意图澄清（向用户提确认问题）
```

---

### 2.2 A层 Arrange 编排层（操作系统调度器）

**定位**：根据意图动态构建执行图（StateGraph），决定"怎么做"。纯编排层——只选节点、分配预算、构建执行图，**不包含任何业务节点实现，不执行业务逻辑**。

**核心组件清单**：

| 组件 | 文件路径 | 职责说明 | 状态 |
|------|---------|---------|------|
| **GraphPlanner** | [graph_planner.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/arrange/graph_planner.py) | 图规划器主入口（意图→执行图） | 🟢 |
| **NodeSelector** | [node_selector.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/arrange/node_selector.py) | 节点选择器（**从NodeRegistry查询节点**，按置信度+适用场景+历史表现加权排序） | 🟢 |
| BudgetAllocator | [budget_allocator.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/arrange/budget_allocator.py) | 预算分配器（Token预算的节点间分配） | 🟢 |
| ExecutionGraph | [execution_graph.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/arrange/execution_graph.py) | SequentialGraph / ConditionalGraph 数据结构 | 🟢 |
| STANDARD_CHAINS / Types | [types.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/arrange/types.py) | 标准链路定义（A/C/F/G1/G2/I）+ 数据结构 | 🟢 |

**硬约束**（来自 `project_memory.md`）：
- A层节点必须是**动态技能选择**，由 `NodeRegistry.get()` + `NodeSelector.select()` 根据上下文动态选择，**不是硬编码的固定流水线**
- A0矛盾分析引擎必须是**代码驱动**的，实现7维市场数据计算（多空/时间/信息不对称/流动性/情绪/周期/结构矛盾）+创伤检测

**编排流程图**：
```
IntentResult (from S层)
    │
    ▼
NodeSelector.select() ──► 从 NodeRegistry 查询候选节点池
    │                      ├─ 按意图类型筛选适用场景
    │                      ├─ 按历史表现加权排序
    │                      └─ 返回top_k候选 + 置信度
    │
    ▼
BudgetAllocator.allocate() ──► Token预算分配（关键节点多分配，验证节点少分配）
    │
    ▼
GraphPlanner.build() ──► 构建 ExecutionGraph
    │                    ├─ SequentialGraph（顺序执行，默认）
    │                    ├─ ConditionalGraph（条件分支）
    │                    └─ 节点间依赖关系 + 降级路径
    │
    ▼
ExecutionGraph ──► 交给 C层 GraphExecutor 执行
```

---

### 2.3 C层 Compute 执行层（操作系统内核态）

**定位**：调度和执行图中的节点。C层本身不包含业务节点实现——业务节点来自 Registry（能力层），C层通过适配器框架调度节点执行，并在执行中进行反射决策。

**核心组件清单**：

| 组件 | 文件路径 | 职责说明 | 状态 |
|------|---------|---------|------|
| **GraphExecutor** | [graph_executor.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/compute/graph_executor.py) | 图执行器主入口（按依赖拓扑执行） | 🟢 |
| **NodeRunner** | [node_runner.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/compute/node_runner.py) | 节点运行器（执行单个节点，路由到对应适配器） | 🟢 |
| **Reflector** | [reflector.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/compute/reflector.py) | 反射决策器（5种决策类型：CONTINUE/REDO/JUMP/INSERT/TERMINATE） | 🟢 |
| Aggregator | [aggregator.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/compute/aggregator.py) | 结果聚合器（加权融合 + 分歧检测） | 🟢 |
| ExecutionReport | [types.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/compute/types.py) | 执行报告（结构化结果 + 完整轨迹 + 节点调用链） | 🟢 |

**两阶段三链结合执行机制**：

```
阶段一：交叉验证投票（多链并行）
    ├─ C链（经典量化）：C1扫描 → C2识别 → C3匹配
    ├─ F链（基本面）：F1新闻 → F2资金 → F3情绪
    └─ A链（AI交易）：A2第一性原理 → A3策略设计
    ↓
    三链投票聚合：≥2链同向 → 高置信；单链独向 → 标记分歧，INSERT补充节点

阶段二：动态插入节点（根据阶段一结果）
    ├─ 分歧大 → INSERT 大师研讨(A3内部) 或 独立验证(A7)
    ├─ 置信度高 → SKIP 冗余节点，直接到 A4 门禁
    └─ 单链独向但信号强 → REDO 该链 + 插入交叉验证节点
```

**反射决策矩阵**（Reflector 决策逻辑）：

| 决策类型 | 触发条件 | 执行动作 |
|---------|---------|---------|
| CONTINUE | 节点成功，置信度达标，无分歧 | 执行下一个节点 |
| REDO | 节点失败但可重试（超时/网络错） | 重试当前节点（最多3次，指数退避） |
| JUMP | 当前节点降级条件满足 | 跳转到fallback节点或跳过非关键节点 |
| INSERT | 检测到知识缺口/分歧/低置信 | 在当前位置插入额外节点（如大师研讨/交叉验证） |
| TERMINATE | 连续失败/致命错误/风险超标 | 终止执行，上报错误，触发降级最终态 |

---

### 2.4 G层 Graph 图存储层（操作系统文件系统）

**定位**：操作系统的"文件系统"，负责状态检查点、上下文压缩、执行历史回放。上下文压缩是OS的内置特性，不是外挂功能。

**核心组件清单**：

| 组件 | 文件路径 | 职责说明 | 状态 |
|------|---------|---------|------|
| **GraphStore** | [store.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/graph_store/store.py) | 图存储主入口（统一CRUD） | 🟢 |
| Checkpointer | [checkpointer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/graph_store/checkpointer.py) | 状态检查点（每个节点执行后快照） | 🟢 |
| **ContextCompressor** | [compressor.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/graph_store/compressor.py) | 上下文压缩器（C→A→B回溯三层压缩） | 🟢 |
| HistoryReplay | [history.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/graph_store/history.py) | 历史回放（从检查点恢复并重执行） | 🟢 |

**检查点存储位置**：`1-ARCHITECTURE/dreamos/data/graph_store/ckpt_YYYYMMDDHHMMSS_XXXXXX.json`（按执行批次自动生成）

**三层压缩模型（BAC 图结构压缩）**：
```
C层 (Chronicle 记录层) — 最细粒度：节点级执行时间线 + 完整输入输出
    │  压缩：按时间窗口聚合，合并同类节点调用
    ▼
A层 (Architecture 架构层) — 中粒度：DAG执行图结构 + 关键决策点
    │  压缩：剪枝冗余节点，合并线性子图为super node
    ▼
B层 (Blueprint 蓝图层) — 最粗粒度：顶层架构图 + 核心链路（可重建完整执行路径）
```

---

### 2.5 横切关注点（OS系统服务）

#### 2.5.1 节点注册表 Registry

**定位**：OS内核的"设备管理器"，是**所有能力节点的唯一真相源**。所有可用能力的元数据、接口契约、配置参数、降级策略都在这里统一登记。

| 组件 | 文件路径 | 职责说明 |
|------|---------|---------|
| NodeRegistry | [registry/capability/registry.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/capability/registry.py) | 节点注册表（注册/查询/列表/元数据查询） |
| RegistryLoader | — (YAML批量加载) | 从 `config/nodes.yaml` 批量加载配置 |
| VersionManager | — (版本管理) | semver版本 + 依赖兼容性检查 |

配置文件：`1-ARCHITECTURE/dreamos/config/nodes.yaml`（35+模块配置 + 11个本地实现）

#### 2.5.2 自我进化 Evolution

**定位**：交易策略的自我进化引擎，区别于认知系统的"开发认知进化"。Evolution处理的是"交易策略怎么变"，认知系统处理的是"代码怎么写"。

| 组件 | 文件路径 | 职责说明 |
|------|---------|---------|
| EvolutionEngine | [core/memory/evaluation_memory.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/memory/evaluation_memory.py) | 进化引擎主入口 |
| LessonDistiller | — (经验提炼) | 从历史执行轨迹中提炼成功/失败经验 |
| GapAnalyzer | — (差距分析) | A8知行合一的gap_score驱动，分析期望vs实际的差距 |
| NodeOptimizer | — (节点优化) | 生成节点参数调整/替换建议 |

#### 2.5.3 全局预算管理 Budget

| 组件 | 文件路径 | 职责说明 |
|------|---------|---------|
| GlobalBudget | [budget/global_budget.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/budget/global_budget.py) | 全局预算（三层模式：经济/标准/性能 + 四层健康度） |
| CostTracker | [budget/cost_tracker.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/budget/cost_tracker.py) | 单次执行的成本追踪 |

#### 2.5.4 适配器框架 Adapters

**定位**：OS内核的"驱动层"，将异构的能力节点（SKILL/HTTP API/本地函数）统一接口。详见第3章。

| 适配器 | 文件路径 | 适配对象 |
|--------|---------|---------|
| SkillAdapter | [adapters/skill_adapter.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/adapters/skill_adapter.py) | TRAE SKILL（通过 SKILL.md 定义） |
| APIAdapter | [adapters/api_adapter.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/adapters/api_adapter.py) | HTTP REST API 接口 |
| FunctionAdapter | [adapters/function_adapter.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/adapters/function_adapter.py) | 本地Python函数 |

#### 2.5.5 错误码体系 Errors

**6大类错误码**（覆盖全场景）：

| 错误类别 | 前缀 | 说明 | 是否可重试 |
|---------|------|------|----------|
| 系统级错误 | `SYS_` | 系统级故障（服务不可用/资源耗尽） | 部分 |
| 模块节点错误 | `NODE_` | 节点不存在/版本不兼容 | 否 |
| 适配器错误 | `ADAPTER_` | 适配器初始化失败/连接失败 | 部分 |
| 执行错误 | `EXEC_` | 超时/执行失败/降级触发 | 部分 |
| 数据错误 | `DATA_` | 输入校验失败/输出格式错误 | 否 |
| 编排错误 | `ORCH_` | 循环依赖/节点冲突/依赖缺失 | 否 |

---

### 2.6 内核代码目录总览

```
dreamos/                              # Dreambuddy OS 内核主目录
├── core/                             # SACG 四层内核（核心）
│   ├── sense/                        # S层 感知/意图识别 🟢
│   │   ├── intent_engine.py
│   │   ├── token_budget.py
│   │   ├── scenario_classifier.py
│   │   ├── types.py
│   │   └── recognizers/              # 规则/LLM/动态三识别器
│   ├── arrange/                      # A层 编排/图规划 🟢
│   │   ├── graph_planner.py
│   │   ├── node_selector.py          # ★ 从Registry动态选节点
│   │   ├── budget_allocator.py
│   │   ├── execution_graph.py
│   │   └── types.py
│   ├── compute/                      # C层 执行/节点调度 🟢
│   │   ├── graph_executor.py
│   │   ├── node_runner.py            # ★ 路由到适配器
│   │   ├── reflector.py              # 5种反射决策
│   │   ├── aggregator.py
│   │   └── types.py
│   ├── graph_store/                  # G层 存储/检查点/压缩 🟢
│   │   ├── store.py
│   │   ├── checkpointer.py
│   │   ├── compressor.py             # BAC三层压缩
│   │   ├── history.py
│   │   └── types.py
│   ├── capability/                   # 横切：节点注册表 🟢
│   │   ├── registry.py
│   │   └── router.py
│   ├── memory/                       # 横切：内核级记忆（进化/反馈） 🟢
│   │   ├── evaluation_memory.py
│   │   ├── execution_feedback.py
│   │   └── orchestration_memory.py
│   └── scheduler/                    # 横切：调度评估器 🟡
│       └── dynamic_evaluator.py
├── capabilities/trading/             # 能力层（A_domain能力）
│   ├── nodes/                        # A/C/F/G系列节点示例实现
│   │   ├── a0_contradiction.py       # ★ A0矛盾论（代码驱动，7维计算）
│   │   ├── a1_deep_research.py       # A1调研
│   │   ├── a2_comprehensive.py       # A2第一性原理
│   │   ├── a3_strategy.py / a4_gate.py
│   │   ├── a5_execution.py / a6_regime_monitor.py
│   │   ├── a7_practice_gate.py / a8_unity.py / a9_exit_strategy.py
│   │   ├── c1_tech_scan.py / c2_momentum.py / c3_volatility.py / c5_exit_system.py
│   │   ├── f1_news.py / f2_flow_analysis.py / f3_valuation.py
│   │   ├── f4_onchain_data.py / f5_macro_analysis.py
│   │   ├── g1_risk_control.py / g2_governance.py
│   ├── execution/ / evaluators/ / backtest/  # 执行/评估/回测
│   └── evaluator.py / loss_diagnoser.py / ...
├── adapters/                         # 横切：适配器框架 🟢
│   ├── base.py / skill_adapter.py / api_adapter.py / function_adapter.py
├── apps/                             # 应用层入口 🟢
│   ├── trading_agent/agent.py        # TradingAgent
│   ├── api_server.py                 # Flask REST API
│   └── cli.py                        # 命令行工具
├── cli/                              # CLI扩展命令（auto/scheduler/backtest/...）
├── budget/                           # 横切：预算管理 🟢
│   ├── global_budget.py / cost_tracker.py
├── config/
│   └── nodes.yaml                    # 节点注册表YAML（35+模块）
├── data/graph_store/                 # G层检查点存储目录
├── dreamos-tests/                    # OS内核测试
│   └── test_*.py（8个测试套件）
└── README.md
```

---

### 2.7 TypeScript 历史参考版本

> ⚠️ 以下是历史 TypeScript 版本（目录：`6-图结构上下文压缩/`），仅供参考，**不维护、不作为主实现**。当前主实现为上面的 Python 版本。

| OS内核层 | TS组件 | 对应Python组件 | 状态 |
|---------|--------|--------------|------|
| S层 | IntentGateway / ChainPlanner / ChainsRegistry | IntentEngine / GraphPlanner | 🟢 参考 |
| A层 | GraphOrchestrator / GraphExecutor / ReflectEngine | GraphPlanner / Reflector | 🟢 参考 |
| C层 | UnifiedExecutor / VotingCalculator | GraphExecutor / Aggregator | 🟢 参考 |
| G层 | Blueprint / Architecture / Chronicle / Compressor / Checkpointer | BAC三层 + Compressor + Checkpointer | 🟢 参考 |

---

## 三、能力层与模块化体系

> 能力层是OS内核之上的"血肉"，所有具体业务能力都在这里。通过粗-中-细三层模块化体系组织，五大领域分类，统一接口契约，通过适配器框架接入OS内核。
>
> 核心参考文档：`1-ARCHITECTURE/WORKBUDDY_OS_MODULAR_ARCHITECTURE.md` v1.1（详细接口契约和元数据定义）

### 3.1 粗-中-细三层模块化体系

#### 3.1.1 设计原则

| 层级 | 粒度 | 定位 | 示例 |
|------|------|------|------|
| **粗粒度 Layer 1：Domain** | 5大领域 | 按能力属性的顶层分类，便于理解和导航 | A_domain（AI交易能力） |
| **中粒度 Layer 2：Category** | 20+子系统 | 按业务功能的子系统分组，便于整体调用和管理 | 执行闭环（A1-A9节点） |
| **细粒度 Layer 3：Module** | 50+独立模块 | 每个SKILL/功能都是独立模块，最大灵活性 | A2_第一性原理（单节点模块） |

**调用方式**：

| 调用层级 | 示例 | 适用场景 |
|---------|------|---------|
| 细粒度（单模块） | `call_module("A2_第一性原理", input)` | 精确控制调用哪个具体能力 |
| 中粒度（子系统） | `call_category("执行闭环", input)` | 整个子系统协同工作 |
| 跨粒度组合 | `[C1技术扫描, A0矛盾论, F2资金流] → 综合` | 跨领域、跨子系统的定制组合 |
| 动态编排（OS内核） | GraphPlanner + NodeSelector | AI驱动，根据意图和置信度动态选择 |

#### 3.1.2 三层结构图

```
粗粒度 Layer 1: Domain（5 大领域）
│
├── A_domain (AI交易能力)  🟢
│   └── 中粒度 Layer 2: Category（4 个子系统）
│       ├── 三屏交易系统
│       │   └── 细粒度 Layer 3: Module
│       │       ├── Screen1_周线方向（周线级别七维牛熊评分）
│       │       ├── Screen2_日线预设（入场/加仓/止盈/止损挂单）
│       │       └── Screen3_实时执行（盘中撤改挂 + A9离场）
│       ├── 执行闭环
│       │   ├── A0_矛盾论（内嵌到A1/A2/A3，代码驱动7维计算）
│       │   ├── A1_深度调研（Tavily+OKX+链上数据）
│       │   ├── A2_第一性原理（阻力最小+趋势延续）
│       │   ├── A3_策略设计（大师辩论+沙盘推演）
│       │   ├── A4_战术验证（三层索引+委托落地）
│       │   ├── A5_决策执行（综合判断+OKX下单）
│       │   ├── A7_实践论门禁（理论vs实践一致性校验）
│       │   └── A9_离场决策（四层离场+21事件库）
│       ├── 情报闭环
│       │   ├── A6_情报监控（实时雷达+异常检测+5级放射）
│       │   ├── 大师辩论（10位大师分阵营辩论）
│       │   └── 做梦部（弗洛伊德潜意识+反直觉信号）
│       └── 复盘进化
│           ├── A8_知行合一（自我批评+gap_score路由）
│           ├── 数据分析（回测结果/交易日志分析）
│           └── 知识库（领域知识蒸馏存储）
│
├── C_domain (经典量化能力)  🟢
│   ├── 指标库（C1技术扫描 / C2动量 / C3波动率 / C4形态识别）
│   ├── 策略库（趋势/均值回归/突破/套利 等）
│   ├── 回测引擎（参数优化/多场景压力测试）
│   └── 执行引擎（Freqtrade适配器 / Aster执行器）
│
├── F_domain (基本面能力)  🟡
│   ├── F1_新闻聚合（Tavily+财经媒体+社交舆情）
│   ├── F2_资金流分析（ETF流入/机构持仓/交易所余额）
│   ├── F3_情绪分析（FGI恐惧贪婪/多空比/费率）
│   ├── F4_链上指标（地址/巨鲸/活跃地址）
│   └── F5_宏观数据（CPI/Fed利率/就业/地缘）
│
├── G_domain (治理能力)  🟡
│   ├── G1_宪法校验（GOVERNANCE_CHARTER合规）
│   ├── G2_合规审查（风控阈值/仓位限制/禁投标的）
│   ├── G3_风控集成（13-通用风控模块）
│   ├── 成本控制（Token预算/API费用/执行时间）
│   └── 性能评估（延迟/吞吐/准确率）
│
└── T_domain (工具能力)  🟢
    ├── Tavily搜索（外部信息检索）
    ├── 7-产物中台（产物索引+路由+归档）
    ├── 4-MEMORY记忆系统（应用记忆+全局记忆+7接口）
    ├── 15-监控告警系统（监控+告警+通知）
    └── 系统维护（配置管理/日志/健康检查）
```

---

### 3.2 统一接口契约（Module API）

#### 3.2.1 统一调用协议

所有模块（不论粒度、不论语言、不论适配器类型）都遵循完全相同的调用协议：

```python
def execute_module(
    module_id: str,           # 模块唯一标识（如 "A0_矛盾论", "C1_技术扫描"）
    inputs: Dict[str, Any],   # 结构化输入参数（符合输入Schema）
    context: ExecutionContext # 执行上下文（会话/市场/记忆/治理/配置/追踪）
) -> ModuleResult:
    ...
```

#### 3.2.2 ModuleResult 结构

```typescript
interface ModuleResult {
    // ===== 基本信息 =====
    success: boolean;
    module_id: string;
    module_version: string;           // semver
    
    // ===== 核心输出 =====
    direction?: 'LONG' | 'SHORT' | 'HOLD' | 'NEUTRAL';  // 交易类模块的方向输出
    confidence: number;               // 0-1，本次执行的置信度
    outputs: Record<string, any>;     // 结构化输出数据（符合输出Schema）
    
    // ===== 置信度分项（可选但推荐）=====
    confidence_dimensions?: {
        data_completeness: number;      // 数据完整性（缺失项扣分）
        logical_consistency: number;    // 逻辑一致性（内部矛盾扣分）
        cross_validation?: number;      // 交叉验证度（多链/多源匹配加分）
        historical_performance?: number; // 历史表现加权（Registry.accuracy加权）
    };
    
    // ===== 推理过程（可解释性）=====
    reasoning: string[];             // 推理步骤说明（人可读，每条一行）
    warnings?: string[];             // 警告信息（非致命但需注意）
    suggestions?: string[];          // 下一步建议（后续节点/补充分析）
    
    // ===== 成本与性能 =====
    tokens_used?: number;
    latency_ms: number;              // 端到端执行延迟
    execution_mode: 'skill' | 'api' | 'local_fallback' | 'hybrid';
    
    // ===== 错误处理与降级 =====
    error?: string;
    error_code?: string;             // 6大类错误码前缀
    fallback_used?: boolean;
    fallback_reason?: string;
}
```

#### 3.2.3 ExecutionContext 结构

```typescript
interface ExecutionContext {
    // 会话信息
    session_id: string;
    user_id?: string;
    
    // 市场状态（交易类模块必填）
    market_state: {
        symbol: string;
        price: number;
        regime?: string;        // REGIME_UP / REGIME_DOWN / REGIME_RANGE
        volatility_20d?: number;
        // ... 其他市场数据字段
    };
    
    // 记忆系统引用（模块可自行查询/写入）
    memory: {
        lessons: any[];                  // 最近经验（top_k, min_quality=B）
        recent_decisions: any[];         // 近期决策（用于避免重复）
        memory_unit_id?: string;         // 目标应用记忆单元（如 AM-TRD-001）
    };
    
    // 治理约束
    governance: {
        constitution_version: string;    // 宪法版本号
        compliance_level: 'R0' | 'R1' | 'R2' | 'R3';  // 合规级别
        risk_preference: 'conservative' | 'balanced' | 'aggressive';
    };
    
    // 配置
    config: {
        llm_preference: string[];        // LLM偏好顺序（如 ["doubao-pro", "gpt-4o"]）
        max_tokens: number;              // 单次最大Token
        enable_skill_execution: boolean; // 是否允许SKILL真实执行（false=影子模式）
    };
    
    // 产物引用（可复用前序产物）
    context_artifacts?: string[];        // Artifact Hub的产物ID
    
    // 追踪
    trace_id?: string;                   // 分布式追踪ID
    parent_module?: string;              // 父模块ID（嵌套调用场景）
}
```

---

### 3.3 适配器框架

> 适配器框架是OS内核与异构能力之间的"驱动层"。每种适配器将不同类型的能力源转换为统一的 `execute_module()` 接口调用。

| 适配器类型 | 适用场景 | 执行流程 | 示例模块 |
|-----------|---------|---------|---------|
| **SkillAdapter** | TRAE SKILL（通过SKILL.md定义的技能） | 构造SKILL调用参数 → 调用SKILL执行器 → 解析输出 → 包装ModuleResult | A1深度调研 / A2第一性原理 / dream-*系列 |
| **APIAdapter** | HTTP REST API（外部服务/内部服务） | 构造HTTP请求（URL/headers/body）→ 调用（重试+超时）→ 解析响应 → 错误处理 | OKX API / Tavily Search API |
| **FunctionAdapter** | 本地Python函数（纯代码/零外部依赖） | 直接import+调用（异常捕获）→ 包装结果 | C1技术扫描 / F2资金流分析 / A0矛盾论 |

**适配器路由机制**（NodeRunner内部）：
```
NodeRegistry.get元数据(node_id)
    │
    ▼
adapter_type = node_meta.adapter.type  # "skill" | "api" | "function"
    │
    ▼
对应Adapter实例化 + 执行
    │  成功 → ModuleResult（success=true）
    │  失败且可重试 → 重试（最多3次，指数退避）
    │  失败且不可重试/重试耗尽 →
    ▼
fallback触发？
    │  是（fallback_enabled=true）→ 调用fallback模块 → 标记 fallback_used=true
    │  否 → ModuleResult（success=false + 错误码）
```

---

### 3.4 模块元数据与注册表

每个模块在注册表（`dreamos/config/nodes.yaml`）中必须包含以下元数据：

| 元数据项 | 必填 | 说明 | 示例 |
|---------|-----|------|------|
| id | ✅ | 模块唯一标识 | `dream-contradiction-theory` |
| name | ✅ | 模块名称 | `A0 矛盾论分析` |
| description | ✅ | 模块描述（30字内） | `多维度矛盾分析，确定市场主要矛盾` |
| version | ✅ | semver版本 | `v1.0` |
| chain | ✅ | 所属领域链 | `A` / `C` / `F` / `G` / `T` |
| category | ✅ | 中粒度分类 | `执行闭环` / `三屏交易` |
| tags | ✅ | 搜索标签数组 | `["contradiction", "multi-dimension"]` |
| estimated_tokens | ✅ | 预估Token消耗 | `2000` |
| estimated_latency_ms | ✅ | 预估延迟(ms) | `15000` |
| confidence_range | ✅ | 典型置信度范围 | `[0.65, 0.85]` |
| applicable_stages | ✅ | 适用执行阶段 | `["research", "analysis"]` |
| market_conditions | ✅ | 适用市场条件 | `["all"]` / `["regime_trend"]` |
| input_schema | ✅ | 输入参数Schema（name/type/required/description） | 见注册表 |
| output_schema | ✅ | 输出Schema | 见注册表 |
| adapter | ✅ | 适配器配置（type + skill_path / api_url / function_path） | `{type: "skill", skill_name: "..."}` |
| timeout_ms | ✅ | 超时配置 | `120000` |
| retry | ✅ | 重试策略（max_retries / retry_delay_ms / retryable_codes） | 见注册表 |
| fallback | ✅ | 降级策略（enabled / fallback_module / reason） | 见注册表 |
| dependencies | ✅ | 前置依赖模块ID列表 | `["A1_调研", "A2_第一性原理"]` |
| historical_accuracy | 动态 | 历史准确率（自动更新） | `0.78` |
| total_calls | 动态 | 累计调用次数（自动更新） | `356` |
| last_called | 动态 | 最后调用时间（自动更新） | `2026-06-29T20:00:00Z` |

---

### 3.5 重试与降级机制

#### 3.5.1 重试机制

- **可重试错误码**：SYS_001（临时服务不可用）/ EXEC_001（执行超时）/ ADAPTER_001（连接失败）等网络/临时故障
- **最大重试次数**：默认 3 次
- **重试间隔**：指数退避（1s → 2s → 4s）
- **重试过程记录**：完整记录到 trace 中，便于排查
- **重试耗尽**：触发降级流程，或最终返回 `EXEC_002` 错误

#### 3.5.2 降级策略（优先级从高到低）

1. **同类型替换**：优先使用同类别其他模块作为 fallback
   - 例：Screen1_周线方向 不可用 → fallback 到 A2_第一性原理（独立方向判断）
2. **跨链补充**：同领域模块不可用时，跨领域补充
   - 例：A系列方向信号不可用 → 补充 C1技术扫描 + F2资金流 交叉验证
3. **本地规则降级**：所有外部依赖（LLM/SKILL/API）不可用时，使用本地硬编码规则
   - 例：MA200+波动率阈值硬编码规则（置信度低，标记 `execution_mode=local_fallback`）
4. **最终安全态**：所有降级都失败 → 返回 HOLD / PASS 决策，不主动开仓

降级触发时，ModuleResult 中必须标记：
- `fallback_used = true`
- `fallback_reason = "<触发原因，如：Screen1超时2次重试耗尽>"`
- `confidence = min(0.5, 原置信度 * 0.7)`（降级自动降置信度）

---

## 四、应用层与子系统映射

> 应用层是OS内核的"使用者"，包含用户交互入口和具体业务实现的6个交易子系统。子系统不直接接入OS内核——它们的能力模块通过能力层注册，由OS内核动态调度。

### 4.1 应用入口

| 入口 | 代码位置 | 面向用户 | 交互模式 | 状态 |
|------|---------|---------|---------|------|
| **TradingAgent** | `dreamos/apps/trading_agent/agent.py` | AI Agent开发者 | Python调用（S-A-C-G全链路编排） | 🟢 |
| **HTTP REST API** | `dreamos/apps/api_server.py` | 前端/外部系统 | 8个REST端点 | 🟢 |
| **CLI 命令行** | `dreamos/apps/cli.py` + `dreamos/cli/` | 开发者/运维 | 7个子命令 + REPL交互模式 + scheduler/auto/backtest扩展 | 🟢 |
| **三屏交易前端** | `3-FRONTEND/` + `3.1-FRONTEND/` | 交易员/运营 | Next.js Web UI（可视化+交互） | 🟡 |
| **Claude Code + TRAE** | `.claude/settings.json` + `.trae/mcp.json` + MCP Server | 开发者（代码层面） | IDE插件+MCP协议+认知系统hook | 🟢 |
| **8-FEISHU 飞书协作** | `8-FEISHU/` + `6-TRADING/scripts/feishu_notify.py` | 人类决策者 | 飞书群组5个+审批(Gate-C/A9)+Bitable+Wiki+Cron任务+2 Bot | 🟢 |

#### 4.1.1 TradingAgent 内部结构

```
TradingAgent（S-A-C-G 全链路调度）
    │
    ├─ __init__：初始化 S/A/C/G 四层组件
    ├─ run(user_input, market_data) 主入口：
    │   ├─ 1. S层 → 意图识别（IntentEngine → IntentResult）
    │   ├─ 2. A层 → 编排执行图（GraphPlanner → ExecutionGraph）
    │   ├─ 3. C层 → 执行图调度（GraphExecutor → ExecutionReport）
    │   ├─ 4. G层 → 检查点 + 压缩 + 历史记录
    │   └─ 返回：结构化交易决策 + 完整执行轨迹
    │
    ├─ run_scheduled(symbols)：定时批量运行（供 daemon 调用）
    ├─ replay_graph(ckpt_id)：从 G层检查点回放执行
    └─ get_trace(trace_id)：查询指定 trace 的完整轨迹
```

#### 4.1.2 HTTP API 端点

| 方法 | 端点 | 说明 | 对应OS内核层 |
|------|------|------|------------|
| POST | `/api/intent` | 仅意图识别 | S层 IntentEngine |
| POST | `/api/orchestrate` | 完整执行（意图→编排→执行→存储） | S→A→C→G |
| POST | `/api/plan` | 仅构建执行图（不执行） | S→A层 |
| POST | `/api/execute` | 执行预构建的图 | C→G层 |
| GET  | `/api/trace/:trace_id` | 查询执行轨迹 | G层 HistoryReplay |
| GET  | `/api/checkpoint/:ckpt_id` | 查询检查点 | G层 Checkpointer |
| GET  | `/api/nodes` | 列出所有注册节点 | NodeRegistry |
| GET  | `/api/health` | 健康检查 | 全层 |

---

### 4.2 七大交易子系统总览

> 7 个子系统中，6 个已遵循 [DOC_STANDARD.md](../0-系统文档管理/1-规范体系/DOC_STANDARD.md) 规范（5 文档齐全）；17-v4-wave-strategy 为新增子系统，文档待补齐。
>
> 详细文档索引：[SYSTEM_MAP.md](../0-系统文档管理/2-文档地图/SYSTEM_MAP.md) §L2

| 编号 | 子系统名称 | 定位 | 核心模块 | 文档评级 | 状态 |
|------|----------|------|---------|---------|------|
| 10 | **经典指标系统** | 核心交易决策引擎，16层信号体系 | `ml_trade_service.py`(8092) + `classic_exit_system.py` + `carry_service.py` | A | 🟢 |
| 11 | **易经推理系统** | BCRM 2.0 + 易经推理 + 辩证 ML | `polling_trader.py` + `yijing_exit_system.py` + `bcrm2_adapter.py` | A | 🟢 |
| 12 | **三屏趋势系统** | V4+波浪互斥融合趋势策略 | `engine.py` + `signals.py` + `ml/halving_top_exit_strategy.py` | A | 🟢 |
| 13 | **通用风控模块** | 三层风控（事前门禁/仓位/事后离场）+ L1评估 + ML | `core/engine.py`(RiskEngine) + `core/l1_assessor.py` + `core/ml_model.py` | A | 🟢 |
| 14 | **V15经典马丁策略** | V15马丁格尔策略，**文档标杆** | `core/v15_signal.py` + `core/v15_trader.py` + `lib/v15_api_server.py` | A（标杆） | 🟢 |
| 16 | **调控系统** | 跨系统宏观战略离场决策层 | `core/unified_position_query.py` + `core/skill_engine.py` + `core/a9_exit_decision.py` | A-（TECHNICAL_DESIGN范围错位） | 🟡 |
| **17** | **V4波浪策略系统** | V4减半周期+艾略特波浪互斥融合，独立于三屏的BTC专用趋势策略 | `v4_wave_engine.py` + `ewave_strategy_adapter.py` + `ewave_recognizer.py` + `halving_top_exit_strategy.py` | 🔴 待补齐 | 🟢 运行中 |

#### 4.2.1 子系统技术设计文档版本对照

| 子系统 | ENGINEERING_INDEX | TECHNICAL_DESIGN | API_SPEC | CHANGELOG |
|--------|-------------------|------------------|----------|-----------|
| 10-经典指标 | v1.1 | v2.0（`docs/TECHNICAL_DESIGN.md`） | v1.1 | v1.1 |
| 11-易经推理 | v2.6 | v2.9 | v2.9 | v2.9 |
| 12-三屏趋势 | v4.0.0 | v4.0 | v4.0.0 | v4.0.0 |
| 13-通用风控 | —（待完善） | —（待完善） | v1.1.0 | v1.1.0 |
| 14-V15马丁 | v5.1（标杆） | v5.1（标杆） | v3.1 | v5.1 |
| 16-调控 | v2.0 | ⚠️ v1.0范围错位 | v2.0 | v2.0 |
| 17-V4波浪 | 🔴 待建立 | 🔴 待建立（9年回测已验证：BTC年化56.43%，夏普1.41） | 🔴 待建立 | 🔴 待建立 |

---

### 4.3 子系统与 Dreambuddy OS 内核的关系

**重要区分**：7个交易子系统 **≠** Dreambuddy OS 内核。两者关系如下：

```
┌──────────────────────────────────────────────────────────────────────┐
│ Dreambuddy OS 内核（1-ARCHITECTURE/dreamos/）                         │
│                                                                      │
│  S层 IntentEngine ──► A层 GraphPlanner ──► C层 GraphExecutor ──► G层  │
│        │                    │                     │                    │
│        │ NodeRegistry.get() │ NodeSelector.select │ NodeRunner       │
│        ▼                    ▼                     ▼                    │
│  能力层（A/C/F/G/T 五大领域，50+模块，统一适配器接入）                 │
│                                                                      │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       │ 能力模块通过 FunctionAdapter/SkillAdapter 接入
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
┌──────────────────┐      ┌─────────────────────────────────────────┐
│ 14-V15马丁(标杆) │      │ 其他6个交易子系统（10/11/12/13/16/17）    │
│ ┌─────────────┐  │      │                                         │
│ │ 独立入口     │  │      │  各自有独立的入口、CLI、服务端口          │
│ │ v15_trader   │  │      │  各自有独立的数据目录、状态文件           │
│ │ 独立CLI/API  │  │      │  各自独立开发、测试、部署                 │
│ └─────────────┘  │      │                                         │
│                  │      │  与OS内核的关系：                         │
│  标杆：文档最完整 │      │   1. 部分节点作为能力模块被Registry注册   │
│ 独立运行不依赖OS │      │   2. 可独立运行，也可被OS Graph编排调度  │
└──────────────────┘      │   3. 风控模块13号被 G3_风控集成 统一调用  │
                          │   4. 17号依赖12号的物理引擎模块(跨子系统) │
                          └─────────────────────────────────────────┘
```

**关键结论**：
1. **7个交易子系统可以独立运行**（都有自己的服务端口、CLI、配置、数据目录）——这是当前的实际生产运行模式
2. **Dreambuddy OS 内核作为可选的"高级编排层"**：当需要跨子系统调度、A系列完整闭环执行时，子系统的核心能力模块通过Registry被OS内核动态调用
3. **13-通用风控模块是跨子系统的标准组件**：所有子系统的开仓/离场前都必须经过13号风控门禁（G3_风控集成能力统一调用）
4. **16-调控系统是宏观决策层**：跨系统汇总所有持仓，基于宏观信号做出战略离场/减仓决策（独立于单个交易子系统的战术离场）
5. **17-V4波浪策略系统跨子系统依赖12-三屏趋势系统**：导入其物理引擎模块（PhysicsConfidenceScorer / KinematicsEngineer / DynamicsEngineer），但策略逻辑完全独立

---

### 4.4 辅助模块总览

| 编号/名称 | 定位 | 核心能力 | 文档状态 | 状态 |
|----------|------|---------|---------|------|
| **2-KNOWLEDGE 知识库** | 从Skills蒸馏的跨领域系统知识 | 5大域：TRADING/TECHNICAL/THEORY/OPERATIONS/METHODOLOGY | ✅ 完整（5域齐全） | 🟢 |
| **4-MEMORY 记忆系统** | AI Agent的长期记忆（区别于2-KNOWLEDGE的人类知识） | L0工作记忆 + L1应用记忆（5个MU）+ L2总记忆 + 7标准接口 + 质量分级S/A/B/C/D | 🟡 部分完整（L1丰富，L2待充实） | 🟡 |
| **8-FEISHU 飞书协作系统** | 人机协作外部信息层：飞书群组+审批+多维表格+Wiki+Cron任务 | 5群组(研究/交易台/管理/复盘/风控) + 2 Bot(Dream分析推送/Hermes执行接收) + Gate-C/A9审批 + Bitable交易记录 + lark-cli集成 | ✅ README完整 | 🟢 运行中 |
| **7-产物中台** | 产物存储+索引+路由+归档 | Artifact Hub V2：研究中台+市场化中台+交易链路监控+治理控制台 | ⚠️ 部分完整（仅工程索引有） | 🟡 |
| **15-监控告警系统** | 全系统监控+告警+通知 | 监控指标采集+阈值告警+多渠道通知 | ⚠️ 仅README | 🔴 待规范化 |
| **5-BUSINESS 业务管理** | HR+运营+成本管理 | 六部门模型的运营实现 | — | 🔴 规划中 |
| **2-GOVERNANCE 治理系统** | 宪法+合规+审计 | GOVERNANCE_CHARTER + COMPLIANCE_RULES + AUDIT_LOGS | ✅ 文档齐全（实现待对齐） | 🟡 |
| **3-EVOLUTION 进化引擎** | TypeScript版实验性进化 | 发现问题→学习→分析→更新 | ⚠️ 无文档（实验状态） | 🔴 实验中 |
| **6-图结构上下文压缩** | TypeScript版BAC压缩参考实现 | Blueprint/Architecture/Chronicle三层压缩 | ⚠️ 有SPEC/TECHDOC | 🟢 参考 |
| **AGENT协作工具** | 多Agent开发协作辅助（本地+GitHub完整版） | agent-collab-supervisor SKILL（任务卡核验/设计评审/评论协议/测试证据/分支合规）+ GitHub Actions（agent生命周期检查） | ⚠️ 仅SKILL.md | 🟡 辅助非主线 |

#### 4.4.1 8-FEISHU 飞书协作系统详解

> 8-FEISHU 是 Dreambuddy 与人类决策者之间的**外部信息协作层**，不是交易子系统，而是贯穿交易决策闭环和治理闭环的**人机交互通道**。

```
人类决策者（你）
    │
    ├── 飞书群组（5个）          ← 接收报告/通知/审批
    │   ├── Trading-Research      Screen1完整报告 + A1/A2/A3
    │   ├── Trading-Desk          Screen2预设 + 执行日志 + A6监控
    │   ├── Trading-Management    摘要 + A9离场结论 + P&L
    │   ├── Trading-Review        ProcessD复盘
    │   └── Trading-RiskControl   Gate-C/A9审批单 + AI代决通知
    │
    ├── 飞书审批中心              ← Gate-C 入场审批 / A9 离场审批
    │   └── 超时兜底：30min未处理 → AI自动决策（approval_agent.py）
    │
    ├── 多维表格 Bitable          ← 交易记录持久化（Episode全生命周期）
    │   └── 自动化Workflow：新Episode推送/离场Episode推送
    │
    └── Wiki 知识库               ← 交易知识/策略/复盘档案

AI 执行层
    ├── Dream Bot (openclaw)      ← 分析引擎：消息推送/Wiki写入/Bitable/审批/任务/OKR
    └── Hermes Bot (云涯Hermes)   ← 执行引擎：WebSocket接收群消息执行SKILL

Cron 任务
    ├── Screen1-weekly            每周日 20:00
    ├── Screen2-daily             工作日 07:30
    ├── A6-monitor-4h             每 4 小时
    └── ApprovalTimeout-10min     每 10 分钟
```

**与架构其他部分的集成关系**：
- **6-TRADING/scripts/feishu_notify.py**：统一通知脚本，所有飞书推送的入口（screen1/screen2/execution/a6/a9/gate_c_approval/review/bitable/task 共 10 种推送模式）
- **2-GOVERNANCE**：Gate-C/A9 审批流是治理合规体系（§7.4 四层合规）的「门禁层」实现
- **交易决策闭环**：A6 监控报告→飞书推送→人类决策者→审批/驳回→执行，形成人机协同闭环
- **认知系统**：飞书 Wiki 作为 L2 总记忆 MU-INF（信息记忆单元）的外部数据源之一

#### 4.4.2 AGENT协作工具详解

> AGENT协作工具是**开发认知闭环的辅助组件**，用于多Agent协作开发场景的任务卡核验、评审记录检查和分支合规监督。当前为辅助非主线，后期明确接口后可接入认知系统的协议层。

| 组件 | 位置 | 功能 |
|------|------|------|
| agent-collab-supervisor SKILL | `AGENT协作工具/SKILLS/agent-collab-supervisor/` | 核验任务卡存在性 / 设计评审记录 / STARTED&DONE评论 / 非Owner评审 / 测试证据 / 分支策略合规 |
| GitHub Actions | `AGENT协作工具/github-actions/` | `check_agent_lifecycle.py`（Agent生命周期检查）+ `build_agent_lifecycle_payload.py`（生命周期载荷构建） |

**输出结论**：`SUPERVISION_PASS` / `SUPERVISION_REWORK` / `SUPERVISION_BLOCK`

**后期接口规划**：可通过 MCP 协议接入认知系统的协议层，作为开发认知闭环中「评审节点」的自动化监督能力。当前独立运行，不阻塞主开发流程。

> **experiments/ AB交易实验**：多种策略的AB对比实验（实验配置+数据收集+结果分析），❌ 无文档，🔴 待规范化。

#### 4.4.3 deploy/ 部署配置体系

> deploy/ 是 Dreambuddy 的**部署自动化中枢**，负责将 6-TRADING 的 AI 理论架构通过 Hermes 网关部署到云服务器，实现系统级的生产运行能力。

| 组件 | 位置 | 功能 |
|------|------|------|
| **deploy.sh** | `deploy/deploy.sh` | 一键部署入口（3阶段：依赖安装→代码拉取→服务注册） |
| **01-04 脚本** | `deploy/0*.sh` | 分步部署：依赖安装 / 代码克隆配置 / systemd 服务注册 / Hermes 配置初始化 |
| **Hermes 配置包** | `deploy/hermes/` | 预部署的 Hermes 网关配置（config.yaml + 13个SKILL + cron任务 + 记忆） |
| **systemd 服务** | `deploy/*.service` | 3个 Linux 服务：hermes-gateway / group-poller / hermes-dashboard |
| **群消息轮询器** | `deploy/group_poller.py` | 飞书群消息轮询，作为 Hermes WebSocket 的补充 |

**deploy/ 与其他系统的关系**：
- **6-TRADING ← deploy/ → 8-FEISHU**：deploy/ 是 6-TRADING 到 8-FEISHU 的部署桥梁。6-TRADING 的 SKILL 通过 deploy/hermes/skills/ 预部署到 Hermes 网关，Hermes 通过飞书 WebSocket 接收群消息并执行 SKILL，产出研报推送到飞书群组
- **deploy/hermes/skills/**：包含 13 个预部署 SKILL（screen1/2/3-trigger, a6-monitor-trigger, process-d-trigger, approval-timeout-check, agent-collab-gatec, agent-collab-screen1, feishu-gateway-setup, feishu-hermes-debug, hermes-feishu-bot-debug, trading-strategy-optimization, 6-trading-screen1-framework）
- **deploy/hermes/cron/jobs.json**：与 8-FEISHU 的 Cron 任务注册表对应（Screen1周报 / Screen2日报 / A6监控 / 审批超时检查）

#### 4.4.4 6-TRADING 双重定位说明（重要！）

> 6-TRADING 在架构中具有**双重定位**，不能简单归类为单个子系统。

```
6-TRADING 的双重角色
│
├── 角色1：AI 交易研究系统（应用层）
│   ├── A0-A9 九步流水线（矛盾→调研→原理→推演→验证→执行→监控→门禁→离场）
│   ├── 通过 Hermes 部署后，为系统提供自动化研报和交易决策
│   ├── 产物存储于 7-产物中台（artifacts/ 目录）和飞书 Bitable
│   └── bridge/ API 服务（端口 3847）：9个模块化 API 端点
│       └── dream_api_server.py / trade_exec_api.py / market_data_api.py /
│           skill_router_api.py / intent_router_api.py / monitoring.py 等
│
├── 角色2：通用 AI 理论架构（能力层/方法论层）
│   ├── A0矛盾论 / A2第一性原理 / A3大师研讨 / A7实践论 / A8知行合一 等
│   │   这些方法论不局限于交易，可广泛应用于任何复杂决策场景
│   ├── skills/ 目录包含 24+ 个 SKILL，覆盖：
│   │   ├── 0-core-integration/    （5个核心集成：产物对齐/Episode写入/知识/经验蒸馏/提案生成）
│   │   ├── 2-intelligence-integration/（5个智能集成：归档/数据分析/情报分析/大师研讨/做梦部）
│   │   ├── 3-support-integration/ （6个支撑集成：合规/自修复/成本/运营/绩效/资源效率）
│   │   └── A7/A8 理论实践验证     （实践论门禁 + 知行合一自我批评）
│   └── 理论框架可被 OS 内核 A 层动态编排调用（通过 SkillAdapter 接入）
│
└── 架构映射
    ├── 应用层入口：bridge/ API（端口3847）+ scripts/（交易执行/回测/监控）
    ├── 能力层节点：A0-A9 节点 + skills/ 24个SKILL → 通过 Registry 注册
    ├── 产物存储：artifacts/ → 7-产物中台 + sessions/ → 4-MEMORY L1应用记忆
    └── 部署通道：deploy/ → Hermes → 8-FEISHU → 人类决策者
```

**关键区分**：
1. **6-TRADING ≠ 单纯交易子系统**：它既是 A0-A9 流水线的应用实现（应用层），也是 AI 理论架构的方法论载体（能力层）
2. **通过 Hermes 部署后，6-TRADING 成为系统的"研报引擎"**：自动产出 Screen1 周报、Screen2 日报、A6 监控报告等，推送到飞书群组，产物归档到 7-产物中台
3. **A 系列方法论可脱离交易场景独立应用**：A0矛盾论（矛盾分析）、A2第一性原理（本质推理）、A7实践论（理论实践一致性检验）、A8知行合一（自我批评）等方法论，适用于任何需要复杂决策的领域

---

## 五、三大思维链与核心闭环

### 5.1 三链定位：S主骨架 + C量化 + F基本面

三大思维链是 Dreambuddy 进行"思考"的三种底层认知范式，它们不是固定的流水线，而是根据意图动态编排的**思维维度**。

| 思维链 | 定位 | 核心范式 | 五阶段框架 | 典型节点来源 |
|--------|------|----------|-----------|-------------|
| **S 链** | **主骨架（元方法论）** | 从"发现问题"到"落地执行"的通用思考框架 | 调研(S1)→分析(S2)→设计(S3)→验证(S4)→执行(S5) | A系列节点（AI交易能力） |
| **C 链** | **量化导向** | 用数据说话，经典量化分析范式 | 扫描→识别→匹配→回测→参数 | C系列节点（经典指标/策略/回测） |
| **F 链** | **基本面导向** | 用逻辑驱动，宏观/链上/情绪综合研判 | 新闻→资金→情绪→链上→宏观 | F系列节点（新闻/资金流/链上/宏观） |

**关键区分（重要！）**：
- S 链 ≠ OS内核S层：S链是**思维框架**（方法论），S层是**感知组件**（软件实现）。S层在识别意图时会参考 S 链框架，但 S 链本身是 A 层动态选择节点时的编排参考。
- A系列节点是 S 链的"血肉实现"，但 S 链的每一步**并不绑定固定节点**。A 层会根据上下文从 NodeRegistry 中动态挑选最合适的节点填充 S 链骨架。

### 5.2 S链五步框架与 A 系列节点的血肉映射关系

S 链五步提供"骨架"，A 系列节点（A0-A9）是可被动态选中的"血肉"。典型映射如下（非硬编码，仅供参考）：

```
S1 调研      ←→  A1 深度调研(dream-strategy-research)
                  意图：收集矛盾各方信息，建立全局认知
                  输入：标的、市场环境、问题描述
                  输出：调研报告 + 情报清单 + 初步矛盾点

S2 分析      ←→  A0 矛盾识别(dream-contradiction-theory)
              +   A2 第一性原理(dream-first-principles)
                  意图：识别主要矛盾、底层逻辑推演
                  输入：S1报告 + 市场数据
                  输出：矛盾矩阵(7维) + 第一性原理结论

S3 设计      ←→  A3 沙盘推演(master-seminar + tactical-validator)
                  意图：多情景推演 + 10位大师辩论
                  输入：矛盾矩阵 + 交易假设
                  输出：策略方案(多情景) + 风险清单

S4 验证      ←→  A4 战术验证(dream-tactical-validator)
              +   C1 回测引擎
                  意图：历史回测 + 风险压力测试
                  输入：策略方案 + 历史数据
                  输出：回测报告 + 可执行性评分

S5 执行      ←→  A5 决策执行(dream-tactical-executor)
              +   A9 离场决策(dream-exit-skill-v2)
              +   A6 情报监控(dream-intelligence-monitor)
                  意图：开仓 + 监控 + 离场 + 复盘
                  输入：经验证的策略
                  输出：交易信号 + 持仓管理 + 复盘记录
```

**A7/A8 是闭环外挂**：
- A7 实践论门禁：在 A4→A5 之间检查"理论是否经过实践验证"
- A8 知行合一：在 A9 离场后执行，计算 gap_score 驱动治理环

### 5.3 两阶段三链结合策略

对于复杂任务，三链采用 **"阶段一交叉验证 + 阶段二动态融合"** 的两阶段策略：

**阶段一：并行投票（三链独立执行 → 交叉验证）**
```
用户意图
   ├─ S链 → 输出：策略方案_S (置信度0.82)
   ├─ C链 → 输出：策略方案_C (置信度0.75)
   └─ F链 → 输出：策略方案_F (置信度0.68)

投票融合：
  方向一致(≥2链同向) → 通过，进入阶段二
  方向分歧 → 返回 S1 补充情报，标记 high_uncertainty=true
  置信度均值 < 0.5 → 降级返回，触发意图澄清
```

**阶段二：动态节点插入（A 层 GraphPlanner 编排）**
- 若 C 链发现某个技术指标极度超买 → 在 S2 分析后动态插入 C1（超买验证节点）
- 若 F 链发现某条新闻极度敏感 → 在 S5 执行前插入 A6（情报监控加密）
- 三链结论的共识度 → 动态调整 A3 沙盘推演的情景数量和强度

### 5.4 三大核心闭环架构

整个交易决策系统由三个对称的闭环组成，形成**执行-监控-治理**的铁三角：

```
🔵 执行环 (Execution Loop) — 做交易决策
   A1 调研 → A2 分析 → A3 设计 → A4 验证 → A5 开仓 → A9 离场
     ↑                                            ↓
     └──────────── A7 门禁（拦截不成熟决策）──────┘
   周期：单次交易，数小时~数天
   核心指标：胜率、盈亏比、最大回撤

🟠 情报环 (Intelligence Loop) — 持续监控市场
   A6 情报监控(每1小时触发)
     ├─ L0 致命级别 → 直接触发 A9 紧急离场
     ├─ L1 高重要 + L1.5 突变 → 更新 A2 分析 + A4 重验证
     ├─ L2 中等级别 → 观察列表，不触发动作
     └─ L3 背离信号 → 重启 A1+A3 深度分析
   周期：每1小时，5级放射驱动
   核心指标：信号命中率、提前预警时间差

🟣 治理环 (Governance Loop) — 自我进化
   A9 离场 → A7(记录实践) → A8 知行合一(gap_score计算)
                          ├─ gap_score > 0.5 → 矛盾剧烈 → 重启 A1（重新调研）
                          ├─ 0.3 < gap ≤ 0.5 → 有偏差 → 更新 A2 分析逻辑
                          └─ gap_score < 0.3 → 一致 → 优化 A3 参数
                          ↓
                    做梦部(Dream Module) — 非高峰时段深度复盘
                          ↓
                    EvolutionEngine — 升级策略库、知识库、记忆库
   周期：每次交易离场后 + 每日收盘后
   核心指标：gap_score 趋势、策略库升级频率
```

### 5.5 A0 矛盾论内嵌机制

A0（矛盾识别引擎）不是独立节点，而是**内置于 A1→A2→A3 链路的核心机制**，借鉴毛泽东《矛盾论》实现：

**7 维市场矛盾计算**（代码驱动，非 LLM 推理）：
1. **多空矛盾**：多空持仓比 vs 价格趋势方向的背离度
2. **时间矛盾**：短周期(1H)信号 vs 长周期(4H/D)信号的方向冲突
3. **信息不对称矛盾**：成交量放大 vs 价格不动（主力吸筹/出货信号）
4. **流动性矛盾**：买卖盘价差 vs 订单簿深度（滑点风险）
5. **情绪矛盾**：贪婪恐惧指数 vs 当前价位（情绪极端反转信号）
6. **周期矛盾**：当前波动率 vs 历史波动率分位（突破/震荡判断）
7. **结构矛盾**：板块龙头 vs 小弟标的的强弱分化度

**矛盾传递链路**：
```
A1 调研输出 raw_data
   ↓
A0.calculate_7dim_contradictions(raw_data) → contradiction_matrix[7]
   ↓
A2 第一性原理：取矛盾矩阵的 TOP-2（主要矛盾+次要矛盾），
             用《矛盾论》的"主要矛盾决定事物发展方向"进行底层推演
   ↓
A3 沙盘推演：针对 TOP-2 矛盾设计"矛盾解决假设"，
             大师辩论环节专门设置"矛盾正方/反方"角色
   ↓
A9 离场：矛盾是否已解除？→ 作为离场 L2 层的核心判断条件
```

**创伤检测**：若某标的在过去 30 天内曾因同一类矛盾导致 >3% 亏损，标记为 trauma=True，A5 决策时自动乘以 0.8 仓位折扣。

### 5.6 BAC 图压缩模型与意图→链路映射

借鉴 TypeScript 版 BAC（Blueprint/Architecture/Chronicle）三层压缩，将复杂执行图压缩为三层上下文：

| BAC 层 | 存储内容 | 生命周期 | 典型大小 |
|--------|----------|----------|---------|
| **B 层 Blueprint（蓝图）** | 当前任务的目标、约束、最终交付形态 | 会话级 | ≤500 tokens |
| **A 层 Architecture（架构）** | 已执行节点的摘要（输入/输出/置信度/关键判断），保留决策骨架 | 会话级 | ≤3000 tokens |
| **C 层 Chronicle（编年史）** | 完整执行历史 + 原始数据 + 中间产物（可回放、可审计） | 持久化到 G 层 | 无限制 |

**6 种意图 → 6 条标准链路**（IntentEngine 识别后，A 层 GraphPlanner 快速载入）：

| 意图类型 IntentType | 推荐链路 | 基础节点序列 | 典型触发词 |
|-------------------|---------|-------------|-----------|
| **TREND_FOLLOWING** | S链为主 + C链验证 | [A1, A2, A3, C1, A4, A5, A6, A9] | "趋势"、"追涨"、"顺势" |
| **REVERSAL** | F链为主 + C链背离验证 | [F3, C2, A2(矛盾), A3, A4, A5, A9] | "抄底"、"反弹"、"反转" |
| **RANGE_TRADING** | C链为主 + S链风控 | [C3, C4, A2(结构), A3, A4, A5, A9] | "震荡"、"区间"、"高抛低吸" |
| **NEWS_EVENT** | F链为主 + A6监控 | [F1, F2, A2, A3, A4, A6(加密), A5, A9] | "新闻"、"事件"、"美联储"、"ETF" |
| **PORTFOLIO_OPT** | 多链并行 + A7门禁 | [并行(S/C/F各1轮), A7, A3, A4, A5×N] | "组合"、"配置"、"分散" |
| **UNCERTAIN** | 阶段一投票 → 动态规划 | [并行(S/C/F投票融合), 判定后转以上5种之一] | 置信度 < 0.55 或用户提问模糊 |

> **重要**：6条链路是"推荐模板"，不是硬编码固定流水线。A 层 GraphPlanner 会基于上下文对模板进行增删节点、调整顺序。唯一不变的是"A 层不能直接硬编码业务节点，必须走 NodeRegistry.get() + NodeSelector.select()"这条硬约束（见 §10.1）。

---

## 六、认知系统与记忆进化

### 6.1 认知系统定位：开发认知闭环（与交易决策闭环对称）

Dreambuddy 有**两个对称的认知闭环**，一个解决"怎么交易"，一个解决"怎么写代码"：

| 维度 | 交易决策闭环（A系列节点） | 开发认知闭环（本系统） |
|------|------------------------|---------------------|
| **回答的问题** | 这笔交易怎么做？ | 这个代码怎么改？ |
| **触发源** | 用户请求 / 定时调度 / 监控告警 | 文件变更(mtime) / git post-commit hook |
| **核心组件** | A1-A9 + 6个交易子系统 | daemon + git hook + CognitiveSessionManager + MCP Server |
| **记忆交互** | L0(信号/仓位) + L1 AM-TRD + L2 MU-TRD | L0(会话) + L1 AM-DEV/EXP + L2 MU-DEV/MU-DOC |
| **进化机制** | A8 gap_score 路由 + EvolutionEngine | 贝叶斯v2 + 元/应用模板双向反馈 |
| **代码位置** | `6-TRADING/`, `11-易经推理系统/` | `4-MEMORY/9-工具与接口/cognitive_*.py` |

**认知系统 = 开发者的"交易系统"**，交易系统的每一个设计理念（闭环、门禁、进化、监控），认知系统都有对应的对称实现。

### 6.2 三层架构：触发层 + 协议层 + 宿主层

```
┌──────────────────────────────────────────────────────────┐
│  宿主层 Host（IDE 层，AI Agent 运行地）                    │
│  Claude Code  /  TRAE  /  Cursor  /  Continue            │
│  职责：提供AI推理能力、发起MCP调用、展示交互界面            │
└────────────────────────────┬─────────────────────────────┘
                             │ MCP 协议 (JSON-RPC over stdio)
                             ▼
┌──────────────────────────────────────────────────────────┐
│  协议层 Protocol（MCP Server）                             │
│  cognitive_mcp_server.py                                  │
│  职责：暴露 10+ MCP 工具，封装会话/记忆/模板/校验能力       │
│  暴露工具：create_session / recall / record / commit      │
│           on_commit / verify / distill / healthcheck      │
└────────────────────────────┬─────────────────────────────┘
                             │ 本地函数调用 + 文件系统读写
                             ▼
┌──────────────────────────────────────────────────────────┐
│  触发层 Trigger（事件源）                                   │
│  ┌──────────────┐   ┌────────────────┐                   │
│  │ daemon进程   │   │ git post-hook  │                   │
│  │ mtime轮询    │   │ commit message │                   │
│  │ 5s间隔+防抖  │   │ 跨进程接力      │                   │
│  └──────┬───────┘   └───────┬────────┘                   │
│         └───── 互补触发 ────┘                             │
└──────────────────────────────────────────────────────────┘
```

**触发双通道的互补关系**：
- **cognitive_daemon.py**：实时低粒度。捕获"改了什么文件"，但没有 commit message 说明"为什么改"。适合快速发现并开启认知会话。
- **cognitive_hook.py**：延迟高粒度。git commit 时触发，有 commit message（为什么改）+ diff（改了什么），跨进程接力 daemon 创建的会话（通过 .current 文件 + commit_hash）。

### 6.3 认知闭环完整流程（7 步）

```
Step 1: daemon 监听文件变更
  │  cognitive_daemon.py --watch . --interval 5
  │  mtime轮询 → CODE_EXTENSIONS 白名单 → EXCLUDE_DIRS/EXCLUDE_FILES 噪音过滤
  │  (graph_store/checkpoints/scheduler_data 等运行时产物已过滤)
  ▼
Step 2: 防抖合并 (debounce 8秒)
  │  连续变更合并为一个变更批次，避免重复触发
  │  变更数 > 50 时自动升级为 "大规模重构" 标签
  ▼
Step 3: 创建认知会话 (CognitiveSessionManager)
  │  生成 session.json：{session_id, files_changed, metadata, tags, state:"active"}
  │  写入 .current 持久化文件 → 跨进程恢复的关键
  │  富标签提取：infer_task_type（trading-system/trading-data/...）
  │              _extract_rich_tags（kline-data, signal-database, ...）
  ▼
Step 4: recall 注入上下文
  │  调用 MCP: recall(session_id)
  │  从 4-MEMORY L2 搜索相似案例（cosine相似度，top_k=5）
  │  从 L1 搜索同标签的应用记忆
  │  注入 WorkingMemoryManager (L0) 的 context_block
  ▼
Step 5: git hook 触发（用户 git commit 时）
  │  cognitive_hook.py 读取 commit message + diff
  │  尝试通过 session_id 或 commit_hash 关联 daemon 创建的会话
  │  关联失败 → Fallback：基于 commit 信息新建 fallback 会话
  ▼
Step 6: 跨进程会话恢复（接力验证）
  │  hook 进程读取 .current → 加载 session.json → reload_action_chain()
  │  状态：interrupted → resumed → completed
  │  双重 key 兼容（commit_hash / git_commit_hash），避免历史会话 key 不一致
  ▼
Step 7: on_commit（7 个子动作）
  ├─ 7a. 生成 SolutionPath.json（APP-<timestamp>.json）
  │       存：4-MEMORY/1-开发记忆单元/solution_paths/
  ├─ 7b. 事后校验（A8 知行合一）：
  │       实际代码修改 vs SolutionPath 的偏差 → gap_score
  ├─ 7c. 模板沉淀：
  │       本次解决方案 → 蒸馏为 APP-*.json 应用模板
  │       通过 TemplateMappingRegistry 映射到 6 个默认元模板之一
  ├─ 7d. 元反馈：
  │       应用模板效果评分 → 1/√N 加权衰减，反向更新元模板的优先级权重
  ├─ 7e. 记忆蒸馏：
  │       WorkingMemory (L0) → distill_to_app_memory() → L1
  │       L1 质量达标 → DistillScheduler → L2
  ├─ 7f. 记忆更新（贝叶斯v2）：
  │       gap_score 低 → 提升 MU-DEV 相关条目置信度
  │       gap_score 高 → 降低置信度，标记 contradiction
  └─ 7g. 审计 & 健康上报：
          写入 AUDIT_LOGS → 上报 6-应用记忆索引 HEALTH_STATUS
```

### 6.4 双层流程模板系统

借鉴"元认知策略 vs 领域特定策略"的认知科学理论，模板系统分为两层：

```
┌─────────────────────────────────────────────┐
│  元认知模板 Meta Templates（6 个默认）         │
│  存储：4-MEMORY/0-元记忆/template_mappings.json│
│  定义：通用问题解决范式，不依赖具体领域        │
├─────────────────────────────────────────────┤
│  META-01 ResearchFirst       调研优先型       │
│  META-02 ContradictionDriven 矛盾驱动型       │
│  META-03 TestDrivenFix       TDD修复型        │
│  META-04 RefactorInPlace     原地重构型       │
│  META-05 ParallelValidate    交叉验证型       │
│  META-06 UnknownExploration  探索未知型       │
└──────────────────┬──────────────────────────┘
                   │ TemplateMappingRegistry 映射
                   │ + 1/√N 加权衰减反向反馈
                   ▼
┌─────────────────────────────────────────────┐
│  应用认知模板 App Templates（领域特定）        │
│  存储：4-MEMORY/1-开发记忆单元/solution_paths/│
│  命名：APP-<timestamp>.json                  │
├─────────────────────────────────────────────┤
│  APP-1785405385546  OKX密钥迁移到.env         │
│  APP-1785406016201  RiskManager异常处理改造   │
│  APP-1785405442691  dedup状态去重同步         │
│  APP-1785292560413  跨进程会话恢复方案         │
│  ... (持续积累)                               │
└─────────────────────────────────────────────┘
```

**应用→元反馈机制（1/√N 加权衰减）**：
- 每次 App 模板成功执行后，计算效果评分 s ∈ [0, 1]（基于 gap_score 反向映射）
- 更新对应 Meta 模板权重：`w_meta += s / sqrt(N_meta)`，N_meta 是该 Meta 被使用次数
- 作用：使用次数越多的元模板，单次反馈影响越小 → 成熟元模板稳定、新星元模板可快速爬升
- 代码位置：`cognitive_loop_entry.py` → `_update_meta_template_weights()`

### 6.5 贝叶斯驱动的记忆进化 v2

**数学基础**：
- **先验-后验共轭**：Beta-Binomial 共轭分布。每条记忆的"有效性"是一个 Bernoulli 概率 p ~ Beta(α, β)。每次验证成功 → α+1，失败 → β+1。
- **全概率公式**：新观察 O 对记忆 M 的影响 = P(M|O) = P(O|M)·P(M) / P(O)，同时考虑相关记忆的间接影响（一阶马尔可夫链）。
- **指数遗忘**：置信度乘 exp(-λ·Δt)，λ = ln2 / T_half，半衰期 T_half 默认 30 天。长期未验证的记忆自动降级。

**5 级质量分级（双门槛：置信度 + 独立验证次数）**：

| 等级 | 含义 | 置信度门槛 | 独立验证次数 | 验证要求 |
|------|------|-----------|-------------|---------|
| **S 公理级** | 业界公认真理 | ≥ 0.98 | ≥ 10 次，至少 3 个场景 | 需 2 人以上复核 + 理论证明 + 10 次以上 |
| **A 可信级** | 经反复验证 | ≥ 0.85 | ≥ 3 次，至少 2 个场景 | 交叉验证 + 文档化 |
| **B 待验证** | 初步验证 | ≥ 0.60 | 1-2 次 | 单次验证，待扩展 |
| **C 假设级** | 未经实证 | ≥ 0.30 | 0 次 | 仅逻辑推演，有理论支撑 |
| **D 已证伪** | 被证明错误 | < 0.30 | （负证据 ≥ 2次） | 保留但标注 RED FLAG，禁止作为决策依据 |

**蒸馏四阶段路径**：
```
具体案例（L1 应用记忆，一条交易或一次开发记录）
   ↓  DistillScheduler：同主题 ≥ 3 条 + 质量 ≥ B
一般经验（5-通用经验，TECH_LESSONS / BEST_PRACTICES / ANTI_PATTERNS）
   ↓  ConsolidationEngine：≥ 5 条经验 + 质量 ≥ A
方法论（2-方法论记忆，A1_RESEARCH_METHOD / A8_THEORY_PRACTICE / CONTRADICTION_METHOD）
   ↓  A8 知行合一校验 + 人工评审（每季度）
原则（1-原则记忆，ENGINEERING_PRINCIPLES / 治理宪章条款）
```

### 6.6 交易领域感知

认知系统必须能区分"开发代码的变更"和"交易运行时产生的噪音文件"，并精准分类到正确的记忆单元：

**Step 1: infer_task_type 任务类型分类**

| 路径特征 | 任务类型 | 说明 |
|---------|---------|------|
| 文件名含 kline/candle/ohlcv + 扩展名 parquet/csv/json | trading-data | 交易行情数据 |
| 路径含 signal_pool / artifacts | trading-data | 信号/产物数据 |
| 路径含 memory/ + 扩展名 .json | trading-data | 交易状态记忆 |
| 路径在 6-TRADING/, 11-易经推理系统/, 12-马丁策略/ 等 | trading-system | 交易系统代码 |
| 路径在 1-ARCHITECTURE/, 4-MEMORY/, dreamos/ | architecture-design | 架构/记忆系统设计 |
| 路径含 .tsx/.vue/.css/.scss/ | frontend-development | 前端开发 |
| 路径在 8-CUSTOMER/, 7-USER-CENTER/, 13-产品与运营/ | product-platform | 产品运营平台 |
| 其他 .py/.ts/.js/.md | general-development | 通用开发 |

**Step 2: _extract_rich_tags 富标签细分**

基于路径/文件名/扩展名的关键词匹配，产出数组型标签，后续用于记忆检索：
```
示例：11-易经推理系统/data/ETHUSDT_klines_4h.parquet
  → 标签：["trading-data", "kline-data", "eth", "4h-timeframe", "parquet-format"]

示例：4-MEMORY/1-开发记忆单元/solution_paths/APP-1785406016201.json
  → 标签：["development", "solution-path", "risk-management", "mu-dev"]

示例：6-TRADING/scripts/trading_utils.py
  → 标签：["trading-system", "risk-manager", "python", "core-logic"]
```

**Step 3: 应用记忆单元映射**

```
task_type = trading-system + 标签含 risk-management → AM-TRD-RSK-001（风控应用记忆）
task_type = trading-data + 标签含 kline-data      → AM-TRD-EXP-042（交易实验/行情）
task_type = architecture-design + 标签含 memory   → AM-DEV-ARC-007（架构/记忆系统）
task_type = frontend-development                   → AM-DEV-FE-018（前端开发）
```

### 6.7 与其他系统的集成

**(1) 与 4-MEMORY 记忆系统的 L0/L1/L2 三层关系**

```
AI Agent (宿主层)
    │
    ├─ 写入/读取 L0 工作记忆
    │   WorkingMemoryManager
    │   单次任务生命周期
    │   └─ context_block（注入的知识/经验） + scratch_block（中间产物）
    │        ↓ distill_to_app_memory()
    ├─ 写入/读取 L1 应用记忆
    │   AM-TRD / AM-RSK / AM-OPS / AM-EXP / AM-DEV
    │   JSON + SQLite（向量）
    │   子系统级生命周期
    │        ↓ DistillScheduler（质量达标后上升）
    └─ 读取 L2 总记忆（写入受限，需蒸馏审核）
        MU-DEV（开发） / MU-TRD（交易） / MU-DOC（文档） / MU-INF（信息）
        Markdown + bayesian_memories.json
        全局长期生命周期
```

**(2) 与 Git 的跨进程恢复接力验证**
- daemon 进程（Python）和 git hook 进程（由 git 调起，独立进程）之间无共享内存
- 接力机制：daemon 写 `.current` 到磁盘 → hook 读 `.current` 找 session_id
- 若 daemon 已停止 → fallback 机制：用 commit message + diff 新建会话
- 双重 key 兼容：commit_hash 和 git_commit_hash 两种写法都能匹配历史会话
- 验证：`test_cognitive_session.py` 18 个单元测试含 `test_cross_process_recovery`

**(3) 与 IDE 宿主层的适配**
- 通过 `cognitive_mcp_server.py`（JSON-RPC over stdio）暴露 MCP 工具
- Claude Code：在 config 中添加 mcp server 配置即可
- TRAE / Cursor：遵循 MCP 协议标准，接入方式一致
- 宿主层无状态切换：会话状态持久化在磁盘，重启 IDE 不丢失

**(4) 与 Dreambuddy OS 内核 Evolution 引擎的区分**

| 维度 | 认知系统（开发侧） | Evolution 引擎（交易侧） |
|------|-----------------|----------------------|
| **优化对象** | 代码、文档、架构 | 交易策略、参数、信号规则 |
| **输入源** | 文件变更 + git commit | 交易结果 + A8 gap_score |
| **执行时机** | 开发时（实时） | 非高峰（收盘后/低波动时） |
| **输出** | SolutionPath + 模板 + 记忆升级 | 参数建议 + 策略库升级 + 交易知识更新 |
| **关系** | 对称设计，互不耦合 | 两者写入不同记忆单元，检索时交叉召回 |

---

## 七、公司中枢与治理体系

### 7.1 六部门模型 + 六人董事会

借鉴现代企业治理架构，将 Dreambuddy 的 AI 能力组织为六个"虚拟部门"+一个"六人董事会"决策机制：

```
              ┌───────────────────────────┐
              │   六人董事会（最终决策层）  │
              │   每个部门出 1 名代表       │
              │   重大决策：≥5/6 同意通过    │
              └─────────────┬─────────────┘
                            │
        ┌───────────┬───────┼───────┬───────────┐
        ▼           ▼       ▼       ▼           ▼
  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
  │研究部   │ │交易部   │ │风控部   │ │技术部   │ │运营部   │ │市场化部│
  │Research │ │Trading  │ │Risk     │ │Tech     │ │Ops      │ │Growth   │
  │A1/A2    │ │A5/A6/A9 │ │RiskMgr  │ │Dev+Infra│ │HR+Admin │ │Product  │
  │知识生产 │ │信号执行 │ │一票否决 │ │工具体系 │ │资源调度 │ │用户增长│
  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

| 部门 | 核心职责 | 对应AI能力/模块 | 否决权范围 |
|------|---------|---------------|-----------|
| **研究部** | 市场调研、策略研发、知识生产 | A1/A2/A3、情报系统、2-KNOWLEDGE、6-RESEARCH | 无（建议权） |
| **交易部** | 信号执行、持仓管理、交易复盘 | A5/A6/A9、6-TRADING、11-易经推理、12-马丁策略 | 交易时机否决 |
| **风控部** | 风险监控、熔断执行、合规检查 | RiskManager / A7 门禁 / 2-GOVERNANCE | **全链路一票否决**（可直接拒绝开仓） |
| **技术部** | 系统架构、开发工具、运维部署 | 认知系统 / 记忆系统 / Evolution / 15-监控告警 | 技术风险否决 |
| **运营部** | 人力、文档、资源、成本管理 | 5-BUSINESS / 0-系统文档管理 / 4-MEMORY 健康 | 资源透支否决 |
| **市场化部** | 产品、用户、竞品、增长 | 13-产品与运营 / 7-用户中心 / 8-客户中心 | 产品方向否决 |

**董事会决策流程**：
1. 任何部门可发起提案 → 附研究数据 + 风险评估
2. 六人投票（每个部门1票）
3. ≥5/6 通过 → 立即执行
4. 3-4/6 通过 → 标记"有争议"，追加沙盘推演(A3)一轮
5. ≤2/6 → 否决，返回研究部补充

### 7.2 双中台：研究中台 + 市场化中台

前台部门（交易/市场化）依赖两个中台共享服务，避免重复造轮子：

**(1) 研究中台（知识生产引擎）**

```
┌─────────────────────────────────────────────────┐
│                  研究中台                          │
├────────────┬──────────────┬─────────────────────┤
│ 报告服务    │ 数据服务     │ 知识服务             │
│            │              │                     │
│ ·策略研报   │ ·行情聚合    │ ·知识库(2-KNOWLEDGE) │
│ ·行业分析   │ ·多源拼接    │ ·向量检索服务        │
│ ·个股点评   │ ·回测数据集  │ ·术语词典            │
│ ·复盘报告   │ ·因子库      │ ·认知检索(记忆+知识)  │
└────────────┴──────────────┴─────────────────────┘
        ↑              ↑               ↑
  ┌─────┘              │               └────┐
  │ 研究部             数据工程            市场化部
  │ (内容消费方)      (基础设施)          (运营需求方)
```

**(2) 市场化中台（增长与运营引擎）**

```
┌─────────────────────────────────────────────────┐
│                 市场化中台                         │
├────────────┬──────────────┬─────────────────────┤
│ 产品服务    │ 用户服务     │ 竞品服务             │
│            │              │                     │
│ ·需求管理   │ ·用户画像    │ ·竞品监控           │
│ ·原型设计   │ ·分层运营    │ ·功能对比           │
│ ·版本规划   │ ·反馈归集    │ ·趋势跟踪           │
│ ·AB测试    │ ·增长实验    │ ·对标分析           │
└────────────┴──────────────┴─────────────────────┘
```

### 7.3 双交易工作流：投资研究 + 交易运营

交易部拆分为两个角色工作流，对应现实中的"分析师"和"交易员"分离：

**工作流 A：投资研究（分析师流）**
```
市场扫描（A1 定时调研）
   ↓ 发现机会 / 风险
标的入库（写入 5-WATCHLIST，附初始评级）
   ↓ 评级 ≥ A
深度研究（A1 + A2 + F链全面分析）
   ↓ 产出研究报告
策略设计（A3 沙盘 + C链回测）
   ↓ 回测 Sharpe ≥ 1.5 + 胜率 ≥ 55%
提交董事会审议（附报告 + 回测 + 风控预案）
   ↓ ≥5/6 通过
纳入正式策略库（6-RESEARCH/STRATEGY_LIBRARY）
```

**工作流 B：交易运营（交易员流）**
```
从策略库读取候选策略
   ↓
A7 实践门禁：该策略在当前市场匹配度？
   ↓  通过
A5 决策执行：
  · 置信度仓位（conf_factor × 基准仓位）
  · 方向折扣（做空 × 0.95）
  · 排序执行（置信度从高到低）
   ↓  开仓成功
A6 情报监控：持续盯盘，L0/L1/L2/L3 分级处理
   ↓  触离离场条件（L0 紧急 / L1 信号 / L2 逻辑 / L3 时间）
A9 离场决策：执行离场
   ↓
A8 知行合一：gap_score 计算 + 复盘记录
   ↓
治理环：更新记忆 / 调整策略 / 升级参数
```

### 7.4 治理合规体系

四层治理架构，从"宪法"到"执行日志"全链路可追溯：

```
L1 宪法层（宪章）
  └─ 2-GOVERNANCE/GOVERNANCE_CHARTER.md
     · 系统根本大法：使命、架构、权限边界、六部门权责
     · 修改要求：≥5/6 董事会通过 + 季度评审

L2 规则层（合规检查清单）
  ├─ COMPLIANCE_RULES.md — 合规规则总表
  │    · 交易类：单标的仓位上限 / 日内交易次数 / 总敞口限制
  │    · 安全类：密钥硬编码扫描 / 反序列化禁用清单
  │    · 代码类：lint通过率 / 测试覆盖率 / 文档覆盖率
  │    · 资金类：单日亏损熔断阈值 / 连续亏损暂停阈值
  └─ 自动扫描：cognitive_daemon 内置合规检查钩子

L3 门禁层（执行时检查）
  ├─ A7 实践门禁：策略执行前的理论-实践一致性检查
  ├─ RiskManager.can_trade()：开仓前的熔断/敞口/暂停检查
  │     · _save_failed = True 时，拒绝一切开仓（D062 修复）
  ├─ dedup 去重：4h 窗口内信号去重（D081 同步）
  └─ 意图澄清：IntentEngine 置信度 < 35% → 拒绝执行，请求澄清

L4 审计层（事后追溯）
  ├─ AUDIT_LOGS/ — 全量审计日志（加密 + 不可篡改）
  │    · 每次交易：决策依据 + 信号参数 + 执行结果 + gap_score
  │    · 每次代码变更：SolutionPath + 实际 diff + gap_score
  │    · 每次治理动作：投票记录 + 决议内容 + 执行情况
  ├─ 4-MEMORY/versions/ — MemOS 版本控制（记忆文件快照链）
  │    · commits.json：版本链索引
  │    · snapshots/<commit_id>/：9 个 Tier0/Tier1 文件快照
  └─ AI 黑箱治理：每次 LLM 调用记录 → prompt/response/tokens/latency
       · 用于：事后分析 LLM 幻觉、token 成本归因、prompt 效果评估
```

### 7.5 意图识别增强：IntentGateway + ChainPlanner

基础 IntentEngine（见 §2.1）之上的增强层，专门处理复杂多意图请求：

**IntentGateway（多意图拆解与路由）**
```
用户："分析BTC和ETH的趋势，对比一下哪个更值得买入，
      顺便给我最近的交易复盘"
   ↓  IntentGateway.parse()
意图拆解：
  [1] TREND_FOLLOWING（BTC）  → 推荐链路：S+C
  [2] TREND_FOLLOWING（ETH）  → 推荐链路：S+C
  [3] COMPARE([1],[2])        → 推荐链路：A3 横向对比
  [4] REVIEW_RECENT_TRADES    → 推荐链路：A7/A8 + MU-TRD 检索
   ↓
依赖图构建：[1]和[2]可并行，[3]依赖[1][2]完成，[4]独立
   ↓
并行执行：ThreadPoolExecutor(max_workers=2)
   ↓
结果聚合：按 COMPARE 语义输出对比表格 + 复盘报告
```

**ChainPlanner（四维规划过滤）**

GraphPlanner 选中推荐链路后，ChainPlanner 再用四维过滤器裁剪节点：

| 维度 | 过滤器 | 作用 |
|------|--------|------|
| **时间维** | 截止时间 vs 预计执行耗时 | 删除 A3 沙盘等重节点（紧急模式） |
| **成本维** | Token 预算（BudgetLevel） | LLM 节点降级为规则节点（省钱模式） |
| **置信度维** | 目标置信度阈值 | 追加验证节点（高标准模式） |
| **风险维** | 风险偏好设置 | 追加风控节点/加大仓位折扣（保守模式） |

---

## 八、数据流与通信协议

### 8.1 端到端数据流全景

从用户输入到结果返回的完整路径，覆盖 OS 内核 SACG 四层 + 能力层 + 适配器：

```
用户请求（自然语言 / CLI / HTTP API / 前端 UI）
   │
   ▼
┌────────────────────────────────────────────────────┐
│  应用层（§4 六大交易子系统 + 前端 + CLI）             │
│  职责：提供入口、参数校验、用户交互、结果可视化       │
└──────────────────────┬─────────────────────────────┘
                       │ 结构化请求（IntentInput）
                       ▼
┌────────────────────────────────────────────────────┐
│  S 层 Sense 感知层（OS 内核）                        │
│  IntentEngine.recognize()                           │
│    1. RuleBasedRecognizer（零Token，规则打分）        │
│       置信度 ≥ 0.55 → 直接返回                       │
│       置信度 < 0.35 → 标记 clarify_needed=True      │
│    2. Token预算充足 → LLMBasedRecognizer             │
│    3. DynamicRecognizer（自定义扩展）                │
│  输出：IntentResult（intent_type/confidence/         │
│        recommended_chain/base_chain/extend_nodes）   │
└──────────────────────┬─────────────────────────────┘
                       │ IntentResult
                       ▼
┌────────────────────────────────────────────────────┐
│  A 层 Arrange 编排层（OS 内核）                       │
│  GraphPlanner.plan() + NodeSelector.select()        │
│    1. 载入 6 条标准链路模板之一                      │
│    2. ChainPlanner 四维过滤（时间/成本/置信/风险）    │
│    3. NodeRegistry.get() 动态查找节点元数据          │
│    4. 插入横切节点（A7门禁/审计/监控）               │
│  输出：ExecutionGraph（节点DAG + 边依赖 + 预算）     │
└──────────────────────┬─────────────────────────────┘
                       │ ExecutionGraph
                       ▼
┌────────────────────────────────────────────────────┐
│  C 层 Compute 执行层（OS 内核）                      │
│  GraphExecutor.run()                                │
│    1. 拓扑排序 → 调度线程池执行节点                  │
│    2. 每个节点走适配器框架（§3.3）                   │
│       SkillAdapter / APIAdapter / FunctionAdapter   │
│    3. 重试机制：max_retry=3 + 指数退避               │
│    4. 降级策略：fallback_node / default_value       │
│    5. Aggregator 聚合多分支结果                      │
│    6. Reflector 检测环路 / 死循环 / 置信异常         │
│  输出：NodeResult[]（每个节点的输出+置信度+耗时）     │
└──────────┬───────────────────────────────┬─────────┘
           │ 节点内部调用                   │ 运行时状态
           ▼                               ▼
┌──────────────────────────┐  ┌──────────────────────────────┐
│  能力层（§3 模块化体系）   │  │  G 层 GraphStore（OS 内核）    │
│  · 5大领域 A/C/F/G/T     │  │  · Checkpoint：每步执行快照    │
│  · 35+ 模块配置          │  │  · Chronicle：完整执行历史     │
│  · 11+ 本地节点实现      │  │  · BAC 三层压缩               │
│  · 统一 Module API       │  │  · 向量索引（相似历史检索）    │
└──────────┬───────────────┘  └──────────────────────────────┘
           │ 模块对外调用
           ▼
┌────────────────────────────────────────────────────┐
│  适配器框架（§3.3 + §8.5）                          │
│  · SkillAdapter：→ TRAE Skill（MCP封装）             │
│  · APIAdapter：→ HTTP REST（OKX/其他交易所）         │
│  · FunctionAdapter：→ 本地Python函数调用             │
└──────────┬───────────────────────────────┬─────────┘
           ▼                               ▼
   外部服务（OKX API / 数据源 /      本地执行（LLM推理 /
   资讯 API / 第三方 MCP Server）     回测引擎 / 风控计算）
```

### 8.2 模块调用协议 MEP（Module Execution Protocol）

所有能力层模块（无论 A/C/F/G/T）必须遵守统一的 MEP 协议，确保可组合性和可观测性：

**输入契约（ModuleInput）**：
```python
@dataclass
class ModuleInput:
    module_id: str                    # 如 "A1-RESEARCH"
    version: str = "latest"           # 支持版本路由
    context: Dict[str, Any]           # 上游节点输出 + 全局上下文
    params: Dict[str, Any]            # 本节点专属参数
    budget: Dict[str, Any]            # {"tokens": 4000, "timeout_ms": 30000}
    confidence_floor: float = 0.0     # 置信度下限（低于则降级）
    trace_id: str                     # 全链路追踪ID
    span_id: str                      # 当前节点 span
```

**输出契约（ModuleResult）**：
```python
@dataclass
class ModuleResult:
    module_id: str
    success: bool
    confidence: float                 # 0.0~1.0，沿链路传递
    data: Dict[str, Any]              # 结构化输出
    artifacts: List[ArtifactRef]      # 产物引用（存 G 层）
    errors: List[ModuleError]         # 错误链（含错误码 + 建议）
    latency_ms: int
    tokens_used: int
    fallback_triggered: bool          # 是否走了降级
    next_hint: List[str]              # 对下游的建议（追加哪些节点）
```

**置信度传递规则**：
- 串行节点：final_conf = Π（各节点 confidence），乘法累积衰减
- 并行分支投票：final_conf = Σ(w_i × conf_i) / Σw_i，w_i = 分支节点权重
- 任一节点 conf < confidence_floor → 整图标记 degraded=True，结果末尾附警告

**错误传播规则**：
- Fatal（ErrorCode 1xx）→ 立即终止，向上冒泡，执行 on_failure 钩子
- Retryable（ErrorCode 2xx）→ 重试 ≤ max_retry，仍失败转降级
- Degraded（ErrorCode 3xx）→ 记录错误，走 fallback，结果标记 degraded=True
- Info（ErrorCode 4xx）→ 仅日志，不影响执行

### 8.3 前后端分工

```
┌─────────────────────────────────────────────────────────────┐
│  后端（Python 为主）                                          │
│                                                             │
│  · Dreambuddy OS 内核（S/A/C/G 四层，dreamos/）              │
│  · 能力层（35+ 模块 + 适配器框架）                            │
│  · 6 大交易子系统（11-易经推理/6-TRADING/12-马丁/10-CTA/...）│
│  · 认知系统（daemon/MCP/会话管理器）                          │
│  · 记忆系统（4-MEMORY L0/L1/L2 + 贝叶斯更新器）               │
│  · 外部服务适配器（OKX/万得/FMP/...）                        │
│  · 治理引擎（Evolution / A8 知行合一）                       │
│  · 持久化存储（SQLite向量库 / JSON状态文件 / G层检查点）      │
│                                                             │
│  对外接口：                                                  │
│    · ml_trade_service:8092（推理服务 HTTP API）              │
│    · dreamos_api（OS内核对外 HTTP API，规划中）              │
│    · v15_api_server（V15 策略 API）                         │
│    · MCP over stdio（认知/记忆工具，供IDE调用）              │
│    · CLI 命令（polling_trader.py / cognitive_loop_entry.py）│
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / WebSocket / MCP
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  前端（React + TypeScript + Vite 为主）                       │
│  dream-ai-platform/  目录                                    │
│                                                             │
│  页面与功能：                                                │
│  · Dashboard：总览仪表盘（持仓/盈亏/风险指标/系统状态）      │
│  · TradingDesk：交易操作台（信号列表/手动下单/监控图表）     │
│  · StrategyLab：策略实验室（策略库/回测/参数优化）           │
│  · MemoryStudio：记忆工作台（浏览/编辑/蒸馏/质量评估）       │
│  · CognitiveBoard：认知面板（会话列表/SolutionPath/模板库）  │
│  · GovBoard：治理面板（部门看板/决策记录/合规审计）          │
│  · RiskCenter：风控中心（熔断日志/敞口/压力测试）            │
│  · Settings：设置（密钥管理/环境切换/通知渠道）              │
│                                                             │
│  状态管理：React Query + Zustand；图表：ECharts + Lightweight│
└─────────────────────────────────────────────────────────────┘
```

**禁止事项**（分层违规）：
- ❌ 前端不得包含任何交易决策逻辑、风控计算、策略代码（必须走后端 API）
- ❌ 前端不得直接读写 OKX API 密钥、数据库（必须通过后端代理）
- ✅ 前端可以做：展示、交互、纯前端的 UI 状态缓存、乐观更新

### 8.4 双语言桥接：Python 主实现 + TS 参考 + MCP 协议

| 维度 | Python 版 | TypeScript 版 | MCP 协议 |
|------|----------|--------------|---------|
| **定位** | **主实现**：OS 内核 + 能力层 + 子系统 + 认知/记忆 | **参考实现**：BAC 压缩 / Evolution 实验 / 前端部分组件 | 跨进程/跨语言的能力互通标准 |
| **目录** | 全局大部分目录 | `1-ARCHITECTURE/`（TS版参考）/ `dream-ai-platform/` | `4-MEMORY/9-工具与接口/cognitive_mcp_server.py` |
| **同步策略** | 变更领先，作为事实源 | 仅参考，不作为 Python 实现的约束；实验验证通过后反向迁移到 Python | 版本号对齐 MCP spec v2.x |
| **边界** | Python 调 TS：仅允许 subprocess 方式调用 `ts-node` 特定脚本（有审计） | TS 调 Python：通过 MCP Client 调用 cognitive_mcp_server，不允许直接 subprocess Python 文件 | MCP = 唯一允许的跨进程语言桥接方式（JSON-RPC over stdio，无端口安全隐患） |

**MCP 协议细节（cognitive_mcp_server.py）**：
```
传输层：
  · JSON-RPC 2.0 格式
  · over stdio（stdin 读请求，stdout 写响应，stderr 写日志）
  · 无端口，无 HTTP，无网络依赖 → 天然安全

已暴露工具（10+）：
  · create_session(session_info) → session_id
  · recall(session_id, query, top_k, quality_floor) → memories[]
  · record(session_id, memory_entry) → memory_id
  · commit(session_id, commit_info) → commit_id
  · on_commit(session_id, commit_hash, diff, message) → solution_path_id + gap_score
  · verify(session_id, actual, expected) → verify_result
  · distill(from_layer, to_layer, candidate_ids) → distilled_memory_ids
  · healthcheck() → {pipeline: ok, schema_compliance: 0.xx, ...}
  · list_templates(scope="meta"|"app") → templates[]
```

### 8.5 适配器路由详解：三适配器内部流程

所有能力层模块对外部的调用统一走 Skill/API/Function 三大适配器。以下是每个适配器的内部流程：

**(1) SkillAdapter → TRAE Skill（MCP 封装调用）**

```
模块调用 SkillAdapter.execute(skill_name, params)
   │
   ├─ 1. 注册表查找：SkillRegistry.get(skill_name)
   │       → 检查 skill 状态（active/deprecated/experimental）
   │       → 检查 scope 权限（是否允许当前模块调用）
   │
   ├─ 2. 前置钩子：
   │       · 参数校验（Pydantic Schema）
   │       · 幂等 key 生成（防重复执行）
   │       · 预算预扣（tokens）
   │
   ├─ 3. 执行：
   │       · 通过 run_mcp() 调用 MCP Server 对应 Skill
   │       · 超时监控（timeout_ms），剩余时间 <20% 触发软中断
   │
   ├─ 4. 重试分支：
   │       RetryableError → sleep = base * (2^attempt + jitter)
   │       仍失败 → 降级判断
   │
   ├─ 5. 降级：
   │       · 有 fallback_skill → 调用备用 Skill
   │       · 有 default_value → 返回默认值 + mark degraded
   │       · 都没有 → 抛出 DegradedError
   │
   └─ 6. 后置钩子：
           · 预算结算（实际 tokens 退还差额）
           · 审计日志（含输入输出摘要，不含敏感数据）
           · 指标上报（成功率/延迟/降级率）
           → 返回 ModuleResult
```

**(2) APIAdapter → 外部 HTTP REST（交易所/数据源等）**

```
模块调用 APIAdapter.execute(service, endpoint, params)
   │
   ├─ 1. 服务发现：ServiceRegistry.resolve(service)
   │       → base_url, auth_method（API Key / OAuth / 签名）
   │       → 健康状态（circuit_breaker状态）
   │       · circuit_breaker = open → 直接走降级，不发请求
   │
   ├─ 2. 请求构造：
   │       · OKX：签名 + timestamp + passphrase（HMAC-SHA256）
   │       · 其他：按 API 文档要求加 header/query/body
   │       · 添加 request_id 头（全链路追踪）
   │
   ├─ 3. HTTP 执行：httpx.AsyncClient（async优先）
   │       · 连接池复用
   │       · 超时：connect=5s / read=30s / write=10s
   │       · 自动重试：429（加Retry-After）/ 5xx（最多2次）
   │
   ├─ 4. 响应处理：
   │       · 2xx → JSON 解析 → Pydantic 校验
   │       · 4xx → 分类：Auth → Fatal；RateLimit → 退避重试；Business → Degraded
   │       · 5xx → 熔断计数 +1；计数 > 阈值 → circuit_breaker = open (30s)
   │
   ├─ 5. 降级 & 回源：
   │       · 主 API 失败 → 备用数据源（如 FMP 失败 → fallback 到 Yahoo）
   │       · 仍失败 → 最近 3 次缓存（stale-while-revalidate）
   │       · 仍失败 → default_value（标注"数据可能过时"）
   │
   └─ 6. 后置：审计 + 指标 + 缓存写入（Redis/本地文件，TTL 根据端点）
```

**(3) FunctionAdapter → 本地 Python 函数（同步/异步）**

```
模块调用 FunctionAdapter.execute(func_path, args, kwargs)
   │
   ├─ 1. 惰性加载（解决命名冲突）：
   │       路径如 "dreamos.core.sense.IntentEngine.recognize"
   │       → 用 importlib.import_module 按需 import（避免模块级互相 import）
   │       → 与 Python 标准库同名时，优先项目内部路径（显式前缀）
   │
   ├─ 2. 执行模式：
   │       · 函数是 async def → 事件循环中 await（asyncio.create_task）
   │       · 函数是 sync def → 线程池中运行（to_thread）
   │       · 计算密集型 → 可选进程池（GIL 绕过，但仅限纯函数 + 可序列化）
   │
   ├─ 3. 沙箱检查（针对外部输入的函数）：
   │       · 函数名黑名单：eval/exec/subprocess/os.system/__import__
   │       · 参数类型检查：禁止传 callable / generator 给不信任函数
   │       · 超时保护：threading.Timer / asyncio.wait_for
   │
   ├─ 4. 异常分类：
   │       · ValueError / KeyError / TypeError → Retryable? No → Degraded
   │       · IOError / OSError → Retryable? Yes（最多2次）→ 仍失败 Fatal
   │       · 自定义 KnownException → 按错误码分类（见 MEP §8.2）
   │
   └─ 5. 后置：审计 + 指标 + 返回 ModuleResult
```

---



---

## 九、依赖关系与部署拓扑

### 9.1 模块依赖图：5大领域 DAG + 禁止循环依赖

能力层 5 大领域（A/C/F/G/T）之间的依赖必须是有向无环图（DAG），禁止任何循环依赖。

```
允许的依赖方向（上游 → 下游，上游不得依赖下游）：

  ┌──────────────────────────────────────────────────────────┐
  │                    G 域 (通用工具)                        │
  │  日志 / 配置 / 工具函数 / 数据结构 / 加密 / 存储基类        │
  └──────────────┬──────────────────────────┬────────────────┘
                 │                          │
                 ▼                          ▼
  ┌──────────────────────────┐   ┌───────────────────────────┐
  │  T 域 (系统支撑)          │   │  C 域 (经典量化)          │
  │  监控 / 风控 / 调度 /     │   │  指标 / 策略 / 回测引擎    │
  │  状态管理 / 健康检查      │   │  纯计算，零外部依赖        │
  └──────┬───────────────────┘   └─────────┬─────────────────┘
         │                                  │
         └───────────────┬──────────────────┘
                         ▼
              ┌──────────────────────┐
              │  F 域 (基本面能力)    │
              │  新闻/资金流/链上/宏观 │
              │  可依赖 C 域做数值计算│
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │  A 域 (AI 交易能力)   │
              │  A0-A9 系列节点       │
              │  最下游，可依赖全部上游│
              └──────────────────────┘
```

**禁止的依赖关系（Anti-Dependencies）**：
| ❌ 禁止 | 说明 |
|--------|------|
| G 域 → A/C/F/T 域 | 通用工具层不得反向依赖业务层 |
| C 域 → A 域 | 经典量化不应该知道 AI 交易节点的存在 |
| C 域 → F 域 | 指标计算不应该调用新闻/资金流 API |
| T 域 → A 域 | 风控/监控是系统支撑，不得反向被业务节点依赖 |
| 任何域 → A 域 → 任何上游域 | 禁止形成循环：如 A→T→A |

**检测机制**：每次 `ModuleRegistry.load()` 完成后，运行 `detect_cycles()` 做拓扑排序检测，如发现环 → 启动失败，错误码 105。

### 9.2 目录结构全景（根目录 → 0-16号系统 → 核心代码目录）

```
dreambuddy-v2/
├── 0-系统文档管理/              ← 文档导航+规范（视角B：以1-ARCHITECTURE为主入口）
│   ├── 1-规范体系/             （DOC_STANDARD / 模板 / 分类）
│   ├── 2-文档地图/             （SYSTEM_MAP / TOPIC_MAP / ARCHITECTURE_MAP）
│   ├── 3-文档治理/             （DOC_DEBT / 生命周期 / 质量审计 / RELEASE_NOTES）
│   └── 4-工具与自动化/
│
├── 1-ARCHITECTURE/             ← ★ 架构主入口（视角B）
│   ├── SYSTEM_ARCHITECTURE_OVERVIEW.md   ← ★ 本文档 v3.0（唯一事实源 SSoT）
│   ├── WORKBUDDY_OS_MODULAR_ARCHITECTURE.md   （旧版，参考保留，后续归档）
│   ├── TRADING_MODULES_OVERVIEW.md      （A/C/F链模块细节）
│   ├── THREE_CHAIN_DISPATCH_CHECKLIST.md（三链调度清单）
│   ├── SUPERPOWERS_INTEGRATION_UPGRADE.md（超能力集成）
│   ├── DEBT_INDEX.md                    ★ 技术债全景 v2.4
│   ├── dreamos/                         ★ Dreambuddy OS 内核代码（SACG四层）
│   │   ├── core/
│   │   │   ├── sense/      S层（IntentEngine/Recognizers/TokenBudget）
│   │   │   ├── arrange/    A层（GraphPlanner/NodeSelector/ChainPlanner）
│   │   │   ├── compute/    C层（GraphExecutor/Aggregator/Reflector）
│   │   │   ├── graph_store/G层（Checkpoints/Chronicle/BAC压缩/向量索引）
│   │   │   └── capability/ 横切（Registry/Evolution/Budget/Adapters/Errors）
│   │   └── shared/         （llm_client / utils / types）
│   ├── modules/             （35+ 模块 YAML 配置）
│   └── nodes/               （A0-A9 + C1 + F1-F3 本地实现 11+）
│
├── 2-KNOWLEDGE/              知识库（语义记忆：交易/技术/理论/运营/方法论）
├── 2-GOVERNANCE/             治理宪章（GOVERNANCE_CHARTER + 合规规则 + 审计日志）
├── 3-EVOLUTION/              进化引擎（TS版实验性实现，后续迁移 Python）
│
├── 4-MEMORY/                 ★ 记忆系统（L1/L2总记忆 + 9-工具与接口）
│   ├── 0-元记忆/             （记忆架构/类型/质量/生命周期/元模板映射）
│   ├── 0-工作记忆/           L0（WorkingMemoryManager + checkpoints）
│   ├── 1-原则记忆/           L2（ENGINEERING_PRINCIPLES 等）
│   ├── 2-方法论记忆/         L2（A1 / A8 / 矛盾论 方法论）
│   ├── 3-架构记忆/           L2（ADR / 当前架构 / 架构历史）
│   ├── 5-通用经验/           L2（技术/流程/最佳实践/反模式）
│   ├── 1-开发记忆单元 MU-DEV/L2（情景/程序/语义/SolutionPaths）
│   ├── 2-交易记忆单元 MU-TRD/L2（交易核心经验 + 贝叶斯JSON）
│   ├── 3-文档记忆单元 MU-DOC/L2
│   ├── 4-信息记忆单元 MU-INF/L2
│   ├── 6-应用记忆索引/       （Registry + RoutingTable + HealthStatus）
│   ├── 9-工具与接口/         ★（daemon/hook/session/MCP/贝叶斯更新器等）
│   └── versions/             ★ MemOS（commits.json + snapshots/<commit_id>/）
│
├── 5-WATCHLIST/              标的观察清单与评级
├── 5-BUSINESS/               业务管理（HR/运营/成本，六部门运营）
├── 6-RESEARCH/               研究中台（策略库/因子库/研报归档）
│
├── 6-TRADING/                ★ 交易中台主目录
│   ├── scripts/              （dream_trade_exec.py, trading_utils.py 等）
│   ├── config/               （.env, config.json, dedup_state）
│   └── data/                 （artifacts/ / signal_pool/ / logs/）
│
├── 7-USER-CENTER/            用户中心
├── 8-CUSTOMER/               客户中心
├── 8-FEISHU/                 ★ 飞书协作系统（人机交互外部信息层）
│   ├── approval/             （Gate-C/A9 审批规则 + AI代决）
│   ├── bitable/              （交易记录多维表格字段定义）
│   ├── wiki/                 （知识库节点注册表）
│   └── workflows/            （agent协作工作流配置）
├── 9-DATA-PLATFORM/          数据中台（行情/因子/标签/特征存储）
│
├── 10-CTA/                   CTA 策略子系统
├── 11-易经推理系统/           ★ AI交易核心（易经框架 + L4记忆 + polling_trader）
│   ├── scripts/memory_l4/    （L4 应用记忆 + 交易 utils + A0 矛盾引擎）
│   └── data/                 （K线/状态/信号/回测数据集）
├── 12-马丁策略/              ★ V15 经典马丁（v15_api_server + 风控）
├── 13-产品与运营/            产品运营平台
├── 14-V15经典马丁策略/       V15 数据目录（运行时产物）
├── 15-监控告警系统/          全系统监控+告警
├── 16-GATEWAY/               API 网关 + 外部服务接入
├── 17-v4-wave-strategy/      ★ V4波浪策略系统（V4减半+艾略特波浪互斥融合）
│   ├── v4_wave_engine.py     （主引擎：V4定方向→波浪择时加仓→物理置信度调节）
│   ├── ewave_strategy_adapter.py （波浪策略适配器 + 互斥融合规则）
│   ├── ewave_recognizer.py   （艾略特波浪识别器）
│   ├── halving_top_exit_strategy.py （减半顶部离场策略）
│   ├── backtest_v4_wave.py   （9年回测验证）
│   ├── live/v4_wave_trader.py （实盘交易器）
│   └── data/                 （BTC日线数据 + 行情获取）
│
├── AGENT协作工具/            多Agent开发协作辅助（非主线，后期明确接口）
│   ├── SKILLS/agent-collab-supervisor/ （监督SKILL：任务卡/评审/测试/分支合规）
│   └── github-actions/       （Agent生命周期检查 + 载荷构建）
├── deploy/                   ★ 部署配置体系（Hermes 网关 + 云服务器部署）
│   ├── deploy.sh             ★ 一键部署入口（3阶段：依赖→代码→服务）
│   ├── 01-install-deps.sh    （Node.js / Python / lark-cli 安装）
│   ├── 02-clone-and-config.sh（代码拉取 + 配置注入）
│   ├── 03-systemd-services.sh（systemd 服务注册：gateway/poller/dashboard）
│   ├── 04-hermes-config.sh   （Hermes 配置初始化）
│   ├── hermes/               ★ Hermes 预部署配置包
│   │   ├── config.yaml       （模型/Provider/飞书群组规则/Cron）
│   │   ├── skills/           （13个预部署SKILL：screen1/2/3-trigger, a6-monitor, process-d, approval-timeout, gatec, screen1-framework 等）
│   │   ├── cron/jobs.json    （Cron 定时任务注册表）
│   │   └── memories/         （Hermes 记忆 + 用户画像）
│   ├── group_poller.py       （飞书群消息轮询器）
│   ├── *.service             （3个 systemd 服务文件：hermes-gateway / group-poller / hermes-dashboard）
│   └── INDEX.md
├── dream-ai-platform/        ★ 前端（React + TS + Vite）
├── experiments/              AB交易实验（待规范化）
│
├── .env / .env.local         （环境变量，ENCRYPTION_KEY 全局唯一约束）
├── DEBT_INDEX.md             （根目录快捷链接，与 1-ARCHITECTURE/ 内一致）
└── README.md
```

**视角 B 的文档索引关系**：
- `0-系统文档管理/` 负责**导航+规范**：告诉你"有哪些文档、到哪里找、文档怎么写"
- `1-ARCHITECTURE/` 负责**架构事实**：所有架构设计、OS内核代码、模块配置的 SSoT
- 因此：**架构设计/OS内核/模块变更 → 修改 1-ARCHITECTURE/ 下文档；文档规范/文档地图/文档治理 → 修改 0-系统文档管理/ 下文档**

### 9.3 部署拓扑：进程/服务/端口清单

| 进程名 | 入口文件 | 端口 | 职责 | 依赖 | 启动优先级 |
|--------|---------|------|------|------|-----------|
| **ml_trade_service** | `11-易经推理系统/scripts/ml_service.py` | **8092** | AI 推理服务（易经推理HTTP API） | OKX API / LLM API | P1（核心交易服务） |
| **yijing_polling** | `11-易经推理系统/scripts/polling_trader.py` | 无（定时轮询） | 轮询式 AI 交易执行器（定时→推理→下单） | ml_trade_service:8092 / OKX / 4h dedup | P1（启动后持续运行） |
| **v15_api_server** | `12-马丁策略/scripts/v15_api_server.py` | 8093（示例） | V15 马丁策略 API 服务 | OKX API / 风控状态 | P1 |
| **dreamos_api** | 规划中 | 8090 | Dreambuddy OS 内核对外 HTTP API | dreamos/ core 四层 | P2（Phase2 核心系统治理） |
| **cognitive_daemon** | `4-MEMORY/9-工具与接口/cognitive_daemon.py` | 无（mtime 轮询） | 认知守护进程（文件变更→认知闭环） | Git / 4-MEMORY 系统 | P1（开发环境启动） |
| **cognitive_mcp_server** | `4-MEMORY/9-工具与接口/cognitive_mcp_server.py` | 无（stdio） | MCP Server（供 IDE 宿主层调用） | 认知会话/记忆/模板 | P1（IDE 自动拉起） |
| **前端 dev server** | `dream-ai-platform/` | 5173（Vite 开发） | 前端 UI 开发模式 | dreamos_api / ml_trade_service | P3（开发环境） |
| **distill_scheduler** | `4-MEMORY/9-工具与接口/distill_scheduler.py` | 无（cron: 每日03:00） | 记忆蒸馏调度（L1→L2） | 4-MEMORY L1/L2 + 贝叶斯更新器 | P2（非高峰时段） |
| **monitor_agent** | `15-监控告警系统/` | 9090（Prometheus示例） | 全系统指标采集+告警 | 全部服务健康端点 | P1 |
| **hermes-gateway** | `deploy/hermes/` → systemd | 无（WebSocket） | Hermes 网关：飞书 WebSocket 接收群消息→执行 SKILL→推送研报 | 飞书 API / 6-TRADING scripts / lark-cli | P1（云服务器部署后） |
| **hermes-dashboard** | `deploy/hermes-dashboard.service` | 9119 | Hermes 仪表盘：部署状态+SKILL运行+Cron监控 | hermes-gateway | P2 |
| **group-poller** | `deploy/group_poller.py` → systemd | 无（轮询） | 飞书群消息轮询器（Hermes WebSocket 补充） | 飞书 API | P2 |
| **bridge_api** | `6-TRADING/bridge/run_server.py` | 3847 | 6-TRADING Bridge API 服务（9模块端点：交易/行情/SKILL路由/意图路由/监控） | OKX API / LLM / 6-TRADING scripts | P1 |

**典型启动顺序**：
```
1. 加载 .env（ENCRYPTION_KEY 校验一致性）
2. 启动 monitor_agent（最先启动，监控后续服务）
3. 启动 ml_trade_service + v15_api_server
4. 启动 bridge_api（6-TRADING Bridge，端口3847）
5. 启动 cognitive_daemon + cognitive_mcp_server 注册
6. 启动 yijing_polling（等待上游健康检查通过）
7. 启动 hermes-gateway + group-poller（云服务器部署后，飞书消息→SKILL执行）
8. 启动前端（可选，生产用 build 产物由 Nginx 提供）
9. 启动 hermes-dashboard（可选，端口9119，监控 Hermes 运行状态）
```

### 9.4 配置文件体系与环境变量管理

**.env 文件优先级**（从高到低，高优先级覆盖低优先级同名字段）：
```
1. 同目录 .env.local    （仅本地开发，不提交 Git，最高优先级）
2. 同目录 .env          （各子系统专属，如 6-TRADING/scripts/.env）
3. 项目根目录 .env      （全局默认，ENCRYPTION_KEY 全局唯一约束在这里定义）
4. 系统环境变量         （export/launchctl/k8s secret，生产环境使用）
5. 代码默认值           （os.environ.get("XXX", "default_value")，兜底）
```

**ENCRYPTION_KEY 全局唯一约束（D085 已修复）**：
- 唯一真实来源：`项目根目录/.env.local` 的 `ENCRYPTION_KEY`
- 所有其他 `.env` 文件（根目录/各子系统/前端）必须同步引用同一个值
- 启动时 `_load_env()` 会检测：若多个 `.env` 中定义了不同的 `ENCRYPTION_KEY` → **启动失败，退出码 2**
- LLM 凭证加解密必须使用同一密钥，否则会出现 `decrypt failed` 导致功能静默失效

**各子系统配置加载顺序（示例：6-TRADING/scripts/dream_trade_exec.py）**：
```python
# Step 1: 加载同目录 .env（子系统专属配置，如 OKX 密钥）
_load_env(local_dir=".")
# Step 2: 加载项目根目录 .env（全局默认 + ENCRYPTION_KEY 继承）
_load_env(local_dir=PROJECT_ROOT)
# Step 3: 加载 config.json（动态配置：阈值/仓位/标的池/置信度）
config = load_json_config("6-TRADING/config/config.json")
# Step 4: 与记忆系统 L2 配置冲突 → 以 config.json 为准（交易决策用最新参数）
```

### 9.5 持久化存储映射

| 存储类型 | 技术方案 | 典型目录/文件 | 所有者（负责读写的模块） | 备份策略 |
|---------|---------|-------------|----------------------|---------|
| **SQLite 向量库** | SQLite + sqlite-vss 扩展 | `4-MEMORY/.../vector_index.sqlite` / `dreamos/core/graph_store/vector.db` | 记忆系统 / G 层向量索引 | 每日 dump 到 `archive/` |
| **JSON 状态文件** | 纯 JSON + fcntl 文件锁 | `trading_utils.py state_file: .risk_state.json` / `dedup: .4h_dedup.json` | RiskManager / dedup 去重模块 / polling state | git 跟踪 + 每小时备份 |
| **G 层检查点** | JSON（每步快照） | `4-MEMORY/0-工作记忆/checkpoints/*.json` / `dream-os/graph_store/checkpoints/` | GraphExecutor + G 层 | TTL 30 天自动清理 |
| **G 层 Chronicle** | NDJSON 追加写 | `dreamos/core/graph_store/chronicle/<date>.ndjson` | C 层 Aggregator | TTL 90 天，超期归档 |
| **Artifact 产物** | JSON / CSV / Parquet / PNG | `6-TRADING/data/artifacts/` / `11-易经推理系统/data/artifacts/` | 各策略执行脚本 / 回测引擎 / 报告生成 | 重要产物入 git，普通产物 TTL |
| **记忆文件** | Markdown + bayesian_memories.json | `4-MEMORY/` 下 1-4 记忆单元子目录 | 贝叶斯更新器 / distill_scheduler | ★ MemOS 版本控制（每变更自动 commit） |
| **审计日志** | 加密 NDJSON | `AUDIT_LOGS/` 目录（加密 + 不可篡改） | A7/A8 门禁 / 认知系统 / 风控系统 | WORM 存储（Write Once Read Many） |
| **运行时产物（噪音）** | 大量小文件 | `graph_store/` / `checkpoints/` / `scheduler_data/` / `logs/` | 运行时生成，无业务价值 | 不备份，daemon EXCLUDE_DIRS 已排除 |

---

## 十、硬约束与设计原则

### 10.1 Dreambuddy OS 内核硬约束清单（来自 project_memory.md，违反即 bug）

| # | 硬约束 | 说明 | 验证方式 |
|---|--------|------|---------|
| H-01 | **A 层必须动态选节点** | A 层 GraphPlanner 只能通过 `NodeRegistry.get()` + `NodeSelector.select()` 获取节点，**不得硬编码 A1/A2/... 的 import 路径** | 静态扫描 A 层 arrange/ 代码，禁止出现 `from ...nodes.a1 import` |
| H-02 | **S 链 ≠ A 层节点** | S 链（S1-S5）是编排 A 层的**思维框架**，不得在 A 层实现中出现 S1()/S2() 等"映射函数"。S 链只存在于 NodeSelector 选择节点时的策略代码里 | 单元测试：A 层无 S1-S5 命名的类/函数 |
| H-03 | **A0 矛盾引擎必须代码驱动** | A0 的 7 维市场矛盾计算（多空/时间/信息/流动性/情绪/周期/结构）**必须是纯 Python 计算**，不得调用 LLM。仅矛盾解释和行动建议可使用 LLM | A0 单测：给 mock 数据 → 7 维分数可复现，误差 < 1e-6 |
| H-04 | **意图澄清阈值 35%** | IntentEngine 识别置信度 < `clarify_threshold=0.35` → **必须**返回 `clarify_needed=True` + 澄清问题，不得静默降级继续执行 | 集成测试：构造置信度 0.30 的输入 → 期望 clarify_needed |
| H-05 | **LLM 密钥一致性** | 所有 `.env` + DB 中加密存储的 LLM API Key 必须使用**同一个** `ENCRYPTION_KEY` 加解密 | 启动自检：多环境 decrypt 同一条凭证 → 明文一致 |
| H-06 | **任务状态更新防并发槽耗尽** | ExecutionPlanner 执行成功后必须在同一事务中：① 将任务状态标记为 `completed` ② 写入 result 文件。二者缺一不可，否则并发槽会一直被"运行中"占满 | 并发压测：N 个任务 → 最终 running=0，槽释放率 100% |
| H-07 | **记忆系统 7 标准接口 + 2 便利方法** | 所有应用记忆系统（AM-TRD/AM-DEV/...）**必须实现**：`search / add / update / get / stats / distill_candidates / healthcheck` + 便利方法 `search_similar_cases / run_distill_from_review`。缺失任何一个 → 不能注册到 AM Registry | 注册时 `assert hasattr(am, 'search')` 共 9 项 |
| H-08 | **记忆质量 5 级门槛双条件** | S/A/B/C/D 每级升级必须同时满足「置信度门槛」**和**「独立验证次数」**两个条件**（见 §6.5 表）。达标但未通过人工复核 → 停在当前级 | 质量升级单测：conf=0.9、验证=2次 → 仍为 B，不升到 A |
| H-09 | **记忆被动更新 4 机制** | 应用记忆 ↔ 总记忆之间不得有主动推送。只能通过 4 种被动机制同步：①心跳上报（healthcheck）②蒸馏候选上报③索引同步（结构变更时）④按需拉取（总记忆查询时） | 代码审计：禁止有 ApplicationMemory.push_to_global() |
| H-10 | **应用记忆适配器模式** | 对接已有子系统（如 L4 交易记忆）时，必须用 Adapter Pattern 封装**现有接口**，不得侵入式修改子系统原有代码 | 架构评审：AM-TRD-001 接入时 trading_utils.py 没有 import 记忆系统代码 |
| H-11 | **蒸馏 4 阶段路径严格顺序** | 蒸馏必须按 具体案例→一般经验→方法论→原则 的顺序逐阶段上升，不得跨级（比如跳过方法论直接从经验升原则） | distill_scheduler 集成测试：输入 3 条 case → 产出一般经验，**不产出**原则 |

### 10.2 记忆系统架构硬约束

| # | 硬约束 | 说明 |
|---|--------|------|
| M-01 | **两层架构（Global + Application，薄核肥边）** | **L2 总记忆（Global Memory）** 只做两件事：①索引+全局管理（6 应用记忆索引：Registry/RoutingTable/HealthStatus）②全局内容（原则/方法论/通用经验/架构）。**不得**存储任何子系统的具体案例细节。**L1 应用记忆（Application Memory）** 负责所有子系统特定的场景化内容 |
| M-02 | **总记忆 ↔ 应用记忆之间 5 种同步机制（仅此 5 种，见 H-09）** | ①蒸馏聚合（L1→L2，质量达标后）②心跳上报（AM→Global，healthcheck）③蒸馏候选上报（AM→Global，主动提交）④索引同步（AM 结构变更→Global Registry 更新）⑤按需拉取（Global 查询时→读取对应 AM） |
| M-03 | **AM 粒度：按子系统/业务域划分，不按代码模块** | 粒度：交易（AM-TRD）/ 风控（AM-RSK）/ 运维（AM-OPS）/ 实验（AM-EXP）/ 开发（AM-DEV）/ ...。不是按 dreamos / 11-易经推理 / 12-马丁 这样的代码目录划 |
| M-04 | **AM 仅在子系统被调用时更新** | 应用记忆是「被动唤醒」：没跑交易 → AM-TRD 不更新；没写代码 → AM-DEV 不更新。不得有定时任务轮询子系统主动采集 |
| M-05 | **总记忆只有索引查询能力** | Global Memory 对 AM 的所有查询都通过「索引→路由→按需拉取 AM→聚合结果」。总记忆内部没有任何 AM 的实际数据副本 |

### 10.3 版本控制硬约束（MemOS）

| # | 硬约束 | 说明 |
|---|--------|------|
| V-01 | **9 个 Tier0/Tier1 文件必须追踪** | MemOS 必须追踪以下 9 个核心文件的每次变更：`CORE.md` + `1-原则记忆/*.md`（1个） + `2-方法论记忆/*.md`（3个：A1/A8/矛盾） + `5-通用经验/*.md`（4个：技术/流程/最佳/反模式） = 1+1+3+4= 9 个 |
| V-02 | **commit 必须 hash 去重 + 无变更跳过** | 调用 `MemOS.commit(msg)` 时：对追踪文件计算 hash，对比上次 commit 的 hash → 全部没变 → **直接跳过**，不创建空 commit |
| V-03 | **rollback 默认创建备份 commit，--no-backup 才能跳过** | `MemOS.rollback(target_commit)` 默认流程：①先对当前状态创建一次 commit（backup_<timestamp>）②再 rollback 到 target。只有加 `--no-backup` 才跳过第①步 |
| V-04 | **存储结构固定** | 版本链索引：`4-MEMORY/versions/commits.json`（数组，每次 push_back）；文件快照：`4-MEMORY/versions/snapshots/<commit_id>/<9个追踪文件>` |
| V-05 | **双入口一致** | 集成入口（`cognitive_loop_entry.py vc <subcmd>`）和独立入口（`memory_version_control.py`）**必须**调用同一个 `MemOS` 类，行为完全一致 |

### 10.4 代码与文档一致性要求

| 要求 | 说明 | 不满足的后果 |
|------|------|-------------|
| **文档↔代码同 PR** | 任何影响架构/接口/配置/算法行为的代码变更 PR **必须**附带：①本 v3.0 文档相关章节更新 ②`DEBT_INDEX.md` 状态更新（若涉及） | CI 门禁检查：PR diff 内有 .py 但无对应 .md 更新 → 标记 `needs-doc-update`，阻塞合并 |
| **A8 知行合一校验** | 每次交易/开发闭环结束后，A8 引擎计算 `gap_score = |预期行为 - 实际行为|`。gap_score 同时包含：文档描述 vs 代码行为的一致性偏差 | gap_score > 0.5 → 强制登记一条 DOC 类债务到 DOC_DEBT_INDEX.md |
| **文档债登记机制** | 文档变更与代码变更无法在同一 PR 完成时（如文档量大需后续补充），发起人**必须**登记一条 DOC 类债务：包含「文档缺失点 / 责任人 / 截止日期」 | 超期未关闭 → 认知系统 daemon 提醒 + 责任人看板高亮 |
| **v3.0 文档 = 唯一事实源** | 关于系统架构的任何争议/讨论/决策，最终以本 `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md v3.0` 为准，其他分散文档仅作参考或历史归档 | 冲突处理：以 v3.0 为准，旧版文档陆续标注「归档」链接到本文件 |

### 10.5 架构设计禁止事项（Anti-patterns，严禁新增）

| 禁止事项 | 说明 | 若已存在的债务编号 |
|---------|------|-----------------|
| ❌ **A 层硬编码业务节点** | arrange/ 目录中出现 `from nodes.a1_research import A1ResearchNode` 这样直接 import 具体业务节点 | （架构债，已登记） |
| ❌ **OS 内核直接访问外部服务** | S/A/C/G 任何一层直接调用 httpx.get/post/websockets 访问 OKX/万得/新闻 API。必须通过 APIAdapter → ServiceRegistry 路由 | （安全债，已登记 P0） |
| ❌ **绕过 Registry 调用节点** | 业务代码直接 new A1Node().execute()，跳过 NodeRegistry 权限/状态/版本检查。必须走 `UnifiedNodeExecutor.run(module_id=...)` | （架构债，已登记 P1） |
| ❌ **前端包含交易/风控逻辑** | 前端 .tsx/.vue 中出现 stop_loss_pct、position_size、confidence_threshold 等交易决策参数计算。这些只能在后端算好返回 | （待新增到 DEBT_INDEX，如有） |
| ❌ **新模块无 Module API 契约** | 能力层新增模块但没有 ModuleInput/ModuleOutput 数据类，仍用裸 dict 传参 | （代码质量债，P1，已登记若干） |
| ❌ **新 AM 不实现 7+2 接口** | 新增应用记忆但缺失 7 标准接口 + 2 便利方法（见 H-07） | （架构债，P1） |
| ❌ **pickle/eval/exec 反序列化用户输入** | 对任何来自外部文件/网络的内容使用 pickle.load / eval / exec。涉及反序列化 D060/D061（P0 级安全债） | D060/D061（P0，批次2待修） |
| ❌ **subprocess 调用无沙箱无白名单** | subprocess.run 没有 command 白名单 + 超时 + cwd 限制。涉及沙箱绕过 D059/D064（P0 级安全债） | D059/D064（P0，批次2待修） |

### 10.6 设计原则重申（§1.4 + 新增架构演进原则）

| # | 设计原则 | 说明（一句话版本） |
|---|---------|-------------------|
| P01 | **分层解耦** | S/A/C/G + 能力层 + 应用层 三层，每层只依赖自己的下游 |
| P02 | **接口契约优先** | 先定义 ModuleInput/ModuleOutput 数据类，再写实现 |
| P03 | **动态编排，拒绝硬编码** | A 层永远是 Registry + Selector，没有写死的节点 ID 列表 |
| P04 | **本地零 Token 优先** | 规则识别 + 本地计算能解决的，绝不花 Token 调 LLM |
| P05 | **错误必分类，失败必降级** | 6 大类 ErrorCode + max_retry + fallback + default_value |
| P06 | **闭环自进化** | 交易/开发两个闭环都要有「执行→记录→校验→进化」的完整螺旋 |
| P07 | **记忆是第一公民** | 任何有价值的经验必须流入 4-MEMORY，经验只放在 PR/issue=债务 |
| P08 | **文档即代码，代码即文档** | v3.0 SSoT + 同 PR 约束 + A8 gap_score 校验一致性 |
| P09 | **安全默认拒绝** | 外部 API、反序列化、subprocess、密钥存储均采用默认拒绝白名单模式 |
| P10 | **薄核肥边，去中心化** | Global Memory/OS内核只做调度和索引，真实计算和数据放在模块和AM里 |
| **新增** P11 | **架构演进不做「大爆炸重写」** | 任何架构升级（如 SACG 新增一层）优先做增量扩展 + Adapter 兼容，禁止一次性重写全部旧代码 |
| **新增** P12 | **可观测性优先于性能优化** | 先加 tracing/metrics/logs 把系统「看见」，再谈优化。在可观测性之前做的优化都是猜 |
| **新增** P13 | **命名冲突靠显式前缀，不靠 import 技巧** | Python 标准库重名（如 memory/collections 等）一律用 `from dreamos.memory import ...` 的显式前缀，避免 sys.path hack |

---

## 十一、实现进度与技术债全景图

### 11.1 各架构层实现状态矩阵（🟢已实现 / 🟡部分实现 / 🔴规划中）

| 架构层 | 子模块 | 状态 | 代码位置（或参考文档） | 备注 |
|--------|-------|------|---------------------|------|
| **应用层** | 6大交易子系统（11-易经 / 6-TRADING / 12-马丁 / 10-CTA / 9-数据 / 13-产品） | 🟡 60% | §4.2 各子系统目录 | 易经/马丁核心可运行；CTA和中台骨架 |
| | CLI 工具（polling_trader / cognitive_loop_entry / dream_trade_exec） | 🟢 | 对应子系统 scripts/ | 已有完整入口 |
| | 前端 dream-ai-platform | 🟡 40% | `dream-ai-platform/` | 页面骨架，待接真实后端 API |
| | HTTP API（ml_trade_service:8092） | 🟢 | 11-易经推理系统/scripts | 已通过交易流程验证 |
| | dreamos_api（OS内核对外 HTTP） | 🔴 | dreamos/api 规划中 | Phase2 核心系统治理交付 |
| **能力层** | 5大领域分类（A/C/F/G/T） | 🟢 文档完备 | §3.1 + modules/*.yaml | 分类体系完整 |
| | 35+ 模块配置 | 🟡 25个已填，10个占位 | 1-ARCHITECTURE/modules/ | 10个高阶模块待补详情 |
| | 11+ 本地节点实现（A0-A9/C1/F1-F3） | 🟡 A0/A1/A2/A3/A5/A7/A8/A9/C1 核心已实现 | 1-ARCHITECTURE/nodes/ + 各子系统 scripts | A4/A6/F 系列待完整接入 |
| | 统一 Module API 契约 | 🟡 类型定义已完成，实现待对齐 | dreamos/shared/types.py | 旧代码仍有 dict 传参（债务 CODE 类） |
| | 三适配器框架（Skill/API/Function） | 🟢 实现完整 | §3.3 + dreamos/core/capability/adapters.py | 适配器路由 + 重试 + 降级均验证通过 |
| | NodeRegistry + ModuleRegistry | 🟢 | capability/registry.py | 动态查找 + 元数据 + 版本路由 |
| **OS内核 S层** | IntentEngine（Rule/LLM/Dynamic + TokenBudget） | 🟢 | dreamos/core/sense/ | 阈值 0.55/0.35 + 双模式识别已单测 |
| **OS内核 A层** | GraphPlanner + NodeSelector | 🟡 规划已完成，代码实现待对齐 | dreamos/core/arrange/ | 旧版用 ChainRouter，迁移到 GraphPlanner（债务） |
| | ChainPlanner 四维过滤 | 🔴 设计已定 | §7.5 | Phase2 交付 |
| **OS内核 C层** | GraphExecutor + Aggregator + Reflector | 🟡 基本执行器可用 | dreamos/core/compute/ | Reflector 环路检测待补 |
| **OS内核 G层** | 检查点 + Chronicle + BAC 压缩 + 向量索引 | 🟢 Checkpoint/Chronicle 可用；BAC TS参考 + 向量SQLite | dreamos/core/graph_store/ + 4-MEMORY/0-工作记忆 | G层代码迁移中（参考TS版） |
| **OS内核横切** | Evolution 引擎 | 🔴 实验中（TS版） | 3-EVOLUTION/ | Python版规划中，和认知系统对称 |
| | 错误码体系（6大类） | 🟢 | capability/errors.py | 1xx-6xx 覆盖全部场景 |
| **认知系统** | daemon + git hook + 会话管理器 + 跨进程恢复 | 🟢 已验证（18个单元测试） | 4-MEMORY/9-工具与接口/cognitive_*.py | 见近期 topics：跨进程恢复/fallback机制均通过 |
| | 双层模板系统（6元模板 + APP-*.json） | 🟢 模板机制可运行 | 4-MEMORY/0-元记忆/template_mappings.json | 1/√N 反馈公式已实现 |
| | 认知 MCP Server（10+ 工具） | 🟢 | cognitive_mcp_server.py | create_session/recall/record/on_commit... 可用 |
| **记忆系统** | L0 工作记忆（WorkingMemoryManager） | 🟢 | 4-MEMORY/9-工具与接口/working_memory_manager.py | context_block + scratch_block + Token预算 |
| | L1 应用记忆（AM-TRD/DEV/...） | 🟡 AM-TRD/DEV 已建，其余 AM 待登记到索引 | 6-应用记忆索引/REGISTRY.md | 7+2 接口待对齐 |
| | L2 总记忆（4个 MU-xxx） | 🟢 | 1-开发/2-交易/3-文档/4-信息 记忆单元目录 | 目录+骨架齐备，内容持续蒸馏填充 |
| | 贝叶斯记忆进化 v2（Beta-Binomial + 指数遗忘） | 🟢 | bayesian_memory_updater.py + test_rigorous_bayesian.py | 数学公式已实现 + 严格测试 |
| | 质量分级（S/A/B/C/D 五门槛） | 🟢 分级标准已在文档，代码待集成到 distill_scheduler | §6.5 表 + MEMORY_QUALITY.md | 质量升级需通过双条件检查 |
| | MemOS 版本控制（9文件追踪 + commit/rollback） | 🟢 | memory_version_control.py | commits.json + snapshots 已产出多条 |
| **治理体系** | 六部门模型 + 双中台 + 双交易工作流 | 🟡 文档完备，代码实现待落地 | §7.1-7.3 + DEPARTMENT_MATRIX.md | 董事会投票机制在 A8 层部分可运行 |
| | 四层合规体系（宪法/规则/门禁/审计） | 🟢 L1宪章 + L2规则 + L3RiskManager门禁 已可用 | §7.4 + 2-GOVERNANCE/ | L4 审计日志模块待补（DOC→P1） |
| **双闭环** | 交易决策闭环（执行/情报/治理三环） | 🟡 A0-A9核心 + A6情报监控 + A8 gap_score 已跑通 | §5.4 | 做梦部和Evolution深度联动待Phase2 |
| | 开发认知闭环（7步流程） | 🟢 | §6.3 daemon+hook+会话+on_commit完整链路 | 见 topics：端到端验证已通过 |

**整体完成度评估**：架构文档（v3.0 本文档）🟢 100%；OS内核代码 🟡 约 55%（S/A层领先，G层参考TS待迁）；认知+记忆系统 🟢 75%；交易子系统 🟡 60%；治理体系 🟡 30%。

### 11.2 DEBT_INDEX v2.4 全景（103 项债务 × 8 大分类 × 4 优先级）

数据来源：`1-ARCHITECTURE/DEBT_INDEX.md v2.4` + 根目录快捷链接。

**按优先级分布**：
| 优先级 | 数量 | 定义 | 典型代表 |
|--------|------|------|---------|
| **P0 紧急** | 11 项 | ≥1500 分，3天内必须处理 | 明文密钥、反序列化风险、沙箱绕过、熔断失效、并发状态分叉 |
| **P1 高** | 38 项 | 500~1500 分，本迭代处理 | 架构边界模糊、模块无契约、测试缺失、循环依赖 |
| **P2 中** | 45 项 | 100~500 分，下迭代处理 | 命名不规范、函数过长、README过时、lint缺失 |
| **P3 低** | 9 项 | <100 分，有空再处理 | 注释完善、小范围代码风格统一 |
| **合计** | **103 项** | | |

**按 8 大分类分布**：
| 分类 CODE | 含义 | 数量 | TOP债务 |
|----------|------|------|---------|
| CODE | 代码质量债 | 26 项 | 函数>200行、重复代码、命名不规范 |
| ARCH | 架构设计债 | 8 项 | A层硬编码节点、分层违规、循环依赖 |
| CFG | 配置债 | 9 项 | 硬编码参数、配置分散、.env不同步 |
| ENG | 工程化债 | 6 项 | 无lint/CI/pre-commit、无统一构建脚本 |
| TEST | 测试债 | 5 项 | 单测覆盖低、只有happy path、无集成测试 |
| DOC | 文档债 | 2 项 | README过时、API无文档（详见 DOC_DEBT_INDEX.md） |
| DEP | 依赖债 | 2 项 | 多套requirements冲突、过期依赖有CVE |
| **新增 SEC** | 安全与资金安全债 | **7 项** | 明文凭据/反序列化/沙箱绕过/熔断失效/并发状态分叉等 **P0致命级** |
| **合计** | | **~65项显性 + 38项由 v2.4 深度排查新增** | |

### 11.3 技术债 × 架构层 / 子系统映射矩阵（精简版）

| 架构层 / 子系统 | P0 | P1 | P2 | P3 | 典型债务编号 |
|-----------------|----|----|----|----|-------------|
| **应用层·交易子系统** | 3 | 9 | 15 | 3 | D056(密钥) D062(风控except:pass) D081(dedup同步) |
| **应用层·前端** | 0 | 3 | 6 | 1 | 交易逻辑泄漏到前端、API对接缺失 |
| **能力层·A/C/F/G/T模块** | 1 | 8 | 10 | 2 | 无Module API契约、Adapter未覆盖全部外调 |
| **OS 内核 S/A 层** | 1 | 4 | 2 | 0 | A层 GraphPlanner 待迁移、ChainRouter 遗留 |
| **OS 内核 C/G 层** | 1 | 3 | 4 | 0 | C层 Reflector 环路、G层 BAC 压缩迁移自 TS |
| **认知系统** | 0 | 2 | 3 | 0 | 噪音过滤参数调优、元模板自动学习 |
| **记忆系统** | 1 | 4 | 3 | 0 | 记忆质量分级代码集成、AM 7+2接口全量对齐 |
| **治理与文档** | 0 | 5 | 2 | 3 | DOC_DEBT_INDEX 若干条、L4 审计日志模块 |
| **安全 / 跨层 / 基础设施** | 4 | 0 | 0 | 0 | D060/D061(反序列化) D059/D064(沙箱绕过) |
| **合计** | **11** | **38** | **45** | **9** | 103 项 |

### 11.4 P0 级 11 项致命债务重点标注（资金 + 安全）

| ID | 分类 | 标题 | 风险说明 | 修复批次 |
|----|------|------|---------|---------|
| D056 | SEC-CFG | OKX API Key 硬编码在 dream_trade_exec.py 明文 | 代码泄漏 = 资金被盗 | **✅ 批次1（已迁移到 .env，密钥不变）** |
| D062 | SEC-CODE | RiskManager._save_state except:pass 静默吞异常 | 风控状态无法持久化 = 熔断失效 = 资金无限亏损风险 | **✅ 批次1（logger.exception + _save_failed 标记 + can_trade 拒绝开仓）** |
| D081 | SEC-CFG | CLI版与执行版 dedup 状态不同步（双进程分叉） | 同信号重复下单 = 超额敞口 = 资金安全 | **✅ 批次1（状态文件统一，根因待 D051 彻底解决）** |
| D085 | SEC-CFG | 多 .env 文件中 ENCRYPTION_KEY 不一致 | LLM凭证解密失败 = 交易推理静默失效 | **✅ 批次1（统一为 .env.local 值 + 启动自检）** |
| D059 | SEC-SEC | subprocess 无白名单无超时无 cwd 沙箱 | 任意命令执行 RCE 漏洞 | **⏳ 批次2 待修** |
| D060 | SEC-SEC | pickle.load 读取外部文件（反序列化 RCE） | 构造恶意 pickle 文件 → 服务器被控 | **⏳ 批次2 待修** |
| D061 | SEC-SEC | eval/exec 用户输入（代码执行注入） | 外部输入未过滤直接 eval | **⏳ 批次2 待修** |
| D064 | SEC-SEC | FunctionAdapter 沙箱黑名单不全（绕过 eval 风险） | 不信任函数仍有可调用空间 | **⏳ 批次2 待修** |
| D071 | SEC-FIN | 交易并发槽 state "running" 未清理导致无法开新仓（H-06 违反） | 交易功能 DoS = 错过交易机会 | **⏳ 批次3 待修** |
| D073 | SEC-FIN | 多子系统 RiskManager 状态分叉（易经/V15/各策略各写各的） | 全局敞口超限 = 总仓位风控形同虚设 | **⏳ 批次3 待修** |
| D078 | SEC-FIN | 单日亏损熔断阈值无全局校验（子系统各自熔断但总和不检查） | 多个子系统同时亏 = 全局亏损突破N倍 | **⏳ 批次3 待修** |

> 7 项 SEC（安全）类 P0 + 3 项 FIN（资金安全）类 P0 + 1 项 CFG（D085）= 11 项 P0。资金安全永远高于一切。

### 11.5 修复批次规划

| 批次 | 主题 | 包含债务 | 状态 | 预计工作量 |
|------|------|---------|------|-----------|
| **批次 1** | 资金安全止损（先保命） | D056 / D062 / D081 / D085 | ✅ **已完成 4 项**，状态：待验证 | 2 人日（已投入） |
| **批次 2** | 安全沙箱 + 反序列化加固 | D059 / D060 / D061 / D064（4项P0 SEC） | ⏳ **下一批次启动候选** | 3~5 人日 |
| **批次 3** | 全局风控统一（消除子系统状态分叉） | D071 / D073 / D078（3项 FIN类 P0） + 相关 P1 若干 | 🔴 规划中 | 5~8 人日 |
| **批次 4** | 架构边界对齐（A层GraphPlanner迁移 + 能力层Module API 统一） | ARCH 类 P1 8 项 + CODE 类 P1 若干 | 🔴 规划中 | 2 周 |
| **批次 5** | 工程化与测试（lint/CI + 测试覆盖率提升） | ENG 6 + TEST 5 + CODE P2 若干 | 🔴 规划中 | 2 周 |
| **批次 6** | 记忆系统 AM 7+2 接口全量落地 + 质量分级集成 | M-01/H-07/H-08 对应的 P1/P2 债务 | 🔴 规划中 | 1~2 周 |
| **批次 7** | 文档与治理闭环（DOC 债清理 + A8 文档一致性校验上线） | DOC 2 + 治理体系代码落地 | 🔴 规划中 | 1 周 |
| **批量清理** | P2/P3 散点小额债务（45+9=54项） | 按「谁欠下谁偿还」原则 + 每个开发迭代 20% 配额 | 🔴 常态化 | 每个迭代 1~2 人日 |

> 批次 1→2→3 优先级严格递减：**先保资金安全 → 再保服务器安全 → 再统一风控 → 再优化架构/工程化**。

---

## 十二、技术文档总览与演进

### 12.1 架构文档索引（视角 B：1-ARCHITECTURE 为主入口）

| 文档 | 位置 | 版本 | 定位 & 说明 |
|------|------|------|-------------|
| ★ **SYSTEM_ARCHITECTURE_OVERVIEW.md（本文档）** | `1-ARCHITECTURE/` | **v3.0** | **L0 级唯一事实源（SSoT）**。整体架构、OS内核、能力层、应用层、思维链、认知系统、治理、数据流、硬约束、技术债全景。所有架构争议以此为准 |
| WORKBUDDY_OS_MODULAR_ARCHITECTURE.md | `1-ARCHITECTURE/` | v1.1（旧版） | **历史归档参考**。定义了早期的 S/A 分层 + NodeRegistry/ModuleRegistry/UnifiedNodeExecutor。**所有决策以 v3.0 为准**；旧版仅保留作为迁移参考，后续归档到 `archive/` |
| TRADING_MODULES_OVERVIEW.md | `1-ARCHITECTURE/` | v1.0 | L2 专题：A/C/F链模块细节 + 三环架构 + 核心模块清单 |
| THREE_CHAIN_DISPATCH_CHECKLIST.md | `1-ARCHITECTURE/` | v1.0（修正版） | L2 操作手册：A0-A9 各阶段 SKILL + 核心方法论 |
| SUPERPOWERS_INTEGRATION_UPGRADE.md | `1-ARCHITECTURE/` | v1.0 | L2 专题：超能力集成 + SACG五层流程参考 |
| DEBT_INDEX.md | `1-ARCHITECTURE/` + 根目录快捷链接 | v2.4 | L0 级：技术债管理体系（103项全景 + 8分类 + 优先级评估 + 路线图） |
| DOC_DEBT_INDEX.md | `0-系统文档管理/3-文档治理/` | v1.0 | L1 级：文档债细化管理（DOC类债务） |
| （系统规范） DOC_STANDARD / DOC_CLASSIFICATION / TEMPLATES/* | `0-系统文档管理/1-规范体系/` | 最新 | L0级：文档写作规范 + 分类标准 + 5套模板 |
| （文档导航） SYSTEM_MAP / TOPIC_MAP / ARCHITECTURE_MAP | `0-系统文档管理/2-文档地图/` | 最新 | L0级：告诉你「文档有哪些、到哪里找」的导航地图 |
| INDEX.md / README.md | `0-系统文档管理/` | 最新 | 0号系统入口页 + 全局说明 |
| MEMORY_SYSTEM_ARCHITECTURE.md / MEMORY_QUALITY.md / COGNITIVE_ARCHITECTURE.md 等 | `4-MEMORY/0-元记忆/` | v3.0 | L1 级：记忆系统架构/质量分级/认知架构专题。**设计约束以 §10.1/10.2 提炼版为准，详细说明在此** |
| GOVERNANCE_CHARTER.md / COMPLIANCE_RULES.md | `2-GOVERNANCE/` | 最新 | L0级：系统根本大法 + 合规规则总表 |
| DEPARTMENT_MATRIX.md / SKILL_INDEX.md / TOOL_MAPPING.md | `1-ARCHITECTURE/` 或专题目录 | 最新 | L1专题：六部门矩阵 / Skill索引 / 工具映射 |

**v3.0 与旧 v2.3 / v1.1 的变更关系**：
- v2.3 及之前：内容分散在 WORKBUDDY_OS_MODULAR_ARCHITECTURE（TS视角）+ 多个专题 md，认知系统和记忆系统完全未纳入整体架构
- **v3.0 新增内容（相对 v2.3）**：①整体架构从两层升级到三层（应用层/能力层/OS内核）②SACG 四层 OS 内核正式定义 ③能力层粗-中-细三层模块化体系 ④三大思维链 + 三大闭环架构升级 ⑤**新增第六章：认知系统 + 记忆进化（对称闭环）** ⑥**新增第七章：六部门+双中台+双交易流+四层合规** ⑦硬约束 13 条 + 禁止事项 ⑧技术债 103 项全景 + 批次规划 ⑨术语表 + 演进路线图

### 12.2 子系统文档索引（复用 §4.2.1：6交易子系统 × 5 文档标准）

| 子系统 | 目录 | README | ARCHITECTURE | API_SPEC | CONFIG_GUIDE | CHANGELOG |
|--------|------|--------|-------------|----------|-------------|-----------|
| 易经推理AI交易系统 | `11-易经推理系统/` | ✅ | ✅ L4完整 | ✅ | ✅ | ✅ |
| 交易中台主系统 | `6-TRADING/` | ✅ | 🟡 骨架 | ✅ | ✅ | ✅ |
| V15经典马丁子系统 | `12-马丁策略/` | ✅ | ✅ 部分 | ✅ | ✅ | ✅ |
| V15 数据/运行目录 | `14-V15经典马丁策略/` | ✅ | ❌（纯数据） | ❌ | ❌ | ❌ |
| CTA 趋势跟踪子系统 | `10-CTA/` | ✅ | 🔴 规划 | 🔴 | 🔴 | 🔴 |
| 数据中台 | `9-DATA-PLATFORM/` | ⚠️ 仅README | 🔴 | 🔴 | 🔴 | 🔴 |
| 产品与运营平台 | `13-产品与运营/` | ✅ | 🔴 | 🔴 | 🔴 | 🔴 |
| （其他辅助系统） | `5-WATCHLIST/` 等 | ⚠️ 部分 | ❌ | ❌ | ❌ | ❌ |

> 文档缺口 = P1 类 5 个子系统文档债（详见 DOC_DEBT_INDEX.md），批次 7 处理。

### 12.3 专题架构文档索引

| 专题文档 | 路径 | 内容覆盖 |
|---------|------|---------|
| SKILL_INDEX（技能索引） | `1-ARCHITECTURE/SKILL_INDEX.md`（规划中） | 200+ Wind AIFin 技能 + 11-易经推理技能 + 开发认知技能，按 A/C/F/G/T 领域分类 |
| TOOL_MAPPING（工具映射） | `1-ARCHITECTURE/TOOL_MAPPING.md`（规划中） | 子系统内脚本/CLI/API/daemon 与 OS 内核能力的对应关系表 |
| DEPARTMENT_MATRIX（部门矩阵） | `5-BUSINESS/DEPARTMENT_MATRIX.md`（或 1-ARCHITECTURE 专题） | 六部门权责+KPI+对应AI能力+否决权矩阵 |
| 前端架构文档 | `dream-ai-platform/docs/FRONTEND_ARCHITECTURE.md`（规划中） | 页面路由 / 状态管理 / 后端 API 对接 / 组件库 / 构建部署 |
| 产物中台文档 | `9-DATA-PLATFORM/docs/ARTIFACT_PLATFORM.md`（规划中） | Artifact 分类 / 元数据 / TTL / 检索接口 / 权限 |
| 网关设计文档 | `16-GATEWAY/docs/GATEWAY_DESIGN.md`（规划中） | 外部接入认证 / 限流熔断 / 多账户路由 / 签名校验 / 审计 |

### 12.4 版本历史

| 版本 | 日期 | 变更要点 |
|------|------|---------|
| v1.0 | 2026-05 | 初版架构：明确 S1-S5 思维链框架 + A0-A9 节点定义 |
| v1.1 | 2026-06 | 模块化升级（WORKBUDDY_OS_MODULAR_ARCHITECTURE v1.1）：35模块配置 + NodeRegistry/ModuleRegistry/UnitifedNodeExecutor + 6大类错误码 |
| v2.0 | 2026-07-中 | 引入 4-MEMORY 记忆系统（三层架构）+ 认知系统雏形（daemon + session） |
| v2.3 | 2026-07-末 | 技术债体系升级：DEBT_INDEX v2.0→v2.4，新增 7 项 P0 安全与资金安全债，合计 103 项全景；完成批次1修复 4 项 |
| **v3.0（本文档）** | **2026-07-31** | **架构重构版**：升级为三层架构全景 + SACG 四层 OS 内核；正式纳入认知系统、记忆系统、治理体系、双闭环对称设计；提炼硬约束 13 条；统一术语表与演进路线图 |

### 12.5 架构演进路线图

```
Phase 0  概念验证（2026-05 及之前）  ✅ 完成
   └─ 单策略原型 + S1-S5 思维链 + TS 版 Evolution 实验

Phase 1  工程化骨架                    ✅ 完成（2026-06）
   ├─ 从单策略 → 六大子系统目录化
   ├─ WORKBUDDY OS v1.1：NodeRegistry + 模块配置 + 错误码
   ├─ 6-TRADING / 11-易经推理 / 12-马丁 核心交易链路跑通
   └─ 4-MEMORY 目录骨架 + MU-DEV/MU-TRD 初始内容

Phase 1+ S1 文档与记忆统一             ✅ 完成（2026-07-上旬）
   ├─ 0-系统文档管理 / DOC_STANDARD / 5套文档模板 落地
   ├─ 4-MEMORY L0/L1/L2 三层架构 + WorkingMemoryManager 可用
   └─ 认知系统 daemon + MCP Server 原型上线

Phase 2  核心系统治理（⏳ **进行中**，预计 2026-08 完成）
   ├─ ★ SYSTEM_ARCHITECTURE_OVERVIEW v3.0 完整落地（= 本文档）
   ├─ 技术债批次 1~3：11 项 P0 全部清零（资金安全 + 沙箱 + 反序列化 + 全局风控）
   ├─ Dreambuddy OS 内核：S层已OK → A层 GraphPlanner 对齐 → C层 Reflector 补齐 → G层 BAC 迁Python
   ├─ 统一风控服务（RiskManager 多子系统全局统一，解 D073/D078）
   ├─ dreamos_api:8090 对外 HTTP API 骨架
   └─ 记忆系统：AM 7+2 接口全量落地 + 质量分级代码集成

Phase 3  高级特性（🔴 规划中，预计 2026-Q3末启动）
   ├─ ML 流水线：因子挖掘 + 超参自动优化 + 在线学习闭环
   ├─ 多账户风控与资金分配引擎（支持多交易所、多子账户）
   ├─ 前端 dream-ai-platform：Dashboard / TradingDesk / MemoryStudio / CognitiveBoard 接后端 API
   ├─ EvolutionEngine Python 版：和认知系统对称，交易侧进化自动升级策略库
   ├─ 16-GATEWAY 网关：外部接入 + 多租户 + 限流熔断
   └─ 运维：Prometheus + Grafana 全链路指标 + 告警看板

Phase 4  产品化（🔴 更远期，根据市场需求启动）
   ├─ 市场化中台完整落地：用户/产品/竞品 + AB 增长实验平台
   ├─ 六部门治理代码实现：董事会投票 / 合规自动扫描 / AI 黑箱治理面板
   └─ DreamBuddy Studio：一键私有化部署包 + App Store 式策略/技能市场
```

### 12.6 术语表

| 缩写/术语 | 英文/中文全称 | 定义一句话 |
|----------|-------------|-----------|
| SACG | Sense / Arrange / Compute / GraphStore | Dreambuddy OS 内核四层：感知→编排→执行→图存储 |
| OS 内核 | Operating System Kernel | Dreambuddy 系统的 SACG 四层 + 横切服务，类比操作系统 |
| 能力层 / Capability Layer | 三大架构中间层 | 5大领域 A/C/F/G/T 35+ 模块化能力，OS内核调用的"业务库" |
| 应用层 / Application Layer | 三大架构顶层 | 6大交易子系统 + CLI/API/前端等入口，直接面向用户价值 |
| A / C / F / G / T 域 | AI交易 / 经典量化 / 基本面 / 通用工具 / 系统支撑 | 能力层 5 大领域分类，上下游依赖方向：G→T/C→F→A |
| 三链（S/C/F链） | Strategy / Classic / Fundamental Chain | 三大思维范式：主骨架(S) / 量化导向(C) / 基本面导向(F) |
| S1-S5 | Survey → Analyze → Design → Validate → Execute | S 链五阶段思维框架；仅为编排参考，不映射为 A 层硬编码节点 |
| A0-A9 | A 系列 10 个节点 | AI交易能力节点：矛盾/调研/原理/沙盘/验证/执行/监控/门禁/知行/离场 |
| 三大闭环（交易侧） | 执行环 / 情报环 / 治理环 | 🔵 A1→A9 执行；🟠 A6 5级放射监控；🟣 A8 gap_score + 做梦部 进化 |
| 双闭环对称 | 交易决策闭环 + 开发认知闭环 | 一个解决"怎么交易"，一个解决"怎么写代码"，架构理念完全对称 |
| 认知系统 | Cognitive System | daemon + git hook + 会话管理器 + MCP Server 组成的开发侧自进化引擎 |
| 4-MEMORY | 记忆系统目录 | Dreambuddy 的"海马体+大脑皮层"：0-元/0-工作/1-原则/2-方法论/1~4-MU/5-通用/6-AM索引/9-工具 |
| L0 / L1 / L2（记忆层） | Working / Application / Global Memory | **L0** 单次任务工作记忆；**L1** 子系统场景化应用记忆；**L2** 全局普适总记忆 |
| MU-xxx | Memory Unit（总记忆单元） | L2 总记忆的四大分区：MU-DEV 开发 / MU-TRD 交易 / MU-DOC 文档 / MU-INF 信息 |
| AM-xxx | Application Memory（应用记忆） | L1 应用记忆分区：AM-TRD 交易 / AM-RSK 风控 / AM-OPS 运维 / AM-EXP 实验 / AM-DEV 开发... |
| S/A/B/C/D（质量级） | 5 级记忆质量分级 | S公理(≥0.98+≥10验) / A可信(≥0.85+≥3) / B待验(≥0.6+1~2) / C假设(≥0.3) / D证伪(<0.3) |
| BAC（压缩） | Blueprint / Architecture / Chronicle | 执行图三层压缩模型：B蓝图(≤500tok) / A骨架(≤3000tok) / C编年史(完整持久化) |
| MEP | Module Execution Protocol | 模块调用统一协议：ModuleInput + ModuleResult + 置信度/错误传递规则 |
| 7+2 记忆接口 | 7标准接口 + 2便利方法 | search/add/update/get/stats/distill_candidates/healthcheck + search_similar_cases/run_distill_from_review |
| MemOS | Memory Version Control System | 记忆文件专用版本控制：9个Tier0/Tier1文件追踪 + commit/log/diff/rollback/restore |
| gap_score（A8） | Theory-Practice Gap Score | A8 知行合一度量：预期 vs 实际偏差，0~1，越小越好；>0.5 触发矛盾重启 |
| IntentEngine | S 层意图引擎核心 | 规则识别(零Token)→LLM增强→结果融合→澄清判断→IntentResult 输出 |
| GraphPlanner | A 层编排核心 | 6条链路模板 + ChainPlanner 四维过滤 + Registry 选节点 → 输出 ExecutionGraph DAG |
| SolutionPath | 认知闭环产物 | 开发任务的解决方案路径 JSON（APP-<ts>.json），蒸馏为应用认知模板 |
| 元/应用模板 | Meta / App Templates | **元模板**6个通用解题范式；**应用模板**领域特定SolutionPath。1/√N 反馈双向更新权重 |
| 薄核肥边 | Thin Core, Fat Edge | 总记忆/OS内核只做调度和索引，真实计算和数据下沉到模块和应用记忆（避免上帝模块） |
| SEC | Security / 安全分类 | DEBT_INDEX 新增分类，覆盖服务器安全+资金安全，7项 P0 中的最高优先级 |
| 8-FEISHU | 飞书协作系统 | 人机协作外部信息层：5群组+2Bot+审批(Gate-C/A9)+Bitable+Wiki+Cron，贯穿交易闭环和治理闭环 |
| 17-v4-wave-strategy | V4波浪策略系统 | V4减半周期+艾略特波浪互斥融合的BTC专用趋势策略，9年回测年化56.43%，依赖12号物理引擎 |
| AGENT协作工具 | Agent Collaboration Tools | 多Agent开发协作辅助：任务卡核验/评审/测试/分支合规监督，非主线，后期接入认知系统协议层 |
| deploy/ | 部署配置体系 | 一键部署脚本+Hermes预部署配置包+systemd服务，将6-TRADING的AI理论架构部署到云服务器 |
| Hermes | Hermes 网关 | 云端AI执行网关：通过飞书WebSocket接收群消息→执行SKILL→推送研报，是6-TRADING到8-FEISHU的部署桥梁 |
| 6-TRADING 双重定位 | Dual Role of 6-TRADING | 既是通过Hermes部署的AI交易研究系统（应用层：A0-A9流水线+Bridge API），也是通用AI理论架构的方法论载体（能力层：矛盾论/第一性原理/实践论/知行合一可跨领域应用） |

---

**文档版本**: v3.0 **(DRAFT — 12 章全文完成 + 5子系统/模块补充，待用户 review)**
**最后更新**: 2026-07-31
**下一步**: 等待用户全文 review，重点确认第5章（三链+三大闭环）第6章（认知系统/记忆）第10章（硬约束）三个核心章节。如有调整点，按反馈迭代后进入 FINAL 定稿并触发相关代码/文档债务的登记。
