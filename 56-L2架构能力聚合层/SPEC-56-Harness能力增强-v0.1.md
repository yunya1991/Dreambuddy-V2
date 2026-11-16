# SPEC-56-H — L2 Harness 能力增强（HCP）v0.1

> **版本**: v0.1（设计稿，未实现）
> **日期**: 2026-11-17
> **状态**: ⛔ 已被 v0.2 取代（2026-11-17），保留用于追溯；当前版本见 [SPEC-56-Harness能力增强-v0.3.md](./SPEC-56-Harness能力增强-v0.3.md)
> **上游 SSoT**:
> - [SPEC-56-L2架构能力聚合层.md](./SPEC-56-L2架构能力聚合层.md) v0.9（ADR/IF/G-L2）
> - [docs/TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md) v1.16（能力登记与 GAP-01~30）
> - [docs/RESEARCH-20261117-Trae逆向解析与交互学习-v0.1.md](./docs/RESEARCH-20261117-Trae逆向解析与交互学习-v0.1.md) v0.1.3（Trae 证据）
> **下游**: 34（Router/Ticket）、47（MCP Registry）、3.1（tool profile）、52（计量）、33（训练案例）
> **不做什么**: 不复制 Trae、不修改 Trae、不读取凭据、不破解加密库、不新建业务能力。

---

## §0 摘要

1. Trae 最值得迁移的不是 UI 或 prompt，而是 **5 个装配机制**：`agent_type×model→skills`、`session×mode→tool_set`、`command→sandbox envelope`、`session→checkpoint`、`session→summary memory`。
2. 对照 56 后，真正阻塞我们的不是「能力不够」，而是 **可归因性不足**：1,006 条执行信封无 `trace_id/session_id`，导致交互案例交叉证据率为 0%（`GAP-T3`）。
3. 本 SPEC 新增一个横切面 **HCP（Harness Capability Plane）**，含 5 个组件 H1–H5，全部以现有 IF-1/IF-3/IF-4/IF-5/IF-7 为锚点扩展，不新开第二套契约。
4. 优先级：**H3（trace 归因）→ H5（证据门禁）→ H1（能力 bundle）→ H2（tool_set 版本）→ H4（checkpoint）**；H3/H5 先 shadow，不改生产行为。
5. 验收以机器判定为主：join_rate ≥95%、tool_set hash 稳定、checkpoint 恢复一致、纯 inference 案例必须被拒。

---

## §1 Trae 收获与取舍

### 1.1 五个可迁移机制

| # | 机制 | Trae 观察（observation） | 对我们的含义 |
|---|---|---|---|
| M1 | `agent_type × model → skill bundle` | trae 6 / code 6 / design 4 / work 10 个 profile；skills 1–14 | 能力面应按模型能力与任务类型装配，不应全局暴露 |
| M2 | `session × mode → tool_set` | 25 会话 / 10 mode / 每 mode 16–37 工具 | 工具可见性要按会话物化、可审计、同源 |
| M3 | `command → sandbox envelope` | 1,006 条；含 ownerHash/退出码/受限路径；无 trace/session ID | 执行证据必须可归因，否则无法做回归与学习 |
| M4 | `session → checkpoint` | 19 个 git 快照 | paused 必须绑定可恢复检查点，而不是只存状态 |
| M5 | `session → summary memory` | 627 条案例；intent/actions/outcome/learned | 交互可蒸馏，但摘要属 inference，必须过证据门禁 |

### 1.2 五个缺口候选

| 候选 | 机制 | 现有 GAP | 优先级 | 本 SPEC 对应 |
|---|---|---|---|---|
| GAP-T1 | M1 | GAP-02/13/19 | P1 | H1 CapabilityBundle |
| GAP-T2 | M2 | GAP-19/23/25 | P1 | H2 ToolSetSnapshot v2 |
| **GAP-T3** | M3 | GAP-01/24/30 | **P1（硬阻塞）** | H3 ExecutionTrace v2 |
| GAP-T4 | M4 | GAP-20/24 | P2 | H4 Checkpoint |
| GAP-T5 | M5 | GAP-15/29 | P1 | H5 Interaction Evidence Gate |

### 1.3 采用 / 不采用

