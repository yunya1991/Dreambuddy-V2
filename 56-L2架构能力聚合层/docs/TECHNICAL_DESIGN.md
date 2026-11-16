# 56 总技术文档 — L2 大模型驱动层能力地图

- **版本**: v1.16 ｜ **日期**: 2026-11-17 ｜ **状态**: 🟡 正式修订版（A0–A3 全链路 + preset 导出/加载 + 四类 probe 采集器 + Cordis loader 探针 + sandbox profile 实装挂载）
- **上游**: [SPEC-56-L2架构能力聚合层.md](../SPEC-56-L2架构能力聚合层.md)（ADR/契约/门禁/路线）、[3+3架构模块映射.md](../1-ARCHITECTURE/3+3架构模块映射.md) v1.2、[SYSTEM_ARCHITECTURE_OVERVIEW.md](../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) v4.2
- **下游**: 3.1 前端 L2 通道、DreamOS/DSH 实现、47 层级 MCP 注册表、48 涌现/54 统计层协作面
- **协议层证据**: [REA-lobehub协议逆向解析-v0.1.md](./REA-lobehub协议逆向解析-v0.1.md)（52 协议事实 + GAP-17~23 + 对照实验设计）
- **总装线对标**: [总装线对标-三源与DreamOS逐模块优化-v0.1.md](./总装线对标-三源与DreamOS逐模块优化-v0.1.md)（LobeHub/OpenAI/Claude 三源 + 7 段契约 + GAP-24~30）
- **定位**: 本文是 56 的**总技术文档**——§0 回答「L2 有哪些问题域、每个域用什么机制、边界在哪」；§2 是能力登记册（能力 ID / 载体 / 状态 / 缺口）；§6/§7 是缺口与推进顺序。

---

## §0 全景：文档地图 / 五子层 / 能力地图 / 治理规则

### 0.1 文档地图（谁是 SSoT）

| 文档 | 角色 | 唯一负责的内容 | 版本 |
|---|---|---|---|
| [SYSTEM_ARCHITECTURE_OVERVIEW.md](../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) | 架构 SSoT | L0/L1/L2 判据、新 SACG 定义、层级文档权威性 | v4.2 |
| [3+3架构模块映射.md](../1-ARCHITECTURE/3+3架构模块映射.md) | 归层 SSoT | 53 个模块的层归属、L2 五子层、层级 MCP 治理结论 | v1.2 |
| [SPEC-56-L2架构能力聚合层.md](../SPEC-56-L2架构能力聚合层.md) | **本域契约** | ADR-01~10、IF-1~IF-6、G-L2-1~9、路线 P0–P5 | v0.5 |
| **本文 TECHNICAL_DESIGN.md** | **总技术文档 + 能力登记** | 能力 ID `L2-*`、状态列、缺口 GAP-*、推进顺序、部署与验收 | **v0.1** |
| [SPEC-v1.4-L0L1L2-路由边界与认知裁决.md](../34-前端应用训练系统/SPEC-v1.4-L0L1L2-路由边界与认知裁决.md) | 路由边界 | 四道闸 G1–G4、`channel` 三值、10 行判定表、认知裁决层 | v1.4-r3 |
| [SPEC-v1.2-SACG-orchestration.md](../34-前端应用训练系统/SPEC-v1.2-SACG-orchestration.md) | 内核编排 | S→A→C→G 流转、C-drive 双语义 | v1.2 |
| [SPEC-L1L2-MCP-PACKAGING-v0.1.md](../47-MCP管理系统/docs/tech/SPEC-L1L2-MCP-PACKAGING-v0.1.md) | 层级 MCP | `l2.<domain>.mcp` 命名、分层配额、硬约束 H1/H2/H4/H8 | v0.1 |
| 32/34/46/48/52/53/24 各模块 SPEC | 模块实现 | 各自算法、状态机、评分与实验口径 | 见各自文档 |

**读法**：本文只登记「L2 能做什么、做到什么程度」，算法与实验细节一律回到模块 SPEC，不在此复述。

### 0.2 唯一判据与灰区（不自造口径）

> **是否依赖生成式 LLM 推理** —— 依赖 → L2；不依赖 → L0 或 L1。

灰区规则见 SPEC-56 §2.1（R1 本地模型算 L1 / R2 工具链算 L0-L1 / R3 主体唯一形态可降级 / R4 编排≠生成 / R5 一次 LLM 调用即 L2）。

**推论（最容易错的三点）**：
1. `intent` 识别若用本地 bge-base 小模型 → 仍属 **L1**（34 SPEC v1.4 §2.2 明确「不新训 L1 意图模型」）。
2. `GraphExecutor`、`Router`、`Ticket` 是机制 → 属 **L2-E 的确定性部分**，本身不消耗 token。
3. 只有「规划理由 / 反思理由 / 裁决理由」的**生成**才是 token 成本来源。

### 0.2.1 三层职责边界（2026-11-16 定位决策）

| 层 | 本质 | 核心工作 | 输出物 | 红线 |
|---|---|---|---|---|
| **L0 确定性底座** | 确定性能力：事实读取、持久化、调度、事件、预算、注册表 | 保证「正确、可复现、可审计」 | 事实与状态（`data` / `verdict` / `ticket`） | 不得引入任何生成式推理；不得做统计显著性或业务判断 |
| **L1 统计能力层** | 统计方法 + 涌现架构（本地模型 / 向量 / 检验 / CBR-KNN / 贝叶斯） | 维护 + **发现**：统计显著、异常、相似案例、涌现线索 | 候选 + 证据（`p_adj` / `n` / 置信区间 / 相似案例） | 不得输出叙事性结论；不得写执行 |
| **L2 生成与编排层** | 生成式 LLM + 编排（DreamOS/DSH） | **对内（主负载）：开发端修 bug、做优化**；对外：规划 / 裁决 / 生成 / 辩论 | 动作 + 理由 + 证据引用（`L2Envelope`） | 不得替 L1 做统计判定；不得自证验收 |

**一句话口诀**：**L0 给事实，L1 给证据，L2 给动作。**

三条落地规则：

1. **L2 内部应用 = 开发端**：主负载是「症状 → 复现 → 根因 → 修复 → 回归 → 沉淀」闭环，而不是用户问答；问答是同一套能力的外显。
2. **L1 是发现端**：L2 的开发任务优先级由 L1 的发现驱动（异常、漂移、失效假设、统计显著的机会），避免「凭感觉优化」。
3. **L0 不参与智能**：任何需要判断的环节都上移；L0 保持零 LLM、可复现，这是三层能分开审计的前提。

**分层判定顺序**（从下往上问，命中即停）：

```text
任务 → 需要生成式推理吗？
        否 → 要「事实」还是「证据」？
               事实 → L0（数据/状态/调度）
               证据 → L1（统计检验/相似检索/涌现度量）
        是 → 是「改系统」吗（bug/优化/自扩展）？
               是 → L2 开发端闭环（§2.6）
               否 → L2 对外生成（规划/裁决/辩论）
```

**推论**：L2 的 KPI 不是「回答数量」，而是 **修复率 / 回归通过率 / 优化收益（回测或指标）/ 单任务 token 成本**。因此 `L2Envelope` 的 `tokens_used` 与 `trace` 是开发端闭环的计量基础（GAP-01 优先级因此更高）。

### 0.3 L2 五子层与实际载体

```
L2-K 内核编排（DreamOS · 新 SACG）        载体：1-ARCHITECTURE/dreamos + 34/core
  C-drive 调度者 ⇄ 反思器
  S 认知规划 ──→ A OKR 验收 ──→ C 执行驱动 ──→ G 压缩沉淀
  横切：NodeRegistry(28 节点/5 链) / Budget / Adapters / Evolution
        ↓
L2-E 执行编排（DSH Router / Worker）      载体：34-前端应用训练系统/core
  router_loop.run_pass() 单轮八步；ticket 四态；mandate_gate；gate_45_adapter；shell_handles
        ↓
L2-G 生成式能力层                          载体：32 / 34 / 48 / 25 / 30 / 3-EVOLUTION
  对抗辩论 · 主动+被动训练 · 涌现度量(D1/D2/D3) · 策略生成 · E2E · 进化引擎
        ↓
L2-P 协议接入层                            载体：46 / 52 / 53 / 24
  DSH Harness · LobeHub(PlanCard/模型路由) · Cordis 插件 · 图结构压缩
        ↓
L2-A 应用与前端                            载体：3.1-FRONTEND(3001) / 6-TRADING(bridge 3847)
```

**子层之间的硬边界**：

| 边界 | 规则 | 依据 |
|---|---|---|
| L2-K ↔ L2-E | K 只下发「做什么/验收标准」，E 只回答「谁做/做到哪」；E 不做业务决策 | `ticket_router.py` 头注释 |
| L2-E ↔ L2-G | G 提供能力，E 负责调度与门禁；G 不得自证验收（验收外置） | `gate_45_adapter.py` ADR-6 |
| L2-P ↔ 全体 | P 是宿主侧协议面，不是能力面；不得绕过 MCP 壳直连业务代码 | 52 §1「协议唯一」、53 ADR-07 |
| L2 ↔ L1 | L2 对 L1 **只读**；L1 热路径永不 MCP | SPEC-56 ADR-01/05 |

### 0.4 能力地图：L2 回答的八类问题

L2 有两个消费面，共用同一套能力：**对内（开发端）**——修 bug、做优化，是主负载；**对外（用户）**——规划、裁决、生成、辩论。下图的 ①–⑧ 是两者的共同骨架，⑦⑧ 尤其服务开发端闭环。

```
① 路由交接    L1 答不了 → 谁接、走哪条路线（retrieval / deep reasoning）
      ↓
② 规划       把模糊需求变成 Spec/Plan（S 层 + 开工 Skill）
      ↓
③ 验收       把 Plan 拆成 OKR 节点 + 每节点验收标准（A 层）
      ↓
④ 执行       节点调度、重试、依赖闸、Worker 分派（C 层 + L2-E）
      ↓
⑤ 生成       辩论、研究综合、策略方案、内容产出（L2-G）
      ↓
⑥ 实验       训练、涌现度量、A/B、verdict 四态（34/48）
      ↓
⑦ 沉淀       图压缩 + 四分流（案例/认知/流程/文档）（G 层）
      ↓
⑧ 计量       每出口 token / 预算 / trace / 证据边界（ADR-03，当前最大缺口）
```

