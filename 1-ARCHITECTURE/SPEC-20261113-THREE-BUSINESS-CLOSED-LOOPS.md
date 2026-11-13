# SPEC：三大业务闭环链——交易链、涌现链、执行链

> **版本**：v0.3.4  
> **日期**：2026-11-13  
> **状态**：待复评（P0 已关闭；P1-03~06 规格已补齐；§12.3 D1 缺口已裁决 B+C 并落地契约；DEC-BCL-07 纠正执行层落位——40 只产意图，成交由 22 产生；G-BCL-1 仍为 FAIL，待纸面成交累积到 n≥100）  
> **评审意见**：[REVIEW-20261113-THREE-BUSINESS-CLOSED-LOOPS.md](./REVIEW-20261113-THREE-BUSINESS-CLOSED-LOOPS.md) v1.0（4 项 P0 已在 v0.2.0 修订，待复评确认关闭）  
> **scoped 标识**：`BUSINESS-CLOSED-LOOPS-SSOT`，仅作为三大业务闭环链的编排事实源  
> **上游架构 SSoT**：[SYSTEM_ARCHITECTURE_OVERVIEW.md](./SYSTEM_ARCHITECTURE_OVERVIEW.md) v4.2  
> **模块映射**：[3+3架构模块映射.md](./3+3架构模块映射.md)  
> **领域定义权**：交易契约归 49/50，涌现判据与实验归 48，DSH 归 46，MCP 封装归 47  
> **本次变更范围**：架构调研与文档固化；不改业务代码、不开放 live、不新增 MCP 壳  
> **证据口径**：当前状态来自 2026-11-13 文档与代码静态核查；运行态数字引用既有核验记录，本次未重跑云端链路

---

## 0. 阅读规则与决策状态

### 0.1 规范用语

- **必须 / 禁止**：目标态的约束。继承自已批准 SSoT 的约束立即有效；本 SPEC 新增约束须评审通过后成为实施门禁。
- **应 / 建议**：推荐实现方式，可在评审中以等价方案替代。
- **当前 / 已有证据**：只描述已核实的代码或已有运行记录，不代表本 SPEC 发布时再次复测。
- **目标态 / 提议**：不得登记为已完成能力。

### 0.2 本 SPEC 的五项推荐裁决

| ID | 推荐裁决 | 状态 |
|---|---|---|
| DEC-BCL-01 | 使用“三大业务闭环链”命名，与既有“三大能力链”和其他业务链明确区分 | 待评审 |
| DEC-BCL-02 | 50 是 NN 链决策出口，23 保持独立对照；40/43 只能作为受控、带版本的共享输入，不构成 23 串行依赖 | 沿用 49 v0.14 双链目标口径，待本 SPEC 评审确认 |
| DEC-BCL-03 | 6-TRADING 定位为 L2 研究分析核心，不是绕过 L1 路由和执行权的交易第一入口 | 待评审 |
| DEC-BCL-04 | 25—28 区分“确定性经典策略模式”和“LLM 辅助设计模式”；当前 25 的生成主路径归 L2 | 待评审 |
| DEC-BCL-05 | 48 主管判据、实验、度量和候选裁决；34 与领域模块分别承担训练执行和候选生成 | 待评审 |

### 0.3 总决策

采用“**内部固化闭环系统，外部选择性 MCP 投影**”。不建设包含三链全部业务逻辑和权限的超级 MCP。

系统的核心资产应固化为：

1. 统一事件与证据契约；
2. 研究权、决策权、执行权和发布权的分离；
3. 跨链 trace 与业务实体关联；
4. 可证伪实验、独立验收和发布门禁；
5. 模型、参数、策略、SKILL 的版本化发布与回滚；
6. 上述机制持续积累的可回放数据资产。

插件和外部宿主只是已稳定能力的分发方式，不属于核心权威链。

---

## 1. 背景、目标与非目标

### 1.1 背景

现有架构已经定义 L0/L1/L2 三层能力，并在各域形成大量模块和局部链路，但仍存在四类问题：

1. 把模块箭头当成业务闭环，缺少结果回流和版本化发布；
2. 研究、决策、执行、训练和发布权限混用；
3. 同一模块在不同文档中被放入不同“链”，缺少视角区分；
4. 目标态、代码已接线、历史运行证据和正式验收结论混写。

### 1.2 目标

本 SPEC 建立三条可独立验收、又可相互闭环的业务链：

- **交易链**：研究、信号、决策、风控、执行、成交和归因；
- **涌现链**：训练、候选生成、实验、度量、独立验证和版本发布；
- **执行链**：通用意图路由、任务编排、节点执行、结果验收和认知沉淀。

### 1.3 非目标

本 SPEC 不做以下事项：

- 不重写 49/50 的交易契约或双链实施路线；
- 不重写 48 的 E1—E5 判据、D1/D2/D3 实验协议；
- 不重写 DreamOS 新 SACG 或 46 DSH Router/Worker 契约；
- 不改变 47 的 registry、MCP 命名、配额和层级读写规则；
- 不把 50 live、自动权重回灌、三维联合涌现或 6 的完整前端接线写成既成事实；
- 不新增一套与 Signal Bus、TrainingEvent、FinalDecisionSignal 竞争的领域 schema。

---

## 2. 概念边界与权威关系

### 2.1 两种“三链”视角必须并存但不得混用

| 视角 | 三条链 | 回答的问题 | 定义位置 |
|---|---|---|---|
| 模块归属视角 | 交易框架链、模型训练链、产品能力链 | 模块主要归属于哪类能力资产 | 3+3 架构模块映射 |
| 业务运行视角 | 交易链、涌现链、执行链 | 一次业务如何完成、如何回流、如何进化 | 本 SPEC |

二者不是替代关系。同一模块可以属于一条能力资产链，同时参与多条业务闭环链。例如 48 属于模型训练链，同时参与交易链的离线控制面和涌现链的实验评价面。

### 2.2 与其他链命名的隔离

- S/C/F 链是思维链，不是本 SPEC 的执行链；
- D/Z/E 链是开发方法论，不是 D1/D2/D3 涌现维度；
- A0—A9 是 6-TRADING 的研究与交易生命周期，不等同于 NN 权威交易链；
- 新 SACG 是 L2 内部编排四层，不是独立业务闭环链；
- D1/D2/D3 在涌现链中分别表示交易、技术架构、对话意图，不与其他域的同号概念复用。

### 2.3 领域权威矩阵

| 主题 | 权威文档 | 本 SPEC 的使用方式 |
|---|---|---|
| L0/L1/L2、新 SACG | SYSTEM_ARCHITECTURE_OVERVIEW | 引用分层和路由，不重复定义 |
| 模块层级与能力链归属 | 3+3 架构模块映射 | 提供模块索引，不代替业务闭环 |
| 交易契约、50/23 双链、执行权 | 49 SPEC（含 execution_rights）、50 SPEC | 编排引用，不修改契约语义 |
| D1 交易全链 | 48 FULL-CHAIN | 引用快环、慢环、观测环及缺口 |
| D2/D3 涌现 | 48 D2-D3-CHAIN、3D 子 SPEC | 引用真值、实验协议和 verdict |
| 训练执行 | 34 域 SPEC | 作为训练与采集能力提供者 |
| 通用执行与 Worker 治理 | 46 DSH 架构 | 引用 Ticket、Mandate、trace、验收和 settle |
| MCP 对外边界 | 47 L1/L2 MCP PACKAGING | 复用域壳，不新建链内业务壳 |

---

## 3. 总体架构：三条业务链、三个运行平面

