# DESIGN:DSH 量化交易团队（Q-TEAM）v0.1

> **版本**: v0.9 ｜ **日期**: 2026-11-18 ｜ **状态**: 设计定稿；对外任务看板（§十一）T0–T2 已落地，T3 待 SSE；§11.8 T4-1~T4-5、P0 治理最小闭环（Agent 席位 / 空审批人兜底 / SLA 巡检 / 退回生效 / 终止 / 批量确认）、§十二 三类模型 / JEV 会签 / 双运行模式 / 409 拦截 / 待办中心已落地
> **定位**: 在 DSH 内组织「多 Agent 量化交易团队」，以 6-TRADING 为流程与阈值 SSoT，DreamOS SACG 为编排骨架
> **上游**: [SPEC-SYSTEM-ARCH-CAPABILITY v1.0](../../../1-ARCHITECTURE/specs/SPEC-SYSTEM-ARCH-CAPABILITY-v1.0.md)（架构总纲）｜ [DESIGN-DSH-ARCH-UPGRADE-v0.2](DESIGN-DSH-ARCH-UPGRADE-v0.2.md) ｜ [3+3架构模块映射](../../../1-ARCHITECTURE/3+3架构模块映射.md) ｜ [A_SERIES_DETAIL](../../../6-TRADING/A_SERIES_DETAIL.md) ｜ [DOC_INDEX](../../../6-TRADING/DOC_INDEX.md)
> **门禁制度依据**: [RESEARCH-GATE-INSTITUTIONS-v0.1](RESEARCH-GATE-INSTITUTIONS-v0.1.md)
> **已定决策**: ① C-drive 双模式开关 ② 编制 8+2+领队 ③ 能力注册「主表 + 角色投影」

---

## 一、问题与差距

### 1.1 三个认知纠正

| # | 现状事实 | 影响 |
| --- | --- | --- |
| 1 | DSH 的 8 个子代理是 technical / sentiment / macro / flow / valuation / onchain / risk / portfolio；**c_drive 与 debate 不在其中** | c_drive 是 C 层调度者，debate 是其内部一步。当前把它们注册成 `dsh.*` 能力属于**层放错** |
| 2 | 6-TRADING 是流程、阈值与验收标准的 SSoT；其脚本承担确定性计算 | 不应把 6-TRADING 当成"另一个 Agent 系统"，而应作为**规则层**被团队引用 |
| 3 | DSH 子代理契约是"隔离执行 / 互不通信 / 只回摘要" | 多 Agent 协作必须由领队扇出聚合，**不能靠子代理互相调用** |

### 1.2 c_drive 为何"没融进 DreamOS"

c_drive 已具备调度语义：节点→子代理路由、分级阈值、SUPPLEMENT 路由、Bull/Bear 辩论（见 `c_drive_agent.py` 的 `_NODE_MODULE_MAP` 与 `CONF_*` 常量）。但它目前只被当作**事后裁判**调用：

- 对话层：作为叶子能力 `dsh.c_drive` 排在维度结果之后；
- `dsh-execution-engine`：仅在 reflect 阶段调用；
- 6-TRADING 脚本：完全不调用。

缺的不是算法，而是**三样授权**：Ticket、DAG 派工权、Verdict 终止权。SACG 的 C 层要的正是这个。

### 1.3 其他必须在设计期内解决的缺口

- 子代理不取数（HC-1），调用方必须注入；已为 technical/macro/sentiment 补真实数据注入；
- GDP 无入库源、新闻无极性源：只能进 `data_quality`，禁止用 0/中性冒充；
- 主表若按角色复制多份，必然漂移。

---

## 二、团队编制（8 + 2 + 领队）

| 分组 | 角色 ID | 对应 6-TRADING | 来源 |
| --- | --- | --- | --- |
| 领队 | `c_drive.supervisor` | A0 矛盾识别 + 调度 | 现有 c_drive 升级 |
| 研究 Pod | `macro` / `onchain` / `flow` | A1 深度调研 | 现有 |
| 结构 Pod | `technical` / `sentiment` / `valuation` | A2 第一性原理 | 现有 |
| 推演 Pod | `scenario`（红队+三情景）/ `tactical`（关键位+委托方案） | A3 沙盘 / A4 战术验证 | **新增** |
| 风控 Pod | `risk` / `portfolio` | A9 离场 + 仓位 | 现有 |
| 横切 | `okr_verifier` / `report_writer` | A7/A8 + G 层 | 不进 Worker 池 |

**不在团队内**：A5 下单执行、A6 实时盯盘。团队只产出研判与方案，交易热路径零接入（沿用 H5 红线）。

---

## 三、核心契约

### 3.1 TradingTicket

```json
{
  "ticket_id": "tk_20261118_btc_01",
  "trace_id": "tr_...",
  "spec_id": "spec_...",
  "symbol": "BTC",
  "timeframe": "4h",
  "intent_type": "trading_analysis",
  "dag": [
    { "step": "A1", "role": "macro", "depends_on": [], "required": true },
    { "step": "A1", "role": "onchain", "depends_on": [], "required": true },
    { "step": "A2", "role": "technical", "depends_on": ["A1"], "required": true },
    { "step": "A3", "role": "scenario", "depends_on": ["A2"], "required": true },
    { "step": "A4", "role": "tactical", "depends_on": ["A3", "risk"], "required": true }
  ],
  "mandate": {
    "allowed_capabilities": ["data.macro_snapshot", "market.series", "dsh.macro"],
    "max_tool_calls": 12,
    "max_latency_ms": 90000
  },
  "state": "live"
}
```

状态机沿用四态：`live / paused / waitsForPerson / ended`；`paused` 与 `waitsForPerson` 不占 Worker 槽。

### 3.2 TradingOKR（A 层验收标准）

每条 KR 必须绑定 6-TRADING 的硬标准，且可机器判定：

| 阶段 | KR 判据样例 | verify 类型 |
| --- | --- | --- |
| A0 | ≥3 条可证伪矛盾，每条附 evidence_refs | evidence_backed |
| A1 | 每个维度带数据时间戳与来源；缺失项进 data_quality | evidence_backed |
| A2 | 最小阻力路径 + 数值化失效阈值 | evidence_backed |
| A3 | 三情景，概率合计 100%±2，各带触发条件 | gap_closed |
| A4 | 委托方案含入场/止损/目标/仓位上限，且无下单动作 | c_action |
| risk | 仓位 ≤ Mandate 预算；VaR 超限需书面约束 | c_action |

### 3.3 DispatchPlan / VerdictBundle

```json
{ "plan_id": "...", "ticket_id": "...", "phase": "A2",
  "tasks": [{ "role": "technical", "capability_ids": ["market.technical_indicator"],
              "inject": { "symbol": "BTC" }, "depends_on": [] }],
  "budget": { "max_tool_calls": 12 } }
```

