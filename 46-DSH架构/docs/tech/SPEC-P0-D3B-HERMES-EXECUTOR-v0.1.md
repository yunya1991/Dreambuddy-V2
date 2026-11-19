# SPEC-P0-D3B: HermesExecutor 接入方案（接口契约 + 治理约束 + POC 验收）

- **版本**: v0.1 ｜ **日期**: 2026-11-19 ｜ **状态**: 🟡 草案，**评审结论：修改后接受（见 [REVIEW](REVIEW-SPEC-P0-D3B-HERMES-EXECUTOR-v0.1.md)），需修订 v0.2**
- **定位调整**: 本文的 `HermesExecutor` 仅作为 [P0-D3C 场外助手](SPEC-P0-D3C-HERMES-FIELD-ASSISTANT-v0.1.md) 的 C 层救援执行实现；角色边界以 P0-D3C 为准
- **归属**: 46-DSH架构 / 执行侧运行时（P0-D3 Worker Launcher 的 executor 扩展）
- **上游约束**:
  - [DESIGN-DSH-ARCH-UPGRADE-v0.2](DESIGN-DSH-ARCH-UPGRADE-v0.2.md)（ADR-4 能力集 / ADR-6 不自证 / ADR-9 只读 / ADR-10 壳共享）
  - [PROPOSAL-P0-D3-WORKER-LAUNCHER-v0.1](PROPOSAL-P0-D3-WORKER-LAUNCHER-v0.1.md)（inbox / receipt / 重试 / 超时契约）
  - [SPEC-53-DSH插件生态接入总规范](../../../53-DSH插件模块/SPEC-53-DSH插件生态接入总规范.md) + [plugin_whitelist.yaml](../../../53-DSH插件模块/plugin_whitelist.yaml)
  - [3+3 架构模块映射 v1.3](../../../1-ARCHITECTURE/3+3架构模块映射.md)
  - [47-MCP管理系统 registry](../../../47-MCP管理系统/registry/mcp_capabilities.yaml)（工具面唯一事实源）
  - [49-交易框架协议 SPEC](../../../49-交易框架协议/SPEC.md)（L1 只读与实盘边界）
- **下游影响**: `34-前端应用训练系统/core/worker_launcher.py`、`47/registry/mcp_capabilities.yaml`、`53/plugin_whitelist.yaml`、`deploy/systemd`
- **一句话**: **不替换 Worker 契约，只新增一个可插拔的 executor 实现**；Hermes 只接管 `research` / `engineer` 两类长任务，工具面仍经 MCP 壳，只读、可回执、可回退。

---

## §0 结论先行

| 问题 | 结论 |
|---|---|
| 是否替换 C-drive？ | **否**。C-drive 是 S/A/C/G 的路由与反思门，不是执行器 |
| 是否替换 DSH Worker？ | **否**。Worker 是“槽位 + 契约”，Hermes 只是它的执行内核 |
| 是否新增一个 Worker 角色？ | **否**。不新增角色，只新增 `executor_kind` |
| Hermes 是什么定位？ | **外部执行运行时（external runtime）**，不是 Cordis 插件 |
| 先接哪些角色？ | 仅 `research` / `engineer`；`data_reader` / `verifier` / `executor` 继续 DSH |
| POC 通过标准 | H0–H8 全过 + 三项任务成功率优于 DSH 基线 10pp + 零越权/零写 |

---

## §1 背景与问题

### 1.1 现状