```text
                         ┌──────────────────────────┐
                         │         涌现链            │
                         │ D1 交易 / D2 开发 / D3 意图 │
                         │ 训练·生成·实验·度量·裁决   │
                         └─────────────▲────────────┘
                                       │
                          事件、证据、反馈、验收结果
                                       │
        ┌──────────────────────────────┴──────────────────────────┐
        │                                                         │
┌───────┴─────────┐                                     ┌─────────┴────────┐
│     交易链       │                                     │      执行链       │
│ 研究→决策→执行   │                                     │ 路由→编排→验收    │
│ 风控→成交→归因   │                                     │ L1 优先/L2 接管   │
└───────┬─────────┘                                     └─────────┬────────┘
        │                                                         │
        └──────────────────────────────┬──────────────────────────┘
                                       ▼
                         L0 数据、证据与记忆平面
                    fetchContext / settle / 统一关联查询
                                       │
                                       ▼
                    经门禁批准、带版本、可回滚的能力包
                    模型 / 参数 / 策略 / SKILL / 规则
                                       │
                                       ▼
                        Registry 发布，供后续任务消费
```

### 3.1 三个运行平面

| 平面 | 主要职责 | 不应承担的职责 |
|---|---|---|
| 在线服务与执行平面 | L1/L2 请求处理、交易决策、风控和已授权执行 | 不同步运行离线训练，不允许实验直接改生产状态 |
| L0 数据、证据与记忆平面 | fetchContext、settle、事实存储、证据引用、关联查询 | 不作为所有请求的固定同步路由节点 |
| 离线训练、涌现与发布平面 | 训练、做梦、反思、反事实实验、度量、审批、发布 | 不直接下单，不绕过门禁修改在线权重 |

### 3.2 链间关系

- 交易链是核心业务闭环；
- 执行链是通用任务执行骨架，可承载交易研究，但不因此取得交易执行权；
- 涌现链是跨业务的进化控制面；
- 链内闭环通过业务结果回流完成，链间闭环通过事件、证据和版本化能力发布完成；
- 禁止用“涌现实验直接操纵在线交易”形成伪闭环。

---

## 4. 交易链 SPEC

### 4.1 链范围

交易链由四类能力组成：

1. NN 核心交易闭环；
2. 23 独立自进化对照链；
3. 6-TRADING AI 研究分析能力；
4. 25—28 经典策略生命周期支链。

四者共享事实和证据，但不共享无边界执行权。

### 4.2 NN 核心交易闭环

**节点语义声明（消除跨文档歧义）**

- **49 是交易契约层，不是运行节点**：49 定义 FinalDecisionSignal、execution_rights、双链权限等契约语义，在线链只"遵循"契约，不在链路上"经过"49；
- **48 是离线控制面，不在同步热路径**：48 产出实验结论与训练建议，经各自门禁后被离线采纳，不参与单次交易；
- **42 是唯一的汇聚与约束透传节点**，任何绕过 42 直连 50 的接线均视为违约；
- 48 域文档中 `48→40→43→49→50` 的旧表述属于**历史口径**，其意图是"48 的建议经 40/43 契约化后由 50 决策"，不等于 49 是运行节点。收敛责任见 §4.2.1。

沿用 49 v0.14 双链目标口径，拆分离线控制面和在线热路径：

```text
离线控制面：
48 实验/度量/训练建议
  → 40/50 各自训练门禁
  → 可审计采纳或拒绝
  → 经批准、带版本、可回滚的 40/43/42/50 产物

在线决策与执行面：
40 → 43 → 42
       + 11/12/14/17/29 等子交易能力
  → 50 FinalDecisionSignal
  → execution_rights 单标的单出口裁决
  → 13 风控（Fail-Closed）
  → 16 调控/定容
  → 22 / 11 已授权执行出口

异步回流：
信号、证据、约束、拒单、委托、成交、PnL、能力版本
  → TrainingEvent / L0
  → 48 归因、实验和下一轮训练建议
```

#### 硬性边界

- 40/43 提供约束和上下文，不直接下单；
- 42 只做汇聚、归一化、约束透传和参数治理，不做最终策略判断；
- 50 输出 NN 链决策，不直接训练自身、不直接修改 40/50 权重；
- 13 保留最终风控否决权；
- 同标的同时刻只能有一个执行出口；
- 50 初期保持 shadow/paper，live 必须另有显式授权、Mandate、kill-switch 和评审；
- 48 不进入每次交易的同步热路径，在线链只消费最近已批准的产物。

#### 4.2.1 主干口径对照与收敛责任

| 来源 | 表述 | 本 SPEC 判定 | 收敛要求 |
|---|---|---|---|
| 本 SPEC §4.2 | `40 → 43 → 42 → 50 → execution_rights → 13 → 16 → 22/11` | ✅ 权威在线口径 | 保持不变 |
| 48 FULL-CHAIN v1.0-r1 | `48→40→43→49→50→执行器` | ⚠️ 历史口径，49 被误列为节点 | 48 域下次升版改为"48 建议→40/43→42→50"，49 回归契约层引用 |
| 3+3 模块映射 | 反馈层 → 48 训练 40/50 | ✅ 已收敛为"训练建议→各自门禁→采纳或拒绝" | — |
| 49 SPEC 旧章节 | 23 为唯一最终出口 | ⚠️ 与双链增补冲突 | 由 49 owner 在域内登记并收敛，本 SPEC 不代改 |

> 收敛责任人：48 口径由 48 域 owner 负责；49 内部旧章节由 49 域 owner 负责。本 SPEC 只登记差异，不取得领域定义权。

### 4.3 23 独立自进化对照链

23 不作为 `40 → 43 → 23 → 50` 的串行节点。其目标是提供独立进化机制、独立样本与权重体系，以及对 NN 链的对照和反证。

如需让 23 承接 40/43 宏观因子，采用共享快照方式：

```text
同一份带版本的 40/43 宏观因子快照
   ├──► 50 NN 链
   └──► 23 独立对照链
              │
              ▼
       同窗口、同标的、同成本口径对照
```

约束如下：

- 共享的是可回放输入快照，不是运行时状态；
- 23 和 50 不互相 import 运行时模块；
- 不共享未隔离的样本、权重和运行时文件；
- 主对照窗口内 control 必须冻结，基因注入另开实验；
- 输出由 48 按同一实验协议比较，执行仍受 execution_rights 单出口约束。

### 4.4 6-TRADING：L2 研究分析能力

6-TRADING 可提供 A0—A9 的研究、分析、辩论、方案、监控和复盘 SKILL，但 live 直连已经退休。

目标调用关系：

```text
用户研究请求
  → L1 意图路由 + L0 recall
  → 未命中或复杂任务转 L2
  → 6-TRADING + L0/L1 只读事实
  → 研究报告、情景分析、交易草案或复盘结论
```

权限边界：

- “6 + L0 是 AI 分析第一选择”只在**研究分析域**成立；
- 系统架构第一跳仍是 L1 路由，不是固定直连 6；
- NN 权威交易链不是研究请求的“二级备用”，它承担独立的在线决策职责；
- 6 或 L2 不得绕过 50/23、execution_rights、13 风控和唯一执行出口；
- 用户确认执行后，必须转入 L1 内部权威交易链，而不是由研究 SKILL 直接下单。

当前证据只支持 `trading_mode='ai_skill'` 参数和多轨任务编排存在，不能证明主前端已完整直接调用 6 的 A0—A9。后续验收必须依据真实调用目录和 trace，而不是模式名称。

### 4.5 25—28 经典策略生命周期支链

目标结构：

```text
策略设计/生成 25
  → 策略库与版本 26
  → 回测、治理与审批 27
  → Freqtrade 信号/webhook 28
  → 36 Signal Bus
```

必须区分两种模式：

| 模式 | 生成方式 | 层级 | 目标用途 |
|---|---|---|---|
| 确定性经典模式 | 模板、参数配置、规则、经典指标 | L1 | 无生成式 LLM 的策略配置与复用 |
| LLM 辅助设计模式 | 千问、DeepSeek、Claude 等生成或修改策略 | L2 | 自然语言策略设计和解释 |

当前 25 的 `generate_from_intent` 主路径在 LLM 不可用时返回 `llm_not_available`，因此不得将现状描述为“无大模型策略生成链”。只读策略元数据可以按确定性能力暴露，但不改变生成主路径的 L2 归属。