```json
{ "ticket_id": "...", "main_contradiction": "...", "direction": "LONG|SHORT|NEUTRAL",
  "confidence": 0.62, "key_levels": { "support": 0, "resistance": 0 },
  "invalidation": ["跌破 X 且放量"], "conflicts": ["技术面多 vs 情绪面空"],
  "data_quality": [{ "item": "macro.gdp_yoy", "status": "missing" }],
  "evidence_refs": ["l1:...", "dsh:..."] }
```

### 3.4 Brief / Report（G 层）

- 简报：一句话结论 + 3 条要点 + 置信度 + data_quality，≤300 字；
- 研报：完整维度、关键位、情景、失效条件、证据清单；
- 两者都必须引用工具输出，禁止自由生成数字。

---

## 四、工作流 S → C → A → G

```
触发（用户问题 / 事件）
  ↓
S1 意图识别与复杂度分级（零 token 优先）
    ├ 直答：L1 单点能力
    ├ 团队研判：A1→A2→C→G
    └ 全流程：A0→A4→C→A→G
S2 生成 Spec：IntentSpec + TradingOKR（复用 intent-spec-writer）
S3 按需取证：brainstorming / 外部采集 / REA —— 信息足够即停（预算门）
  ↓
C1 Supervisor 建 Ticket DAG，按 Pod 派工，下发 Mandate
C2 Worker 并行：只用角色能力集 → SubagentOutput（含 evidence_refs + 数据时间戳）
C3 聚合裁决：冲突走 debate；低置信走 SUPPLEMENT（最多 2 轮）→ VerdictBundle
  ↓
A1 逐条 KR 验收 + 45 门禁：证据不全 = FAIL，不进入 G
  ↓
G1 简报（默认）/ 研报（详情）
G2 settle 回写 L0；A8 写 Episode/Lesson
```

**失败路径**：任一必需维度缺失 → 标记 `partial`，结论必须写明缺口；A 层判 FAIL 时只输出"数据不足"报告，不出方向。

---

## 五、C-drive 双模式

同一个 Agent，两个契约，开关 `CDRIVE_SUPERVISOR`（默认 `false`）：

| 模式 | 方法 | 职责 | 是否改行为 |
| --- | --- | --- | --- |
| judge（默认） | `run(node_id, result, state, signals)` | 事后裁决、辩论、补充建议 | 不变，字节等价 |
| supervisor | `supervise(ticket, dag, state)` | 读 Ticket/DAG → 产出 DispatchPlan → 收集结果 → 冲突/补充 → VerdictBundle | 新路径，开关控制 |

约束：
- Supervisor **只读**，不执行 settle（ADR-9）；
- 不做业务判定，只做派工、聚合、终止；
- 最大 2 轮补充，防死循环；
- 所有分派带 `trace_id`，落 `dsh_calls`。

---

## 六、能力注册：主表 + 角色投影

### 6.1 主表

`3.1-FRONTEND/src/lib/agent/capability-registry.json` 增加 `roles` 字段：

```json
{
  "id": "data.macro_snapshot",
  "layer": "L1",
  "roles": ["macro", "tactical", "scenario"],
  "readonly": true,
  "l2_allowed": true,
  "enabled": true
}
```

### 6.2 角色投影（构建期生成，不手写）

- 输出：`src/lib/agent/capability-profiles/<role>.json`（每角色 ≤10 项）；
- 运行时：`runCapability(id, params, { role })` 二次校验，未授权直接拒绝；
- 投影文件只是视图，**主表是唯一 SSoT**；新增能力只改主表并重跑投影。

### 6.3 角色能力集（首版）

| 角色 | 能力 |
| --- | --- |
| macro | data.macro_snapshot / market.series / news.listing / dsh.macro / l0.recall |
| onchain | data.onchain_cycle / market.series / dsh.onchain / l0.recall |
| flow | market.series / data.onchain_cycle / dsh.flow |
| technical | market.price / market.technical_indicator / market.series / dsh.technical |
| sentiment | data.onchain_cycle / news.listing / dsh.sentiment |
| valuation | data.fundamental_snapshot / market.series / dsh.valuation |
| scenario | dsh.debate / l0.recall / 历史案例 |
| tactical | trading.backtest / trading.screen_first / dsh.risk / A4 脚本 |
| risk | dsh.risk（纯算法）/ 组合数据 / 风控限额 |
| portfolio | dsh.portfolio / 持仓数据 |
| okr_verifier | 45 门禁 API / evidence bundle（只读） |
| report_writer | /api/reports/generate / artifacts（只写报告） |

**c_drive / debate 不进分析员能力集**，归控制器专用。

---

## 七、与 6-TRADING 的职责边界

| 事项 | 归属 |
| --- | --- |
| A0-A9 阶段定义、阈值、验收标准 | 6-TRADING（SSoT） |
| 回测、筛选、风险数值、离场规则等确定性计算 | 6-TRADING 脚本 / L1 |
| 维度判断（技术/情绪/宏观/估值/链上/资金） | DSH 子代理 |
| 派工、冲突裁决、终止 | C-drive Supervisor |
| 验收 | A 层 OKR + 45 门禁 |
| 简报 / 研报 | G 层 |

一句话：**6-TRADING 定规则，L1 算事实，DSH 做判断，C 层调度，A 层验收，G 层输出。**

---

## 八、落地路径

| 阶段 | 交付 | 退出判据 |
| --- | --- | --- |
| **P0** | 主表加 roles + 投影脚本 + macro/technical 两角色 + 模型注册表（三类模型）+ A 层"证据完整性"校验 | 两个角色端到端出 VerdictBundle，越权调用被拒；三类模型启动校验通过，gate 与 worker 异构 |
| **P1** | supervisor 模式（开关）+ scenario/tactical + 完整 DAG | 开关关断行为等价；开启后按 DAG 并行 |
| **P2** | 45 门禁转硬门 + G 层带 data_quality 的简报/研报 | 未过验收 0 条进入报告 |
| **P3** | 事件驱动 + settle 沉淀 + A8 复盘 | 同类分析 recall 可命中历史案例 |

### 参考实现位置

- 子代理注册与输出契约：`1-ARCHITECTURE/dream-harness-bridge/packages/python-server/subagent_registry.py`、`subagent_types.py`
- C 层调度：`.../c_drive_agent.py`
- 能力主表与调度：`3.1-FRONTEND/src/lib/agent/capability-registry.{json,ts}`
- Spec 与澄清：`3.1-FRONTEND/src/lib/planner/intent-spec-writer.ts`
- A 层 OKR：`34-前端应用训练系统/core/okr_nodes.py`
- 45 门禁：`45-评测系统/api/server.py`
- G 层报告：`3.1-FRONTEND/src/app/api/reports/generate/route.ts`

