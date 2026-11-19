# SPEC-P0-D3C: Hermes 场外助手 + 双层验收 + 有界自主 + 死信接管

- **版本**: v0.1 ｜ **日期**: 2026-11-19 ｜ **状态**: 🟡 草案（待评审）
- **归属**: 46-DSH架构 / L2-E 执行编排的**例外通道**
- **关系**: 本文是 P0-D3 的主方案；[SPEC-P0-D3B](SPEC-P0-D3B-HERMES-EXECUTOR-v0.1.md) 的 `HermesExecutor` 降级为本文 C 层救援的一种执行实现；决策层由 [SPEC-P0-D3D v0.2](SPEC-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.2.md) 承接（Hermes 只提案，DSH 不直连 Hermes）
- **上游约束**: [DESIGN-DSH-ARCH-UPGRADE-v0.2](DESIGN-DSH-ARCH-UPGRADE-v0.2.md)（ADR-6/9/10）、[P0-D3 Worker Launcher](PROPOSAL-P0-D3-WORKER-LAUNCHER-v0.1.md)、[53 插件规范](../../../53-DSH插件模块/SPEC-53-DSH插件生态接入总规范.md)、[3+3 映射](../../../1-ARCHITECTURE/3+3架构模块映射.md)、[47 registry](../../../47-MCP管理系统/registry/mcp_capabilities.yaml)、[49 交易协议](../../../49-交易框架协议/SPEC.md)
- **一句话**: **DreamOS + DSH 保持强规则主链路；Hermes 只做例外通道的补位、第二双眼睛和有界代办，不做影子主链路。**

---

## §0 结论与角色切分

| 能力 | 归属 | 是否允许 Hermes |
|---|---|---|
| 标准制定 | S 层（OKR/验收标准） | ❌ 只能起草建议，必须人审冻结 |
| 主链路执行 | DSH Worker | ❌ 不得替代 |
| 断路救援 / 能力补齐 | C 层例外通道 | ✅ 有界、可回退 |
| 规则验收 | A 层 `okr_acceptance` | ❌ 规则引擎独占 |
| 语义验收 | A 层第二双眼睛 | ✅ 只产候选裁决，不签核 |
| 最终通过/不通过 | 规则 + 45 + 人工 | ❌ |
| 自主审批 | 有界自主（AutonomyGrant） | ⚠️ 仅低风险可逆 + 四眼原则 |

**核心原则**：Hermes 的所有输出都是**候选证据/候选计划/候选裁决**；Ticket 状态、验收签核、主链路路由仍由 DSH/A 层/45 掌握。

---

## §1 总体架构

```text
S 层：目标 → OKR 节点 + 验收标准（冻结）
        │
        ▼
DSH 强规则主链路（唯一 Ticket 事实源）
  Router → Worker（47 只读工具）→ receipts
        │
        │ 断路：重试耗尽 / 无新证据 / 工具缺失 / 路由未命中 / 用户超范围
        ▼
Hermes 场外助手（C 层例外通道）
  ├─ 诊断与救援（有界预算 + TTL + 最多 2 次交接）
  ├─ 返回：resolved / partial / needs_dsh_retry / needs_human
  └─ 产出：证据、计划、能力缺口记录
        │
        ▼
A 层双层验收
  ├─ 规则门（硬否决）
  └─ Hermes 语义门（候选裁决 + 引用）
        │
        ▼
45 门禁 + 人工（高风险 / 分歧 / U2-U3）
```

### 1.1 为什么不是“Hermes 接管主链路”

- DSH 的确定性、可回放、可审计是系统的核心资产；
- Hermes 是概率型运行时，无法保证同一输入同一输出；
- 一旦 Hermes 进入主链路，Ticket 状态会出现第二个写入者，审计链断裂。

因此 Hermes 必须**在 DSH 之外**，通过交接信封和回执交互。

---

## §2 断路救援协议（DSH ↔ Hermes）

### 2.1 触发分类