28 当前证据显示事件上报到 36 Signal Bus，未发现其直接进入 42/50 的证据。未来若成为 NN 候选信号源，必须增加：

- 明确的信号适配和 provenance；
- 同源去重与 horizon/intent 分类；
- 策略版本、审批状态和输入快照；
- execution_rights 与 13 风控约束；
- 对 Freqtrade 上游实际执行能力的单出口审计。

### 4.6 交易权限矩阵

| 能力 | 研究/建议 | 最终决策 | 真实执行 | 修改生产权重 |
|---|---:|---:|---:|---:|
| 6-TRADING / L2 | 允许 | 不允许越权 | 禁止直接执行 | 禁止 |
| 50 NN 链 | 允许 | NN 链内允许 | 仅经授权执行面 | 禁止 |
| 23 对照链 | 允许 | 独立链内允许 | 仅经 execution_rights | 仅走自身既有门禁 |
| 13/16/22/11 | 不适用 | 不改写策略 | 按权限与风控执行 | 禁止 |
| 34 | 提供训练执行 | 无交易决策权 | 禁止 | 仅生成候选训练产物 |
| 48 | 提供评价与训练建议 | 无交易决策权 | 禁止 | 禁止直接修改，必须走门禁 |

---

## 5. 涌现链 SPEC

### 5.1 职责分工

```text
34：训练执行、样本采集、训练产物
33 / 46 / DreamOS / 35 及领域模块：做梦、反思、候选生成
48：实验设计、判据、度量、反事实验证、candidate 裁决
45 与独立人工门禁：验证、审批和发布依据
Registry：保存已批准版本、证据引用和回滚信息
```

核心原则是：**生成者不自证，评价者不直接上线，发布必须可追溯。**

### 5.2 三条涌现维度

| 维度 | 真值来源 | 统计单元 | 主要输出 | 明确禁止 |
|---|---|---|---|---|
| D1 交易涌现 | 决策、拒单、成交、PnL、风险约束 | 交易决策/实验窗口 | 模型、参数、策略候选 | 用 shadow 结果宣称 live 有效 |
| D2 技术架构涌现 | AST/import、工程门禁、需求解决、人工盲评 | 模块/工程缺口 | 架构修复、工程方案、代码候选 | 用 AI 盲评替代最终独立人工 |
| D3 对话意图涌现 | 用户接受、修改、拒绝和后续行为 | 会话/任务 | 意图先验、知识组合、SKILL 候选 | 把 task_type 代理标签等同真实意图 |

三者可以共用 E1—E5 判据、实验协议和度量 schema，但不得混用真值、执行器和统计单元。

### 5.3 能力生命周期

目标状态机：

```text
observed
  → candidate
  → verified
  → approved
  → published
  → retired / rolled_back
```

任一阶段还可进入 `falsified / inconclusive / insufficient_data`，不得以调参或更换口径隐藏失败结论。

状态要求：

- `candidate`：已有可复现实验产物，但仍可能缺独立复核；
- `verified`：完成该维度要求的独立验证，D2 包括人工盲评，D3 包括真实在线标签或 A/B；
- `approved`：发布权限主体批准，记录适用边界、版本和回滚；
- `published`：通过 Registry 被后续任务消费；
- 任何在线异常均可回到 `rolled_back`，原始证据不得删除。

### 5.4 当前证据边界

- D1 快环和部分观测证据存在，慢环、统一 join 和训练采纳审计未闭合；
- D2-A 是统计候选，人工盲评未执行；
- D2-B 已形成缺口到真实 45 门禁的候选链，但需求单完整回填和独立复核仍不足；
- D3-A/D3-B 是候选实验，当前仍存在代理标签和离线反事实限制；
- X-A 只能称“跨域联合收益（代理）”，不得宣称三维联合涌现已发生；
- 48 在线反思不得因离线实验存在而被写成已进入实时决策。

---

## 6. 执行链 SPEC

### 6.1 简单任务：L1 优先

```text
用户请求
  → L1 意图识别
  → L0 fetch_context / cognitive.recall
  → 达到路由置信度则 L1 直接执行
  → L0 settle
```

边界：

- L0 提供工作前事实和工作后沉淀，不是固定业务路由跳点；
- 41 文件索引按需参与检索，不是所有请求的强制第二跳；
- 48 不是所有 L1 请求的同步终点；
- L1 异常按现有规则 FAIL-OPEN 转 L2，但交易风控失败仍必须 Fail-Closed。

### 6.2 复杂任务：L2 接管与 DSH 执行

```text
L1 未命中
  → 携带 l1_intent_hint 转 L2
  → planner / SKILL 编排 / 新 SACG / DSH
  → Registry 节点或领域能力执行
  → 结果汇总与 A 层/45 验收
  → L0 settle
  → 按事件类型进入 D2/D3 等离线实验
```

新 SACG 与 DSH 的目标关系：

- S 提供认知驱动规划；
- A 提供 OKR 节点验收；
- C-drive 驱动执行，DSH Router/Worker 承担受控节点执行；
- G 负责压缩与沉淀；
- Worker 默认只读，编排侧统一 settle；
- trace_id 贯穿规划、Ticket、Worker、验收和 settle。

当前前端仍存在预存链模板、SKILL 编排、原 planner/conversation/trade 等多轨实现，并带开关和 FAIL-OPEN 回退。因此 DreamOS 新 SACG → DSH 是目标统一编排形态，不得写成所有请求的唯一现状热路径。

### 6.3 AI 交易执行链的两种语义

“AI 交易执行”必须拆成两类：

1. **研究任务执行**：L2 调 6-TRADING 和只读事实，输出报告或草案；
2. **权威交易执行**：L1 内部决策链经 execution_rights、13 风控和唯一出口执行。

执行链可以连接二者，但不能把研究任务的“执行完成”当成交易已获授权。

### 6.4 执行链到涌现链的反馈

每次任务应按需沉淀：

- task_id、trace_id、意图、路由决策和节点版本；
- 开始/结束状态、降级、重试和预算；
- 验收 verdict 和证据引用；
- 用户接受、修改、拒绝等真实反馈；
- 工程缺口与需求单关联。

L0 settle 不阻塞在线响应；离线训练与涌现评价异步消费这些事件。

---

## 7. 跨链事件与关联契约

### 7.1 原则

跨链闭环需要统一“信封与关联规则”，不重复定义各域 payload。

- FinalDecisionSignal、MacroElasticConstraint、TrainingEvent 等继续由 49/48 等域定义；
- Signal Bus 的现行 SignalType 继续由 36 域治理；
- 本节只定义跨链最小字段和 join 规则；
- 大 payload 保存在权威存储，事件携带不可变证据引用和内容哈希。

### 7.2 最小跨链信封（提议）

| 字段 | 必要性 | 说明 |
|---|---|---|
| schema_version | 必填 | 信封版本，不替代领域 payload 版本 |
| event_id | 必填 | 全局唯一事件 ID |
| event_type | 必填 | 逻辑事件类型，映射到现有领域事件 |
| occurred_at | 必填 | 事件发生时间 |
| source_module | 必填 | 产生事件的编号模块 |
| trace_id | 必填 | 跨链追踪主键 |
| task_id / session_id | 条件必填 | 执行链和 D3 关联 |
| decision_id | 条件必填 | 交易决策和 TrainingEvent 关联 |
| order_id / fill_id | 条件必填 | 委托和成交关联 |
| requirement_id / gap_id | 条件必填 | D2 需求和工程缺口关联 |
| input_snapshot_version | 条件必填 | 可回放输入快照 |
| capability_versions | 条件必填 | model/strategy/SKILL/rule 等版本 |
| provenance | 必填 | 数据来源和生成方式 |
| evidence_ref / payload_hash | 必填 | 证据位置与完整性校验 |

逻辑事件可覆盖决策、拒单、成交、PnL、任务完成、用户反馈、工程门禁、训练建议和能力发布，但新增物理事件类型必须登记到对应领域，不得由本 SPEC 私自冻结新枚举。