| 采用 | 不采用 |
|---|---|
| 能力按 `agent_type × model` 装配并留 bundle_id | 照搬 Trae 的 profile 名称与工具名 |
| 工具面按会话物化、hash、diff | 复制其 16–37 个工具的具体清单 |
| 命令/工具执行统一 span + trace_id | 读取或复用其加密 DB、token、prompt |
| checkpoint + resume 的物理载体 | 依赖 Trae 的 git 快照格式 |
| 交互摘要做案例，但先过证据门禁 | 把 `learned` 当事实直接进训练/台账 |

---

## §2 问题与目标

### 2.1 现状（引用既有事实）

| 现状 | 证据 | 影响 |
|---|---|---|
| L2 统一信封缺 `tokens_used/model` | L2-K14 / GAP-17 | 成本与证据边界无法闭合 |
| tool_set 只有单快照 | A1-2 / GAP-25 | 无法审计「LLM 可见工具」与「审批工具」是否同源 |
| 执行链无统一 trace/session ID | GAP-30 / GAP-T3 | 交互案例无法归因，R2 门禁 0% |
| Ticket paused 无 checkpoint 契约 | GAP-20/24 / GAP-T4 | 「可续跑」无法验证 |
| 交互摘要未过证据门禁 | GAP-15/29 / GAP-T5 | inference 可能污染训练与台账 |

### 2.2 目标（可机器判定）

1. **可归因**：任一 L2 会话的交互案例，≥95% 能 join 到 span/命令信封。
2. **可审计**：同一会话/mode 的 tool_set hash 稳定；变更产生 diff；可见性与审批同源。
3. **可恢复**：`paused` Ticket 必须绑定 checkpoint；resume 后产物 hash 一致。
4. **可装配**：`route_signal` 必须携带 `capability_bundle_id` 与 `model_profile_id`；缺一即 `needs_review`。
5. **可学习**：只有 `observation` 级且有交叉证据的案例可进入训练/优化；纯 `inference` 只能留存，不能使用。

### 2.3 非目标

- 不改变 L0/L1 的判定权与事实源。
- 不新增业务生成能力；HCP 只做装配、留痕、门禁。
- 不要求一次性改造所有壳；先 34/3.1/52 三个宿主。
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

HCP 不是第六个子层，而是 L2-K/L2-E 的**横切能力面**；对外不新增 MCP 壳，通过既有 `l2.dreamos` / `l2.dsh`（待建）暴露只读观测。

### 3.2 五个组件

| 组件 | 回答 | 锚点契约 | 主要宿主 |
|---|---|---|---|
| H1 CapabilityBundle | 这次任务该给模型哪些技能/工具/权限 | IF-1 `route_signal` | 34 Router / 47 Registry |
| H2 ToolSetSnapshot v2 | LLM 实际看到哪些工具、何时变过 | IF-7 `tool_set` | 47 / 3.1 / 34 |
| H3 ExecutionTrace v2 | 这次执行属于哪个会话/请求/步骤 | IF-3 `L2Envelope.trace` + IF-7 `span` | 34 / 52 / 3.1 |
| H4 Checkpoint | 断了从哪里续、续得对不对 | IF-4 `Ticket` + ADR-10 | 34 Ticket |
| H5 Interaction Evidence Gate | 这条经验能不能用 | IF-5 `RepairLedger` + ADR-06 | 34 台账 / 33 案例 |

### 3.3 数据流

```
请求
 → H1 选 bundle（agent_type/model/permissions）
 → H2 生成 tool_set 快照（hash + version）
 → H3 每个 span 带 trace_id/session_id/step
 → H4 paused 时写 checkpoint（content hash + git）
 → H5 会话结束生成 InteractionCase，过证据门禁
 → 合格案例进 training_cases / RepairLedger；不合格只留存
```

---

## §4 契约

### 4.1 H1：CapabilityBundle

```json
{
  "bundle_id": "cb-20261117-001",
  "agent_type": "<47 worker_role_id>",
  "model_profile": {
    "model_id": "qwen-max",
    "context_window": 131072,
    "capabilities": ["tool_use", "vision"]
  },
  "skills": ["dream-bugfix-workflow"],
  "tools": ["read_file", "run_command"],
  "permissions": {
    "mode": "read|write|trade",
    "requires_mandate": true
  },
  "source": "registry|manifest|override",
  "hash": "sha256:..."
}
```

