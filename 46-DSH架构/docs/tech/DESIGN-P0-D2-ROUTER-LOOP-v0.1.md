# DESIGN: P0-D2 常驻 Router 循环 v0.1

> **版本**: v0.1 ｜ **日期**: 2026-11-12 ｜ **状态**: ✅ D2a/D2b/D2c 已实施（D2d shadow 观察期待启动，默认仍全关）
> **定位**: 把 P0 骨架里的「单轮无状态分派工具」升级为「按 pass 常驻推进的 Router 循环」，补齐 [DESIGN-DSH-ARCH-UPGRADE v0.2](DESIGN-DSH-ARCH-UPGRADE-v0.2.md) §五 P0·骨架的「常驻」半边。
> **上游约束**: DESIGN-DSH-ARCH-UPGRADE v0.2（ADR-1/2/3/4/7/8、H1/H2/H3/H6、DD1/DD3）｜ [SPEC-EVENT-DRIVEN-L1-GATEWAY](SPEC-EVENT-DRIVEN-L1-GATEWAY.md)（事件入口）｜ [SACG_A SUPERVAGENT CONNECTION SPEC v0.2](../../../1-ARCHITECTURE/specs/SACG_A_SUPERAGENT_CONNECTION_SPEC.md)（契约层）
> **下游影响**: `34-前端应用训练系统/core/`（新增 `router_loop.py`）、`dream-harness-bridge/packages/python-server/`（新增 1 个 IPC 方法）、`cordis-plugin-superagent-p0`（新增 timer 宿主）、`53-DSH插件模块/SPEC-53` §9.3 状态

---

## §0 一页纸摘要

| 项 | 结论 |
|---|---|
| 现状 | `ticket_router.route_single_round()` 是**纯函数**，只在 Worker 显式调 `ticket_router_dispatch` 工具时被调用一次；没有任何"自己醒来推进"的机制 |
| 目标 | 以固定节拍执行 `pass`：读 L0 快照 → 依赖/槽位判闸 → 分派 → 落 L0 / 投递 worker inbox，异常一律降级 |
| 形态决策 | **不新增进程**（复用 D3-b 共享 IPC）；循环宿主放在 Cordis 插件侧的 `setInterval`，Python 侧仍是无状态函数 |
| 状态 | 全部来自 L0（`ticket_store` 每次 `recover_tickets`），进程内不持权威状态（ADR-2） |
| 上线方式 | `enable_router_loop` 默认 **false**；首版默认 **shadow=true**（只算不写），观察后再转正 |
| 核心不变量 | 同一 L0 快照 + 同一花名册 ⇒ 分派结果可复现（ADR-1）；已绑定 Worker 的 live Ticket 不重复派 |

---

## §1 现状与差距

### 1.1 AS-IS（已核实的代码事实）