---

## 九、红线与验收

| # | 红线 |
| --- | --- |
| H1 | 交易热路径零接入：团队不下单、不改配置、不写策略 |
| H2 | Worker 只读；写操作仅编排侧与 Verifier 持有 Mandate |
| H3 | Worker 不自证完成，完成由 A 层 verify + 45 判定 |
| H4 | 子代理不互相通信，只经领队聚合与 L0 黑板 |
| H5 | 禁止编造数据；缺失进 data_quality |
| H6 | 新路径开关默认关，关断字节等价 |
| H7 | 生产模型与门禁模型必须异构（不同 provider 或不同家族），同源配置拒绝启动 |
| H8 | 门禁模型只读、无工具权限；不可用即阻塞为 `needs_human`，禁止降级放行 |

**验收标准**

1. 同一问题在 `CDRIVE_SUPERVISOR=false/true` 下均可返回；关断时与现状字节等价。
2. 每条 KR 都有 evidence_refs，缺失即 FAIL。
3. 所有缺口出现在 data_quality，且被简报引用。
4. 单角色调用未授权能力被明确拒绝并留痕。
5. `trace_id` 贯穿 S→C→A→G。
6. 审计确认团队无任何交易写操作。

---

## 十、可观测性：调度工作流侧边面板

**结论：可行，且不需要引入图可视化依赖。** 现有 `PartRenderer` 已能渲染 reasoning/tool/plan-card/verification；`monitor-bus` 已有 trace_id、环形缓冲与 SSE；缺的只是"粒度"和"与推理的绑定"。

### 10.1 展示形态

```
┌ 对话区 ───────────────────────┬ 调度面板（320–380px）──────────┐
│ 推理过程（可折叠）             │ S1 意图 → S2 Spec              │
│ 工具调用卡片                   │   ↓                            │
│ 结论 / 研报                    │ C1 派工 ──┬─ macro    ✅ 1.2s   │
│                                │           ├─ technical ✅ 0.9s   │
│                                │           └─ flow     ⚠️ 缺失  │
│                                │ C3 裁决 → A1 验收 → G1 简报    │
│                                │ ─────────────────────────────  │
│                                │ 选中节点：technical            │
│                                │ 能力/证据/耗时/缺口            │
│                                │ [跳转到对应推理片段]           │
└────────────────────────────────┴────────────────────────────────┘
```

- **时间线**：S1→S2→C1→C2→C3→A1→G1 状态灯 + 耗时；
- **泳道/DAG**：按 S/C/A/G 四层或研究/结构/推演/风控四 Pod 排布；节点状态 `pending/running/done/degraded/failed`；
- **节点详情**：角色、能力 ID、输入摘要、证据引用、缺失项、耗时；
- **联动**：点节点 → 高亮/滚动到对应推理片段；点推理片段 → 反选节点。

### 10.2 TraceSpan 模型（新增）

```json
{
  "span_id": "sp_01",
  "trace_id": "tr_...",
  "parent_span_id": null,
  "stage": "C2",
  "role": "technical",
  "capability_id": "market.technical_indicator",
  "status": "done",
  "started_at": 0,
  "duration_ms": 900,
  "summary": "RSI14=19.7，DIF<0",
  "evidence_refs": ["l1:..."],
  "degraded": false,
  "seq": 12
}
```

- 生产者：对话路由、`runCapability`、`dsh-execution-engine`、C-drive Supervisor、A 层 Verifier、G 层报告；
- 存储：请求级内存环形缓冲（即时面板）+ `dreamos_spans`（持久化/复盘）；
- 复用 `monitor-bus`，只扩展 phase：`stage_start/stage_end/agent_dispatch/capability_call/gate_result`，不另建总线。

### 10.3 传输选型

| 方案 | 做法 | 取舍 |
| --- | --- | --- |
| **A（推荐）** | 复用现有 UIMessage 流，新增 `data-trace` 自定义 part | 单连接、与推理严格同序、无需额外基础设施；刷新后需回放持久化 span |
| B | 独立 SSE `/api/agent/trace?trace_id=` 订阅 monitor-bus | 适合全局运维大屏；与对话流存在时序对齐成本 |

首版用 A，后续做运维大屏时再加 B。

### 10.4 推理与环节对齐

不解析自然语言推理，而是**由编排层打点**：

1. 进入/离开每个阶段时写入 `stage_start/stage_end`；
2. 每次能力调用前后写入 `capability_call`；
3. 前端把相邻打点之间的 reasoning delta 归入同一 `stage`，形成"分段推理"；
4. 节点与推理片段用 `seq` 区间双向索引。

这样即使模型推理是英文、自由格式，也能稳定对应到环节。

### 10.5 分级落地

| 阶段 | 交付 | 判据 |
| --- | --- | --- |
| O0 | 打点 + 右侧列表视图（阶段/状态/耗时） | 一次分析能看到完整 S→G 步骤 |
| O1 | 泳道/DAG 视图 + 节点↔推理高亮 | 点节点能定位到推理片段 |
| O2 | 持久化回放 + monitor-bus 运维大屏 | 刷新后可复盘历史 trace |

### 10.6 风险与约束

| 风险 | 对策 |
| --- | --- |
| 推理为自由文本，无法直接映射阶段 | 只依赖编排打点，不做文本推断 |
| 事件过多导致面板噪声 | 只展示阶段/角色/能力三级，工具内部调用折叠 |
| 大 JSON 撑爆流 | span 只传摘要与引用，明细按需拉取 |
| 刷新后丢失 | O2 落 `dreamos_spans` 回放 |
| 泄露内部提示/数据 | 生产环境脱敏，按 entitlement 控制可见性 |

---

## 十一、对外任务看板（Task Board）

### 11.1 视图分层：内核图 vs 任务视图

**内核调度图不对外。** 第十章那张 S→C→A→G + 8+2+领队 + 能力主表的完整结构，只出现在本文档与诊断模式；默认产品界面不出现 SACG / DSH / Mandate / Worker 池等内部术语。

对外只回答四个问题：

1. 我在做什么（目标 + SPEC）
2. 做到哪一步（步骤条点亮）
3. 谁在做、用什么能力（子代理卡 + 能力标签）
4. 做完了吗、算不算合格（OKR 验收绿/黄/红 + G 层汇总）

### 11.2 两屏结构

**上屏 · 任务定义**