一句话类比：**L1 是查表和计算，L2 是「先想清楚要做什么，再决定谁做，最后说清凭什么」**。

> 与 54 的区别：54 的能力是「问题 → 统计量」，答案确定；L2 的能力是「问题 → 计划/结论」，必须带证据与不确定性声明。

### 0.5 四层分工（本域内部）

| 层 | 载体 | 回答什么 | 命名单位 |
|---|---|---|---|
| ① **机制层** | `router_loop` / `ticket_*` / `mandate_gate` / `shell_handles` | 怎么调度、怎么续跑、怎么拒权 | 无 ID，按文件 |
| ② **编排层** | `sacg_orchestrator` / `okr_nodes` / `okr_acceptance` / `okr_ticket_bridge` | 一次请求怎么走完 S→A→C→G | SACG 四层 |
| ③ **能力层** | 32/34/48/25/30/52/53/24 | 需要生成时产出什么 | `L2-G/P-*` |
| ④ **出口层** | `l2.*.mcp` + DreamOS HTTP + 3.1 前端 | 外部宿主怎么调 | `L2-K/E-*` |

**边界纪律**：
1. 机制层不得内联业务判定（`gate_45_adapter` 只做提交/轮询/裁决结构化）。
2. 编排层不执行业务节点（A 层不含业务节点，2.1 架构总览明确）。
3. 能力层不得自证验收（ADR-6 / H2 验收外置）。
4. 出口层不新增业务逻辑（壳只做协议转换，双事实源禁止）。

### 0.6 文档治理规则（v0.1 起强制）

1. **能力 ID `L2-*`** 只在本文 §2 登记；SPEC-56 只写契约，不新建能力 ID。
2. **状态列变更**（✅/🟡/⬜）必须附代码位置或可执行证据，禁止只改图标。
3. **模块算法口径**只在模块自身 SPEC 定义，本文只引用。
4. **层级归属**变更必须先改 3+3 映射，再改本文，禁止反向。
5. **实测数字**（工具数、节点数、端口）必须来自当次执行输出，并在变更记录注明复跑命令。

---

## §1 架构定位与调用链

### 1.1 一次请求的完整链路

```
用户输入（3.1 前端 3001）
  → L1 意图注册表 l1-intent-registry.ts（channel: data/semantic/generative）
      ├─ L1_DIRECT → 19 执行器 → 直答（零 token）
      └─ L2_HANDOFF → route_signal（decision/reasons/confidence）
            ↓
      /api/task/stream 或 dsh_frontend_bridge（IPC，18 条命令）
            ↓
      sacg_orchestrator（route_confidence 门控）
            S 规划 → A OKR 分解 → C 逐节点执行（CDriveV3Router 五步反思门）→ G 沉淀
            ↓
      router_loop.run_pass()（L2-E 单轮八步）
            恢复快照 → 消费 Worker 回执 → 对账 → 事件唤醒 → 分派 → 提交 → 观测
            ↓
      能力层（L0 壳只读 / L2-G 生成）→ 45 门禁 → 回写 L0
            ↓
      L2Envelope（result/meta/trace/quality）→ 前端
```

### 1.2 端口与服务清单（部署用）

| 服务 | 端口 | 入口 | 状态 |
|---|---|---|---|
| DreamOS API | `8000` | `1-ARCHITECTURE/dreamos/apps/api_server.py`（Flask，`0.0.0.0:8000`） | ✅ |
| 3.1 主前端 | `3001` | `3.1-FRONTEND`（`next dev/start -p 3001`） | ✅ |
| 6 交易中台 Bridge | `3847` | `6-TRADING/bridge/` | 🟡 |
| 25 策略生成 | `8095` | `25-用户策略生成系统/app.py#L307`（`STRATEGY_GEN_PORT`） | ✅ |
| 26 策略管理 | `8093` | `26-策略管理模块/app.py#L467`（`STRATEGY_LIB_PORT`） | ✅ |
| 27 治理审批 | `8094` | `27-策略治理审批系统/app.py#L568`（`GOVERNANCE_PORT`） | ✅ |
| 28 信号触发 | `8096` | `28-策略信号触发模块/app.py#L460`（`SIGNAL_TRIGGER_PORT`） | ✅ |
| 45 评测系统 | `8790` | `45-评测系统/api/server.py#L11`（uvicorn 启动注释）；门禁注入点 `core/gate_45_runtime.py::resolve_settle_gate()` | ✅ 已接线（2 处 settle，默认关；GAP-14 关闭） |

> 状态口径：✅ = **入口文件与默认端口已确证**（含 env 覆盖变量），不等于运行态已验证；运行态按 §7.3 复跑。

### 1.3 DreamOS 对外端点（实测 12 个）

| 方法 | 路径 | 用途 | 返回是否含 token 计量 |
|---|---|---|---|
| GET | `/api/v1/health` | 健康检查（`service=dreambuddy-os`） | — |
| GET | `/api/v1/status` | Agent 运行状态 | — |
| GET | `/api/v1/nodes` | 节点清单（`total` + `nodes[]`，含 `estimated_tokens/latency`） | 预估有，实测无 |
| POST | `/api/v1/run` | 同步完整推理（`user_input/market_data/context/phase`） | ⬜ |
| POST | `/api/v1/run/async` | 异步提交（返回 `cycle_id`） | ⬜ |
| GET | `/api/v1/result/<cycle_id>` | 异步结果轮询 | ⬜ |
| POST | `/api/v1/intent` | 意图识别 | ⬜ |
| POST | `/api/v1/analyze` | 分析 | ⬜ |
| POST | `/api/v1/chat` | 对话 | ⬜ |
| GET | `/api/v1/history` | 运行历史 | ⬜ |
| GET | `/api/v1/budget` | 预算余额 | ✅（仅余额，无本次消耗） |
| POST | `/api/v1/budget/reset` | 预算重置 | — |

> 该表是 `L2-K01~K13` 能力登记的源码依据；`/api/v1/*` 端点总数 12，不含 404/405/500 处理器。

---

## §2 能力登记（50 项：K16 / E12 / G8 / P10 / A4）

状态口径：`✅ 已有实现并可用` ｜ `🟡 部分可用/未统一` ｜ `⬜ 未实现或未注册`。判定以**代码可执行**为准，不以文档描述为准。

### 2.1 K 组：内核编排（16 项）

| ID | 能力 | 载体 | 对外形态 | 状态 |
|---|---|---|---|---|
| L2-K01 | L1→L2 路由交接 | `3.1/src/lib/l1-intent-registry.ts`（`ROUTE_DECISION_L2_HANDOFF`）+ `34/SPEC-v1.4` §4 判定表 | 前端 + `route_signal` | ✅ |
| L2-K02 | 入口意图识别 | `POST /api/v1/intent` | HTTP | ✅ |
| L2-K03 | 同步完整推理 | `POST /api/v1/run`（支持 `phase` 渐进档） | HTTP | ✅ |
| L2-K04 | 异步作业提交与轮询 | `POST /api/v1/run/async` → `GET /api/v1/result/<cycle_id>` | HTTP | ✅ |
| L2-K05 | S 层认知规划入口 | `34/core/sacg_orchestrator.py`（S 段，`l1_intent_hint` 先验） | in-process | 🟡 骨架已落，实质认知接入未闭环 |
| L2-K06 | A 层 OKR 节点验收 | `okr_nodes.py` / `okr_acceptance.py`（三态 pass/degraded/fail） | in-process | 🟡 规则齐备，覆盖节点类型有限 |
| L2-K07 | C 层执行驱动 | 两宿主两实现：DreamOS `core/compute.GraphExecutor`（`apps/trading_agent/agent.py#L39`）/ 34 侧 `sacg_orchestrator` → `CDriveV3Router.run_v3` | in-process | 🟡 两宿主分工不同，一致性靠 IF-2 OKR 契约；是否统一见 Q5 |
| L2-K08 | G 层压缩沉淀 | `dreamos/core/graph_store` + 收尾 Skill 四分流 | in-process | 🟡 图存储有，四分流未统一入口 |
| L2-K09 | 节点注册表 | `dreamos/registry/node_registry.py` + `config/nodes.yaml`（28 节点 / A·C·F·G·I 五链） | `GET /api/v1/nodes` | ✅ |
| L2-K10 | 预算管理 | `dreamos/budget/global_budget.py`（`/budget`、`/budget/reset`） | HTTP | ✅ |
| L2-K11 | 状态与历史 | `GET /api/v1/status`、`GET /api/v1/history` | HTTP | ✅ |
| L2-K12 | 健康检查 | `GET /api/v1/health` | HTTP | ✅ |
| L2-K13 | 层级 MCP 观察面 | `l2.dreamos.mcp`（`submit_run` 需 Mandate；`poll_run/get_result/get_intent/get_budget` 只读） | MCP | ✅ |
| L2-K14 | 统一信封与 token 计量 | 无统一实现（散落在各端点直出 JSON） | — | ⬜ **P0 缺口** |
| L2-K15 | 开发端闭环（修 bug / 优化） | DreamOS + DSH Router/Worker + 45 门禁 + 回归测试 + 台账 settle/周报 | in-process / CLI | 🟡 闭环已通，单任务 tokens 待 GAP-17 |
| L2-K16 | 开发端修复台账 | 契约 v1.1（`contracts/repair_ledger.schema.json` + `state_machine.yaml` + 校验器）+ 生成方 `34/core/l2_repair_ledger.py`（A2-1）+ settle/周报 `34/core/l2_settle.py`（A2-2） | ✅ 生成 + 结算 + 周报可用（`l2_repair_ledger.jsonl` 随首条发现创建） |

**K 组读法**：K01–K04 是「请求进得来」，K05–K08 是「SACG 走得通」，K09–K13 是「可观测、可调」，K14 是「说得清成本」——当前唯一致命缺口。

### 2.2 E 组：执行编排（12 项）