| 能力 | 现有实现 | 缺口 |
|---|---|---|
| 单轮分派 | [`ticket_router.route_single_round()`](../../../34-前端应用训练系统/core/ticket_router.py#L37-L116)：纯函数，输入 plan + workers，输出 `assignments / unassigned / deferred` | 只被动调用，无节拍 |
| 槽位并发 | [`worker_pool.dispatch_concurrent()`](../../../34-前端应用训练系统/core/worker_pool.py#L77-L103)：仅 live 且绑 worker 的占槽，空闲花名册再分派 | 需要调用方每轮喂 `active_tickets` |
| 状态机 | [`ticket_state.transition_ticket()`](../../../34-前端应用训练系统/core/ticket_state.py#L55-L96)：四态 + paused 子因 | 需要调用方驱动迁移 |
| L0 持久化 | [`ticket_store.recover_tickets()/save_ticket()`](../../../34-前端应用训练系统/core/ticket_store.py#L82-L108)：append-only latest-wins | 无自动读写节拍 |
| Thread 直通 | [`thread_affinity.AffinityTable`](../../../34-前端应用训练系统/core/thread_affinity.py#L47-L143)：TTL 1800s、LRU 4096 | 需在 pass 中绑定/解除 |
| 事件唤醒 | [`ticket_resume.resume_on_event()`](../../../34-前端应用训练系统/core/ticket_resume.py#L76-L110) | 需在 pass 前被调用 |
| 触发入口 | `event_gateway.route_trigger` 已三分流 | 分流结果没有"驱动一次 pass"的落点 |
| 工具面 | `ticket_router_dispatch`（同步单次） | 无"循环状态/统计"可观测面 |

**结论**：P0/P1/P3 的零件都在，缺的是**节拍器 + 编排顺序 + 幂等闸 + 可观测面**。D2 不重写任何算法。

### 1.2 为什么不能直接在 Python 里加 `while True`

1. `server.py` 的主循环是 **stdin NDJSON 请求-响应**契约；在其中插常驻线程会让"进程存活 = 服务可用"的语义变模糊（子进程被杀、请求超时都由它兜底）。
2. 开关粒度：`cordis.patch.yml` 的 `enabled` / `config` 是**插件级**的；Python 侧开关只能靠环境变量，profile 隔离能力弱。
3. 生命周期：Cordis 的 `ctx.effect()` 提供确定的 cleanup；Python 侧没有等价的"卸载"信号。
4. D3-b 已把 11 个插件收敛到 1 个 `server.py`，再来一个后台线程会与共享 IPC 的退出钩子抢生命周期。

→ 决议：**循环在 JS 插件，计算在 Python 纯函数**（见 §4.6）。

---

## §2 目标与非目标

### 2.1 目标（本设计覆盖）

1. 每 `interval` 执行一次 `pass`，完成「快照 → 唤醒 → 物化 → 分派 → 提交 → 观测」。
2. 单飞（single-flight）：上一轮未完成时跳过本轮并计数，不排队。
3. 幂等：同一 `external_ref` 已存在 live Ticket 时不重复分派。
4. shadow 优先：只算不写，输出 `would_*` 字段供比对。
5. FAIL-OPEN：任何异常 → 本轮降级返回，不击穿 runtime（H1）。
6. 可观测：每轮一份 pass 摘要 + 环形缓冲统计，可经 IPC 读取。
7. 与现有同步工具**共用同一 core 函数**，不出现两套分派逻辑。

### 2.2 非目标（明确不做）

| 不做 | 归属 |
|---|---|
| Worker 会话的拉起/续跑执行 | 既有 DSH session 机制；D2 只投递 assignment 到 inbox |
| 死链 Ticket 的状态修复 / 心跳超时改状态 | Watchdog（P2） |
| 45 业务门禁裁决 | P2 |
| 独立调度进程 / systemd timer | DD1 后置（先挂 timer） |
| Thread 直通首次绑定（事件侧的亲和建立） | 既有 P3 续跑链，D2 只消费 |
| 交易热路径任何接入 | H5 红线 |

---

## §3 总体设计

### 3.1 组件视图

```
┌─ Node 运行时（DSH profile: headless / superagent）──────────────────────┐
│                                                                        │
│  cordis-plugin-superagent-p0 (D2c 扩展)                                 │
│   ├─ ctx.effect(() => setInterval(tick, intervalMs))   ← 节拍器         │
│   ├─ tick: 单飞闸 → ipc.callMethod("router_pass", {...}) → 记录摘要     │
│   └─ tool: ticket_router_dispatch（既有，手动单次 pass，共用 core）      │
│                          │                                              │
│                          ▼ 共享 IPC（D3-b，不新增进程）                  │
└──────────────────────────┼──────────────────────────────────────────────┘
                           ▼
┌─ Python server.py（单进程，DSH_ENABLE_UPGRADE 组）─────────────────────┐
│  superagent_p0.handle("router_pass", params)                           │
│      └─ router_loop.run_pass(...)   ← D2a 新增，纯函数                │
│            ├─ ticket_store.recover_tickets(L0)      读快照             │
│            ├─ ticket_resume.resume_on_event(...)    事件唤醒            │
│            ├─ ticket_state.transition_ticket(...)   状态迁移            │
│            ├─ worker_pool.dispatch_concurrent(...)  槽位分派            │
│            ├─ ticket_store.save_ticket(L0)          写回（非 shadow）   │
│            └─ inbox_sink(assignment)                投递 worker inbox   │
└────────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
   L0（逻辑归属通用 L0 能力；`34-前端应用训练系统/` 仅为本地 JSONL 路径约定）
     dsh_tickets.jsonl          权威状态（SSoT，ADR-2）
     dsh_worker_inbox.jsonl     派单投递通道（Router → Worker）
     dsh_worker_receipts.jsonl  结果回执通道（Worker → Router）
```

### 3.2 pass 生命周期（一次 tick 的 8 步）

| # | 步骤 | 输入 | 输出 | 失败行为 |
|---|---|---|---|---|
| 1 | **闸门** | flags | 是否继续 | 开关关 → `{degraded, reason:"loop_disabled"}` |
| 2 | **快照** | `store` | `tickets[]`（latest-wins） | store 不可用 → `degraded:"store_unavailable"` |
| 2b | **回执消费**（R14/R16） | `dsh_worker_receipts.jsonl` | `receipts.applied / ignored` | 映射（W0 冻结）：`done→ended`；`failed+retryable→paused(waiting_job)`；`failed+manual→waitsForPerson`；缺省/未知 `failure_class` 按 `manual`。坏行/未知状态计入 `ignored`；整体异常 → FAIL-OPEN（按旧状态继续）；`shadow` 不消费；同内容回执按 `last_receipt_key` 去重，重放不二次迁移 |
| 3 | **对账（只读）** | `tickets[]` | `drift[]`（live 但无 worker / 超时未心跳） | 只报告，**不改状态**（避免与 Watchdog 重叠） |
| 4 | **唤醒** | 本轮 `triggers[]`（可选）、`affinity` | `resumed[]` | 单条坏事件跳过 |
| 5 | **物化** | `plan`（可选） | `materialized[]` | 双门未过 / shadow → 不建 Ticket |
| 6 | **分派** | plan + 空闲花名册 + 已完成 refs | `assignments / unassigned / deferred / skipped` | 非法 plan → `None` → 本轮跳过 |
| 7 | **提交** | assignments | L0 写入 + inbox 投递 + 亲和绑定 | 单条失败不回滚其他条（可重放） |
| 8 | **观测** | 以上全部 | pass 摘要 + 环形缓冲 | 记录失败不抛 |

**步 3/5/6 共用同一份快照**：保证单轮内视图一致（避免"分派时读到的一半是新状态"）。**步 2b 先于快照定型**：回执迁移完成后再算 `pre_ref_tickets` 与 `snapshot`，使本轮分派看到最新状态（`done→ended` 即刻释放槽并解除依赖）。

### 3.3 关键判闸

| 判闸 | 规则 | 依据 |
|---|---|---|
| **幂等闸** | `plan.tickets[].external_ref` 若已存在 Ticket → 移入 `skipped`，不再物化/分派；原因区分 `already_live` / `already_open`(paused|waitsForPerson) / `already_ended`。**例外（R13）**：`state=live` 但 `worker_id` 为空（上轮物化后被槽位闸挡住、未获派分）不跳过，本轮正常参与分派与提交，避免该 ref 被永久锁死 | ADR-2 单源；防重复 Ticket 与重派已完成项 |
| **依赖闸** | `depends_on[ref]` 中指向本批的依赖未出现在 `completed_refs` → `deferred`。**跨轮补强（R15）**：依赖票已物化但未 `ended` 时虽被幂等闸移出本批，仍按 L0 快照判 `dependency_unmet`，不得当作外部锚点放行 | 复用 `route_single_round` + 编排侧 L0 快照 |
| **槽位闸** | 只从"空闲花名册"（全量 − live 占槽）里挑 Worker | 复用 `worker_pool.free_roster` |
| **能力闸** | Router 只看 `route_hint.role`，不感知工具集 | ADR-4 |
| **双门闸** | 物化 Ticket 需 Policy 门 + S 层元认知门都通过（MVP 用注入的 `gate(plan) -> bool`） | `okr_ticket_bridge` docstring「双门后才创建 Ticket」 |
| **shadow 闸** | `shadow=true` → 步 7 全部不执行，只输出 `would_assignments` | 对齐 event_gateway 的 shadow 语义 |

### 3.4 单飞与背压

```
tick 触发
  ├─ inFlight === true  → skipped_overlap += 1，直接返回（不排队、不补跑）
  └─ inFlight = true
       ├─ ipc.callMethod("router_pass")（超时 15s，沿用 shared-ipc）
       └─ finally: inFlight = false

连续失败 ≥ maxConsecutiveFailures（默认 3）
  → 熔断：跳过接下来 3 × interval，期间只累计 failure 计数
  → 一次成功后计数清零
```

- **不排队**：Router 的下一轮会用最新快照重算，排队只会放大陈旧决策（ADR-1）。
- **限频日志**：同类失败日志每 60s 最多一条，避免 tick 级日志风暴。

### 3.5 状态归属

| 状态 | 归属 | 说明 |
|---|---|---|
| Ticket 四态 / history | **L0** `dsh_tickets.jsonl` | 唯一权威（ADR-2） |
| Worker 花名册 | 插件 config（MVP）→ 47 `worker_roles`（后续） | Router 只读 |
| Thread 亲和 | 进程内 `AffinityTable`（可丢） | 丢失只退化成分派，不产生分歧 |
| pass 摘要 / 计数 | 进程内环形缓冲（可丢） | 诊断用，不做权威 |
| `inFlight` | 插件闭包变量 | 生命周期与插件一致 |

> **红线**：循环内**禁止**在内存里维护"当前有哪些 Ticket"的权威副本；每轮必须 `recover_tickets`。

---

## §4 契约定义

### 4.1 `run_pass(params) -> dict`（Python，纯函数）

```python
# 34-前端应用训练系统/core/router_loop.py
def run_pass(
    store,                       # ticket_store 后端（必须实现 read_all/append）
    roster=None,                 # {role: [worker_id,...]}
    affinity=None,               # AffinityTable 或 None
    triggers=None,               # 本轮待处理事件（事件网关投递）
    plan=None,                   # 可选：待物化/分派的 Ticket 草案集
    completed_refs=None,         # 已完成 external_ref 集合（调用方从 L0 算或注入）
    sink=None,                   # assignment → bool；None 时只产出不投递
    flags=None,                  # 模块开关
    shadow=True,                 # 默认 shadow
    now=None,                    # 注入时钟（测试）
    gate=None,                   # 双门：gate(plan) -> bool
) -> dict
```

返回：

```jsonc
{
  "ok": true,
  "degraded": false,
  "pass_id": "rp-<uuid>",
  "trace_id": "<pass 级 trace>",
  "shadow": true,
  "duration_ms": 12,
  "snapshot": { "total": 7, "live": 3, "paused": 2, "waitsForPerson": 1, "ended": 1 },
  "drift": [ { "ticket_id": "TK-1", "reason": "live_without_worker" } ],
  "resumed": [ { "ticket_id": "TK-2", "thread_id": "TH-1" } ],
  "materialized": [ { "ticket_id": "TK-9", "external_ref": "R9" } ],
  "assignments": [ { "external_ref": "R3", "ticket_id": "TK-3", "role": "research",
                     "worker_id": "w-res-1", "mandate": {...}, "trace_id": "..." } ],
  "would_assignments": [ /* shadow=true 时等价内容在此 */ ],
  "skipped":     [ { "external_ref": "R1", "reason": "already_live" } ],
  "unassigned":  [ { "external_ref": "E2", "reason": "no_free_worker" } ],
  "deferred":    [ { "external_ref": "E3", "reason": "dependency_unmet" } ],
  "error": null
}
```

失败契约（与既有 P0 组件一致）：

```jsonc
{ "ok": false, "degraded": true, "reason": "store_unavailable" }
```

### 4.2 IPC 方法：`router_pass`

| 项 | 值 |
|---|---|
| method | `router_pass` |
| 归属 | `superagent_p0.py` 的 `_METHODS`，`server.py` 的 `_P0_METHOD_NAMES` |
| params | `{ "roster": {...}, "plan": {...}, "triggers": [...], "shadow": true }`（均可缺省） |
| 状态 | 无状态；store 路径由 `server.py` 按 L0 root 约定解析后注入 |
| 附带诊断 | `router_loop_stats`（只读，返回最近 N 轮摘要 + 计数） |

> 与既有 `ticket_router_dispatch` 的关系：**同一份 core 实现**。`dispatch` 是"只跑步 6"的手动入口；`router_pass` 是"跑完 8 步"的循环入口。禁止为循环另写一套分派。

### 4.3 插件配置（Schemastery，无 `.enum()/.record()`）

```js
const Config = z.object({
  // ...既有字段
  enableRouterLoop: z.boolean().default(false),   // HC-2 默认关
  routerLoopIntervalMs: z.number().default(5000),
  routerLoopStartDelayMs: z.number().default(2000), // 避免启动风暴
  routerLoopShadow: z.boolean().default(true),    // 首版默认影子
  routerLoopWorkers: z.any().default({}),         // {role:[worker_id]}
  routerLoopMaxConsecutiveFailures: z.number().default(3),
  routerLoopWakeOnEvent: z.boolean().default(false), // D2-e，可后置
});
```

`cordis.patch.yml` 开启示例：

```yaml
- insert:
    - name: dreambuddy-superagent-p0
      config:
        enabled: true
        enableUpgrade: true
        enableRouterLoop: true
        routerLoopIntervalMs: 5000
        routerLoopShadow: true
        routerLoopWorkers:
          research: ["w-res-1", "w-res-2"]
          engineer: ["w-eng-1"]
```

### 4.4 Inbox 契约（assignment 投递）

```jsonc
// 34-前端应用训练系统/dsh_worker_inbox.jsonl，一行一条
{
  "schema_version": "1.0.0",
  "pass_id": "rp-...",
  "trace_id": "...",
  "external_ref": "R3",
  "ticket_id": "TK-3",
  "role": "research",
  "worker_id": "w-res-1",
  "mandate": { "goal": "...", "acceptance": "...", "completion_policy": {...} },
  "created_at": 1794488000.0
}
```

- append-only；消费方（Worker 拉起器）不在这里实现。
- 投递失败**不阻塞**本轮其余 assignment；失败条计入 `delivery_failures`。

---

## §5 开关与降级矩阵

| 开关 | 默认 | 关断时的行为 | 位置 |
|---|---|---|---|
| `enable_router_loop` | false | 不创建 timer，插件无循环副作用 | plugin config |
| `enable_superagent_router` | false | `run_pass` 返回 `loop_disabled`（复用既有模块开关） | core flags |
| `enable_ticket_store` | false | **硬依赖**：不开启时 pass 降级 `store_unavailable`（宁可不动，不建内存副本） | core flags |
| `enable_worker_pool` | false | 关闭时退化为 `route_single_round`（不剔除占槽 Worker） | core flags |
| `enable_thread_affinity` | false | 关闭时不绑定/不查询亲和 | core flags |
| `router_loop_shadow` | **true** | 只算不写，输出 `would_assignments` | plugin config |
| `routerLoopPlanPath` | `""` | plan 文件路径；空/缺失/坏 JSON → 本轮只做对账/唤醒（不物化、不分派）。调度方写文件即注入 plan（DD-D2-3 的 MVP 落点） | plugin config |
| `DSH_ENABLE_UPGRADE` | false | 既有总闸门；关闭时 `router_pass` 直接降级 | 环境变量 |

**降级顺序**：`DSH_ENABLE_UPGRADE` → `enable_router_loop` → `enable_superagent_router` → `enable_ticket_store`。任一不满足即返回 degraded，且**不产生任何写操作**。

---

## §6 观测

### 6.1 trace 主轴（ADR-7）

- 每轮 pass 生成 `pass_id`；`trace_id` 优先级：`ticket.trace_id`（已有）> 本轮 `pass_id` 派生。
- assignment / inbox / L0 记录三处都带同一 `trace_id`。
- 与既有链路兼容：`dreamos_sessions/spans` 不需要新表。

### 6.2 结构化日志（走 `server.py._send_stderr`）

```jsonc
{ "level": "INFO", "message": "router_pass", "pid": 1234,
  "pass_id": "rp-...", "duration_ms": 9, "live": 3, "assigned": 1,
  "skipped": 0, "unassigned": 0, "deferred": 0, "shadow": true }
```

### 6.3 诊断面

| 方法 | 返回 |
|---|---|
| `router_loop_stats` | `{ passes, last_pass, failures, consecutive_failures, circuit_open, skipped_overlap, ring: [最近 20 轮摘要] }` |
| 既有 `superagent_p0_health` | 增补 `router_loop: {enabled, shadow, interval_ms}` |

---

## §7 风险与红线

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| R1 | Router 单点 | 高 | 无状态 + 可随时重启；插件崩溃只影响循环，工具面仍在（Cordis 插件隔离） |
| R2 | 状态漂移（内存副本 vs L0） | 高 | 每轮 `recover_tickets`；红线：禁止内存权威副本 |
| R3 | 与同步工具双入口不一致 | 高 | 共用 `run_pass`/`route_single_round`，禁止复制逻辑 |
| R4 | tick 重叠 / 长尾 | 中 | 单飞 + 15s IPC 超时 + 熔断 |
| R5 | 日志风暴 | 中 | 同类失败日志 60s 限频 |
| R6 | 两层 shadow 语义混淆 | 中 | `event_gateway.shadow`（不改事件流）与 `router_loop_shadow`（不写 L0）相互独立，文档与配置各自标注 |
| R7 | 重复 Ticket | 中 | 幂等闸（`already_live`）+ `external_ref` 作为 Chain of Recall 锚点 |
| R8 | 交易热路径误接 | 高 | 循环不触任何交易模块；`*trading*` 白名单禁止项与 H5 一致 |

**红线**：H1 FAIL-OPEN / H2 开关默认关 / H3 状态不双写 / H5 交易热路径零接入 / H6 独立 profile / ADR-1 无状态。

---

## §8 分阶段实施与验收

### 8.1 阶段拆分（每阶段可独立回滚）

| 阶段 | 交付 | 文件 | 验收 |
|---|---|---|---|
| **D2a** | `run_pass` 纯函数 + `JsonlInboxSink` + 单测 | `34-前端应用训练系统/core/router_loop.py`、`tests/test_router_loop.py` | 无副作用；开关默认关；10 条单测全绿 |
| **D2b** | IPC 方法 `router_pass` / `router_loop_stats` | `python-server/superagent_p0.py`、`server.py` | 冒烟：handshake → `router_pass` 返回 `ok`；关断时 `degraded` |
| **D2c** | 插件 timer 宿主 + 单飞 + 熔断 + cleanup | `cordis-plugin-superagent-p0/lib/index.js` | 开关关 → 无 timer；开 → 每 interval 一次调用；dispose 后无回调 |
| **D2d** | shadow 观察 → 转正 | `cordis.patch.yml` | shadow 期 0 条 L0 写入；转正后 1 类事件端到端可复现 |
| **D2e（可选）** | 事件驱动唤醒（`wakeOnEvent`，500ms 去抖） | 插件侧 | 事件到达 ≤1s 内触发一次 pass |

### 8.2 验收标准（可测，对齐 DESIGN §七）

| # | 标准 | 测法 |
|---|---|---|
| A1 | 开关关断字节等价 | `enable_router_loop=false` 下 runtime 无 `router_pass` 调用、无新文件 |
| A2 | 无状态可复现 | 同一 store 快照 + 同一 roster，两次独立 `run_pass` 的 `assignments` 完全一致（除 `pass_id`/时间） |
| A3 | 幂等 | 对已有 live Ticket 的 ref 再入 plan → 进 `skipped(already_live)`，L0 不多出 Ticket |
| A4 | 槽位不抢占 | 3 个 live 占 3 槽时，第 4 个 Ticket → `unassigned(no_free_worker)` |
| A5 | paused 释放槽 | 一个 live → paused 后，同一轮新 Ticket 可复用该 Worker（V3） |
| A6 | shadow 不写 | `shadow=true` 时 `dsh_tickets.jsonl` mtime 不变、inbox 为空；`would_assignments` 非空 |
| A7 | FAIL-OPEN | store 路径不可写/坏行 → `degraded`，进程存活，下一轮可恢复 |
| A8 | 单飞 | 人为拖慢一轮（>interval）→ 后续 tick 计入 `skipped_overlap`，无并发调用 |
| A9 | 重启续跑 | 进程重启后首轮能 recover live/paused 并继续分派（V5） |
| A10 | trace 贯穿 | assignment == inbox == L0 记录的三处 `trace_id` 一致（V2） |

### 8.3 测试计划

| 层 | 文件 | 覆盖 |
|---|---|---|
| 单测 | `tests/test_router_loop.py`（新增） | A2/A3/A6/A7 + 对账/物化/闸门分支 |
| E2E | `tests/test_e2e_router_loop.py`（新增） | A5/A9/A10（真实 jsonl 落 tmp 根） |
| 回归 | 既有 `test_ticket_*.py` / `test_worker_pool.py` / `test_e2e_parallel_tickets.py` | 必须全绿（V1） |
| runtime | `dsh --profile headless` 冒烟 | A1/A8（配合 `router_loop_stats`） |

---

## §9 待决策

| # | 待决 | 建议 |
|---|---|---|
| DD-D2-1 | 默认 interval | 5000ms（Super-agent passes 实测同量级；纯计算无 LLM，成本可忽略） |
| DD-D2-2 | shadow 观察期多久转正 | 至少积累 3 类事件 × 20 轮 pass，人工比对 `would_*` 与人工预期 |
| DD-D2-3 | `completed_refs` 来源 | ✅ 已落地（R14）：`core/worker_receipts.py` 消费 `dsh_worker_receipts.jsonl`（`{"ticket_id","status":"done|failed","evidence","at"}`）→ `done→ended` / `failed→paused+waiting_person`；坏行 FAIL-OPEN；`run_pass` 步骤 2b 消费后由 L0 `ended` Ticket 派生 `completed_refs`，调用方仍可注入覆盖。**v0.2 计划扩展（W0，见 [PROPOSAL-P0-D3 §9.1](PROPOSAL-P0-D3-WORKER-LAUNCHER-v0.1.md)）**：`failed` 携带 `failure_class`，`retryable→paused(waiting_job)`、`manual→waitsForPerson`，缺省按 `manual` 兼容 |
| DD-D2-4 | inbox 消费方谁来实现 | 单独立项「Worker 拉起器」：[PROPOSAL-P0-D3](PROPOSAL-P0-D3-WORKER-LAUNCHER-v0.1.md)；Router 侧消费端已落地（`worker_receipts.apply_receipts`，R14），D2 现交付「投递 + 回执」双向契约 |
| DD-D2-5 | 花名册来源 | MVP 插件 config；后续接 47 `worker_roles`（ADR-4 唯一载体） |
| DD-D2-6 | 是否引入事件唤醒 | 先跑 timer；若实测事件到分派延迟 > 1 个 interval 再加 `wakeOnEvent` |

---

## §10 文件清单（开工时新增/修改）

| 类型 | 路径 | 动作 |
|---|---|---|
| 新增 | `34-前端应用训练系统/core/router_loop.py` | `run_pass` + `JsonlInboxSink` + `PassStats` |
| 新增 | `34-前端应用训练系统/tests/test_router_loop.py` | 单测 |
| 新增 | `34-前端应用训练系统/tests/test_e2e_router_loop.py` | E2E |
| 修改 | `dream-harness-bridge/packages/python-server/superagent_p0.py` | `router_pass` / `router_loop_stats` |
| 修改 | `dream-harness-bridge/packages/python-server/server.py` | `_P0_METHOD_NAMES` 增 2 项 |
| 修改 | `dream-harness-bridge/packages/cordis-plugin-superagent-p0/lib/index.js` | timer 宿主 + 单飞 + 熔断 + 配置 |
| 修改 | `.dsh-home/profiles/headless/cordis.patch.yml` | 新配置项（默认关） |
| 修改 | `53-DSH插件模块/SPEC-53-...md` §9.3 | P0-D2 状态更新 + 指向本文件 |

> 不改动：`ticket_router.py` / `worker_pool.py` / `ticket_state.py` / `ticket_store.py` / `ticket_resume.py` / `thread_affinity.py`（全部复用）。

---

## §11 实施记录（2026-11-12）

### 11.1 已落地（D2a / D2b / D2c）

| 阶段 | 文件 | 实际实现 |
|---|---|---|
| D2a | [`core/router_loop.py`](../../../34-前端应用训练系统/core/router_loop.py) | `run_pass()` 八步编排 + `JsonlInboxSink` + `PassStats` + `is_loop_enabled()`；默认 `shadow=True` |
| D2a | [`tests/test_router_loop.py`](../../../34-前端应用训练系统/tests/test_router_loop.py) | 15 条单测（见 11.2） |
| D2b | [`python-server/superagent_p0.py`](../../../1-ARCHITECTURE/dream-harness-bridge/packages/python-server/superagent_p0.py) | `router_pass` / `router_loop_stats` + 进程级 store/affinity/stats/sink 单例 |
| D2b | [`python-server/server.py`](../../../1-ARCHITECTURE/dream-harness-bridge/packages/python-server/server.py) | `_P0_METHOD_NAMES` 增 2 项 |
| D2c | [`cordis-plugin-superagent-p0/lib/index.js`](../../../1-ARCHITECTURE/dream-harness-bridge/packages/cordis-plugin-superagent-p0/lib/index.js) | `ctx.effect` 内 setTimeout→setInterval；单飞 / 熔断 3 次 / 日志 60s 限频 / cleanup；新增第 5 个工具 `dreamos_router_loop_stats` |

### 11.2 验证证据

| 项 | 结果 |
|---|---|
| 单测 | `pytest tests/test_router_loop.py` → **15 passed** |
| 回归 | `pytest tests/` → **全绿**（原既有失败 `test_mandate_gate::test_load_worker_roles_real_registry` 已同步 47 registry 的 8 个当前角色，2026-11-12 修复） |
| IPC 冒烟 | `server.py` NDJSON：handshake ok / `router_pass` 返回 `assignments=[SMOKE-1→w-res-1]` / `router_loop_stats` ok |
| 插件循环冒烟 | stub ctx：`PASSES=4`（interval=600ms，约 2.9s），5 个工具全部注册 |
| shadow 零写入 | 冒烟后 `dsh_tickets.jsonl` / `dsh_worker_inbox.jsonl` **均未生成** |
| 进程 | 循环启用后仍复用共享 IPC，退出后 `server.py` 残留 **0** |

### 11.3 与设计的偏差（已确认合理）

1. **幂等闸从"仅 live"扩展为"任意状态"**：ended 的 ref 若再次进入 plan 会被重派（测试暴露），故按状态细分为 `already_live` / `already_open` / `already_ended`。
2. **新增第 5 个 Worker 工具** `dreamos_router_loop_stats`：设计 §6.3 只定义了诊断方法，若不暴露工具则外部不可读。
3. **IPC 响应为双封装** `{ result: { ok, result: summary } }`：与既有 4 个 P0 方法一致，插件侧按 `resp.result.result ?? resp.result` 解包。

### 11.4 未执行

- **D2d**：shadow 观察期（需在 `cordis.patch.yml` 将 `enableRouterLoop: true`，默认仍为 false）
- **D2e**：事件驱动唤醒（`wakeOnEvent`）
- inbox 消费方（Worker 拉起器）按 DD-D2-4 单独立项，不在本设计内