约束：
- `bundle_id` 必须可由 `route_signal` 引用；不得只存在于日志。
- `route_signal` 尚未实现（GAP-13）时，先在 34 的 `route_hint` 加同名字段，待契约落地后迁移；不得因此阻塞 H3。
- `tools` 必须是 H2 快照的子集；bundle 不能绕过 tool_set 审批。
- `permissions.mode=trade` 时必须 `requires_mandate=true`，且审批只能 `human/deny`。
- `hash` 对 `{agent_type, model_profile, skills, tools, permissions}` 做 canonical JSON 哈希。

### 4.2 H2：ToolSetSnapshot v2

在 `contracts/tool_set.schema.json` 上扩展，不新建文件：

```json
{
  "tool_set_id": "ts-20261117-003",
  "session_id": "sess-...",
  "mode": "solo_agent",
  "version": 3,
  "hash": "sha256:...",
  "tools": [
    {"name": "read_file", "effect": "read", "requires_mandate": false, "source": "l2.dreamos"}
  ],
  "diff": {"added": [], "removed": [], "changed": []},
  "approval_source": "same_snapshot"
}
```

约束：
- `hash` 对 `tools` 排序后的 canonical JSON 计算；同会话同 mode 且工具未变时 hash 必须稳定。
- 工具可见性与审批必须来自**同一次**快照；禁止各端自建白名单（沿用 IF-7 硬约束）。
- 每次变更生成一条 diff 事件；无 diff 的重复快照不落新版本。
- `version` 单调递增；`tool_set_id` 与 `(session_id, mode, version)` 一一对应。

### 4.3 H3：ExecutionTrace v2

在 `contracts/span.schema.json` 上扩展，禁止私有 trace 字段：

```json
{
  "trace_id": "tr-...",
  "run_id": "run-...",
  "session_id": "sess-...",
  "span_id": "sp-...",
  "parent_span_id": "sp-...",
  "segment": "sense|arrange|capability|compute|gate|memory|scheduler|artifact",
  "tool_call_id": "tc-...",
  "model_id": "qwen-max|none",
  "tokens": {"input": 0, "output": 0},
  "context_hash": "sha256:...",
  "started_at": "2026-11-17T10:00:00Z",
  "ended_at": "2026-11-17T10:00:01Z",
  "stop_reason": "<stop_reason.schema.json 的 7 值之一>",
  "interaction_case_id": "case-..."
}
```

约束：
- `trace_id/run_id/session_id` 三者必填；缺任一不得进入生产验收。
- `model_id=none` ⇒ `tokens={0,0}`；`ended_at ≥ started_at`。
- `interaction_case_id` 可空；非空时必须能反查到案例。
- 命令信封（execution envelope）必须携带同一 `trace_id/session_id`；这是 H3 的验收重点。

### 4.4 H4：Checkpoint

新增 `contracts/checkpoint.schema.json`（P2 才启用）：

```json
{
  "checkpoint_id": "ckpt-...",
  "session_id": "sess-...",
  "ticket_id": "ticket-...",
  "state": "paused",
  "content_hash": "sha256:...",
  "git": {"repo": "...", "commit": "...", "dirty": false},
  "artifacts": [{"path": "...", "hash": "sha256:..."}],
  "created_at": "2026-11-17T10:00:00Z",
  "resume_guard": {"requires_same_hash": true, "max_age_s": 86400}
}
```

约束：
- `paused` Ticket 必须引用 `checkpoint_id`；无 checkpoint 不得声明 `resumable=true`。
- resume 前校验 `content_hash`；不一致时进入 `needs_review`，禁止静默续跑。
- `dirty=true` 时必须在 `artifacts` 中列出未提交文件；否则拒绝。
- checkpoint 只存引用与 hash，不存凭据/大对象。

### 4.5 H5：InteractionCase + Evidence Gate

新增 `contracts/interaction_case.schema.json`：

```json
{
  "case_id": "case-...",
  "session_id": "sess-...",
  "intent": "...",
  "actions": ["..."],
  "outcome": "...",
  "learned": ["..."],
  "evidence": {
    "level": "observation|inference",
    "refs": ["span:sp-...", "checkpoint:ckpt-...", "file:..."],
    "join_rate": 1.0
  },
  "gate": {"admissible": true, "reason": "..."},
  "links": {"trace_id": "tr-...", "ledger_task_id": "fix-..."}
}
```