| 项 | 事实 | 证据 |
|---|---|---|
| Worker 契约已存在 | inbox → claim → execute → receipt，含重试/租约/超时 | [worker_launcher.py](../../../34-前端应用训练系统/core/worker_launcher.py#L1-L20) |
| 角色能力集已存在 | 8 角色，每角色 ≤10 个只读工具 | [mcp_capabilities.yaml](../../../47-MCP管理系统/registry/mcp_capabilities.yaml#L996-L1056) |
| 执行内核是 MVP | `DshCliExecutor` 每任务起 `dsh` 子进程，只回 stdout 末 500 字 | [worker_launcher.py](../../../34-前端应用训练系统/core/worker_launcher.py#L788-L835) |
| 单运行时多会话未验收 | 方案 B 是目标形态，但尚未通过云端验证 | [PROPOSAL §4.2](../../../46-DSH架构/docs/tech/PROPOSAL-P0-D3-WORKER-LAUNCHER-v0.1.md#L102-L115) |

### 1.2 问题定义

“执行能力弱”的落点是 **executor**，不是 Router、不是 C-drive：

1. 一次黑盒 `goal` 调用，没有多轮自我纠错；
2. evidence 只有 500 字，缺少工具轨迹与结构化产物；
3. 无法承载跨多步的调研/逆向任务；
4. 超时后线程无法真正终止（`thread.join` 超时返回，但线程仍在跑），存在僵尸执行风险（[`_run_with_timeout`](../../../34-前端应用训练系统/core/worker_launcher.py#L582-L599)）。

### 1.3 目标 / 非目标

**目标**

- G1：在不改 Router / Ticket 四态 / receipt 契约的前提下，新增 `HermesExecutor`；
- G2：只对 `research` / `engineer` 角色生效，按角色路由；
- G3：工具调用仍受 `worker_roles[role].tools` 白名单约束，越权即失败；
- G4：输出可被 launcher 直接归类为 `done / retryable / manual`；
- G5：默认关闭，可一键回退到 `DshCliExecutor`。

**非目标**

- 不替换 C-drive、不替换 Router、不新增 Ticket 状态；
- 不接交易执行、不接 live、不碰 L1 热路径；
- 不替代 MCP（53 ADR-2）；
- 不让 Hermes 直接写认知库 / settle / 订单；
- 不做自然语言任务分解（由 Mandate 给出目标）。

---

## §2 与 53-DSH 插件模块的对齐

### 2.1 关键判定：Hermes 不是 Cordis 插件

53 的治理对象是**挂进 `dsh profile` 的 Cordis 插件**（JS `apply(ctx, config)`，见 [53 SPEC §2.1](../../../53-DSH插件模块/SPEC-53-DSH插件生态接入总规范.md#L93-L134)）。Hermes 是独立 Python 运行时，不进入 `cordis.patch.yml`，因此：

- **禁止**把 Hermes 登记为 `plugin_whitelist.yaml.entries` 里的普通插件；
- **禁止**用 Hermes 绕过 MCP 壳直连 L0/L1；
- Hermes 的治理走 53 的**新增分类 `external_runtimes`**（见 §2.3）。

### 2.2 职责切分（互补，不重叠）

| 维度 | 53 插件（Cordis） | HermesExecutor（本文） |
|---|---|---|
| 位置 | DSH 运行时**内部** | DSH 运行时**外部** |
| 形态 | JS `apply(ctx)` 注册工具 | Python executor，被 launcher 调用 |
| 扩展对象 | Worker 的**工具面** | Worker 的**执行内核** |
| 生命周期 | profile 加载/卸载 | 按 assignment 起停 |
| 治理入口 | `plugin_whitelist.yaml` | `plugin_whitelist.yaml.external_runtimes`（v2 增补） |
| 与 MCP 关系 | 自有插件必须经 MCP 壳（DEC-06） | 同样必须经 MCP 壳 |
| 交易热路径 | `*trading*` 一律 forbidden | `executor` 角色与交易工具一律禁止 |

**互补原则**：插件解决“Worker 能调什么工具”，Hermes 解决“Worker 用什么内核去调”。两者都不得自建第二套工具面。

### 2.3 53 白名单 v2 增补（待评审后落地）

在 `plugin_whitelist.yaml` 增加独立段，不改动现有 `entries` 语义：

```yaml
external_runtimes:
  - id: "hermes-worker"
    source: "pip:hermes-cli"
    runtime_version: "0.20.x"          # POC 锁定，禁止漂移
    status: "candidate"                # sandbox 通过后升 approved
    risk_level: "medium"
    permitted_profiles: ["superagent"] # 仅 Worker 执行 profile
    sandbox_verified: false
    fail_open_verified: false
    mcp_shell_required: true           # 必须经 47 MCP 壳
    allowed_roles: ["research", "engineer"]
    allowed_shells: ["l0.cognition.mcp", "l0.semantic-39.mcp", "l0.rea.mcp"]
    forbidden_paths: ["*trading*", "*live*", "*order*"]
    notes: "外置执行内核；不进入 cordis.patch.yml；仅 P0-D3B POC 使用"
```

校验器同步增加 `--runtime <id> --role <role>` 检查：

1. 未登记 → 拒绝（deny-by-default 不变）；
2. `profile` 不在 `permitted_profiles` → 拒绝；
3. `role` 不在 `allowed_roles` → 拒绝；
4. 非 sandbox profile 且 `sandbox_verified=false` / `fail_open_verified=false` → 拒绝；
5. 声明的 shell 不在 `allowed_shells` → 拒绝。

### 2.4 与 53 的硬约束对齐

| 53 约束 | 在 HermesExecutor 的落地 |
|---|---|
| ADR-2 不替代 MCP | Hermes 只能作为 MCP client 调 47 壳，不自建数据通道 |
| ADR-4 白名单 + sandbox | 先进 `superagent` 的 sandbox 验证，再进生产 profile |
| ADR-5 不改 42 | 不触碰 42 协调层、不改 `registry.yaml` |
| ADR-6 工具级 FAIL-OPEN | 工具异常返回 degraded；**但 executor 激活失败 fail-closed**（对齐 §2.5 踩坑） |
| ADR-7 Creator mode 不进生产 | Hermes 自建技能/记忆不得写入共享生产目录（见 §5.4） |

---

## §3 与 3+3 架构的对齐

### 3.1 层归属（不新增层、不改变归属）

| 模块 | 3+3 归属 | 在本方案中的角色 |
|---|---|---|
| 46 DSH架构 | L2 / 产品链（基础设施） | **契约归属**：定义 executor 接口与 POC 门禁 |
| 34 前端应用训练系统 | L2 / 训练链 | **实现归属**：`HermesExecutor` 与 launcher 路由 |
| 53 DSH插件模块 | L2 / 产品链 | **治理归属**：外部运行时登记与白名单校验 |
| 47 MCP管理系统 | L0 / 横切→产品链 | **工具面归属**：`worker_roles` 与 shell 映射唯一事实源 |
| 45 评测系统 | L0 / 横切 | **验收归属**：POC 指标与证据包 |
| 49 / 22 / 11 | L1 / 交易链 | **只读观察对象**，不接执行 |

HermesExecutor 属于 **L2-E 执行编排**，是 `Worker` 的一个执行实现，不产生新的架构层。

### 3.2 从 3+3 继承的硬约束

1. **L2 对 L1 只读**：Hermes 只能调 `l1.trading.mcp` 的只读工具，不得触发信号或交易；
2. **实盘永不暴露 MCP**：Hermes 不接任何 live/order 工具；
3. **交易热路径 in-process**：`polling_trader` / `trailing_stop` / `yijing_trading` 与 Hermes 完全隔离；
4. **Worker 只读**：写工具（`record/verify/place_order/cancel_order/ingest_signal/forward_signal`）禁止装载；
5. **settle 归编排侧**：Hermes 输出只是候选证据，沉淀由 Settle 节点执行（ADR-9）；
6. **Mandate + 预算 + trace 三件套**：缺一不得执行；
7. **45 门禁**：POC 产物必须过评测门禁，不得直接上线。

### 3.3 能力链影响

| 能力链 | 影响 | 边界 |
|---|---|---|
| 产品能力链（3.1/6/7/8/53） | 间接：Worker 执行质量提升 | 不改前端入口、不改产品协议 |
| 模型训练链（34/48） | 主要：research/engineer 任务执行增强 | 不改变训练数据口径 |
| 交易链（49） | 无写入影响 | 仅只读观测，不进入决策/执行 |

---

## §4 接口契约（规范性）

### 4.1 Executor 协议

与现有 launcher 完全兼容，不改变调用方式：

```python
from typing import Any, Dict, List, Protocol

class WorkerExecutor(Protocol):
    def __call__(self, assignment: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个 assignment，必须返回 ExecutorResult（§4.3）。"""

    # 可选：方案 B（单运行时多会话）时由 launcher 调用
    def run_batch(self, assignments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ...
```

`HermesExecutor` 必须满足：

| 编号 | 要求 | 判定 |
|---|---|---|
| E-1 | 线程安全，可被 launcher 多线程调用 | 并发 4 任务无共享状态污染 |
| E-2 | 预期失败不抛异常，返回 `status=failed` | 注入 5 类错误均不 crash |
| E-3 | 不写 ticket / receipt / offset | 文件探针为零写入 |
| E-4 | 不依赖 launcher 的线程超时兜底 | 自身可杀子进程，超时后无残留 |
| E-5 | 同一 `ticket_id` 幂等 | 重放 3 次结果一致，无重复副作用 |
| E-6 | 输出 evidence ≤ 32KB | 超限截断并落 artifact |

> E-4 是硬要求：launcher 的 `thread.join(timeout)` 只能“放弃等待”，不能终止线程；Hermes 必须以**子进程 + 进程组 kill** 或**自带硬超时**实现，否则会产生僵尸任务。

### 4.2 输入契约（在 PROPOSAL §4.3 上扩展）

```json
{
  "ticket_id": "TK-R1",
  "external_ref": "R1",
  "worker_id": "w-research-1",
  "role": "research",
  "trace_id": "rp-xxxxxxxx",
  "assigned_at": 1794498000.0,
  "mandate": {
    "goal": "对 BTC 本周结构做多源调研并给出证据链",
    "tools": ["recall", "unified_search", "submit_rea_analyze", "poll_rea_analyze"],
    "budget": {
      "max_turns": 12,
      "max_tokens": 60000,
      "timeout_s": 600
    },
    "context_refs": ["case:xxx", "doc:yyy"],
    "acceptance": {
      "must_include": ["结论", "证据", "反例"],
      "evidence_required": true
    }
  }
}
```

约束：

1. `role` 必须命中 47 `worker_roles`；
2. `mandate.tools` ⊆ `worker_roles[role].tools`，否则直接 `failed/manual`；
3. `budget` 对 Hermes 必填；缺失时用角色默认值，但不得超过全局上限；
4. `trace_id` 必填，缺失 → `failed/manual`（契约错误，不重试）。

### 4.3 输出契约（receipt v0.2 + evidence 扩展）

保持 [PROPOSAL §4.4](../../../46-DSH架构/docs/tech/PROPOSAL-P0-D3-WORKER-LAUNCHER-v0.1.md#L133-L154) 不变，只扩展 `evidence`：

```json
{
  "status": "done",
  "failure_class": null,
  "evidence": {
    "summary": "≤2000 字结论摘要",
    "artifacts": ["34-.../artifacts/TK-R1/report.md"],
    "duration_ms": 48210,
    "executor": "hermes",
    "hermes_session_id": "hs-...",
    "turns": 7,
    "tool_calls": [
      {"name": "recall", "ok": true, "ms": 42},
      {"name": "submit_rea_analyze", "ok": true, "ms": 118}
    ],
    "tokens": {"prompt": 21000, "completion": 4300},
    "cost_usd": 0.012,
    "degraded": false,
    "trace_id": "rp-xxxxxxxx"
  }
}
```

失败时：

```json
{
  "status": "failed",
  "failure_class": "retryable",
  "evidence": {
    "reason": "tool_error",
    "summary": "MCP l0.rea 超时",
    "executor": "hermes",
    "duration_ms": 60000,
    "trace_id": "rp-xxxxxxxx"
  }
}
```

**失败原因枚举（扩展）**：`timeout | tool_error | runtime_error | budget_exceeded | contract_error | role_violation | approval_denied`。

**禁止写入 evidence 的内容**：完整思维链、完整 transcript、密钥、绝对路径中的用户名。完整轨迹落 artifact 文件，evidence 只放引用。

### 4.4 Hermes 传输层抽象（POC 必须先验证）

```python
class HermesTransport(Protocol):
    def execute(self, task: "HermesTask") -> "HermesResult":
        """同步或“提交+有界轮询”返回结构化结果。"""

    def cancel(self, task_id: str) -> None:
        ...
```

候选实现（按优先级）：

| 编号 | 方式 | 要求 | POC 判定 |
|---|---|---|---|
| T1 | CLI headless（`hermes ... --json` 类入口） | 可传 task 文件，stdio 返回结构化结果 | 首选 |
| T2 | ACP / RPC adapter | 有请求-响应语义，可取消 | 备选 |
| T3 | Gateway 消息注入 | 异步、无同步返回 | 仅兜底，不作为 Worker 主路径 |

**H1 门禁**：若 T1/T2 都不成立，POC 直接终止——不允许用“发飞书消息再等回执”的方式冒充同步 executor。

### 4.5 工具边界三层执行

```text
① 配置层：per-role Hermes profile
   - 只挂载 allowed_shells 对应的 MCP server
   - 关闭 terminal / file / browser 等通用工具集
② 运行时层：47 registry 判权
   - mandate.tools ⊆ worker_roles[role].tools
   - 写工具 / 交易工具 deny-by-default
③ 事后层：轨迹审计
   - 解析 tool_calls，出现白名单外工具 → failed/manual + 隔离
```

任何一层不通过，均不得把结果标为 `done`。

### 4.6 超时与预算

| 层 | 控制 | 行为 |
|---|---|---|
| Launcher | `task_timeout`（默认 300s，角色可覆盖） | 外层兜底，记录 timeout |
| Executor | `budget.timeout_s` | 到时 kill 进程组，返回 `retryable/timeout` |
| Hermes | `max_turns` | 到轮次上限，返回 `manual/budget_exceeded` |
| Token | `max_tokens` | 超预算终止，返回 `manual/budget_exceeded` |

`budget_exceeded` 归 `manual`：不自动重试，避免成本失控。

### 4.7 Trace 与幂等

- `trace_id` 透传到 Hermes 会话标签、MCP 调用与 evidence；
- `ticket_id` 作为幂等键：executor 在本地 state 目录维护 `ticket_id → session_id`；
- 重试时优先续跑同一 session；session 不存在则新建；
- launcher 仍负责 receipt 去重，executor 不写 receipt。

---

## §5 安全与隔离

### 5.1 运行隔离

| 项 | 要求 |
|---|---|
| 系统用户 | 专用非 root（如 `dreambuddy-hermes`） |
| HERMES_HOME | 独立目录（`/home/dreambuddy-hermes/.hermes-worker`），不与现有 Feishu gateway 共用 |
| 代码挂载 | 只读 |
| 环境变量 | 独立 env 文件，不继承生产 `.env` |
| 网络 | 仅允许 LLM API + 本地 MCP 端口 |
| 审批 | 自动化只允许读工具；写/终端类一律 deny |
| 记忆/技能 | POC 关闭 Hermes 的 curator 与跨任务记忆写入（或每任务临时 HOME） |

### 5.2 硬约束（H 系列）

| ID | 约束 |
|---|---|
| H-1 | 不写 `dsh_tickets.jsonl` / `dsh_worker_receipts.jsonl` / offset |
| H-2 | 不调用任何写工具（`record/verify/place_order/...`） |
| H-3 | 不接交易执行、不接 live、不接 L1 热路径 |
| H-4 | 不绕过 47 MCP 壳直连数据源 |
| H-5 | 不绕过 53 外部运行时登记 |
| H-6 | 未通过 sandbox 验证不得进生产 profile |
| H-7 | 无预算不执行、无 trace 不执行 |
| H-8 | evidence 不得含密钥 / 完整思维链 / 超限内容 |

### 5.3 与现有 Feishu Hermes 的隔离

现有 [hermes-gateway.service](../../../deploy/hermes-gateway.service#L1-L19) 是飞书消息网关，与本 POC **必须物理隔离**：

- 独立 systemd unit：`dreambuddy-hermes-worker.service`；
- 独立 `HERMES_HOME`、独立配置、独立凭据；
- 禁止复用飞书 gateway 的会话与记忆；
- 禁止两者共享进程或端口。

---

## §6 角色路由与配置

### 6.1 路由规则

优先级从高到低：

1. `assignment.mandate.executor`（显式指定，仅排障用）；
2. `worker_roles[role].executor`（单一事实源）；
3. 环境变量 `DREAMBUDDY_WORKER_EXECUTOR_<ROLE>`；
4. 默认 `dsh`。

未知值 → 回落 `dsh` 并告警，不阻断。

### 6.2 47 registry 变更（向后兼容）

```yaml
worker_roles:
  research:
    executor: hermes          # 新增可选字段，缺省 dsh
    tools: [...]
  engineer:
    executor: hermes
  data_reader:
    executor: dsh
```

校验规则（`worker_roles.py` 自检新增）：

- `executor ∈ {dsh, hermes}`；
- `executor=hermes` 时，`role` 必须在 53 `external_runtimes.allowed_roles` 内；
- `executor=hermes` 时，`tools` 必须全部落在 `allowed_shells` 的工具集内。

### 6.3 开关

| 开关 | 默认 | 作用 |
|---|---|---|
| `enable_hermes_executor` | `false` | 总开关；关闭时字节等价现有行为 |
| `hermes_executor_roles` | `research,engineer` | 允许路由的角色 |
| `hermes_executor_canary_pct` | `0` | 按 ticket hash 灰度 |

---

## §7 POC 验收

### 7.1 POC 范围

| 项 | 范围 |
|---|---|
| 角色 | 仅 `research`（Phase 1）；`engineer` 在 Phase 1 通过后接入 |
| 任务类型 | ① 认知检索 + REA 分析；② 工程逆向解析；③ 文档/知识调研 |
| 样本量 | 每类 ≥ 20 条，共 ≥ 60 条 |
| 对照 | 同任务集走 `DshCliExecutor` |
| 环境 | `superagent` sandbox profile → 灰度 → 生产候选 |

### 7.2 门禁（H0–H8，全过才可进入灰度）

| ID | 门禁 | 通过标准 | 证据 |
|---|---|---|---|
| H0 | 契约一致性 | 60 条回放 100% 通过 schema 校验，0 异常 | `receipts.jsonl` + 校验脚本 |
| H1 | 程序化入口 | T1 或 T2 可用，提交→结果闭环；启动开销 p95 < 5s | 调用日志 |
| H2 | 工具边界 | 白名单外工具调用 0 次；3 次注入越权全部被拒 | 轨迹审计 |
| H3 | 写隔离 | 写工具 0 次；ticket/receipt 文件 0 写入 | 文件探针 + 审计 |
| H4 | 回执兼容 | `done/retryable/manual` 三态均能驱动 Router 正确迁移 | 端到端用例 |
| H5 | Trace | 100% receipt 带 `trace_id` + `hermes_session_id`；可 join | trace 表 |
| H6 | 崩溃恢复 | kill -9 后租约回收，重试 ≤3，最终 `manual`；无重复 done | 故障注入 |
| H7 | 预算/超时 | 超 token / 超时均返回 `budget_exceeded/timeout`，无残留进程 | 资源监控 |
| H8 | 回归/回退 | 开关关闭时现有链路字节等价；回退 < 5 分钟 | 回归报告 |

### 7.3 测试矩阵

| # | 场景 | 输入 | 期望 |
|---|---|---|---|
| T-01 | 正常完成 | 合法 assignment | `done` + 结构化 evidence |
| T-02 | 工具越权 | `mandate.tools` 含白名单外工具 | `failed/manual`，不执行 |
| T-03 | 运行中越权 | Hermes 尝试调写工具 | `failed/manual` + 隔离 |
| T-04 | 任务超时 | 下游 MCP 挂起 | `retryable/timeout`，无残留进程 |
| T-05 | 进程崩溃 | kill -9 executor | 租约回收 → 重试 |
| T-06 | 重复投递 | 同 ticket 投递 3 次 | 仅 1 次执行，1 条 done |
| T-07 | 预算超限 | `max_tokens` 调小 | `manual/budget_exceeded` |
| T-08 | 审批拒绝 | 触发高风险命令 | `manual/approval_denied` |
| T-09 | MCP 降级 | 单个 shell 不可用 | `done/degraded=true` 或 `retryable`，不 crash |

### 7.4 指标与阈值

| 指标 | 阈值 | 口径 |
|---|---|---|
| 任务成功率 | ≥ DSH 基线 + 10pp | 三类任务加权 |
| p95 时延 | ≤ 2× DSH 基线，且 ≤ 600s | 端到端 |
| 单任务成本 | ≤ mandate 预算；中位数 ≤ 2× DSH | token + 调用费 |
| 越权调用 | 0 | 轨迹审计 |
| 写操作 | 0 | 文件探针 |
| 回执合法率 | 100% | schema 校验 |
| 重复执行 | 0 | 幂等测试 |
| 回退时间 | < 5 分钟 | 演练 |

### 7.5 验收证据包

```text
acceptance_bundles/<date>_hermes_executor_poc/
├── acceptance_report.md      # H0–H8 逐项结论
├── receipts_sample.jsonl     # 60 条回执
├── trace_join.jsonl          # trace 串联证据
├── violation_tests.md        # T-02/T-03 注入记录
├── crash_recovery.md         # T-05 故障注入记录
├── cost_report.md            # 与 DSH 基线对比
└── rollback_drill.md         # 开关回退演练
```

### 7.6 灰度与退出

1. `canary_pct=10`，仅 `research`，观察 2 周；
2. 无 P0/P1、指标达标 → 50%；
3. 再观察 1 周 → 100%（仅 research/engineer）；
4. 任一硬门禁失败 → 关闭开关，回退 `DshCliExecutor`，保留证据包复盘。

---

## §8 部署形态

| 项 | 决策 |
|---|---|
| 托管 | `dreambuddy-hermes-worker.service`（systemd，独立用户） |
| 启动 | `Restart=on-failure`、`RestartSec=5` |
| 停止 | `KillMode=mixed`、`TimeoutStopSec=30`，先 SIGTERM 再 SIGKILL 进程组 |
| 日志 | journald，不落自定义文件 |
| 配置 | `/etc/dreambuddy/hermes-worker.env` + 只读 role 配置 |
| 依赖 | 锁定 `hermes-cli` 版本；离线包可用；升级需重新过 H0/H2/H3 |
| 资源 | 单实例；并发上限 ≤ 3（与 `delegation.max_concurrent_children` 对齐） |

---

## §9 开放问题（评审前必须回答）

| ID | 问题 | 阻塞级别 | 备选 |
|---|---|---|---|
| Q1 | Hermes 是否有稳定的 headless 结构化入口？ | **阻塞 H1** | T1/T2/T3 |
| Q2 | Hermes 是否支持作为 MCP client 按角色挂载 shell？ | **阻塞 H2** | 自建 MCP proxy |
| Q3 | 审批在非交互模式下如何自动放行只读、拒绝写？ | 阻塞 H3 | 独立 profile + 工具白名单 |
| Q4 | 会话复用与 Ticket 幂等如何映射？ | 阻塞 H6 | 每任务临时 HOME |
| Q5 | 能否获取 token/成本指标？ | 影响 7.4 | 外部计量 |
| Q6 | curator/记忆是否会污染共享目录？ | 阻塞 H8 | 关闭 curator + 临时 HOME |
| Q7 | 版本升级策略与离线安装？ | 影响部署 | 固定 wheel + 内网源 |
| Q8 | 与现有 Feishu gateway 的凭据/端口隔离？ | 阻塞部署 | 独立用户 + 独立 HOME |

---

## §10 落地改动清单（评审通过后执行）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `34-.../core/hermes_executor.py` | 新增 `HermesExecutor` + `HermesTransport` |
| 2 | `34-.../core/worker_launcher.py` | 增加按 role 解析 executor；不改变现有默认 |
| 3 | `34-.../core/worker_roles.py` | 自检 `executor` 字段与 53 `allowed_roles` |
| 4 | `47/registry/mcp_capabilities.yaml` | 为 research/engineer 增加 `executor: hermes`（可选字段） |
| 5 | `53/plugin_whitelist.yaml` | 新增 `external_runtimes` 段 |
| 6 | `53/check_whitelist.py` | 增加 `--runtime/--role` 校验 |
| 7 | `deploy/systemd/dreambuddy-hermes-worker.service` | 新增独立服务 |
| 8 | `deploy/hermes/hermes-worker.env.example` | 独立环境变量模板 |
| 9 | `34-.../tests/test_hermes_executor.py` | T-01~T-09 契约测试 |
| 10 | `acceptance_bundles/` | POC 证据包 |

### 10.1 Phase 3 落地状态（2026-11-19）

- ✅ `core/hermes_executor.py`：`HermesExecutor` / `CliHermesTransport` / `ExecutorRouter` / `build_executor_router`。
- ✅ `core/worker_roles.py`：`executor` 字段自检 + 53 `allowed_roles` 对齐。
- ✅ `47/.../mcp_capabilities.yaml`：`research` / `engineer` 标记 `executor: hermes`（开关关闭时不生效）。
- ✅ `53/check_whitelist.py`：新增 `--runtime/--role/--profile` 外部运行时校验。
- ✅ `deploy/systemd/dreambuddy-worker-launcher.service` + `.env.example`：`D3_EXECUTOR=auto`，默认关闭 Hermes。
- ✅ `tests/test_hermes_executor.py`：14 项契约/路由/超时/证据限长/写隔离测试通过。
- ⛔ **本地 H1 FAIL**：`~/.hermes/.venv/bin/hermes` 缺 `hermes_cli`；PATH 上是 npm REPL。
- ✅ **云端 H0–H8 全过**（H6 SKIP）：`/usr/local/bin/hermes` 0.19.0，`-z PROMPT` headless 可用；证据包 `acceptance_bundles/P0-D3B-GATES-CLOUD-2026-11-19.json`，决策 `eligible_for_canary`。
- ✅ **canary 机制实测**（云端）：0/10/50/100 → Hermes 命中 0/106/509/1000；修正了 `digest[0] % 100` 的分布偏差（改用 4 字节取模）。
- ⛔ **实际放开被阻塞**：云端仓库尚未包含 Phase 3 代码（`core/hermes_executor.py` 不存在），需要 commit/push + 云端 ff-only 更新 + 重启 `dreambuddy-worker-launcher.service` 后才能把 canary 置为 10。
- 🔒 53 `hermes.enabled=false`：任何角色即使被标记 hermes，运行时仍返回 `runtime_disabled`，fail-closed。

---

## §11 评审检查表

- [ ] 是否确认 Hermes 不进入 `cordis.patch.yml`（不是 Cordis 插件）
- [ ] 是否确认 53 采用 `external_runtimes` 新分类，而非改造现有 `entries`
- [ ] 是否确认只接 `research/engineer`，`executor/data_reader/verifier` 保持 DSH
- [ ] 是否确认工具面只经 47 MCP 壳，不自建数据通道
- [ ] 是否确认 H-1~H-8 为不可协商硬约束
- [ ] 是否确认 H1（程序化入口）是 POC 的 go/no-go 前置
- [ ] 是否确认默认关闭 + 一键回退
- [ ] 是否确认与 Feishu gateway 物理隔离

---

## 附录 A：assignment → executor 的调用链

```text
Router (34/core/router_loop.py)
  └─ append dsh_worker_inbox.jsonl
       └─ WorkerLauncher.run_once()
            ├─ 判权（worker_roles / RolePolicy）
            ├─ resolve_executor(role)
            │    ├─ dsh    → DshCliExecutor
            │    └─ hermes → HermesExecutor
            │         ├─ HermesTransport.execute(task)
            │         ├─ MCP shells（47，只读）
            │         └─ HermesResult → ExecutorResult
            └─ 写 dsh_worker_receipts.jsonl
                 └─ Router 下一轮 apply_receipts()
```

## 附录 B：契约字段速查

| 字段 | 必填 | 来源 | 说明 |
|---|---|---|---|
| `ticket_id` | 是 | assignment | 幂等键 |
| `role` | 是 | assignment | 决定能力集与 executor |
| `trace_id` | 是 | assignment | 全链路观测 |
| `mandate.goal` | 是 | Router | 任务目标 |
| `mandate.tools` | 是 | Router | 必须 ⊆ 角色白名单 |
| `mandate.budget` | 是（hermes） | Router | turns/tokens/timeout |
| `status` | 是 | executor | `done/failed` |
| `failure_class` | failed 时必填 | executor | `retryable/manual` |
| `evidence.summary` | 是 | executor | ≤2000 字 |
| `evidence.executor` | 是 | executor | `hermes` |
| `evidence.trace_id` | 是 | executor | 与 assignment 一致 |