| ID | 能力 | 载体 | 对外形态 | 状态 |
|---|---|---|---|---|
| L2-E01 | Router 常驻单轮 | `core/router_loop.py::run_pass()`（八步：读开关→恢复快照→消费回执→对账→事件唤醒→分派→提交→观测） | in-process | ✅ |
| L2-E02 | Ticket 四态状态机 | `core/ticket_state.py::transition_ticket()`（live/paused/waitsForPerson/ended + paused 子因） | in-process | ✅ |
| L2-E03 | 单轮分派 | `core/ticket_router.py::route_single_round()`（`route_hint.role` 匹配角色池、依赖闸、轮询、mandate 传递） | in-process | ✅ |
| L2-E04 | 会话续跑与事件唤醒 | `core/ticket_resume.py`（`matches_wakeup` / `resume_on_event`，支持 `thread_id` 直通） | in-process | ✅ |
| L2-E05 | Ticket L0 持久化 | `core/ticket_store.py`（`save_ticket` / `recover_tickets`，L0 为单一事实源） | in-process | ✅ |
| L2-E06 | Mandate 门禁 | `core/mandate_gate.py`（deny-by-default；写工具即使角色集内也拒） | in-process | ✅ |
| L2-E07 | 45 业务门禁适配 | `core/gate_45_adapter.py`（submit 202 → poll verdict；shadow 期只记录） | in-process | ✅ |
| L2-E08 | 壳句柄池 | `core/shell_handles.py`（同域共享单壳；`MAX_RESTARTS=3`；连接数=域数而非 Worker 数） | in-process | ✅ |
| L2-E09 | Worker 角色池工具上限 | `47/registry/mcp_capabilities.yaml::worker_roles` + `validate_mcp_registry.py#L379-L435`（角色引用的壳/工具必须存在，且 `0 < 工具数 ≤ max_tools_per_role`） | 注册表 + 校验器 | ✅（v1.2.1 已拆分 `max_tools_per_role=10`，Q4 采 B 并落地） |
| L2-E10 | IPC 命令面 | `core/dsh_frontend_bridge.py`（`subagent.*` 8 类、`c-drive`、`c-drive.debate`、`synthesizer`、`orchestrator`、`orchestrator.status`、`knowledge.search`、`skill.index`、`user.memory`、`data.dal_query`、`shell.stats`） | IPC | ✅ |
| L2-E11 | 线程亲和 / 事件网关 / 资源管理 | `thread_affinity.py` / `event_gateway.py` / `resource_manager.py` / `event_emitter.py` | in-process | ✅ |
| L2-E12 | 层级 MCP（`l2.dsh`） | 未注册 | — | ⬜ 外部宿主完全不可观测 |

### 2.3 G 组：生成式能力（8 项）

| ID | 能力 | 载体 | 出口 | 状态 |
|---|---|---|---|---|
| L2-G01 | 对抗辩论 | `32-对抗性辩论Bot`（DebateOrchestrator + Bull/Bear/Judge；状态机 + 五维评分） | `l2.debate.mcp`（3 工具，`exposure=control`） | ✅ |
| L2-G02 | 训练系统（主动+被动） | `34`（`active_training_collector.py` / `coaching_loop.py` / SPEC v0.5–v1.0 系列） | IPC/脚本 | 🟡 主链路有，训练数据源仍在扩 |
| L2-G03 | 涌现度量与实验 | `48`（D1 交易 / D2 工程 / D3 意图；10 个 verdict） | `l2.emergence.mcp`（3 只读工具） | 🟡 5 candidate / 1 falsified / 1 inconclusive 等，均未转正式 |
| L2-G04 | 策略生成 | `25-用户策略生成系统`（`:8095`，`strategy_gen/`） | HTTP | 🟡 LLM 主路径，只读元数据未降级出口 |
| L2-G05 | 训练运维 | `l2.train.mcp`（`trigger_training` 需 Mandate + `get_training_status` + `list_runs`） | MCP | ✅（`source_modules` 登记为 `param_center` + 23，与 34 不对齐 → GAP-05） |
| L2-G06 | 真实环境 E2E | `30-真实环境交互系统`（Chrome 自动化） | 脚本 | 🟡 |
| L2-G07 | 进化引擎 | `3-EVOLUTION`（`evolution-engine.ts` / `real-benchmark.ts`） | 实验态 | 🟡 未接入 L2 主链路 |
| L2-G08 | 辩论质量评估 | 32 SPEC §九（五维评估 + 综合评分 + `DebateQualityScore`） | in-process | 🟡 设计完整，产出未进 trace |

### 2.4 P 组：协议接入（8 项）

| ID | 能力 | 载体 | 状态 |
|---|---|---|---|
| L2-P01 | LobeHub 协议层 | `52`（`orchestrator/` + `bridge/distill_bridge.py` + `ops/supervisor.py`；G1–G4 门禁、PlanCard 竞争、live 永禁；3.1 侧 F1–F7 工作台/产品包/profile） | 🟡 协议层已含路由/PlanCard/计量/插件，**与 L2 内核未打通**（双轨，GAP-17/19/20） |
| L2-P02 | Cordis 插件生态 | `53`（`plugin_whitelist.yaml` deny-by-default；先消费→再封装→后治理） | 🟡 白名单 13 条 `approved`（实测 2026-11-16） |
| L2-P03 | 图结构上下文压缩 | `24`（BAC 三层：Blueprint/Architecture/Chronicle；接口设计 §5） | 🟡 有件，未接入协议层循环 |
| L2-P04 | DSH Harness 规范归集 | `46-DSH架构`（仅 README，SPEC 归集） | ⬜ 无实现载体 |
| L2-P05 | 层级 MCP 封装 | `47`（schema `1.2-mcp`，`layer/exposure/source_modules/plugin_ready/llm_dependency` 已落地） | ✅ |
| L2-P06 | 运行时插件图自检（inspect） | `1-ARCHITECTURE/dreamos/core/capability/plugin_inspect.py`（A3-1）：DSH profile + 本地包静态提取，只读 | ✅ 可用（headless 17 插件 / 0 unresolved / `--plugin` 0 violation） |
| L2-P07 | 内存实验 + 卸载回滚 + 安装门禁 | experiment + unload 验收器（含 probe 完整性门禁）+ install 门禁 + adapter + probe 协议/Node 采集器 + Cordis loader 探针（patch `Fiber.prototype.effect`，订阅随 fiber dispose 注销） | ✅ 真实 Cordis 集成通过；未挂到实际 profile |
| L2-P08 | Preset 打包与分发 | `preset_export.py`（导出 + hash 校验）+ `preset_load.py`（先校验后加载，默认 dry-run，apply 需注入 adapter，单点失败进 `failed`）；headless dry-run 实测 12 已装 / 0 待装 / 5 skipped | ✅ 导出 + 一键加载 |
| L2-P09 | 算力计量与用量（新增） | `3.1/src/lib/billing/meter.ts`（CU 7 维：llm_input/output、tool_call、heavy、backtest_cpu、data_query、plugin_runtime）；reserve→settle→`52/runtime/usage_ledger.jsonl` | 🟡 代码可用，**运行态零落账**（GAP-17） |
| L2-P10 | 工具 profile 与可见性（新增） | `3.1/src/lib/agent/tool-profiles.ts`（platform/trading_read/trading_proposal/admin，服务端注入） | 🟡 声明 5/11/13/7 工具，实际仅 cognition 1 壳可见（GAP-19） |

### 2.5 A 组：应用与前端（4 项）

| ID | 能力 | 载体 | 状态 |
|---|---|---|---|
| L2-A01 | 3.1 主前端 | `3.1-FRONTEND`（`:3001`，68 个 `page.tsx`，`l1-intent-registry` + L2 通道；52 F1/F2 工作台/产品包双层 + 唯一聊天入口） | ✅ |
| L2-A02 | 6 交易中台 | `6-TRADING`（A0–A9 流水线 + SKILL 引擎 + `bridge` `:3847`） | 🟡 |
| L2-A03 | 话题边界检查 | 6 §2.5（A 类核心金融 / B 类边缘 / C 类非金融委婉拒绝） | 🟡 文档有，代码校验未统一 |
| L2-A04 | 前端执行轨迹 | `3.1/src/lib/execution-trace.ts`（`entry: l1/l2`、`route: l1_direct/l2_handoff/l2_direct`） | ✅ |

### 2.6 开发端闭环与自扩展（Creator Mode 对照）

**闭环状态机**（SPEC-56 §2.5，不可跳步）：`reported → reproduced → root_caused → fixed → regression_passed → settled`。每步证据落 `RepairLedger`（SPEC §4.5），台账本轮回写 L0。

**与 DeepSeek Harness Creator Mode 的能力对照**（2026-11-02 发布，机制参考，不引入其运行时）：

| 机制 | Harness Creator Mode | 我们现状 | 对应能力/缺口 |
|---|---|---|---|
| 运行时插件图自检 | 生成前读已加载插件、依赖、事件通道 | 53 只有静态白名单，运行时不暴露插件图 | `L2-P06` / GAP-16 |
| 内存实验 | 内存构建试跑，失败不崩会话 | experiment 预检已落地（A3-2 `plugin_experiment.py`，`disk_writes=0`） | `L2-P07` / GAP-16/21 |
| 卸载回滚 | Cordis 可逆依赖图，卸载回滚副作用 | 四类副作用验收器已落地（A3-3 `plugin_unload.py`）；真实 install 已通过 sandbox 验证，真实 unload 与四类 probe 未接 | `L2-P07` / ADR-10 |
| Preset 打包分发 | 导出配置，一条命令加载，生态分发 | 导出 + 一键加载已落地（P08 `preset_export.py` / `preset_load.py`）；加载默认 dry-run，真实 apply 需 adapter | `L2-P08` / GAP-16 |
| 一切皆插件 | 模型/工具/会话/UI/存储/沙箱皆插件 | 部分（DSH 插件目录 + MCP 壳） | 🟡 方向一致 |

**结论**：我们与 Creator Mode 的差距不在「生成插件的模型能力」，而在**运行时自检与可回滚**这两个前置设施。因此 P3（台账）先做，P4（自扩展）必须等 `unload` 验证通过再开放 install。

---

## §3 与 L0/L1/47 的边界矩阵

### 3.1 谁能调谁