门禁规则：
- `level=inference` 或 `refs` 为空 ⇒ `admissible=false`；只能留存，不得进入训练/优化/settled。
- 进入 `training_cases` 必须 `level=observation` 且至少 1 条 `span` 或 `checkpoint` 引用。
- `RepairLedger` 的 `settled` 必须引用 `case_ref`；无 case_ref 不得结算。
- `join_rate` 由 H3 计算，不接受手工填写。

### 4.6 与现有契约的映射

| HCP | 现有契约 | 变更方式 |
|---|---|---|
| H1 | IF-1 `route_signal` | 增加 `capability_bundle_id/model_profile_id` |
| H2 | IF-7 `tool_set.schema.json` | 扩展 `tool_set_id/version/hash/diff/approval_source` |
| H3 | IF-3 `L2Envelope.trace` + IF-7 `span` | 增加 `session_id/tool_call_id/interaction_case_id` |
| H4 | IF-4 `Ticket` + ADR-10 | 新增 `checkpoint.schema.json`，paused 引用 |
| H5 | IF-5 `RepairLedger` + ADR-06 | 新增 `interaction_case.schema.json`，settled 引用 case_ref |

---

## §5 门禁

| # | 门禁 | 判据 | 失败后果 |
|---|---|---|---|
| G-L2-12 | 能力装配门禁 | `route_signal` 含 `capability_bundle_id` + `model_profile_id`；tool_set 引用同一 bundle | `needs_review`，不得进入执行 |
| G-L2-13 | 工具面审计门禁 | tool_set 有 hash/version；变更必有 diff；可见性与审批同源 | 审计失败，禁止上线 |
| G-L2-14 | 归因门禁 | 50 会话样本 join_rate ≥95%（案例↔span/信封） | 只允许 shadow，不进生产验收 |
| G-L2-15 | 恢复门禁 | paused 有 checkpoint；resume 后 content_hash 一致 | 标记不可续跑，人工复核 |
| G-L2-16 | 证据门禁 | inference-only 案例不得进 training/optimization/settled | 拒绝入账，记录违规 |

门禁实现要求：
- 每个门禁都有 `pass/fail/skip` 三态与 `reason`；`skip` 必须显式声明原因。
- 门禁结果写入 `evidence.json`，与 H3 span 同 `trace_id`。
- 任一 P0 门禁失败，本轮不得合并；P1 可 shadow。

---

## §6 实施

### 6.1 阶段

| 阶段 | 内容 | 交付 | 门禁 |
|---|---|---|---|
| **P0** | H3 trace 字段 + 命令信封 join；H5 证据门禁 | schema 扩展 + 影子采集 + 负例测试 | G-L2-14 / G-L2-16 |
| **P1** | H1 CapabilityBundle + H2 ToolSet v2 | bundle 注册 + tool_set hash/diff | G-L2-12 / G-L2-13 |
| **P2** | H4 Checkpoint + resume | checkpoint schema + 恢复实验 | G-L2-15 |

### 6.2 任务拆分

| ID | 任务 | 宿主 | 验收 |
|---|---|---|---|
| H-D1 | 扩展 IF-1/IF-3/IF-7 schema；新增 checkpoint/interaction_case schema | 56 contracts | `validate_contracts.py --self-test` 全绿 |
| H-F1 | `route_signal` 注入 bundle/model_profile | 34 Router | 缺字段负例被 G-L2-12 拒 |
| H-F2 | tool_set v2 hash/diff + 同源审批 | 47 / 3.1 / 34 | 同会话 hash 稳定；变更出 diff |
| H-F3 | trace context 贯穿 34/52/3.1 + 命令信封 | 34 / 52 / 3.1 | 50 会话 join_rate ≥95% |
| H-F4 | paused→checkpoint→resume | 34 Ticket | 恢复后产物 hash 一致 |
| H-F5 | InteractionCase 证据门禁 + 台账 case_ref | 34 台账 / 33 | inference-only 负例被拒 |
| H-M1 | 影子回填 50 会话 + 报告 | 33/56 | `reports/hcp-YYYYMMDD/` 可复跑 |

### 6.3 依赖与顺序