#### 7.2.1 去重主键与 36 Signal Bus 信封的归属（已裁决）

**唯一去重主键是 `dedupKey`，不是独立生成的 `event_id`。**

```text
business_key = source_module + ":" + event_type + ":" + <业务主键>
              （D1 用 decision_id/order_id；D2 用 gap_id/candidate_id；D3 用 task_id/session_id）
event_id     = sha256(business_key)              # 跨链信封内的事件标识
dedupKey     = event_id                          # 36 信封去重键直接取 event_id
```

约束：

1. **禁止两套独立生成**：本地端与云端必须由同一 `business_key` 推导 `event_id`，否则 12/3 TrainingEvent 的同步永不可幂等；
2. `occurred_at` **不参与** `event_id` 计算（否则重放或补录会产生新 ID），只进入排序与乱序窗口判定；
3. `event_type ↔ SignalType` 映射表由 **36 域维护**，本 SPEC 只引用映射名，不定义枚举；
4. `DispatchChannel / Severity / 订阅路由` 全部归 36，跨链信封不重复定义。

**字段归属对照**

| 跨链信封字段 | 与 36 的关系 | 归属 |
|---|---|---|
| `event_id` | 派生 `dedupKey`，一值两用 | 本 SPEC 定义派生规则 |
| `event_type` | 通过映射表对应 `SignalType` | 36 定义映射 |
| `schema_version` | 独立于 36 信封版本 | 本 SPEC |
| `source_module` / `provenance` | 36 无对应字段 | 本 SPEC |
| `trace_id` | 36 透传不解释 | 46 定义语义 |
| `evidence_ref` / `payload_hash` | 36 只传引用 | 本 SPEC |
| `severity` / `dispatch_channel` | 36 原生字段 | **不在跨链信封中重复** |

#### 7.2.2 时间语义

| 字段 | 含义 | 要求 |
|---|---|---|
| `occurred_at` | 业务事实发生时间 | ISO-8601 含时区，写入方本地时钟不可信时须标注来源 |
| `ingested_at` | 接收方落库时间 | 由接收方填写，不可由发送方伪造 |
| 乱序窗口 | 允许迟到事件的合并窗口 | 默认 24h；超出窗口不得静默丢弃，须进入 `late` 队列并计数 |
| 补录 | 事后回填 | 保留原 `business_key`，仅更新 `ingested_at`，不生成新 `event_id` |


### 7.3 三条关键 join 规则

```text
D1：
decision_id
  → order_id / rejection
  → fill_id
  → pnl
  → training_event_id
同时保留 trace_id、input_snapshot_version、capability_versions

D2：
gap_id / requirement_id
  → candidate_id
  → sandbox_run_id / gate_run_id
  → independent_review_id
  → resolved / rejected
  → published_version

D3：
session_id / task_id
  → intent_prediction
  → selected_SKILL_or_knowledge_version
  → user_accept / edit / reject
  → online_experiment_id
```

闭环验收不得只检查“事件存在”，还必须检查关联覆盖率、版本完整性和证据可回放性。

---

## 8. 闭环能力包与 Registry 固化

### 8.1 链能力包

每条链和可发布子链应有机器可读的能力描述清单。建议最小结构如下：

```yaml
chain_id: trading.nn
version: v1
entry: <authoritative-entry>
nodes:
  - id: <module-or-capability>
    version: <approved-version>
contracts:
  inputs: [<existing-contract-ref>]
  outputs: [<existing-contract-ref>]
  feedback: [<existing-event-ref>]
authority:
  decision: <owner>
  execution: <owner>
  publish: <owner>
gates: [<gate-ref>]
observability:
  trace_id: required
  evidence: <evidence-ref>
slo: <service-objective-ref>
exposure:
  internal: <in-process-or-ipc>
  mcp: <readonly-observe-or-control-or-not-exposed>
rollback: <rollback-ref>
```

#### 8.1.1 承载方案与发布权限（已裁决，关闭 R-P0-02）

**方案 B：编排层独立登记，MCP 层交叉引用。**

| 决策项 | 结论 | 理由 |
|---|---|---|
| 承载位置 | `1-ARCHITECTURE/registry/capability_packages.yaml` | 能力包描述的是**链编排**（含大量非 MCP 节点），塞入 47 的 `mcp_capabilities.yaml` 会把"MCP 暴露清单"与"业务链编排"混为一谈 |
| 校验归属 | 47 `validate_mcp_registry.py` 新增 **V8 交叉引用**：能力包引用的每个节点若有 `mcp` 暴露，必须在 47 registry 中存在且状态一致 | 保持单一校验入口，避免两套校验漂移 |
| 写入权限 | 仅允许通过治理入口追加新版本；同一 `chain_id` 的历史版本不得覆盖，只能新增 `version` 并标记上一版 `retired` | 保证可回滚、可审计 |
| 状态字段 | `status ∈ {draft, candidate, verified, approved, published, retired, rolled_back}`，与 §5.3 一致 | 单一状态机，不另造 |

**发布权限主体（具名到域，不具名到人）**

| 能力类型 | 审批主体 | 签发主体（Mandate principal） |
|---|---|---|
| 40/43/42/50 模型与参数 | 49 契约 owner + 50 决策 owner 双签 | `orchestrator` |
| 25—28 策略与规则 | 26 管理 + 27 治理审批 | `verifier` |
| 6-TRADING SKILL 版本 | 6 域 owner | `orchestrator` |
| D1/D2/D3 涌现候选 | 48 裁决 + 45 独立复核 | `verifier` |
| 对外 MCP 暴露变更 | 47 域 owner | `admin` |
| 生产权重与 live 开关 | **不在本 SPEC 授权范围**，走 49 显式授权与人工评审 | `admin` |

**最小条目示例（首批三条链）**

```yaml
- chain_id: trading.nn
  version: v1
  status: draft
  entry: 50.FinalDecisionSignal
  owner: 49
  authority: { decision: "50", execution: "11", publish: "49+50" }
  gates: [G-BCL-1, G-BCL-4, G-BCL-5]
- chain_id: emergence.d1
  version: v1
  status: draft
  entry: 48.verdict
  owner: 48
  authority: { decision: "48", execution: "none", publish: "48+45" }
  gates: [G-BCL-2, G-BCL-5]
- chain_id: execution.general
  version: v1
  status: draft
  entry: 3.1-FRONTEND./api/data/query
  owner: 46
  authority: { decision: "46.Router", execution: "46.Worker", publish: "46" }
  gates: [G-BCL-3, G-BCL-4]
```

> `status: draft` 是刻意选择：本 SPEC 尚未复评通过，不得有任何条目标注 `approved` 或 `published`。

### 8.2 固化规则

- 能力包只引用领域契约，不复制契约正文；
- 每个节点必须声明版本、权限和证据；
- 发布物必须能定位到训练/实验/验收记录；
- Registry 是已批准能力的消费入口，不是实验产物的自动通行证；
- 链版本变化必须可回滚，回滚不得删除历史证据；
- 插件只消费已发布能力包，不自定义另一条权威链。

---

## 9. MCP 对外投影 SPEC

### 9.1 总原则

MCP 是三层能力的边界适配层，不是内部调用链改造层。纵向业务链通过已有 L0/L1/L2 域壳选择性投影，不新增 `trade-chain.mcp` 一类超级壳。

### 9.2 暴露矩阵