| 触发 | 判定 | 典型场景 |
|---|---|---|
| `route_miss` | 意图未命中 L1/L2 路由 | 用户问题超出注册意图 |
| `tool_missing` | 角色能力集内无可用工具 | 47 未注册所需能力 |
| `retry_exhausted` | Worker 重试达到上限 | 连续工具失败 |
| `no_progress` | 多轮无新证据/无新计划 | 同一错误反复出现 |
| `evidence_gap` | 验收缺关键证据 | `evidence_pending` 长期不消 |
| `out_of_scope` | 用户请求超出系统能力 | 新域调研、外部系统操作 |

### 2.2 交接信封（HandoffEnvelope）

```json
{
  "ticket_id": "TK-1",
  "trace_id": "rp-xxx",
  "trigger": "no_progress",
  "goal": "完成 BTC 周度结构调研",
  "failure_class": "manual",
  "attempted_steps": ["recall:ok", "rea:timeout", "rea:timeout"],
  "evidence_refs": ["artifact:TK-1/a.md"],
  "allowed_tools": ["recall", "unified_search"],
  "forbidden_tools": ["place_order", "record"],
  "budget": {"max_attempts": 1, "timeout_s": 300, "max_cost_usd": 0.5},
  "schema_version": "v1"
}
```

硬规则：

1. 只传结构化失败记录与证据引用，**不传 DSH 思维链**；
2. `forbidden_tools` 必须包含全部写工具与交易工具；
3. 信封不可变，救援过程不得修改 goal。

### 2.3 返回契约（RescueResult）

| status | 含义 | 后续 |
|---|---|---|
| `resolved` | 已补齐，附证据 | DSH 重新验收 |
| `partial` | 部分补齐 | DSH 继续或转人工 |
| `needs_dsh_retry` | 给出新计划/新参数 | DSH 用新 Mandate 重试 |
| `needs_human` | 超出有界自主 | 转 `waitsForPerson` |
| `rejected` | 交接不合法/预算不足 | 记录并回退 |

返回必须带：`trace_id`、`summary`、`evidence_refs`、`capability_gap`（可空）、`cost_usd`。

### 2.4 防死锁（核心）

| 机制 | 规则 |
|---|---|
| 交接上限 | 同一 Ticket 最多 2 次（DSH→Hermes） |
| 新信息门槛 | 每次交接必须携带新的 `info_hash`（失败类别+尝试步骤+证据集） |
| 冷却 | 同一 Ticket 两次交接间隔 ≥ 60s |
| 救援预算 | `max_attempts=1`、TTL、成本上限，超限即 `needs_human` |
| 禁止乒乓 | Hermes 不得把同一信封原样退回；退回必须附新计划或缺口 |
| 监管者 | 规则型 supervisor 监控双方；任一方超时/超预算即升级人工 |

> “避免一个 agent 陷入死胡同”不靠更强的 agent，靠**规则化熔断 + 单调进度账本 + 三级升级**。

---

## §3 A 层双层验收

### 3.1 分工

| 层 | 职责 | 输入 | 输出 |
|---|---|---|---|
| S 层 | 制定并冻结 criteria | 目标 | OKR 节点 |
| 规则门 | 硬判定：结果缺失、动作失败、数据造假 | 节点 + result | `pass/degraded/fail` |
| 语义门 | 证据比对、缺口是否补齐 | 冻结 criteria + evidence | 候选裁决 + 引用 |
| 签核 | 最终 verdict | 规则 + 语义 | `pass/degraded/fail` |

Hermes **不得**修改 criteria、不得新增验收维度、不得把 `fail` 改为 `pass`。

### 3.2 冲突裁决矩阵

| 规则 verdict | 语义候选 | 最终 | 说明 |
|---|---|---|---|
| fail | 任意 | **fail** | 规则硬否决 |
| pass | pass + 有引用 | pass | 双通过 |
| pass | pass 无引用 | degraded | 无引用不算通过 |
| pass | fail | degraded | 转人工，不直接推翻规则 |
| degraded | pass + 有引用 | pass | 需抽样复核 |
| degraded | fail | degraded | 保持待验 |
| degraded | 缺失/非法 | degraded | 维持现状（零回归） |

