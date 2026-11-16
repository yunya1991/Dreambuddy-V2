# SPEC-56-H — L2 Harness 能力增强（HCP）v0.2

> **版本**: v0.3（复审修订稿）
> **日期**: 2026-11-17
> **状态**: ✅ 设计复审通过（Conditional Pass）—— v0.3 已修 P0 阻断项；**H-D0b 注入点已落表**；H1 声明层 + H2/H3/H4/H5 影子/门禁已落地（见 §6.2 状态）；G-L2-12/13 仍为 off，H4 强制绑定与 ledger v1.2 延后，未改生产默认行为
> **上游 SSoT**:
> - [SPEC-56-L2架构能力聚合层.md](./SPEC-56-L2架构能力聚合层.md) v0.9（ADR/IF/G-L2）
> - [docs/TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md) v1.16（能力登记与 GAP-01~30）
> - [docs/RESEARCH-20261117-Trae逆向解析与交互学习-v0.1.md](./docs/RESEARCH-20261117-Trae逆向解析与交互学习-v0.1.md) v0.1.4（Trae 证据）
> **评审**: [REVIEW-20261117-SPEC-56-H-HCP.md](./docs/REVIEW-20261117-SPEC-56-H-HCP.md)（复审：设计层通过，实现层待 G-R1–G-R3；见 §十二）
> **下游**: 34（Router/Ticket）、47（MCP Registry）、3.1（tool profile）、52（计量）、33（训练案例）
> **不做什么**: 不复制 Trae、不修改 Trae、不读取凭据、不破解加密库、不新建业务能力。

---

## §0 摘要

1. **v0.2 的核心修订**：不新建第二套契约；H2/H3 采用「影子兼容 → 版本升级」两阶段；H5 的 evidence level 改为由 refs 推导；审批改为 hash 绑定。
2. **P0 收缩**：只做 **H3（可归因）+ H5（证据门禁）**；H1/H2 移到 P1，H4 移到 P2，且都必须先做代码复核。
3. **统计口径**：P0 用固定 50 会话、**100% join** 准入；生产门禁用 `n≥100`、点估计 ≥95%、Wilson 95% 下限 ≥90%。50 个全命中只能证明下限约 92.9%，不足以单独证明 95%。
4. **证据分层**：A 级（observation + 交叉证据）可优化/训练；B 级（inference + 人工确认/复现）只生成假设；C 级（inference-only）只可检索。
5. **门禁激活**：G-L2-14/G-L2-16 在 P0 只开 shadow；G-L2-12/13 到 P1；G-L2-15 到 P2。门禁带 `activation` 与 `since_phase`，不再“先立门禁再补实现”。
6. **v0.3 的阻断项修复**：H5 对 H3 增加依赖栅栏；新增 H-D0b（重复性复核 + 命令信封注入点勘察）作为 P0 前置；`derived_level` 拆为 `author_claim`（作者写）+ `derived`（校验器写）；`mode` 拆为 `permission_mode` / `session_mode`；弱关联改为不计入分子；`resume_guard` 与保留期统一为 7 天；P0 退出条件与 shadow 阻断语义分层；A 级增加“可复现/人工确认”并要求复用 33 的 PoE 校验器。

---

## §1 Trae 收获与取舍

### 1.1 五个机制（带证据等级）

> **术语校正**：`declaration / observation / inference` 描述的是**命题的证据来源**，不是命题强度。正确读法是“命题 P 的证据来源 = declaration”，不要给机制本身贴“X 级”；下游 A/B/C 分级只作用于 `InteractionCase`。

| # | 机制 | Trae 观察 | 证据来源 | 采用前提 |
|---|---|---|---|---|
| M1 | `agent_type × model → skill bundle` | trae 6 / code 6 / design 4 / work 10 个 profile；skills 1–14 | **declaration**（manifest 声明） | 代码复核 47/34 后再 P1 |
| M2 | `session × mode → tool_set` | 25 会话 / 10 mode / 16–37 工具 | observation | 先核对 A1-2/GAP-25 |
| M3 | `command → sandbox envelope` | 1,006 条；无 trace/session ID | observation | **P0 直接做** |
| M4 | `session → checkpoint` | 19 个 git 快照 | observation / analogy | 先核对 Ticket paused，P2 |
| M5 | `session → summary memory` | 627 条案例；全为 inference | inference | **P0 做证据门禁** |

### 1.2 五个缺口候选