| 能力 | MCP 投影 | 约束 |
|---|---|---|
| 交易状态、信号证据、实验报告查询 | 允许只读 | 按 role 裁剪，保留 trace/evidence |
| 6-TRADING 研究分析 workflow | 允许异步 submit/poll | 输出研究产物，不取得交易执行权 |
| DreamOS 通用任务 | 允许异步 submit/poll | Mandate、预算、trace、token 计量按 47 执行 |
| 训练状态和历史 run 查询 | 允许只读 | 不暴露样本秘密和未授权数据 |
| 训练触发 | 有条件允许 | 仅 L2 自身写工具，须 Mandate、预算、trace 和 45 门禁 |
| 能力发布和回滚 | 默认不直接开放 | 由发布权限主体和既有治理入口执行 |
| L1 判定/下单/止损热路径 | 禁止 | 必须 in-process |
| 11 live / 51 真实下单 | 禁止 | 实盘链路永不暴露 MCP |
| 涌现实验直接改生产权重 | 禁止 | 必须经训练建议、独立门禁和版本发布 |

### 9.3 与 47 的衔接

- 复用 `l1.trading.mcp`、`l1.intent.mcp`、`l1.strategy.mcp`、`l2.dreamos.mcp`、`l2.train.mcp`、`l2.emergence.mcp` 等域壳规划；
- 壳内只允许协议解析、port/域入口调用和信封映射；
- L2 对 L1 只读；
- L2 数据必须经 L0 或 in-process DAL；
- `in-process-only` 能力永不插件化；
- 插件化继续遵守“先消费、再封装、后治理”。

---

## 10. 安全、降级与审计

| 场景 | 目标行为 |
|---|---|
| L0 recall/settle 失败 | 通用任务 FAIL-OPEN 并记录降级，不阻塞响应 |
| L1 路由失败 | 按现有规则转 L2，并携带可用意图先验 |
| DSH Worker 失败 | 编排侧记录失败和降级，Worker 不得自证完成 |
| 13 风控数据不足或校验失败 | Fail-Closed，禁止以通用 FAIL-OPEN 覆盖 |
| execution_rights 冲突 | 禁止执行，保留冲突证据 |
| 50 未获 live 授权 | 仅 shadow/paper，kill-switch 可立即关闭 |
| 训练/涌现服务失败 | 不影响在线交易，不自动回退到未批准权重 |
| D2/D3 证据不足 | 标记 insufficient_data，不得晋升为 verified |
| MCP 外部调用失败 | 壳返回标准错误，不绕过内部权威链重试写操作 |
| 回滚 | 回到上一批准版本，保留新版本失败证据和审计链 |

---

## 11. 当前状态与主要缺口

> 本节是 2026-11-13 静态核查快照，不是本轮运行验收报告。

| 链路 | 已有证据 | 主要缺口 | 当前结论 |
|---|---|---|---|
| NN 快环 | 既有记录显示 50 shadow/paper、48→40 消费端、40 先验到 50 已有证据 | R2 融合、完整对照和 live 灰度未完成 | 部分贯通 |
| D1 慢环 | TrainingEvent 已实现且幂等，反思/做梦能力存在 | 既有记录本地 12/云端 3 未同步，统一 join 和自动回灌不足 | 部分实现 |
| 观测环 | E0—E6、M1—M7 和多类 verdict 已落盘 | 部分实验候选、证伪或数据不足 | 有观测，不等于涌现成立 |
| D2 | D2-A/D2-B 有 formal candidate | 人工盲评、需求单回填、独立复核 | 候选 |
| D3 | D3-A/D3-B 有 formal candidate | 真实用户标签、在线 A/B、联合实验 | 候选 |
| 通用执行链 | L1 recall/route/settle、L2 settle、多轨编排代码存在 | 目标 SACG/DSH 链尚未统一所有请求 | 多轨部分实现 |
| 6-TRADING 前端调用 | ai_skill 模式和 SKILL 编排存在 | A0—A9 直接映射不足，缺完整调用目录和 trace | 未证明完整接线 |
| 25—28 | 策略生成、库、治理、信号和 Signal Bus 能力存在 | 25 当前依赖 LLM；28 未证明直接进入 42/50 | 独立支链，双模式待收敛 |

另有两类文档治理问题需登记：

1. 49 内部仍存在“23 唯一最终出口”与 v0.14 双链口径的新旧章节冲突，且任务表有重复/状态不一致行；
2. 48 FULL-CHAIN 部分早期状态已被后续 r7-fix 修正，引用时必须读取后续复核记录，不能只摘取旧缺口描述。

本 SPEC 不通过复制旧状态来“修复”上述文档，后续应由责任域升版收敛。

---

## 12. 实施路线与验收门禁

### P0：统一语义、权限和契约

| ID | 任务 | 验收 |
|---|---|---|
| BCL-P0-01 | 确认三大业务闭环链命名及与三大能力链的关系 | 3+3 映射、架构索引和本 SPEC 无歧义互链 |
| BCL-P0-02 | 确认 50/23、6、25、48/34 五项裁决 | 评审记录明确接受或替代方案 |
| BCL-P0-03 | 定义跨链最小信封、条件字段和三条 join 规则 | 不重复领域 schema；样例文件已落地：`1-ARCHITECTURE/registry/fixtures/cross_chain_event.sample.json`（D1/D2/D3 + 执行链各 1 条，`event_id` 可复算） |
| BCL-P0-04 | 建立研究权、决策权、执行权、训练权、发布权矩阵 | 与 49/50/47/48 权限无冲突，且矩阵每行有具名主体 |

### P1：补齐闭环证据

| ID | 任务 | 验收 |
|---|---|---|
| BCL-P1-01 | 打通 D1 decision→execution→PnL→TrainingEvent 统一 join | `join_coverage ≥ 0.95`、`n ≥ 100` 可回放、缺失原因分类计数可查（阈值见 G-BCL-1） |
| BCL-P1-02 | 完成三端事件同步和训练采纳/拒绝审计 | `dedupKey` 由 `business_key` 派生且两端一致；重复写入计数 = 0；训练建议有审批、版本和采纳/拒绝结果 |
| BCL-P1-03 | 建立 6-TRADING SKILL 调用目录和真实 trace | 施工规格见 §12.2.1；验收 = G-BCL-3 判定式 |
| BCL-P1-04 | 补 D2 人工盲评和需求单 resolved 回填 | 施工规格见 §12.2.2；验收 = G-BCL-2 判定式 |
| BCL-P1-05 | 补 D3 真实反馈标签和在线 A/B | 施工规格见 §12.2.3；主终点只用 explicit 标签，禁止申报"A/B 显著" |
| BCL-P1-06 | 收敛 25—28 双模式和执行权边界 | 施工规格见 §12.2.4；无 LLM 时仍产出可回测策略，provenance 含 template_id + params_hash |

### P2：固化能力包并选择性 MCP 化

| ID | 任务 | 验收 |
|---|---|---|
| BCL-P2-01 | 为三链及子链建立版本化能力包 | 入口、节点、权限、反馈、门禁、SLO、证据和回滚齐全 |
| BCL-P2-02 | 将已批准能力接入 Registry | 消费者只获取已发布版本，可执行回滚演练 |
| BCL-P2-03 | 复用 47 域壳开放只读和异步 workflow | 无超级壳；L1 热路径和 live 零暴露；权限测试通过 |

### P3：插件和生态扩展

- 仅对已发布、已版本化、可回滚能力进行插件化；
- 插件不携带独立交易执行权；
- 插件接入量、调用证据和治理成熟度满足 53 域规则后再扩大范围。

### 12.1 跨链出口门禁（可机器判定）

**判定脚本位置**：`1-ARCHITECTURE/registry/scripts/bcl_gate_check.py`（已实现 v0.1.0，Phase 0 / T0-1）。未提供证据数据或阈值未确认时，对应门禁输出 `not_evaluated` 或标记 `threshold_unconfirmed`，不得作为放行依据。

```bash
python3 1-ARCHITECTURE/registry/scripts/bcl_gate_check.py --json-out /tmp/bcl_gates.json
```

当前基线（2026-11-13）：G-BCL-0 PASS、G-BCL-2 PASS（空集）、G-BCL-4 PASS；G-BCL-1/3/5 `not_evaluated`（缺证据数据）；退出码 2，符合"不虚报 PASS"。