| 区块 | 内容 | 组件 |
| --- | --- | --- |
| 任务头 | 任务号 / 目标 / 整体状态 / 完成计数 | `TaskBoardHeader` |
| 意图门 | 用户原话 → 三判定（脑暴 / 逆向解析 / 外部采集）命中或跳过 → 判定结论 | `IntentGate` |
| 目标卡 | O 标题、负责人、模式（judge/supervise）、截止、置信门槛 | `OkrBoard` 头部 |
| SPEC 推理框 | 六字段：目标 / 范围 / 假设 / 交付 / 验收 / 依赖，流式填充，必现 | `SpecPanel` |
| OKR 卡 | O 进度条 + KR 行（编号 / 判据 / 负责人 / 证据数 / 状态徽标） | `OkrBoard` |

**下屏 · 执行与验收**

| 区块 | 内容 | 组件 |
| --- | --- | --- |
| 步骤条 | 意图 → SPEC → 派工 → 执行 → 验收 → 汇总，逐节点点亮 | `DispatchRail` |
| 子代理网格 | 角色 / 状态点 / 能力标签（MCP id）/ 一行结论 | `AgentGrid` |
| 验收回流 | 子代理 → KR：绿通过、黄待复核、红驳回，标注原因 | `AcceptanceFeed` |
| G 层汇总 | 全部通过后展开：结论 / 要点 / 置信度 / data_quality | `SummaryPanel` |

### 11.3 业务事件模型（独立于 TraceSpan）

`TraceSpan` 是内部打点，粒度过细且包含实现细节，不能直接驱动对外看板。新增一层业务事件，由编排侧投影：

| 事件 | 载荷 | 消费方 |
| --- | --- | --- |
| `intent.decided` | `raw_input`、`gates[]`、`decision` | IntentGate |
| `spec.updated` | `spec_id`、`version`、`status`、`fields[]` | SpecPanel |
| `okr.updated` | `objective`、`krs[]` | OkrBoard |
| `agent.updated` | `role`、`state`、`capability_ids[]`、`summary`、`evidence_count` | AgentGrid |
| `acceptance.recorded` | `role`、`node_id`、`verdict`、`reason`、`evidence_refs[]` | AcceptanceFeed + OkrBoard |
| `summary.ready` | `conclusion`、`key_points[]`、`confidence`、`data_quality[]` | SummaryPanel |

约束：

- **幂等**：以 `(task_id, type, entity_id)` 为键记录 `seq`，旧事件不覆盖新状态；
- **有序**：事件必须带 `seq` 与 `ts`，回放按 `seq` 升序；
- **如实**：缺失项进 `data_quality`，禁止用 0 或"中性"冒充；
- **可回放**：事件经 `applyTaskEvent` 归并成 `TaskBoardSnapshot`，刷新后可从存储重放。

### 11.4 状态映射

Ticket 四态（`ticket_state.py`）→ 卡片状态：

| Ticket | 卡片 |
| --- | --- |
| `live` | 执行中 |
| `paused` + `waiting_job` / `waiting_event` | 等待中 |
| `waitsForPerson` | 待人工 |
| `ended` | 终态（由验收结论决定绿/红） |

验收三策略（`okr_ticket_bridge.py`）→ 判定：

| verify | 通过条件 | 缺省结果 |
| --- | --- | --- |
| `evidence_backed` | 报告含匹配 `evidence_id` | 缺证据即 FAIL |
| `gap_closed` | 缺口项关闭标记存在 | 未关闭即 FAIL |
| `c_action` | 决策动作非 `REDO` / `EARLY_TERMINATE` | 命中即 FAIL |

### 11.5 前端落地

**新增**

```
src/types/task-board.ts                      事件与快照契约 + applyTaskEvent 归并
src/lib/task-board/project-events.ts         TraceSpan → 业务事件（降级投影）+ 快照构建
src/lib/task-board/use-task-board.ts         SSE 订阅 + 历史回放 + 增量归并
src/lib/task-board/server-store.ts           JSONL 事件 SSoT（append-only + 指纹去重 + seq 分配）
src/lib/task-board/gate-policy.ts            GatePolicy 默认策略 + 启动期校验（§11.8）
src/lib/task-board/gate-model.ts             门禁模型适配器（只读预审 + schema 校验 + needs_human 降级）
src/lib/task-board/gate-quorum.ts            异构会签（按家族去重计票）
src/lib/task-board/gate-precheck.ts          预审编排（Qwen 主 + JEV 副）
src/lib/task-board/gate-audit.ts             预审审计（append-only JSONL）
src/lib/task-board/gate-auto.ts              全权模式自动确认（仅低/中风险）
src/lib/task-board/gate-block.ts             对话侧 409 拦截载荷
src/lib/task-board/roles.ts                  门禁角色表（owner / team_lead / risk_reviewer / admin）
src/lib/model/model-registry.ts              三类模型注册表（judge / worker / gate）+ 异构校验
src/lib/model/gate-client.ts                 千问门禁客户端（OpenAI 兼容、只读、严格 JSON）
src/lib/model/jev-client.ts                  JEV 门禁客户端（noul / score，仅验收语义）
src/app/api/task/[id]/gate/precheck/route.ts 机器预审接口（只读，不改门禁状态）
src/app/api/gate/health/route.ts             门禁配置与模型连通性自检
src/app/api/gates/pending/route.ts           待办中心数据接口
src/app/dashboard/gates/page.tsx             门禁待办中心页面
src/instrumentation.ts                       启动钩子：生产环境校验失败即拒绝启动
src/components/features/task-board/          TaskBoardHeader / IntentGate / SpecPanel /
                                             OkrBoard / DispatchRail / AgentGrid /
                                             AcceptanceFeed / SummaryPanel / GateBar
src/app/dashboard/task/[id]/page.tsx         任务看板路由（对外唯一入口，dashboard 壳内）
src/app/dashboard/gates/page.tsx             门禁待办中心（我的待办）
src/app/api/task/[id]/route.ts               GET 快照 + 未确认门禁；POST 上报事件
src/app/api/task/[id]/gate/route.ts          POST 确认 / 驳回（409 = 仍有未确认门禁）
```

**修改**

- `components/features/agent/AgentChatPanel.tsx`：头部增加「看板 / 对话」切换；对话流中的 `data-task` part 实时推进看板。
- `components/features/agent/TracePanel.tsx`：收进诊断模式（`?debug=1` 或管理员），默认不出现。

**数据通道**

对话场景用 UIMessage 的 `data-task` 自定义 part（与推理同序）；独立访问时先从本地快照回放（`use-task-board.ts`），SSE（`GET /api/task/[traceId]/stream`）待编排侧把 span 落到可查询存储后接入。两者共用同一个 projector，保证同一 `trace_id` 得到同一快照。

### 11.6 落地阶段