| 候选 | 机制 | 现有 GAP | 优先级 | 本 SPEC |
|---|---|---|---|---|
| GAP-T1 | M1 | GAP-02/13/19 | P1 | H1（P1） |
| GAP-T2 | M2 | GAP-19/23/25 | P1 | H2（P1） |
| **GAP-T3** | M3 | GAP-01/24/30 | **P1（硬阻塞）** | H3（P0） |
| GAP-T4 | M4 | GAP-20/24 | P2 | H4（P2） |
| GAP-T5 | M5 | GAP-15/29 | P1 | H5（P0） |

### 1.3 采用 / 不采用

| 采用 | 不采用 |
|---|---|
| 能力按 `profile × role × model` 装配并留 bundle_id | 照搬 Trae 的 profile 名称与工具名 |
| 工具面按会话物化、hash、diff | 复制其 16–37 个工具清单（我们上限 15） |
| 命令/工具执行统一 span + trace_id | 读取或复用其加密 DB、token、prompt |
| checkpoint + resume 的物理载体 | 依赖 Trae 的 git 快照格式 |
| 交互摘要做案例，但先过证据门禁 | 把 `learned` 当事实直接进训练/台账 |

**单案例边界**：M1/M2/M4 来自一个产品的一个版本，属 analogy；在第二个产品/版本复现或在我方代码复核前，不得从 pattern 升为“通用机制”。

---

## §2 问题与目标

### 2.1 现状

| 现状 | 证据 | 影响 |
|---|---|---|
| L2 统一信封缺 `tokens_used/model` | L2-K14 / GAP-17 | 成本与证据边界无法闭合 |
| tool_set 只有单快照 | A1-2 / GAP-25 | 无法审计可见性与审批是否同源 |
| 执行链无统一 trace/session ID | GAP-30 / GAP-T3 | 交互案例无法归因，R2 门禁 0% |
| Ticket paused 无 checkpoint 契约 | GAP-20/24 / GAP-T4 | “可续跑”无法验证 |
| 交互摘要未过证据门禁 | GAP-15/29 / GAP-T5 | inference 可能污染训练与台账 |

### 2.2 目标（可机器判定）

1. **可归因（P0）**：固定 50 会话样本中，100% 的案例能 join 到 span/命令信封；生产门禁 `n≥100`、点估计 ≥95%、Wilson 95% 下限 ≥90%。
2. **可审计（P1）**：同一会话/mode 的 tool_set hash 稳定；变更产生 diff；审批必须引用同一 `tool_set_hash`。
3. **可恢复（P2）**：`paused` Ticket 必须绑定 checkpoint；resume 后产物 hash 一致。
4. **可装配（P1）**：`route_signal`（或过渡期 `route_hint`）携带 `capability_bundle_id` 与 `model_profile_id`。
5. **可学习（P0）**：只有 A 级案例可进入优化/训练；B 级只生成假设；C 级只可检索。

### 2.3 非目标

- 不改变 L0/L1 的判定权与事实源。
- 不新增业务生成能力；HCP 只做装配、留痕、门禁。
- 不要求一次性改造所有壳；P0 只碰 34，P1 再扩 3.1/52。
- 不把 Trae 的内部实现写成我们的实现。

---

## §3 架构

### 3.1 HCP 的位置

```
L2-K 内核编排（DreamOS / SACG）
  └─ HCP 横切（H1 能力装配 / H2 工具面 / H3 执行追踪 / H4 检查点 / H5 证据门禁）
L2-E 执行编排（DSH Router / Worker / Ticket / Mandate）
L2-G 生成式能力（32/34/48/25/30）
L2-P 协议接入（46/52/53/24）
L2-A 应用与前端（3.1/6）
```

HCP 不是第六个子层，而是 L2-K/L2-E 的横切能力面；不新增 MCP 壳，只通过既有 `l2.dreamos`（以及未来 `l2.dsh`）暴露只读观测。

### 3.2 组件与阶段

| 组件 | 回答 | 锚点 | 阶段 | 门禁激活 |
|---|---|---|---|---|
| H1 CapabilityBundle | 这次任务该给模型哪些技能/工具/权限 | IF-1 | P1 | G-L2-12：P1 enforce |
| H2 ToolSetSnapshot v2 | LLM 实际看到哪些工具、何时变过 | IF-7 | P1 | G-L2-13：P1 enforce |
| H3 ExecutionTrace v2 | 这次执行属于哪个会话/请求/步骤 | IF-3 + IF-7 | **P0** | G-L2-14：P0 shadow，P1 enforce |
| H4 Checkpoint | 断了从哪里续、续得对不对 | IF-4 + ADR-10 | P2 | G-L2-15：P2 enforce |
| H5 Evidence Gate | 这条经验能不能用 | IF-5 + ADR-06 | **P0** | G-L2-16：P0 shadow，P1 enforce |

### 3.3 数据流