- H3 依赖 34 Router/Worker 的 trace 上下文与 52 的计量入口；先做 34，再接 3.1/52。
- H5 依赖 H3 的 `interaction_case_id`；无 H3 时只能做静态负例测试。
- H1 依赖 47 的 registry schema；先加字段，不改变现有工具配额。
- H2 复用 A1-2 的单快照实现，不重写；只补 hash/version/diff/approval_source。
- H4 复用 Ticket paused 与 git 快照，不新建存储引擎。

---

## §7 验收

### 7.1 指标

| 指标 | 目标 | 测量 |
|---|---|---|
| join_rate | ≥95% | 50 会话样本，案例↔span/信封 |
| tool_set 稳定性 | 100% | 同会话同 mode 重复生成 hash 一致 |
| diff 捕获率 | 100% | 人为增删工具必出 diff |
| checkpoint 恢复 | 100% | 恢复后产物 hash 一致 |
| 证据门禁 | 100% 拒绝 | inference-only 负例全部 `admissible=false` |
| 回归 | 0 失败 | 既有 56 契约自检 + 34 相关测试 |

### 7.2 必须失败的负例

1. `route_signal` 缺 `capability_bundle_id` → G-L2-12 fail。
2. 同一 tool_set 被两端各自加白名单 → G-L2-13 fail。
3. 案例只有 `learned`、无 span/checkpoint → G-L2-16 fail。
4. paused Ticket 无 checkpoint → G-L2-15 fail。
5. `model_id=none` 但 `tokens>0` → span schema fail。

### 7.3 证据包

`reports/hcp-YYYYMMDD/` 至少包含：
- `schema_self_test.txt`（28/28 或更新计数）
- `join_report.json`（样本、命中、失败原因）
- `tool_set_diff.jsonl`
- `checkpoint_resume.json`
- `negative_cases.jsonl`
- `README.md`（复跑命令与结论边界）

---

## §8 风险与开放问题

### 8.1 风险

| 风险 | 缓解 |
|---|---|
| 与 A1-2/A1-3/GAP-25/30 重复 | 实施前代码复核；优先补字段，不新建机制 |
| trace 体积与 PII | 采样 + 字段白名单；不落 prompt 原文 |
| checkpoint 存储成本 | 只存引用/hash；git + 短期 artifacts |
| 模型能力表漂移 | `model_profile` 版本化；变更需评审 |
| 摘要自我合理化 | H5 强制 observation 门槛；inference 只留存 |

### 8.2 开放问题

| # | 问题 | 选项 | 建议 |
|---|---|---|---|
| Q1 | bundle 放 47 registry 还是新文件 | A 扩展 `mcp_capabilities.yaml`；B 新建 `capability_bundles.yaml` | A（先扩展，避免双源） |
| Q2 | checkpoint 存 git 还是内容寻址 | A git commit；B CAS + manifest | A 起步，B 作为二期 |
| Q3 | InteractionCase 存 34 还是 33 | A 34 训练库；B 33 案例库 | B 存原始，A 存合格子集 |
| Q4 | H1 是否覆盖 L1 | A 仅 L2；B L1+L2 | A（L1 无生成式装配） |
| Q5 | trace 采样率 | A 100%；B 10% + 失败全采 | B 起步，P0 验证期 100% |

---

## §9 证据索引

- Trae 研究：[RESEARCH-20261117-Trae逆向解析与交互学习-v0.1.md](./docs/RESEARCH-20261117-Trae逆向解析与交互学习-v0.1.md)
- 机制卡：[reports/trae-20261117/mechanism_cards.md](../33-REA逆向解析工程/reports/trae-20261117/mechanism_cards.md)
- 差距映射：[reports/trae-20261117/gap_mapping.md](../33-REA逆向解析工程/reports/trae-20261117/gap_mapping.md)
- 候选缺口：[reports/trae-20261117/gap_candidates.json](../33-REA逆向解析工程/reports/trae-20261117/gap_candidates.json)
- 参考实现：[33-REA逆向解析工程/trae/](../33-REA逆向解析工程/trae/)
- 技能：`~/.trae-cn/skills/harness-reverse-engineering/SKILL.md`

---

## §10 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-17 | 首版：Trae 五机制/五缺口 → HCP 五组件 + 五门禁 + P0–P2 |