| 阶段 | 交付 | 退出判据 |
| --- | --- | --- |
| **T0** | `types/task-board.ts` + `project-events.ts` + fixture 回放 | 六类事件覆盖图中全部状态；归并幂等；tsc 0 |
| **T1** | 上屏组件（意图门 / SPEC / OKR） | 用真实快照渲染，无 mock 数字 |
| **T2** | 下屏组件（步骤条 / 子代理 / 验收回流） | 事件到达即更新，驳回可回环 |
| **T3** | SSE + 回放 + 诊断开关 | 刷新可复原；默认隐藏内核 |
| **T4** | 工作门禁：`GatePolicy` + `GateBar` + 对话内联卡 + 待办中心 + 409 阻断 | 未确认门禁 100% 阻断下游；自批与超时放行被拒；驳回可回转 |

> 2026-11-18：T0–T2 与本地回放已落地（契约 / 投影 / 八个组件 / 看板页 / 对话侧投影与入口 / `?debug=1` 才显示轨迹）；SSE 端点等后端提供可查询 span 存储后再接。T4 契约与服务端存储已就绪，UI 与对话拦截待实现。

### 11.7 脱敏与可见性

- 能力 id 按角色投影后展示，只出现当前角色可用能力；
- 不展示提示词、阈值常量、内部评分函数、其他任务的数据；
- 诊断模式需角色校验，且只读；
- 摘要是投影结果，不允许前端根据原始 span 自行推断结论。

### 11.8 工作门禁：制度化的前端控制点

**定位**：门禁不是"接飞书审批"，而是把公司管理里被验证过的控制制度，**制度化到 Agent 的原生工作与推理流**。AI 负责干活，人只在五道门上做决策；门禁同时是前端交互、服务端裁决与审计记录三者合一。

先明确三条边界：

1. **门禁是状态机守卫**：未确认 → 下游不可执行，服务端返回 409 与 `pending_gates[]`；
2. **门禁不篡改进度**：`stage` 只反映事实做到哪，待确认由 `status = waiting` 表达；
3. **门禁与证据版本绑定**：证据变化（SPEC 升版、验收重跑）→ 旧确认自动失效回 `waiting`。

制度依据见 [RESEARCH-GATE-INSTITUTIONS-v0.1](RESEARCH-GATE-INSTITUTIONS-v0.1.md)，本节只写落地口径。

#### 11.8.1 制度 → 原生门禁映射

| 制度内核 | 原生落地 | 不可妥协点 |
| --- | --- | --- |
| 不相容职务分离（SoD） | 生产者 ≠ 批准者；子代理永不在审批池 | 服务端校验，不靠前端隐藏按钮 |
| 分级授权（DoA） | `GatePolicy` 按 `task_type / risk_level / change_class` 路由 | 策略可配，代码不写死角色判断 |
| 双人复核（Four-Eyes） | 高风险门 `quorum = all` 且 `min_distinct ≥ 2` | 同一人重复批准不计入 quorum |
| 阶段门（Stage-Gate） | 五道门，每道门先声明交付物与判据 | 判据来自 SPEC/OKR，不在门禁时临时生成 |
| 变更分级（ITIL） | `standard / normal / emergency` | 只有标准变更可预授权；紧急变更必须 PIR |
| 停线权（Andon） | Worker 可主动 `blocked`，进待办等人处理 | 上报不惩罚、不降权 |
| 审计追踪 | append-only 事件 + `evidence_ref` + `decided_by` | 前端不得直写快照 |
| 例外管理 | 例外带 `expires_at`，到期自动失效 | 例外不能绕过验收门 |
| 审批疲劳治理 | 待办限流、按风险排序、SLA 提醒限次 | 催办限流（类比飞书 24h 一次） |

#### 11.8.2 五道门

| 门 | 触发事实 | 必检证据 | 默认批准角色 | 默认驳回回转 |
| --- | --- | --- | --- | --- |
| `intent` 意图确认 | `intent.decided` 已到 | 用户原话 + 三项判定（脑暴/逆向解析/外部采集） | `owner` | 无（回到对话） |
| `spec` SPEC 确认 | `spec.updated` 已到 | 六字段齐全（目标/范围/假设/交付/验收/依赖） | `owner` | `intent` |
| `dispatch` 派工确认 | `okr.updated` 已到 | 每条 KR 有可判定判据与负责人 | `team_lead` | `spec` |
| `acceptance` 验收确认 | 验收记录已到 | 每 KR 有 `evidence_ref`；缺口进 `data_quality` | `risk_reviewer` | `dispatch` |
| `summary` 交付确认 | `summary.ready` 已到 | 结论 + 要点 + 置信度 + 缺口清单 | `owner` / `team_lead` | `acceptance` |

门禁决策的输出统一收敛为三态（避免契约膨胀）：

| 决策含义 | `status` | 附带字段 |
| --- | --- | --- |
| 通过 | `approved` | `evidence_ref`、`decided_by`、`decided_at` |
| 需补充（停在当前门） | `rejected` | `comment` 必填、`rewind_to = 当前门` |
| 驳回并回转 | `rejected` | `comment` 必填、`rewind_to = 指定门` |

#### 11.8.3 GatePolicy（可配，不写死）

核心字段：`mode`（全权 / 人工干预）、`auto_approve`、`human_required`、`applies_to`（任务类型 / 风险级别 / 变更分级）、`approver`（角色、会签方式、最小独立人数、是否允许自批/转交/加签）、`gate_model`（门禁模型类、是否异构会签、最小异构模型数）、`sod`（禁止同一主体、禁止同组、禁止 Agent 入池）、`evidence`（必需证据与最小数量、是否展示 diff）、`sla`（时限、超时只提醒或升级）、`escalation`（升级对象与兜底阻塞）、`rejection`（原因必填、回转目标）、`bypass`（默认禁止）、`preauthorized`（仅标准变更可开，带 TTL 与次数上限）、`audit`（不可变、保留期）、`notify`（各阶段通知对象）。

**四条写进代码、不给配置留口子的硬约束**：

1. Agent / 子代理 / c_drive **永不**出现在审批池；
2. 超时不允许自动通过，只允许提醒或升级，兜底永远阻塞；
3. `evidence_ref` 变化 → 已批准的同门必须回到 `waiting`；
4. 门禁状态只能由 `gate.updated` 事件写入，前端不得直改快照。

#### 11.8.4 模型级分工：三类模型 + 异构多模型

制度里的「不相容职务分离」和「会签」，在 AI 层要落到**模型**上：同一个模型既生产又自审，会放大自我偏好偏差（LLM-as-a-judge 的 self-preference bias）；异构模型交叉审查能显著压低这类偏差。因此不是「一个任务一个模型」，而是**三类基础模型 + 两处异构多模型**。

**基础三类（按能力分工，配置在模型注册表，见 §十二）**