```
请求
 → H1 选 bundle（profile → role → model）        [P1]
 → H2 生成 tool_set 快照（v1.0 + sidecar）        [P1]
 → H3 每个 span 带 trace/run/session（影子 attrs）[P0]
 → H4 paused 时写 checkpoint                     [P2]
 → H5 会话结束生成 InteractionCase，按 refs 分级  [P0]
 → A 级进 training/optimization；B 级假设；C 级检索
```

---

## §4 契约

> 下例中的 hash 均用 64 个 0 占位，仅用于通过 schema 形状校验；实际实现必须写入真实 `sha256:` 值，校验器不得接受全 0 占位。

### 4.1 H1：CapabilityBundle（P1）

```json
{
  "bundle_id": "cb-20261117-001",
  "agent_profile_id": "developer|reviewer|researcher|operator",
  "worker_role_id": "<47 worker_role_id>",
  "model_profile": {
    "model_id": "qwen-max",
    "context_window": 131072,
    "capabilities": ["tool_use", "vision"]
  },
  "skills": ["dream-bugfix-workflow"],
  "tools": ["l2.dreamos.submit_run"],
  "permission_mode": "read|write|trade",
  "requires_mandate": true,
  "source": "registry|manifest|override",
  "hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
}
```

约束：
- `agent_profile_id` 是任务原型（如 developer/reviewer），`worker_role_id` 是 47 的执行角色（research/engineer/verifier/...）；两者不得混用。
- 选择顺序固定 `agent_profile_id → worker_role_id → model_profile`；同一 role 在不同 profile 下可有不同 skills。
- `route_signal` 尚未实现（GAP-13）时，先在 34 的 `route_hint` 加 `capability_bundle_id/model_profile_id`；G-L2-12 在 P1 前保持 off。
- `tools` 必须是 H2 快照的子集；bundle 不能绕过 tool_set 审批。
- `hash` 对 `{agent_profile_id, worker_role_id, model_profile, skills, tools, permissions}` 做 canonical JSON 哈希。
- **证据边界**：M1 的证据来源是 manifest declaration，不是运行时 observation；H1 先按设计假设落地，代码复核后再 enforce。
- `permission_mode`（read/write/trade）与 H2 的 `session_mode`（如 `solo_agent`）是不同维度，禁止共用一个字段名。
- 时序：`approval_ref` 必须在快照生成之后签发（见 §4.2），否则审批无效。

### 4.2 H2：ToolSetSnapshot v2（P1）

**两阶段，避免破坏 v1.0 消费方：**

1. **影子阶段（P1 前）**：现有 `tool_set.schema.json` v1.0 不动，旁路写 `tool_set.hcp.json`：

```json
{
  "schema_version": "hcp-1.0",
  "tool_set_id": "ts-20261117-003",
  "run_id": "run-...",
  "session_id": "sess-...",
  "mode": "solo_agent",
  "version": 3,
  "hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "diff": {"added": [], "removed": [], "changed": []},
  "approval_ref": {"tool_set_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000", "mandate_id": "mandate-..."}
}
```

2. **升级阶段（P1 enforce）**：`tool_set.schema.json` 升 v1.1，保留原有必填字段，新增 `tool_set_id/session_id/version/hash/diff/approval_ref`。

v1.1 示例（必须保留 v1.0 字段）：

```json
{
  "schema_version": "1.1",
  "run_id": "run-...",
  "generated_at": "2026-11-17T10:00:00Z",
  "source": "47-registry",
  "policy": {"order": ["deny", "mode", "allow", "human"], "mode": "default"},
  "tool_set_id": "ts-20261117-003",
  "session_id": "sess-...",
  "version": 3,
  "hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "tools": [
    {
      "name": "l2.dreamos.submit_run",
      "shell": "l2.dreamos.mcp",
      "layer": "L2",
      "exposure": "control",
      "effect": "write",
      "requires_mandate": true,
      "visibility": "model",
      "approval": "human"
    }
  ],
  "diff": {"added": [], "removed": [], "changed": []},
  "approval_ref": {"tool_set_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000", "mandate_id": "mandate-..."}
}
```

约束：
- `hash` 对排序后的 `tools` canonical JSON 计算；同会话同 mode 且工具未变时 hash 稳定。
- `len(tools) ≤ max_tools_per_shell`（当前 15，见 47 `enums`）；不得直接搬 Trae 的 16–37。
- 审批必须引用 `tool_set_hash`；Mandate 校验时 `mandate.tool_set_hash == 当前快照 hash`，否则拒绝。
- **时序**：先出快照、后签发审批；`approval_ref.mandate_id` 的签发时间必须晚于 `generated_at`。审批早于快照视为无效，避免“先批后用”的循环。
- `diff` 只在变更时生成；无变更的重复快照不落新版本。
- 保留期：30 天或最近 100 个版本，先到为准；过期只留 hash 与 diff 摘要。