> 实现差异：脚本 v0.1.0 的 G-BCL-0 只校验"声明存在 + 49 未作运行节点"两项；五种链命名的全量冲突扫描尚未实现，待补。

| 门禁 | 判定式（全部满足才 PASS） | 数据来源 |
|---|---|---|
| G-BCL-0 语义门禁 | 五种易混链命名在 3+3 / 本 SPEC / SYSTEM_ARCHITECTURE_OVERVIEW 中出现且互不冲突；49 在运行链节点清单中出现次数 = 0 | 文档静态扫描 |
| G-BCL-1 交易证据门禁 | `join_coverage = count(decision_id ∧ order_id ∧ fill_id ∧ pnl ∧ training_event_id) / count(decision_id) ≥ 0.95`；`execution_rights` 冲突计数 = 0；可回放抽样 `n ≥ 100` 且回放成功率达 100% | TrainingEvent + execution_rights 审计 |
| G-BCL-2 涌现验证门禁 | 每个 `published` 条目 `evidence_ref` 可解析率 = 100%；`verified` 但缺独立复核的条目数 = 0；被 `falsified` 的结论在后续版本中未被删除 | Registry + 48 verdict 落盘 |
| G-BCL-3 执行追踪门禁 | 抽样 `n ≥ 100` 个执行单元（L2 task；L1 直答按 `trace_id` 聚合为请求单元），`trace_id` 从创建到 settle 五阶段贯穿率 = 100%；同一 trace 被多个 task 复用数 = 0；降级项（`degraded=true` 或 `verdict=fail`）`degraded_reason` 非空率 = 100% | `events/frontend/execution_chain_trace.jsonl`（task/Worker/验收/settle 台账） |
| G-BCL-4 对外边界门禁 | 47 registry 校验零违规；`layer=L1 且 exposure=mcp 且含写工具` 的条目数 = 0；`live` 暴露条目数 = 0 | `validate_mcp_registry.py` |
| G-BCL-5 回滚门禁 | 近 90 天内至少 1 次成功回滚演练，有证据文件；回滚前后历史证据文件删除数 = 0 | Registry 版本与演练记录 |

判定输出统一为 `{gate_id, verdict: PASS|FAIL|not_evaluated, value, threshold, evidence_ref, checked_at}`，落盘可供复评引用。

### 12.2 P1 施工规格（BCL-P1-03 ~ P1-06）

> 本节只定义施工规格与验收口径，**不代表已实施**。四项均为"已有部件 + 缺口组装"，评审原描述中的"从零新建"判断已按核实结果修正。

#### 12.2.1 trace 贯穿（BCL-P1-03）

**现状（已核实）**

- 透传层已存在：`api-client.ts` 生成/接收 `traceId` 并作为 `X-Request-Id` 发出（第 63—64、150 行）；`dsh-execution-engine.ts` 的 `inboundTraceId()` 读取 `x-request-id` / `x-trace-id`（第 199—208 行），并向 orchestrator、HTTP body（`trace_id`）、IPC 三路透传（第 138—277 行）。
- 真实缺口：`task-manager.ts` 的任务对象只有 `taskId`，没有 `trace_id` 字段；L1（`/api/data/query`）与 L2（`/api/task/stream`）是两个入口，未证明同一用户请求在"L1 未命中转 L2"时复用同一个 trace。

**实施状态（v0.3.4，2026-11-13）**：上述两项缺口已在代码中关闭——`task-manager.ts` 任务结构新增 `trace_id`（入参或生成），`ChatPanel` 入口唯一生成并同时透传 L1/L2，L1 未命中交接时不再生成新 trace；新增执行链台账 `events/frontend/execution_chain_trace.jsonl`（`created/route/execute/accept/settle`），L1 直答行 `task_id` 为空、按 `trace_id` 聚合并由 `entry=l1` 标识，交接行标记 `handoff=true` 不计入执行单元；门禁补降级原因覆盖率与跨 task trace 复用检查。**当前运行时样本 n=1（< 100），G-BCL-3 仍 FAIL，不得据此宣称通过。**

**目标**

- **生成点唯一**：由前端首个请求发起处生成 `tr_<ulid>`，全链只生成一次；
- L1 未命中转 L2 时**原样透传**，禁止 L2 重新生成（否则同一请求产生两条 trace）；
- `task_id` 与 `trace_id` 一对一：一个用户请求 = 一个 task = 一个 trace；
- 落盘点：task 元数据、L1 settle payload、L2 settle payload、DSH span、Worker 事件、执行链台账（`events/frontend/execution_chain_trace.jsonl`）。

**变更点**

| 文件 | 变更 |
|---|---|
| `3.1-FRONTEND/src/lib/task-manager.ts` | 任务结构增加 `trace_id`，创建时取入参或生成，禁止用 `taskId` 冒充 |
| `3.1-FRONTEND/src/components/features/chat/ChatPanel.tsx` | 提交时生成 trace 并随 L1 请求头携带 |
| `3.1-FRONTEND/scripts/l1_route_signal.py` | 接收 `--trace-id`，写入 settle payload |
| `3.1-FRONTEND/src/app/api/task/stream/route.ts` | `settleL2ToCognitive()` 从 task 元数据取 `trace_id`，不新生成 |
| 46 DSH | 复用既有 `trace_id` 字段，不新增 schema |

**验收**：G-BCL-3 判定式（抽样 `n ≥ 100` 个执行单元，五阶段贯穿率 100%，跨 task trace 复用数 0，降级项 `degraded_reason` 非空率 100%）。

**风险**：L1 与 L2 各自生成 trace 会产生"同请求双 trace"，表现为关联率虚高但实际断裂；判定式必须校验**同一用户请求内 trace 唯一性**，而不只是"字段非空"。

#### 12.2.2 D2 人工盲评（BCL-P1-04）

**现状（已核实）**

- 45 已具备盲评基础设施：`scorers/human/workflow.py` 的 `_validate_blind()`（第 318 行）会拒绝包含预期结论的 payload，配套单测 `test_blind_payload_rejects_expectations`（第 128 行）。
- 真实缺口：D2-A 的盲评**从未实际执行**；D2-B 的 AI 盲评（E-H4）**不能等同**人工盲评；E6 需求单未回填 `resolved`；originality 均值仅 1.0/2。

**协议**

- 评审单元 = 模块 / 方案；评审者 `N ≥ 2`，独立盲评，隐藏来源、作者与预期结论；
- 维度：originality（0—2）、correctness、feasibility；
- 一致性：Krippendorff `α ≥ 0.6`；未达则增补评审者，或判 `inconclusive`，不得用均值掩盖分歧；
- 记录：`45.human_review{reviewer_id(脱敏), blind_payload_hash, scores, alpha, verdict}`；48 verdict 以该记录作为 `verified` 证据。

**变更点（归 45/48 域，本 SPEC 不实施）**

1. 45 增加 D2 盲评批次 run，产物落 `human_review`；
2. 48 D2 verdict 增加 `human_review_ref`，`verified` 判定要求该字段非空且 `alpha ≥ 0.6`；
3. E6 需求单 `resolved` 回填由 48 域完成。

**验收**：G-BCL-2 判定式。

**不可自动化声明**：AI 评分不得替代人工盲评；无人工执行时，D2 状态**只能停留在 `candidate`**，不得因统计指标高而升 `verified`。

#### 12.2.3 D3 在线标签（BCL-P1-05）

**现状**

- D3 真值当前使用 `task_type` 代理标签；D3-B 为离线反事实；无 `user_accept / edit / reject` 采集。

**标签定义**

| 标签 | 判定 | 来源 |
|---|---|---|
| `accept` | 用户采纳输出并继续 | explicit |
| `edit` | 用户改写后重发 | explicit |
| `reject` | 用户明确否定或撤回 | explicit |
| `abandon` | 会话中断超阈值无后续 | inferred |

- 字段：`d3_label` + `label_source ∈ {explicit, inferred}`；
- 关联：`task_id → intent_prediction → selected_capability_version → d3_label`；
- 隐私：实验库只存标签、时间、能力版本与**内容哈希**，不存会话原文。