| 模型类 | 承担阶段 | 能力画像 | 硬约束 |
| --- | --- | --- | --- |
| `judge` | S 意图识别 / A 验收判定 | 小而快、结构化输出稳定、低温度 | 只出判定与理由，不写事实、不调生产工具 |
| `worker` | C 派工/聚合/辩论、G 简报研报、8 个子代理 | 强推理、长上下文、工具调用 | 可写产物，但必须附 `evidence_ref` |
| `gate` | 五道门的机器预审 | 独立供应商/家族、只读、无工具、`temperature=0` | **必须与 worker / judge 异构** |

**两处异构多模型（不是同类模型开多个实例）**

| 场景 | 多模型形态 | 理由 |
| --- | --- | --- |
| 多人审批（会签 / 或签 / 依次） | 会签 = 多个**不同家族**的 gate 模型各自独立出结论，全通过才通过；或签 = 任一通过；依次 = 按风险递增逐个审 | 同模型多实例只是重复采样，不产生独立性；异构才有交叉校验价值 |
| 脑暴 / 辩论（brainstorm、scenario 红队、bull/bear） | 至少两个不同家族的 worker 模型分别出方案，再由 judge 模型或人裁决 | 独立模型互相审视，能暴露单一模型会自信坚持的错误 |

会签的独立性判定：

- 按 `provider + model` 去重，同一模型重复出现只计 1 票；
- 高风险门要求 `min_distinct_models ≥ 2`，且 `deny_same_family = true`；
- **模型票与人工票分开计数**：模型票只能作为预审意见，不能单独放行 high / critical 门。

**门禁模型输出契约**（不合 schema 一律视为 `needs_human`）：

```json
{ "verdict": "pass|fail|needs_human", "reasons": ["..."],
  "evidence_refs": ["..."], "missing": ["..."], "confidence": 0.0 }
```

**四条模型级硬约束**

1. `gate` 模型必须与所有 `worker` / `judge` 模型不同 provider 或不同家族，启动期校验，不满足拒绝启动；主副两个 gate 模型之间也必须异构；
2. `gate` 模型只读证据，`allowed_capabilities = []`，不可调用任何写能力；
3. 会签去重按 `provider + model`，同模型多实例不增加票数；
4. gate 模型不可用 / 超时 / 输出不合规 → 一律 `needs_human`，禁止默认放行。

#### 11.8.5 变更分级与预授权

| 分级 | 判定 | 审批要求 |
| --- | --- | --- |
| `standard` 标准 | 同类任务已跑通、风险低、有回归证据 | 可预授权：TTL + 次数上限 + 全量留痕 |
| `normal` 常规 | 默认档 | 按 `GatePolicy` 正常走门 |
| `emergency` 紧急 | 线上故障、止损、安全事件 | 单人/双人快速批，但强制生成 `pir_required`；未复盘不得再次走紧急通道 |

#### 11.8.6 防黑箱 / 防漂移规则

| # | 规则 | 拦截点 |
| --- | --- | --- |
| 1 | 生产者在审批池中 → 拒绝 | 服务端 `sod` 校验 |
| 2 | 证据为空即 FAIL，禁止"看情况通过" | `evidence.required` |
| 3 | 证据版本变化 → 旧确认失效 | `reconcileGates` |
| 4 | 超时只提醒/升级，绝不自动放行 | `sla.on_timeout` |
| 5 | 驳回必须填原因并指定回转门 | `rejection` |
| 6 | 例外必须有理由、期限、审计 | `exception` 记录 |
| 7 | 管理员旁路必须留痕且限次 | `bypass` |
| 8 | 门禁不得回退已发生的进度 | `deriveStage` 只看事实 |
| 9 | 审批卡必须显示证据摘要与版本 | 前端 `GateBar` |
| 10 | 重复批准不计入 quorum | `approver.min_distinct` |

> **多节点流程定义见总纲 [§6.9 GateFlow](../../../1-ARCHITECTURE/specs/SPEC-SYSTEM-ARCH-CAPABILITY-v1.0.md) / 调研 [§2.6](../RESEARCH-GATE-INSTITUTIONS-v0.1.md)**：本节只定义单门的 `GatePolicy`；当需要条件分支、并签、加签、转交、抄送、限时升级时，由 `GateFlow` 组合多个门并过编译期校验（必须终于 acceptance、超时不得自动通过）。

#### 11.8.7 三处入口，一份状态

| 入口 | 场景 | 行为 |
| --- | --- | --- |
| 对话内联卡 | Agent 推理流走到门时 | 推理流暂停，插入确认卡；未决策不继续调用下游能力 |
| 看板 `GateBar` | 打开任务看板 | 顶部固定展示当前门：证据摘要 / 通过 / 驳回（填原因 + 选回转门） |
| 待办中心 `/dashboard/gates` | 集中处理跨任务待确认 | 按风险与 SLA 排序，支持批量查看（批量批准仅限 `standard`） |

三处入口共用 `GET /api/task/[id]` 的快照与 `POST /api/task/[id]/gate`，不存在第二份状态。

#### 11.8.8 API 与幂等

```
GET  /api/task/[id]            → { snapshot, pending_gates[], mode }
POST /api/task/[id]            → 上报业务事件（编排侧）
POST /api/task/[id]/gate       → { gate_id, status, comment?, rewind_to?, evidence_ref? }
                                  200 = 最新快照 + pending_gates
                                  409 = stale_evidence（证据版本已变）
                                  403 = role_not_allowed
POST /api/task/[id]/gate/precheck → { gate_id }
                                  200 = 各模型票 + 会签建议（只读，不改状态）
POST /api/agent/chat           → { messages, task_id?, ... }
                                  409 = GATE_PENDING + pending_gates[] + mode
GET  /api/gates/pending        → { success, mode, count, tasks[] }
```

- 携带 `evidence_ref` 时必须与快照一致，否则 409（防止带着过期视图批准）；
- 同一 `(kind, evidence_ref, status)` 重复提交幂等返回，不产生重复事件；
- `decided_by` 取服务端会话身份（`x-user-email` / `x-user-id`），缺省 `workspace-user`，**不取请求体**；
- 角色在服务端校验；未配置角色表时进入 bootstrap（本地单用户可用，审批记录标记来源）；
- 对话侧携带 `task_id`（body 或 `x-task-id`）时，先查快照：存在 waiting / rejected 门禁即返回 409，**不进入 L1 / L2 任何模型调用**；无 `task_id` 的旧客户端行为不变。

#### 11.8.9 最小角色表

`owner`（任务发起/业务负责人）、`team_lead`（派工与交付）、`risk_reviewer`（验收复核）、`admin`（策略维护与旁路，需留痕）。角色来源先落本地配置，后续再接组织架构。

**Agent 也是治理主体**：Agent 以数字员工身份持席位（`agent:<id>`），可承担 `team_lead` / `risk_reviewer` 席位并投绑定票；三条硬约束：不得批准自己 / 同一 run 的产出、同 `provider + family` 只计 1 票、只读证据无写能力。高风险验收保留 1 个人类责任人席位，其余可由异构 Agent 担任（总纲 §6.9.8）。