### 4.3 H3：ExecutionTrace v2（P0）

**影子阶段（P0）**：`span.schema.json` v1.0 不动；新 ID 放 `attrs.hcp`（`attrs` 是自由对象），避免破坏 `additionalProperties:false`：

```json
{
  "schema_version": "1.0",
  "trace_id": "tr-...",
  "run_id": "run-...",
  "span_id": "sp-...",
  "parent_span_id": null,
  "name": "capability.route",
  "segment": "capability",
  "started_at": "2026-11-17T10:00:00Z",
  "ended_at": "2026-11-17T10:00:01Z",
  "model_id": "qwen-max",
  "tokens_in": 120,
  "tokens_out": 80,
  "cost_cu": 0.02,
  "context_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "stop_reason": "done",
  "attrs": {
    "hcp.session_id": "sess-...",
    "hcp.tool_call_id": "tc-...",
    "hcp.interaction_case_id": "case-..."
  }
}
```

**升级阶段（P1）**：`span.schema.json` 升 v1.1，新增顶层 `session_id/tool_call_id/interaction_case_id`；保留 `tokens_in/tokens_out/cost_cu`，不得改成嵌套 `tokens`。

约束：
- `trace_id/run_id/session_id` 必填（shadow 期 session_id 在 `attrs.hcp`）。
- `model_id=none` ⇒ `tokens_in=tokens_out=cost_cu=0`。
- `ended_at ≥ started_at`；`context_hash=sha256:*`。
- 命令信封必须携带同一 `trace_id/session_id`；这是 G-L2-14 的核心。
- 迁移顺序：34 → 52 → 3.1；P0 只要求 34 产出，52/3.1 允许 `skip` 并写明原因。
- **注入点必须落表**：H-D0b 产出“命令信封注入点清单”（文件、函数、字段、写入时机）。未落表前 P0 不得开工。Trae 侧 1,006 条命令**无** trace/session ID 的事实说明：影子写 `attrs.hcp` 只能覆盖模型调用层，命令层必须显式注入。

### 4.4 H4：Checkpoint（P2）

新增 `contracts/checkpoint.schema.json`（P2 才启用）：

```json
{
  "checkpoint_id": "ckpt-...",
  "session_id": "sess-...",
  "ticket_id": "ticket-...",
  "state": "paused",
  "content_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "git": {"repo": "...", "commit": "...", "dirty": false},
  "artifacts": [{"path": "...", "hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000"}],
  "created_at": "2026-11-17T10:00:00Z",
  "resume_guard": {"requires_same_hash": true, "max_age_s": 604800}
}
```

约束：
- `paused` Ticket 必须引用 `checkpoint_id`；无 checkpoint 时 `stop_reason.resumable=false`（沿用 IF-7 语义，不另造字段）。
- resume 前校验 `content_hash`；不一致时进入 `needs_review`，禁止静默续跑。
- `dirty=true` 时必须在 `artifacts` 列出未提交文件；否则拒绝。
- checkpoint 只存引用与 hash，不存凭据/大对象；保留期 7 天，与 `resume_guard.max_age_s=604800` 必须同步修改。

### 4.5 H5：InteractionCase + Evidence Gate（P0）

新增 `contracts/interaction_case.schema.json`：

```json
{
  "case_id": "case-...",
  "session_id": "sess-...",
  "intent": "...",
  "actions": ["..."],
  "outcome": "...",
  "learned": ["..."],
  "refs": [
    {"type": "span", "id": "sp-...", "hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000"},
    {"type": "checkpoint", "id": "ckpt-...", "hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000"}
  ],
  "author_claim": "observation|inference",
  "derived": {"level": "observation|inference", "admissibility": "A|B|C"},
  "human_confirmation": {"by": "...", "at": "...", "ref": "..."},
  "links": {"trace_id": "tr-...", "ledger_task_id": "fix-..."}
}
```

分级规则（`derived` 由校验器写入，案例作者只能写 `author_claim`；校验器忽略/拒绝任何自带 `derived` 的输入）：
- `derived.level=observation` ⇔ `author_claim=observation` 且至少 1 条 `span`/`checkpoint`/`file` ref 的 id 存在、hash 匹配；否则降为 `inference`。
- A 级：`observation` + refs 含 span/checkpoint + **可复现记录或 `human_confirmation` 二者之一** → 可进入优化/训练。仅“引用自洽”不足以评 A——自洽不等于事实正确。
- B 级：`inference` 且有 `human_confirmation` 或复现记录 → 只生成假设，不做优化结论。
- C 级：`inference` 且无确认 → 只可检索/回忆，不得进入训练/优化/settled。
- **复用而非新建**：A/B/C 判定与审计复用 33 的 `reflection`/PoE 能力；56 只定义 schema 与分级函数签名，不建第二套 validator。