| 调用方 ↓ / 被调方 → | L0 壳 | L1 壳 | L2 壳 | in-process |
|---|---|---|---|---|
| 外部宿主（Trae/Claude/Cursor） | ✅ 按角色 | ✅ 按角色（默认只读） | ✅ 按角色 | ❌ |
| L2 编排（DreamOS/DSH） | ✅ 按角色 | ✅ **只读** | ✅ 自身 | ✅（L0 port） |
| L1 内部编排 | ✅ | ✅（含写） | ❌ | ✅ |
| L2 Worker | ✅ 按角色 | ✅ 只读 | ❌（不自调） | ❌ |

### 3.2 层级 MCP 现状（实测）

| 指标 | 值 | 证据 |
|---|---|---|
| 注册表 schema | `1.2-mcp` | `mcp_capabilities.yaml` 首行 |
| 壳总数 | 17（0 规划壳） | `validate_mcp_registry.py` 输出 |
| 活跃工具 | **78** / 上限 120 | 同上 |
| 分层配额 | L0:60 / L1:30 / L2:30 / total:120 | `layer_quota` 段 |
| L2 壳 | 5（`l2.debate` / `l2.dreamos` / `l2.train` / `l2.emergence` available；`agent.debate` deprecated） | 逐壳核对 |
| L2 活跃工具 | **14**（3+5+3+3）/ 配额 30 | 同上 |

**L2 硬约束（不可逆）**：
1. `l2.*` 写工具必须 `requires_mandate: true`（`submit_run`、`trigger_training` 已满足）。
2. L2 角色不得持有 `forward_signal` 类写工具（ADR-01）。
3. `l2.dreamos` / `l2.debate` / `l2.train` 为 `exposure=control`，必须挂 Mandate；`l2.emergence` 为 `readonly-observe`。
4. 插件化只允许 `readonly-observe` 或 `control(受 Mandate)` 的壳（`plugin_ready` 门禁）。

---

## §4 统一信封、成本与质量

### 4.1 现状核对（不是设计，是实测）

| 出口 | 当前返回 | 是否含 `tokens_used` | 是否含 `run_id` | 是否含 `trace` |
|---|---|---|---|---|
| DreamOS `/api/v1/run` | `jsonify(result)` | ❌ | 🟡（`cycle_id` 仅异步） | ❌ |
| DreamOS `/api/v1/budget` | 预算余额 | ❌（无本次消耗） | ❌ | ❌ |
| `l2.dreamos.mcp` | `envelope_version: '0.1'` | ❌ | ❌ | ❌ |
| `l2.debate.mcp` | 同上 | ❌ | ❌ | ❌ |
| `l2.emergence.mcp` | 同上 | ❌ | ❌ | ❌ |
| `dsh_frontend_bridge` | `{ok, data, error_code, meta}` | ❌ | ❌ | ❌ |
| `3.1 /api/agent/chat` | 文本流 | 🟡（仅写 CU 账本，不出口） | 🟡（`x-request-id`） | ❌ |
| 52 编排器 CLI `--json-out` | 单行 JSON 摘要 | ❌ | 🟡（`trace_id`） | 🟡（trace 文件路径） |

结论：**信封字段名不统一、计量缺失**，这是 `L2-K14` 判 ⬜ 的直接依据；52 的 CU 账本（`meter.ts`）是唯一有实际计量维度的地方，但与 DreamOS 预算不同源（GAP-17）。

### 4.2 三件套要求（ADR-04）

| 件 | 含义 | 现有载体 | 缺口 |
|---|---|---|---|
| Mandate | 谁被授权做写操作 | `mandate_gate.py` + registry `requires_mandate` | Mandate 来源与生命周期未在 56 登记 |
| 预算 | 本次最多花多少 | `dreamos/budget/global_budget.py` | 与壳层未打通（壳不读预算） |
| Trace | 凭什么这么答 | `execution-trace.ts` + `nodes[]` | L2 出口未回传 `nodes[]` |

### 4.3 质量与证据边界

- 每条生成结论必须能回溯到 `trace.nodes[]` 或 L1 只读事实，否则标 `quality.evidence=none`。
- 固定尾注：「模型推断/历史统计，不代表未来」；禁止「将会/预计/必然」。
- 涌现类结论必须沿用 48 的 verdict 四态（`candidate` / `falsified` / `inconclusive` / `insufficient_data`），不得自造「已验证」。

### 4.4 开发端台账字段（`RepairLedger`，P3 落地）

| 字段 | 必填 | 来源 | 说明 |
|---|---|---|---|
| `schema_version` | ✅ | 契约 | 固定 `1.0` |
| `task_id` | ✅ | 台账生成 | `^(fix\|opt)-\d{8}-\d{3}$` |
| `kind` | ✅ | 任务声明 | `bugfix` / `optimization` |
| `trigger` | ✅ | G-L2-7 | `{source,resolver,ref,resolved_at}`；`ref` 必须匹配 resolver |
| `state` | ✅ | 状态机 | 见 `contracts/state_machine.yaml` |
| `history` | ✅ | 状态机 | 首条 `from=reported`，末条 `to=state` |
| `attempts` | ✅ | 状态机 | 等于重开次数，`≤3` |
| `reported` | ✅ | L0 事实 | `{repo, base_commit, env}` |
| `symptom` / `root_cause` | ✅ | L2 填写 | 根因 ≥10 字，禁止「代码有问题」 |
| `change_ref` | fixed 及之后 ✅ | git | `{type, sha\|url, summary}` |
| `evidence.repro` | ✅ | 复现器 | `{cmd, fails_on_base=true, artifact_hash}` |
| `evidence.regression` | regression_passed 及之后 ✅ | 测试执行器 | `{runner≠manual, cmd, exit_code, passed, ts, log_uri}` |
| `evidence.optimization` | 优化类 ✅ | 45 / L1 | `gate45` 与 `stats{n≥30,p_adj≤0.05}` 至少一项 |
| `metrics` | 优化类 ✅ | 同测试集 | `[{name,unit,before,after,n?,ci_low?,ci_high?}]` |
| `settled` | settled 时 ✅ | 收尾四分流 | `case/cognition/process/doc` 四键，各 `done\|skipped` |
| `run_ids` | settled 时 ✅ | L2Envelope | 关联信封；`tokens_used` 按 `run_id` 从信封取，不在此重算 |

契约文件 `contracts/repair_ledger.schema.json`（**v1.1**：允许初始入队自迁移 `reported→reported`）；落点 `34-前端应用训练系统/l2_repair_ledger.jsonl`；校验 `scripts/validate_contracts.py --ledger <file>`（自检 `--self-test`，2 正 5 负）。

**settle 回写（A2-2）**：`34/core/l2_settle.py` 收口 `regression_passed → settled`，回归未通过 / 缺 `run_ids` / 非 `regression_passed` 一律 fail-closed；案例落点确定为 L0 案例库 `34-前端应用训练系统/l1_case_store.jsonl`（与 `l0_foundation._CASE_STORE` 同域，`case_type=l2_repair`，按 `task_id` 幂等，`settled.case=skipped` 不写）。周报口径：修复率 `settled/(settled+abandoned)`、回归通过率 `passed/regression_evidence`、优化收益按同测试集 `before/after/delta` 逐项列出；0 样本记 `null`，不按 0 记，不自动判优劣。CLI：`python3 core/l2_settle.py weekly --since <iso> --until <iso> --out <path>`。

### 4.5 总装线四契约（A0，2026-11-16 冻结）

> 目的：先冻结段间契约、不改行为；A1 的单模块改造全部以此为准。细则见 [SPEC §4.7](../SPEC-56-L2架构能力聚合层.md)。

| 契约 | 文件 | 冻结判据 | 当前证据 |
|---|---|---|---|
| 停止原因 | `contracts/stop_reason.schema.json`（v1.1） | 7 值；必填 `trace_id`；`parked` 三子因且可续跑；`done/error/no_next_context` 不可续跑 | 缺子因 / done 可续跑 / no_next_context 可续跑 / 缺 trace_id 均被拒 |
| 工具集快照 | `contracts/tool_set.schema.json` | 名称唯一；写必 Mandate；trade 必须 Mandate + 审批 human/deny；权限顺序固定 | 交易工具 `auto` / 无 Mandate 被拒；非法时间被拒 |
| 观测 span | `contracts/span.schema.json` | 8 段；`ended≥started`；`model=none ⇒ tokens=0` | 时间倒挂 / 无模型有 token 被拒 |
| 规划/交接 | `contracts/plan_handoff.schema.json`（v1.1） | 必填 `trace_id`；self/handoff/agents_as_tools；交权与保留控制权互斥；软≤硬；外部验收必填 | 缺 trace_id、handoff 未交权、软超硬、步骤断号被拒 |

校验入口：`python3 scripts/validate_contracts.py --self-test`（四契约 20 项 + 台账/插件 9 项 = 29 项）；单文件 `--stop-reason / --tool-set / --span / --plan`。
A0 明确**不改运行时**；`validate_contracts.py --self-test` 需在受信任终端执行一次，全绿后 A0 才算完成。

> 新增门禁：G-L2-10（循环出口）/ G-L2-11（工具集）；新增 ADR-11（段间契约唯一化）。

---

## §5 非确定性治理（L2 专属）

| 风险 | 表现 | 治理 |
|---|---|---|
| 采样不可复现 | 同输入两次结论不同 | 记录 `model` + 参数摘要 + prompt 版本；实验类落盘快照 |
| 结论越界 | 把模型推断说成统计事实 | `quality.evidence` 分级；尾注纪律 |
| 成本失控 | 无限重试/递归调用 | 预算门禁 G-L2-3 + Router 单轮批处理（非常驻会话） |
| 越权写 | Worker 调写工具 | `mandate_gate` deny-by-default + 审计留痕 |
| 双事实源 | 壳内重实现业务逻辑 | 壳只做协议转换（ADR-02/回归测试） |
| 工具面膨胀 | 每子层建壳 | 角色工具上限 `max_tools_per_role=10`（v1.2.1 已拆分）+ 分层配额 |

---

## §6 缺口登记