#### 11.8.10 T4 落地顺序

| 步骤 | 交付 | 退出判据 |
| --- | --- | --- |
| T4-1 | `model-registry.ts` + `gate-policy.ts` + 启动校验 + 单测 | 三类模型缺失 / gate 同源 / gate 有写权限 → 启动即失败 |
| T4-2 | `gate-model.ts`：只读预审适配器（schema 校验 + 降级） | 未配置或输出不合规 → `needs_human`，绝不默认放行 |
| T4-3 | `GateBar` + `use-task-board.decideGate` | 通过/驳回（必填原因）能写回并刷新快照 |
| T4-4 | 对话侧拦截：门未确认返回 409 并插入内联卡 | 未确认时下游能力零调用 |
| T4-5 | `/dashboard/gates` 待办中心 + SLA 提醒 | 跨任务待办可见、按风险排序 |

> 2026-11-18：T4-1 ~ T4-5 全部落地。

#### 11.8.11 P0 治理最小闭环（Agent 协作版）

| 交付 | 文件 / 入口 | 规则 |
| --- | --- | --- |
| Agent 席位 | `lib/task-board/gate-governance.ts` | `defaultGateSeats` 合并人类角色与 Agent 席位；`canSeatApprove` 执行 SoD 与家族异构 |
| 空审批人兜底 | `resolveApprovalPlan` | 无有效席位 → 升级到 `escalation.to_roles` 并阻塞，绝不自动通过 |
| 混合计票 | `tallySeatVotes` | 一人一票；同 family 的 Agent 只计 1 票；阻塞计划永不 approved |
| 超时巡检 | `POST /api/gates/sweep` | 只写 `gate.reminded` / `gate.escalated`，每门最多提醒 1 次，永不自动放行 |
| 退回生效 | `POST /api/task/[id]/gate` + `computeRewind` | 目标门到链尾全部失效，下游旧批准作废 |
| 终止任务 | `POST /api/task/[id]/terminate` | 仅 admin，必须写原因；终止后门禁不再推进、待办不再展示 |
| 批量确认 | `GateBar`「批量确认 N 道」 | 低/中风险门一次落票；验收门必须单独确认 |
| GateFlow DSL | `lib/task-board/gate-flow.ts` | 节点：gate/condition/parallel/cc/timer/terminate；12 条编译期校验 |
| GateRun 运行时 | `gate-flow.ts` | 事实条件分支、并/或签、抄送不计票、超时只推进不批准、加签清票、退回祖先、终止 |

> 验证：`tsc --noEmit` 通过；门禁 + 模型相关 11 个套件、87 项测试全绿。

---

## 十二、模型分层与路由（Model Tiers）

**结论：至少三类模型，按能力分工；两处必须异构多模型（会签、脑暴/辩论）。** 模型不是按"贵不贵"分，而是按**职责边界**分：生产、判定、门禁三者不能共用一个模型。

### 12.1 三类模型

| 模型类 | 建议配置 | 用途 | 禁止事项 | 故障降级 |
| --- | --- | --- | --- | --- |
| `judge` 判定类 | 小参数、低温度、强 JSON schema | S1 意图识别、A 层 OKR 判定、data_quality 归纳 | 不生成长文、不调用写工具 | 规则引擎兜底；仍不可用 → 人工 |
| `worker` 生产类 | 强推理、长上下文、支持工具调用 | 8 个子代理、C 派工/聚合/辩论、G 简报与研报 | 不批准门禁、不修改自己的验收结论 | 标记 `partial`，缺口进 `data_quality` |
| `gate` 门禁类 | 两个异构模型（Qwen + TypeSafe JEV）、只读、`temperature=0`、固定 prompt 版本 | 五道门机器预审、异构会签 | 任何写操作、任何工具调用、读取未脱敏内部提示 | `needs_human`（阻塞，不放行） |

### 12.2 路由矩阵

| 阶段 | 默认模型类 | 可否替换 | 备注 |
| --- | --- | --- | --- |
| S1 意图识别 | `judge` | 可 | 零 token 规则优先 |
| S2 SPEC 生成 | `worker` | 可 | 输出结构化字段 |
| S3 按需取证 | `worker` | 可 | 只读能力 |
| C1 派工 | `worker`（领队） | 可 | 不调用 gate |
| C2 子代理 | `worker`（可按角色分家族） | 可 | 角色与模型解耦，换模型不改角色契约 |
| C3 聚合 / 辩论 | `worker` × N（≥2 家族） | **否** | 辩论必须异构，否则只是自我复述 |
| A1 验收 | `judge` 预判 → `gate` 复核 → 人确认 | 否 | 三层，模型票不单独放行高风险门 |
| G1 / G2 输出 | `worker` | 可 | 数字必须来自证据 |

### 12.3 模型注册表

`src/lib/model/model-registry.ts`：每个模型声明 `class / provider / family / model / context_window / max_temperature / allowed_capabilities / prompt_version`。

**环境变量（只写 `.env.local`，不入库）**

| 变量 | 作用 |
| --- | --- |
| `MODEL_WORKER_PROVIDER` / `MODEL_WORKER` | 生产模型 |
| `MODEL_JUDGE_PROVIDER` / `MODEL_JUDGE` | 判定模型 |
| `MODEL_GATE_PROVIDER` / `MODEL_GATE` | 门禁模型 |
| `MODEL_GATE_BASE_URL` / `MODEL_GATE_API_KEY` | 门禁主模型凭据（只读，不写日志） |
| `MODEL_GATE_TIMEOUT_MS` / `MODEL_GATE_MAX_TOKENS` / `MODEL_GATE_DISABLE_THINKING` | 门禁主模型调用参数 |
| `MODEL_GATE_SECONDARY_PROVIDER` / `MODEL_GATE_SECONDARY` | 第二门禁模型（JEV） |
| `TYPESAFE_API_KEY` / `TYPESAFE_BASE_URL` / `TYPESAFE_TIMEOUT_S` | JEV 凭据与超时（复用 DSH 配置） |
| `GATE_MODE` | 运行模式：`human`（默认）/ `autonomy`（全权） |

**当前部署（2026-11-18）**

| 类 | 模型 | 家族 |
| --- | --- | --- |
| worker | `deepseek-v4-pro` | deepseek |
| judge | `deepseek-v4.1-flash` | deepseek |
| gate（主） | `qwen4-max`（关闭思考） | alibaba |
| gate（副） | `jev-latest` | typesafe |

两个门禁模型互为异构，且都不同于 worker / judge，启动校验通过。自检入口：`GET /api/gate/health`（静态校验）、`GET /api/gate/health?probe=1`（两个门禁模型各真实调用一次）。