### 3.3 与现有代码的衔接

- 规则门：[okr_acceptance.py](../../../34-前端应用训练系统/core/okr_acceptance.py#L144-L174)；
- 当前 `evidence_backed / gap_closed` 仅标 `evidence_pending`（[L169-L173](../../../34-前端应用训练系统/core/okr_acceptance.py#L169-L173)），由语义门补齐；
- 签名扩展为 `evaluate_nodes(nodes, results, semantic_reviews=None)`，默认行为不变（零回归）。

### 3.4 可信度约束

1. 每条语义裁决必须带 `evidence_refs`，无引用一律 `degraded`；
2. 语义裁决需记录 `model_version`、`prompt_hash`、`confidence`，支持回放；
3. 与规则不一致时不得静默覆盖，必须留 `disagreement` 标记；
4. U2/U3 或高风险节点必须人工抽样复核；
5. 定期用人工标注集校准（κ、假通过率）。

---

## §4 有界自主（Bounded Autonomy）

### 4.1 等级

| 等级 | 权限 | 适用 |
|---|---|---|
| AL0 | 只建议，不执行 | 默认 |
| AL1 | 执行可逆、低风险动作 | 只读/草稿/沙箱 |
| AL2 | 预算内多步执行 + 事后审计 | 调研/工程 |
| AL3 | 单 Ticket 显式授权，例外场景 | 需人工逐单授予 |

### 4.2 授权对象

```json
{
  "grant_id": "AG-1",
  "subject": "hermes-field-assistant",
  "level": "AL2",
  "allowed_tools": ["recall", "unified_search"],
  "max_budget_usd": 1.0,
  "ttl_s": 3600,
  "issued_at": 1795000000,
  "revoked": false,
  "exclusions": ["live", "order", "credential", "prod_db_write", "policy_change", "self_approval"]
}
```

### 4.3 硬排除项（任何等级都拒绝）

- live 交易、下单、撤单、仓位变更；
- 凭据/密钥/权限变更；
- 生产数据库写、生产配置写；
- 策略上线、模型 promote；
- 对自己发起的动作行使审批（四眼原则）。

### 4.4 四眼原则

- Hermes 可以**准备**审批包、**路由**审批、**执行**已批准的低风险动作；
- Hermes 不能作为自己发起动作的唯一审批人；
- 高风险/不可逆动作必须“规则或人工”第二签。

### 4.5 生命周期

`签发 → 使用 → 到期/撤销 → 审计`；撤销必须立即生效，且不依赖进程重启。

---

## §5 DSH 断路事务接管

### 5.1 死信队列

```text
DSH 终态 manual / 路由未命中 / 长尾 paused
  → append dsh_deadletter.jsonl（不改 Ticket）
  → Hermes 租约领取（lease + TTL）
  → 救援 → 写 rescue receipt
  → DSH 重新进入主链路，或转人工
```

### 5.2 死信条目

```json
{
  "entry_id": "DL-1",
  "ticket_id": "TK-1",
  "trace_id": "rp-xxx",
  "trigger": "retry_exhausted",
  "payload": {"failure_class": "manual", "attempts": 3},
  "created_at": 1795000000,
  "status": "pending",
  "claimed_by": "",
  "lease_until": 0,
  "result": null
}
```

### 5.3 接管边界

| 允许 | 禁止 |
|---|---|
| 路由未命中、工具缺失、证据缺口、重复失败 | 安全事件、实盘故障、策略上线 |
| 只读诊断、沙箱验证、产出证据/计划 | 直接改 Ticket、直接写生产库、直接下单 |

### 5.4 能力缺口回流

每次救援必须产出 `capability_gap`，回流 S 层。北极星指标：

- `hermes_intervention_rate`：Hermes 介入占比，应逐季下降；
- `repeat_intervention_rate`：同类断路重复介入率，应趋近 0。

若持续上升，说明 Hermes 正在变成影子主链路，必须收紧。

---

## §6 代码契约（本次落地）

| 模块 | 路径 | 职责 |
|---|---|---|
| 交接协议 | `34-.../core/hermes_handoff.py` | 信封、触发分类、进度账本、防乒乓 |
| 场外助手 | `34-.../core/hermes_field_assistant.py` | 有界救援、预算、升级 |
| 双层验收 | `34-.../core/dual_acceptance.py` | 语义候选与规则裁决合并 |
| 有界自主 | `34-.../core/bounded_autonomy.py` | AutonomyGrant、硬排除、四眼 |
| 死信队列 | `34-.../core/dsh_deadletter.py` | append/claim/complete + 租约 |

所有模块要求：

- Python 3.10+，标准库优先；
- FAIL-OPEN：非法输入返回安全默认，不抛异常；
- 只读/无副作用：不写 Ticket、不写 receipt；
- 线程安全：JSONL 追加与租约需加锁。

---

## §7 与 46/53/3+3/47/49 的对齐

| 约束 | 落地 |
|---|---|
| 46 ADR-6：Worker 不自证 | Hermes 只产候选裁决 |
| 46 职责边界：A 层不拥有执行 | Hermes 验收与救援使用不同身份/会话 |
| 46 Watchdog 不改任务 | 巡查只产 finding，修复走救援通道 |
| 53：外部运行时治理 | 登记 `external_runtimes`，deny-by-default |
| 53 ADR-2：不替代 MCP | 只经 47 壳访问能力 |
| 3+3：L2 对 L1 只读 | 禁止交易/实盘工具 |
| 3+3：主链路强规则 | Hermes 不进 Router/Worker 热路径 |
| 47：工具面 SSoT | 角色能力映射只在 47，53 不复制 |
| 49：实盘永不 MCP | 硬排除 live/order |

---

## §8 验收标准

| ID | 门禁 | 通过标准 |
|---|---|---|
| G0 | 契约 | 5 模块单测全绿；非法输入 FAIL-OPEN |
| G1 | 防死锁 | 同一 Ticket 第 3 次交接必拒；无新信息必拒 |
| G2 | 双层验收 | 冲突矩阵 7 种组合全部符合预期 |
| G3 | 零回归 | `semantic_reviews=None` 时 A 层行为字节等价 |
| G4 | 有界自主 | 硬排除项 100% 拒绝；过期/撤销即时生效 |
| G5 | 四眼 | 自审批 100% 要求第二签 |
| G6 | 死信 | 并发 claim 仅 1 个成功；租约过期可重领 |
| G7 | 无副作用 | 不写 Ticket/receipt；输入对象不被修改 |
| G8 | 可观测 | 每次救援/裁决带 trace_id 与能力缺口 |

---

## §9 落地计划

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | 5 个核心模块 + 单测 + A 层可选集成 | 本次落地 |
| Phase 2 | WorkerLauncher 终态写死信（开关默认关） | 待评审 |
| Phase 3 | Hermes 真实运行时接入（headless/MCP client 验证） | 待 Phase 0 spike |

---

## §10 风险与开放问题

| ID | 风险/问题 | 处理 |
|---|---|---|
| R1 | Hermes 裁决过于宽松 | 引用强制 + 人工抽样 + 假通过率门禁 |
| R2 | 与执行者同模型导致相关性偏差 | 独立会话；高风险跨模型复核 |
| R3 | 救援变成长期依赖 | 介入率指标 + 能力缺口回流 |
| R4 | 自主授权被滥用 | 有界授权 + 硬排除 + 四眼 + 撤销 |
| R5 | 死信队列无界增长 | 租约 + TTL + 人工兜底 + 告警 |
| Q1 | Hermes headless 入口是否可用 | Phase 0 spike |
| Q2 | Hermes 是否支持 MCP client | Phase 0 spike |
| Q3 | 语义裁决成本/延迟 | 分层触发，仅模糊节点上 Hermes |
