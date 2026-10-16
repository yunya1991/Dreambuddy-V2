# DreamBuddy v2 系统总体架构

> **版本**: v4.0
> **更新日期**: 2026-10-16
> **文档定位**: ★ **系统架构唯一事实源（SSoT）**。所有架构设计争议、模块边界、分层口径一律以本文档为准。
> **维护说明**: 被本文档取代的旧架构文档已在顶部标注「已归档」横幅，**禁止作为实现依据**（详见第十六章「文档权威性与弃用指引」）。
> **核心理念**: 三层能力架构（L0/L1/L2）+ 认知驱动编排（新 SACG）+ 高度模块化 + OS内核 + 适配器接入
> **实现状态**: 🟢 已实现 / 🟡 部分实现 / 🔴 规划中

---

## 一、架构总览

### 1.1 设计哲学

DreamBuddy v2 采用**三层能力架构（L0/L1/L2）**，按「是否依赖生成式 LLM 推理」这一唯一判据划分能力层级：

| 层级 | 定位 | 驱动方式 | 成本 |
|------|------|---------|------|
| **L0 基础能力层** | 数据与事实的存储、采集、结构化 + 经验沉淀 + 工程检验 | 数据库 / 采集管线 / 规则 / 认知记录 | 零 token，独立双向层 |
| **L1 基础智能层** | 不依赖大模型的金融能力（已落地 10 意图） | 算法 / 规则 / 统计 / 意图识别 | 零 token，秒级响应 |
| **L2 大模型驱动层** | 语义理解、复杂推理、内容生成、跨域综合 | LLM（DreamOS C 层 + DSH + 子 Agent） | token 成本 |

**判据边界定义**：「依赖大模型」特指**依赖生成式 LLM 推理**（语义理解 / 复杂推理 / 内容生成）。
- **不含**：本地小模型、向量检索（embedding / 相似度召回）、确定性算法（规则 / 统计 / 贝叶斯）。
- **推论**：L1 的语义嵌入升级（TF-IDF + embedding 混合）**仍属 L1**——只要不调用生成式 LLM 推理。
- **收敛判据**：**「确定性 + 本地模型 / 向量检索」→ L1；「生成式 LLM 推理」→ L2**。

**路由逻辑**：前端用户需求先过 L1 → 命中执行意图则直接返回（零 token 秒回）→ 未命中再走 L2。**L0 不直接对外路由**，由 L1/L2 在工作前调用（fetchContext）、工作后沉淀（settle）。

核心设计理念：**纯编排层，不重复建设能力**。OS 内核（L2）只负责"调度"，所有具体能力通过适配器接入，不改核心代码。L2 内部编排采用**新 SACG**（S=认知驱动规划入口 → A=OKR 节点验收 → C=执行驱动 → G=压缩沉淀，C-drive 贯穿全程调度），详见 §1.2 / §1.3。

```
┌──────────────────────────────────────────────────────────────────┐
│                     应用层 (Applications)                         │
│   Agent B / Agent A / 三屏交易 / 研究助手 / ...                   │
│   （每个应用都是 OS 内核的一个使用者）                              │
├──────────────────────────────────────────────────────────────────┤
│                    能力层 (Capabilities)                          │
│   6-TRADING SKILLs / 10-经典指标 / 9-基本面 / 7-中台 / ...        │
│   （通过适配器接入 OS，不改核心代码）                               │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│                    DreamBuddy OS 内核（L2 大模型驱动层）           │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  C-drive 认知驱动路由 —— L2 全程调度者 / 节点级反思器      │    │
│  │  （贯穿 S→A→C→G 四层编排；双语义：调度者 ⇄ 反思器）         │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  S层 认知驱动规划入口                                     │    │
│  │  recall 经验先验 + 元认知门控 → 开工 Skill → Spec / Plan   │    │
│  └──────────────────────┬───────────────────────────────────┘    │
│                         ▼                                        │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  A层 OKR 节点验收体系                                     │    │
│  │  依据 Spec/Plan 分解 OKR 节点 + 每节点验收标准             │    │
│  └──────────────────────┬───────────────────────────────────┘    │
│                         ▼                                        │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  C层 执行驱动层                                           │    │
│  │  DSH 子 agent + GraphExecutor + Reflector（执行内反思）    │    │
│  └──────────────────────┬───────────────────────────────────┘    │
│                         ▼                                        │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  G层 压缩沉淀层                                           │    │
│  │  图压缩存储 + 收尾 Skill 认知沉淀（案例/认知/流程/文档）    │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Registry     │  │ Evolution    │  │ Budget       │          │
│  │ 注册表        │  │ 自我进化      │  │ 预算管理      │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

| 层级 | 类比 | 核心组件 | 作用 | 状态 |
|------|------|---------|------|------|
| **应用层** | 用户程序 | TradingAgent / API / CLI / 前端应用 | 面向用户的交互入口 | 🟢 已实现 |
| **能力层** | 硬件驱动 | SKILLs / 经典指标 / 基本面 | 具体专业能力，通过适配器接入 | 🟡 持续扩充 |
| **L0 基础能力层** | 存储/固件 | 数据库系统 / 广义认知系统(C1-C4) / REA 逆向解析 | 数据与经验供给、结果沉淀、工程检验（fetchContext ⇄ settle） | 🟢 成熟 |
| **L1 基础智能层** | OS用户态 | 意图注册表 / 路由器 / 十意图执行器 | 零 token 确定性金融能力 | 🟢 已实现 |
| **L2 大模型驱动层** | OS内核态 | 新 SACG（S 规划 / A 验收 / C 执行 / G 沉淀）+ C-drive | 生成式推理与编排 | 🟢 已实现 |
| **横切关注点** | OS系统服务 | Registry / Evolution / Budget | 节点注册、自我进化、预算管控 | 🟢 已实现 |

**核心原则**：
- **用户意图驱动**：从自然语言到意图识别再到分层路由执行，三层递进
- **判据唯一**：按「是否依赖生成式 LLM 推理」归层，**主体唯一、形态可降级**（无模型子集不改变归属）
- **图是一等公民**：所有执行以图结构组织，可追溯、可压缩、可展开
- **纯编排层**：OS内核（L2）只做调度，具体能力通过适配器接入，不改核心代码
- **模块化是基础**：统一契约，独立优化，按领域分类（A/C/F/G/T）
- **动态是常态**：AI驱动，根据置信度动态调整执行路径
- **原生压缩能力**：G层作为操作系统原生功能，上下文压缩是内置特性
- **前后端分工**：后端负责核心逻辑和执行，前端负责展示和交互

---

### 1.2 关键概念澄清

> **⚠️ 同名异义警戒 —— 务必区分以下五组概念，它们互不等价：**
>
> 1. **L0/L1/L2** = 三层能力架构（系统整体分层，见 §1.1）
> 2. **新 SACG** = **L2 内部**的编排四层（S=认知规划 / A=OKR 验收 / C=执行驱动 / G=压缩沉淀），仅在 L2 内部编排，C-drive 贯穿调度
> 3. **S链 / C链 / F链** = 三大思维链（骨架层，见第二章）——**与 SACG 无关**，也与 L0/L1/L2 无关
> 4. **认知 C1-C4** = 广义认知系统内部四层（C1 基础 / C2 记忆 / C3 路由 / C4 元认知，见 §1.5 与第七章）——与 L0/L1/L2 不同号语境，也与交易矛盾维度 C1-C8 不同号
> 5. **BAC 三层** = 图结构压缩模型（B=Blueprint / A=Architecture / C=Chronicle，见第三章）——**第三章的 A 层 / C 层是本模型的层，不是新 SACG 的 A/C**
>
> **旧 SACG（已作废）**：S=Sense 感知 / A=Arrange 编排 / C=Compute 执行 / G=Graph 图存储。凡见旧命名一律以本节新口径为准。

**新 SACG 四层定义**：

| 层 | 名称 | 定位 | 核心机制 | 产出 |
|----|------|------|---------|------|
| **S** | 认知驱动规划入口 | L2 规划的入口 | recall 经验先验 + 元认知门控 → 开工 Skill | Spec / Plan |
| **A** | OKR 节点验收体系 | 依据 Spec/Plan 验收 | 整体/局部 OKR 节点 + 每节点验收标准 | 节点验收结论 |
| **C** | 执行驱动层 | 执行与执行内反思 | DSH 子 agent + GraphExecutor 执行 + Reflector 执行内反思（毫秒级） | 执行结果 |
| **G** | 压缩沉淀层 | 存储与沉淀 | 图压缩存储 + 收尾 Skill 认知沉淀（案例/认知/流程/文档 四分流） | 压缩图 + 沉淀记录 |

**C-drive（认知驱动路由）**：L2 全程调度者，贯穿 S→A→C→G 四层编排流转；同时具反思器语义（节点级 jev 门）。两个已认可裁定：
- ① **OKR 归属**：S 层产草案 / A 层做验收；
- ② **C-drive 双语义**：调度者（S→A→C→G 编排）⇄ 反思器（节点 jev 门）。

**L2 内部组件与 SACG 的对应关系**（组件来自 Registry/能力层，SACG 只做编排）：

> **关键区分**：新 SACG 是 L2 内核的四层编排（认知规划/OKR 验收/执行驱动/压缩沉淀）；节点（A/C/F 系列技能）是能力层具体实现，通过 Registry 与适配器动态接入。S 层产出规划文档，A 层不包含业务节点。

| SACG 层 | 定位 | 核心组件 | 说明 |
|-------|------|---------|------|
| **S层** (认知规划) | 接入认知系统 + 生成 Spec/Plan | 认知系统 recall、REA 架构识别、开工 Skill | 产出 Spec / Plan；不重复 L1 已完成的粗分类 |
| **A层** (OKR 验收) | 验证节点目标达成 | OKR 分解器、验收标准、结果回传 | 依据 Spec/Plan 分解 OKR 节点，**不执行业务逻辑** |
| **C层** (执行驱动) | 执行节点 + 执行内反思 | DSH 子 agent、GraphExecutor、Reflector、Aggregator | 调度执行，**节点来自 Registry（能力层）** |
| **G层** (压缩沉淀) | 图压缩存储 + 认知沉淀 | GraphStore、Checkpointer、Compressor、收尾 Skill | 图压缩/展开 + 四分流沉淀 |

```
┌─────────────────────────────────────────────────────────────┐
│  【C-drive】认知驱动路由（L2 调度者 ⇄ 反思器）                 │
│  贯穿 S→A→C→G 四层；L1 未命中请求（携带 l1_intent_hint）进入  │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    S层 认知驱动规划入口                        │
│  认知系统 recall（经验先验）+ 元认知门控 → 开工 Skill          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ 经验先验     │  │ REA架构识别  │  │ 外部调研     │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
│  产出：Spec / Plan                                           │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    A层 OKR 节点验收体系                       │
│  依据 Spec/Plan 分解整体/局部 OKR 节点 + 每节点验收标准        │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    C层 执行驱动层                            │
│  DSH 子 agent + GraphExecutor + Reflector（执行内反思）       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ 子agent执行   │  │ 图节点执行    │  │ 执行内反思    │       │
│  │ (DSH, 默认    │  │ (调用Registry │  │ (过程决策,    │       │
│  │  isolated)   │  │  中的节点)    │  │  毫秒级)      │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│  执行结果回传 A 层做 OKR 节点验收（粒度不同于 Reflector）      │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    G层 压缩沉淀层                            │
│  图压缩存储（GraphStore）+ 收尾 Skill 认知沉淀                │
│  四分流：案例 / 认知 / 流程 / 文档                            │
└─────────────────────────────────────────────────────────────┘
```

---

### 1.3 整体架构图

DreamBuddy v2 整体采用**「应用层 + 能力层 + 路由器 + L0/L1/L2 分层内核」**结构。前端用户请求先经**路由器**（意图识别系统）判定层级归属，再决定落 L1（零 token 秒回）或 L2（token 成本）：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        应用层 (Applications) 🟢                          │
│   TradingAgent / HTTP API / CLI / 三屏交易前端 / ...                      │
│   （每个应用都是内核的一个使用者，通过统一接口调用内核能力）                │
├─────────────────────────────────────────────────────────────────────────┤
│                       能力层 (Capabilities) 🟡                           │
│   6-TRADING SKILLs / 10-经典指标 / 9-基本面 / 7-产物中台 / ...            │
│   （通过适配器接入：SkillAdapter / APIAdapter / FunctionAdapter）         │
├─────────────────────────────────────────────────────────────────────────┤
│                    路由器（意图识别系统）                                 │
│   意图预测 → 按层询问 canHandle → 置信度门控（读 L0 认知 C3/C4 信号）       │
│   高置信 → L1 直答（零 token）；置信度不高 → 转 L2（token 成本）           │
├─────────────────────────────────────────────────────────────────────────┤
│  L0 基础能力层（独立双向层 · 不对外路由 · fetchContext ⇄ settle）🟢       │
│   数据库系统（18 数据获取中心 / 19 DAL / 20 清洗 / 21 特征）              │
│   广义认知系统 C1-C4（35 协作模块 SSoT + 4-MEMORY 实现）                 │
│   REA 逆向解析（33：依赖图/调用链/架构模式/工程风控）                     │
├─────────────────────────────────────────────────────────────────────────┤
│  L1 基础智能层（零 token · 秒级）🟢                                      │
│   意图注册表（单一事实源）+ 十意图执行器（data_query / data_insight /     │
│   contradiction_insight / path_insight / technical_analysis /            │
│   fundamental_valuation / asset_class_trend / event_analysis /           │
│   risk_control / price_query）                                          │
├─────────────────────────────────────────────────────────────────────────┤
│  L2 大模型驱动层（token 成本）🟢                                         │
│   DreamBuddy OS 内核（Core Kernel）— 内部编排 = 新 SACG                  │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  C-drive 认知驱动路由：贯穿 S→A→C→G（调度者 ⇄ 反思器）            │   │
│   ├─────────────────────────────────────────────────────────────────┤   │
│   │  S层 认知驱动规划入口                                            │   │
│   │   认知系统 recall（经验先验）+ 元认知门控 + REA 架构识别           │   │
│   │   → 开工 Skill 产出 Spec / Plan                                  │   │
│   ├─────────────────────────────────────────────────────────────────┤   │
│   │  A层 OKR 节点验收体系                                            │   │
│   │   依据 Spec/Plan 分解整体/局部 OKR 节点 + 每节点验收标准           │   │
│   ├─────────────────────────────────────────────────────────────────┤   │
│   │  C层 执行驱动层                                                  │   │
│   │   DSH 子 agent + GraphExecutor + Reflector（执行内反思，毫秒级）   │   │
│   │   结果回传 A 层做 OKR 节点验收                                    │   │
│   ├─────────────────────────────────────────────────────────────────┤   │
│   │  G层 压缩沉淀层                                                  │   │
│   │   GraphStore 图压缩存储 + 收尾 Skill 认知沉淀（案例/认知/流程/文档）│   │
│   └─────────────────────────────────────────────────────────────────┘   │
│   横切关注点：Registry 节点注册表 / Evolution 自我进化 / Budget 预算管控   │
│              Adapters 适配器 / State 全局状态 / Errors 错误码体系         │
└─────────────────────────────────────────────────────────────────────────┘
```

**路由与数据流方向**：用户请求 → 应用层 → 路由器（定层）→ L1 直答 或 L2 内核（S→A→C→G）→ 能力层（经适配器）→ 返回结果。

**L0 双向流**：L1/L2 工作前经 `fetchContext` 取数据/经验/工程结论；工作后经 `settle` 沉淀（数据入库 / 经验入认知库 / 工程结论入 REA 检验体系）。

**核心设计**：L2 内核是"纯编排层"，所有具体能力（SKILLs/经典指标/基本面）都通过适配器接入，不改核心代码；L0/L1 为确定性零 token 能力，token 成本严格限制在 L2。

---

### 1.4 三大核心闭环架构