启动期校验（fail-closed）：

1. `judge / worker / gate` 三类必须齐全；
2. `gate` 与所有 `worker`、`judge` 必须不同 provider 或不同 family；
3. `gate.allowed_capabilities` 必须为空数组；
4. 任一校验失败 → 生产环境拒绝启动；开发环境用 mock，但门禁仍走人工确认。

### 12.4 判定梯度

| 风险 | `judge` | `gate`（异构） | 人 |
| --- | --- | --- | --- |
| low / standard | 判定 | 可绑定结论（预授权 + 留痕） | 抽检 |
| medium | 判定 | 出建议 | 必确认 |
| high | 判定 | 会签 ≥2 家族 | 必确认，`min_distinct ≥ 2` |
| critical | 判定 | 会签 + 分歧显性化 | 双人 + 负责人 |

### 12.5 审计字段

每次模型调用必须记录：`class / provider / family / model / prompt_version / temperature / seed / evidence_ref / verdict / abstain / latency_ms / tokens`。缺任一字段的调用视为无效，不得进入验收。

### 12.6 失败与降级

- `gate` 不可用 → `needs_human`（阻塞）；
- `worker` 不可用 → `partial` + `data_quality`；
- `judge` 不可用 → 规则兜底；规则也没有 → 人工；
- 任何降级都必须写事件，不静默、不默认通过。

### 12.7 验收标准

1. 启动期能拒绝"三类不全 / gate 同源 / gate 有写权限"的配置；
2. 任一任务可查到每次判定用了哪个模型、哪个版本；
3. 会签中同模型多实例只计 1 票；
4. 关掉 gate 模型后，所有高风险门仍然阻塞；
5. 脑暴与辩论的参与者可验证为不同家族。

### 12.8 JEV 接入：验收预审 + 异构第二票（已落地）

**定位**

- 适合：`intent`、`acceptance`、`summary` 的**机器预审 + 异构第二票**；
- 不适合：作为 high / critical 门的唯一批准者；也不适合判断"方向对不对"（触碰 HC-9 与交易决策边界）。

**适配度**

| 维度 | 评价 | 说明 |
| --- | --- | --- |
| 结构化输出 | 强 | noul / score 带置信度，天然映射 `pass / fail / needs_human` |
| 模型级 SoD | 强 | 供应商 typesafe，与 deepseek / qwen 异构 |
| 证据审查 | 中强 | 输入为 state + 带 criteria 的问题，适合完成度/质量判据，不适合开放式事实核查 |
| 契约稳定性 | 强 | 只读、无工具、无自由生成 |
| 可用性 | 中 | 第三方 API，实测约 8s，必须做 fail-closed 包装 |
| 判定质量 | 未验证 | 仓库内 A/B 报告的 JEV 数字为 mock（latency 0.0ms），不能当作准确率证据 |

**已落地实现**

| 层 | 文件 | 作用 |
| --- | --- | --- |
| 客户端 | `src/lib/model/jev-client.ts` | `noul ≥ 0.85 且 score ≥ 50%` → pass；`noul < 0.50` → fail；中间区间 / degraded → needs_human |
| 注册表 | `src/lib/model/model-registry.ts` | `gate_secondary` 槽位，校验与主门禁、worker、judge 三方异构 |
| 会签 | `src/lib/task-board/gate-quorum.ts` | 按 `provider + family` 去重；`all` 任一反对即 fail；`any` 任一通过即 pass |
| 编排 | `src/lib/task-board/gate-precheck.ts` | Qwen + JEV 并行预审；acceptance 按 high 风险要求 2 个异构家族 |
| 接口 | `POST /api/task/[id]/gate/precheck` | 只读预审，不改变门禁状态 |
| 审计 | `src/lib/task-board/gate-audit.ts` | 记录 `model / family / verdict / confidence / latency_ms`，append-only |
| 界面 | `GateBar` 的「机器预审」 | 展示各模型票与合计建议，明确标注"模型票仅为预审意见" |

**边界与降级**

- JEV 超时 / 5xx / 输出异常 → `needs_human`，覆盖 DSH 侧 HC-7 的 FAIL-OPEN；
- 只发送结构化摘要（判据、证据引用、结论），不发送原始行情与持仓；
- 两个门禁模型同源 → 启动校验拒绝；只剩一个可用 → 高风险门退化为"单模型预审 + 人工确认"。

**实测（2026-11-18）**：`probeJevModel` 返回 `configured=true, ok=true, model=jev-latest, latency≈8.3s`；对 `ping` 证据给出 `fail`/`confidence=0.36`，符合"证据不足不放行"的预期。

**验收标准**：JEV 票与 Qwen 票、人工票分开计数；关闭 JEV 不影响高风险门阻塞；每次调用都有审计记录。

### 12.9 运行模式：全权 vs 人工干预

**结论：只保留两种模式，不再增加第三种。** 模式只决定"低/中风险门是否自动确认"，不改变模型分工，也不改变验收门的性质。

| 模式 | 行为 | 适用 |
| --- | --- | --- |
| `human`（默认） | 五道门全部人工确认 | 生产、陌生任务、高风险期 |
| `autonomy` | 低/中风险门自动确认并留痕；**high / critical 门仍人工** | 本地、重复性任务、已验证流程 |

**风险映射（固定，不可配置）**

| 门 | 风险 | 全权模式 |
| --- | --- | --- |
| intent | low | 自动确认 |
| spec | medium | 自动确认 |
| dispatch | medium | 自动确认 |
| acceptance | high | **必须人工** |
| summary | low | 自动确认 |

**硬规则**

1. `acceptance` 任何时候都不自动确认；这是"非常高危命令必须人工审批"的落点；
2. 自动确认写入 `gate.updated` 事件，`decided_by = mode:autonomy`，`comment` 记录风险级别；
3. 证据变化后门禁回到 `waiting`，再按当前模式重新处理，不会带着过期授权继续；
4. 模式由 `GATE_MODE` 控制（默认 `human`），`GET /api/task/[id]` 与健康检查都会返回；
5. 切到 `autonomy` 对已存在的任务在下一个事件后生效（避免"读时写"）。

**落地文件**：`src/lib/task-board/gate-auto.ts`（自动确认）、`gate-policy.ts`（模式与风险映射）、`server-store.ts`（事件写入后立即物化）、`GateBar`（模式徽标）。

**已落地（T4-4 / T4-5）**

- 对话侧：`/api/agent/chat` 携带 `task_id` 时，waiting / rejected 门禁直接返回 409，L1 / L2 均不执行；
- 待办中心：`/dashboard/gates` 汇总所有仍有未确认门禁的任务，按风险排序，可跳转任务看板；
- 接口：`GET /api/gates/pending`；
- 侧栏新增「门禁待办」入口。