| # | 缺口 | 影响 | 优先级 |
|---|---|---|---|
| GAP-01 | 无统一 `L2Envelope`（`tokens_used/budget_remaining/model/run_id`） | 无法做层级成本审计与证据边界 | **P0** |
| GAP-02 | `route_signal` 缺 `l2_route` 字段（`retrieval_augmented`/`deep_reasoning`） | 裁决①③只有语义，前端与 trace 无法消费 | P1 |
| GAP-03 | `l2.dsh` 未注册 | Router/Ticket/Worker 对外零可观测 | P1 |
| GAP-04 | `agent.debate.mcp` 与 `l2.debate.mcp` 双壳并存 | 工具账目重复（L2 名义 17 / 活跃 14） | P1 |
| GAP-05 | `l2.train` 的 `source_modules` 为 `param_center`+23，与 34 训练系统不对齐 | 溯源错误，审计会找错模块 | P1 |
| GAP-06 | `dreamos/README.md` 顶部标注「已归档，以 v4.0 为准」，但目录仍在使用 | 文档漂移，读者按归档文档实现会错 | P1 |
| GAP-07 | 两宿主 C 层（`core/compute` vs `cdrive_v3_router`）无一致性回归测试 | 宿主间行为漂移不可发现 | P2（Q5） |
| GAP-08 | 45 门禁仍 shadow（误拦率未统计） | 验收门禁未真正生效 | P2 |
| GAP-09 | 25 的 LLM 依赖点未逐函数登记（仅确认 `app.py#L307` 端口与 `strategy_gen/` 包） | 无法判断哪些子能力可降级到 L1 | P2 |
| GAP-10 | `L2-G03` 涌现 10 个 verdict 未汇入 L2 出口 | 外部宿主只能看指标，看不到结论 | P2 |
| GAP-11 | ✅ 已关闭：角色上限拆分——`max_tools_per_role=10`（v1.2.1），校验器角色检查改用该值 | 原风险：治理意图被历史默认值覆盖 | 已关闭 |
| GAP-12 | 48 与 54 的 handoff 边界只在 48/54 侧登记，56 未引用 | 跨域变更容易漏改 | P2 |
| GAP-13 | `cognition_signal` / `l2_route` 零实现 | 裁决层与 L2 路线选择全部停在文档层 | **P1** |
| GAP-14 | ✅ 已关闭：`core/gate_45_runtime.py::resolve_settle_gate()` 接入 2 处 settle（默认关） | 原风险：门禁真实生效状态不明 | 已关闭 |
| GAP-15 | 开发端闭环无度量台账（修复率 / 回归通过率 / 优化收益 / 单任务 token） | L2 主负载无法证明有效，「优化」易退化为凭感觉 | **P1 → 台账/周报 Closed（A2-2）；tokens 待 GAP-17** |
| GAP-16 | 自扩展四缺项：无运行时插件图自检、无内存实验、无副作用级卸载回滚、无 preset 导出（52 F5 已补包级 add/remove + 审计；**inspect / experiment / unload 验收 / install 门禁 / preset 导出+加载均已落地**） | 放开 L2 自改的条件不具备；53 只能静态白名单 | P2（Closed：P06/P07/P08 关闭） |
| GAP-17 | 计量双轨且未接通：52 CU 账本（7 维）vs DreamOS tokens 预算，`L2Envelope.tokens_used` 仍空；`52/runtime/usage_ledger.jsonl` 实测不存在 | 无法回答「一次 L2 任务花了多少」，成本审计与预算门禁无共同单位 | **P0** |
| GAP-18 | 注册表配额口径冲突：`enums.max_total_tools=80` vs `layer_quota.total=120`；声明 84（含 2 个 deprecated 壳）/ 活跃 78，仅剩 2 余量 | 新增 `l2.dsh`（3 工具）即 81>80 破门禁；治理与文档口径不一致，扩壳判定歧义 | **P0** |
| GAP-19 | 能力面未聚合：3.1 MCP 客户端单例单壳（仅 cognition），`trading_read/trading_proposal` 的 8 个工具无壳可挂 | 工作台实际能力=1/17 壳，「能力聚合」名不副实 | **P0** |
| GAP-20 | 循环/终止语义不通约：3.1 `stopWhen: stepCountIs(5)` 无停止原因；34-core Ticket 四态；无共享 `stop_reason` | 卡死/超预算/等人无法在 trace 区分，调度不可复盘 | **P1** |
| GAP-21 | 插件可逆性不完整：52 F5 仅包级 add/remove + 审计；inspect / experiment / unload 验收 / install 门禁 / adapter / probe 协议 + Node 采集器 + Cordis loader 探针均已补，未完整快照被 unload 拒绝 | 生产 install 仍受 Mandate + 白名单门禁（ADR-10） | P1（Closed：代码 + 真实 Cordis 集成 + sandbox profile 实装挂载） |
| GAP-22 | 主动调度不可靠：仅 `supervisor.py` 每日 22:30，不跨重启；无 heartbeat 等价物 | shadow/蒸馏常态运转依赖人工重拉；积压实测 46 条 | P1 |
| GAP-23 | 工具可见性无运行时同步：无指纹/可见性控制，工具增删需重启 + 人工改白名单 | 工具面漂移不可观测，LLM 可能看到过期工具集 | P2 |
| GAP-24 | 无统一 loop 契约：`stop_reason`（7 值）/`max_turns`/软硬预算/`parked` 三态均缺失（**运行时部分已落地：A1-1 `graph_executor` 出口统一，3.1/34-core trace 侧待接**） | 3.1 `stopWhen=5` 与 Ticket 四态各自推导，调度不可复盘、恢复语义错 | **P0** |
| GAP-25 | 工具集非单副本、无受众可见性、无权限顺序（**运行时部分已落地：A1-2 `core/capability/tool_set.py` 由 47 registry 生成唯一快照，3.1 chat 走多壳聚合消费**） | `capability/registry` + 47 roles + 3.1 profile 三处静态清单，权限易漂移 | **P0** |
| GAP-26 | 上下文压缩无锚点、未接 24 BAC（**已落地：A1-3 锚点语义 + A1-4 循环内按阈值自动压缩**） | `graph_store/compressor` 未接协议层循环，长任务目标可能被摘要覆盖 | P1 → **Closed** |
| GAP-27 | 验收无 tripwire 硬失败，45 仍 shadow/INCONCLUSIVE（**运行时已落地：A1-4 `tripwire.py` 双模 + G-L2-10/11 内置门禁；45 HTTP 裁决仍由外部 evaluator 注入**） | 无验收闭环，「修好了」仍可自证 | **P1** |
| GAP-28 | handoff 与 agents-as-tools 未区分 | PlanCard 只表达交接产物，无控制权语义，主控/专家权责不清 | P1 |
| GAP-29 | L1 发现不驱动 L2 任务队列（**生成方 A2-1：`34/core/l2_repair_ledger.py` 生成 trigger 并入队；结算侧 A2-2：`34/core/l2_settle.py` settle + 案例回写 + 周报**） | `repair_ledger.trigger` 契约已冻结但无生成方，「优化」退化为凭感觉 | **P1 → 生成侧/结算侧 Closed** |
| GAP-30 | 无 trace span 契约（`run_id/model_id/step/tokens/cost/stop_reason/context_hash`） | DreamOS/52/3.1 三套 trace 字段无法跨段对账 | P1 |

---

## §7 推进顺序与验收

### 7.1 串行推进（写代码串行，只读调研可并行）