`RepairLedger` v1.2：
- 新增 `settled.case_ref`；新 `settled` 必须填，历史 v1.1 记录允许缺失（legacy）。
- 负例：v1.2 settled 无 `case_ref` → 校验失败。

### 4.6 契约映射与兼容

| HCP | 现有契约 | 影子方式 | 升级版本 | 兼容规则 |
|---|---|---|---|---|
| H1 | IF-1 `route_signal` | `route_hint` 加字段 | IF-1 v1.1 | G-L2-12 P1 前 off |
| H2 | IF-7 `tool_set` | `tool_set.hcp.json` sidecar | `tool_set` v1.1 | v1.0 消费方只读原文件 |
| H3 | IF-3/IF-7 `span` | `attrs.hcp.*` | `span` v1.1 | v1.0 必填字段不变 |
| H4 | IF-4 `Ticket` | 新 schema，P2 才写 | `checkpoint` v1.0 | `resumable` 沿用 IF-7 |
| H5 | IF-5 `RepairLedger` | 新 case schema | `repair_ledger` v1.2 | 历史 settled 允许无 case_ref |

---

## §5 门禁

| # | 门禁 | 阶段 | 激活 | 判据 | 失败后果 |
|---|---|---|---|---|---|
| G-L2-12 | 能力装配 | P1 | off → enforce | `route_signal/route_hint` 含 `capability_bundle_id` + `model_profile_id`；tool_set 引用同一 bundle | `needs_review` |
| G-L2-13 | 工具面审计 | P1 | off → enforce | tool_set 有 hash/version；变更必有 diff；`mandate.tool_set_hash == 快照 hash`；`len(tools) ≤ 15` | 审计失败，禁止上线 |
| G-L2-14 | 归因 | **P0** | shadow → enforce | P0：50 会话 100% join；P1：n≥100，点估计 ≥95%，Wilson 95% 下限 ≥90% | shadow 只记录；enforce 失败不得验收 |
| G-L2-15 | 恢复 | P2 | off → enforce | paused 有 checkpoint；resume 后 content_hash 一致；`resumable` 与 checkpoint 一致 | 标记不可续跑 |
| G-L2-16 | 证据 | **P0** | shadow → enforce | A 级才可优化/训练；C 级不得进入；v1.2 settled 必须有 case_ref | 拒绝入账，记录违规 |

门禁结果格式：

```json
{
  "gate_id": "G-L2-14",
  "phase": "P0",
  "activation": "shadow",
  "status": "pass|fail|skip",
  "reason": "...",
  "trace_id": "tr-...",
  "metrics": {"numerator": 0, "denominator": 0, "point": 0.0, "wilson_low": 0.0}
}
```

规则：
- `skip` 必须写明原因；P0 的 52/3.1 允许 skip。
- P0 只启用 G-L2-14/G-L2-16 的 shadow；G-L2-12/13/15 必须为 `off`。
- 任一 enforce 门禁失败，本轮不得合并；shadow 失败只记录，不阻断。

### 5.1 Join 统计口径

- **单位**：`InteractionCase`（不是会话）。
- **分母**：`session_id` 非空的案例数。
- **强关联（计入分子）**：至少 1 条 span/命令信封满足以下之一：
  1. `interaction_case_id` 相同；或
  2. `trace_id` 相同；或
  3. `tool_call_id` 相同。
- **弱关联（不计入分子，单独统计）**：仅 `session_id` 相同且时间差 ≤60s。
- **P0 准入**：固定 50 会话，100% 强关联；弱关联占比必须单列，不得混入分子。
- **样本抽取**：预先登记起止时间窗与 `session_id` 清单，按时间顺序连续取样，**不得剔除**、不得事后替换；抽样清单随证据包一起提交。
- **生产门禁**：`n≥100`，点估计 ≥95%，Wilson 95% 下限 ≥90%。
- **置信说明**：50 个全命中时 Wilson 95% 下限约 92.9%；要证明 ≥95%，至少约 73 个全命中样本。P0 的 100% 是工程准入，不是统计证明。

---

## §6 实施

### 6.1 阶段

| 阶段 | 内容 | 交付 | 门禁 |
|---|---|---|---|
| **P0** | H3 影子 trace + H5 证据门禁 | span attrs + command join + case validator + ledger v1.2 | G-L2-14/16 shadow |
| **P0 栅栏** | H5 的 A 级依赖 H3 的 join | H3 未达 100% 强关联前，H5 只能产出 C 级案例，不得进入 A/B 验收 | H-D0b 复核通过 |
| **P1** | H1 bundle + H2 tool_set v2 | route_hint 字段 + sidecar + schema v1.1 | G-L2-12/13 enforce |
| **P2** | H4 checkpoint + resume | checkpoint schema + 恢复实验 | G-L2-15 enforce |