Dreambuddy OS 的 A 系列节点按**三大核心闭环**组织，每个闭环有明确的职责和触发机制：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         三大核心闭环                                      │
│                                                                         │
│  🔵 执行环 (Execution Loop)                                              │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  A1 ──→ A2 ──→ A3 ──→ A4 ──→ A5 ──→ A9                        │   │
│  │  发现    辩证     推演     门禁     战术     离场                 │   │
│  │  主要    看待     解决     过滤     执行     评估                 │   │
│  │  矛盾    矛盾     矛盾                                          │   │
│  │   │       │       │                                            │   │
│  │  (含A0)  (含A0)  (含A0)                                        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  🟠 情报环 (Intelligence Loop)                                            │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  A6 (每1H运行)                                                   │   │
│  │  ┌─────────┐                                                   │   │
│  │  │ 情报监控 │ ──→ Level 1-5 分级响应                             │   │
│  │  │ 市场雷达 │ ──→ Level 1.5: A2增量更新                          │   │
│  │  └─────────┘ ──→ 双轨触发: A6自主 + A4上报                       │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  🟣 治理环 (Governance Loop) — 两个独立维度                               │
│                                                                         │
│  维度1: gap_score 路由闭环 (知行合一)                                     │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  A9 ──→ A7 ──→ A8(gap_score) ──→ 路由修正                       │   │
│  │  离场    实践    知行合一            │                            │   │
│  │  评估    记录    (自我批评)          ├─≥0.5──→ A1 重启            │   │
│  │                             │        ├0.3~0.5→ A2 更新            │   │
│  │                             │        └─<0.3──→ A3 优化            │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  维度2: 做梦部 (独立潜意识分析, 不串入 gap_score 链)                       │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  做梦部 (dream-oneirology)                                       │   │
│  │  ┌──────────────┐                                               │   │
│  │  │ 弗洛伊德潜意识 │ ──→ 被压制的判断清单                           │   │
│  │  │ 反直觉分析    │ ──→ 强迫性重复检测(连败≥3)                     │   │
│  │  │ 第三只眼      │ ──→ 噩梦场景模拟                              │   │
│  │  └──────────────┘ ──→ 反事实损益表                              │   │
│  │  触发条件: 连败≥3 / 置信度55-64% / A8检测到被压制判断              │   │
│  │  定位: 参考信号, 不直接执行, 独立于 gap_score 路由                 │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  A0 矛盾论 (治理环方法论基础, 内嵌到 A1/A2/A3)                     │   │
│  │  A7 实践论 (治理环门禁基础, INDEPENDENT_AUTO 独立验证)              │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### A0 矛盾论内嵌关系

A0 矛盾论不是独立节点，而是内嵌到 A1→A2→A3 全链路的方法论框架：

| 节点 | A0 调用方式 | 职责 |
|------|------------|------|
| A1 深度调研 | 调用 A0 **发现主要矛盾** | 识别市场当前的主要矛盾是什么 |
| A2 第一性原理 | 调用 A0 **辩证看待矛盾** | 分析矛盾的主次关系，哪个决定方向，哪个决定节奏 |
| A3 策略设计 | 调用 A0 **推演解决矛盾** | 围绕主要矛盾推演解决方案 |

> **核心逻辑**：A1 发现矛盾 → A2 辩证矛盾 → A3 解决矛盾，A0 贯穿三节点。

#### 三大闭环详细说明

| 闭环 | 节点流 | 触发机制 | 核心职责 |
|------|--------|---------|---------|
| 🔵 执行环 | A1→A2→A3→A4→A5→A9 | 用户请求 / 定时调度 | 发现矛盾→辩证矛盾→解决矛盾→门禁→执行→离场 |
| 🟠 情报环 | A6 | 每1H自动运行 | 5级放射，驱动执行环增量更新 |
| 🟣 治理环·维度1 | A9→A7→A8→A1/A2/A3 | 离场后触发 | gap_score路由修正（知行合一闭环） |
| 🟣 治理环·维度2 | 做梦部 | 连败≥3/置信度55-64% | 独立潜意识分析（不串入gap_score链） |

#### A 系列节点完整定义

| 节点 | 名称 | 闭环 | SKILL路径 | 职责 | 状态 |
|------|------|------|-----------|------|------|
| A0 | 矛盾论 | 治理(内嵌) | `dream-contradiction-theory` | 内嵌A1/A2/A3: 发现→辩证→解决矛盾 | 🟢 |
| A1 | 深度调研 | 执行 | `asset-research` + Tavily | 发现主要矛盾(Tavily+LLM+调用A0) | 🟡 |
| A2 | 第一性原理 | 执行 | `dream-first-principles` | 辩证看待矛盾(阻力最小路径+调用A0) | 🟡 |
| A3 | 策略设计 | 执行 | `dream-strategy-designer` | 推演解决矛盾(大师研讨+沙盘+调用A0) | 🟡 |
| A4 | 门禁 | 执行 | `dream-pretrade-gatekeeper` | 置信度门禁+风险过滤+PASS/SKIP决策 | 🟡 |
| A5 | 战术执行 | 执行 | `dream-tactical-executor` | 仓位/杠杆/止损止盈+OKX下单 | 🟡 |
| A6 | 情报监控 | 情报 | `dream-intelligence-monitor` | 每小时市场雷达+5级放射响应 | 🟡 |
| A7 | 实践论门禁 | 治理 | `A7-practice-theory` | INDEPENDENT_AUTO独立验证A4/A5 | 🟡 |
| A8 | 知行合一 | 治理·维度1 | `A8-theory-practice-verification` | gap_score路由+纸上谈兵检测+回滚机制 | 🟡 |
| A9 | 离场评估 | 执行 | `dream-exit-skill-v2` | 四层离场决策链+OKX TP/SL联动 | 🟡 |
| 做梦部 | 梦境分析 | 治理·维度2 | `dream-oneirology` | 弗洛伊德潜意识+反直觉信号(独立维度) | 🟡 |

#### 意图到链路映射

| 意图类型 | 推荐链路 | 节点序列 | 说明 |
|---------|---------|---------|------|
| TREND_FOLLOWING | A链(精简) | C1→F2/F3→A2→A4 | 趋势跟随 |
| MEAN_REVERSION | A链(精简) | C1→F2/F3→A2→A4 | 均值回归 |
| FUNDAMENTAL_PLAY | F链 | A1→F1→F5→A2→A4 | 基本面驱动 |
| BREAKOUT | C链 | C1→A2→C3→A4 | 突破 |
| KNOWLEDGE_MATCH | C链(快捷) | C3→A4 | 知识库快捷路径 |
| UNCERTAIN | A链(完整) | C1→A1→A2→A4 | 不确定时走完整链路 |

> **注意**：A0 矛盾论内嵌到 A1/A2/A3，不在链路中独立出现。A1 发现矛盾、A2 辩证矛盾、A3 解决矛盾。

#### 治理环两个维度说明

**维度1 — gap_score 路由闭环**（知行合一）：

离场后 A8 知行合一检查产出 gap_score，根据分数路由到不同修正节点：

| gap_score | 路由目标 | 含义 |
|-----------|---------|------|
| ≥ 0.5 | A1 重启 | 认知差距大，需重新发现矛盾 |
| 0.3 ~ 0.5 | A2 更新 | 分析方向需调整，重新辩证矛盾 |
| < 0.3 | A3 优化 | 策略细节需优化，重新推演解决 |

**维度2 — 做梦部**（独立潜意识分析）：

做梦部是**独立于 gap_score 路由**的治理维度，不串入 gap_score 链：

- 定位：参考信号，不直接执行，提供"第三只眼"视角
- 触发条件：连续 SKIP ≥ 3 次 / 置信度 55%~64% / A8 检测到被压制的判断
- 输出：被压制的判断清单、强迫性重复检测、噩梦场景模拟、反事实损益表

---

### 1.5 L2 内核组件清单（新 SACG · Python 实现）

本节列出 **L2 大模型驱动层**内核（`1-ARCHITECTURE/dreamos/`）的核心组件，这是当前主要实现版本。**这些是旧 SACG 命名下的代码实体**，按新 SACG 口径的映射见 §1.2；下表按新口径重新标注。

> **代码路径未变，语义定位已升级**：`core/sense/` 从"S层 感知层"升级为 **S层 认知驱动规划入口** 的支撑（意图识别已上移 L1，S层聚焦认知规划 + Spec/Plan 生成）；`core/arrange/` 的 GraphPlanner 演进为 **A层 OKR 节点验收**；`core/compute/` 的 GraphExecutor + Reflector 为 **C层 执行驱动**；`core/graph_store/` 为 **G层 压缩沉淀**。

#### 1.5.1 内核总览（按新 SACG 口径）

```
dreamos/
├── core/                    # L2 内核 — 新 SACG 四层
│   ├── sense/               # S层: 认知驱动规划入口支撑（意图识别已上移 L1）
│   ├── arrange/             # A层: OKR 节点验收（GraphPlanner 演进）
│   ├── compute/             # C层: 执行驱动（GraphExecutor + Reflector）
│   └── graph_store/         # G层: 压缩沉淀（存储/检查点/压缩）
├── nodes/                   # 业务节点 (能力层示例实现, 动态发现)
├── registry/                # 节点注册表 + 版本管理
├── adapters/                # 适配器框架 (Function/Skill/API)
├── apps/                    # 应用层 (TradingAgent / API / CLI)
├── evolution/               # 自我进化 (经验提炼/差距分析)
├── budget/                  # 全局预算管理
└── shared/                  # 共享基础 (State/Errors/Utils)
```

#### 1.5.2 S层（认知驱动规划入口）— 意图识别支撑组件

> 说明：新架构下 L1 承担零 token 意图识别（十意图注册表 + 路由器），本节组件为 L2 内 S 层的历史支撑/兜底实现，供 S 层做深化识别时参考。

| 组件 | 文件路径 | 职责说明 |
|------|---------|---------|
| IntentEngine | `dreamos/core/sense/intent_engine.py` | 意图识别主入口，协调多个识别器 |
| RuleBasedRecognizer | `dreamos/core/sense/recognizers/rule_based.py` | 规则识别器（市场数据+关键词，零Token） |
| LLMBasedRecognizer | `dreamos/core/sense/recognizers/llm_based.py` | LLM识别器（自然语言深度理解） |
| DynamicRecognizer | `dreamos/core/sense/recognizers/dynamic.py` | 动态识别器（规则→LLM渐进升级） |
| TokenBudget | `dreamos/core/sense/token_budget.py` | Token预算管控 |
| IntentResult | `dreamos/core/sense/types.py` | 意图结果（类型/置信度/推荐链路） |

#### 1.5.3 A层（OKR 节点验收体系）— 不执行业务逻辑

| 组件 | 文件路径 | 职责说明 |
|------|---------|---------|
| GraphPlanner | `dreamos/core/arrange/graph_planner.py` | 图规划器主入口 |
| NodeSelector | `dreamos/core/arrange/node_selector.py` | 节点选择器（从Registry选节点） |
| BudgetAllocator | `dreamos/core/arrange/budget_allocator.py` | 预算分配器 |
| SequentialGraph | `dreamos/core/arrange/execution_graph.py` | 顺序执行图 |
| ConditionalGraph | `dreamos/core/arrange/execution_graph.py` | 条件执行图 |
| STANDARD_CHAINS | `dreamos/core/arrange/types.py` | 标准链路定义（A/C/F/G1/G2/I） |

> **注意**：A层是 OKR 节点验收体系，节点（A1/A2/...）来自 NodeRegistry，A层不包含任何业务节点；A层依据 S 层产出的 Spec/Plan 分解整体/局部 OKR 节点并逐节点验收。

#### 1.5.4 C层（执行驱动层）— DSH 子 agent + 节点执行，节点来自 Registry

| 组件 | 文件路径 | 职责说明 |
|------|---------|---------|
| GraphExecutor | `dreamos/core/compute/graph_executor.py` | 图执行器主入口 |
| NodeRunner | `dreamos/core/compute/node_runner.py` | 节点运行器（执行单个节点） |
| Reflector | `dreamos/core/compute/reflector.py` | 反射决策器（CONTINUE/REDO/JUMP/INSERT/TERMINATE） |
| Aggregator | `dreamos/core/compute/aggregator.py` | 结果聚合器（加权融合/分歧检测） |
| ExecutionReport | `dreamos/core/compute/types.py` | 执行报告 |

> **注意**：C层调度执行节点，但节点本身来自 Registry（能力层），C层不包含业务节点实现。

#### 1.5.5 G层（压缩沉淀层）

| 组件 | 文件路径 | 职责说明 |
|------|---------|---------|
| GraphStore | `dreamos/core/graph_store/store.py` | 图存储主入口 |
| Checkpointer | `dreamos/core/graph_store/checkpointer.py` | 状态检查点 |
| ContextCompressor | `dreamos/core/graph_store/compressor.py` | 上下文压缩器 |
| HistoryReplay | `dreamos/core/graph_store/history.py` | 历史回放 |

#### 1.5.6 横切关注点

| 组件 | 文件路径 | 职责说明 |
|------|---------|---------|
| NodeRegistry | `dreamos/registry/node_registry.py` | 节点注册表（注册/查询/列表） |
| RegistryLoader | `dreamos/registry/loader.py` | YAML/JSON批量加载 |
| VersionManager | `dreamos/registry/version_manager.py` | 版本管理（semver+依赖检查） |
| EvolutionEngine | `dreamos/evolution/engine.py` | 进化引擎（经验提炼→差距分析→节点优化） |
| LessonDistiller | `dreamos/evolution/lesson_distiller.py` | 经验提炼器 |
| GapAnalyzer | `dreamos/evolution/gap_analyzer.py` | 差距分析器 |
| NodeOptimizer | `dreamos/evolution/node_optimizer.py` | 节点优化建议器 |
| GlobalBudget | `dreamos/budget/global_budget.py` | 全局预算管理（三层模式/四层健康度） |
| CostTracker | `dreamos/budget/cost_tracker.py` | 成本追踪器 |

#### 1.5.7 能力层 — 业务节点（动态注册）

| 节点 | 文件路径 | 所属链 | 职责 | 状态 |
|------|---------|--------|------|------|
| A1 深度调研 | `dreamos/nodes/a1_deep_research.py` | A | 发现主要矛盾 | 🟡 |
| A2 第一性原理 | `dreamos/nodes/a2_comprehensive.py` | A | 辩证看待矛盾 | 🟡 |
| A0 矛盾论(内部) | `dreamos/nodes/a0_contradiction.py` | A(内部) | 内嵌A1/A2/A3，不独立执行 | 🟢 |
| C1 技术扫描 | `dreamos/nodes/c1_tech_scan.py` | C | 基础技术指标扫描 | 🟢 |
| F2 资金流分析 | `dreamos/nodes/f2_fund_flow.py` | F | 资金流向分析 | 🟢 |
| F3 情绪分析 | `dreamos/nodes/f3_sentiment.py` | F | 市场情绪分析 | 🟢 |

> **设计原则**：业务节点是能力层，通过 Registry 动态注册，OS内核(SACG)只做调度，不改核心代码。新增节点只需继承 BaseNode 并放入 `dreamos/nodes/` 目录即可自动发现。

#### 1.5.8 应用层

| 组件 | 文件路径 | 职责说明 |
|------|---------|---------|
| TradingAgent | `dreamos/apps/trading_agent/agent.py` | 交易Agent（S-A-C-G全链路编排） |
| HTTP API | `dreamos/apps/api_server.py` | Flask REST API（8个端点） |
| CLI | `dreamos/apps/cli.py` | 命令行工具（7个子命令+REPL） |

---

### 1.6 历史版本组件清单（TypeScript 实现 · 旧架构已弃用）

> **说明**：以下是历史 TypeScript 版本（`6-图结构上下文压缩/`）的组件清单，**属于旧 SACG 架构（S=Sense 感知 / A=Arrange 编排 / C=Compute 执行 / G=Graph 图存储），已弃用**，仅供参考；当前主实现为新 SACG 口径的 Python 版本（见 §1.5）。**本节内容不得作为实现依据。**

#### 1.6.1 S层（意图识别层）

| 组件名称 | 文件路径 | 职责说明 | 状态 |
|---------|---------|---------|------|
| IntentGateway | `6-图结构上下文压缩/intent-gateway.ts` | 意图分类、主链推荐、扩展节点池构建 | 🟢 |
| ChainPlanner | `6-图结构上下文压缩/planner/planner.ts` | 四维规划（Token预算/知识库命中/历史表现/标的覆盖） | 🟢 |
| ChainsRegistry | `6-图结构上下文压缩/planner/chains-registry.ts` | 思维链注册表（S/C/F三链定义） | 🟢 |
| ModuleRegistry | `6-图结构上下文压缩/planner/module-registry.ts` | 模块注册表 | 🟢 |
| SkillsRegistry | `6-图结构上下文压缩/planner/skills-registry.ts` | 技能注册表初始化 | 🟢 |

#### 1.6.2 A层（图编排层）