| 阶段 | 内容 | 完成判据（可机器判定） |
|---|---|---|
| **P0-1** | `L2Envelope` 落地 | 12 个 DreamOS 端点 + 4 个 L2 壳全部返回 `meta.model/tokens_used/budget_remaining`；`tokens_used=0 ⇔ model=none` |
| **P0-2** | 信封回归测试 | 新增测试逐出口校验必填字段；失败即红 |
| **P0-3** | 工具面聚合（GAP-19，依赖 P0-0） | 3.1 多壳客户端可同时连 `cognition` + `l2.dreamos`；`platform` profile 可见工具数 ≥10；单壳失败不影响其他壳 |
| **P0-0** | 配额口径统一（GAP-18） | `max_total_tools` 与 `layer_quota.total` 二选一或建立换算；新增 `l2.dsh` 后门禁仍通过（当前 78/80，仅余 2） |
| **P0-4** | 计量同源（GAP-17） | 一次 chat 后 `usage_ledger.jsonl` 新增 ≥1 条且 `cu_cost>0`；`L2Envelope.tokens_used` 与 ledger 折算偏差 ≤2% |
| **P1-1** | 裁决层与 `l2_route` 落地（GAP-13） | `cognition_signal` 全仓非零命中；`route_signal` 含三值枚举；`execution-trace` 落 `trace.sagc.route` |
| **P1-2** | `l2.dsh.mcp` 只读 | 3 工具（Router 摘要 / Ticket 状态 / Worker 角色）+ `exposure=readonly-observe`；配额 17/30 |
| **P1-3** | 双壳退役 | `agent.debate.mcp` → `deprecated` 或移除，L2 活跃工具 = 14 或 17 |
| **P1-4** | 文档与注册表对齐 | 修 GAP-05/06；49 §3.8 与 `mcp_shells/l1_trading` 实现一致 |
| **P1-5** | 开发端台账（GAP-15） | 每次修复/优化产出 `{症状, 根因, 改动, 回归结果, tokens, 优化收益}` 并回写 L0；可按周出修复率/回归通过率（A2-2 ✅：`l2_settle.py` + 周报；tokens 仍待 GAP-17） |
| **P1-6** | 终止语义（GAP-20） | `stop_reason ∈ {done,error,interrupted,parked,cost_limit,max_steps}` 在 3.1 与 34-core 双侧落 trace；`unclassified` <5% |
| **P1-7** | 配额与调度（GAP-18/22） | 注册表总量口径唯一；`supervisor` 可跨重启恢复，积压 ≤5 条 |
| **P2** | 45 门禁转硬 / verdict 汇出 | 误拦率 <5%；`l2.emergence` 可返回 verdict；角色上限已收口（v1.2.1 `max_tools_per_role=10`） |
| **P2-2** | 自扩展前置（GAP-16） | `inspect` 只读接口可用；`unload` 四类副作用回滚验证通过后才允许 `install`（G-L2-9）——A3-1 ✅ inspect；A3-2 ✅ experiment（`disk_writes=0`）；A3-3 ✅ unload 验收器；A3-4 ✅ install 门禁；adapter ✅ 且 sandbox 真实 `add→remove` 通过（清单/锁哈希复原）；P08 ✅ preset 导出+一键加载；probe 协议+Node 采集器+Cordis loader 探针 ✅；bundle 包 ✅ 已装进 sandbox profile（`--dump-config` 可见 entry，安装副本 `probe.complete=true`） |
| **P2-3** | 工具可见性同步（GAP-23） | 工具增删在 1 个刷新周期内对 LLM 可见；指纹变化留痕 |
| **A0** | 总装线契约冻结（GAP-24/25/28/30） | ✅ **完成（Closed）**：`--self-test` 28/28 PASSED（2026-11-16）；A2-1 台账契约 v1.1 增初始入队正例后 29/29（2026-11-17）；四契约 v1.1；未改运行时 |
| **A1** | 单模块改造（GAP-24/25/26/27） | `graph_executor` 返回 `stop_reason`；`capability` 产出唯一 `tool_set`；压缩保留锚点；45 tripwire 先 shadow。**A1-1 ✅（2026-11-16）**：`ExecutionReport.stop_contract()` 返回 7 值出口（软预算 done / 硬预算 cost_limit / max_steps / parked 三态 + `resume_from` / interrupted），`tests/test_a1_graph_executor_stop_reason.py` 8 例绿；三份抽样经 `--stop-reason` 校验 0 violation。**A1-2 ✅（2026-11-16）**：`core/capability/tool_set.py` 由 47 registry 生成唯一 `tool_set`（78 工具 / 3 退役 denied / 4 交易工具强制 human）；D3 配额交叉校验暴露 GAP-18 口径 warning；3.1 `mcp-multi-shell.ts` 多壳聚合（FAIL-OPEN + 冲突留痕）接入 chat；`test_a1_tool_set.py` 9 例 + `mcp-multi-shell.test.ts` 6 例绿，快照 `--tool-set` 校验 0 violation。**A1-3 ✅（2026-11-16）**：`ContextCompressor` 增 24 BAC 锚点语义（目标/最新指令/未完成节点原文保留并重注入 `state.extra.compression_anchors`；trace 首部 `anchor_nodes` 强制保留；Plan `is_required` 节点证据不降级）；`test_a1_compressor_anchors.py` 5 例绿。循环自动触发（GAP-26 后半）留待 A1-4 一并接线。**A1-4 ✅（2026-11-17）**：`compute/tripwire.py` 双模（shadow 记录 / hard 熔断）+ 内置 `G-L2-10` 出口契约、`G-L2-11` 工具集门禁；`GraphExecutor` 增 `tripwire_ids/tripwire_mode/max_inserts/enable_auto_compress`，门禁节点与出口评估、`INSERT_BEFORE` 次数上限、循环内按阈值自动压缩（GAP-26 收口）；`test_a1_tripwire_and_limits.py` 8 例绿 |
| **A2** | 两条反馈回路（GAP-29） | L1 发现可生成 `repair_ledger.trigger` 并入队；L2 settle 回写台账并出周报。**A2-1 ✅（2026-11-17）**：`34/core/l2_repair_ledger.py` + 契约 v1.1 初始自迁移；12 例绿，产出经 `--ledger` 0 violation。**A2-2 ✅（2026-11-17）**：`34/core/l2_settle.py`（settle → 案例回写 L0 → 周报）；10 例绿；W47 周报已生成（0 样本 → null，不造数） |
| **A3** | 自扩展（GAP-21/16） | inspect 只读可用；experiment 沙箱；unload 四类副作用回滚通过后才开 install。**A3-1 ✅（2026-11-17）**：`dreamos/core/capability/plugin_inspect.py`（IF-6 只读插件图，依赖环 fail-closed）；9 例绿，headless 17 插件 0 violation。**A3-2 ✅（2026-11-17）**：`plugin_experiment.py`（manifest/依赖/通道/权限预检，零落盘）；15 例绿，冲突通道 `E_CHANNEL_CONFLICT`。**A3-3 ✅（2026-11-17）**：`plugin_unload.py`（token/mandate 授权 + 四类副作用 before/after 验收）；12 例绿，残留 timer 正确阻断。**A3-4 ✅（2026-11-17）**：`plugin_install.py`（Mandate/白名单/experiment/四类回滚证据四道门禁，无 adapter 拒绝伪造成功）；16 例绿。**adapter 接缝 ✅（2026-11-17）**：`plugin_runtime_adapter.py`（绝对 `file:` 路径 + 包名→目录反查 + 回读 profile 验证 + 可注入 runner + probe 快照，默认 dry-run）；10 例绿，端到端 fake 闭环通过。**真实 apply ✅（2026-11-17）**：项目内 `DSH_HOME` sandbox profile 上 `dsh plugin add/remove dreambuddy-stats` 均 rc=0，`package.json`/`pnpm-lock.yaml` SHA-256 前后一致。**probe ✅（2026-11-17）**：`side_effect_probe.py` 协议 + 完整性门禁、`probes/side_effect_probe.mjs` 采集 timer/connection/handle 与订阅登记；未完整快照被 unload 拒绝。**loader 探针 ✅（2026-11-17）**：`probes/dsh_probe_plugin.mjs` patch `Fiber.prototype.effect`（Cordis `ctx.on` 走此路径），订阅归属 + dispose 自动注销，真实 Cordis 集成测试通过。**profile 挂载 ✅（2026-11-17）**：新增 bundle 包 `dreamos/probes/dsh-probe-plugin/`（`dsh.bundle.patch` + 单文件自包含 `index.mjs` + `cordis.patch.yml` insert），`dsh plugin add file:<abs> --profile sandbox` 安装并自动进 `dsh.profile.bundles`，`--dump-config` 出现 `# == dreambuddy-side-effect-probe` entry；用 profile 内已安装副本跑真实 Cordis：`probe.complete=true`、订阅归属 `sub:p-installed:agent/pre-step`、dispose 后四类清零，Python `require_complete` 通过 |

### 7.2 接口冻结点（不能拖到下一阶段）

| 冻结点 | 内容 | 冻结后禁止 |
|---|---|---|
| **IF-L2-1** | `L2Envelope` 字段集（SPEC-56 §4.3） | 新增字段必须升版本，禁止各壳私加 |
| **IF-L2-2** | `route_signal` 的 `l2_route` 枚举 | 禁止用自由文本表达路线 |
| **IF-L2-3** | OKR 节点契约 `{node_id,objective,criteria,source,verify,evidence_id?}` | 禁止新增 `verify` 取值 |
| **IF-L2-4** | 层级 MCP 命名与 `requires_mandate` 语义 | 禁止 `l2.*` 写工具免 Mandate |

### 7.3 部署与验收命令（复跑用）

```bash
# 1) 层级 MCP 注册表校验（当前应输出 17 壳 / 78 active / 上限 120）
python3 47-MCP管理系统/registry/scripts/validate_mcp_registry.py

# 2) DreamOS 健康检查（12 端点之一）
curl -s http://127.0.0.1:8000/api/v1/health
curl -s http://127.0.0.1:8000/api/v1/nodes | python3 -c "import sys,json;print(json.load(sys.stdin)['total'])"

# 3) 3.1 前端（3001）
cd 3.1-FRONTEND && npm run test          # 契约与意图路由测试
```

**验收口径**：`validate_mcp_registry.py` 退出码 0；`/api/v1/health` 返回 `status=ok`；`/api/v1/nodes` 返回 28；前端 `npm run test` 全绿。任何一项不达标，不得宣称 L2「已完成」。

---

## §8 跨域协作边界

| 对方 | 56 提供 | 56 索要 | 硬约束 |
|---|---|---|---|
| 54-L1 能力聚合层 | 路由交接消费方、L2 出口 | `route_signal`、只读能力出口 | L2 不写 L1；54 不调用 L2 内部实现 |
| 48-涌现架构 | 实验触发与 verdict 展示面 | verdict 四态 + 度量快照 | 涌现主张必须 48 出具，L2 只转发 |
| 6-交易中台 | 意图路由与话题边界 | A0–A9 产物路径 | 实盘永禁 L2 直接触发（live 由 22/47 管） |
| 47-MCP 管理 | 层级壳注册 | 配额、`layer/exposure` 校验 | 壳不得绕过注册表 |
| 34-训练系统 | 编排与门禁宿主 | Router/Ticket/Mandate 契约 | E 不做业务决策 |

---