### 6.2 任务拆分

| ID | 任务 | 宿主 | 阶段 | 验收 |
|---|---|---|---|---|
| **H-D0b** | **重复性复核 + 注入点勘察**（P0 前置）：A1-2/A1-3/A3 已有字段清单；34 命令信封注入点（文件/函数/字段/时机） | 56/34 | **P0 前置** | ✅ 已落表（TECHNICAL_DESIGN v1.17）：`worker_tool_call.call_worker_tool` → `meta.trace_id/session_id/tool_call_id`（成功与失败返回前，`hcp.trace.shadow` 控制）；`hcp_trace.build_span` → `attrs.hcp.*`；复用 span v1.0 + 扩 attrs，不新建协议 |
| H-D0 | 更新主 SPEC §5 的 G-L2-12~16 与 `validate_contracts.py` 自检 | 56 | P0 | ✅ 新增 `checkpoint` / `interaction_case` 两契约校验，自检 29→33 全绿 |
| H-F3 | span 影子字段 + 命令信封 join | 34（先）/52/3.1 | P0 | 🟡 34 影子落地（`build_span` / `stamp_envelope` / `classify_join`，13/13 测试）；50 会话 100% 强关联待 H-M1；52/3.1 按 §6.3 允许 skip |
| H-F5 | InteractionCase 校验器 + A/B/C + ledger v1.2 | 34/33 | P0 | 🟡 `interaction_case.schema.json` + `34/core/evidence_gate.py` 落地（A/B/C 9 例全绿，C 级训练/settled 全拒，33 PoE 以注入方式复用）；**ledger v1.2 暂不升版**（避免破坏 A2 v1.1 台账，`settled.case_ref` 强制化延后） |
| H-M1 | 50 会话固定样本 + 证据包 | 33/56 | P0 | `reports/hcp-YYYYMMDD/` 可复跑 |
| H-D1 | H1/H2 schema v1.1 + sidecar 规范 | 56/47 | P1 | `validate_contracts.py` 通过 |
| H-F1 | `route_hint`/`route_signal` 注入 bundle | 34/47 | P1 | 🟡 声明层落地（`capability_bundle.py`：登记 + canonical hash + `bundle_route_hint`，9/9 测试）；**不修改 34 route_hint**，G-L2-12 保持 off |
| H-F2 | tool_set sidecar → v1.1 + hash/diff | 47/3.1/34 | P1 | 🟡 影子 `hcp-1.0` 落地（hash/diff/version/审批绑定/≤15，13/13 测试）；v1.1 升级待 P1 enforce |
| H-F4 | paused→checkpoint→resume | 34 | P2 | 🟡 `checkpoint.schema.json` + `34/core/ticket_checkpoint.py`（build/bind/resume guard，7 例全绿）；checkpoint 为**可选 sidecar**，现有 `ticket_resume.py` 事件续跑不改；强制绑定待 P2 enforce |

### 6.3 RACI

| 角色 | 负责 | 账号/模块 |
|---|---|---|
| HCP Owner | 契约、门禁、复审 | 56 |
| Router Owner | H1/H3 上下文 | 34 |
| Registry Owner | H1/H2 注册表与 schema | 47 |
| Frontend Owner | 3.1 tool profile/trace | 3.1 |
| Protocol Owner | 52 计量/trace | 52 |
| Evidence Owner | InteractionCase/训练案例 | 33/34 |

**合并门禁**：56 只合契约/schema/门禁定义；实现代码由宿主模块（34/47/52/3.1）各自 PR 合并。跨模块变更须在 PR 描述引用本 SPEC 任务 ID；禁止单个 PR 同时改契约与实现。

### 6.4 Feature flags 与回滚

| Flag | 默认 | 作用 | 回滚 |
|---|---|---|---|
| `hcp.trace.shadow` | off | 写 `attrs.hcp.*` | 关 flag，停止写 attrs |
| `hcp.evidence.shadow` | off | 计算 A/B/C，不阻断 | 关 flag，保留案例 |
| `hcp.bundle.enforce` | off | G-L2-12 enforce | 关 flag，回 route_hint |
| `hcp.toolset.enforce` | off | G-L2-13 enforce | 关 flag，回 v1.0 + sidecar |
| `hcp.checkpoint.enforce` | off | G-L2-15 enforce | 关 flag，回 paused 原语义 |

