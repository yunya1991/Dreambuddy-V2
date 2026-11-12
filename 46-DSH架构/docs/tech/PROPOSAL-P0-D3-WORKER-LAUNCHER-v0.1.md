# PROPOSAL-P0-D3 Worker 拉起器立项文档（草案）

- **版本**: v0.5 ｜ **日期**: 2026-11-13 ｜ **状态**: 草案（S0/W0/W1/W2 已完成；W3 静态部分完成 + A7 实跑通过；W4 可观测/CLI/systemd 已就位，剩余需云端与真实额度）
- **归属**: 46-DSH架构 / 执行侧运行时
- **上游约束**: [DESIGN-P0-D2-ROUTER-LOOP-v0.1](DESIGN-P0-D2-ROUTER-LOOP-v0.1.md)（DD-D2-4）｜ DESIGN-DSH-ARCH-UPGRADE v0.2（ADR-9/ADR-10、G1/G2/G3）｜ [47 worker_roles](../../../47-MCP管理系统/registry/mcp_capabilities.yaml#L540)
- **下游影响**: `34-前端应用训练系统/` 新增执行侧运行时；`dsh_worker_inbox.jsonl` 消费方；`dsh_worker_receipts.jsonl` 生产方

---

## §0 一句话定位

D2 已把「Router 派单 → inbox 投递 → 回执消费 → 依赖解除」的双向契约打通，但 **inbox 没有执行者**：Worker 拉起器负责消费 `dsh_worker_inbox.jsonl`，按角色能力集执行任务，并把结果写回 `dsh_worker_receipts.jsonl`。

**结论**：建议单独立项（P0-D3），先做契约冻结 + 单角色 MVP，再扩池化与多角色。**不改造 Router 算法，不新增 Ticket 状态**。

## §1 背景与问题

### 1.1 现状

| 能力 | 状态 | 证据 |
|---|---|---|
| Router 常驻循环（八步 + 回执消费） | 已落地 | [router_loop.py](../../../34-前端应用训练系统/core/router_loop.py) |
| 派单投递 `dsh_worker_inbox.jsonl` | 已落地（append-only） | `JsonlInboxSink`，路径常量 `_INBOX_REL_PATH` |
| 回执消费 `dsh_worker_receipts.jsonl` | 已落地（R14/R16） | [worker_receipts.py](../../../34-前端应用训练系统/core/worker_receipts.py) |
| **投递消费 / Worker 执行** | **缺失** | DESIGN-D2 DD-D2-4（[L385](DESIGN-P0-D2-ROUTER-LOOP-v0.1.md#L385)） |
| 角色→工具集矩阵 | 已定义（8 角色） | [mcp_capabilities.yaml](../../../47-MCP管理系统/registry/mcp_capabilities.yaml#L540) |

### 1.2 缺口后果

1. inbox 只增不减，`live` Ticket 永远等不到回执 → 依赖闸永不解除、槽位永久占用。
2. 无执行侧就无法验证「派单 → 执行 → 回执 → 状态迁移」的真实闭环，只能靠模拟。
3. 角色只读约束（ADR-9）没有执行侧兜底，存在越权调用风险。

## §2 目标与非目标

### 2.1 目标

| # | 目标 | 可判定标准 |
|---|---|---|
| G-1 | 消费 inbox，按 `worker_id/role` 执行任务 | 每条 assignment 恰好被一个 Worker 领取一次 |
| G-2 | 结果回写标准回执 | `done`/`failed` 回执 100% 含 `ticket_id/status/evidence/at` |
| G-3 | 角色能力集强约束 | 越权工具调用被拒绝并产出 `failed` 回执 |
| G-4 | 崩溃可恢复 | 拉起器 kill -9 后重启，未完成 assignment 可重新领取，不丢不重派已终态 Ticket |
| G-5 | 可观测 | 每轮 claim/execute/receipt 三段有结构化日志与计数 |
| G-6 | 复用 D2 契约，零改 Router | 不修改 `run_pass` 的八步语义与 Ticket 四态 |

### 2.2 非目标（明确不做）

- 不实现分派/依赖/槽位算法（属 Router）。
- 不直接写 `dsh_tickets.jsonl`（唯一入口是回执文件）。
- 不开放交易写工具（`executor` 角色恒只读）。
- 不做自然语言任务分解（D2 的 `plan.tickets.mandate` 已给出目标）。
- 不替换 MCP、不改造 42/47 注册表。

## §3 范围

### 3.1 In Scope

- 拉起器守护进程（inbox tail + claim + 执行 + 回执）。
- Worker 运行时封装（角色能力集装载、工具调用句柄）。
- 领取/超时/重试/心跳的本地状态机。
- 单测、故障注入、端到端场景测试。
- 运维入口（启动/停止/查看 offset 与在途任务）。

### 3.2 Out of Scope

- DSH 内核插件加载机制改造。
- Router 侧 `routerLoopWorkers` 花名册协议变更。
- 45 评测门禁与 Mandate 签发（沿用现有）。

## §4 架构草案

### 4.1 组件图

```
┌─ 调度侧（已落地，D2）─────────────────────────────────────┐
│ router_loop.run_pass                                      │
│   ├ 物化/分派/提交                                        │
│   └ worker_receipts.apply_receipts ◄──────────┐           │
└──────────────┬────────────────────────────────┼───────────┘
               │ append                              │ append
┌──────────────▼──────────────┐        ┌───────────┴───────────┐
│ dsh_worker_inbox.jsonl      │        │ dsh_worker_receipts   │
│ （assignment，只追加）       │        │ .jsonl（只追加）      │
└──────────────┬──────────────┘        └───────────▲───────────┘
               │ tail/claim                        │ result
┌──────────────▼─ P0-D3 Worker 拉起器 ─────────────┴───────────┐
│  launcher（单进程守护）                                        │
│   ├ OffsetStore       已消费偏移（重启恢复）                   │
│   ├ ClaimTable        在途任务 + lease/心跳                    │
│   ├ RoleRouter        worker_id/role → 能力集                  │
│   ├ Executor          调用 DSH Worker 运行时执行 mandate        │
│   └ ReceiptWriter     done/failed + evidence                   │
└──────────────┬─────────────────────────────────────────────────┘
               │ 角色能力集（只读 MCP 工具）
┌──────────────▼─ DSH 运行时 / MCP 壳 ──────────────────────────┐
│ 按域共享壳（G2）：cognition / data / rea … 连接数=域数         │
│ Worker 仅持工具调用句柄，不新建 N×连接                          │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 执行模型（D1 决策）

| 方案 | 描述 | 优点 | 风险 | 结论 |
|---|---|---|---|---|
| A. 进程级 Worker | 每个 `worker_id` 一个 DSH 进程 | 隔离简单 | 连接数随 Worker 数增长，违背 G2 | 仅作 MVP 降级 |
| B. 单运行时多会话 | 一个 DSH 运行时托管 N 个 Worker 会话，按域共享壳 | 符合 G2（连接数=域数） | 依赖 DSH 0.1.5 子会话能力 | **目标形态** |

**D1 决策**：目标形态为 **B（单运行时多会话）**，生产必须满足 G2。S0 spike 限时 2 天；未通过则 **W1 仅允许在 sandbox 用方案 A 跑通闭环**，生产上线继续 blocked，直到 B 验证通过。禁止用方案 A 直接进生产。

### 4.2.1 并发度（D2 决策）

- 并发上限 = `routerLoopWorkers` 花名册（单一事实源），默认每角色 1 个 Worker。
- 全局并发 = 花名册 worker_id 总数，硬上限 8；单角色上限 2。
- 首版**不做动态扩缩容**：固定池 + 队列（inbox）已能满足可预测性与成本约束；扩容等指标（P95 时延/排队长度）达标后再议。

### 4.3 输入契约（inbox assignment）

```json
{
  "ticket_id": "TK-R1",
  "external_ref": "R1",
  "worker_id": "w-research-1",
  "role": "research",
  "mandate": { "goal": "..." },
  "trace_id": "rp-xxxxxxxx",
  "assigned_at": 1794498000.0
}
```

约束：`ticket_id + worker_id + trace_id` 唯一定位一次派单；`role` 必须在 47 `worker_roles` 白名单内。

### 4.4 输出契约（receipt v0.2）

```json
{
  "ticket_id": "TK-R1",
  "status": "done",
  "failure_class": null,
  "evidence": { "summary": "...", "artifacts": [], "duration_ms": 1234 },
  "attempts": 1,
  "next_retry_at": null,
  "at": "2026-11-12T15:04:05+08:00",
  "receipt_id": "rc-<uuid>",
  "worker_id": "w-research-1",
  "trace_id": "rp-xxxxxxxx"
}
```

- `status ∈ {done, failed}`；`failed` 时 `failure_class ∈ {retryable, manual}` 且必填。
- `evidence.reason`：`timeout|role_violation|tool_error|runtime_error|budget_exceeded`。
- `attempts`：已执行次数（从 1 开始）；`next_retry_at` 仅 `retryable` 非空。
- 消费侧以内容键去重（R16），拉起器仍必须保证 `receipt_id` 唯一。
- 禁止伪造 `ticket_id`；未知/已终态 Ticket 的回执由 Router 侧 `ignored` 兜底。

**失败分类 → Ticket 状态映射（D2 消费端 W0 需扩展）**：

| receipt | Ticket 结果 | 语义 | 是否占槽 |
|---|---|---|---|
| `done` | `ended` | 完成 | 释放 |
| `failed` + `retryable` | `paused` + `waiting_job` | 自动退避重试中，无需人工 | 释放 |
| `failed` + `manual` | `waitsForPerson` | 重试耗尽 / 权限或契约错误，需人工 | 释放 |

> 旧版消费端把所有 `failed` 映射为 `paused + waiting_person`；W0 契约冻结时同步扩展 `worker_receipts` 与单测，旧回执（无 `failure_class`）按 `manual` 兼容。

**W0 落地（2026-11-13）**：`core/worker_receipts.py` 已实现 `_resolve_target(status, failure_class)`；单测覆盖 retryable / manual / 缺省 / 未知值四种输入（`test_router_loop.py`）。

### 4.5 领取与幂等

1. 读 inbox 增量（持久化 `offset`，按字节）。
2. `worker_id` 必须命中本地花名册；不命中 → 写 `failed(role_violation)`，不执行。
3. 领取写入 `claims.json`（`ticket_id → {state, lease_until, attempt, worker_id}`），加 `fcntl.flock` 防多实例。
4. 已存在 `done/failed` 回执的 `ticket_id` → 跳过（防重放）。
5. 同一 assignment 只允许一个 Worker 执行（at-least-once 语义，回执侧幂等）。

### 4.6 失败、超时与重试（D3/D4 决策）

| 场景 | 处理 | failure_class |
|---|---|---|
| 工具执行异常 | 捕获 → 退避重试，不 crash 守护进程（FAIL-OPEN） | retryable |
| 心跳丢失（lease 过期） | 回收 → 重新入队重试 | retryable |
| 单次执行超过 `task_timeout`（默认 300s，角色可覆盖） | kill 子任务 → 重试 | retryable |
| 超过 `max_task_duration`（默认 30min） | 强制终止，不再重试 | manual |
| 重试耗尽（`attempts >= 3`） | 写终态回执 | manual |
| Worker 进程崩溃 | lease 过期回收；重启后按 claim 表恢复 | retryable |
| 未知角色 / 越权工具 | 直接拒绝，不重试 | manual |

**两套时钟（最佳实践：liveness 与执行超时分离）**：

- 心跳 `heartbeat_interval = 10s`；租约 `lease_ttl = 30s`（3 次未心跳判失联）。
- 重试退避：`5s → 20s → 60s` + ±20% jitter；最多 `max_attempts = 3`。
- 长任务通过心跳**续租**（D4），但受 `max_task_duration` 硬上限约束，防止无限占用。

**硬约束**：主循环禁止忙轮询（G3）；等待外部 job 完成必须由事件唤醒；轮询仅为 inbox tail（默认 500ms）。

### 4.7 权限与安全

- **ADR-9/G1**：Worker 只读；拉起器按 `worker_roles[role].tools` 白名单装载工具，越权调用在拉起器侧直接拒绝。
- **G2**：壳实例按域共享，Worker 只持句柄；不得为每个 assignment 新建 MCP 连接。
- 不持有交易写权限；`executor` 仅 `get_* / pre_trade_check / reconcile` 只读。
- 不读取 `.env`/密钥；凭据由宿主注入。

### 4.8 可观测

- 结构化日志：`pass_offset`、`claimed`、`started`、`finished`、`failed`、`receipt_written`。
- 指标（本地 JSON）：在途数、成功率、P50/P95 时延、超时数、角色拒绝数。→ 已在 §4.16 落地（`metrics.json` + `status` 子命令）
- 与 Router `router_loop_stats` 对账：`inbox_lines ≈ receipts + in_flight`。

### 4.9 部署形态（D6 决策：云端 systemd）

**生产环境以云端 Linux + systemd 为唯一形态**；本地 macOS 仅用于开发（前台进程或 tmux），不作为部署目标。

| 项 | 决策 |
|---|---|
| 托管方式 | `dreambuddy-worker-launcher.service`（systemd system unit） |
| 运行用户 | 专用非 root 用户（如 `dreambuddy`），只读挂载代码与 L0 |
| 重启策略 | `Restart=on-failure`、`RestartSec=5`、`StartLimitIntervalSec=60`、`StartLimitBurst=10` |
| 停止语义 | `KillMode=mixed`、`TimeoutStopSec=30`，先 SIGTERM 触发优雅退出并 flush offset/claims |
| 日志 | 直接写 journald（`StandardOutput=journal`），不落自定义日志文件 |
| 配置 | `EnvironmentFile=/etc/dreambuddy/worker-launcher.env` + 花名册只读注入 |
| 启动前检查 | `ExecStartPre` 跑 `preflight`：花名册非空且自检通过、状态/回执目录可写（offset 同目录，写权限由目录探针覆盖）、offset 可解析 |
| 高可用 | 首版单实例 + `flock` 防双开；多实例需先做分片（按 role/worker_id） |

> 选择 systemd 的理由：云端已有 systemd 基础设施；`Restart=on-failure` + journald 满足崩溃恢复与可观测的最小闭环，无需引入额外 supervisor。容器化（K8s）留作规模化后的演进，不作为首版依赖。
>
> 落地清单（unit 文件、env 模板、`preflight/once/run/status` 子命令）见 §4.16。

### 4.10 L0 归属与 StorePort 对齐（W0 冻结）

**归属澄清**：本文的「L0」指**通用 L0 能力**（`dreambuddy_l0/`，SPEC-C C1），不是 `34-前端应用训练系统` 的训练业务。

| 层 | 实体 | 说明 |
|---|---|---|
| 通用 L0 包 | `dreambuddy_l0/`：envelope / facade / ports / adapters / scheduling | 唯一公共门面（`get_l0()`） |
| 34 的薄壳 | `34-.../core/l0_foundation.py` | 仅 re-export 历史 11 个 scope，不是 L0 本体 |
| 本地存储适配 | `34-.../core/ticket_store.py`（`JsonlTicketStore`） | append/read_all；路径 `34-前端应用训练系统/dsh_tickets.jsonl` 只是**路径约定**，不代表业务归属 |
| 上云适配 | 待接 PG（同 StorePort 接口） | 替换 adapter，编排层零改动 |

**四个 dsh_* 文件的角色不同，不能都叫「事实源」**：

| 文件 | 角色 | 读写方 |
|---|---|---|
| `dsh_tickets.jsonl` | **权威状态（SSoT，ADR-2）** | Router 读快照 / 回执消费后写 |
| `dsh_worker_inbox.jsonl` | 派单投递**通道**（append-only） | Router 写 → Worker 读 |
| `dsh_worker_receipts.jsonl` | 结果回执**通道**（append-only） | Worker 写 → Router 读 |
| `dsh_router_plan.json` | plan **输入通道**（调度方注入，`routerLoopPlanPath`）；**非事实源** | 调度方写 → 插件读；profile 已配路径，仓库内暂无写入方 |

**StorePort 映射（方案 A：保留私有接口，加适配层）**：

新增 `dreambuddy_l0/adapters/ticket.py::TicketStoreAdapter`，把 legacy `append/read_all` 映射为通用 `StorePort`：

| StorePort | 映射 |
|---|---|
| `read(table="dsh_tickets", key=ticket_id)` | `read_all()` 后按 ticket_id 取最后一条（latest-wins） |
| `write(table, data, idempotency_key)` | `legacy.append(data)`；`write` 带 `@require_principal(ALLOWED_ROLES_STORE)` |
| `query(table, filters)` | latest-wins 结果集上过滤 |
| `health()` | `{ok, dialect:"jsonl-ticket", tables:1, path}` |

**硬约束（易踩坑）**：`idempotency_key` **不得直接用 `ticket_id`**。latest-wins 下同一 Ticket 会多次写入不同状态，用 ticket_id 做幂等键会把后续状态更新全部吞掉。缺省时按「内容哈希（剔除 `stored_at` 等易变字段）」推导；显式传入时持久化到内部字段 `_adapter_idem_key`，读取时剥离。

**理由**：既让「云端 PG 同接口注入」有可对齐的契约，又不触碰 `router_loop` 八步语义（验收 A6）。

### 4.11 W1 落地与 W2 差异（2026-11-13）

**实现**：`34-前端应用训练系统/core/worker_launcher.py`

| 组件 | 实现 |
|---|---|
| `WorkerLauncher` | `run_once()` / `run_forever(poll_interval=0.5)`；inbox 增量 → 判权 → claim → executor → 回执 |
| `DshCliExecutor` | 方案 A 降级：每 assignment 起一个 `dsh --profile <p> "<goal>"` 子进程；**仅 sandbox**，生产仍 blocked 到方案 B |
| 状态文件 | `34-.../.worker_launcher/offset.json`、`claims.json`（`flock` 单写） |
| Executor | 注入式 callable，签名为 `(assignment) -> {status, failure_class?, evidence?}` |

**W1 明确未含（W2 补齐）**：心跳/租约回收、退避重试（5/20/60s）、`task_timeout` kill、`max_task_duration` 硬上限、多角色并发。

**W1 的保守降级**：executor 返回 `retryable` 一律升级为 `manual(retry_exhausted)`。原因是没有重试循环时写 `retryable` 会留下 `paused(waiting_job)`，而无人唤醒 → Ticket 永久卡住。**（已被 §4.12 取代：W2 引入重试循环后 `retryable` 正常生效。）**

**证据**：`test_worker_launcher.py` 9 例（offset/半行、坏行 FAIL-OPEN、重复回执跳过、越权拒绝、异常、retryable 升级、Router 端到端 `ended`）；D2+D3 回归 303 项全绿。

### 4.12 W2 恢复与超时落地（2026-11-13）

**claim 状态机**：`claims.json` 每条记录 `{state: pending|retry_pending|running, attempt, next_retry_at, lease_until, first_started_at, assignment}`，`flock` 单写。

| 能力 | 实现 |
|---|---|
| offset 自愈 | `offset.json` 同时存 64 字节头部指纹；文件截断/轮转/**等长替换**均从头重读（仅比 size 会漏判） |
| 心跳 | `_Heartbeat` 线程每 10s 把 `lease_until` 推后 30s；executor 结束即停 |
| 租约回收 | 启动/每轮把 `running && lease_until < now` 的 claim 改回 `retry_pending` 并立即重试，`attempt` 续接 |
| 退避 | 第 1/2/3 次失败后 5/20/60s，±20% jitter（测试可注入 `jitter_ratio=0`） |
| 超时 | `task_timeout` 默认 300s，角色可用 `roles[role].task_timeout` 覆盖；超时 → retryable |
| 硬上限 | `max_task_duration` 默认 1800s，超限直接 `failed(manual, timeout)`，不再重试 |

**失败分类（W2 定稿）**：

| 场景 | 分类 | 行为 |
|---|---|---|
| 正常完成 | — | `done` 终态回执 |
| 工具异常 / 超时 / 租约丢失 | `retryable` | 中间重试**不写回执**，仅本地 `attempt++` |
| 3 次耗尽 | `manual` | 写一次终态回执，`reason` 保留最后一次（`tool_error`/`timeout`/`runtime_error`），`summary` 追加 `retry exhausted after N attempts` |
| 未知角色 / 未知 status | `manual` | 直接终态，不重试 |

**已知边界**：
- Python 线程无法被强杀。`task_timeout` 到期后主线程放弃该 daemon 线程并计一次失败，线程可能仍在后台跑完；真实强杀依赖 W4 的进程/会话级取消（W3 只做角色与 G2 校验，未触及执行取消）。
- 真实 `kill -9` 联调（含 flock 遗留、半写回执）留 W4，本轮用「租约过期 + offset 已推进」的崩溃现场模拟。

**证据**：`test_worker_launcher.py` 15 例（含四类故障注入）；D2+D3 回归 309 项全绿；ruff 清洁。

### 4.13 W3 多角色与 G2 校验落地（2026-11-13）

**新增 `34-前端应用训练系统/core/worker_roles.py`**（只做校验，不做工具调用）：

| 能力 | 实现 |
|---|---|
| 花名册装载 | `load_worker_roles()` 读 47 `mcp_capabilities.yaml` 的 `worker_roles`（8 角色）；读取失败返回 `{}`，由调用方决定 FAIL-OPEN |
| 角色自检 | `RolePolicy.validate()`：空工具集 / 单角色 >10 工具 / 重复工具 / 含写工具 / 空 `shells` |
| 越权判定 | `RolePolicy.check(role, requested)`：未知 role、空工具集、`requested` 非白名单子集 → 返回违规原因（None 为通过） |
| G2 聚合 | `g2_summary()`：从 `mcp_profiles.json` 提取入口，统计 `--role` 网关 profile 的入口集合；`connections_independent_of_roles = len(role_entrypoints) <= 1` |

**拉起器接入**：`worker_launcher.py` 内 `self.policy = RolePolicy(self.roles)`；`_role_violation` 依次判定「`worker_id` 是否在本地花名册 → `role` 是否在白名单 → `requested tools` 是否为白名单子集」，任一失败 → `failed(manual, role_violation)`，executor 零调用。`mandate.tools` 可省略；省略时按角色全量白名单放行。

**越权矩阵（W3 定稿）**：

| 输入 | 结果 |
|---|---|
| `worker_id` 不在本地花名册 | `failed(manual, role_violation)` |
| `role` 不在 8 角色白名单 | `failed(manual, role_violation)` |
| `tools`/`mandate.tools` 非 list | `failed(manual, role_violation)` |
| `tools` 含白名单外工具（如 `place_order`） | `failed(manual, role_violation)` |
| `tools` 为白名单子集 / 省略 | 正常执行 |

**边界**：G2 本轮是**静态口径校验**（profile 入口是否聚合），不是实跑连接计数；真实单进程多会话（A7）与角色网关连通验证受 DeepSeek quota 限制，留 W4。

**证据**：`test_worker_roles.py` 5 例（8 角色只读 / 禁用工具锚点 / 越权矩阵 / validate 违规 / G2 入口聚合）+ `test_worker_launcher.py` 17 例（新增越权拒绝、白名单内执行 2 例）；D2+D3 相关套件 61 项全绿；ruff 清洁。

### 4.14 W4-A7 单进程多会话实跑（2026-11-13）

**背景**：DeepSeek 额度仍为 `QUOTA: Insufficient Balance`，真实 LLM 调用不可用。为不阻塞 A7，采用 **LLM 层 stub + 真实运行时** 的验证方式：被替换的只有最外层 provider，agent loop、subagent seam、workflow 引擎、会话持久化全部真实执行。

**探针位置**：`34-前端应用训练系统/tools/a7_probe/`
- `stub_llm_plugin/`：实现 `LlmAdapter`（`providerInfo` / `listModels` / `resolveModel` / `prepareCall` / `stream`），注册 provider `stub`，不发起任何网络请求；
- `a7.patch.yml`：`agent-default-model` 指向 `stub/stub-1`，并用 `insert` 挂载探针插件；
- `run_a7.sh`：复制插件到 sandbox profile 的 `node_modules` 后执行 `dsh --profile sandbox --patch ...`。

**执行链路**：根 agent（stub）发出一笔 `workflow` 工具调用 → workflow 引擎 `parallel([() => agent(...), () => agent(...)])` 拉起 2 个 child agent → 两个 child 会话在同一进程内并发完成 → 结果回传根 agent。

**实跑证据（pid 21057）**：

```
A7_STUB stream#1 pid=21057 marker=ROOT   inflight=1 max=1
A7_STUB stream#3 pid=21057 marker=CHILD  inflight=1 max=2
A7_STUB stream#4 pid=21057 marker=CHILD  inflight=2 max=2   ← 两个子会话并发重叠
A7_STUB tool-result isError=false body="workflow \"a7-multi-session\" completed (2 agents). ..."
ROOT_DONE
```

**会话血缘**（`DSH_HOME/sessions/.../session.v3.jsonl.zstd` 首行）：

| session id | origin | parentSession | delegationDepth | createdAt |
|---|---|---|---|---|
| session-75986505… | — | — | 0 | 1794502737808 |
| 2e9ff117… | `subagent` | session-75986505… | 1 | 1794502737925 |
| 2f9c5aa4… | `subagent` | session-75986505… | 1 | 1794502737925 |

> 两个 child 会话 `createdAt` 完全相同，且 `parentSession` 指向同一根会话，证明是同一父会话下的并发子会话，而非串行。

**结论与边界**：
- A7 的「同一 pid 内 ≥2 child session 并发完成 mandate」已实测成立，方案 B（单运行时多会话）可行。
- 本次未验证：真实 LLM 下的 P95 时延与 token 成本、8 Worker 场景 MCP 实际连接计数（A5 实跑口径）、child 会话失败传播。均需额度恢复后补测。
- 探针仅挂在 sandbox profile，不进入 headless/web，不影响生产路径。

### 4.15 方案 B 下沉：InProcessSessionExecutor（2026-11-13）

**目标**：D3 执行侧不再「一任务一进程」（方案 A），改为「一批任务一个运行时、批内多 child session 并发」（方案 B）。

**组成**：

| 层 | 文件 | 职责 |
|---|---|---|
| Python 执行器 | `34-前端应用训练系统/core/inproc_session_executor.py` | `run_batch(assignments)`：写批次输入 → 拉一个 `dsh` → 读批次输出 → 归一化为既有 result 契约；`__call__` 兼容单任务接口 |
| Node 宿主插件 | `34-前端应用训练系统/tools/dsh_session_host/` | `apply()` 内创建 1 个根 agent，按 `D3_HOST_MAX` 并发启动 K 个 child session（`ctx.subagents.start('spawn', {parent, prompt, agentOptions, signal})`），写结果后退出 |
| 拉起器接线 | `core/worker_launcher.py` | `run_once` 检测 executor 是否提供 `run_batch`：有则整批一次调用，无则保持逐任务 `_execute`（向后兼容） |

**契约**：
- 批次输入 `[{ticket_id, role, goal, timeout_ms, provider?, model?}]`；输出 `{ticket_id: {status, failure_class?, evidence:{summary, reason, duration_ms, session_id, pid}}}`。
- 归类逻辑与单任务完全一致（`_classify` 共用）：`done` → 终态；`retryable` → 退避重试；`manual` → `waitsForPerson`。
- 超时三层：单 child `timeout_ms`（宿主侧 AbortController）→ 批次 join 超时（Python 侧释放线程）→ `max_task_duration` 硬上限。
- 模型路由必须显式：根 agent 与 child 都需 `provider/model`（`D3_MODEL_PROVIDER` / `D3_MODEL_NAME`，或 assignment 级覆盖）。空路由会让 child 直接 `stopReason=error`。

**实跑证据（2026-11-13，stub LLM）**：

```
D3_HOST batch tasks=2 max=4 pid=24062
TK-A7-1 → done session=0f5f08f6… duration_ms=1590
TK-A7-2 → done session=a0b3cbb5… duration_ms=1591
```

同 pid、两个不同 session、耗时几乎相同（并行而非串行），说明一批 2 个 assignment 只起 1 个运行时。

**边界**：
- 当前是「**批级**单运行时」：每个 `run_once` 批次起一个 `dsh`，批次结束即退出；不是跨批次常驻守护。常驻化需要 `dsh` 提供 serve/长连接能力，留作后续。
- 批内并发上限 = `D3_HOST_MAX`（默认 8，与花名册硬上限对齐）；超时强杀仍是进程级（Python 杀宿主进程），不是单会话级取消。
- 生产需配真实 provider/model；本轮仅用 stub 验证链路。

### 4.16 W4 收口：可观测 + 运维 CLI + systemd unit（2026-11-13）

**可观测（§4.8 落地）**

| 层 | 文件 | 内容 |
|---|---|---|
| 聚合器 | `core/worker_launcher_metrics.py` | 每轮 `run_once` 统计并入 `<state_dir>/metrics.json`；累计计数 + 滚动时延窗口（默认 500）→ P50/P95/max + 成功率 + 在途峰值；坏文件 FAIL-OPEN |
| 拉起器接线 | `core/worker_launcher.py` | 新增 `pass_offset`、`role_rejections`、`done`、`latencies_ms`、`in_flight_peak`；`run_once` = `_run_once` + `metrics.record`（指标异常不影响本轮） |
| 结构化日志 | CLI `run` | 每轮向 journald 打一行 JSON：`{"event":"pass", ...stats}` |

时延口径：优先取 executor 回传的 `evidence.duration_ms`（方案 B 下是单个 child session 的真实耗时），缺失时回退墙钟差；批次超时/异常也计入一条。

**运维 CLI（`core/worker_launcher_cli.py`）**

| 子命令 | 用途 | 退出码 |
|---|---|---|
| `preflight` | 花名册非空 + 自检通过、状态/回执目录可写、offset 可读 | 0 通过 / 2 失败（systemd `ExecStartPre` 据此拒绝启动） |
| `once` | 单轮消费（联调 / 手动补跑） | 0 无 error / 1 有 error |
| `run` | 常驻循环，SIGTERM/SIGINT 优雅退出；`flock` 单实例（已被占用退出码 3） | 0 |
| `status` | 打印 `metrics.json` 派生视图 + claims 状态分布 | 0 |

参数默认值全部来自 `EnvironmentFile`：`D3_ROOT` / `D3_ROLES_PATH` / `D3_WORKERS` / `D3_EXECUTOR`（`inproc`｜`dsh-cli`｜`noop`）/ `D3_PROFILE` / `D3_MAX_CONCURRENCY` / `D3_POLL_INTERVAL` / `D3_MODEL_PROVIDER` / `D3_MODEL_NAME`。`noop` 仅用于本地冒烟，生产必须是 `inproc`。

**systemd 与部署清单**

| 文件 | 说明 |
|---|---|
| `34-前端应用训练系统/deploy/dreambuddy-worker-launcher.service` | `WorkingDirectory=/opt/dreambuddy/34-前端应用训练系统`；`ExecStartPre=... -m core.worker_launcher_cli preflight`；`Restart=on-failure` / `RestartSec=5` / `KillMode=mixed` / `TimeoutStopSec=30`；`NoNewPrivileges` / `PrivateTmp` |
| `34-前端应用训练系统/deploy/worker-launcher.env.example` | 上表环境变量模板；不含任何密钥（凭据由宿主注入） |

```bash
sudo cp deploy/dreambuddy-worker-launcher.service /etc/systemd/system/
sudo install -m 600 -o dreambuddy -g dreambuddy deploy/worker-launcher.env.example /etc/dreambuddy/worker-launcher.env
sudo systemctl daemon-reload && sudo systemctl enable --now dreambuddy-worker-launcher
journalctl -u dreambuddy-worker-launcher -f
```

**验证（2026-11-13）**

- 新增 `tests/test_worker_launcher_metrics.py`（4 例）+ `tests/test_worker_launcher_cli.py`（6 例，含 `flock` 双开拒绝）；D2+D3 回归 **71 passed**；`ruff check` 全通过。
- CLI 端到端冒烟（真实 47 registry 花名册 + `noop` executor）：

```
{"ok": true, "problems": [], "root": "/tmp/d3cli-smoke"}
{"consumed": 1, "executed": 1, "done": 1, "receipts": 1, "pass_offset": 69, "in_flight_peak": 1, "errors": []}
{"metrics": {"passes": 1, "counters": {...}, "success_rate": 1.0}, "claims": {"total": 0, "by_state": {}}}
```

**仍未覆盖（需外部条件）**：真实额度下的 P95 时延与 token 成本、A5「8 Worker 场景 MCP 实际连接计数」、systemd 重启恢复联调（需云端）、影子运行一周。

**W4 验收（2026-11-13，五维证据）**

| 维度 | 结果 | 证据 |
|---|---|---|
| 症状/功能复测 | ✅ | 真实 dsh 批：`host_pid=26786`，ACC-1/ACC-2 两个不同 `session_id` 均 `done`，各 1662ms（单运行时多会话） |
| 日志/输出证据 | ✅ | `metrics.json` 非默认值（`passes=2`、`role_rejections=1`、`success_rate=0.5`）；CLI `once/status` JSON |
| 回归 | ✅ | 全量 `pytest tests` **1132 collected / exit 0**；`ruff check core tools tests` exit 0 |
| 影响面 | ✅ | 12 个文件（5 改 7 增），全部在 `34-前端应用训练系统/{core,tools,tests,deploy}` 与本文；未触碰 `router_loop.py` |
| 边界 | ✅ | 坏 metrics FAIL-OPEN、`flock` 双开退出 3、坏 inbox 行 `bad_lines=1` 且继续消费、角色越权 `failed(manual)` |

证据包：`acceptance_bundles/20261113_d3_w4_closeout/`（`repro_after.log` / `cli_chain.log` / `boundary.log` / `test.log` / `fix.diff` / `acceptance_report.md`）。

## §5 关键决策（ADR）

| # | 决策 | 理由 |
|---|---|---|
| ADR-W1 | 拉起器独立于 `server.py` 主循环 | 避免与 D2 共享 IPC 的退出钩子抢生命周期（同 D2 不新增后台线程的结论） |
| ADR-W2 | 只通过 inbox/receipts 文件交互，不直写 Ticket | 保持 L0 单一事实源与 Router 权威 |
| ADR-W3 | at-least-once + 回执幂等 | 崩溃恢复优先于严格 exactly-once；R16 已提供去重 |
| ADR-W4 | 角色白名单在拉起器侧二次校验 | 纵深防御，不能只依赖 Router 花名册 |
| ADR-W5 | 目标形态单运行时多会话（方案 B） | 满足 G2 连接数=域数 |
| ADR-W6 | 默认关闭（`enableWorkerLauncher=false`） | 与 D2 的开关化/H2 一致，先影子后实盘 |
| ADR-W7 | 生产部署固定为云端 systemd | 复用现有运维设施，`Restart=on-failure` + journald 覆盖恢复与观测 |
| ADR-W8 | `failed` 分 `retryable` / `manual` 两类 | 可自动恢复的不占用人工；重试耗尽/权限错误才转人工 |
| ADR-W9 | 心跳租约与任务超时分离 | liveness（30s）与执行预算（300s/30min）解耦，避免误杀长任务 |

## §6 里程碑

| 阶段 | 内容 | 退出条件 |
|---|---|---|
| W0 契约冻结 | inbox/receipt schema v0.2（含 `failure_class`）、claim 状态机、开关命名；扩展 D2 `worker_receipts` 映射（retryable→paused/waiting_job，manual→waitsForPerson，旧回执按 manual 兼容）；L0 归属澄清 + StorePort 适配（§4.10） | ✅ 已完成（2026-11-13）：消费端映射 + 4 类输入单测；`TicketStoreAdapter` + 8 项单测；D2 回归 240 项全绿 |
| W1 单角色 MVP | `research` 单 Worker、单进程（sandbox 方案 A 兜底）、done/failed 回执 | ✅ 已完成（2026-11-13）：`core/worker_launcher.py` + 9 项单测；端到端 1 任务闭环，Router 下一轮 `ended`；D2+D3 回归 303 项全绿 |
| W2 恢复与超时 | offset 恢复、心跳/lease、退避重试、两类失败回执、坏行 FAIL-OPEN | ✅ 已完成（2026-11-13）：heartbeat 10s / lease 30s、退避 5/20/60s、300s 超时、30min 硬上限；四类故障注入（kill -9 现场 / 超时 / 心跳丢失 / 坏行）单测通过；D2+D3 回归 309 项全绿 |
| W3 多角色 + G2 | 8 角色白名单、单运行时多会话（若 spike 通过） | ✅ 部分完成（2026-11-13）：`core/worker_roles.py` 花名册自检 + 越权矩阵（5 类输入）+ `g2_summary` 静态聚合；拉起器二次校验接入；相关套件 61 项全绿。**未含**：真实连接计数（A5 实跑口径）；A7 已在 W4 补测通过（§4.14/§4.15） |
| W4 收口 | 可观测、运维 CLI、systemd unit 与云端部署、影子运行一周、文档与认知闭环 | 方案 B 已下沉（§4.15）；可观测 + 运维 CLI + systemd unit 已就位（§4.16，71 passed）；剩余：真实额度下时延/成本、A5 实跑连接计数、云端 systemd 重启恢复联调、影子运行一周 |

## §7 验收标准

| # | 标准 | 验证方式 |
|---|---|---|
| A1 | 每条 assignment 恰好一次领取 | 100 轮模拟，claim 表与 inbox 对账 |
| A2 | `done/failed` 回执字段完整 | ✅ 2026-11-13：`test_worker_launcher.py` 断言 `receipt_id/attempts/failure_class/worker_id/trace_id/at` |
| A3 | kill -9 后恢复 | ✅ 模拟验证（租约过期 + offset 已推进的崩溃现场 → 回收后续接 attempt 完成）；真实进程 kill 联调留 W4 |
| A4 | 越权角色/工具被拒 | ✅ 2026-11-13：未知 worker_id / role / 非白名单 tools → `failed(manual, role_violation)`，executor 零调用（W1 基础项 + W3 工具级子集校验） |
| A5 | G2 连接数 | ✅ 静态口径（2026-11-13）：`g2_summary()` 显示角色网关 profile 共用单一入口，连接数不随 Worker 数增长；**实跑连接计数**（8 Worker 场景 =3）待 A7 后补测，计数所需指标已就绪（§4.16 `in_flight_peak`/`passes`） |
| A6 | 零 Router 改动 | `git diff` 不触碰 `router_loop.py` 的八步语义 |
| A7 | 单进程并发 ≥2 会话 | ✅ 2026-11-13 实测（§4.14）：单 pid 21057 内 2 个 `origin=subagent/depth=1` 子会话并发（stub inflight 峰值 2），workflow 返回 2 个 agent 结果。LLM 层为 stub（quota 不可用），运行时全真实 |

## §8 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| DSH 0.1.5 不支持单进程多会话 | 方案 B 不可行 | S0 spike 前置；失败则方案 A **仅限 sandbox**，生产上线 blocked |
| at-least-once 导致重复执行 | 副作用重复 | 回执幂等 + mandate 幂等键 + 只读角色为主 |
| 长任务阻塞单 Worker | 吞吐下降 | 每角色池化（roster 多 worker_id）+ lease |
| 文件 offset 与人工改文件竞争 | 漏读/重读 | flock + 行级幂等（跳过已回执 ticket） |
| 拉起器误写 Ticket | 破坏 SSoT | 代码层禁写 `dsh_tickets.jsonl`，CI 静态检查 |
| 回执时钟漂移 | 排序异常 | 统一 ISO8601 + 本地单调时钟差 |

## §9 决策记录（Q1-Q6 已决）

| # | 议题 | 决策 | 最佳实践依据 |
|---|---|---|---|
| D1 | 运行时形态 | 目标 B（单运行时多会话）；S0 spike 2 天；A 仅 sandbox，生产必须 B | 不把生产架构建立在未验证能力上；用时间盒 spike 去风险，而非主观取舍 |
| D2 | 并发度 | 并发 = `routerLoopWorkers` 花名册，默认每角色 1，全局 ≤8、单角色 ≤2；首版不自动扩缩 | 固定池 + 队列可预测、可压测、成本可控；扩容由指标驱动而非预先设计 |
| D3 | 超时与重试 | 心跳 10s / 租约 30s；任务超时 300s（角色可覆盖）；硬上限 30min；最多 3 次，退避 5/20/60s + ±20% jitter | liveness 与执行预算分离；指数退避 + 抖动避免惊群；有限重试防雪崩 |
| D4 | 长任务 | 允许心跳续租，但受 `max_task_duration=30min` 硬约束；超限转人工 | 租约续期是分布式任务标准做法；硬上限防止无限占用 |
| D5 | `failed` 语义 | 分 `retryable`（→`paused+waiting_job`）与 `manual`（→`waitsForPerson`）；回执带 `failure_class/attempts/next_retry_at` | 可恢复错误自动处理，不可恢复才占人工；错误分类是可观测与自动化的前提 |
| D6 | 部署形态 | 云端 Linux + systemd（`Restart=on-failure` + journald + 专用用户 + flock 单实例）；本地 macOS 仅开发 | 复用现有基础设施，最小运维面；崩溃自动拉起，日志统一进 journald |

### 9.1 决策带来的契约变更（W0 执行 · 已完成）

- `worker_receipts` 扩展：`retryable → paused(waiting_job)`、`manual → waitsForPerson`；缺省 `failure_class` 的旧回执按 `manual` 处理。→ ✅ `core/worker_receipts.py::_resolve_target`
- `ticket_state` 不新增状态，仅使用既有 `paused/waiting_job` 与 `waitsForPerson`（迁移表无需改动）。→ ✅ 未改 `ticket_state.py`
- 拉起器写入的 `failed` 必须是「终态回执」；中间重试只记本地 attempt，不写 Router，避免状态抖动。→ 约束保留，W1 实现
- L0 归属冻结（§4.10）：`dsh_*` 文件落点 `34-前端应用训练系统/` 只是路径约定，逻辑归属通用 L0。→ ✅ 文档澄清
- 新增 `TicketStoreAdapter`（`dreambuddy_l0/adapters/ticket.py`）实现 `StorePort`，`append/read_all` 保持不动。→ ✅ 8 项单测
- **幂等键纠偏**：`idempotency_key` 不用 `ticket_id`（会吞掉 latest-wins 的状态更新），改内容哈希 / 显式键持久化。→ ✅ 单测覆盖
- 单测：`test_router_loop.py` 回执映射 4 例 + `test_ticket_store_adapter.py` 8 例；D2 回归 240 项全绿。

### 9.2 遗留待验证

1. ~~S0 spike：DSH 0.1.5-rc.3 单进程多会话能力~~ → **已通过（能力级，见 §10）**；仅剩 2 路并发实跑待补测（受 LLM 余额限制）。
2. 云端 systemd 环境：专用用户、只读挂载、`EnvironmentFile` 路径需运维确认。
3. 花名册动态变更（增删 worker_id）时的平滑生效策略。

---

## §10 S0 spike 结果（2026-11-12）

**结论：PASS（能力级）。单进程多会话在 DSH 0.1.5-rc.3 原生支持，D1 方案 B 可行，W1 可开工。**

### 10.1 运行时证据（sandbox profile，同进程探针）

| 观测项 | 结果 |
|---|---|
| 进程 | 单进程（`pid` 唯一），provider 与探针同 pid |
| subagent providers | `spawn`、`fork` 均已注册（boot settle 后 `providers.size=2`） |
| spawn 能力位 | `toolFilter / agentOptions / persona / depthLimit / outputSchema` 全部 `true` |
| workflow 引擎 | 已挂载，`provider=spawn`、`maxConcurrentAgents=0` → 解析为 `min(16, CPU并行度-2)`；本机 8 核 → **6 路并发** |
| 工具过滤 | headless 已配置 `toolFilter.allow/deny`（只读子集），且「只缩减不扩展」 |

### 10.2 代码级证据

- `dsh-subagent-spawn-in-process`：每个子会话是 **同一 cordis context 上的 fresh child Agent**（自有 session / system prompt / 零父上下文），复用 agent factory、LLM 与工具服务 → 壳连接可共享（满足 G2）。
- `dsh-workflow-worker-thread`：`agent()` 调用经 `ctx.subagents.start(provider, …)` 创建子会话，并有显式 `maxConcurrentAgents` 上限 → DSH 自身已在生产组合中使用「单进程多会话并发」。
- `dsh-tool-subagent`：`provider=spawn`、`backgroundMode=continuable`，支持后台持续会话。

### 10.3 未能验证（受环境限制）

- 两路 child agent 的**实际并发执行**：DeepSeek 账户 `QUOTA: Insufficient Balance`，端到端 LLM 回合无法完成。
- 影响评估：不改变可行性结论（能力、注册、并发上限均已证实）；列入 W2 回归项 A7，余额恢复后补测。

### 10.4 W1 必须遵守的工程约束（spike 新发现）

1. **provider 注册发生在 boot settle 之后**：探针在 `apply()` 内立即读取为 0，500ms 后为 2。**禁止在插件 `apply` 内直接 `start()`**；拉起器必须等运行时 ready 后再消费 inbox。
2. **单进程是并发边界**：`process-local residency` 明确不做跨进程协调；与 D6「单实例 + flock」一致，多实例必须先分片。
3. `toolFilter` 是角色白名单的落点（只缩减不扩展），拉起器侧仍保留二次校验（ADR-W4）。

### 10.5 对决策的影响

- D1：维持方案 B，**无需生产降级**。
- W1：直接按 B 实现；A 仅保留为 sandbox 故障演练的对照。
- 新增验收项 **A7**：同一 pid 内并发 ≥2 个 child session 完成各自 mandate（quota 恢复后执行）。

### 10.6 复现步骤

```bash
# 1) 在 sandbox profile 放探针包（验证后删除）
#    profiles/sandbox/node_modules/probe-s0-subagent/lib/index.js
#    inject = ["subagents","workflowEngine"]；apply 内打印 providers/caps/config
# 2) patch 追加 insert 条目后启动
DSH_HOME=<bridge>/.dsh-home dsh --profile sandbox probe
# 3) 期望看到 PROBE_S0_LATE：providers=[spawn,fork]、caps 五项 true、
#    workflowConfig.maxConcurrentAgents=0（运行时解析为 6）
```

## §11 依赖与参考

- [DESIGN-P0-D2-ROUTER-LOOP-v0.1](DESIGN-P0-D2-ROUTER-LOOP-v0.1.md)：投递/回执契约、幂等闸、依赖闸。
- [router_loop.py](../../../34-前端应用训练系统/core/router_loop.py)：`JsonlInboxSink`、八步顺序。
- [worker_receipts.py](../../../34-前端应用训练系统/core/worker_receipts.py)：回执映射与去重（R14/R16）。
- [ticket_state.py](../../../34-前端应用训练系统/core/ticket_state.py)：四态迁移表。
- [mcp_capabilities.yaml](../../../47-MCP管理系统/registry/mcp_capabilities.yaml#L540)：8 角色能力集。
- [SPEC-53](../../../53-DSH插件模块/SPEC-53-DSH插件生态接入总规范.md)（R14-R16）：本轮闭环与联通性测试结论。

---

## 附：落地目录（W1-W4 实际实现）

```
34-前端应用训练系统/
  core/
    worker_launcher.py          # 主循环 / offset / claim / 心跳 / 批路径
    worker_launcher_metrics.py  # W4 指标聚合（metrics.json）
    worker_launcher_cli.py      # W4 运维 CLI（preflight/once/run/status）
    worker_roles.py             # 8 角色白名单 + 越权矩阵 + G2 聚合
    inproc_session_executor.py  # 方案 B：单运行时多会话执行器
  tools/
    dsh_session_host/           # DSH 宿主插件（host.patch.yml + lib/index.js）
    a7_probe/                   # A7 探针（stub LLM 插件）
  deploy/
    dreambuddy-worker-launcher.service
    worker-launcher.env.example
  tests/
    test_worker_launcher.py
    test_worker_launcher_metrics.py
    test_worker_launcher_cli.py
    test_worker_roles.py
    test_inproc_session_executor.py
```

## 附：systemd unit（已落地，W4）

唯一真源：`34-前端应用训练系统/deploy/dreambuddy-worker-launcher.service`（本文不重复维护副本）。关键字段：

```ini
WorkingDirectory=/opt/dreambuddy/34-前端应用训练系统
EnvironmentFile=-/etc/dreambuddy/worker-launcher.env
ExecStartPre=/opt/dreambuddy/.venv/bin/python -m core.worker_launcher_cli preflight
ExecStart=/opt/dreambuddy/.venv/bin/python -m core.worker_launcher_cli run
Restart=on-failure
```

```bash
sudo cp deploy/dreambuddy-worker-launcher.service /etc/systemd/system/
sudo install -m 600 -o dreambuddy -g dreambuddy deploy/worker-launcher.env.example /etc/dreambuddy/worker-launcher.env
sudo systemctl daemon-reload
sudo systemctl enable --now dreambuddy-worker-launcher
journalctl -u dreambuddy-worker-launcher -f
```

---