**验收**：主终点只使用 `explicit` 标签；`inferred` 单独报告，不得混入主终点计算。

**不可自动化声明**：当前单用户环境不具备在线 A/B 的统计效力。因此：
- 只采用**时序前后对照**（上线前 vs 上线后同分布任务）；
- 结论强度上限为 `inconclusive` 或"代理收益"，**禁止申报"A/B 显著"**；
- 若未来有多用户流量，再按 48 3D 子 SPEC 的 A/B 协议升级。

#### 12.2.4 25—28 确定性经典模式（BCL-P1-06）

**现状（已核实，修正评审"从零新建"判断）**

- `25/strategy_gen/template.py` 已有策略骨架，但 `get_template_fields()`（第 114—115 行）明确返回"模板需要 **LLM 填充**的字段说明"；
- `25/strategy_gen/paramopt.py` 已有 hyperopt → `config_patch` 的确定性参数搜索链路（第 4、70 行）；
- `intent.py` 在 `llm_available()==False` 时直接返回 `llm_not_available`，没有模板渲染兜底。

**目标**：把"模板 + 参数优化"组装成**无 LLM 入口**，而不是另建一套策略体系。

```text
generate_from_template(template_id, params, symbol, timeframe)
  → 模板占位符替换（无 LLM）
  → 语法检查 + lookahead 检测
  → 可选 hyperopt(config_patch)
  → 回测（复用 backtest_engine）
  → S5 检查清单
```

- `generate_from_intent()` 保持不变，仍归 L2；
- 两入口共享 `backtest_engine` 与 S5 检查，不得出现两套验收标准；
- 流转：25 产出 → 26 注册 → 27 审批 → 28 触发 → 36 bus（`source='m28-freqtrade'` 保留）；
- provenance 增加 `template_id` 与 `params_hash`。

**验收**

1. `llm_available()==False` 时仍能产出语法有效、可回测、无 lookahead 的策略；
2. 信号 provenance 含 `template_id + params_hash`，且不含任何 LLM 调用痕迹；
3. 确定性模式与会话式 LLM 模式的产物在 26/27 **不享受不同权限**，走同一门禁。

**风险**：模板参数空间若不加约束，"确定性"会退化为人工挑参。必须登记模板版本与参数 JSON Schema，参数越界即拒绝，不做隐式裁剪。

### 12.3 D1 结构性缺口（Phase 1 实测，2026-11-13）

**实测数据**

| 项 | 结果 |
|---|---|
| 50 域 TrainingEvent | 180 条，`symbol` **全部为 `MULTI`** |
| 40 域 execution_trades | 96 条，**无 `decision_id`、无 `order_id`**，`fill` / `pnl` 全为 `null` |
| 严格 join | 0 / 180，`join_coverage = 0.0`，缺口分类 `no_order = 180` |
| 既有 `training_event_join.py` | 对 `symbol=MULTI` 直接跳过，覆盖率恒为 0 |

**结论**：G-BCL-1 **FAIL**。这不是数据质量问题，而是**契约缺失**——决策侧与执行侧没有共享主键。

**三种修复路径（已于 2026-11-13 裁决：B 短期 + C 中期，A 不采纳）**

| 路径 | 改动 | 代价 | 风险 | 裁决 |
|---|---|---|---|---|
| A：50 输出 per-symbol 决策 | 改 50 决策语义 | 大 | 50 是组合级矛盾评估，拆到标的级可能失真 | ❌ 不采纳 |
| B：40 记录回写 `decision_id` | 40 增加字段 + 承接通道 | 小 | 需 50→40 传递 decision_id，且历史数据无法回填 | ✅ 短期（已落地） |
| C：新增组合级执行记录 | 新数据源 | 中 | 需 11/13/16/22 汇总层配合 | ✅ 中期（已落地） |

**B 落地契约（v0.3.2）**

| 项 | 规定 |
|---|---|
| 写入方 | `40-周期神经网络系统/execution/x0_pipeline.py` |
| 来源 | `40-周期神经网络系统/execution/config.json` → `decision_source.path`（默认 50 `runtime/decisions.jsonl`）+ `max_age_hours`（默认 24） |
| 字段 | `decision_id`（取 `signal_id`）、`decision_ts`；无匹配/过期/读取失败写 `null` |
| 归一 | `BTC/USDT`、`BTC-USDT-SWAP` → `BTC`；`BTC-PROFILE-DEFAULT` 等非交易载荷键返回 `None`，禁止回写 |
| 禁止 | 模糊匹配、跨标的借用、事后补造 decision_id、回填历史记录 |

**C 落地契约（v0.3.2）**

| 项 | 规定 |
|---|---|
| 写入方 | `40-周期神经网络系统/execution/portfolio_execution.py`（X0 主流程 fail-open 调用 + 可独立 CLI） |
| 落盘 | `40-周期神经网络系统/portfolio_executions.jsonl`，一行一个组合级 batch |
| 字段 | `batch_key`、`decision_id`、`legs[]`、`leg_count`、`notional_total`、`fill_count`、`pnl_total`、`status ∈ {planned, partially_filled, filled}` |
| 幂等 | 同 `(intent_date, source, decision_id, 标的集合)` 只写一条 |
| 禁止 | 无成交写 `pnl_total`、把 `planned` 计为已实现、用 batch 覆盖率替代严格 join |

**契约验证（fixture，非生产数据）**

单条带 `decision_id` 的成交记录 + 对应 TrainingEvent → `matched_by=decision_id`、`join_coverage_strict = 1.0`；证明 B 打通后链路可闭合。

**当前仍 FAIL 的真实原因**

40 的 X0 停在**意图流**（SPEC_execution_layer：X0 不下单、`order_placed=false`、`fill/pnl=null`），生产库内不存在任何成交事实。因此 B/C 只解决"契约缺失"，不产生可计入覆盖率的成交；G-BCL-1 在出现成交事实前必须保持 **FAIL**，不得以 `planned` 批次或覆盖率 0 数据充抵。

**架构落位纠偏与纸面成交（DEC-BCL-07，v0.3.3）**

| 项 | 规定 |
|---|---|
| 架构事实 | 40 是**周期/意图/验证场**，不是执行层；执行层为 **22-执行引擎中心**（13 风控 → 16 定容 → 22 执行 → 11/51） |
| 意图侧 | `40/execution/x0_pipeline.py` 只写意图流（X0），新增 `VALIDATION_UNIVERSE`（`40/asset_classes.py`）展开为 `execution_scope=paper_only` 意图；X2 实盘白名单不动 |
| 成交侧 | `22-执行引擎中心/x1_paper_executor.py`：意图 → `FinalDecisionSignal(decision_id)` → 13 PreTradeGate → 22 Gateway → 18 统一价格源纸面撮合，落盘 `22/audit/x1_paper_fills.jsonl` |
| 成交字段 | `venue=paper`、`decision_id`、`order_id`、`fill_id`、`fill_px`、`exit_px`、`pnl`、`status ∈ {open, closed, rejected, no_price}` |
| 证据源 | `48/metrics/d1_join_evidence.py` 默认执行源切到 22 纸面账本；`rejected/no_price` 不参与 join |
| 标的域 | `VALIDATION_UNIVERSE` 覆盖加密/贵金属（XAU、XAG）/能源（CL、BZ、NG）/工业金属（XCU）/美股指数与 ETF（US500、SPY）/美股龙头（NVDA）/亚太（JP225）/利率（TLT），解决 B 的标的域上限 |
| 禁止 | 把 40 的意图记录当成交事实；用 paper 成交冒充 live；纸面扩标放松 X2 实盘门禁；`open` 状态记 `pnl` |