回滚原则：不降 schema 版本；只关 flag；已写入的 sidecar/attrs 保留，便于追溯。

---

## §7 验收

### 7.1 指标

> **口径分层**：`P0 退出条件` 用于阶段验收（不阻断日常合并）；`生产门禁` 才在 enforce 模式下阻断。shadow 期只记录，不因未达 P0 退出条件而阻止合并。

| 指标 | P0 退出条件（shadow） | 生产门禁（enforce，阻断） | 测量 |
|---|---|---|---|
| 强关联 join | 50 会话 100% | n≥100，点 ≥95%，Wilson 下限 ≥90% | 按案例计数 |
| tool_set 稳定性 | — | 同会话同 mode hash 100% 一致 | 重复生成 |
| diff 捕获 | — | 人为增删工具 100% 出 diff | 负例 |
| 工具配额 | — | `len(tools) ≤ 15` | schema |
| checkpoint 恢复 | — | 恢复后 hash 100% 一致 | 实验 |
| 证据分级 | C 级 100% 拒绝 | A/B/C 可复算 | 负例 |
| 回归 | 0 失败 | 0 失败 | 56 自检 + 34 测试 |

### 7.2 必须失败的负例

1. v1.0 span 顶层加 `session_id`（影子期应放 `attrs.hcp`）→ schema fail。
2. `tool_set` 缺 `schema_version/run_id/generated_at/source/policy` → schema fail。
3. `mandate.tool_set_hash` 与快照 hash 不一致 → G-L2-13 fail。
4. 案例 `author_claim=observation` 但无 refs → 校验器降为 inference/C 级。
5. v1.2 settled 无 `case_ref` → ledger fail。
6. 50 会话中弱关联计入分子 → P0 join 不通过。
7. 案例自带 `derived` 字段（绕过校验器）→ 校验器拒绝并重算。
8. `author_claim=observation` 但 refs 只有 `file`、无 span/checkpoint → 最高只能 B 级。

### 7.3 证据包

`reports/hcp-YYYYMMDD/` 至少包含：
- `schema_self_test.txt`（含 G-L2-12~16 计数）
- `join_report.json`（分子/分母、强/弱关联、Wilson 区间）
- `tool_set_sidecar.jsonl` + `tool_set_diff.jsonl`
- `checkpoint_resume.json`
- `negative_cases.jsonl`（6 类负例）
- `README.md`（复跑命令、结论边界）

---

## §8 风险与开放问题

### 8.1 风险

| 风险 | 缓解 |
|---|---|
| 与 A1-2/A1-3/GAP-25/30 重复 | **P0 前置 H-D0b 代码复核**；只补字段，不新建机制 |
| trace 体积/PII | P0 100% 验证；生产 10% + 失败全采；不落 prompt 原文 |
| checkpoint 成本 | 只存引用/hash；7 天保留 |
| 模型能力表漂移 | `model_profile` 版本化；变更评审 |
| 单案例外推 | M1/M2/M4 标 analogy；第二案例复现后再升级 |
| 门禁膨胀 | activation/since_phase；P0 只开两道 shadow |

### 8.2 开放问题

| # | 问题 | 选项 | 建议 |
|---|---|---|---|
| Q1 | bundle 放 47 还是新文件 | A 扩展 `mcp_capabilities.yaml`；B 新文件 | A（先扩展，避免双源） |
| Q2 | checkpoint 存 git 还是 CAS | A git；B CAS+manifest | A 起步，B 二期 |
| Q3 | InteractionCase 存 34 还是 33 | A 34 训练库；B 33 案例库 | B 存原始，A 存 A 级子集 |
| Q4 | H1 是否覆盖 L1 | A 仅 L2；B L1+L2 | A |
| Q5 | trace 采样 | A 100%；B 10%+失败全采 | P0 100%，生产 B |
| Q6 | schema 版本协商 | A sidecar/attrs 过渡；B 一次性升版本 | A（v0.2 采用） |

---

## §9 证据索引

- Trae 研究：[RESEARCH-20261117-Trae逆向解析与交互学习-v0.1.md](./docs/RESEARCH-20261117-Trae逆向解析与交互学习-v0.1.md)
- 机制卡：[mechanism_cards.md](../33-REA逆向解析工程/reports/trae-20261117/mechanism_cards.md)
- 差距映射：[gap_mapping.md](../33-REA逆向解析工程/reports/trae-20261117/gap_mapping.md)
- 候选缺口：[gap_candidates.json](../33-REA逆向解析工程/reports/trae-20261117/gap_candidates.json)
- 参考实现：[33-REA逆向解析工程/trae/](../33-REA逆向解析工程/trae/)
- 技能：`~/.trae-cn/skills/harness-reverse-engineering/SKILL.md`
- 内部已有能力（H-D0b 必查）：`1-ARCHITECTURE/dreamos/core/capability/`（A1-2 tool_set、A1-3 span/stop_reason、A3 probe/unload/install/preset）、[TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md) v1.16 的 GAP-01~30 与 A1/A3 行、`33-REA逆向解析工程` 的 reflection/PoE 门禁

