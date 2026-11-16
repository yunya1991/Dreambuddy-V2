# REA 逆向解析：LobeHub 协议 × L2 能力聚合调度缺失（v0.1）

> **日期**: 2026-11-16 ｜ **方法**: 33-REA 静态分析（`l0.rea.mcp`）+ 只读代码核对 + 运行态产物计数
> **目标**: 用户命题「L2 基础能力已具备，核心是如何组织」——以 LobeHub 协议为参照，定位 L2 **能力聚合/调度**的真实缺失
> **证据等级**（SPEC-33）：`observation` 可直接复算 ｜ `derivation` 由事实推导 ｜ `inference` 模式判断 ｜ `unknown` 未验证
> **配套**: [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md)（能力登记）、[../../52-lobehub协议集成/SPEC.md](../../52-lobehub协议集成/SPEC.md)

---

## §0 结论（先看这五条）

1. **L2 缺的不是能力数量，而是「统一出口与统一调度语义」**。52 已经长出一套完整的协议层（模型路由 / MCP 消费 / PlanCard / 门禁评分 / CU 计量 / 插件 tab），DreamOS 已有一套内核（239 模块 / 12 端点 / 28 节点）。两套东西**结构上零耦合**（REA compare：common modules = 0），对接只靠 HTTP/stdio，因此「谁调度谁、成本怎么算、失败怎么表达」全靠文档约定。
2. **计量已经出现双轨，且从未在运行态落账**。52 用 CU 账本（7 个维度，reserve→settle），DreamOS 用 `GlobalBudgetManager`（tokens），`L2Envelope.tokens_used` 仍未实现。实测 `52/runtime/usage_ledger.jsonl` **不存在**——F4 计量只有代码，没有运行证据（GAP-17）。
3. **工具面聚合是「静态白名单」而非「运行时能力面」**。3.1 的 MCP 客户端是**单例单壳**（只连 cognition），4 个 tool profile 里 `trading_read/trading_proposal` 的 8 个工具在 registry 中并无对应壳注册，因此「能力聚合」目前只在 cognition 一个域成立（GAP-19）。
4. **两套循环语义不通约**。LobeHub 上游有显式停止原因（`done/error/interrupted/parked/cost_limit/max_steps`）；3.1 协议层只有 `stopWhen: stepCountIs(5)`；34-core 有 Ticket 四态。三者没有共享的 `stop_reason` 契约，导致「卡住/超预算/等人」在 trace 里不可区分（GAP-20）。
5. **可逆性仍不达标**。52 F5 已能 `dsh plugin add/remove` 并写审计（实测 30 条），但这是**包级启停**，未验证 ADR-10 要求的「订阅/连接/句柄/定时器」四类副作用回滚；53 侧仍无运行时 inspect/内存 experiment（GAP-21）。

> 一句话：**L2 现在像一个「零件齐全但没有总装线」的工厂**——能力都在，缺的是统一的信封（成本/证据）、统一的工具面（聚合）、统一的终止语义（调度）。

---

## §1 方法与证据

### 1.1 REA 分析对象（observation）

| 目标 | 语言 | 模块 | 项目内依赖边 | 环 | 函数 | 外部依赖 | snapshot_id |
|---|---|---:|---:|---:|---:|---:|---|
| `52-lobehub协议集成` | Python | 18 | 28 | 0 | 244 | 20 | `bb9c106bbbfd32fc` |
| `1-ARCHITECTURE/dreamos` | Python | 239 | 92 | 0 | 2855 | 86 | `c315b6c904379e2f` |
| `34-前端应用训练系统/core` | Python | 52 | 26 | 0 | 426 | 55 | `467a577eed73fc77` |

REA compare（`52` vs `dreamos`，feature=`agent orchestration protocol`）：**共同模块 0 个**；52 独占 18 模块 / dreamos 独占 239 模块。
→ `derivation`：两者**没有任何代码级复用**，集成面只能靠协议（HTTP / MCP / JSONL），这与 52 SPEC 的 A2「协议唯一性」一致，也意味着**任何能力语义不一致都不会被编译期发现**。

> 局限（原样保留）：REA 只做静态结构；动态 import、反射、运行时环无法覆盖；上游 `lobehub/lobehub` **本地无源码副本**，其协议语义引用 2026-11-11 源码级评审（[REVIEW-20261111](../../52-lobehub协议集成/REVIEW-20261111-LobeHub代码架构调研与SPEC评审.md)，含文件路径），标为「前次观察」，本轮未复验。