| 组件名称 | 文件路径 | 职责说明 | 状态 |
|---------|---------|---------|------|
| GraphOrchestrator | `6-图结构上下文压缩/architecture.ts` | 图编排器，构建和管理执行图 | 🟢 |
| GraphExecutor | `6-图结构上下文压缩/graph-executor.ts` | 图执行器，按依赖关系执行节点 | 🟢 |
| GraphParallel | `6-图结构上下文压缩/graph-parallel.ts` | 并行执行引擎 | 🟢 |
| GraphHITL | `6-图结构上下文压缩/graph-hitl.ts` | 人机交互集成 | 🟢 |
| ReflectEngine | `3-FRONTEND/dream-universal-gateway/src/lib/dynamic-chain/reflect-engine.ts` | 反思决策引擎（5种决策类型） | 🟢 |
| SkillSelector | `6-图结构上下文压缩/planner/skill-selector.ts` | 技能选择器 | 🟢 |
| CrossValidator | `6-图结构上下文压缩/planner/cross-validator.ts` | 交叉验证器（三链投票） | 🟢 |
| ConfidenceEvaluator | `6-图结构上下文压缩/planner/confidence-evaluator.ts` | 置信度评估器 | 🟢 |
| BlueprintRegistry | `6-图结构上下文压缩/blueprint-registry.ts` | 蓝图注册表 | 🟢 |

#### 1.6.3 C层（执行层）

| 组件名称 | 文件路径 | 职责说明 | 状态 |
|---------|---------|---------|------|
| UnifiedExecutor | `6-图结构上下文压缩/graph-executor.ts` | 统一执行器 | 🟢 |
| DynamicChainRunner | `3-FRONTEND/dream-universal-gateway/src/lib/dynamic-chain/runner.ts` | 动态链运行器（前端展示版） | 🟢 |
| A系列技能 | `6-TRADING/skills/` | AI交易技能（dream-*系列） | 🟢 |
| C系列技能 | `10-经典指标系统/` | 经典量化技能（RSI/MACD/回测等） | 🟢 |
| F系列技能 | `6-TRADING/skills/` | 基本面工具（Tavily/情绪/链上等） | 🟡 |
| VotingCalculator | `6-图结构上下文压缩/planner/voting-calculator.ts` | 投票计算器 | 🟢 |

#### 1.6.4 G层（图存储压缩层）

| 组件名称 | 文件路径 | 职责说明 | 状态 |
|---------|---------|---------|------|
| Blueprint (G.B) | `6-图结构上下文压缩/blueprint.ts` | 蓝图层 - 顶层架构图 | 🟢 |
| Architecture (G.A) | `6-图结构上下文压缩/architecture.ts` | 架构层 - DAG执行图 | 🟢 |
| Chronicle (G.C) | `6-图结构上下文压缩/chronicle.ts` | 记录层 - 执行时间线 | 🟢 |
| Compressor | `6-图结构上下文压缩/compressor.ts` | 图压缩器（C→A→B回溯压缩） | 🟢 |
| IncrementalCompressor | `6-图结构上下文压缩/incremental-compressor.ts` | 增量压缩器 | 🟢 |
| SemanticCompressor | `6-图结构上下文压缩/semantic-compressor.ts` | 语义压缩器 | 🟡 |
| ShardedCompressor | `6-图结构上下文压缩/sharded-compressor.ts` | 分片压缩器 | 🟡 |
| GraphCheckpointer | `6-图结构上下文压缩/graph-checkpointer.ts` | 图检查点 | 🟢 |
| GraphState | `6-图结构上下文压缩/graph-state.ts` | 图状态管理 | 🟢 |
| Visualization | `6-图结构上下文压缩/visualization.ts` | 可视化工具 | 🟢 |
| Models | `6-图结构上下文压缩/models.ts` | 数据模型定义（BNode/ANode/CNode等） | 🟢 |

#### 1.6.5 基础设施层

| 组件名称 | 文件路径 | 职责说明 | 状态 |
|---------|---------|---------|------|
| **产物中台** | `7-产物中台/` | 产物存储、分发、状态追踪 | 🟢 |
| **记忆系统** | `4-MEMORY/` | 意图记忆、用户偏好、经验模式 | 🟡 |
| **知识库** | `2-KNOWLEDGE/` | 策略、方法论、理论、运营知识 | 🟢 |
| **索引系统** | `2-KNOWLEDGE/0-SCHEMA/` | L1主索引/L2目录索引/L3文件锚点 | 🟢 |
| **自我进化引擎** | `3-EVOLUTION/` | 发现问题→学习记录→深度分析→能力更新 | 🟡 |
| **治理系统** | `2-GOVERNANCE/` | 宪法层、治理流程、门禁审计 | 🟡 |
| **数据服务** | `6-TRADING/bridge/api/` | 行情数据、实时推送、交易接口 | 🟢 |

#### 1.6.6 前端与API层

| 组件名称 | 文件路径 | 职责说明 | 状态 |
|---------|---------|---------|------|
| 前端网关 | `3-FRONTEND/dream-universal-gateway/` | 统一前端入口、展示与交互 | 🟢 |
| 交易桥接API | `6-TRADING/bridge/api/` | 后端API服务（/api/orchestrate等） | 🟢 |
| WebSocketManager | `6-TRADING/bridge/api/websocket_manager.py` | WebSocket流式推送 | 🟢 |
| SkillRouterAPI | `6-TRADING/bridge/api/skill_router_api.py` | 技能路由API | 🟢 |

---

## 二、三大思维链（骨架层）

### 2.1 三链定位

> **⚠️ 消歧**：S链 / C链 / F链 是三大**思维链**（骨架层），**与 §1.2 的新 SACG（L2 编排四层）无关，也与 L0/L1/L2 分层无关**。名称中的 S/C/F 是思维链代号，**不是** SACG 的 S/C 层。

三大思维链是系统的**骨架**，定义思考的顺序和框架，但不定义具体实现。每步内部由AI动态决定调用什么技能。

| 链 | 名称 | 思维模式 | 适用场景 | 五步框架 | 技能系列 | 状态 |
|----|------|---------|---------|---------|---------|------|
| **S链** | 通用交易思维链 | 定性+定量结合，主链路 | 交易决策、策略构建、深度分析 | S1调研→S2分析→S3设计→S4验证→S5执行 | A系列（AI交易技能） | 🟢 |
| **C链** | 量化技术思维链 | 纯技术/量化导向 | 技术指标分析、策略回测、参数优化 | C1扫描→C2识别→C3匹配→C4回测→C5参数 | C系列（经典量化技能） | 🟢 |
| **F链** | 基本面思维链 | 基本面/宏观导向 | 基本面分析、宏观研判、新闻解读 | F1新闻→F2资金→F3情绪→F4链上→F5宏观 | F系列（基本面技能） | 🟡 |

> **关键认知**：三链不是互斥的，是**互补的三个维度**。以一条为主链，在关键节点通过交叉验证或动态插入，融合另外两条链的能力。

---

### 2.2 S链 — 通用交易思维链（主链）

**S链是系统的核心骨架**，覆盖从调研到执行的完整交易决策流程。A系列技能、三屏交易系统、三大闭环都是S链的"血肉"模块。

```
S1_调研 (Research)
  ├─ 核心问题：当前市场处于什么状态？有哪些关键因素？
  ├─ 推荐技能类别：intelligence, execution
  ├─ 对应A系列技能：dream-strategy-research, dream-data-analysis, Tavily搜索
  └─ 产出：市场调研报告

S2_分析 (Analysis)
  ├─ 核心问题：多空逻辑是什么？主要矛盾在哪？置信度多少？
  ├─ 推荐技能类别：execution, intelligence
  ├─ 对应A系列技能：dream-contradiction-theory, dream-first-principles, master-seminar
  ├─ 必选技能：dream-regime-detector
  └─ 产出：深度分析报告 + 多空倾向 + 置信度评分

S3_设计 (Design)
  ├─ 核心问题：具体策略方案是什么？入场/止损/止盈/仓位？
  ├─ 推荐技能类别：execution, research
  ├─ 对应A系列技能：dream-strategy-designer, dream-strategy-parser, war-game-simulator
  └─ 产出：交易策略方案 + 风险管理方案

S4_验证 (Validate)
  ├─ 核心问题：这个策略历史表现如何？有哪些风险？
  ├─ 推荐技能类别：governance, research
  ├─ 对应A系列技能：dream-backtest, dream-bayesian-opt, dream-tactical-validator
  ├─ 必选技能：dream-pretrade-gatekeeper
  └─ 产出：回测报告 + 参数优化方案

S5_执行 (Execute)
  ├─ 核心问题：如何落地执行？门禁检查通过了吗？
  ├─ 推荐技能类别：execution
  ├─ 对应A系列技能：dream-pretrade-gatekeeper, dream-tactical-executor, dream-exit-skill-v2
  └─ 产出：执行结果 + 交易记录
```

#### S链内嵌模块：三屏交易系统

**三屏系统是S链中最成熟、最核心的技能模块集群**，覆盖战略→战术→执行三层：

| 层级 | 屏 | 周期 | 核心SKILL | 对应S链阶段 | 状态 |
|------|----|------|-----------|------------|------|
| 战略层 | Screen1 | 周线 | `dream-screen1-first` | S1+S2（方向研判） | 🟢 |
| 战术层 | Screen2 | 日线 | `dream-screen2-second` | S2+S3（策略设计） | 🟢 |
| 执行层 | Screen3 | 实时 | `dream-screen3-third` | S4+S5（验证执行） | 🟢 |

#### S链内嵌模块：三大闭环

**三大闭环是S链内部的三类技能模块集群**，不是独立的架构环：

```
┌─────────────────────────────────────────────────────────────┐
│              交易执行闭环（主链路技能集群）                     │
│  A0矛盾→A1调研→A2第一性→A3沙盘→A4验证→A5执行→A6监控→A7门禁→A9离场  │
│  对应S链全流程（S1-S5）                                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              情报监控闭环（并行技能集群）                       │
│  信号采集→异常检测→告警响应→应急处置→影响评估→A1/A2/A3增量更新  │
│  主要支撑S1（调研）和S2（分析）                                 │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              治理闭环（约束技能集群）                           │
│  宪法层→治理层→门禁层→执行层→审计追溯→改进迭代                 │
│  贯穿全流程，主要作用于S4（验证）和S5（执行）                   │
└─────────────────────────────────────────────────────────────┘
```

---

### 2.3 C链 — 量化技术思维链

```
C1_扫描 (Scan)
  ├─ 核心问题：当前技术面有哪些信号？
  ├─ 技能：classic-indicator-scan（RSI/MACD/MA/Bollinger/ATR）
  ├─ 接入：经典指标系统 (:8092)
  └─ 产出：技术信号清单

C2_识别 (Identify)
  ├─ 核心问题：当前是什么Regime？趋势/震荡/突破？
  ├─ 技能：classic-regime-detection
  └─ 产出：Regime判定 + 置信度

C3_匹配 (Match)
  ├─ 核心问题：适合什么策略？
  ├─ 技能：策略库匹配、经典10策略、freqtrade策略
  └─ 产出：匹配策略列表 + 评分

C4_回测 (Backtest)
  ├─ 核心问题：历史表现如何？
  ├─ 技能：经典回测系统、Gate评估
  └─ 产出：回测报告

C5_参数 (Optimize)
  ├─ 核心问题：参数如何优化？
  ├─ 技能：贝叶斯优化、网格搜索、Walk-forward
  └─ 产出：优化后参数
```

---

### 2.4 F链 — 基本面思维链

```
F1_新闻 (News)
  ├─ 核心问题：有哪些重要新闻/事件？
  ├─ 技能：Tavily搜索、新闻日历
  └─ 产出：新闻摘要 + 重要性评分

F2_资金 (Capital Flow)
  ├─ 核心问题：资金流向如何？
  ├─ 技能：资金费率分析、交易所余额追踪、鲸鱼地址追踪
  └─ 产出：资金流向报告

F3_情绪 (Sentiment)
  ├─ 核心问题：市场情绪如何？贪婪还是恐惧？
  ├─ 技能：恐惧贪婪指数、社交情绪分析、多空比
  └─ 产出：情绪评分 + 极端信号

F4_链上 (On-chain)
  ├─ 核心问题：链上指标怎么看？
  ├─ 技能：MVRV、NUPL、SOPR、UTXO年龄分布
  └─ 产出：链上分析报告

F5_宏观 (Macro)
  ├─ 核心问题：宏观环境如何？
  ├─ 技能：美联储政策、美元指数、国债收益率、宏观数据
  └─ 产出：宏观研判报告
```

---

### 2.5 三链结合策略（两阶段）

三链不是互斥的，根据问题复杂度采用不同的结合方式：

```
┌──────────────────────────────────────────────────────────┐
│  阶段一：简单问题 — 交叉验证投票 🟢 已实现                   │
│                                                          │
│  主链执行 → 关键验证点 → 收集A/C/F三链信号 → 加权投票 → 共识  │
│                                                          │
│  特点：轻量、快速，不改变主链执行序列                       │
│  触发：置信度中等、常规问题                                 │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  阶段二：复杂问题 — 动态插入节点 🟡 部分实现                 │
│                                                          │
│  主链执行 → 置信度不足 → 从技能注册表追加其他链步骤 → 继续执行  │
│                                                          │
│  特点：深度、精准，改变执行图结构                           │
│  触发：低置信度、三链分歧、高复杂度问题                       │
│  来源：1) 三链SKILL注册表；2) AI自行思考；3) 联网补充        │
└──────────────────────────────────────────────────────────┘
```

#### 交叉验证权重（阶段一）

| 验证点 | S链(A系列) | C链 | F链 | 触发条件 |
|--------|-----------|-----|-----|---------|
| 方向判定（S2） | 40% | 35% | 25% | S2阶段结束时 |
| 入场时机（S3） | 30% | 50% | 20% | S3阶段结束时 |
| 离场决策（S5） | 35% | 30% | 35% | A9离场时 |

**共识达成逻辑**：
- 三链一致 → 高置信度，可跳过验证
- 两链一致 → 正常置信度，按计划执行
- 三链分歧 → 低置信度，**触发阶段二（动态插入深度分析）**

---

## 三、图结构压缩模型（BAC三层）

### 3.1 模型总览

图结构上下文压缩是系统的**记忆与追溯基础设施**，采用BAC三层模型：

```
正向展开 (B → A → C)：
  🏗️ Blueprint ──展开──→ 🔀 Architecture ──展开──→ ⏱️ Chronicle
     (顶层架构)             (DAG依赖)              (执行记录)

回溯压缩 (C → A → B)：
  ⏱️ Chronicle ──压缩──→ 🔀 Architecture ──压缩──→ 🏗️ Blueprint
     (完整记录)             (保留依赖)              (架构级摘要)
```

**OKR 映射**：
| 层级 | OKR对应 | 时间维度 | 特性 |
|------|--------|---------|------|
| B层 | Long-term Objective | long | 跨多轮持久，一般不变 |
| A层 | Key Results / Mid-term tasks | mid | 当轮计划，动态调整 |
| C层 | Short-term execution | short | 当步执行记录 |

---

### 3.2 B层 — Blueprint（蓝图/总目标）

**定义**：顶层架构图，描述本次任务的宏观组件和数据流向。

**特点**：
- **一般不变**：总目标确定后，B层架构基本固定
- **模块级粒度**：只定义大的组件和流向，不涉及具体步骤
- **对应思维链骨架**：选择了哪条主链，B层就对应哪条链的宏观结构
- **由ChainPlanner在规划阶段构建**