---

## §10 评审 Major 修订对照

> 这里的 M1–M4 是评审 Major 编号，不是机制 M1–M5。

| 评审项 | 修订位置 | 修订内容 | 状态 |
|---|---|---|---|
| M1 | §4.3 | 保留 `tokens_in/tokens_out/cost_cu`；影子用 `attrs.hcp`；P1 升 span v1.1 | ✅ 已修 |
| M2 | §4.2 | 保留 v1.0 必填字段；sidecar → v1.1；`tools[]` 原字段不变 | ✅ 已修 |
| M3 | §4.2 / §5 | `approval_ref.tool_set_hash`；Mandate 校验 hash 一致 | ✅ 已修 |
| M4 | §4.5 | `derived_level` 由 refs 推导；A/B/C 分级；ledger v1.2 + case_ref | ✅ 已修 |
| m1 | §4.1 | 拆 `agent_profile_id` / `worker_role_id` | ✅ 已修 |
| m2 | §2.2 / §5.1 | P0 100%；生产 n≥100 + Wilson；73 全命中说明 | ✅ 已修 |
| m3 | §4.5 | A/B/C 三级准入 | ✅ 已修 |
| m4 | §5 | `activation/since_phase` | ✅ 已修 |
| m5 | §6.3 / §6.4 | RACI + feature flags + 回滚 | ✅ 已修 |
| m6 | §6.2 | H-D0 更新主 SPEC/校验器 | ✅ 已修 |

### 10.1 v0.3 复审修订对照

| 编号 | 问题 | 修订位置 | 修订内容 |
|---|---|---|---|
| R1 | H5 对 H3 隐性强依赖 | §6.1 | 新增“P0 栅栏”：H3 未达 100% 强关联前，H5 只能产出 C 级 |
| R2 | 命令信封注入点无锚点 | §4.3 / §6.2 | 新增 H-D0b 必须产出注入点清单（文件/函数/字段/时机），未落表不得开工 |
| R3 | 重复性复核被放到 P1 | §6.2 / §8.1 / §9 | H-D0b 提为 P0 前置；§9 补内部能力索引 |
| R4 | `derived_level` 自填与计算双写歧义 | §4.5 | 拆为 `author_claim`（作者写）+ `derived`（校验器写），自带 `derived` 一律拒绝重算 |
| R5 | shadow 不阻断与 P0 指标冲突 | §7.1 | 表头改为“P0 退出条件 / 生产门禁（enforce，阻断）”并加口径说明 |
| R6 | `mode` 同名不同义 | §4.1 | 改为 `permission_mode`，与 H2 的 `session_mode` 分列 |
| R7 | 弱关联定义自相矛盾 | §5.1 | 强关联含 `tool_call_id` 相同；弱关联仅“同 session + ≤60s”且不计入分子 |
| R8 | checkpoint 时间口径冲突 | §4.4 | `max_age_s` 86400 → 604800，与 7 天保留期同步 |
| R9 | A 级只校验引用完整性 | §4.5 | A 级增加“可复现或人工确认”之一；要求复用 33 PoE，不建第二套 validator |
| R10 | 样本抽取与审批时序缺失 | §5.1 / §4.2 | 补预先登记、连续取样、不得剔除；补“先快照后审批”时序约束 |
| R11 | 跨模块合并无门禁 | §6.3 | 补“56 只合契约、实现由宿主各自 PR”的合并门禁 |
| R12 | 术语把数据来源当命题强度 | §1.1 | 表格列名改“证据来源”，加术语校正说明 |
| R13 | 负例不足 | §7.2 | 新增负例 7（自带 `derived`）与 8（只有 file ref） |

---

## §11 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-17 | 首版：M1–M5 → H1–H5 + G-L2-12~16 |
| v0.2 | 2026-11-17 | 修评审 Major M1–M4；P0 收缩为 H3+H5；补统计口径、RACI、feature flags、回滚、schema 两阶段兼容 |
| v0.3 | 2026-11-17 | 修复审阻断项 R1–R13：H5→H3 依赖栅栏、H-D0b 前置复核、`author_claim`/`derived` 拆分、`permission_mode` 改名、弱关联不计入分子、checkpoint 时间统一、P0 与 enforce 口径分层、A 级加可复现并复用 33 PoE、补合并门禁与两条负例 |
