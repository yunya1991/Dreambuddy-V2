# SPEC：DreamBuddy L2 系统架构能力 v1.2.6（完整版）

> **版本**: v1.2.6 ｜ **日期**: 2026-11-18 ｜ **状态**: 定稿（总纲）
> **v1.2.6 settle 写入口**: L0 `settle` 识别到数据源的坑/降级模式后写入 `.data/memory/pending.jsonl`；治理周期统一过准入后落正式记录，避免 Python 侧复制准入判定。
> **v1.2.5 闭环补齐**: 残差记忆生产端（`POST /api/memory/records`，准入后才落盘 + 锚点复核）、DSH 事件消费者（`verdict_event_consumer`，按 seq 增量消费 `verdict.updated`）、launchd `WatchPaths` 触发（不做忙轮询）。
> **v1.2.4 运行时接线**: 异步裁决 job（`POST /api/verdicts/jobs`，202 + 轮询）、L0 `verdict.updated` 权威事件（事件优先读取、旧文件回退）、治理周期 `POST /api/governance/cycle` 挂 launchd（每日 03:30）、Ticket `waiting_verdict` 唤醒桥。
> **v1.2.3 生产化（P2.5）**: 三项遗留落地 —— U3 跨源自动对账（去重/过期/字段冲突）、U2 沙箱/回测统一出口（白名单 + 可复放/成本/样本外校验）、残差遗忘事件驱动调度（降级/痕迹池/M1 容量门）；前端纯函数模块 + 38 项测试。
> **v1.2.2 架构挂载评审**: 明确两项能力以"横切服务带"嵌入 SACG + DSH，不新增第五平面；新增 §2.4、§4.4、§5.5 与 §14.1；修正单一事实源与写入口。
> **v1.2.1 评审修订**: 对 §3.6/§3.7 做事实核对与一致性评审，修正 4 处过度声明/口径冲突（详见 §14）；审批结论"修订后通过"。
> **v1.2 变更**: 新增 [§3.6 不确定性裁决](#36-不确定性裁决核心差异化能力) 与 [§3.7 广义认知、残差记忆与反思进化](#37-广义认知残差记忆与反思进化核心差异化能力)，明确两个差异化护城河；§0 增加对应摘要。
> **v1.1 变更**: 新增 [§6.9 GateFlow](#69-gateflow把飞书流程定义内化为可执行制度)——把飞书的「流程定义 + 运行状态机」内化为可校验、可回放的门禁流程；原 §6.9 治理缺口顺延为 §6.10；同步更新 §11 路线与 §12 验收清单。依据 [RESEARCH-GATE-INSTITUTIONS v0.2 §2.6](../../46-DSH架构/docs/tech/RESEARCH-GATE-INSTITUTIONS-v0.1.md)。
> **定位**: 把此前的增补文档收敛为一份完整的系统架构能力 SPEC；本文定义**平面边界、契约与红线**，细节仍由各分册承载。
> **上游 SSoT**: [SYSTEM_ARCHITECTURE_OVERVIEW](../SYSTEM_ARCHITECTURE_OVERVIEW.md) v4.2 ｜ [3+3架构模块映射](../3+3架构模块映射.md) v1.2 ｜ [SPEC-56 L2 契约](../../56-L2架构能力聚合层/SPEC-56-L2架构能力聚合层.md) v0.9 ｜ [DESIGN-DSH-ARCH-UPGRADE v0.2](../../46-DSH架构/docs/tech/DESIGN-DSH-ARCH-UPGRADE-v0.2.md) ｜ [DESIGN-QUANT-TEAM v0.9](../../46-DSH架构/docs/tech/DESIGN-QUANT-TEAM-v0.1.md)
> **下游**: 各域 SPEC / TECHNICAL_DESIGN / 验收清单

---

## §0 摘要

DreamBuddy 不是"会聊天的 Agent"，而是一套**可被治理的 AI 工程操作系统**：下层用 L0/L1/L2 提供事实、证据与动作，中层用 DreamOS SACG 做规划与验收，执行层用 DSH Superagent 做并行工程，治理层把公司管理制度内化为前端门禁。

**四个平面 + 一个生态**

| 平面 | 回答什么 | 核心载体 |
| --- | --- | --- |
| 能力平面 | 有什么事实、证据、动作 | L0 / L1 / L2、MCP、6-TRADING、45 门禁 |
| 编排平面 | 怎么规划、验收、执行、沉淀 | DreamOS SACG（S→A→C→G） |
| 执行平面 | 谁来做、怎么并行、怎么续跑 | DSH Router / Worker / Ticket / Mandate |
| 治理平面 | 谁批准、凭什么批准、何时阻断 | 前端任务看板 + GateFlow + 五道门 + 三类模型 |
| 生态平面 | 怎么扩展、怎么接入、怎么验证 | DSH 插件、MCP 能力、交易协议实盘验证 |

**三句口诀**

1. **L0 给事实，L1 给证据，L2 给动作。**
2. **前端不是展示层，是门禁层。**
3. **门禁不是流程，是授权：没有确认就没有下一步。**

**两个差异化护城河**（§3.6 / §3.7）

1. **不确定性裁决**：确定性高的能力各家 AI 趋同；我们的差异是遇到不确定事件时，能依次用 L0/L1 事实、沙箱验证、6-TRADING 回测、18 多源采集 + 33-REA 逆向解析把不确定性收敛掉，收敛不了就明确 `inconclusive`。
2. **认知与进化**：广义认知系统 + 残差记忆器决定"什么值得记、什么时候该忘、记忆从哪来"；48 涌现架构 + hermes 反思决定"下一次怎么做得更好"，且进化只出提案、必须过门禁。

**五条不可妥协的红线**

| # | 红线 | 判据 |
| --- | --- | --- |
| R1 | 不自证验收 | 完成与否由 A 层 verify + 45 判定，Worker 不得自报完成 |
| R2 | 不越过门禁 | 存在 waiting / rejected 门禁时，对话与执行均返回 409 |
| R3 | 不双写状态 | Ticket / 快照 / 认知记录以 L0 为唯一事实源 |
| R4 | 交易热路径零接入 | 团队不下单、不改策略、不写交易配置 |
| R5 | 第三方能力默认拒绝 | 插件 / MCP / 模型未授权即拒绝，失败不倒向放行 |

---

## §1 定位与边界

### 1.1 系统是什么

- 一个**多平面协同的操作系统**：能力、编排、执行、治理各自独立，通过契约连接；
- 一个**可审计的工程组织**：每个任务都有目标、角色、证据、门禁与结论；
- 一个**可扩展的能力市场**：DSH 插件、MCP 能力、交易验证协议都按同一准入门槛接入。

### 1.2 系统不是什么

- 不是单体聊天应用：对话只是入口之一；
- 不是"多 Agent 自由对话"：Agent 之间不直接通信，只经领队与黑板聚合；
- 不是"接入了飞书"：飞书的员工管理/公司管理是**被内化的制度**，不是外部 API；
- 不是"模型越多越好"：三类模型足够，关键是异构与职责分离。

### 1.3 与既有文档的关系（增量收敛）

本文**不重写分册**，只做三件事：

1. 把 11 份增量文档的结论收敛到四平面；
2. 冻结平面之间的边界与红线；
3. 给出统一的成熟度评估与落地路线。

冲突裁决顺序：**本文的平面边界与红线 > 各分册的细节契约 > 实现现状**。能力"实现了多少"以 `56-L2架构能力聚合层/docs/TECHNICAL_DESIGN.md` 登记为准。

### 1.4 成功判据（机器可判定）

| # | 判据 |
| --- | --- |
| S1 | 任一任务可回答四问：做什么 / 到哪步 / 谁在做 / 合不合格 |
| S2 | 任一结论可回溯到 `evidence_refs`，缺失即 `needs_review` |
| S3 | 任一越权调用被拒绝并留痕，不存在静默成功 |
| S4 | 关断新路径（`CDRIVE_SUPERVISOR=false`、`GATE_MODE=human`）行为等价 |
| S5 | 同类任务二次执行可 recall 命中历史案例 |

---

## §2 总体架构

### 2.1 四平面图

```
┌──────────────────────────────────────────────────────────────┐
│ 治理平面  Agent Management（前端 = 工作管理工程）              │
│ 五道门 · GatePolicy · 角色 SoD · 双模型会签 · 双模式 · 409     │
└──────────────▲───────────────────────────┬──────────────────┘
               │ 证据 / 门禁事件            │ 放行 / 驳回 / 回转
┌──────────────┴───────────────────────────▼──────────────────┐
│ 执行平面  DSH Superagent（Router / Worker / Ticket / Mandate）│
│ 事件驱动 · 多 Ticket 并行 · 隔离执行 · 插件生态（Cordis）      │
└──────────────▲───────────────────────────┬──────────────────┘
               │ 派工 / 预算 / 能力集        │ 结果 / 证据 / 摘要
┌──────────────┴───────────────────────────▼──────────────────┐
│ 编排平面  DreamOS SACG（S 规划 → A 验收 → C 执行 → G 沉淀）    │
└──────────────▲───────────────────────────┬──────────────────┘
               │ 能力调用                    │ 事实 / 证据
┌──────────────┴───────────────────────────▼──────────────────┐
│ 能力平面  L0 事实 · L1 证据 · L2 动作（MCP 统一出口）          │
│ 6-TRADING A0-A9 · 45 门禁 · 32 辩论 · 34 训练 · 54/56 聚合     │
└──────────────────────────────────────────────────────────────┘

生态平面（纵向贯穿）：DSH 插件 / MCP 能力 / 交易协议实盘验证
观测平面（横向贯穿）：trace_id → span → stop_reason → 验收证据
横切服务带：不确定性裁决（L2-K Adjudicator）· 认知/残差/进化（35 + 48）
```

### 2.2 控制流与数据流

- **控制流下行**：用户/事件 → Router → Ticket → Worker → 能力调用；
- **数据流上行**：能力结果 → 证据 → OKR verify → 门禁 → 结论；
- **治理流横切**：门禁事件写入 L0，前端读快照、写决策，任何写操作都经过 Mandate。

### 2.3 单一事实源

| 对象 | SSoT | 禁止 |
| --- | --- | --- |
| Ticket / 任务状态 | L0（快照由事件回放） | 在 DSH 或前端维护第二套权威状态 |
| 门禁状态 | `gate.updated` 事件 | 前端本地"假批准" |
| 认知 / 经验 | L0 广义认知五系统 | Worker 私有记忆作为事实 |
| 成本 / 预算 | `GlobalBudgetManager` | 各壳自行记账 |
| 不确定性裁决 | L0 `verdict` 事件（绑定 evidence_ref / run_id） | Worker 自出 verdict、DSH 缓存作为权威 |
| 残差记忆 | 35 认知系统存储 | Worker 私有记忆、未过准入的写入 |
| 进化提案 | 48 涌现 + Ticket | 绕过门禁直接改生产 |

### 2.4 两项差异化能力的挂载方式（横切服务带）

> **不新增第五个平面，也不做第二事实源。** 两项能力以"横切服务带"挂载：各自唯一 owner、唯一写入口、唯一消费契约，贯穿既有四平面。

#### 2.4.1 挂载矩阵

| 能力 | 唯一 owner | 贯穿平面 | 唯一写入口 | 主要消费方 | SSoT |
| --- | --- | --- | --- | --- | --- |
| 不确定性裁决 | L2-K Adjudicator | 能力（L0/L1/U2/U3）→ 编排（S/A）→ 执行（证据）→ 治理（验收门） | 编排侧 A / settle（持 Mandate） | A verify、门禁预审、45、OKR KR | L0 `verdict` 事件 |
| 认知与进化 | 35 认知系统 + 48 涌现 | 执行（settle）→ 认知（recall）→ 编排（S）→ 治理（提案门） | settle（编排侧，持 Mandate） | S 规划、A 验收、hermes | 35 存储 + 48 实验注册 |

#### 2.4.2 数据流（与四平面的关系）

```
S 规划（声明 claims + 所需 U 级）
  → C 执行（Worker 产证据；U2 沙箱/回测以异步 job 运行）
  → A 裁决（Adjudicator 产 UncertaintyVerdict，只读证据）
  → 验收门（读 verdict：supported 放行 / contradicted 驳回 / inconclusive 补证据）
  → G 沉淀（残差准入 → 认知 record → 48 反思 → 进化提案）
  → 下次 S recall（残差指针 + 历史 verdict）
```

#### 2.4.3 防腐层（架构硬约束）

1. **Worker 不产 verdict**：Worker 只能产 `evidence_ref`，裁决权在 A/Adjudicator；
2. **DSH 不持权威状态**：verdict / 记忆 / 提案的权威副本只在 L0 与 35/48；
3. **证据变更即失效**：`evidence_ref` 或 `run_id` 变化后旧 verdict 自动失效，需重新裁决；
4. **写入口唯一**：认知写入只走 settle；进化只能出提案，不能直接改代码或阈值；
5. **热路径零接入**：U2 回测/沙箱、U3 采集/REA 一律异步，不进入交易主循环。

---

## §3 能力平面：L0 / L1 / L2

### 3.1 唯一判据

> **是否依赖生成式 LLM 推理**：依赖 → L2；不依赖 → L0 或 L1。

灰区规则沿用 3+3 v1.2：本地模型/统计检验归 L1；工具链归 L0/L1；编排 ≠ 生成；路径必须经过 LLM 才归 L2。

### 3.2 三层职责

| 层 | 本质 | 输出 | 失败形态 | 红线 |
| --- | --- | --- | --- | --- |
| L0 | 确定性能力 | 事实、状态、注册表、预算 | `error_code` | 零 LLM；不做业务判断 |
| L1 | 统计方法 + 涌现 | 候选、异常、显著、相似、证据 | `degraded` | 只给证据，不给叙事结论 |
| L2 | 生成与编排 | 规划、裁决、生成、动作 | `needs_review` / `inconclusive` | 不替 L1 做判定；不自证验收 |

### 3.3 统一信封（`L2Envelope`）

所有 L2 出口必须返回：

```json
{
  "ok": true,
  "result": {},
  "meta": {
    "layer": "L2",
    "capability_id": "l2.dreamos",
    "run_id": "run-...",
    "model": "qwen4-max | deepseek-v4-pro | jev-latest | none",
    "tokens_used": 0,
    "budget_remaining": 0,
    "latency_ms": 0,
    "degraded": false,
    "needs_review": false
  },
  "trace": {
    "route": "L2_HANDOFF",
    "reasons": [],
    "sagc": { "S": "done", "A": "done", "C": "done", "G": "skipped" }
  },
  "quality": {
    "evidence": "none | partial | full",
    "caveat": "..."
  }
}
```

硬约束：`tokens_used` 与 `budget_remaining` 同源；`model=none` 时 token 必须为 0；失败不得用 HTTP 200 掩盖；结论不得出现"将会/必然"。

### 3.4 能力注册与配额

- 注册表：`47-MCP管理系统` 为唯一入口，按层配额（L2 ≤ 30，当前活跃 14）；
- 角色投影：主表 + 角色视图，运行时二次校验，未授权直接拒绝；
- 命名：`l0.* / l1.* / l2.*`，禁止跨层别名（兼容别名必须标 deprecated）；
- 版本：semver + 依赖检查，破坏性变更必须升主版本。

### 3.5 交易能力（6-TRADING）

- A0–A9 阶段定义、阈值、验收标准由 6-TRADING 作为 SSoT；
- L1 负责确定性计算（回测、筛选、风险数值、离场规则）；
- L2 负责研判与方案，不执行下单；
- 45 门禁负责最终业务判定，shadow 期只记录，转硬门后未过不得进报告。

### 3.6 不确定性裁决（核心差异化能力）

> **确定性高的能力，所有 AI 都差不多；真正的差距在"说不准的时候怎么办"。**

同理，"生成一个看起来合理的答案"不构成壁垒；壁垒是**能不能用事实、实验和外部证据把不确定性收敛掉，并在收敛不了时明确说"不知道"**。

#### 3.6.1 四级裁决阶梯

| 级 | 名称 | 依靠什么 | 输出 | 不做什么 |
| --- | --- | --- | --- | --- |
| U0 | 事实裁决 | L0 事实源（零 LLM） | 直接答案 + 来源 | 不做推断 |
| U1 | 统计裁决 | L1 检验：显著性、效应量、置信区间、异常/漂移 | `supported / contradicted / inconclusive` | 不生成叙事结论 |
| U2 | 实验裁决 | 沙箱复现 + 6-TRADING 回测（walk-forward、成本/滑点、样本外），统一出口 `sandbox-exit` | 可复现证据包 + 45 裁决 | 不接交易热路径、不实盘下单；缺 seed / 版本 / 成本 / 样本外即阻断 |
| U3 | 三角验证 | 18-数据获取中心多源采集（DataRecord 校验/去重）+ 20 清洗 + 33-REA 逆向解析结构事实；`cross-source-reconcile` 自动对账 | 多源一致性报告 + 代码/文档事实 | 不以单一来源定论；同源转载只计 1；字段冲突不强行多数决 |

#### 3.6.2 裁决协议（`UncertaintyVerdict`）

> `UncertaintyVerdict` 是**证据信封**，不是第三套裁判体系：它上承 L0/L1/实验证据，下接统一 PoE（`SPEC-Unified-PoE-Framework.md`）与 45 业务门禁。重型 PoE 仍产出 `poe_score`；本契约只回答"证据够不够、结论是什么"。

```ts
interface UncertaintyVerdict {
  claim: string;                     // 待验证命题，必须可证伪
  level: "U0" | "U1" | "U2" | "U3";
  methods: string[];                 // 统计检验 / 沙箱 / 回测 / 采集对账 / REA
  evidence_refs: string[];           // 证据版本绑定，缺失即 inconclusive
  sample_size?: number;
  effect_size?: number;
  confidence: number | null;         // 缺失写 null，不填 0 冒充
  verdict: "supported" | "contradicted" | "inconclusive" | "needs_human";
  poe_score?: number;                // 证据进入 PoE 时的评审分（≥0.7 才可晋级）
  dissent: string[];                 // 反方证据 / 未解释残差
  replayable: boolean;               // 能否按 trace_id 重放
}
```

**硬规则**：

1. `verdict` 不得由生产模型单独给出；U1 以上必须附可复算证据；
2. 证据不足一律 `inconclusive`，不得用置信度阈值"凑通过"；
3. U2 只能调用 6-TRADING 的只读/回测能力，交易热路径零接入（红线 R4）；
4. U3 至少两个独立来源；同源转载只计 1 个；
5. 裁决结果进入认知系统成为案例，而不是只留在会话里；
6. 与 PoE/45 的映射：`supported → 进入 45`；`contradicted → 驳回`；`inconclusive → 补证据`；`needs_human → 人工门`。三者不得给出相互矛盾的结论。

#### 3.6.3 与门禁的关系

- 低风险门可由 U0/U1 支撑；
- **涉及交易、策略、参数或因果主张**的验收门至少 U2：没有沙箱/回测证据不得通过；
- 研究、文档、代码类验收至少 U1 + 可复算证据，不强制回测；
- 策略变更、参数调整必须 U2 + 45 硬门；
- 裁决 `inconclusive` ≠ 驳回，进入 `needs_human` 或补证据，绝不放行。

### 3.7 广义认知、残差记忆与反思进化（核心差异化能力）

> **会做一次不算能力；做错一次能记住、做对一次能复用、下次能提出更好的架构，才是。**

#### 3.7.1 广义认知系统（35）

- `record / recall / verify / search / knowledge-ingest` 五通道；
- 认知记录绑定证据版本与来源，过期即降级，不做过期内容的"权威"；
- 写操作只在编排侧（Mandate），Worker 只读。

#### 3.7.2 残差记忆器（RMD）

> 只保留**不可由基础模型、单一事实源或现场求解再推导**的信息。

| 维度 | 口径 |
| --- | --- |
| 准入 | 四禁入 / 四残差 / 三测试（见 `35-广义认知系统协作模块/SPEC-ResidualMemory-Admission.md`） |
| 形态 | M1 指针（硬上限 150 条）/ M2 联想 / M3 零记忆（现场重建） |
| 求解 | D0—D4 级联：确定性定位 → 按需重建；能用 REA 直接解的不查记忆 |
| 过期 | 事件驱动治理：`subclass` + `source_anchor` 复核 + `verify_state`（SPEC-ResidualMemory v1.5 §3.7′）；`residual-forgetting` 产出 keep / demote / archive_trace。FSRS 时间调度不再作为判据；删除测试集未建立前只降级不物理删除 |

价值：降低"记忆污染"，同时把上下文成本压到最低；记忆不再是"越多越好"，而是"越不可推导越值得存"。

#### 3.7.3 反思进化（48 涌现架构 + hermes）

- 每次任务结束产出反思：哪里判断错、哪类证据缺失、哪条规则该改；
- 实验必须**预注册**（指标、样本、阈值先定），防止事后挑指标；
- 晋级判据采用**相对阈值**：`selection_gap / mean_inner_score > 0.2` 或 `leakage_free=false` 判 rejected；`mean_inner_score ≤ 0` 直接 rejected（`selection_gap > 0.1` 的绝对阈值已废弃）；
- 进化产出的是**提案**：架构优化、SKILL 修订、阈值调整；必须走 S→A→门禁，不得自批。

#### 3.7.4 闭环

```
任务 trace → 残差准入 → 反思（hermes/48） → 假设 → 沙箱/回测（U2）
   → UncertaintyVerdict → 验收门 → settle 回认知系统 → 下次 recall
```

两个能力互相喂养：**不确定性裁决产生高质量案例，残差记忆与反思让下一次裁决更快、更准、更便宜。**

---

## §4 编排平面：DreamOS SACG

### 4.1 四层语义（新口径）

| 层 | 语义 | 核心组件 | 不做什么 |
| --- | --- | --- | --- |
| S | 认知驱动规划入口 | 意图深化、Spec/Plan | 不直接执行业务 |
| A | OKR 节点验收 | `okr_nodes` / `okr_acceptance` / `okr_ticket_bridge` | 不拥有执行 |
| C | 执行驱动 | GraphExecutor / Reflector / Aggregator | 不判定完成 |
| G | 压缩沉淀 | GraphStore / Checkpointer / Compressor | 不篡改事实 |

C-drive 贯穿 S→A→C→G：judge 模式做事后裁决，supervisor 模式做派工与终止；开关 `CDRIVE_SUPERVISOR` 默认关，关断字节等价。

### 4.2 Ticket / Mandate

- Ticket 四态：`live / paused / waitsForPerson / ended`；`paused` 与 `waitsForPerson` 不占 Worker 槽；
- Mandate = 能力授权 + 预算上限；写工具必须持有 Mandate；
- Worker 默认只读；交易类工具只能 `human / deny`，禁止自动放行；
- 每次判定（含放行）必须可审计。

### 4.3 预算与沉淀

- `GlobalBudgetManager` 统一记账，超预算降级为 L1 事实回答或拒答；
- settle 回写 L0：认知经验、SKILL、知识、文档、索引五系统；
- 未过门禁的产出不得沉淀、不得上线。

### 4.4 两项能力在 SACG 中的挂载点

| SACG 层 | 不确定性裁决 | 认知 / 残差 / 进化 | 硬约束 |
| --- | --- | --- | --- |
| **S 规划** | 必须声明 `claims[]` 与所需 U 级（U0–U3）；高风险命题不得只写"待确认" | `fetchContext` 召回历史 verdict、残差指针、相关案例 | S 不产 verdict，只发起命题 |
| **A 验收** | 调 `Adjudicator` 生成/读取 verdict；`inconclusive` → `waitsForPerson` 补证据 | 用历史案例校验 OKR 判据是否重复踩坑 | A 不得自证，Adjudicator 只读证据 |
| **C 执行** | U2 沙箱/回测作为异步 job（`paused waiting_job`），U3 采集/REA 异步 | 执行只产 `evidence_ref` 与 trace | 不接交易热路径；Worker 无裁决权 |
| **G 沉淀** | verdict 绑定 `evidence_ref + run_id` 落 L0 | 残差准入（四禁入/四残差/三测试）→ record → 48 反思 → 提案 | settle 是唯一写入口；提案必过门禁 |

**Ticket / Mandate 约定**：

- Ticket 的 `objective` 增加 `claims` 与 `required_verdict_level`；
- Mandate 同时授权"证据工具"与"裁决读取"，**不授权裁决写入**；裁决写入由 A 层服务身份执行；
- U2 计算成本计入 Ticket 预算，超预算不得降级为"无证据通过"，只能 `needs_human`；
- `paused` 子因增加 `waiting_verdict`（等待 U2/U3 证据或裁决）。

---

## §5 执行平面：DSH Superagent

### 5.1 七层目标架构

入口层（事件网关）→ 编排层（Router）→ 契约层（OKR/Ticket/Mandate）→ 执行层（Worker）→ 认知层（L0 六维供给）→ 验收层（45 + Watchdog）→ 沉淀层（settle）。

### 5.2 运行约束

| 约束 | 内容 |
| --- | --- |
| Router | 常驻但无状态，每轮从 L0 读快照 |
| Worker | 按角色分池，单角色工具数 ≤ 10（硬上限 15） |
| 隔离 | 子代理隔离执行、互不通信、只回摘要 |
| 续跑 | `thread_id + 续跑锚点`，同一 Thread 后续事件可直送原 Worker |
| 并发 | ≥3 个 Ticket 并行且互不阻塞 |
| 退出 | loop 结束只允许返回 `stop_reason` 结构 |

### 5.3 插件生态（工程层）

- 载体：Cordis 插件 + `dream-harness-bridge`；
- 契约：`inspect / experiment / install / unload` 四操作；
- 硬约束：`install` 必须 `rollback_verified=true`；`experiment` 磁盘写入必须为 0；`unload` 必须回滚订阅/连接/句柄/定时器四类副作用；
- 准入：无 manifest、无回滚、无权限声明一律拒绝；
- 现状：inspect 可用；install 未开放（P4）。

### 5.4 已知缺口

| 缺口 | 影响 | 计划 |
| --- | --- | --- |
| 无 `l2.dsh.mcp` 只读壳 | 外部宿主无法观察 Router/Ticket | P2 |
| 会话续跑未全量验证 | 长任务断点恢复不可靠 | P3 |
| 插件 install 未开放 | 生态只能"看"不能"装" | P4 |
| L2 认知裁决未实现 | `l2_route` 仅存在于契约 | P1（与 §5.5 裁决服务不是同一件事） |

### 5.5 两项能力在 DSH 七层中的挂载

| DSH 层 | 职责 | 不做什么 |
| --- | --- | --- |
| ① 入口（事件网关） | 事件可携带 `claims` 提示与期望 U 级；零 token 分流 | 不裁决、不判真伪 |
| ② Router | 按能力标签把 U2/U3 任务路由到沙箱/回测/采集 Worker；聚合结果 | 不生成 verdict，不持有状态 |
| ③ Ticket / Mandate | `objective` 含 `claims + required_verdict_level`；`waiting_verdict` 为 paused 子因；预算含 U2 计算 | 不由 Worker 扩权拿裁决写权限 |
| ④ Worker | 产证据包（日志、指标、diff、回测报告、采集记录），只读工具 | 不自证、不写 verdict、不写认知 |
| ⑤ 认知层 | `fetchContext` 六维供给追加：历史 verdict、残差指针、相似案例 | 不把缓存当权威 |
| ⑥ 验收层（45 + Watchdog） | Watchdog 查"证据缺失/指标漂移/越权"；45 消费 verdict 做业务裁决 | Watchdog 不改任务、不代批 |
| ⑦ 沉淀层（settle） | 唯一写入口：verdict → L0；残差准入 → 35；反思 → 48 提案 | 未过门禁不沉淀 |

**跨层规则**：

- verdict 是**证据的结论**，不是 Worker 的自我评价；DSH 侧 FAIL-OPEN 只影响"是否继续执行"，不影响"是否通过验收"；
- U2 长任务必须走 `waiting_job` 异步唤醒，禁止忙轮询；
- 认知 recall 只做"提示"，最终判据仍来自 L0/L1 与本次证据；
- 进化提案由 settle 生成 Ticket，进入普通门禁流程，不使用"系统身份"直改。 

---

## §6 治理平面：Agent 工作管理（飞书制度内化）

### 6.1 核心命题

> **不是接入飞书，而是把飞书的员工管理与公司管理制度，直接内生化到 Agent 的工作与推理流中。**

Agent 应该像员工一样工作：有目标、有分工、有审批、有验收、有复盘。区别只是——人用会议与邮件，Agent 用事件与门禁。

### 6.2 制度映射

| 传统制度 | 失效模式 | DreamOS 原生落地 |
| --- | --- | --- |
| 目标对齐（OKR） | 做偏、做完才发现 | `objective + KR`，Spec 门确认 |
| 分工与不相容职务分离（SoD） | 自批、自审、自证 | 角色表 + `deny_same_person/group/agent` |
| 分级授权 | 小事也审批、大事没人批 | 风险分级 + 两种模式 |
| 双人复核（four-eyes） | 单点误判 | 会签 + 异构模型双票 |
| 三单匹配 | 说的、做的、验的不是一件事 | 证据版本绑定 `evidence_ref` |
| Stage-Gate | 带病进入下一阶段 | 五道门阻断下游 |
| 例外管理 | 例外变成惯例 | 驳回必填原因 + 回转 + 升级 |
| 审计追踪 | 无法复盘"谁批的" | 事件 SSoT + 预审审计 |
| Andon 停线 | 发现问题不敢停 | 409 阻断 + 待办中心 |

### 6.3 五道门

| 门 | 风险 | 看什么 | 全权模式 | 人工干预 |
| --- | --- | --- | --- | --- |
| intent | low | 意图理解是否正确 | 自动确认 | 人工 |
| spec | medium | 目标/范围/验收标准 | 自动确认 | 人工 |
| dispatch | medium | 派谁、给什么权限 | 自动确认 | 人工 |
| **acceptance** | **high** | 证据是否齐全、KR 是否通过 | **必须人工** | **人工** |
| summary | low | 结论是否可交付 | 自动确认 | 人工 |

### 6.4 GatePolicy（可配置，不写死）

```json
{
  "gate_id": "acceptance",
  "kind": "acceptance",
  "mode": "human | autonomy",
  "auto_approve": false,
  "human_required": true,
  "applies_to": { "task_types": ["trading_analysis"], "risk_levels": ["high"], "change_class": "normal" },
  "approver": { "roles": ["owner", "risk_reviewer"], "quorum": "all", "min_distinct": 2 },
  "gate_model": { "class": "gate", "model_ids": ["qwen4-max", "jev-latest"], "quorum": "all", "min_distinct_models": 2, "deny_same_family": true },
  "sod": { "deny_same_person": true, "deny_same_group": true, "deny_agent_self_review": true },
  "evidence": { "required": ["spec", "test", "stats"], "min_count": 2 },
  "sla": { "hours": 24, "on_timeout": "escalate" },
  "escalation": { "to": ["risk_reviewer"], "fallback": "block" },
  "rejection": { "comment_required": true, "rewind_to": "spec" },
  "audit": { "immutable": true, "retention_days": 365 }
}
```

### 6.5 模型分工（三类，足够）

| 类 | 职责 | 当前模型 | 约束 |
| --- | --- | --- | --- |
| worker | 干活：生产、研究、报告 | `deepseek-v4-pro` | 不审批、不自证 |
| judge | 判定：S/A 层判定与聚合 | `deepseek-v4.1-flash` | 不写、不执行 |
| gate | 门禁预审：只读判断 | `qwen4-max` + `jev-latest` | 双模型异构会签；失败 → `needs_human` |

> **三类是"模型类"，不是模型个数**：gate 类内保留两个异构实例用于会签，不构成第四类；不再新增模型类。

**模型级 SoD**：gate 必须与 worker / judge 异构；主副 gate 之间也必须异构。JEV 只判断"完成度/质量"，不判断市场方向。

### 6.6 两种运行模式

- **人工干预（默认）**：五道门全部人工；
- **全权**：低/中风险自动确认并留痕，验收门永远人工；
- 模式由 `GATE_MODE` 控制；自动确认写入 `decided_by=mode:autonomy`；
- 证据变化后门禁回到 waiting，再按当前模式处理。

### 6.7 执行点（已落地）

| 执行点 | 行为 |
| --- | --- |
| 任务看板 `GateBar` | 通过 / 驳回（必填原因）/ 机器预审 / 模式徽标 |
| `POST /api/task/[id]/gate` | 证据过期 409、角色不符 403、幂等 |
| `POST /api/agent/chat` | 带 `task_id` 且有 pending 门禁 → 409，模型不调用 |
| `GET /api/gates/pending` | 待办中心数据 |
| `/dashboard/gates` | 按风险排序的待办列表 |

### 6.8 防黑箱 / 防漂移七条

1. **讲做分离**：模型可以解释，但不能决定是否放行；
2. **证据绑定**：每次确认绑定证据版本，证据变了确认作废；
3. **事实优先**：`stage` 只反映实际做到哪，门禁不篡改进度；
4. **不可匿名**：审批必须记录主体，Agent 不得自批；
5. **高风险保留责任人**：high / critical 验收门至少 1 个人类席位；其余席位可由异构 Agent 担任（§6.9.8）；
6. **全链路可回放**：`trace_id` 贯穿 S→C→A→G；
7. **失败即阻塞**：模型/预审异常一律 `needs_human`，不放行。

### 6.9 GateFlow：把飞书流程定义内化为可执行制度

> **要内化的不是飞书表单，而是「流程定义 + 运行状态机」这套控制语义。**

#### 6.9.1 三层内化（防止"改流程 = 改制度"）

| 层 | 飞书对应 | DreamOS 对应 | 变更权限 |
| --- | --- | --- | --- |
| 制度层 | 审批模板 / 制度文档 | Policy Template（标准 / 高风险 / 紧急 / 热修） | 只能走版本评审，前端不可随意改 |
| 流程层 | 审批流程设计器 | `GateFlow`（节点、条件、会签、时限） | 前端可配，必须过校验器 |
| 运行层 | 审批实例 / 操作日志 | `GateRun` + 事件流 | 只追加，不改写 |

制度层决定**必须控什么**，流程层决定**怎么控**，运行层只记录**实际怎么发生**。

#### 6.9.2 GateFlow v0.1

```ts
type GateNodeType = "gate" | "condition" | "parallel" | "cc" | "timer" | "terminate";

interface GateFlow {
  flow_id: string;
  version: number;                       // 运行实例绑定版本，升级不追溯
  status: "draft" | "active" | "archived";
  applies_to: { task_types: string[]; risk_levels: RiskLevel[] };
  entry: string;
  nodes: GateFlowNode[];
  guardrails: {
    must_end_with: "acceptance";         // 所有路径必须以验收门结束
    forbid_skip_high_risk: true;
    max_nodes: 12;
    max_gates: 5;
  };
}

type GateFlowNode =
  | { id: string; type: "gate"; gate: GatePolicy; next: string | null }
  | { id: string; type: "condition"; when: ConditionExpr; then: string; else: string }
  | { id: string; type: "parallel"; branches: string[]; join: "all" | "any"; next: string }
  | { id: string; type: "cc"; to: string[]; next: string }
  | { id: string; type: "timer"; hours: number; on_timeout: "remind" | "escalate" | "block"; next: string }
  | { id: string; type: "terminate"; reason: string; admin_only: true };
```

`next: null` 表示该门是终点（只能是验收门）。

`ConditionExpr` 只允许读取**事实字段**（`risk_level / task_type / change_class / evidence_count / kr_verdict`），禁止自由文本或 LLM 判定——条件必须是可确定性求值的，否则流程本身变成黑箱。

#### 6.9.3 运行状态机与事件

`GateRun` 绑定 `flow_id + version + task_id + trace_id`，状态在 `running / waiting_human / waiting_timer / completed / terminated` 之间流转。全部变更以事件落 append-only 流：`flow.started`、`node.entered`、`node.approved`、`node.rejected`、`node.delegated`、`node.signer_added`、`node.signer_removed`、`node.rewound`、`node.cc`、`sla.reminded`、`sla.escalated`、`flow.terminated`、`flow.completed`。

#### 6.9.4 十二条编译期校验（不通过不得 active）

| # | 规则 | 防的是什么 |
| --- | --- | --- |
| 1 | 所有路径必须终于 `acceptance` | 绕过验收 |
| 2 | risk 为 high / critical 的路径必须含人工门 | 机器自动放行 |
| 3 | 无环，节点 ≤ 12，gate 节点 ≤ 5 | 流程失控膨胀 |
| 4 | `condition` 只能引用事实字段 | 条件黑箱 |
| 5 | 转交仅限人 → 人，且高风险验收门禁止转交 | 责任稀释 |
| 6 | 加签使该门既有批准失效，需重新计票 | 假会签 |
| 7 | 退回只能退到祖先节点，且下游状态全部失效 | 状态说谎 |
| 8 | 终止仅管理员可触发，必须写原因并留痕 | 静默终止 |
| 9 | 审批人为空必须升级 + 阻塞，不得自动通过 | 空节点放行 |
| 10 | 任何超时只能是 remind / escalate / block | 超时自动通过 |
| 11 | `cc` 不计入票数、不阻塞 | 抄送干扰裁决 |
| 12 | 同一 actor 重复批准不计入 quorum | 自批凑票 |

#### 6.9.5 飞书原语 → GateFlow 对照

| 飞书原语 | GateFlow 落地 |
| --- | --- |
| 会签 / 或签 / 依次 | `approver.quorum = all / any / sequential` |
| 条件分支 | `condition` 节点 + 事实字段 |
| 并行分支 | `parallel` 节点 + `join` |
| 前 / 并 / 后加签 | `node.signer_added` 事件 + 既有票失效 |
| 转交 | `node.delegated`，人 → 人，留痕 |
| 减签 | `node.signer_removed`，不得减空 |
| 退回 | `node.rewound` + 下游失效 |
| 终止 | `terminate` 节点，仅管理员 |
| 抄送 | `cc` 节点，不计票不阻塞 |
| 审批人为空 | 升级 + 阻塞，禁止自动通过 |
| 限时 / 催办 | `timer` 节点 + `sla.reminded` 限流 |
| 字段权限 | 门禁卡片按角色裁剪可见字段 |
| 自动化触发 | 事件触发 `GateRun`，不触发审批结论 |
| OKR 打分 | 仅 KR 打分，O 由 KR 加权推导 |

#### 6.9.6 OKR 内化

- **O 不允许手工填进度**，只能由 KR 加权推导；
- 每个 KR 双评分：`self_score`（Worker）+ `review_score`（验收人/门禁）；
- 两者差异 > 0.2 → 强制复核，不允许取平均；
- 任务目标必须能回溯到上层目标（Episode / 策略），对齐字段必填。

#### 6.9.7 反模式（硬禁止）

| 反模式 | 后果 | 拦截点 |
| --- | --- | --- |
| 流程即代码 | 改流程等于改制度 | 三层内化 + 校验器 |
| 无限加签 | 审批永不收敛 | `max_nodes` / `max_gates` |
| 超时自动通过 | 静默旁路 | 校验规则 10 |
| 空审批人自动过 | 无主审批 | 校验规则 9 |
| 退回不回滚下游 | 状态失真 | 校验规则 7 |
| 机器票单独放行高风险 | 假验收 | 校验规则 2 + §6.8 第 5 条 |

#### 6.9.8 Agent 也是治理主体（数字员工）

> **Agent 不是"被审批的工单"，而是持席位、有角色、要担责的数字员工。**
> 治理协作不只在人之间发生，也在异构模型之间发生：多个模型各自持席位，按制度投票、会签、复核。

| 维度 | 人类席位 | Agent 席位 |
| --- | --- | --- |
| 身份 | `email` | `agent:<id>` + `model_id` + `family` |
| 授权 | 环境变量角色表 | 角色 + 能力集（只读证据） |
| 计票 | 一人一票 | 一席位一票，**同一模型多实例只计 1 票** |
| SoD | 生产者不得批准自己的门 | Agent 不得批准自己或同一 `run_id` 产出的门；且模型家族须与生产者异构 |
| 高风险 | 责任人 | 验收门保留**至少 1 个人类席位**作为责任人，其余席位可由异构 Agent 担任 |
| 审计 | `decided_by` | `decided_by=agent:<id>` + `model_id/family/prompt_version` |
| 停线权 | 可拉 Andon | Worker 可主动 `blocked`，不扣分、进待办 |

**Agent 席位的三条硬约束**（来自 §6.8 与模型级 SoD）：

1. 不得自批：`seat.agent_id != producer.agent_id`，同一 run 的产出不可由该 run 的 Agent 批准；
2. 不得同源会签：两个 Agent 席位若同 `provider + family`，只计 1 票；
3. 不得越权：Agent 席位只读证据，无写能力、无工具调用，输出不合规 → `needs_human`。

**协作形态**：低/中风险门可由 Agent 席位独立裁决（绑定票）；高风险验收由「1 个人类责任人 + N 个异构 Agent 复核席」组成，会签结论仍需人类责任人落票——这既是"把 Agent 当人"，也保留最终问责点。

#### 6.9.9 减法：治理要有效，不要繁琐

> 门禁的目标是防黑箱，不是制造流程负担。繁琐会直接催生橡皮图章。

| 简化项 | 做法 | 收益 |
| --- | --- | --- |
| 门数按风险伸缩（P1） | 目标：低风险/标准变更只走 `intent + acceptance`；`summary` 默认只抄送。P0 先提供批量确认 | 为后续减门留接口 |
| 合并确认 | 同一证据版本下，低/中风险相邻门可一次批量确认（一次审阅、一次落票） | 低风险任务少点多次 |
| 会签降噪 | low/medium `any`；high `all` 但只要求 2 个不同席位（Agent 可占席） | 避免"凑人头" |
| 提醒限流 | 每门最多 1 次提醒；超时直接升级，不反复催办 | 降低审批疲劳 |
| 抄送不阻断 | `cc` 只通知不计票、不阻塞 | 知情权与决策权分离 |
| 不做的事 | 不做表单级逐字段审批、不做飞书表单同步、不要求每个动作配专属复核人 | 避免制度外壳 |

#### 6.9.10 与五道门、GatePolicy、双模式的关系

- `GatePolicy` 定义**单道门**的授权与证据要求；
- `GateFlow` 定义**门与门之间**的顺序、分支、并行、加签与超时；
- `GateRun` 记录**一次实际运行**；
- 双模式决定"哪些门可自动确认"，`GateFlow` 不得改变该结论（自动确认只能作用于 low/medium，验收门永远保留人工/人类责任人席位）。

### 6.10 治理缺口

| 缺口 | 影响 | 优先级 |
| --- | --- | --- |
| GateFlow DSL / 校验器 / 运行时未落地 | 流程仍硬编码在五道门 | P0 |
| SLA / 升级未接入 | 待办可能长期滞留 | P0 |
| 空审批人兜底缺失 | 无主门禁可能静默卡死 | P0 |
| `terminate` / `rewind` 只记录不执行 | 驳回后需人工重派，终止不生效 | P0 |
| 会签仅在预审展示 | 人工票未强制多角色 | P1 |
| 转交 / 加签 / 抄送缺失 | 无法复现真实组织审批 | P1 |
| reviewer groups / 角色池缺失 | 审批人只能逐个指定 | P1 |
| OKR 对齐与双评分缺失 | 目标无法回溯，自评分虚高 | P2 |
| 字段级 ACL 缺失 | 敏感证据对无权限角色可见 | P2 |
| 通知未接 | 审批到达率依赖主动查看 | P2 |
| 流程模板库 / 审批效率分析缺失 | 每次重配，无法治理橡皮图章 | P2 |

---

## §7 生态平面

### 7.1 DSH 工程插件

- 目标：能力可插拔、可回滚、可审计；
- 准入：manifest + 权限声明 + 回滚验证；
- 运行：沙箱实验 → 只读 inspect → 授权 install → 可 unload；
- 红线：实验期不得落盘；install 不得绕过 Mandate。

### 7.2 MCP 能力系统

- 三层出口：`l0.* / l1.* / l2.*`，统一信封与配额；
- 外部宿主：Hub-and-Spoke，Agent Runtime 为 Hub，MCP Server 为 Spoke；
- 安全：默认 deny、最小权限、凭据不落日志、第三方数据最小化；
- 版本：正式弃用策略，禁止静默破坏。

### 7.3 交易协议实盘验证（差异化能力）

- 链路：假设 → 回测（统计显著）→ 模拟盘 → 实盘门 → 监控 → 归因 → 基因组沉淀；
- 实盘门：必须同时满足人工审批 + 风险复核 + 45 门禁 + Mandate；
- 热路径零接入：团队只产出研判与方案，不下单；
- 急停：Andon 式 kill switch，任一异常可阻断整条链路；
- 现状：协议与验证框架已有，实盘门待接入（P2）。

---

## §8 四条端到端主链路

### 8.1 研判链路

```
触发 → S1 意图 → [intent 门] → S2 Spec → [spec 门]
→ C1 派工 → [dispatch 门] → C2 Worker 并行 → C3 裁决
→ A1 OKR 验收 → [acceptance 门·人工] → G1 简报/研报 → [summary 门] → settle
```

判据：任一必需维度缺失 → `partial`；KR 缺证据 → FAIL；未过验收不得进入 G。

### 8.2 开发修复链路

```
L1 发现/bug 报告 → RepairLedger(reported) → L2 修复 → 回归/45
→ fixed → settled（case/cognition/process/doc 四项齐全）
```

判据：发现来源必须是 L1 或显式 bug；回归 runner 只能是 pytest/ci/gate45；优化类需 45 PASS 或统计显著。

### 8.3 交易验证链路

```
假设 → 回测（n≥30, p_adj≤0.05）→ 模拟盘 → 实盘门（人工+风险+45）
→ 实盘监控 → 归因 → 基因组/案例库
```

判据：未过实盘门不得下单；实盘异常自动回退模拟盘并留痕。

### 8.4 不确定命题裁决与认知沉淀链路

```
S 声明 claim + required_level
→ C 取证（L0/L1 → U1；沙箱/回测 → U2；18/REA → U3）
→ A Adjudicator 产 UncertaintyVerdict（supported / contradicted / inconclusive / needs_human）
→ [acceptance 门] → G settle（残差准入 → 认知 record → 48 反思）
→ 进化提案 → 新 Ticket → 下一轮 S recall
```

判据：U2 只在沙箱/回测证据齐全时可 `supported`；`inconclusive` 必须补证据或转人工，不得放行；提案未过门禁不得改生产。

---

## §9 非功能与治理

| 维度 | 要求 |
| --- | --- |
| Fail-closed | 门禁模型异常、插件未授权、预算不足、角色未知 → 拒绝或 needs_human |
| SoD | 生产与审批异构；主副 gate 异构；Agent 不得自审 |
| 审计 | 门禁决策、模型预审、插件安装、实盘操作全部 append-only |
| 可观测 | trace_id 贯穿；span 八段；loop 结束必须 `stop_reason` |
| 安全 | 密钥只进 env；第三方只发结构化摘要；插件沙箱 |
| 成本 | token 与预算同源；单 Ticket 可核算 |
| 回滚 | 插件四类副作用可回滚；门禁证据版本可回退 |

---

## §10 调研评估

### 10.1 外部对标

| 参考 | 结论 | 对本系统的启示 |
| --- | --- | --- |
| Agentic OS | 操作系统需管理进程、内存、权限、资源、调度、安全 | 我们的四平面已覆盖，但"资源/调度"仍偏弱 |
| 生产级 Agent 架构 | Plan-and-Execute + ReAct + 多 Agent + HITL 组合 | 与 SACG + DSH 一致；HITL 必须默认开启 |
| Claude Code Harness | 权限系统、压缩管线、四类扩展机制、子代理编排、追加式存储 | 我们的门禁与插件方向正确，压缩与权限模式可借鉴 |
| MCP 2026 | 无状态核心、MCP Apps、Tasks、OAuth 对齐 | 能力面应保持无状态、可水平扩展；长任务用 Tasks 语义 |
| 企业 Agent 管控平台 | 统一接入第三方 Agent，集中配置知识/模型/MCP/安全 | 我们的治理平面可扩展为"多 Agent 统一管控" |

### 10.2 我们真正的差异

1. **四平面闭环**：能力、编排、执行、治理不是拼装，而是同一事实源上的闭环；
2. **不确定性裁决**：U0–U3 四级阶梯把"说不准"变成可复算的证据，而不是更长的解释（§3.6）；
3. **认知与进化**：广义认知 + 残差记忆 + 涌现/反思，让系统越用越准且可解释为什么记、为什么忘（§3.7）；
4. **制度级门禁**：不是"加个确认按钮"，而是 SoD、会签、证据绑定、审计；
5. **交易实盘验证**：从假设到实盘再到归因，其他工具通常只到回测；
6. **L0–L2 证据链**：每个结论都能回到事实或证据，不靠模型自述。

### 10.3 成熟度矩阵

| 域 | 当前 | 目标 | 差距 |
| --- | --- | --- | --- |
| 能力平面 | L3 | L4 | L2Envelope 未全量统一；配额与版本治理待补 |
| 编排平面 | L3 | L4 | C-drive supervisor 默认关；settle 未全量 |
| 执行平面 | L2 | L4 | 无 l2.dsh.mcp；续跑与插件 install 未开放 |
| 治理平面 | L3 | L5 | SLA/升级/多角色会签未接；通知缺失 |
| 不确定性裁决 | L3 | L4 | 统一出口/对账/裁决链路已落地；运行时异步调度与 L0 权威事件尚待接线 |
| 认知与进化 | L3 | L4 | 残差准入 + 遗忘调度已落地；48 反思提案已接门禁 |
| 生态平面 | L2 | L4 | 插件只能 inspect；实盘门未接 |

### 10.4 五个关键风险

| 风险 | 说明 | 对策 |
| --- | --- | --- |
| 门禁被绕过 | 不带 `task_id` 的旧客户端可绕过 409 | 入口统一注入 task_id；缺省拒绝写操作 |
| 模型过度自信 | JEV 准确率未经真实基准验证 | 只作预审；high 门双票 + 人工 |
| 插件供应链 | install 可能带副作用 | 沙箱 + 回滚验证 + deny-by-default |
| 双状态漂移 | 前端/DSH 各自维护状态 | 事件 SSoT；前端只读 + 决策事件 |
| 实盘边界失守 | 验证链路误触下单 | 实盘门 + kill switch + 热路径隔离 |

---

## §11 落地路线

| 阶段 | 目标 | 判据 | 状态 |
| --- | --- | --- | --- |
| P0 | 契约收口 | L2Envelope 全量；门禁 SLA/升级；SSE 实时 | 部分完成 |
| P0.5 | 治理收口 | GateFlow DSL + 12 条校验器 + 运行时（condition/parallel/cc/timer/加签/退回）已落地；待接 API/UI | 部分完成 |
| P1 | 编排补壳 | `l2.dsh.mcp` 只读；认知路由落地；45 转硬门 | 未开始 |
| P2 | 插件与实盘 | inspect/experiment 可用；实盘门接入 | 未开始 |
| P2.5 | 差异化能力 | `UncertaintyVerdict` 服务；18 + REA 三角验证；残差记忆接入；48 反思提案接门禁 | 已完成（含异步 job / L0 事件 / 治理周期） |
| P3 | 自进化 | settle 全量；同类任务 recall 命中 | 未开始 |

**已完成（2026-11-18）**：五道门、GatePolicy、角色表、三类模型、Qwen + JEV 双票、全权/人工双模式、409 拦截、待办中心、任务看板 T0–T2；飞书工作流内化调研（RESEARCH-GATE v0.2 §2.6）；门禁相关 58 项测试全绿。

**P2.5 收尾口径**：T1.6 / T2.4 已在 P2.5 完成；T2.2 仅完成 settle 写入入口（Mandate 身份校验未做），T2.3 recall 指针解析未做。P1/P2/P3 为后续独立阶段，未启动。

---

## §12 验收清单

1. 任一任务四问可答，且来源可点击；
2. 任一结论有 `evidence_refs`，缺失标 `needs_review`；
3. 存在 pending 门禁时，带 task_id 的对话返回 409；
4. `GATE_MODE=autonomy` 只自动确认低/中风险，验收门仍人工；
5. gate 与 worker/judge 异构，主副 gate 异构，否则启动拒绝；
6. 门禁模型异常 → `needs_human`，不出现自动放行；
7. 证据变化 → 旧确认失效，门禁回到 waiting；
8. 审批记录含主体、时间、证据版本、意见；
9. 插件 install 必须具备回滚验证与权限声明；
10. 实盘操作必须同时有人工票、风险票、45 票；
11. trace_id 贯穿 S→C→A→G，span 可回放；
12. 关断开关后行为与旧路径等价；
13. 任一 GateFlow 的所有路径必须终于 `acceptance`，否则不得 active；
14. 超时、审批人为空、机器预审失败三种情况均不得自动通过，只能 remind / escalate / block / needs_human；
15. 加签使该门既有批准失效并重新计票；转交必须记录 `from / to / reason`；
16. `terminate` 仅管理员可触发且写原因，`rewind` 必须使下游状态失效；
17. Agent 席位可投绑定票，但不得批准自己 / 同一 run 的产出，同模型多实例只计 1 票；
18. 高风险验收门至少有 1 个人类席位；低/中风险门支持批量确认，验收门必须单独确认；
19. GateFlow 校验器必须拦截：环、非验收终点、超时自动通过、非祖先退回、空审批人、重复席位；
20. 高风险结论必须附 `UncertaintyVerdict`，U2 以上证据可复算；证据不足一律 `inconclusive`；
21. 认知写入必须过残差准入（四禁入/四残差/三测试），过期内容必须降级，不得冒充事实；
22. 进化提案必须预注册实验 + `selection_gap` 检查 + 过门禁，不得直接改生产。

---

## §13 维护

- 本文为**架构总纲**，版本变更需同步更新 §11 状态与 §10 成熟度；
- 分册继续维护细节：SPEC-56（L2 契约）、DESIGN-DSH（执行）、DESIGN-Q-TEAM（治理）、RESEARCH-GATE（制度依据）；
- 差异化能力的分册 SSoT：残差记忆见 `35-广义认知系统协作模块/SPEC-ResidualMemory-Admission.md`，涌现与预注册见 48-涌现架构，回测与交易计算见 6-TRADING，采集见 18-数据获取中心，结构事实见 33-REA 逆向解析；
- 任何新增能力必须先回答：属于哪个平面、SSoT 在哪、门禁是什么、失败怎么降级。

### 13.1 版本记录

| 版本 | 日期 | 变更 | 状态 |
| --- | --- | --- | --- |
| v1.0 | 2026-11-18 | 四平面 + 一生态总纲；§6 治理平面；§11 路线；§12 验收 | 定稿 |
| v1.1 | 2026-11-18 | 新增 §6.9 GateFlow；原 6.9 顺延 6.10；Agent 席位治理与减法 | 定稿 |
| v1.2 | 2026-11-18 | 新增 §3.6 不确定性裁决、§3.7 认知/残差/进化 | 评审中 |
| v1.2.1 | 2026-11-18 | 评审修订 4 项（U2 范围、相对阈值、18 采集边界、残差 TTL） | 通过 |
| v1.2.2 | 2026-11-18 | 新增 §2.4 / §4.4 / §5.5 / §14.1 架构挂载评审 | 通过 |
| v1.2.3 | 2026-11-18 | P2.5 生产化：U3 跨源对账、U2 沙箱统一出口、残差遗忘调度 | 通过 |
| v1.2.4 | 2026-11-18 | 运行时接线：异步裁决 job、L0 verdict 事件、治理周期 launchd、Ticket 唤醒桥 | 通过 |
| v1.2.5 | 2026-11-18 | 闭环补齐：记忆生产端、DSH 事件消费者、WatchPaths 触发 | 通过 |
| v1.2.6 | 2026-11-18 | settle 写入口：候选暂存 + 治理周期统一准入 | 通过 |

### 13.2 落地状态

- 落地清单：[TASKS-20261118-系统架构能力落地清单](./TASKS-20261118-系统架构能力落地清单.md)
- 已完成：W0 基线、W1 裁决闭环、W2 残差准入、W3 Ticket/Router/Watchdog/45、W4 预注册/阈值/提案桥、W5 trace/验收/文档
- P2.5 生产化：`3.1-FRONTEND/src/lib/verdict/cross-source-reconcile.ts`（U3 对账）、`…/verdict/sandbox-exit.ts`（U2 统一出口）、`…/cognition/residual-forgetting.ts`（遗忘调度），38 项测试通过。
- P2.5 运行时接线：`/api/verdicts/jobs`（U2/U3 异步 job）、`verdict.updated` 事件（SSoT，事件优先读取）、`/api/governance/cycle`（SLA + 遗忘计划，launchd 每日 03:30）、`34-前端应用训练系统/core/verdict_resume_bridge.py`（waiting_verdict 唤醒）。
- P2.5 闭环补齐：`/api/memory/records`（准入后写 `.data/memory/records.jsonl`）、`memory-records.ts`（锚点复核回写）、`verdict_event_consumer.py`（seq 游标增量消费，launchd `WatchPaths` 触发）。
- settle 写入口：`residual_memory_spool.py` 把有价值发现写入 `.data/memory/pending.jsonl`；治理周期 `ingestPendingCandidates` 统一准入（透传 sensitive/trajectory/derivable 等信号），拒绝项不落盘。
- 分册与代码入口见清单“产物索引”；本文不复制实现细节。

---

## §14 评审记录（2026-11-18）

**评审对象**：v1.2 新增 §3.6 不确定性裁决、§3.7 认知与进化。
**评审方式**：与代码/分册 SSoT 逐条事实核对 + 内部一致性检查；不引入外部厂商结论。
**审批结论**：**修订后通过（Conditional → Passed）**。4 处问题已修正，无阻断项。

| # | 级别 | 发现 | 证据 | 处置 |
| --- | --- | --- | --- | --- |
| R1 | 高 | "验收门至少 U2" 与五道门适用范围冲突：研究/文档/代码类验收没有回测 | §6.5 五道门、§12 验收 | 已改为"涉及交易/策略/参数/因果主张才必须 U2；其余至少 U1 + 可复算证据" |
| R2 | 高 | `selection_gap > 0.1` 是已废弃的绝对阈值 | `REVIEW-20261116-统计能力与算法系统-科研评审.md` DA-3；54-TECHNICAL_DESIGN 使用相对阈值 | 已改为 `selection_gap / mean_inner_score > 0.2` 或 `leakage_free=false` → rejected |
| R3 | 中 | "18 采集含清洗/交叉对账"过度声明 | 18-README：`DataRecord` 校验 + 去重；清洗属 20 | 已改为"18 采集 + DataRecord 校验/去重 + 20 清洗"，跨源对账标注为目标能力 |
| R4 | 中 | "分级 TTL" 暗示已生产接入 | `SPEC-ResidualMemory-Admission`：FSRS 仅测试引用、零调用 | 已标注为目标；当前默认只降级不删除；补 M1 硬上限 150 条 |

**未发现的问题（确认成立）**：
- 四禁入 / 四残差 / 三测试、M1/M2/M3、D0–D4 与 35 分册一致；
- 6-TRADING A0–A9 与回测引擎存在；45 评测系统存在；33-REA 与 18 采集模块存在；
- `UncertaintyVerdict` 已显式映射到统一 PoE（`poe_score`）与 45，不构成第三套裁判体系。

**遗留风险（不阻断，v1.2.6 已闭环）**：U3 对账、U2 统一出口、遗忘调度、异步 job、L0 裁决事件、治理周期、记忆生产端、事件消费者、settle 写入口均已落地。无新增阻断项；后续按运行数据校准宽限期、样本外阈值与 M1 上限。

### 14.1 架构挂载评审（SACG + DSH）

**评审问题**：两项新能力放在哪一层？会不会形成第五平面或第二事实源？谁产出、谁消费、谁写？
**审批结论**：**通过（Passed）**。结论是"横切服务带"，不是新平面；挂载点已写入 §2.4 / §4.4 / §5.5。

| # | 风险 | 判断 | 架构处置 |
| --- | --- | --- | --- |
| A1 | 新增能力导致平面膨胀 | 不成立 | 不新增第五平面；以横切服务带挂载，owner 分别为 L2-K Adjudicator 与 35/48 |
| A2 | 裁决权落到 Worker 或门禁模型 | 高风险 | Worker 只产 `evidence_ref`；verdict 由 A 层 Adjudicator 产出；门禁只消费 |
| A3 | DSH 与 L0 双写 verdict / 记忆 | 高风险 | 权威副本只在 L0/35/48；DSH 仅缓存；写入口唯一为 settle |
| A4 | verdict 与 PoE/45 三套裁判冲突 | 中 | verdict 是证据信封，映射 `poe_score` 与 45 四态，不另立裁决标准 |
| A5 | U2/U3 拖慢交易主链路 | 高风险 | 沙箱/回测/采集/REA 一律异步 job，`waiting_verdict` 唤醒；热路径零接入 |
| A6 | 进化提案绕过门禁直改生产 | 高风险 | 只出 Ticket 提案，走 S→A→门禁；不使用系统身份直改 |
| A7 | 残差记忆被 Worker 私写 | 中 | 认知写入只走 settle；Worker 只读 recall；写入过四禁入/三测试 |
| A8 | 证据更新后旧 verdict 仍被引用 | 中 | verdict 绑定 `evidence_ref + run_id`，证据变更自动失效并重裁 |

**落点摘要**：

- 能力层：L2-K 新增 Adjudicator 服务（不新增子层），初期经 `l2.dreamos.mcp` 暴露，稳定后再评估独立壳；
- 编排层：S 声明 claims/U 级，A 调裁决，G 沉淀，Ticket 增加 `required_verdict_level` 与 `waiting_verdict`；
- 执行层：Router 路由证据任务，Worker 只产证据，settle 唯一写认知；
- 治理层：验收门消费 verdict；`inconclusive` 进 `needs_human`，不得自动放行。