**数据结构**（来源：[models.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/models.ts#L35-L59)）：
```typescript
interface BNode {
  id: NodeId;
  type: 'component' | 'module' | 'service';
  name: string;
  description: string;
  metadata: NodeMetadata;
  children?: NodeId[];
}

interface BlueprintGraph {
  id: string;
  name: string;
  version: string;
  nodes: Map<NodeId, BNode>;
  edges: BEdge[];
  rootId: NodeId;
  createdAt: number;
}
```

**示例（S链B层）**：
```
bp_root (交易决策系统)
├── intent_engine (意图识别引擎)
├── knowledge_base (知识库检索)
├── market_data (行情数据服务)
├── analysis_chain (分析链模块)
│   ├── S1_调研
│   ├── S2_分析
│   ├── S3_设计
│   ├── S4_验证
│   └── S5_执行
├── strategy_engine (策略引擎)
└── report_generator (报告生成器)
```

---

### 3.3 A层 — Architecture（执行图/DAG）

**定义**：执行步骤级的DAG（有向无环图），定义具体的执行步骤和依赖关系。

**特点**：
- **动态可变**：AI驱动，根据执行结果实时调整
- **步骤级粒度**：每个节点是一个具体的执行步骤
- **对应血肉层**：节点就是具体的SKILL调用或工具调用
- **由ChainPlanner初步规划，执行中动态调整**

**变化触发因素**：

| 触发因素 | 变化类型 | 说明 | 状态 |
|---------|---------|------|------|
| 置信度过低 | REDO / backtrack | 重做当前节点，换个技能/参数 | 🟢 |
| 信息不足 | INSERT_BEFORE | 在当前节点前插入补充节点 | 🟢 |
| 高置信度 | JUMP_TO / skip | 跳过验证节点，直接进入下一步 | 🟢 |
| 三链分歧 | 追加其他链节点 | 动态插入C/F链步骤做交叉验证 | 🟡 |
| 新发现 | INSERT_AFTER | 追加深度分析节点 | 🟡 |
| 技能不够 | 联网扩展 | AI决定需要外部工具/搜索 | 🔴 |

**反思决策引擎**（来源：[reflect-engine.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/dynamic-chain/reflect-engine.ts)）：

```
决策优先级（从高到低）：
  1. 防御兜底 — 迭代/反射达上限，强制 CONTINUE
  2. REDO     — confidence < 0.55 | risk > 0.7 | issues >= 2
  3. INSERT_BEFORE — 缺少必要信息（如无止损/止盈）
  4. JUMP_TO  — 高置信(≥0.78) 且 无issues，跳过验证
  5. EARLY_TERMINATE — 基本完成且 avg_conf ≥ 0.65
  6. CONTINUE — 默认，正常推进
```

---

### 3.4 C层 — Chronicle（时间线/执行记录）

**定义**：实际执行的完整记录，时间序列格式。

**特点**：
- **完整详尽**：每步的完整输出、置信度、耗时、Token成本
- **决策透明**：记录每一个反思决策的原因和依据
- **可压缩**：通过图压缩算法，从C→A→B逐层压缩
- **可展开**：需要时从B→A→C逐层展开还原

**数据结构**（来源：[models.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/models.ts#L87-L115)）：
```typescript
interface CNode {
  id: NodeId;
  architectureNodeId: NodeId;  // 对应A层节点
  executionId: string;
  startTime: number;
  endTime?: number;
  metadata: NodeMetadata;
  inputs: Record<string, any>;
  outputs: Record<string, any>;
  logs: string[];
}

interface ChronicleGraph {
  id: string;
  architectureId: string;
  nodes: Map<NodeId, CNode>;
  edges: CEdge[];
  executionId: string;
  startedAt: number;
  completedAt?: number;
}
```

---

## 四、意图识别与链路规划（L1 注册表 + 路由器 + 置信度门控）

> **架构变更**：本章描述的分层路由逻辑由 L0/L1/L2 三层架构承接（见 §1.1 / §1.2）。旧「IntentGateway → ChainPlanner → B/A 图层规划」口径属于旧 SACG，已作废；本章按新口径重写。

### 4.1 分层路由总流程

```
用户请求
   │
   ▼
【路由器（意图识别系统）】
   ├─ 意图预测：L1 意图注册表（单一事实源）+ 关键词兜底
   ├─ 按层询问：L1.canHandle → L2.canHandle（L0 不直接对外路由）
   └─ 置信度门控：读取 L0 认知 C3/C4 产出的「用户问题 ↔ 认知库」匹配度信号
         ├─ 高置信（match≥0.7 且 density≥3）→ L1 直答（零 token 秒回）
         └─ 置信度不高 → 转 L2（token 成本，携带 l1_intent_hint 上下文）
```

**前后端分工**：前端只做展示与交互（消费 `handled` 字段）；后端负责意图预测、层能力判断与执行。

---

### 4.2 L1 意图注册表（单一事实源）

**定位**：L1 意图能力的**唯一注册表（单一事实源）**，路由器据此做 `canHandleL1` 判断。

**已落地 10 意图**（全部零 token）：

| 意图 | 说明 | 数据来源 |
|------|------|---------|
| `data_query` | 静态查询 | 18-数据获取中心 |
| `data_insight` | 单数据变化含义 | 9-基本面分析 |
| `contradiction_insight` | 多数据矛盾交汇 | 23-自进化/矛盾系统 |
| `path_insight` | 最小阻力路径 | 23-自进化/矛盾Transformer |
| `technical_analysis` | 技术指标推理 | 11-易经推理/BCRM2.0 |
| `fundamental_valuation` | 单币种估值 | 11-易经推理/BDSM |
| `asset_class_trend` | 跨资产趋势 | 11-易经推理/战略层 |
| `event_analysis` | 金融事件分析 | 29-事件驱动策略系统 |
| `risk_control` | 调控风控 | 16-调控系统 |
| `price_query` | 实时价格查询 | OKX 实时行情 API（降级回查 18 中心） |

**L1 候选扩展**（暂缓，仅记录；详见 `34-前端应用训练系统/SPEC-v1.3-L0L1L2-architecture.md`）：经典指标计算、趋势信号查询、风控状态查询、策略运行状态、监控告警查询、执行引擎状态、信号触发记录、REA 工程分析。

---

### 4.3 置信度门控（跨系统统一阈值契约）

**置信度定义**：指**「用户问题 ↔ 广义认知（记忆库）之间的匹配度 / 涉及度评分」**——即用户问题是否被认知库覆盖、覆盖程度如何。由认知系统 **C3 路由层**的匹配度评分 + **C4 元认知层**的预测误差门控（FOK/JOL）共同产出，**全程无需大模型**。

**跨系统统一阈值（禁止第二套）**：

| 参数 | 值 | 含义 |
|------|----|------|
| `THRESHOLD_HIGH` | 0.7 | `route_confidence ≥ 0.7` → L1 直答；`< 0.7` → 转 L2 |
| `CASE_DENSITY_MIN` | 3 | `case_density < 3` 时即使 match 高也不得直落 L1 |
| `PREDICTION_ERROR_MAX` | 0.3 | C4 预测误差超此值降权 0.3 |
| `FAST_PATH` | `match≥0.8 且 density≥5` | 快路径直落 L1 |
| `Tier1` | `match≥0.7 且 density≥3` | 一级门限 |
| `route_confidence` | `match_score − 0.3（若 prediction_error>0.3）− 0.2（若 case_density<3）` | 综合路由置信度 |

**职责边界**：门控**产出于 L0（认知系统 C3/C4）**，**判决归路由器**——L0 提供置信度**信号**，路由器据此**决策**。

**降级默认 FAIL-OPEN**：认知系统不可用 → 退回注册表侧静态置信度。

**对接细则**：见 `35-广义认知系统协作模块/SPEC-CDrive-CognitiveSystem-Integration.md` §7（复用 §2.2.1 `evaluate_match` = C3、§2.4.1 `jev_gate` = C4 的同一套零 token 确定性机制，仅下游消费方不同）。

---

### 4.4 L1 → L2 交接协议

L1 返回 `handled=false` 时，请求携带 **`l1_intent_hint`**（L1 已算出的意图预测结果）进入 L2 的 S 层（新 SACG），避免 L2 从零理解问法；C-drive 接管后按 S→A→C→G 编排（见 §1.2）。

---

## 五、SKILL模块化能力库（血肉层）

### 5.1 技能分类体系

所有技能都有**统一契约**：输入 → 处理 → 输出 + 置信度评分 + 成本 + 延迟。

```
┌─────────────────────────────────────────────────────────────┐
│                    SKILL 能力库                                │
├──────────────┬──────────────┬──────────────┬────────────────┤
│   A系列       │   C系列       │   F系列       │   G系列        │
│ (S链技能)     │ (C链技能)     │ (F链技能)     │ (治理支持)    │
└──────────────┴──────────────┴──────────────┴────────────────┘
```

**统一契约**（SkillCapability 接口）：
- 元信息：id、name、description、chain、category、tags
- 成本预估：estimatedTokens、estimatedLatencyMs
- 能力范围：applicableIntents、applicableStages、marketConditions
- 质量指标：confidenceRange、historicalAccuracy
- 输入输出：inputSchema、outputSchema
- 执行方法：execute(inputs, context) → SkillResult

---

### 5.2 A系列技能（S链 — AI交易技能）

对应 **S链** 的主要实现模块：

| 分类 | 代表SKILL | 对应S链阶段 | 说明 | 状态 |
|------|----------|------------|------|------|
| **三屏交易** | dream-screen1-first | S1+S2 | 第一屏：周线战略方向 | 🟢 |
| | dream-screen2-second | S2+S3 | 第二屏：日线战术预设 | 🟢 |
| | dream-screen3-third | S4+S5 | 第三屏：实时执行监控 | 🟢 |
| **执行闭环** | dream-strategy-parser | S3 | 策略解析器 | 🟢 |
| | dream-signal-scoring-spec | S3 | 信号评分 | 🟢 |
| | dream-regime-detector | S2 | Regime识别 | 🟢 |
| | dream-risk-position-sizing | S3 | 风险仓位管理 | 🟢 |
| | dream-pretrade-gatekeeper | S4/S5 | 交易前门禁 | 🟢 |
| | dream-tactical-validator | S4 | 战术验证 | 🟢 |
| | dream-tactical-executor | S5 | 战术执行 | 🟢 |
| | dream-exit-skill-v2 | S5/A9 | 离场决策 | 🟢 |
| **情报闭环** | dream-intelligence-monitor | 并行 | 情报监控 | 🟡 |
| | master-seminar | S2/A3 | 大师研讨 | 🟢 |
| | dream-oneirology | 并行 | 做梦部 | 🟡 |
| **治理闭环** | ai-trading-compliance | 约束 | 交易合规 | 🟡 |
| | dream-cost-control | 约束 | 成本控制 | 🟡 |
| | dream-performance-review | 约束 | 绩效复盘 | 🟡 |
| | dual-agent-conflict-gate | 约束 | 双Agent冲突门 | 🟡 |
| **研究工具** | dream-contradiction-theory | S2 | 矛盾论分析 | 🟢 |
| | dream-first-principles | S2 | 第一性原理 | 🟢 |
| | dream-strategy-research | S1 | 策略调研 | 🟢 |
| | dream-strategy-designer | S3 | 策略设计 | 🟢 |
| | dream-data-analysis | S1/S2 | 数据分析 | 🟢 |
| | dream-backtest | S4 | 回测引擎 | 🟡 |
| | dream-bayesian-opt | S4 | 贝叶斯优化 | 🟡 |

---

### 5.3 C系列技能（C链 — 经典量化模块）

对应 **C链** 的实现模块：

| 分类 | 代表模块 | 对应C链阶段 | 说明 | 状态 |
|------|---------|------------|------|------|
| **指标库** | classic-indicator-scan | C1 | RSI/MACD/MA/Bollinger等 | 🟢 |
| **Regime识别** | classic-regime-detection | C2 | 趋势/震荡/波动率识别 | 🟢 |
| **策略库** | 经典10策略 | C3 | 经典策略模板 | 🟡 |
| | freqtrade策略 | C3 | Freqtrade生态 | 🟡 |
| **回测引擎** | 经典回测系统 | C4 | 历史数据回测 | 🟡 |
| | Gate评估 | C4 | Gate指标评估 | 🟡 |
| **参数优化** | 贝叶斯优化 | C5 | Bayesian Optimization | 🟡 |
| **执行引擎** | Freqtrade | S5/C5 | Freqtrade执行 | 🔴 |
| | OKX条件单 | S5/C5 | OKX算法订单 | 🔴 |

**接入方式**：通过 HTTP API 调用经典指标系统（`http://127.0.0.1:8092`）

---

### 5.4 F系列技能（F链 — 基本面工具）

对应 **F链** 的实现模块：

| 分类 | 代表模块 | 对应F链阶段 | 说明 | 状态 |
|------|---------|------------|------|------|
| **新闻聚合** | Tavily搜索 | F1 | 通用搜索 | 🟢 |
| | 新闻日历 | F1 | 事件日历 | 🟡 |
| **资金流向** | 资金费率分析 | F2 | 合约资金费率 | 🟡 |
| | 交易所余额追踪 | F2 | 交易所充提 | 🟡 |
| | 鲸鱼地址追踪 | F2 | 大额转账监控 | 🔴 |
| **情绪分析** | 恐惧贪婪指数 | F3 | 市场情绪 | 🟡 |
| | 社交情绪分析 | F3 | Twitter/Reddit | 🔴 |
| | 多空比 | F3 | 合约多空比 | 🟡 |
| **链上指标** | MVRV/Z-Score | F4 | 市值/已实现价值 | 🟡 |
| | NUPL | F4 | 未实现利润/亏损 | 🟡 |
| | SOPR | F4 | 支出产出利润率 | 🔴 |
| | UTXO年龄分布 | F4 | UTXO分析 | 🔴 |
| **宏观数据** | 美联储政策 | F5 | 利率/点阵图 | 🟡 |
| | 美元指数DXY | F5 | 美元走势 | 🟡 |
| | 国债收益率 | F5 | 美债收益率 | 🟡 |
| | 宏观经济数据 | F5 | CPI/非农等 | 🟡 |

---

### 5.5 G系列技能（治理与支持）

| 分类 | 代表SKILL | 说明 | 状态 |
|------|----------|------|------|
| **宪法层** | dream-constitution | 系统最高指导原则 | 🟢 |
| **治理管理** | dream-governance-manager | 治理流程执行 | 🟡 |
| **门禁** | A7-practice-theory | 实践论门禁 | 🟡 |
| | A8-theory-practice-verification | 知行合一验证 | 🟡 |
| **审计复盘** | learning-episode-writer | 学习记录写入 | 🟡 |
| | learning-lesson-distiller | 经验教训提炼 | 🟡 |
| **运营支持** | dream-operation-director | 运营总监 | 🟡 |
| | auto-repair | 自动修复 | 🟡 |
| | resource-efficiency-analyst | 资源效率分析 | 🟡 |

---

## 六、动态执行引擎（灵魂层）

### 6.1 主循环

**位置**：
- 后端完整实现：[planner.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/planner.ts)
- 前端展示版：[runner.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/dynamic-chain/runner.ts)

```
┌─────────────────────────────────────────────────────────────┐
│                    动态链执行主循环                            │
│                                                             │
│  generateInitialPlan    — ChainPlanner生成初始计划（A阶段）    │
│           │                                                 │
│           ▼                                                 │
│  executeStepPlan        — 执行当前步骤                       │
│           │                                                 │
│           ▼                                                 │
│  reflect                — 反思评估（置信度/风险/问题）        │
│           │                                                 │
│      ┌────┴────┐                                            │
│      ▼         ▼                                            │
│   调整?      继续?                                           │
│      │         │                                            │
│      └────┬────┘                                            │
│           │                                                 │
│           ▼                                                 │
│  下一步 / 重做 / 跳转 / 插入 / 终止                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 6.2 技能选择器（SkillSelector）

在每个思维步骤内，AI动态决定调用什么技能组合：

```
Step N 执行流程：
  1. 明确本步核心问题
  2. 从SKILL注册表检索相关技能（按类别/阶段/市场条件过滤）
  3. 评估技能适用性（成本/延迟/历史表现）
  4. 选择技能组合（可并行、可串行）
  5. 执行技能
  6. 汇总产出
  7. 评估置信度
  8. 写入图架构（更新 BAC 的 A层 Architecture / C层 Chronicle）
```

**位置**：[skill-selector.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/skill-selector.ts)

---

### 6.3 置信度评估器

每个步骤执行后必须评估置信度：

| 评估维度 | 权重 | 说明 |
|---------|------|------|
| 逻辑一致性 | 30% | 论证是否自洽，有无矛盾 |
| 数据支撑 | 25% | 是否有足够数据/证据支撑 |
| 技能输出质量 | 20% | 技能本身的输出质量评分 |
| 多源印证 | 15% | 是否有多个独立来源印证 |
| 风险识别充分性 | 10% | 是否充分识别了风险 |

置信度三档：
- **高置信 (≥ 0.78)**：可跳过验证，直接推进
- **中置信 (0.55 - 0.78)**：正常推进，或追加1次迭代
- **低置信 (< 0.55)**：重做当前步骤，或降级处理

---

### 6.4 交叉验证器（阶段一：投票）

**位置**：[cross-validator.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/cross-validator.ts)

在关键节点（S1/S2/S3/S4/S5）触发三链投票：

```
执行到交叉验证点
    │
    ▼
收集参与链的信号（A/C/F）
    │
    ▼
投票计算器计算共识
    │
    ├─ 三链一致 → 高置信 → 推进
    │
    ├─ 两链一致 → 正常置信 → 推进
    │
    └─ 三链分歧 → 低置信 → 触发阶段二（动态插入）
```

---

## 七、记忆与自我进化系统（动力引擎）

> **核心定位**：驱动系统自动进化的引擎。通过发现问题→学习记录→深度分析→能力更新的闭环，
> 持续优化记忆系统、知识库和索引系统，实现底层基础能力的自动进化。
>
> **关键角色**：治理闭环（A7/A8）+ 做梦系统（Oneirology）+ 学习闭环（Episode→Lesson）
>
> **认知系统分层（C1-C4）**：广义认知系统（`35-广义认知系统协作模块` SSoT + `4-MEMORY` 实现）内部四层为 **C1 基础层（五系统闭环）/ C2 记忆层（三层记忆 + ACT-R + Evidence Ledger）/ C3 路由层（Intent-Engine + 匹配度评分）/ C4 元认知层（GWT + HOT + 预测误差门控 FOK/JOL）**。注意 C1-C4 与 L0/L1/L2 **不同号语境**，也与交易矛盾维度 C1-C8 **不同号**（详见 §1.2）。

### 7.1 进化闭环总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    自我进化闭环（Self-Evolution Loop）                    │
│                                                                         │
│  🔍 发现问题                                                             │
│   ↑                                                                     │
│   │  触发源：                                                           │
│   │    • 执行失败 / 亏损交易                                             │
│   │    • 置信度过低 / 三链分歧                                           │
│   │    • 用户反馈 / 纠错                                                 │
│   │    • 风控触发 / 门禁拦截                                             │
│   │    • 连续SKIP（梦游惯性）                                           │
│   │                                                                     │
│   ▼                                                                     │
│  📝 学习记录                                                             │
│   ↑   Episode Writer（事实层）                                           │
│   │     → 每轮决策完整记录（含skip）                                     │
│   │     → 评分/门禁/执行/结果/证据引用                                   │
│   │                                                                     │
│   │   Lesson Distiller（规律层）                                         │
│   │     → 从Episode中提炼可复用规律                                      │
│   │     → 失败规律(F_) + 成功规律(S_)                                   │
│   │     → 防噪声过拟合（频率/严重度/唯一性阈值）                         │
│   │                                                                     │
│   ▼                                                                     │
│  🌙 深度分析                                                             │
│   ↑   做梦部（Oneirology）                                               │
│   │     → 潜意识分析 / 被压制判断                                        │
│   │     → 反事实推演 / 四象限情景预言                                    │
│   │     → 凝缩/移置/象征/投射 五种梦工作机制                              │
│   │                                                                     │
│   │   治理闭环                                                           │
│   │     → A7实践论：实践→认识→再实践 的认识循环                          │
│   │     → A8知行合一：纯粹理性内部批评自循环                              │
│   │                                                                     │
│   ▼                                                                     │
│  🔧 能力更新                                                             │
│       → 联网补充（Tavily等）—— 现有技能不足时扩展                         │
│       → 记忆系统更新 —— 意图记忆 / 用户偏好 / 经验模式                    │
│       → 知识库更新 —— 新策略 / 新方法论 / 新理论                          │
│       → 索引系统更新 —— 保持导航准确、跨域映射完整                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 7.2 三大基础能力

#### 7.2.1 📚 知识库（Knowledge Base）

**位置**：[2-KNOWLEDGE/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/)

**三层架构**：

| 层级 | 名称 | 目录 | 内容 | 状态 |
|------|------|------|------|------|
| L1 | 元知识层 | 0-SCHEMA/ | 使用指南、跨域映射、质量标准 | 🟢 |
| L2 | 过程知识层 | 5-METHODOLOGY/ | 三链方法论(D/Z/E)、知识库管理框架 | 🟢 |
| L3 | 领域知识层 | 1-TRADING/ | 交易领域：三屏架构、马丁基线、信号体系、风控 | 🟢 |
| | | 2-TECHNICAL/ | 技术运维：Hermes架构、Cron调度、飞书集成 | 🟢 |
| | | 3-THEORY/ | 哲学理论：第一性原理、矛盾分析法、大师谱系 | 🟢 |
| | | 4-OPERATIONS/ | 运营治理：索引体系、OKR、门禁、审批 | 🟢 |

**知识生命周期**：
```
创建 → 审核 → 发布 → 更新 → 归档 → 淘汰
```

**RAG检索系统**：
- 向量化：DeepSeek Embeddings API
- 混合检索：向量相似度 + 关键词命中加权
- 向量缓存：JSON文件持久化，避免重复向量化
- 优雅降级：embedding失败时用字符n-gram fallback

**对应SKILL**：`dream-knowledge`（知识沉淀→评估→检索→进化闭环）

---

#### 7.2.2 🧠 记忆系统（Memory System）

**三类记忆**：

| 记忆类型 | 说明 | 存储位置 | 状态 |
|---------|------|---------|------|
| **意图记忆** | 意图识别经验（用户通常问什么） | `intent-memory/records.json` | 🟢 |
| **用户偏好记忆** | 用户个人偏好（风险承受/响应风格等） | `user-preference-memory.ts` | 🟢 |
| **经验模式记忆** | 提炼的经验教训（Lesson） | `weekly-lessons.json` | 🟡 |

**意图记忆（Intent Memory Bank）**：
- 记录每次意图识别结果 + 用户反馈
- 统计分析：准确率、混淆矩阵、方法分布、趋势
- 模式发现：LLM识别到但规则未匹配的高频模式
- 置信度自动调整：基于反馈优化experience-memory.json
- RingBuffer：1000条环形缓冲

**用户偏好记忆（User Preference Memory）**：
- Hermes风格设计：有限容量约束（最多50条）
- 优先级驱动淘汰：低重要性/过时记忆自动被淘汰
- 记忆进化：相似记忆合并强化，冗余记忆被清除
- 强制更新：用户反馈驱动记忆即时更新
- 记忆类型：响应风格、风险承受、常分析品种、结论偏好等

---

#### 7.2.3 📇 索引系统（Index System）

**位置**：[2-KNOWLEDGE/4-OPERATIONS/索引体系.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/4-OPERATIONS/索引体系.md)

**Z轴三级索引架构**：

```
Z轴索引体系
┌───────────────────┐
│ L1：系统主索引     │  → SYSTEM_INDEX.md（全局导航入口）
├───────────────────┤
│ L2：目录级INDEX   │  → 每个子系统/域的 INDEX.md
├───────────────────┤
│ L3：文件内锚点    │  → 每个知识文件的内部章节/TOC
└───────────────────┘
```

**每日审计（index-ops）**：
- cron任务每日23:00运行
- 扫描项目物理目录结构
- 计算覆盖率 + 健康度评分（A/B/C/D四级）
- 生成优化建议（新目录无索引→建议创建、索引陈旧→建议更新）
- 飞书Base同步差异

**健康度评分标准**：
| 等级 | 条件 |
|:---:|:---|
| A | 有独立INDEX + 有README + 子目录全覆盖 |
| B | 有INDEX或README |
| C | 有索引但内容陈旧/不完整 |
| D | 无任何索引 |

---

### 7.3 学习闭环（事实→规律）

#### 7.3.1 Episode Writer（学习记录器）

**SKILL**：`learning-episode-writer`

**职责**：将每轮决策与结果固化为episode，作为学习闭环的事实底座。

**记录原则**：
- 无论开仓、平仓、还是 **skip 都必须写入**
- 每个episode必须有完整的证据链（evidence_refs）
- 缺关键字段也写入，但标注为`INCOMPLETE`（fail-closed原则）

**Episode结构**：
```
episode {
  decision_audit: trace_id / ts / inst_id / action / strategy_id
  scoring: 维度分 / 理由码 / 冲突点
  gate: PASS/SKIP / reason_codes / 数据完整性
  execution: 订单参数 / 成交回报 / 滑点
  outcome: PnL / 最大回撤 / 触发原因
  evidence_refs[]: 市场快照 / 工件路径 / 审计记录
  skip_tracking: consecutive_skip_count / sleepwalk_alert
}
```

**梦游惯性检测**：
- 连续SKIP ≥ 7次 → 触发梦游惯性告警
- 自动生成复盘提案，强制review

---

#### 7.3.2 Lesson Distiller（经验提炼器）

**SKILL**：`learning-lesson-distiller`

**职责**：从L1事实（单次episode）提炼为L2规律（可复用的经验法则）。

**防噪声过拟合**：
- 最小频率：3次以上重复出现
- 最小严重度：2级以上影响
- 最小唯一轨迹：至少2个不同的trace_id
- 冷却期：10个episode内不重复触发相同lesson

**Lesson分类**：

| 前缀 | 类型 | 示例 |
|------|------|------|
| `F_` | 失败规律 | F_SHORT_SQUEEZE_UNDERWEIGHTED（资金费率极值风险评估不足） |
| `S_` | 成功规律 | S_BOUNCE_ENTRY_BETTER_RR（反弹入场RR优于追入） |

**输出**：weekly-lessons.json（新增/更新/废弃的lesson delta）

---

### 7.4 深度分析层（做梦部 + 治理闭环）

#### 7.4.1 🌙 做梦部（Oneirology）

**SKILL**：`dream-oneirology`

**定位**：系统的"第三只眼"——所有清醒部门不敢说的，让梦来说。

**理论基础**：弗洛伊德《梦的解析》五大机制

| 梦工作机制 | 原意 | 系统映射 | 检测方法 |
|-----------|------|---------|---------|
| **凝缩** | 多意念压缩为一 | 6维→1维丢失张力 | 维度间分歧>3分时触发 |
| **移置** | 情感转移至无关对象 | 恐惧被移置为"流动性不足" | 连续引用同一原因3+次 |
| **象征** | 抽象以具体形象呈现 | FGI/ETF作为象征代替本质 | 指标与价格背离时触发 |
| **二次修正** | 碎片编织为"合理"叙事 | Episode事后归因编织因果 | 检查归因一致性 |
| **投射** | 内在冲突投射到外部 | "市场在等催化剂"=系统无信念 | 外部归因>80%时触发 |

**四大功能模块**：
1. **梦境解析器**：分析episode中的"潜在内容"（显性→潜在映射）
2. **潜意识探测器**：提取系统"想说但没说"的判断（门禁拦截的决策、被压制维度）
3. **强迫性重复检测**：连续3+次SKIP且引用相同原因 = 创伤信号
4. **四象限情景预言**：乐观/中性/悲观/被忽视 四情景矩阵（被忽视情景强制20%权重）

**触发方式**：每日17:00定时运行 + 异常事件触发

---

#### 7.4.2 📘 A7 实践论

**SKILL**：`A7-practice-theory`

**定位**：基于毛泽东《实践论》的交易实践指导框架，建立"实践→认识→实践"的完整闭环。

**认识过程的两个飞跃**：
1. **从感性认识到理性认识**（从现象到本质）
2. **从理性认识到革命实践**（从理论到行动）

**实践→认识→再实践→再认识**，循环往复以至无穷。

**问题处理四级流程**：
```
遇到问题
    ↓
Step 1 查FAQ → 有解→执行
    ↓ 无解
Step 2 查治理文档 → 有解→执行+补充FAQ
    ↓ 无解
Step 3 联网搜索 → 有解→执行+归档经验
    ↓ 无解
Step 4 自主分析 → 有解→执行+输出报告+归档
```

---

#### 7.4.3 🔍 A8 知行合一验证

**SKILL**：`A8-theory-practice-verification`

**定位**：纯粹的理性内部批评自循环。检查A0-A7的理论与实践结合情况，做到"知行合一"。

**核心原则**：不嵌入执行流，通过完善A0/A7来间接推动系统进化。

```
执行体系（直接影响交易）:
A1-A3（认识）→ A4-A5（实践）→ A6（监控）
    ↑  A0指导            ↑  A7指导

理论研究闭环（A8纯粹内部自循环）:
A8（独立内部批评）→ 自我检验 → 观察期验证 → 理论进化
     ↓                    ↑
     └─────────────────────┘
          完整自循环
```

**三大思维工具**：
1. **辩证思维**：矛盾分析法，抓主要矛盾和矛盾的主要方面
2. **系统思维**：整体观、动态观、层次观
3. **批判性思维**：质疑假设、验证证据、避免认知偏差

---

### 7.5 能力更新层

当通过学习和分析发现系统能力不足时，触发四步更新：

```
发现能力缺口
    │
    ▼
Step 1：联网补充 🔴 规划中
  • Tavily / agent-reach 搜索
  • 学术论文 / 行业报告 / 社区讨论
  • 验证有效性后纳入知识库
    │
    ▼
Step 2：记忆系统更新 🟡 部分实现
  • 意图记忆：新意图模式→更新experience-memory
  • 用户偏好：新偏好发现→更新user-preference
  • 经验模式：新Lesson→更新lessons库
    │
    ▼
Step 3：知识库更新 🟢 已实现
  • 新知识写入对应领域目录（1-TRADING/ 等）
  • 标注来源Skill和更新日期
  • 更新对应INDEX.md
  • 重建向量缓存（RAG检索更新）
    │
    ▼
Step 4：索引系统更新 🟢 已实现
  • 更新L2目录级INDEX
  • 触发index-ops审计
  • 同步飞书Base
  • 健康度重新评分
```

---

### 7.6 进化系统中的三链与治理闭环

| 层级 | 角色 | 对应模块 |
|------|------|---------|
| **S链（主链）** | 执行主体 | S1-S5产生决策和执行记录（Episode） |
| **治理闭环** | 约束+进化 | A7实践论 + A8知行合一 = 理论与实践双向校准 |
| **做梦系统** | 第三视角 | 发现被压制的判断、强迫性重复、潜意识信号 |
| **学习闭环** | 事实底座 | Episode记录 → Lesson提炼 → 规律沉淀 |

**进化动力示意**：
```
S链执行产生数据
    │
    ▼
Episode（事实层）← 学习闭环
    │
    ├──→ 治理闭环（A7/A8）── 理论进化 ──→ 指导S链
    │
    └──→ 做梦部（Oneirology）── 潜意识发现 ──→ 补充盲区
    │
    ▼
Lesson（规律层）
    │
    ▼
记忆 + 知识库 + 索引（能力进化）
    │
    ▼
反馈到 ChainPlanner / IntentGateway / S链执行
→ 更高的准确率 / 更好的置信度 / 更优的路径选择
```

---

## 八、DZE 开发链（代码落地）

> **定位**：系统进化的最终落地产物。当记忆进化系统提出优化项后，通过 DZE 三链开发架构，
> 将进化需求转化为实际的代码实现，完成从"知道怎么改进"到"代码已经改进"的闭环。
>
> **借鉴来源**：A系列（矛盾论/三均准/推演验证）的系统化方法论，适配开发场景
> **核心机制**：多Agent接力 + 人工门禁 + 物理约束 = 防止跳步

### 8.1 DZE 三链总览

```
    进化需求（来自 Lesson / A8知行合一 / 用户反馈）
        │
    ┌───┴──────┐
    │ 链路1    │  调研分析 → 方案推荐 → 用户选择方案
    │ D系列    │
    │ （调研） │  D1 深度调研 → D2 分析诊断 → D3 推演验证 → D4 Spec合成
    └───┬──────┘
        │ 门禁1: 用户批准 Spec
    ┌───┴──────┐
    │ 链路2    │  实施规划 → 路径设计 → 用户确认计划
    │ Z系列    │
    │ （规划） │  Z1 代码扫描 → Z2 范围划分 → Z3 路径设计 → Z4 验收方案
    └───┬──────┘
        │ 门禁2: 用户批准实施计划
    ┌───┴──────┐
    │ 链路3    │  逐任务执行 → 验收 → 交付
    │ E系列    │
    │ （执行） │  E1 任务执行 → E2 测试验证 → E3 部署交付
    └───┬──────┘
        │ 用户验收
        ▼
    代码落地完成 → 知识库更新 → 记忆系统更新 → 索引更新
```

**位置**：[3-CHAIN-DEVELOPMENT/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-CHAIN-DEVELOPMENT/)

---

### 8.2 D系列 — 调研分析链

**目标**：搞清楚"问题是什么"、"为什么会这样"、"有哪些方案"，输出 Spec。

| 阶段 | 名称 | 角色 | 核心产出 | 工具权限 | 状态 |
|------|------|------|---------|---------|------|
| **D1** | 深度调研 | 研究员 | 现状调研报告 | 只读（read/search） | 🟢 |
| **D2** | 分析诊断 | 分析师 | 根因分析 + 矛盾识别 | 只读 | 🟢 |
| **D3** | 推演验证 | 推演师 | 多方案对比（A/B/C） | 只读 + 写md | 🟢 |
| **D4** | Spec合成 | 作者 | 最终需求规格说明书 | 只读 + 写md | 🟢 |

**矛盾论贯穿始终**：
- D1 调查矛盾：代码里的"表面正常但实则有问题"的设计矛盾
- D2 分析矛盾：约束条件之间的首对矛盾（快 vs 好，成本 vs 质量）
- D3 推演矛盾：每套方案内在的权衡（理想 vs 可行）
- D4 化解矛盾：Spec中选择的方案如何统一矛盾

---

### 8.3 Z系列 — 实施规划链

**目标**：搞清楚"怎么改"、"改哪些"、"怎么验证没改坏"，输出实施计划。

| 阶段 | 名称 | 角色 | 核心产出 | 工具权限 | 状态 |
|------|------|------|---------|---------|------|
| **Z1** | 代码扫描 | 架构师 | 代码结构全景图 | 只读 | 🟢 |
| **Z2** | 范围划分 | 规划师 | 改动范围 + 影响面评估 | 只读 + 写md | 🟢 |
| **Z3** | 路径设计 | 路径师 | 实施步骤 + 回滚方案 | 只读 + 写md | 🟢 |
| **Z4** | 验收方案 | 质检师 | 验收标准 + 测试用例 | 只读 + 写md | 🟢 |

---

### 8.4 E系列 — 执行落地链

**目标**：按计划执行代码修改，测试验证，部署交付。

| 阶段 | 名称 | 角色 | 核心产出 | 工具权限 | 状态 |
|------|------|------|---------|---------|------|
| **E1** | 任务执行 | 工程师 | 修改后的代码 | 全工具 | 🟢 |
| **E2** | 测试验证 | 测试员 | 测试报告 | 全工具 | 🟢 |
| **E3** | 部署交付 | 运维 | 部署完成 + 交付文档 | 全工具 | 🟡 |

**前端集成**：
- S5_EXECUTE 内部集成 E 链（策略代码开发场景）
- 位置：[dev-chain/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/dev-chain/)
- 控制器：[chain-controller.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/dev-chain/chain-controller.ts)

---

### 8.5 三链接力协议（防跳步约束）

**位置**：[3-CHAIN-DEVELOPMENT/4-PROTOCOL/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-CHAIN-DEVELOPMENT/4-PROTOCOL/)

**核心思想**：不是"写更多文档教AI怎么做"，而是**提供物理约束**——让AI读状态文件来判断当前该做什么，不能让AI自己决定。

#### 门禁系统（chain_guard.py）

**位置**：[scripts/chain_guard.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-CHAIN-DEVELOPMENT/scripts/chain_guard.py)

| 跳转类型 | 规则 | 示例 |
|:---|:---|---:|
| 同链顺序 | ✅ 允许 | `d1→d2`, `z2→z3`, `e1→e2` |
| 同链跳步 | ❌ 拒绝 | `d1→d3`（须 override） |
| 跨链跨步 | ❌ 拒绝 | `d3→z1`, `z2→e1` |
| 跨链接力点 | ✅ 允许 | `d4→z1`, `z4→e1` |
| 用户跳过 | 🔄 override 记录理由 | `override d1 d3 "调研已有机"` |

#### 状态文件（chain_state.json）

```json
{
  "scope": "任务描述",
  "created_at": "ISO时间戳",
  "modified_at": "ISO时间戳",
  "current_phase": "d2",
  "phases": {
    "d1": { "status": "completed", "approved": true, "completed_at": "..." },
    "d2": { "status": "active", "started_at": "..." },
    "d3": { "status": "pending" }
  },
  "overrides": [
    { "from": "d1", "to": "d3", "reason": "调研已足够", "at": "..." }
  ]
}
```

#### CLI 命令

| 命令 | 用途 | 示例 |
|:---|:---|---:|
| `init "描述"` | 初始化新任务 | `init "优化权重中心化接口"` |
| `status` | 查看完整状态 | `status` |
| `check <从> <到>` | 检查跳转合法性 | `check d2 d3` |
| `transition <从> <到>` | 执行合法跳转 | `transition d2 d3` |
| `override <从> <到> <理由>` | 用户指定跳过 | `override d1 d3 "调研已足够"` |
| `approve <阶段>` | 标记已批准 | `approve d1` |
| `start <阶段>` | 标记进行中 | `start e1` |

---

### 8.6 场景匹配（用哪条链）

| 场景规模 | 走什么链路 | 说明 |
|:---|:---|---|
| **极小改动**（<10行，改配置/修单词） | 直接改，不走任何链 | 改完告知 |
| **简单问题**（"这段代码有什么问题"） | 只调一个 Skill（如 D2-analyst） | 单问题走单Skill |
| **小任务**（"重构这段代码"，<100行） | 链路3 直接执行（E1→E2→E3） | 不需要调研/确认 |
| **中等需求**（"设计个新功能"，100-500行） | 完整三链接力 | D1→D2→D3→D4 → Z1→Z2→Z3→Z4 → E链 |
| **复杂需求**（"开发新模块"，>500行） | 完整三链接力 + 每个门禁确认 | 同上，人工确认更严格 |

> **关键原则**：行数是估算指标，不是硬性规则。关键是**影响面**——改一行配置影响全系统，应该走全链；改100行文档，直接改。

---

### 8.7 开发链在进化系统中的位置

```
进化触发源
  ├── 交易执行失败 / 低置信度
  ├── Lesson 提炼的规律
  ├── A8 知行合一发现的理论-实践差距
  ├── 用户反馈 / 纠错
  └── 做梦部发现的盲区
        │
        ▼
  【能力更新层】
    ├── 记忆系统更新
    ├── 知识库更新
    └── 索引系统更新
        │
        ├─ 仅知识层面进化（不需要改代码）
        │   → 完成，反馈到执行层
        │
        └─ 需要代码层面进化（新增功能/修复bug/优化性能）
            │
            ▼
      【DZE 开发链】
        D1 调研 → D2 分析 → D3 推演 → D4 Spec
              ↓ （门禁1）
        Z1 扫描 → Z2 范围 → Z3 路径 → Z4 验收
              ↓ （门禁2）
        E1 执行 → E2 测试 → E3 部署
              ↓
        代码落地完成
              │
              ▼
        知识库更新 + 记忆系统更新 + 索引更新
              │
              ▼
        反馈到 S链 / ChainPlanner / IntentGateway
        → 系统能力真正进化
```

---

## 九、开发协作网络（Dream-Agent）

> **定位**：大规模多Agent协作网络层。基于区块链思想设计，通过账本系统、Token激励、GitHub门禁、飞书审批，
> 实现多Agent高效协作，解决AI开发漂移、黑箱、不可回溯等问题，实现规模效应。
>
> **仓库位置**：`/Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/`
> **核心机制**：账本系统 + DREAM Token + 四大角色 + 双门禁（GitHub + 飞书）

### 9.1 与 DZE 开发链的关系

| 维度 | DZE 开发链 | Dream-Agent 协作网络 |
|------|-----------|---------------------|
| **层级** | 单任务执行层 | 多任务协作网络层 |
| **规模** | 单个任务内的方法论约束 | 多个Agent、多个任务的大规模协作 |
| **核心** | D调研/Z规划/E执行 三链接力 | 账本系统 + 激励机制 + 治理体系 |
| **防漂移** | 物理约束（chain_guard.py） | 契约+账本+评审 三重防漂移 |
| **适用场景** | 单个功能/模块开发 | 系统级迭代、多模块协同、多人协作 |

**协同关系**：
```
进化需求
    │
    ▼
Dream-Agent 协作网络
    │
    ├── 任务拆解（UI-Driven六步分解）
    ├── 任务入账（ledger/tasks）
    ├── Agent认领（Developer/Validator/Governance）
    └── 每个子任务 → 【DZE开发链】
              │
              D1调研 → D2分析 → D3推演 → D4 Spec
              ↓ 门禁1
              Z1扫描 → Z2范围 → Z3路径 → Z4验收
              ↓ 门禁2
              E1执行 → E2测试 → E3部署
              │
              ▼
         交付证明 + Validator评分
              │
              ▼
         Governance合入 + 发放DREAM奖励
              │
              ▼
         系统能力真正进化
```

---

### 9.2 四大角色与职责

| 角色 | 职责 | 对应人类角色 | 状态 |
|------|------|-------------|------|
| **Developer AGENT** | 认领任务，实现代码，提交交付证明 | 开发工程师 | 🟢 |
| **Validator AGENT** | 验收评分，保障质量，发布验证结果 | 测试/QA工程师 | 🟢 |
| **Governance AGENT** | 任务编排，合并管理，冲突处置，门禁执行 | 项目经理/Tech Lead | 🟢 |
| **Ledger AGENT** | 协议演进，账本维护，合约管理 | 架构师/产品经理 | 🟡 |

**核心原则**：权责分离，互相制衡。开发者不能自己验收，治理者不能自己开发。

---

### 9.3 账本系统（区块链思想）

**位置**：[DREAM-AGENT/ledger/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/ledger/)

三大账本：

| 账本 | 文件 | 作用 | 类比 |
|------|------|------|------|
| **任务账本** | `ledger/tasks/index.json` | 所有任务的总账，状态追踪 | 交易总账 |
| **奖励账本** | `ledger/rewards/index.json` | DREAM奖励分配记录 | 资产账本 |
| **区块账本** | `ledger/dream/blocks.json` | 已确认任务的区块记录 | 区块链 |

**三大约束**：
1. **所有正式任务必须先入账再执行**（不入账不算数）
2. **账本状态高于评论状态**（一切以账本为准）
3. **奖励结算必须由验证者AGENT触发**（防止自肥）

---

### 9.4 DREAM Token 激励机制

**设计文件**：[DREAM-TOKEN-DESIGN.md](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/DREAM-TOKEN-DESIGN.md)

**核心参数**：

| 参数 | 值 | 类比 |
|------|----|------|
| **总量** | 21,000,000 DREAM | 比特币总量2100万 |
| **最小单位** | 0.00000001 DREAM | 1 satoshi |
| **创世奖励** | 50 DREAM / 区块 | 比特币创世50 BTC |
| **区块间隔** | 10分钟 | 比特币10分钟 |
| **减半周期** | 每210,000区块（≈4年） | 比特币减半周期 |

**任务 = 区块**：
```
任务认领 (claimed)
    ↓
任务实现 (in_progress) ← "挖矿中"
    ↓
提交交付证明 DONE      ← "计算哈希"
    ↓
Validator 评分 ≥ 80   ← "难度校验通过"
    ↓
合入主干 (ledgered)    ← "区块确认"
    ↓
发放 DREAM 奖励        ← "coinbase 交易"
```

**区块确认条件**：
- 提交完整 DELIVERY_PROOF_HEADER（commit SHA + 父指针 + 文件列表 + Delivery-Hash）
- CI构建通过
- 测试全绿
- Validator评分 ≥ 80
- PR合入 main

---

### 9.5 UI-Driven 任务分解（防漂移）

**核心理念**：以终为始，从用户可见的功能边界（前端页面/模块）拆解，不是从技术边界（API/DB）拆解。

**六步分解法**：
```
1. 技术文档
   ↓  （业务目标、用户需求、非功能约束）
2. 工程架构图（目的驱动 + 数据流向）
   ↓  （前端用户看到什么 → 背后需要什么服务）
3. 前端页面定义（精确到组件级）
   ↓  （页面结构、组件层级、交互流程）
4. 模块联动模拟（定义模块间契约）
   ↓  （数据怎么流、状态怎么变、异常怎么处理）
5. 协作清单拆解（按模块分配Agent）
   ↓  （每个清单对应一个前端模块）
6. 验收标准（每个清单附带可验证标准）
```

**为什么能防漂移**：
- 每个AGENT的交付物对应一个明确的前端功能模块
- 验收标准可视化，不是模糊的"做完了"
- 模块间契约提前定义，不会出现"我以为你会做"的问题

---

### 9.6 Phase 0-8 标准生命周期

每个任务的标准执行流程：

| 阶段 | 名称 | 主责 | 关键产出 | 状态 |
|------|------|------|---------|------|
| Phase 0 | 任务登记 | Governance | 任务入账 + 分配 | 🟢 |
| Phase 1 | 方案评审 | Developer + Validator | 设计方案 + 评审意见 | 🟢 |
| Phase 2 | 实施计划 | Developer | 实施步骤 + 时间预估 | 🟢 |
| Phase 3 | 开工门禁 | Governance + dual-agent-conflict-gate | 门禁通过 | 🟢 |
| Phase 4 | 开发执行 | Developer | 代码实现 + 本地测试 | 🟢 |
| Phase 5 | 测试验证 | Validator | 测试报告 + 评分 | 🟢 |
| Phase 6 | PR评审 | Governance | Code Review | 🟡 |
| Phase 7 | 合入监督 | Governance | Merge + 账本更新 | 🟢 |
| Phase 8 | 完成归档 | Ledger | 奖励发放 + 经验沉淀 | 🟡 |

---

### 9.7 双门禁体系（GitHub + 飞书）

#### 9.7.1 GitHub Actions 门禁

**位置**：[github-actions/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/github-actions/)

**自动化门禁**：
- CI构建检查
- 测试覆盖率检查
- 代码规范检查
- 冲突门禁（dual-agent-conflict-gate）
- 交付证明完整性检查

#### 9.7.2 飞书审批（关键节点人工确认）

**文档入口**：[docs/feishu-collab/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/docs/feishu-collab/)

**关键审批节点**：

| 审批点 | 触发时机 | 审批人 | 作用 |
|--------|---------|--------|------|
| **方案审批** | Phase 1 完成后 | 人类/Tech Lead | 确认技术方案方向正确 |
| **开工审批** | Phase 3 门禁 | Governance + 人类 | 确认可以正式开工 |
| **风险审批** | 检测到高风险变更 | 人类 | 重大变更人工把关 |
| **合入审批** | Phase 7 合入前 | 人类 | 最终质量把关 |

**飞书能力**：
- 目标驱动进度监控
- 风险自动预警与审批
- 审批成功闭环（回读同步）
- 与GitHub Checks联动

---

### 9.8 防漂移三重保障

| 层级 | 机制 | 作用 |
|------|------|------|
| **第一层** | UI-Driven任务分解 | 从源头锚定交付边界，防止范围蔓延 |
| **第二层** | 模块契约定义 | 提前定义接口，防止"我以为你会做" |
| **第三层** | 账本+Validator | 交付有标准、有评分、有记录，可追溯 |

**对比传统AI开发的问题**：

| 问题 | 传统AI开发 | Dream-Agent 方案 |
|------|-----------|-----------------|
| **黑箱** | 不知道AI怎么做的 | 每步有产出、有记录、可审计 |
| **漂移** | 做着做着偏了 | UI-Driven锚定 + 模块契约约束 |
| **不可回溯** | 错了不知道错在哪 | 区块账本 + Phase记录 + 完整交付链 |
| **质量不可控** | AI说做完了就完了 | Validator独立验收 + 评分 |
| **规模效应差** | 单Agent能力上限 | 多Agent协作 + 激励机制 + 治理体系 |

---

### 9.9 完整自主迭代闭环

```
┌─────────────────────────────────────────────────────────────────┐
│                    系统运行（S链交易执行）                          │
│                    产生 Episode 记录                              │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                 学习与进化（记忆系统）                             │
│  Lesson提炼 → 做梦部分析 → A8知行合一 → 发现进化需求                │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│               开发协作网络（Dream-Agent）                        │
│                                                                 │
│  1. UI-Driven六步分解（任务拆解）                                │
│  2. 任务入账（ledger/tasks）                                    │
│  3. Agent认领（Developer + Validator）                           │
│  4. 每个子任务走DZE开发链                                        │
│  5. 【飞书审批】关键节点人工确认                                  │
│  6. Validator验收评分                                           │
│  7. 【GitHub门禁】自动化检查                                     │
│  8. Governance合入主干                                          │
│  9. 发放DREAM奖励 + 更新区块账本                                 │
│  10. 经验沉淀到知识库/记忆系统                                    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    系统能力升级                                    │
│  新SKILL / 优化ChainPlanner / 改进IntentGateway / 完善知识库       │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                回到系统运行（能力更强了）                           │
└─────────────────────────────────────────────────────────────────┘
```

**关键特性**：
1. **全自动发现问题**：学习闭环 + 做梦部 + A8知行合一
2. **全自动拆解任务**：UI-Driven六步分解
3. **全自动执行开发**：DZE三链 + 多Agent协作
4. **关键人工把关**：飞书审批 + GitHub门禁
5. **全自动激励结算**：DREAM Token + 账本系统
6. **全自动经验沉淀**：知识库 + 记忆系统 + 索引更新

> **最终形态**：关键问题飞书审批，其余自主迭代 — 人机协作的新时代

---

## 十、完整运行流程（端到端）

### 10.1 复杂问题处理流程

以用户问 "BTC现在适合开多吗？给我一个完整的交易策略" 为例（本例采纳 **BAC（B/A/C 三层）** 视角；其中「IntentGateway / ChainPlanner / 推荐主链」为旧 SACG 命名，在新架构下对应 **L1 路由器（意图预测）+ L2 S 层（认知规划）**，见 §1.2 与第四章；阶段 3-5 的 B/A/C 层为第三章 BAC 模型的层，**不是新 SACG 的 A/C 层**）：

```
【前端】用户输入
    │
    ├───────────────────────────────────────────┐
    │                                           ▼
    │                              【后端】阶段0：接收请求
    │                                   │
    │                                   ▼
    │                              【后端】阶段1：意图识别
    │                              (IntentGateway — 零Token)
    │                                • 识别意图：deep_analysis / execute_trade
    │                                • 置信度：0.72
    │                                • 推荐主链：S链
    │                                • 扩展池：[C2_Regime, F2_资金流, F3_情绪]
    │                                • 上下文：{ BTC, 当前价格, RSI, 资金费率 }
    │                                   │
    │                                   ▼
    │                              【后端】阶段2：链路规划
    │                              (ChainPlanner — 零Token)
    │                              【A阶段规划 — 构建初始执行图】
    │                                四维规划：
    │                                • 预算：6000 Token → 保留高价值节点
    │                                • 知识库：当前震荡市无高分策略
    │                                • 历史表现：震荡市下A3大师研讨命中率高
    │                                • 标的覆盖：BTC流动性充足，全节点可用
    │                                输出：S1→S2→(C2交叉)→S3→S4→S5
    │                                      + 规划理由
    │                                   │
    │                                   ▼
    │                              【后端】阶段3：构建B层蓝图
    │                              (Graph Builder — 零Token)
    │                                Blueprint架构图：
    │                                  bp_root (交易决策)
    │                                  ├── research (调研模块)  → S1
    │                                  ├── analysis (分析模块)  → S2, C2
    │                                  ├── design (设计模块)    → S3
    │                                  ├── validate (验证模块)  → S4
    │                                  └── execute (执行模块)   → S5
    │                                   │
    ◀────────── 开始流式返回 ──────────────┤
    │                                   │
    │                                   ▼
    │                              【后端】阶段4：执行图动态展开（BAC A层）
    │                              (Dynamic Chain — B不变，A可变)
    │                                │
    │                                ├─ S1_市场调研
    │                                │   ├─ 调用：dream-strategy-research
    │                                │   ├─ 产出：市场调研报告
    │                                │   └─ 置信度：0.71 → 正常推进
    │                                │
    │                                ├─ S2_深度分析
    │                                │   ├─ 调用：dream-contradiction-theory
    │                                │   ├─ 产出：矛盾分析
    │                                │   └─ 置信度：0.68 → 中置信
    │                                │
    │                                ├─ 【交叉验证点】阶段一：投票
    │                                │   ├─ 收集：A链 + C2
    │                                │   ├─ 两链一致 → 正常置信
    │                                │   └─ 但分歧较大 → 触发阶段二
    │                                │
    │                                ├─ 【阶段二：动态插入】INSERT_AFTER
    │                                │   ├─ 追加：master-seminar（A3大师研讨）
    │                                │   ├─ 从A系列技能注册表选择
    │                                │   ├─ 产出：大师评审意见
    │                                │   └─ 置信度：0.82 → 高置信
    │                                │
    │                                ├─ S3_策略设计（JUMP：简化S4验证）
    │                                │   ├─ 调用：dream-strategy-designer + 风控
    │                                │   ├─ 产出：交易策略方案 + 风险管理方案
    │                                │   └─ 置信度：0.79 → 高置信
    │                                │
    │                                ├─ S4_策略验证（简化版）
    │                                │   ├─ 调用：dream-backtest（快速回测）
    │                                │   ├─ 产出：回测摘要
    │                                │   └─ 置信度：0.76 → 通过
    │                                │
    │                                └─ S5_决策执行
    │                                    ├─ 调用：dream-pretrade-gatekeeper + executor
    │                                    ├─ 产出：执行方案 + 交易指令
    │                                    └─ 置信度：0.74 → 完成
    │                                   │
    ◀────────── 实时同步进度 ─────────────┤
    │                                   │
    │                                   ▼
    │                              【后端】阶段5：Chronicle 记录（BAC C层）
    │                              (Chronicle)
    │                                • 完整记录每步输出、置信度、耗时、Token
    │                                • 记录所有反思决策（为什么追加A3？为什么跳S4？）
    │                                • 生成执行轨迹图
    │                                   │
    │                                   ▼
    │                              【后端】阶段6：产物输出 + 沉淀
    │                                 • 交易策略方案（主产物）
    │                                 • 市场调研报告（中间产物）
    │                                 • 回测摘要（验证产物）
    │                                 • 执行轨迹图（可追溯）
    │                                 → 存入产物中台，归档到知识库
    │
【前端】展示完整结果 + 执行轨迹图
    │
    └──── 用户反馈（如有） ────→ 触发重规划 → 调整执行路径
```

---

## 十一、与传统模型的核心差异

| 维度 | 传统LLM | DreamBuddy v2 |
|------|---------|--------------|
| **思考模式** | 黑盒，端到端生成 | 三链骨架 + 模块化技能 + 动态调度 |
| **可追溯性** | 不可追溯，只有最终输出 | BAC三层图结构，每步可追溯 |
| **置信度** | 无，或仅主观"感觉" | 每步量化置信度，多维度评估 |
| **成本控制** | 无法预估，线性增长 | ChainPlanner四维预算规划 + 层级压缩 |
| **能力扩展** | 依赖模型能力上限 | SKILL注册表动态扩展，工具调用 |
| **多维度验证** | 单一视角（模型自身） | S/C/F三链交叉验证，两阶段策略 |
| **知识积累** | 上下文遗忘，无法沉淀 | 产物中台 + 知识库 + 经验教训提炼 |
| **风险意识** | 通用免责声明 | 专门治理层 + 门禁系统 + 风险量化 |
| **前后端分工** | 前端直接调LLM | 后端核心执行 + 前端展示交互 + 双向反馈 |
| **决策质量** | 随问题复杂度下降 | 复杂度越高，优势越明显（+86%~104%） |

---

## 十一、关键代码参考

| 模块 | 核心文件 | 位置 | 状态 |
|------|---------|------|------|
| **BAC三层模型** | models.ts | [6-图结构上下文压缩/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/models.ts) | 🟢 |
| **蓝图构建** | blueprint.ts | [6-图结构上下文压缩/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/blueprint.ts) | 🟢 |
| **意图识别网关** | intent-gateway.ts | [6-图结构上下文压缩/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/intent-gateway.ts) | 🟢 |
| **执行规划器** | planner.ts | [6-图结构上下文压缩/planner/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/planner.ts) | 🟡 |
| **思维步骤定义** | step-types.ts | [6-图结构上下文压缩/planner/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/step-types.ts) | 🟢 |
| **技能注册表** | skills-registry.ts | [6-图结构上下文压缩/planner/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/skills-registry.ts) | 🟢 |
| **A系列技能注册** | skills-registry-init.ts | [6-图结构上下文压缩/planner/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/skills-registry-init.ts) | 🟢 |
| **C/F链技能** | chains-registry.ts | [6-图结构上下文压缩/planner/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/chains-registry.ts) | 🟡 |
| **技能选择器** | skill-selector.ts | [6-图结构上下文压缩/planner/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/skill-selector.ts) | 🟢 |
| **交叉验证器** | cross-validator.ts | [6-图结构上下文压缩/planner/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/cross-validator.ts) | 🟢 |
| **投票计算器** | voting-calculator.ts | [6-图结构上下文压缩/planner/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/voting-calculator.ts) | 🟢 |
| **Python实验版ChainPlanner** | chain_planner.py | [experiments/ab-trading/core/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/chain_planner.py) | 🟢 |
| **Python版意图识别** | intent_gateway.py | [experiments/ab-trading/core/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/intent_gateway.py) | 🟢 |
| **编排API** | route.ts | [app/api/orchestrate/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/api/orchestrate/route.ts) | 🟡 |
| **前端动态链Runner** | runner.ts | [dynamic-chain/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/dynamic-chain/runner.ts) | 🟡 |
| **前端反思引擎** | reflect-engine.ts | [dynamic-chain/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/dynamic-chain/reflect-engine.ts) | 🟢 |
| **图-反思桥接** | graph-reflection-bridge.ts | [3-FRONTEND/.../lib/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/graph-reflection-bridge.ts) | 🟡 |
| **三屏系统架构** | 三屏系统架构.md | [2-KNOWLEDGE/1-TRADING/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/1-TRADING/三屏系统架构.md) | 🟢 |
| **SKILL注册表文档** | SKILL_REGISTRY.md | [6-TRADING/docs/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-TRADING/docs/SKILL_REGISTRY.md) | 🟢 |
| **治理系统** | GOVERNANCE_SYSTEM.md | [2-GOVERNANCE/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-GOVERNANCE/GOVERNANCE_SYSTEM.md) | 🟡 |
| **知识库RAG** | knowledge-rag.ts | [3-FRONTEND/.../lib/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/knowledge-rag.ts) | 🟢 |
| **意图记忆** | intent-memory.ts | [3-FRONTEND/.../intent/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/intent/intent-memory.ts) | 🟢 |
| **用户偏好记忆** | user-preference-memory.ts | [3-FRONTEND/.../memory/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/memory/user-preference-memory.ts) | 🟢 |
| **学习记录器** | learning-episode-writer | [6-TRADING/skills/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-TRADING/skills/learning-episode-writer/SKILL.md) | 🟢 |
| **经验提炼器** | lesson-distiller | [6-TRADING/skills/0-core-integration/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-TRADING/skills/0-core-integration/lesson-distiller/INTEGRATION.md) | 🟡 |
| **做梦系统** | dream-oneirology | [6-TRADING/skills/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-TRADING/skills/dream-oneirology/SKILL.md) | 🟡 |
| **A7实践论** | A7-practice-theory | [6-TRADING/skills/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-TRADING/skills/A7-practice-theory/SKILL.md) | 🟡 |
| **A8知行合一** | A8-theory-practice-verification | [6-TRADING/skills/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-TRADING/skills/A8-theory-practice-verification/SKILL.md) | 🟡 |
| **知识库管理框架** | 知识库管理框架.md | [2-KNOWLEDGE/5-METHODOLOGY/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/5-METHODOLOGY/知识库管理框架.md) | 🟢 |
| **索引体系** | 索引体系.md | [2-KNOWLEDGE/4-OPERATIONS/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/4-OPERATIONS/索引体系.md) | 🟢 |
| **DZE开发链总览** | README.md | [3-CHAIN-DEVELOPMENT/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-CHAIN-DEVELOPMENT/README.md) | 🟢 |
| **D系列（调研）** | D1-D4 docs | [3-CHAIN-DEVELOPMENT/1-RESEARCH/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-CHAIN-DEVELOPMENT/1-RESEARCH/) | 🟢 |
| **Z系列（规划）** | Z1-Z4 docs | [3-CHAIN-DEVELOPMENT/2-PLANNING/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-CHAIN-DEVELOPMENT/2-PLANNING/) | 🟢 |
| **E系列（执行）** | E1-E3 docs | [3-CHAIN-DEVELOPMENT/3-EXECUTION/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-CHAIN-DEVELOPMENT/3-EXECUTION/) | 🟡 |
| **三链接力协议** | SPEC.md | [3-CHAIN-DEVELOPMENT/4-PROTOCOL/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-CHAIN-DEVELOPMENT/4-PROTOCOL/SPEC.md) | 🟢 |
| **门禁系统** | chain_guard.py | [3-CHAIN-DEVELOPMENT/scripts/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-CHAIN-DEVELOPMENT/scripts/chain_guard.py) | 🟢 |
| **前端E链集成** | chain-controller.ts | [3-FRONTEND/.../dev-chain/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/dev-chain/chain-controller.ts) | 🟡 |
| **Evolution Engine** | evolution-engine.ts | [3-EVOLUTION/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-EVOLUTION/evolution-engine.ts) | 🟢 |
| **DZE Bridge** | dze-bridge.ts | [3-EVOLUTION/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-EVOLUTION/dze-bridge.ts) | 🟢 |
| **DreamAgent Bridge** | dream-agent-bridge.ts | [3-EVOLUTION/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-EVOLUTION/dream-agent-bridge.ts) | 🟢 |
| **Approval Bridge** | approval-bridge.ts | [3-EVOLUTION/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-EVOLUTION/approval-bridge.ts) | 🟢 |
| **Evolution Orchestrator** | evolution-orchestrator.ts | [3-EVOLUTION/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-EVOLUTION/evolution-orchestrator.ts) | 🟢 |
| **进化系统类型定义** | types.ts | [3-EVOLUTION/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-EVOLUTION/types.ts) | 🟢 |
| **全链路集成测试** | evolution-fullstack.test.ts | [3-EVOLUTION/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-EVOLUTION/evolution-fullstack.test.ts) | 🟢 |
| **Dream-Agent总览** | README.md | [DREAM-AGENT/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/README.md) | 🟢 |
| **创始宣言** | MANIFESTO.md | [DREAM-AGENT/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/MANIFESTO.md) | 🟢 |
| **协作架构** | 02-ARCHITECTURE.md | [DREAM-AGENT/docs/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/docs/02-ARCHITECTURE.md) | 🟢 |
| **协作宪法** | 00-AGENT-CONSTITUTION.md | [DREAM-AGENT/docs/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/docs/00-AGENT-CONSTITUTION.md) | 🟢 |
| **协作协议** | 01-COLLABORATION-PROTOCOL.md | [DREAM-AGENT/docs/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/docs/01-COLLABORATION-PROTOCOL.md) | 🟢 |
| **账本系统** | ledger/ | [DREAM-AGENT/ledger/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/ledger/README.md) | 🟢 |
| **DREAM Token** | DREAM-TOKEN-DESIGN.md | [DREAM-AGENT/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/DREAM-TOKEN-DESIGN.md) | 🟢 |
| **飞书协作** | feishu-collab/ | [DREAM-AGENT/docs/feishu-collab/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/docs/feishu-collab/README.md) | 🟡 |
| **GitHub门禁** | github-actions/ | [DREAM-AGENT/github-actions/](file:///Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/github-actions/README.md) | 🟢 |
| **系统维护SKILL** | system-maintenance/ | [6-TRADING/skills/system-maintenance/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-TRADING/skills/system-maintenance/) | 🟢 |
| **维护报告** | maintenance-reports/ | [1-ARCHITECTURE/.maintenance-reports/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/.maintenance-reports/) | 🟢 |

---

## 十三、实现进度总览

### 13.1 架构层实现进度

| 架构层 | 完成度 | 说明 |
|--------|--------|------|
| 骨架层（三链定义） | 90% | S/C/F三链步骤定义完整，F链技能部分待补充 |
| 血肉层（SKILL库） | 75% | A系列较完整，C/F系列部分实现，约40+技能 |
| 灵魂层（动态执行） | 60% | 反思引擎+5种决策已实现，AI主动思考待加强 |
| BAC图结构 | 85% | 数据模型完整，压缩/展开算法部分实现 |
| ChainPlanner | 85% | 四维规划完整实现（预算/知识库/历史/标的覆盖），TS版已上线 |
| 交叉验证（阶段一） | 80% | 投票计算器+交叉验证器已实现 |
| 动态插入（阶段二） | 75% | 动态插入决策+动态插入规划器+执行集成，S/C/F三链动态插入 |
| 前后端双向反馈 | 30% | API通路有，用户反馈触发重规划待实现 |
| 联网扩展能力 | 20% | Tavily技能可用，AI主动联网决策待实现 |
| **进化系统（动力引擎）** | **85%** | **Evolution Engine + 五层闭环（发现→学习→深度分析→能力更新→反馈执行），TS版已上线** |
| **DZE开发链（单任务落地）** | **85%** | **DZE Bridge 实现进化→DZE自动打通，Gate1/Gate2双门禁，11阶段完整推进** |
| **Dream-Agent协作网络** | **80%** | **DreamAgent Bridge 实现DZE→协作网络自动打通，账本+DREAM奖励+三角色完整流程** |
| **飞书审批与自主迭代** | **80%** | **Approval Bridge 实现4类审批（design/kickoff/merge/deployment）+超时自动批准，与进化系统全链路集成** |

### 13.2 进化系统各模块进度

| 模块 | 完成度 | 说明 |
|------|--------|------|
| 知识库系统 | 80% | 三层架构完整，RAG检索可用，33个知识文件 |
| 索引系统 | 75% | L1/L2/L3三级索引，index-ops每日审计 |
| 记忆系统 | 65% | 意图记忆+用户偏好记忆已实现，经验模式待完善 |
| 学习闭环（Episode） | 70% | Episode Writer已实现，Lesson Distiller部分实现 |
| 做梦系统（Oneirology） | 60% | 五大机制+四象限预言，需与主系统深度集成 |
| 治理闭环（A7/A8） | 55% | A7实践论+A8知行合一框架已建立，自动化待加强 |
| 联网补充能力 | 25% | Tavily可用，主动搜索和知识沉淀自动化待实现 |
| **Evolution Engine（进化引擎）** | **85%** | **TS版完整实现，发现→学习→提案→执行 全流程编排** |
| **DZE Bridge（进化→DZE打通）** | **85%** | **自动触发DZE链，11阶段推进，Gate1/Gate2双门禁** |
| **DreamAgent Bridge（DZE→协作网络打通）** | **80%** | **任务注册→认领→验证→入账 全流程，DREAM奖励自动计算** |
| **Approval Bridge（飞书审批打通）** | **80%** | **4类审批+超时自动批准，与进化系统/DZE/Dream-Agent全链路集成** |
| **Orchestrator（总编排器）** | **85%** | **统一编排4大模块，端到端闭环，16个测试100%通过** |
| 自动进化闭环 | 75% | 各模块已打通，端到端自动闭环可运行，需生产环境验证 |

### 13.3 下一步规划建议（优先级从高到低）

**✅ 已完成（Top 6 高优任务）：**
1. ~~完善 ChainPlanner 四维优化逻辑（后端）~~ ✅ 已完成，85%
2. ~~实现三链动态插入机制（阶段二）~~ ✅ 已完成，75%
3. ~~打通进化系统端到端闭环（Episode→Lesson→知识库→执行）~~ ✅ 已完成，85%
4. ~~进化系统与DZE开发链打通（Lesson自动触发开发任务）~~ ✅ 已完成，85%
5. ~~DZE开发链与Dream-Agent协作网络打通（单任务→多任务协作）~~ ✅ 已完成，80%
6. ~~飞书审批与自主迭代闭环打通（关键问题人工审批，其余全自动）~~ ✅ 已完成，80%

**中优待完成：**
7. **中优**：补充 F链 技能实现
8. **中优**：完善前后端双向反馈机制
9. **中优**：做梦系统与主系统深度集成（异常事件自动触发）
10. **中优**：DZE开发链生产环境落地（门禁自动触发/状态自动更新）
11. **中优**：Dream-Agent多Agent生产环境落地（任务自动分配/自动验收）
12. **低优**：AI主动联网思考能力
13. **低优**：图压缩/展开算法优化

---

## 十四、维护记录

| 版本 | 日期 | 更新内容 | 更新人 |
|------|------|---------|--------|
| v2.0 | 2026-06-25 | 初始版本，完整系统架构总览 | System |
| v2.1 | 2026-06-25 | 修正：1) S链=骨架/A系列=技能的关系澄清；2) 前后端分工明确（后端执行+前端展示双向反馈）；3) 三链结合两阶段策略（投票+动态插入）；4) 添加实现状态标注（🟢🟡🔴）；5) ChainPlanner定位为A阶段规划 | System |
| v2.2 | 2026-06-25 | 新增：1) 记忆与自我进化系统（动力引擎）完整章节；2) 三大基础能力（知识库/记忆系统/索引系统）详细说明；3) 学习闭环（Episode→Lesson）；4) 深度分析层（做梦部+治理闭环A7/A8）；5) 能力更新四步流程；6) 进化系统与三链的关系图；7) 更新实现进度总览和关键代码参考 | System |
| v2.3 | 2026-06-25 | 新增：1) DZE开发链（代码落地）完整章节，包含D调研/Z规划/E执行三链接力；2) 三链接力协议（chain_guard.py门禁系统+防跳步物理约束）；3) 开发链在进化系统中的位置（从能力进化到代码落地的完整闭环）；4) 进化系统架构图补充代码落地层；5) 实现进度总览补充DZE开发链；6) 关键代码参考补充8个开发链相关文件 | System |
| v2.4 | 2026-06-25 | 新增：1) 开发协作网络（Dream-Agent）完整章节，包含四大角色/账本系统/DREAM Token/UI-Driven分解/Phase 0-8生命周期/双门禁体系（GitHub+飞书）/防漂移三重保障；2) DZE开发链与Dream-Agent的关系说明（单任务方法论 vs 多任务协作网络）；3) 完整自主迭代闭环（系统运行→学习进化→开发协作→能力升级→回到运行）；4) 进化系统架构图补充协作网络层；5) 实现进度总览补充Dream-Agent协作网络；6) 关键代码参考补充10个Dream-Agent相关文件 | System |
| v2.5 | 2026-06-25 | 新增：1) 系统维护 SKILL（自动化运维）完整章节，包含健康检查/问题追踪/报告生成/修复流程；2) SKILL.md 规范文档和 health-check.ts 执行脚本；3) 每周定时执行机制设计；4) 首次运行测试成功（评分94/100，A级）；5) 关键代码参考补充系统维护 SKILL；6) 维护报告自动保存到 .maintenance-reports/ | System |
| **v4.0** | 2026-10-16 | **架构统一重大升级（跨系统一致性）**：1) 三层能力架构 **L0/L1/L2** 正式确立（唯一判据：是否依赖生成式 LLM 推理）；2) **新 SACG** 编排（S=认知驱动规划入口 / A=OKR 节点验收 / C=执行驱动 / G=压缩沉淀，C-drive 贯穿调度）取代旧 SACG（Sense/Arrange/Compute/Graph）；3) 认知系统内部四层改名 **C1-C4**（C1 基础/C2 记忆/C3 路由/C4 元认知）；4) **置信度门控**跨系统统一阈值契约；5) 新增第十六章「文档权威性与弃用指引」，旧架构文档统一加「已归档」横幅。**确保 0-系统文档管理 / 1-ARCHITECTURE / 3.1-FRONTEND / 34-前端应用训练系统 四处口径一致** | System |

---

## 十五、系统维护 SKILL（自动化运维）

> **定位**：将架构文档维护自动化，每周定时执行健康检查，生成维护报告，追踪问题修复。
>
> **SKILL位置**：[6-TRADING/skills/system-maintenance/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-TRADING/skills/system-maintenance/)
>
> **目标**：从"手动维护架构文档"升级为"系统自动检查+人工确认"的新模式。

### 15.1 核心功能

| 功能 | 说明 | 状态 |
|------|------|------|
| **架构健康检查** | 对照架构文档检查各模块实现状态 | 🟢 |
| **问题追踪** | 识别实现与规划的偏差 | 🟢 |
| **维护报告生成** | 自动生成 Markdown + JSON 格式报告 | 🟢 |
| **修复流程触发** | 按架构规划执行修复或触发开发任务 | 🟡 |

### 15.2 检查清单

| 检查项 | 架构章节 | 检查内容 |
|--------|---------|---------|
| 骨架层（三链） | 第二章 | S/C/F 链步骤定义完整性 |
| 血肉层（SKILL库） | 第五章 | A/C/F 系列技能实现状态 |
| 灵魂层（执行） | 第六章 | 反思引擎+5种决策实现 |
| BAC图结构 | 第三章 | 数据模型+压缩展开算法 |
| ChainPlanner | 第四章 | 四维规划逻辑实现 |
| 进化系统 | 第七章 | 记忆/知识库/索引系统 |
| DZE开发链 | 第八章 | D/Z/E三链+门禁实现 |
| Dream-Agent | 第九章 | 四大角色+账本+Token |

### 15.3 执行方式

#### 方式一：定时执行（推荐）

```bash
# 每周一 09:00 自动执行
# 配置在 SKILL.md 中，集成到 Cron 调度
```

#### 方式二：手动执行

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
npx tsx 6-TRADING/skills/system-maintenance/health-check.ts
```

#### 方式三：触发词执行

在 AI 对话中输入：
- "系统维护"
- "架构检查"
- "周维护"
- "健康检查"

### 15.4 报告输出

**位置**：[1-ARCHITECTURE/.maintenance-reports/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/.maintenance-reports/)

**报告文件**：
- `maintenance-report-YYYY-MM-DD.md` - Markdown 格式报告
- `maintenance-report-YYYY-MM-DD.json` - JSON 格式报告
- `LATEST.md` - 最新报告链接

**报告内容**：
```
# 🔧 系统维护报告

## 一、整体健康度
- 综合评分: 94/100 (A级)
- 正常模块: 7/9
- 警告模块: 2/9
- 危急模块: 0/9

## 二、各模块检查详情
- 🟢 骨架层: 100%
- 🟡 血肉层: 67% (待完善)
- ...

## 三、待处理问题
| 优先级 | 问题 | 建议操作 |
|--------|------|---------|
| 🟡中 | SKILL库不足 | 补充实现 |
| 🟡中 | 进化系统未打通 | 下期迭代 |

## 四、下周计划
1. 【中优】补充 SKILL 实现
2. 【中优】打通进化系统
```

### 15.5 与进化系统的关系

```
系统维护 SKILL（定期检查）
    ↓
发现问题（与架构文档的偏差）
    ↓
生成修复计划
    ↓
├─ 轻微问题 → 下周迭代计划
├─ 中等问题 → 触发 DZE 开发链
└─ 严重问题 → 触发 Dream-Agent 协作
    ↓
修复完成 → 更新架构文档 → 更新维护记录
```

### 15.6 使用流程

1. **每周一 09:00** - 系统自动执行健康检查
2. **生成报告** - 自动保存到 `.maintenance-reports/`
3. **飞书通知** - （可选）推送报告到飞书群
4. **人工确认** - 查看报告，确认问题
5. **执行修复** - 按计划执行修复或触发开发任务
6. **更新文档** - 修复完成后更新架构文档

### 15.7 配置文件

```yaml
# SKILL 配置
schedule:
  frequency: "weekly"  # weekly / monthly / manual
  day: "monday"
  time: "09:00"
  timezone: "Asia/Shanghai"

notification:
  feishu: true
  email: false

checks:
  modules:
    - skeleton
    - skills
    - execution
    - bac
    - chain_planner
    - evolution
    - dze_chain
    - dream_agent

reporting:
  format: ["markdown", "json"]
  destination: "1-ARCHITECTURE/.maintenance-reports"
  keep_history: 52  # 保留52周
```

---

## 十六、文档权威性与弃用指引

> **本章目的**：防止新旧架构文档混杂导致 AI / 人读到错误内容。明确**谁为准、谁已废、如何标注**。

### 16.1 文档权威层级（SSoT 裁定）

| 层级 | 文档 | 定位 | 优先级 |
|------|------|------|--------|
| **权威层（SSoT）** | `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md` **v4.0** | 系统架构**唯一事实源** | **最高**，一切争议以本文档为准 |
| **导航层** | `0-系统文档管理/2-文档地图/ARCHITECTURE_MAP.md`、`SYSTEM_MAP.md`、`INDEX.md` | 只告诉你「文档在哪」，不含架构内容 | 高于业务文档，低于 SSoT |
| **一致性子系统文档** | `34-前端应用训练系统/SPEC-v1.3-L0L1L2-architecture.md`、`SPEC-v1.2-SACG-orchestration.md` | 支撑 SSoT 的子域细则（L0/L1/L2 与 SACG 深化） | 与 SSoT 平级口径，细节补充 |
| **已归档层** | 见 16.3 清单 | 被 SSoT 取代的历史文档 | **禁止作为实现依据**，仅历史留档 |

**冲突裁定规则**：
1. 任何架构表述与 SSoT v4.0 冲突 → **以 SSoT 为准**。
2. 子系统文档（34 前端训练 / 35 认知）在**各自子域细节**上有效，但**分层 / SACG / 认知 C1-C4 / 门控口径**必须与 SSoT 一致。
3. AI 检索架构事实时，**应优先锚定 SSoT v4.0**；若命中「已归档」横幅文档，必须改读 SSoT。

### 16.2 统一弃用横幅（逐字模板）

所有被取代的旧架构文档，**必须在文档顶部第一行**加入以下横幅（逐字，不得改写）：

```
> ⚠️ 已归档 · 2026-10-16：本文档描述的架构已被《SYSTEM_ARCHITECTURE_OVERVIEW.md v4.0》取代，请以该文档为准。本文档仅作历史留档，禁止作为实现依据。
```

### 16.3 已归档文档清单（加横幅）

以下文档描述的架构已被 v4.0 取代，统一加 16.2 横幅：

| 位置 | 文档 |
|------|------|
| `1-ARCHITECTURE/` | `README.md`、`intent-recognition-architecture.md`、`RESEARCH_SACG_HARNESS_MAPPING.md`、`RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md`、`WORKBUDDY_OS_MODULAR_ARCHITECTURE.md`、`WORKBUDDY_OS_GAP_ANALYSIS.md`、`SUPERPOWERS_INTEGRATION_UPGRADE.md`、`SPEC-20260929-DREAMOS-渐进式能力演进路线.md` |
| `1-ARCHITECTURE/dreamos/` | `README.md` |
| `1-ARCHITECTURE/dream-harness-bridge/` | `SPEC.md`（旧 SACG 整合方案，项目未启动，重启须按 v4.0 重评） |
| `1-ARCHITECTURE/specs/` | `GLOBAL_COLLABORATION_FRAMEWORK_SPEC.md`、`FRONTEND3_DREAMOS_DSH_GLOBAL_ARCH_SPEC.md`、`ARCH_OPTIMIZATION_INDUSTRY_BENCHMARK_SPEC.md` |
| `1-ARCHITECTURE/前端设计/` | 该目录下全部 17 个 `.md` |
| `34-前端应用训练系统/` | `SPEC-v1.0-L0L1L2-architecture.md`（已被 v1.3 取代） |

### 16.4 保留文档（**不加**横幅）

以下文档**现行有效**，**禁止**加弃用横幅：

- ★ `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md`（本 SSoT，v4.0）
- `1-ARCHITECTURE/specs/` 下现行有效 SPEC：`DREAMOS_SKILL_ORCHESTRATION_SPEC.md`、`SKILL_IMITATION_EVOLUTION_SPEC.md`、`COGNITIVE_SYSTEM_INTEGRATION_SPEC.md`、`COGNITIVE_SYSTEM_INTEGRATION_P1_P3_SPEC.md`、`DATA_AND_COGNITIVE_READONLY_ACCESS_SPEC.md`、`DUAL_MODE_TRAINING_SPEC.md`
- 根层专题 / 基础设施 / 调研文档（不构成系统分层第二套口径）：`SPEC-20260928-POSTGRESQL-CENTRALIZATION.md`、`SPEC-20260929-L1-TRACE-PILOT.md`（含 `-REPORT`）、`SPEC-20260930-COGNITIVE-TAG-HOOKS-AUTO-LOOP.md`、`SPEC-20261004-INTENT-TRAINING-LOOP-30-SYSTEM.md`、`PLAN-20261004-INTENT-TRAINING-LOOP-30-SYSTEM.md`、`TOP10_RANKING_RECOMMENDATION_SPEC.md`、`TRADING_MODULES_OVERVIEW.md`、`THREE_CHAIN_DISPATCH_CHECKLIST.md`、`WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md`（外部同类项目调研）、`RESEARCH_20260930_FINANCE_AI_AGENT_ARCH_SURVEY.md`、`SPEC-自运行系统四层落地路径-总技术文档.md`（其"四层"=可观测→自检测→自修复→自迭代，非 SACG/能力分层）
- `34-前端应用训练系统/SPEC-v1.3-L0L1L2-architecture.md`、`SPEC-v1.2-SACG-orchestration.md`（子域细则，与 SSoT 同口径）
- `0-系统文档管理/` 全量导航文档（ARCHITECTURE_MAP / SYSTEM_MAP / INDEX 等）

> **判断原则**：文档描述的是「**当前正在实现的系统分层/编排/认知口径**」→ 保留；描述的是「**已被 L0/L1/L2 或新 SACG 取代的旧口径**」→ 归档加横幅。

### 16.5 一致性维护要求（硬约束）

系统架构口径涉及以下四处，**必须统一采用 v4.0 新架构（L0/L1/L2 + 新 SACG + 认知 C1-C4 + 置信度门控）**，不得出现第二套口径：

1. `0-系统文档管理/`（导航与地图）
2. `1-ARCHITECTURE/`（SSoT 及架构文档）
3. `3.1-FRONTEND/`（前端架构，`docs/v3-frontend-architecture.md`）
4. `34-前端应用训练系统/`（L0/L1/L2 与 SACG SPEC、README）

**硬约束阈值（跨系统统一，禁第二套）**：
- `THRESHOLD_HIGH = 0.7`
- `CASE_DENSITY_MIN = 3`
- `PREDICTION_ERROR_MAX = 0.3`
- `route_confidence = match_score − 0.3(若 prediction_error > 0.3) − 0.2(若 case_density < 3)`

**同名异义警戒**（详见 §1.2）：L0/L1/L2 ≠ 新 SACG ≠ 认知 C1-C4 ≠ BAC 三层 ≠ S链/C链/F链。修改任何文档时，**先确认语境**再落笔。

---

> **本文档随系统升级定期维护，是理解 DreamBuddy v2 架构的核心参考文件。**
> **状态图例**：🟢 已实现 &nbsp; 🟡 部分实现/进行中 &nbsp; 🔴 规划中/待实现