**残留风险（B 覆盖上限）**：50 当前决策标的含 NVDA/XAU/XAG/BNB/HYPE，40 执行白名单为 8 个加密主流币；B 落地后实测仅 BTC/ETH/SOL 三个标的可建立 `decision_id` 关联（8 条白名单中 3 条）。DEC-BCL-07 通过 `VALIDATION_UNIVERSE` 把 XAU/XAG/XCU/CL/BZ/NG/US500/SPY/NVDA/JP225/TLT 纳入纸面验证场（不改 X2 实盘白名单）；HYPE 仍按 meme/增长型红线排除，BNB 待评估。

**裁决前纪律（硬约束）**

1. 禁止用 `symbol + 时间窗` 模糊匹配的覆盖率替代严格 join；
2. 禁止用覆盖率 0 的数据训练任何模型或生成训练建议；
3. D1 证据链视为断裂，不得对外宣称"交易闭环已打通"；
4. 上述禁令适用于 48/40/50 及任何下游消费方。

---

## 13. 待评审问题

1. 是否正式采用“三大业务闭环链”作为本视角唯一名称？
2. 是否确认 23 在主对照期保持独立，只共享带版本的 40/43 输入快照？
3. 是否确认 6 的定位是 L2 研究分析核心，而非交易执行总入口？
4. 是否确认将 25 的确定性经典模式作为独立目标建设，当前 LLM 生成路径明确归 L2？
5. 是否确认 48 保持判据、实验、度量和候选裁决主体，34 与领域模块承担训练和生成？
6. ~~能力包由哪个现有 Registry 承载，链版本与模型/策略/SKILL 版本的发布权限分别归属谁？~~ **已裁决（v0.2.0）**：采用方案 B，见 §8.1.1；承载物为 `1-ARCHITECTURE/registry/capability_packages.yaml`，发布权限具名到域。
7. ~~**DEC-BCL-06**：D1 决策与执行无共享主键的选型~~ **已裁决（v0.3.2）**：B 短期（40 回写 `decision_id`）+ C 中期（组合级执行记录），A 不采纳；契约与禁止项见 §12.3。Phase 1 解除"选型阻塞"，但 G-BCL-1 仍为 FAIL（无成交事实）。

未裁决前，本 SPEC 可作为架构讨论和差距分析依据，不作为新增开发、live 切流或 MCP 写工具上线授权。

---

## 14. 证据与源文档索引

| 主题 | 证据 |
|---|---|
| 三层能力与新 SACG | [SYSTEM_ARCHITECTURE_OVERVIEW.md](./SYSTEM_ARCHITECTURE_OVERVIEW.md) |
| 模块归属与既有三大能力链 | [3+3架构模块映射.md](./3+3架构模块映射.md) |
| 双决策链、执行权和交易契约 | [49 SPEC](../49-交易框架协议/SPEC.md)、[50 SPEC](../50-NN主矛盾评估器/SPEC.md) |
| D1 快环/慢环/观测环与 TrainingEvent | [48 FULL-CHAIN](../48-涌现架构/docs/tech/SPEC-EMERGENCE-FULL-CHAIN-v1.0.md) |
| D2/D3 真值、候选证据和限制 | [48 D2-D3-CHAIN](../48-涌现架构/docs/tech/SPEC-EMERGENCE-D2-D3-CHAIN-v0.1.md) |
| 48 域边界 | [48 README](../48-涌现架构/README.md) |
| 6-TRADING A0—A9 与 live 退休口径 | [6-TRADING README](../6-TRADING/README.md) |
| 主前端 L1→L2 入口 | [ChatPanel.tsx](../3.1-FRONTEND/src/components/features/chat/ChatPanel.tsx) |
| L1 recall、路由与 settle | [l1_route_signal.py](../3.1-FRONTEND/scripts/l1_route_signal.py) |
| L2 多轨任务执行 | [task-manager.ts](../3.1-FRONTEND/src/lib/task-manager.ts)、[skill-orchestration-executor.ts](../3.1-FRONTEND/src/lib/skill-orchestration-executor.ts) |
| DSH 节点映射与 LLM 兜底 | [dsh-execution-engine.ts](../3.1-FRONTEND/src/lib/dsh-execution-engine.ts) |
| 25 当前 LLM 依赖 | [intent.py](../25-用户策略生成系统/strategy_gen/intent.py) |
| 28 到 Signal Bus 的证据 | [webhook.py](../28-策略信号触发模块/signal_trigger/freqtrade/webhook.py) |
| MCP 层级、权限与壳规划 | [47 L1/L2 MCP PACKAGING](../47-MCP管理系统/docs/tech/SPEC-L1L2-MCP-PACKAGING-v0.1.md) |
| DSH 目标治理 | [46 DSH 架构升级](../46-DSH架构/docs/tech/DESIGN-DSH-ARCH-UPGRADE-v0.2.md) |

---

## 15. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1.0 | 2026-11-13 | 首版草案：定义三大业务闭环链、三平面、交易/涌现/执行目标链、跨链事件与 join、能力包、MCP 投影、现状证据、P0—P3 和 G-BCL-0—5 门禁 |
| v0.1.0-r1 | 2026-11-13 | 评审出具：条件通过。待关闭 R-P0-01 主干口径冲突、R-P0-02 能力包无承载、R-P0-03 双信封幂等、R-P0-04 门禁不可判定 |
| v0.2.0 | 2026-11-13 | 关闭 4 项 P0：新增 §4.2 节点语义声明与 §4.2.1 口径对照；新增 §8.1.1 承载方案（方案 B）与发布权限、落地 `registry/capability_packages.yaml`；新增 §7.2.1 去重主键派生规则与 §7.2.2 时间语义；§12.1 门禁改为可机器判定并指定判定脚本位置 |
| v0.3.0 | 2026-11-13 | 补齐 P1-03~06 施工规格（§12.2）：trace 贯穿（核实透传层已存在，缺口在 task-manager 与 L1→L2 复用）、D2 人工盲评（复用 45 `_validate_blind`，禁止 AI 替代）、D3 在线标签（explicit/inferred 分离，单用户禁用 A/B 申报）、25—28 确定性模式（复用 template + paramopt，非从零新建） |
| v0.3.1 | 2026-11-13 | 新增 §12.3 实测 D1 结构性缺口：180 条决策全 MULTI、96 条执行记录无 decision_id，严格 join 0/180，G-BCL-1 FAIL；登记 DEC-BCL-06 三路选型；确立"禁模糊匹配、禁用 0 覆盖率数据训练"硬约束 |
| v0.3.2 | 2026-11-13 | DEC-BCL-06 裁决为 B 短期 + C 中期并落地契约：40 X0 回写 `decision_id`/`decision_ts`（含标的归一与伪符号排除）、新增 `portfolio_executions.jsonl` 组合级执行记录（幂等 + fail-open）；fixture 验证 `join_coverage_strict=1.0`；G-BCL-1 因无成交事实仍保持 FAIL |
| v0.3.3 | 2026-11-13 | DEC-BCL-07 架构落位纠偏：40 是周期/意图/验证场，**执行层是 22**；新增 `22/x1_paper_executor.py`（13→16→22 纸面成交，落 `22/audit/x1_paper_fills.jsonl`，含 `decision_id/order_id/fill_id/fill_px/exit_px/pnl`）；`FinalDecisionSignal` 增 `decision_id`；D1 证据源切到 22 账本；`40/asset_classes.VALIDATION_UNIVERSE` 扩多板块标的（XAU/XAG/XCU/CL/BZ/NG/US500/SPY/NVDA/JP225/TLT），X2 实盘白名单不变；fixture 验证 `join_coverage_strict=1.0`，G-BCL-1 仍 FAIL（n=2<100） |
| v0.3.4 | 2026-11-13 | trace 贯穿落地并建立台账：task 元数据/入口/L1 settle/L2 settle 全链带 `trace_id`；新增 `execution_chain_trace.jsonl` 五阶段台账；G-BCL-3 判定改为执行单元口径（L1 直答按 trace 聚合、交接行不计）、新增跨 task trace 复用与降级原因覆盖率检查；运行时样本 n=1，G-BCL-3 仍 FAIL（样本不足） |