### 1.2 只读实测（本轮复跑，非文档声明）

| # | 检查 | 结果 | 证据 |
|---|---|---|---|
| 1 | 注册表 schema | `1.2-mcp` | `47/registry/mcp_capabilities.yaml` 首行 |
| 2 | 壳总数 / 声明工具 / 活跃工具 | 17 / 84 / **78**（2 个 deprecated 壳各 3 工具） | 逐壳解析 |
| 3 | L2 壳与活跃工具 | 5 壳 / **14** 工具（debate 3 + dreamos 5 + train 3 + emergence 3；`agent.debate` deprecated） | 逐壳解析 |
| 4 | 配额三件 | `max_tools_per_shell=15`、`max_tools_per_role=10`、`max_total_tools=80`；`layer_quota.total=120` | 同上 |
| 5 | 角色 | 12 个；`lobehub_frontend` **仅 1 个工具**（recall）；最大角色 10（engineer） | 同上 |
| 6 | 52 运行态 | trace 98 行 / outbox 141 行 / 桥游标 **95** / 指纹 58 行 | `orchestrator/traces/brainstorm.jsonl`、`bridge/.cursor`、`bridge/.seen` |
| 7 | 蒸馏积压 | outbox 141 − cursor 95 = **46 条待消费** | 同上 |
| 8 | CU 账本 | `52/runtime/usage_ledger.jsonl` **不存在** | 文件系统 |
| 9 | 插件审计 | `52/runtime/plugin_audit.jsonl` 30 行 | 文件系统 |
| 10 | 最新 trace 语义 | `route=debate`、`mode=debate`、`executed=false`、含 `mode_basis` | trace 末行 |
| 11 | 协议层循环 | `streamText(... stopWhen: stepCountIs(5))` | [chat/route.ts#L187-L216](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/app/api/agent/chat/route.ts#L187-L216) |
| 12 | 计量维度 | 7 维（llm_input/output、tool_call、tool_call_heavy、backtest_cpu、data_query、plugin_runtime） | [meter.ts#L27-L35](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/billing/meter.ts#L27-L35) |
| 13 | MCP 客户端 | 单例单壳，仅 cognition，30s 超时 / 60s 空闲回收 | [mcp-client.ts#L280-L286](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/agent/mcp-client.ts#L280-L286) |
| 14 | 工具 profile | 4 个（platform / trading_read / trading_proposal / admin），服务端注入 | [tool-profiles.ts#L43-L104](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/agent/tool-profiles.ts#L43-L104) |

复跑命令见 §8。

---

## §2 LobeHub 协议事实

### 2.1 上游协议语义（前次源码观察，2026-11-11）

| 协议件 | 上游事实 | 语义要点 |
|---|---|---|
| agent loop | `packages/agent-runtime/src/loop/index.ts` + `executors/`（callLlm / resolveTools / tool / subAgent / compressContext / humanApprove / finish） | 循环是可替换执行器的状态机，不是「一次 streamText」 |
| 停止原因 | `done / error / interrupted / **parked** / cost_limit / max_steps` | 「停」本身是协议字段，可审计、可续跑 |
| Proactive 调度 | `tasks.automation_mode = heartbeat \| schedule` | 定时/心跳是一等公民，且每次动作要过工具面 |
| Expertise | `expertise.ts`（Anchor/Backtest/Canon/Enforcement/InsightEvidence） | 经验闭环：候选→回测→固化→强化 |
| 记忆 / 目标 / 信号 | `userMemories`、`goal/graph/trace`、`signal/signalDecision` | 与 4-MEMORY、43、28 同构 |
| 多 agent | `groupOrchestration` + `chatGroup` | 角色编排有显式协作协议 |
| 异构 harness | `heterogeneous-agents` + `lobehub-gateway` | 外部 agent 作为一等参与者 |
| MCP 客户端 | `src/libs/mcp/client.ts` + `services/mcp.ts` | stdio 由 desktop 主进程执行；远程走 gateway；工具**按指纹同步 + 可见性控制** |

> `inference`：上游真正的「协议」不是某份 schema，而是 **loop + 停止原因 + 工具可见性 + 调度模式** 四件套。我们 52 抄了「模型路由 + MCP 消费 + PlanCard」，但只抄了其中一半。

### 2.2 我方协议层落点（代码事实）

| 能力 | 落点 | 事实 |
|---|---|---|
| 模型路由 | [providers.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/agent/providers.ts) | env 驱动，仅 `openai` / `openai-compatible` 两种；无 fallback 链、无成本感知路由 |
| MCP 消费 | [mcp-client.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/agent/mcp-client.ts) | 换行分隔 JSON-RPC 2.0；懒启动 + initialize 握手 + id 匹配 + 超时；**单例单壳** |
| 对话循环 | [chat/route.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/app/api/agent/chat/route.ts) | 先 L1 直答（16s 超时）→ 未命中再 `streamText`，最多 5 步；失败一律 FAIL-OPEN |
| 工具面 | [tool-profiles.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/agent/tool-profiles.ts) | 服务端按 `surface + entitlement` 选 profile 后过滤；前端不能自选 |
| PlanCard | [plancard.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/agent/plancard.ts) + 52 `schemas/plancard.schema.json` | `tool` 必须匹配注册表；`validation.evaluator_refs` 必填 |
| 双链脑暴 | 52 `orchestrator/brainstorm_orchestrator.py` | route → proposals → dedupe → diversity → gate(G1–G4) → score → T1–T4 → decision → trace/outbox |
| 门禁 / 评分 | [scoring.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/52-lobehub协议集成/orchestrator/scoring.py#L175-L224) | 纯确定性；G3 trade-exec 直接 BLOCK；G4 三档（动作/裸声明 BLOCK，描述/否定记 notes） |
| 意图路由 | [router.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/52-lobehub协议集成/orchestrator/router.py#L155-L244) | `r9-v1` 五分流，交易/高风险先于一切 |
| 计量 | [meter.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/billing/meter.ts) | CU 7 维；reserve（60×1.2=72 CU）→ settle；账本只追加 |
| 蒸馏 | 52 `bridge/distill_bridge.py` | R6 映射 fail-closed；游标防重读 + sha1 指纹防重写 |
| 插件 | 52 SPEC F5 + `/api/dsh/plugins/install` | `dsh plugin --profile sandbox add/remove`，白名单 + 核心保护 + 审计 |

### 2.3 协议消息流（当前真实链路）

```text
浏览器（唯一前端 3.1）
  → POST /api/agent/chat
      ├─ L1 直答：POST /api/data/query（decision=L1_DIRECT 才采用，零 token）
      ├─ 计量预扣：reserveCu(traceId, 60)            ← 仅内存
      ├─ profile：surface+entitlement → 5/11/13/7 个可见工具
      ├─ MCP：spawn cognition 壳 → tools/list → tools/call
      ├─ streamText(model, tools, stopWhen=5)
      └─ onFinish：settleReservation(usage) + maybeWriteSessionSummary(outbox)
  → POST /api/agent/brainstorm（spawn 52 编排器，180s 超时）
      → 双链提案 → G1-G4 → 结构分+45 → T1-T4 → trace/outbox
  → （定时）supervisor.py 22:30 → shadow_batch → distill_bridge
```

---

## §3 我方 L2 聚合/调度现状（结构事实）

| 维度 | 事实 | 来源 |
|---|---|---|
| 内核规模 | DreamOS 239 模块 / 2855 函数 / 12 个 `/api/v1/*` 端点 | REA + TECHNICAL_DESIGN §1.3 |
| 执行编排 | 34-core 52 模块 / 426 函数；Router 单轮八步 + Ticket 四态 + Mandate + 45 门禁 | REA + §2.2 |
| 协议层 | 52 18 模块 / 244 函数；编排器 + 桥 + ops | REA |
| 壳与工具 | 17 壳 / 78 活跃 / L2 14；L2 配额 30 | 实测 |
| 角色 | 12 角色；L2 相关 4 个（l2_analysis 7 / l2_trading_analysis 9 / l2_researcher 6 / l2_planner 4） | 实测 |
| 出口信封 | DreamOS `jsonify(result)`；MCP 壳 `envelope_version: 0.1`；3.1 `{ok,data,degraded,error}`；52 摘要 JSON | §4.1 |
| 成本 | DreamOS 预算（tokens）+ 52 CU 账本，**两套未通约** | 实测 |
| 调度 | 52 `supervisor.py`（每日 22:30，不跨重启）；DSH Router 单轮；DreamOS 无主动调度 | 代码 |

---

## §4 对照矩阵：LobeHub 协议件 × 52 × L2 内核

| 协议件 | 上游 | 52 协议层 | L2 内核（DreamOS/DSH） | 聚合判定 |
|---|---|---|---|---|
| agent loop | 可替换执行器状态机 | 5 步 `streamText`（硬编码） | Router 单轮八步（Ticket 驱动） | 🔴 **两套循环，无共同终止语义** |
| 停止原因 | 6 值显式枚举 | 无（只有 MAX_STEPS 隐式） | Ticket 四态 + paused 子因 | 🔴 不可通约（GAP-20） |
| 工具可见性 | 指纹同步 + 可见性控制 | profile 白名单（静态） | registry 角色（静态） | 🟡 两处静态，无运行时同步（GAP-23） |
| 工具聚合 | 多 MCP server 并行 | **单例单壳**（只 cognition） | 17 壳 / 78 工具（进程内） | 🔴 工作台只能看见 1/17（GAP-19） |
| 模型路由 | RouterRuntime + 50 provider + 成本/能力元数据 | 2 类 provider，无 fallback | 无（LLM 外挂） | 🟡 可用但无成本感知 |
| 计量/成本 | cost_limit + usage | CU 7 维 + ledger（**零落账**） | 预算 tokens | 🔴 双轨（GAP-17） |
| 调度模式 | heartbeat / schedule | supervisor 每日一次 | 无常驻调度 | 🟡 不可跨重启（GAP-22） |
| 插件生命周期 | inspect / experiment / install / unload | add / remove + audit | 53 静态白名单 | 🟡 包级可逆，副作用未验（GAP-21） |
| 上下文压缩 | compressContext executor | 无 | 24 BAC（未接线） | 🟡 有件未接 |
| 人工审批 | humanApprove / parked | 无（前端确认在 venue 流程） | `waitsForPerson` | 🟡 语义分散 |
| 经验闭环 | expertise canon/enforcement | 蒸馏桥 B/C/D 映射 | 35 认知库 + verify 升级 | 🟢 基本同构 |
| 目标/信号 | goal/signal 体系 | 无 | 43 / 28 | 🟢 已有，不进协议层 |

---

## §5 L2 聚合调度缺失清单（本轮新增）

| # | 缺口 | 证据（可复算） | 影响 | 优先级 |
|---|---|---|---|---|
| **GAP-17** | 计量双轨且未接通：CU 账本 vs tokens 预算，`L2Envelope.tokens_used` 仍空 | `meter.ts` 7 维；`usage_ledger.jsonl` 不存在；TECHNICAL_DESIGN §4.1 | 无法回答「这次 L2 任务花了多少」，成本审计/预算门禁无共同单位 | **P0** |
| **GAP-18** | 注册表配额口径冲突：`max_total_tools=80` vs `layer_quota.total=120`；声明 84（含 deprecated）> 80 | 实测 #2/#4 | 治理门禁与文档口径不一致，扩壳时判定歧义 | P1 |
| **GAP-19** | 能力面未聚合：MCP 客户端单例单壳，`trading_read/trading_proposal` 的 8 个工具无壳可挂 | `mcp-client.ts` 单例；registry `lobehub_frontend=1`；SPEC F6 备注「待壳注册」 | 工作台实际能力 = cognition 1 壳；L2 能力「聚合」名不副实 | **P0** |
| **GAP-20** | 循环/终止语义不通约：无共享 `stop_reason`（done/error/interrupted/parked/cost_limit/max_steps） | `chat/route.ts` `stopWhen=5`；`ticket_state.py` 四态 | 卡死、超预算、等人无法在 trace 区分，调度不可复盘 | **P1** |
| **GAP-21** | 插件可逆性不完整：仅包级 add/remove，无 inspect/内存 experiment，未验四类副作用回滚 | `plugin_audit.jsonl` 30 行；53 静态白名单；ADR-10 | 不能安全开放 L2 自扩展 install | P1 |
| **GAP-22** | 主动调度不可靠：仅 `supervisor.py` 每日一次，不跨重启；无 heartbeat | TECHNICAL_DESIGN §11；`ops/supervisor.py` | shadow/蒸馏常态运转依赖人工重拉 | P1 |
| **GAP-23** | 工具可见性无运行时同步：无指纹/可见性控制，工具变更对 LLM 不可观测 | `mcp-client.ts` 每次 `tools/list` 全量；profile 静态 | 工具增删需重启 + 人工改白名单，易漂移 | P2 |

> 与既有缺口的关系：GAP-17 是 GAP-01（统一信封）的**协议层证据补充**；GAP-19 是 GAP-03（`l2.dsh` 未注册）的**消费侧证据**；GAP-21 是 GAP-16 的**推进进度**（包级已可逆，副作用未验）。

---

## §6 对 56 能力登记的修订建议

| 能力 ID | 现状态 | 建议 | 依据 |
|---|---|---|---|
| `L2-P01` LobeHub 协议层 | 🟡 | 保持 🟡，描述改为「协议层已含路由/PlanCard/计量/插件/profile；与内核未打通」 | §2.2 |
| `L2-P09`（新增）算力计量与用量 | ⬜→🟡 | CU 7 维 + reserve/settle 代码可用；**运行态零落账** | GAP-17 |
| `L2-P10`（新增）工具 profile 与可见性 | 🟡 | 4 profile 服务端注入；可见工具数受壳限制（5/11/13/7 声明，实际 1 壳） | GAP-19 |
| `L2-A01` 3.1 主前端 | ✅ | 补「工作台/产品包双层 + 唯一聊天入口（F1/F2）」 | 52 SPEC §4.3 |
| `L2-K14` 统一信封 | ⬜ | 保持 ⬜，补证据：52 ledger 与 DreamOS 预算未通约 | GAP-17 |

---

## §7 测试与对照实验计划（落地前必须跑）

> 原则：**先证明「聚合组织」相对现状有增益，再改代码**。所有实验都用同一批样本、同一模型配置、同一判定人。

### 7.1 基线测试（只读，不改代码）

| # | 测试 | 命令 | 通过判据 |
|---|---|---|---|
| T1 | 52 编排器/桥单测 | `cd 52-lobehub协议集成/orchestrator && python3 -m pytest tests -q`；`cd ../bridge && python3 -m pytest -q` | 95 + 20 全绿 |
| T2 | 注册表门禁 | `python3 47-MCP管理系统/registry/scripts/validate_mcp_registry.py` | 退出码 0；壳 17 / active 78 |
| T3 | 3.1 协议层契约 | `cd 3.1-FRONTEND && npm run test -- src/lib/agent` | 5 个 vitest 文件全绿 |
| T4 | 蒸馏桥积压 | 比对 `outbox.jsonl` 行数与 `bridge/.cursor` | 积压 ≤ 5 条（当前 46） |
| T5 | 计量落账 | 跑 1 次 chat（配置模型）后检查 `runtime/usage_ledger.jsonl` | 新增 ≥1 条且 `cu_cost>0` |

### 7.2 对照实验（H1–H3）

**H1：统一信封（含 `tokens_used/budget_remaining/model`）不改变决策质量，只提升可审计性**

| 项 | 设计 |
|---|---|
| 样本 | 最近 30 条真实 trace（`orchestrator/traces/brainstorm.jsonl` 回放） |
| 分组 | A=现状（无信封）；B=信封注入（只加字段，不改门禁/评分） |
| 指标 | ① `meta` 必填完整率 ② 决策结论一致率 ③ 单任务成本偏差 ④ trace 可追溯率 |
| 判定 | ① =100%；② ≥95%；③ |CU−tokens 折算| ≤2%；④ =100% 才允许进 P0 落地 |

**H2：多壳工具聚合（cognition + l2.dreamos + l2.debate）提升任务完成率**

| 项 | 设计 |
|---|---|
| 样本 | 20 个开发端任务（bugfix 10 / 优化 10，均来自 L1 发现或显式报告） |
| 分组 | A=单壳 cognition；B=多壳（新增 l2.dreamos 只读 + l2.debate） |
| 指标 | 任务完成率、平均工具步数、工具调用失败率、回归通过率 |
| 判定 | 完成率相对提升 ≥10pp，且回归通过率不下降；否则回退 A |

**H3：统一 `stop_reason` 降低不可解释终止**

| 项 | 设计 |
|---|---|
| 样本 | 连续 7 天所有 chat + 脑暴 trace |
| 指标 | `unclassified` 终止占比、平均步数、超 5 步截断率 |
| 判定 | `unclassified` <5%，且截断率下降 ≥30% |

### 7.3 落地顺序（建议，待确认）

```text
P0-3  GAP-19 工具面聚合（最小闭环：多壳客户端 + registry 角色映射）
P0-4  GAP-17 计量同源（52 meter → L2Envelope 适配，不新建第三套账本）
P1-6  GAP-20 stop_reason 契约（3.1 + 34-core 双侧落 trace）
P1-7  GAP-18/22 配额口径与调度（注册表统一 + supervisor 跨重启）
P2-4  GAP-21/23 插件可逆 + 工具可见性同步（ADR-10 前置）
```

---

## §8 复跑命令（只读）

```bash
# REA（需 l0.rea.mcp）
# submit_rea_analyze(target=".../52-lobehub协议集成", scope="summary")
# get_rea_snapshot(snapshot_id="bb9c106bbbfd32fc", section="modules")

# 注册表实测
python3 - <<'PY'
import yaml,pathlib
d=yaml.safe_load(pathlib.Path('47-MCP管理系统/registry/mcp_capabilities.yaml').read_text())
sh=d['shells']; print('shells',len(sh),'tools',sum(len(s.get('tools') or []) for s in sh))
print('active',sum(len(s.get('tools') or []) for s in sh if s.get('status')!='deprecated'))
print('enums',d['enums']['max_tools_per_shell'],d['enums']['max_tools_per_role'],d['enums']['max_total_tools'])
PY

# 52 运行态
wc -l 52-lobehub协议集成/orchestrator/traces/brainstorm.jsonl \
      52-lobehub协议集成/bridge/outbox.jsonl \
      52-lobehub协议集成/runtime/plugin_audit.jsonl
cat 52-lobehub协议集成/bridge/.cursor
ls -l 52-lobehub协议集成/runtime/usage_ledger.jsonl   # 预期不存在
```

---

## §9 局限与未验证项（原样保留）

1. 上游 LobeHub 本地无源码，§2.1 全部为 2026-11-11 评审结论，本轮**未复验**；其协议若已变更，需重新调研。
2. REA 为静态分析：动态 import、反射调用、运行时依赖环未覆盖。
3. `usage_ledger.jsonl` 不存在有两种解释：从未走 chat 计量，或 `PRODUCT_USAGE_DIR` 指向别处——本轮未定位到替代路径，标 `unknown`。
4. 蒸馏积压 46 条是**行数差**，未逐条判断是否为毒丸/指纹跳过，实际待写量可能更小。
5. 未执行任何写操作、未启动服务、未修改 52/33 源码。

---

## §10 基线测试结果（2026-11-16，T1–T5）

> 口径：**能独立复算的只读项当场执行**；需要执行项目内测试脚本的 T1/T3，因工作区未信任未执行，只做静态盘点并给出命令。

| # | 项目 | 结果 | 判定 |
|---|---|---|---|
| T1 | 52 编排器/桥单测 | **未执行**（需跑项目脚本）。静态定义：`test_brainstorm 48 / test_router 16 / test_domain_eval 15 / test_adjudicator 4 / bridge 14`（pytest.parametrize 会使实际用例数高于定义数，不能替代 collected） | ⏸ 待执行 |
| T2 | 注册表门禁（独立复算） | 17 壳 / 声明 84 / 活跃 78；分层 L0 44·L1 20·L2 14，均在配额内；**角色/壳引用 0 违规**；`max_total_tools=80` vs `layer_quota.total=120` 冲突确认 | ✅ 门禁通过，⚠️ 口径冲突 |
| T3 | 3.1 协议层契约 | **未执行**（需 vitest）。静态定义 5 文件 / 32 个 `it/test` | ⏸ 待执行 |
| T4 | 蒸馏积压 | outbox 141 − 游标 95 = **46 条** | ❌ 超阈值（≤5） |
| T5 | 计量落账 | `runtime/usage_ledger.jsonl` **不存在** | ❌ 无运行证据 |

### 10.1 T2 的额外发现（影响落地顺序）

- 活跃工具 **78 / 上限 80**，只剩 **2 个**余量。
- 若按计划新增 `l2.dsh.mcp`（3 工具），活跃将变 **81 > 80**，**直接破门禁**；但按 `layer_quota`（L2 30，当前 14）又完全允许。
- `derivation`：**GAP-18（配额口径冲突）是 GAP-19（工具面聚合）的前置条件**，必须先统一总量口径，否则「加壳」这一步在机器判定上就不合法。

### 10.2 结论对落地顺序的修正

```text
P0-0  GAP-18 统一总量口径（max_total_tools 与 layer_quota 二选一或建立换算）
P0-3  GAP-19 工具面聚合（依赖 P0-0）
P0-4  GAP-17 计量同源（可与 P0-3 并行）
```

T1/T3 的复跑命令（在工作区受信任的终端执行）：

```bash
cd 52-lobehub协议集成/orchestrator && python3 -m pytest tests -q
cd ../bridge && python3 -m pytest -q
cd ../../3.1-FRONTEND && npm run test -- src/lib/agent
```