## §9 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-16 | 首版：建立 56 目录；冻结 L2 五子层能力地图与 43 项能力登记（K14/E12/G8/P5/A4）；实测 MCP 现状（17 壳 / 78 active / L2 14 active / 配额 120）；登记 12 项缺口与 P0–P2 推进顺序；新增 SPEC-56（ADR-01~08、IF-1~IF-4、G-L2-1~6）。 |
| v0.2 | 2026-11-16 | 按评审 R1–R6 修订：IPC 命令 17→**18**（补 `data.dal_query`）；53 插件「3 个」→**13 条 approved**；`L2-E09` 由 🟡 改 **✅**（校验器 L379–L435 已实现角色上限校验）并新增口径冲突 Q4/GAP-11；`L2-K07` 改为「两宿主两实现」（`core/compute` vs `cdrive_v3_router`）+ Q5；25–28 补端口行号证据、45 门禁由 ✅ 降 **🟡**（注入式，生产注入点待核，GAP-14）；新增 **GAP-13（`cognition_signal`/`l2_route` 零实现）** 并将 P1-1 升级为裁决层落地。 |
| v0.3 | 2026-11-16 | 关闭 GAP-11：注册表 v1.2.1 增 `max_tools_per_role: 10`，校验器角色检查与单壳上限解耦（Q4 采 B 已落地；负例 11 工具角色被拒）。关闭 GAP-14：新增 `core/gate_45_runtime.py`，`resolve_settle_gate()` 接入 `data_query_executor#L1718` 与 `settle_case_cli#L50` 两处 settle，默认关（H2 字节等价），启用需注册 payload builder + `DREAM_GATE_45_MODE`。新增 `tests/test_gate_45_runtime.py`（5 例）。 |
| v0.4 | 2026-11-16 | 固化三层职责边界（ADR-09 / §0.2.1 / SPEC §2.4）：L0 确定性给事实、L1 统计+涌现给证据、L2 生成与编排给动作；明确 **L2 内部应用=开发端（修 bug/优化）为主负载**，发现权归 L1、验收权归 45、计量归 L2；新增 `L2-K15` 开发端闭环与 GAP-15（缺修复台账度量），P1-5 登记。 |
| v0.5 | 2026-11-16 | 按「边界 + Creator Mode」两点深化：§0.2.1 增分层判定顺序；新增 §2.6 开发端闭环与自扩展（含 Harness Creator Mode 对照与结论「差距在自检/回滚而非模型」）；新增 `L2-K16` 修复台账、`L2-P06/P07/P08` 自检/内存实验+回滚/preset，GAP-16；§4.4 冻结 `RepairLedger` 字段；SPEC 增 §2.5 开发端状态机、§2.6 自扩展边界、IF-5/IF-6、G-L2-7/8/9、ADR-10、P3/P4、Q6/Q7。 |
| v0.6 | 2026-11-16 | 按评审 §六 落地 6 件产物：`contracts/repair_ledger.schema.json`（Draft 2020-12，`schema_version=1.0`）、`contracts/plugin_extension.schema.json`（四动作 + 6 错误码）、`contracts/state_machine.yaml`（7 态 / 10 边 / 重开 `attempts+1`）、`scripts/validate_contracts.py`（`--self-test` 1 正 5 负 + 插件 1 正 1 负，9/9 通过）、`tests/test_contracts.py`；SPEC §2.5 改为迁移表、§4.5/§4.6 改为引用 schema、G-L2-7/8/9 改为可执行判据；台账落点 `34-前端应用训练系统/l2_repair_ledger.jsonl`。 |
| v0.7 | 2026-11-16 | 按 33-REA 逆向解析 52/LobeHub 协议（[报告](./REA-lobehub协议逆向解析-v0.1.md)，snapshot `bb9c106bbbfd32fc`/`c315b6c904379e2f`/`467a577eed73fc77`）：`L2-P01` 补「与内核未打通」；新增 `L2-P09` 算力计量、`L2-P10` 工具 profile；`L2-P07` 由 ⬜ 升 🟡（52 F5 包级启停 + 审计）；新增 GAP-17~23（计量双轨 / 配额口径冲突 / 单壳未聚合 / 终止语义不通约 / 插件回滚不完整 / 调度不跨重启 / 可见性无同步）；P0 新增 P0-3/P0-4，P1 新增 P1-6/P1-7，P2 新增 P2-3。实测：17 壳 / 84 声明 / 78 活跃（剩 2 余量）/ L2 14；52 trace 98 / outbox 141 / 游标 95（积压 46）/ CU 账本不存在。**基线 T2 结论：GAP-18 升 P0 并新增 P0-0，作为 GAP-19 的前置**（新增 `l2.dsh` 3 工具即 81>80）。 |
| v0.8 | 2026-11-16 | 按三源总装线对标（[报告](./总装线对标-三源与DreamOS逐模块优化-v0.1.md)）：LobeHub 7 值停止原因 / operationToolSet 单副本 / 锚点压缩，OpenAI handoff vs agents-as-tools / guardrails tripwire / background，Claude 权限顺序 / 子 agent 隔离 / max_budget；映射 DreamOS 七目录（sense/arrange/capability/compute/graph_store/scheduler/artifact）；新增 GAP-24~30（loop 契约 / 工具集单副本 / 压缩锚点 / tripwire / handoff 语义 / L1 发现入队 / span 契约）；路线新增 A0 契约冻结→A1 单模块→A2 两回路→A3 自扩展，新增对照实验 H4/H5。 |
| v0.9 | 2026-11-16 | A0 四契约落盘（`contracts/stop_reason.schema.json`、`tool_set.schema.json`、`span.schema.json`、`plan_handoff.schema.json`）；`validate_contracts.py` 扩为 6 类校验 + 25 项自检（新增 `--stop-reason/--tool-set/--span/--plan`）；SPEC 增 IF-7 / ADR-11 / G-L2-10-11；不改运行时。评审后修复：交易工具强制 `requires_mandate=true`；`generated_at` 由校验器解析 RFC3339。 |
| v1.0 | 2026-11-16 | A0 评审裁决落地（[评审记录](./REVIEW-20261116-A0契约与总装线对标评审.md)）：`stop_reason`/`plan_handoff` 升 v1.1 必填 `trace_id`；`no_next_context` 改为不可续跑；新增负例 18/19/20；自检增至 28 项（四契约 20 + 台账/插件 8）。四契约 20 项正负例只读复算通过；全量 `--self-test` 待受信任终端执行。 |
| v1.1 | 2026-11-16 | **A1-1 落地**：`core/compute/types.py` 增 `ExecutionReport` 出口字段 + `stop_contract()`（resumable 仅由 `stop_reason` 推导）；`graph_executor.execute()` 增 `soft_budget/trace_id/run_id/resume_from/cu_per_token/should_interrupt`，实现 done/cost_limit/max_steps/parked/error 出口与独立恢复入口；`NodeStatus.PARKED` + `NodeResult.parked_reason`；`NodeRunner` 映射 parked。证据：`tests/test_a1_graph_executor_stop_reason.py` 8/8 绿；三份 `stop_contract` 抽样经 `validate_contracts.py --stop-reason` 均 0 violation。`no_next_context` 待 handoff 语义接入后由上下文丢失路径产生。 |
| v1.2 | 2026-11-16 | **A1-2 落地**：新增 `1-ARCHITECTURE/dreamos/core/capability/tool_set.py`（47 registry → `tool_set` v1.0 唯一快照；`source=47-registry`；壳 ID 连字符规范化 `l0.trade_exec.mcp`；退役壳同名工具以活跃为准进 `denied_tools`）；新增 `quota_report()` 做 D3 交叉校验（分层/总量/单壳/角色 + `E-TOTAL-CAP-MISMATCH` 口径 warning）；3.1 新增 `src/lib/agent/mcp-multi-shell.ts`（多壳聚合、FAIL-OPEN、冲突留痕、`DREAMBUDDY_MCP_SHELLS` 环境扩展）并接入 `api/agent/chat`。证据：`test_a1_tool_set.py` 9/9、`mcp-multi-shell.test.ts` 6/6、`tsc --noEmit` 对改动文件无错、快照 `--tool-set` 0 violation。 |
| v1.3 | 2026-11-16 | **A1-3 落地**：`core/graph_store/compressor.py` 接 24 BAC 锚点语义——`_collect_anchors()` 收集 Blueprint `objective` / `intent.user_message` / 未完成节点（`selected_nodes`/`steps`/`deferred_nodes`/`execution_plan` 减已完成）；trace 压缩改为「首部 `anchor_nodes`（默认 2）强制保留 + 最近 N 条」，中间才进摘要；Plan `is_required` 节点结果不降级；锚点重注入 `state.extra["compression_anchors"]`；`CompressedState` 增 `anchors` / `anchored_node_ids`。证据：`test_a1_compressor_anchors.py` 5/5 绿。 |
| v1.4 | 2026-11-17 | **A1-4 落地（A1 收口）**：新增 `core/compute/tripwire.py`（`TripwireRegistry` + 内置 `G-L2-10` 出口契约门禁 / `G-L2-11` 工具集门禁；shadow 记录、hard 熔断 fail-closed；evaluator 异常 FAIL-OPEN 记 INCONCLUSIVE）；`GraphExecutor` 增 `tripwire_registry/tripwire_mode/max_inserts/enable_auto_compress` 与 `execute(tripwire_ids, tripwire_mode)`，在门禁节点与出口评估，`INSERT_BEFORE` 超限跳过，循环内按 `compressor.should_compress` 自动压缩；`ExecutionReport` 增 `tripwire_history` / `compression_count`。证据：`test_a1_tripwire_and_limits.py` 8/8；A1 四组测试合并 30/30 绿。GAP-26 关闭；GAP-27 运行时部分落地（45 HTTP 裁决待外部 evaluator 注入）。 |
| v1.5 | 2026-11-17 | **A2-1 落地 + 台账契约 v1.1**：发现契约无法表达「刚入队」（`history[-1].to==state` ⇒ 需 `to=reported`，但原枚举与状态机均无该迁移），经裁决升 v1.1：`schema_version=1.1`、`history.to` 增 `reported`、状态机增 `reported→reported` 初始边（不计数 attempts、无 guard）；新增 `34-前端应用训练系统/core/l2_repair_ledger.py`（L1 发现 → trigger → 台账，fail-closed + 幂等 + task_id 递增 + 复现产物哈希；优化类强制 45/stats 与 metrics）；`--self-test` 29/29。证据：`tests/test_l2_repair_ledger.py` 12 例绿，产出经 `--ledger` 0 violation。 |
| v1.6 | 2026-11-17 | **A2-2 落地（A2 收口）**：新增 `34-前端应用训练系统/core/l2_settle.py`——只允许 `regression_passed→settled`（回归失败 / 缺 run_ids / 非法状态 fail-closed），补齐 `evidence.regression`、`settled` 四分流、`run_ids` 并原子替换台账；案例回写 L0 落点定为 `34/l1_case_store.jsonl`（`case_type=l2_repair`，按 task_id 幂等，`case=skipped` 不写）；周报口径修复率 `settled/(settled+abandoned)`、回归通过率 `passed/regression_evidence`、优化收益 `before/after/delta`，0 样本记 null；CLI `weekly`/`settle`，`reports/l2_weekly_2026-W47.md` 已生成（0 样本，明确标注不造数）。证据：`tests/test_l2_settle.py` 10/10、A2 合并 22/22、`--self-test` 29/29、settle 产出经 `--ledger` 0 violation。GAP-15 台账/周报侧关闭（tokens 待 GAP-17）。 |
| v1.7 | 2026-11-17 | **A3-1 落地（inspect 只读）**：新增 `1-ARCHITECTURE/dreamos/core/capability/plugin_inspect.py`——读 DSH profile `package.json` + 本地插件包清单/源码，静态产出 IF-6 `inspect.response`（插件/依赖/事件通道/能力面）；`file:` 指向缺失包进 `graph.unresolved`，依赖环 fail-closed（契约只允许 `acyclic=true`，不伪装成功）；全程只读不写盘；CLI `python3 -m dreamos.core.capability.plugin_inspect --profile <p>`。实测 headless：17 插件 / 0 unresolved / 8 tools / 9 subscribe / 1 publish，响应经 `--plugin` 0 violation。证据：`tests/test_a3_plugin_inspect.py` 9/9、A1+A3 合并 39/39、`--self-test` 29/29。GAP-21 inspect 侧关闭；experiment/unload 仍未开。 |
| v1.8 | 2026-11-17 | **A3-2 落地（experiment 沙箱预检）**：新增 `1-ARCHITECTURE/dreamos/core/capability/plugin_experiment.py`——manifest 校验（plugin_id/version/entry/permissions/event_channels 闭集）+ 依赖可解析（复用 A3-1 插件图）+ 发布通道冲突 + 权限面（拒绝 `exec`/`fs.write`）；只做内存预检、不执行第三方代码，响应恒 `disk_writes=0`、`rollback_ok=true`，错误码走 IF-6 枚举。实测 headless：合法 manifest → `ok/loaded=true`；发布 `agent/turn-stopping` → `E_CHANNEL_CONFLICT`（与 reflector 冲突），两份响应经 `--plugin` 0 violation。证据：`tests/test_a3_plugin_experiment.py` 15/15、A1+A3 合并 54/54、`--self-test` 29/29。GAP-21 experiment 侧关闭；unload 四类副作用回滚待 A3-3。 |
| v1.9 | 2026-11-17 | **A3-3 落地（unload 四类副作用验收）**：新增 `1-ARCHITECTURE/dreamos/core/capability/plugin_unload.py`——校验 rollback_token（token_id/idempotency_key/未过期）+ Mandate（scope=plugin.unload/未过期），对 before/after 快照逐类比对 `subscription`/`connection`/`handle`/`timer`：插件自有副作用必须清零、其他插件副作用不得误删；全清且插件已消失才 `ok=true`，残留类别不写入 `side_effects_reverted`。不执行卸载、不伪造运行时状态，缺快照即拒绝。演练实测：干净卸载四类全回滚；残留 `timer` 正确 `ok=false`，两份响应经 `--plugin` 0 violation。证据：`tests/test_a3_plugin_unload.py` 12/12、A1+A3 合并 66/66、`--self-test` 29/29。GAP-21 验收器关闭；真实 DSH 运行时快照接入 + A3-4 install 仍未开。 |
| v1.10 | 2026-11-17 | **A3-4 落地（install 门禁）**：新增 `1-ARCHITECTURE/dreamos/core/capability/plugin_install.py`——四道硬门禁：request 形状 + `rollback_verified=true`、Mandate（scope=plugin.install/未过期）、53 白名单（approved / 非 forbidden / permitted_profiles / 生产 profile 需 sandbox+FAIL-OPEN 验证）、`plugin_ready`（A3-2 experiment 通过且 `disk_writes=0` + A3-3 四类回滚证据齐全）。通过门禁后必须注入 `InstallAdapter` 才执行落盘；未注入即 fail-closed，禁止伪造 `installed=true`（契约 const true 无法表达失败，故以异常拒绝）。真实预检：`dreambuddy-c1 @ sandbox` 门禁通过；未登记插件被 deny-by-default 拒绝。证据：`tests/test_a3_plugin_install.py` 16/16、A1+A3 合并 82/82、`--self-test` 29/29、合法 install.response 经 `--plugin` 0 violation。GAP-21 门禁关闭；真实 DSH adapter 与 P08 preset 待接。 |
| v1.11 | 2026-11-17 | **adapter 接缝落地（A3 收尾）**：新增 `1-ARCHITECTURE/dreamos/core/capability/plugin_runtime_adapter.py`——`DSHCommandAdapter` 生成 `dsh plugin add/remove --profile` 命令（本地包解析为 `file:../../packages/<id>`），执行后回读 profile `package.json` 确认登记/移除（不信任退出码）；`Default dry-run`（`apply=False` 只出计划）；runner 可注入，测试用 fake DSH 在临时 profile 上跑通 `install → token 签发 → remove → 四类快照 → A3-3 验收` 全闭环；四类副作用只来自 probe 命令，未配置即拒绝编造。证据：`tests/test_a3_runtime_adapter.py` 9/9、A1+A3 合并 91/91、`--self-test` 29/29。真实 DSH `apply=True` 仍未对生产 profile 执行。 |
| v1.12 | 2026-11-17 | **真实 apply 验证（sandbox）**：暴露并修复两处真实缺陷——`file:` 相对路径受 cwd 影响（改为绝对路径）、本地包目录名 ≠ `package.json` 的 `name`（新增按包名反查目录）。修复后在项目内 `DSH_HOME` 的 sandbox profile 实测：`dsh plugin add file:<abs>` rc=0（1.46s，pnpm +16/-78），profile 登记 `dreambuddy-stats`；`remove` rc=0（1.02s），清单回到原始 4 项；`package.json` 与 `pnpm-lock.yaml` 的 SHA-256 前后完全一致。证据：`test_a3_runtime_adapter.py` 10/10、A1+A3 合并 92/92、`--self-test` 29/29。注意：`dsh` 默认读 `~/.dsh`，测试需显式 `DSH_HOME=<repo>/.dsh-home`；四类副作用 probe 仍未接。 |
| v1.13 | 2026-11-17 | **P08 落地（preset 导出）**：新增 `1-ARCHITECTURE/dreamos/core/capability/preset_export.py`——从 A3-1 插件图 + 53 白名单生成「可部署集合」：只收 `approved`/非 `forbidden`/profile 允许的插件，其余进 `skipped` 并注明 `unregistered`/`not_approved`/`forbidden`/`profile_not_permitted`；插件按 `plugin_id` 排序，`preset_hash` 只覆盖 `{name,version,plugins}`（不含 `generated_at`），`verify_preset` 重算 hash 并拒绝乱序/篡改。真实 headless 导出：12 plugins / 5 skipped，hash `sha256:aea55b0f…`。证据：`tests/test_a3_preset_export.py` 10/10、A1+A3 合并 102/102、`--self-test` 29/29。GAP-16 仅剩「preset 一键加载」；GAP-21 仅剩四类 probe。 |
| v1.14 | 2026-11-17 | **GAP-16 收口（preset 一键加载）+ GAP-21 采集器（probe）**：新增 `preset_load.py`——先校验 preset hash/排序、Mandate（`plugin.install`）、experiment、四类回滚证据、白名单逐插件复核，再计算「待装/已装」；默认 dry-run，`apply=True` 且注入 adapter 才执行，单点失败进 `failed` 且 `ok=false`。真实 headless dry-run：12 已装 / 0 待装 / 5 skipped。新增 `side_effect_probe.py` + `probes/side_effect_probe.mjs`——probe 快照协议（四类 + `probe.complete`）、`static_probe` 只推导订阅并标记其余不可用、`plugin_unload` 拒绝 `complete=false` 的快照；Node 采集器用 `AsyncLocalStorage` 归属 owner，hook `setInterval/setTimeout/net.Socket.connect/fs.watch/child_process.spawn`，订阅由 loader `registerSubscription` 登记。Node 实测：插件内 timer/handle 被归属、clear/close 后清零；未开启订阅采集 `complete=false`。证据：`test_a3_preset_load.py` 8/8、`test_a3_side_effect_probe.py` 7/7、`test_a3_node_probe.py` 2/2、A1+A3 合并 119/119、`--self-test` 29/29。剩余：DSH loader 调用 `withOwner/registerSubscription` 的接线。 |
| v1.15 | 2026-11-17 | **GAP-21 loader 接线（Cordis 探针插件）**：新增 `1-ARCHITECTURE/dreamos/probes/dsh_probe_plugin.mjs`——Cordis `ctx.on` 最终经由 `fiber.effect(..., 'ctx.on("<event>")')`，故只 patch `Fiber.prototype.effect`：开启订阅采集、effect 回调在 `withOwner(fiberName)` 下执行、`ctx.on(...)` label 自动登记订阅并挂一个随 fiber 销毁的 cleanup effect；卸载时还原原型。实测（真实 Cordis，非 mock）：插件 `ctx.on('agent/pre-step')` 被归属为 `sub:p-new:agent/pre-step`，`probe.complete=true`，`fiber.dispose()` 后订阅清空。期间修正两处：`ctx.constructor` 是 Context 而非 Fiber（改用 `ctx.fiber`）、effect 返回的 disposer 不归 fiber 管理（显式注册 cleanup effect）。证据：`test_a3_dsh_loader_probe.py` 1/1（2 组断言）、A1+A3 合并 120/120、`--self-test` 29/29。剩余仅为把探针挂进实际 profile（运维动作）。 |
| v1.16 | 2026-11-17 | **GAP-21 实装收口（探针挂进 sandbox profile）**：新增 DSH bundle 包 `1-ARCHITECTURE/dreamos/probes/dsh-probe-plugin/`——`package.json` 声明 `dsh.bundle.patch`、`index.mjs` 单文件自包含（采集器 + Cordis 插件）、`cordis.patch.yml` 以 `insert` 把 `dreambuddy-side-effect-probe` 插入组合树；`dsh plugin add file:<abs> --profile sandbox`（显式 `DSH_HOME=<repo>/.dsh-home`）安装 rc=0，并自动写入 `dsh.profile.bundles`。验证三层：① profile 内裸包名 `import('dreambuddy-side-effect-probe')` 导出齐全；② `dsh --profile sandbox --dump-config` 出现 `# == dreambuddy-side-effect-probe` entry；③ 用 node_modules 里「已安装副本」跑真实 Cordis（非源码路径）：`probe.complete=true`、`unavailable=[]`、订阅 `sub:p-installed:agent/pre-step`、timer 归属 `p-installed`，`fiber.dispose()` 后订阅与 timer 均清零，快照经 Python `require_complete` 通过。踩坑：pnpm `file:` 依赖是硬链接（共享 inode、只同步同名文件），新增文件不会被复制 → 改为单文件自包含；父目录 `side_effect_probe.mjs` / `dsh_probe_plugin.mjs` 保留为转发入口，原有测试与文档路径不变。证据：A1+A3+capability 合并 140/140、`test_a3_dsh_loader_probe.py` 1/1、`--self-test` 29/29。GAP-21 全部关闭。 |
