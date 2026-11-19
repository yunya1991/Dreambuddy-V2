# SPEC-P0-D3D: 脑暴决策闭环（Brainstorm Decision Loop）

- **版本**: v0.1 ｜ **日期**: 2026-11-19 ｜ **状态**: 🗄 已归档（被 v0.2 取代）
- **归属**: 46-DSH架构 / L2-K 决策编排
- **关系**: 本文是 [P0-D3C 场外助手](SPEC-P0-D3C-HERMES-FIELD-ASSISTANT-v0.1.md) 的决策层扩展；D3C 负责“谁去补”，D3D 负责“补什么、为什么、是否采纳”
- **评审清单**: [REVIEW-CHECKLIST-P0-D3D](REVIEW-CHECKLIST-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.1.md)
- **架构评审意见**: [REVIEW-ARCH-P0-D3D](REVIEW-ARCH-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.1.md)
- **上游约束**: [DESIGN-DSH-ARCH-UPGRADE-v0.2](DESIGN-DSH-ARCH-UPGRADE-v0.2.md)、[GateFlow](../../../3.1-FRONTEND/src/lib/task-board/gate-flow.ts)、[GateGovernance](../../../3.1-FRONTEND/src/lib/task-board/gate-governance.ts)、[3+3 映射](../../../1-ARCHITECTURE/3+3架构模块映射.md)、[47 registry](../../../47-MCP管理系统/registry/mcp_capabilities.yaml)、[49 交易协议](../../../49-交易框架协议/SPEC.md)
- **一句话**: **执行归 DSH，提案归 Hermes，决策归脑暴 Council，授权归人；Hermes 永远不直接指挥 DSH。**

---

## §0 结论与五条不变式

### 0.1 为什么需要 D3D

D3C 解决了“DSH 断路后谁来补”，但留下一个结构性风险：如果 Hermes 补完直接给 DSH 派活，它就变成了事实上的指挥官。D3D 在两者之间插入**脑暴决策层**，把“提案”和“执行”彻底分开。

### 0.2 五条不变式（Hard Invariants）

| ID | 不变式 | 违反后果 |
|---|---|---|
| **HI-1** | Hermes 不得向 DSH 下发任务；DSH 可在执行中向 Hermes 发起 `AssistRequest` | 指挥权旁落，审计链断裂 |
| **HI-2** | 任何 DSH 重做必须引用 `DecisionRecord.adopted` | 无法回溯“为什么做” |
| **HI-3** | 飞书是授权/告警通道，GateFlow 是唯一审批真相 | 双账本、审批失效 |
| **HI-4** | 决策采纳以回测/正常推进门禁为准，不以 Council 投票为准 | 脑暴空转、决策不可验证 |
| **HI-5** | Presentation 层不得修改 Core Facts；成品必须过 Fact Gate | 外表污染内在 |

### 0.3 端到端闭环

```text
DSH 执行
  ├─ 能力不足 → AssistRequest → Hermes 辅助 → DSH 继续
  ├─ 用户要 Word/PPT/图表 → Presentation Assist → Fact Gate
  → A 层验收（规则 + 语义）
  → fail/degraded/缺口 → 立案 BrainstormTicket
  → Hermes 调研/设计/提案/异议（可用自己的工具）
  → 脑暴 Council（32 辩论 + 45 评测 + 48 实验）
  → DecisionRecord
  → 人工/飞书授权（高风险或授权不足时）
  → DSH 按 DecisionRecord 重新执行
  → A 层再验收
```

---

## §1 角色与权责

| 角色 | 定位 | 能做 | 不能做 |
|---|---|---|---|
| **DSH** | 专家内核 + 执行层 | 执行、回执、证据；产出 `CanonicalFactBundle`；能力不足时可向 Hermes 发起 `AssistRequest` | 接受 Hermes 下发的任务；自行决定重做方案 |
| **A 层** | 验收入口 | 验收、识别缺口、立案；硬门禁校验最终结果与表达事实 | 设计重做方案；修改标准 |
| **Hermes** | 研究员/提案人/异议者/外援/表达层 | 响应 `AssistRequest`；按 FactBundle 渲染 Word/PPT/图表；调研、设计任务、责任域建议、使用工具、提出反对意见 | 向 DSH 派活；改 Gate；改 Core Facts；自己批准；终审 |
| **Brainstorm Council** | 决策层 | 辩论、对照实验、形成 DecisionRecord | 代替人工做高风险终审 |
| **飞书审批** | 人类授权通道 | 真实审批、催办、超时升级 | 成为第二套审批真相 |
| **人工** | 最终责任主体 | 高风险授权/否决 | 被 Hermes 代替签字 |

### 1.1 Hermes 的能力边界

允许：

- 响应 DSH 的 `AssistRequest`，在授权范围内辅助完成执行；
- 按 `CanonicalFactBundle` 渲染 Word/PDF/PPT/Excel/图表，不修改核心事实；
- 使用 Hermes 自带工具与 47 MCP 能力进行调研（`hermes -z` / ACP / MCP client）；
- 读取数据、代码、日志、历史 DecisionRecord、认知记忆；
- 在沙箱/回测环境设计并运行对照实验；
- 提出多方案、反例、反对意见。

禁止：

- 直接写生产库、改生产配置、下单/撤单/实盘操作；
- 直接创建 DSH Ticket 或调用 Worker dispatch；
- 修改 GateFlow、GatePolicy、验收标准；
- 作为自己提案的终审人或审批人。

---

## §2 立案：BrainstormTicket

### 2.1 触发条件

| 触发 | 来源 | 是否立案 |
|---|---|---|
| A 层 `fail/degraded` 且缺口非平凡 | `okr_acceptance` / `dual_acceptance` | ✅ |
| GateFlow `node.rejected` 且需要重做 | `gate-flow.ts` | ✅ |
| Hermes 场外助手返回 `capability_gap` / `needs_human` | `hermes_field_assistant` | ✅ |
| 用户显式要求“讨论/脑暴/给方案” | 前端/飞书 | ✅ |
| DSH 执行中发现能力不足，需要外部辅助 | Worker/DSH | ❌ 不立案，走 `AssistRequest` |
| 普通重试可解决的瞬时错误 | Worker retry | ❌ 直接重试 |
| 标准明确、方案唯一的小修复 | A 层 | ❌ 直接重做 |

### 2.2 分级（决定脑暴成本）

| 级别 | 条件 | 决策路径 |
|---|---|---|
| **T0 轻** | 低风险、单方案、标准明确 | Hermes 提案 + 规则核验，不开发布会 |
| **T1 中** | 有 2 个以上方案或中等不确定性 | Hermes + 1 名领域评审 + 快速评测 |
| **T2 高不确定** | 证据冲突、跨域、影响面大 | 完整 Council + 至少 1 个对照实验 |
| **T3 高风险** | live、不可逆、安全、策略上线 | Council 只给建议，人工终审 |

### 2.3 状态机

```text
open → researching → proposed → debating → experimenting
     → decided → authorized → dispatched → closed
                      ↘ escalated（超时/分歧过大）
                      ↘ cancelled（缺口消失/重复）
```

- 事件 append-only；
- 每个状态有时间盒，超时按级别升级；
- 同一 `gap_key` 只允许一个活跃 Ticket（幂等）。

### 2.4 DSH 主动委托 Hermes（AssistRequest）

DSH 执行中发现能力不足时，可直接发起 `AssistRequest`。这是**DSH 调用外援**，不是 Hermes 指挥 DSH。

```json
{
  "assist_id": "AS-1",
  "ticket_id": "TK-1",
  "trace_id": "rp-xxx",
  "task_type": "research|presentation|analysis",
  "need": "需要补充某项数据/工具/调研",
  "expected_output": "可被 DSH 消费的证据或结果",
  "fact_bundle_id": null,
  "allowed_tools": ["recall", "unified_search"],
  "forbidden_tools": ["place_order", "record"],
  "budget": {"max_attempts": 1, "timeout_s": 300, "max_cost_usd": 0.5},
  "read_only": true
}
```

硬约束：

| 约束 | 说明 |
|---|---|
| 方向 | 只能 DSH → Hermes；Hermes 不得反向派工 |
| 产出 | Hermes 只返回 `AssistResult`，不创建 Ticket、不调 Worker |
| 权限 | 默认只读；需要写操作时必须带 `AutonomyGrant` / `ApprovalGrant` |
| 验收 | A 层硬门禁对最终结果负责，Hermes 结果不豁免 |
| 预算 | 次数/TTL/成本受限；超限转 `BrainstormTicket` |
| 审计 | 带 `assist_id + trace_id`，可回放 |

返回契约：

```json
{
  "assist_id": "AS-1",
  "status": "resolved|partial|needs_brainstorm|rejected",
  "output": "可被 DSH 消费的结果/证据",
  "evidence_refs": ["EV-1"],
  "capability_gap": null,
  "cost_usd": 0.0,
  "trace_id": "rp-xxx"
}
```

**AssistRequest 与 BrainstormTicket 的分界**：

- 有明确产出、无需方案选择 → `AssistRequest`；
- 需要方案比较、对照实验、责任域重排 → `BrainstormTicket`。

### 2.5 Presentation Assist（事实锁定的表达层）

DSH = Expert Core，负责事实与结论；Hermes = Presentation Worker，负责表达与交付。方向仍然是 **DSH → Hermes**，Hermes 不反向指挥 DSH。

#### 2.5.1 三类信息

| 类型 | 来源 | Hermes 可做什么 |
|---|---|---|
| **Core Facts** | DSH `CanonicalFactBundle` | 引用、排版、可视化；不得改值/结论 |
| **Derived Facts** | Hermes 基于 Core 计算 | 必须给公式与输入 `fact_id`，可复算 |
| **Supplementary Context** | Hermes 外部调研 | 必须标注“补充信息”+引用；不得与 Core 矛盾 |

#### 2.5.2 契约

**CanonicalFactBundle**

```json
{
  "bundle_id": "FB-1",
  "trace_id": "rp-xxx",
  "facts": [
    {
      "fact_id": "F-1",
      "name": "BTC 周度收益率",
      "value": 0.123,
      "unit": "%",
      "as_of": "2026-11-19",
      "source_ref": "19-DAL/...",
      "content_hash": "sha256:...",
      "confidence": 0.82,
      "caveat": "样本外未验证"
    }
  ],
  "conclusions": ["..."],
  "risks": ["..."],
  "citations": ["..."]
}
```

**PresentationRequest**

```json
{
  "request_id": "PR-1",
  "ticket_id": "TK-1",
  "format": "docx|pdf|pptx|xlsx|html|chart",
  "audience": "投委会|内部|客户",
  "template": "research-report-v3",
  "language": "zh-CN",
  "required_sections": ["结论", "证据", "风险", "附录"],
  "allow_supplementary_research": true,
  "fact_bundle_id": "FB-1"
}
```

**PresentationArtifact**

```json
{
  "artifact_id": "PA-1",
  "uri": "outputs/report.docx",
  "format": "docx",
  "renderer": "hermes|office-plugin",
  "fact_bundle_hash": "sha256:...",
  "fact_refs": ["F-1", "F-2"],
  "supplementary_refs": ["NEWS-1"],
  "consistency_report": "CR-1"
}
```

**FactConsistencyReport**

```json
{
  "report_id": "CR-1",
  "matched": 42,
  "missing": 0,
  "extra": 1,
  "changed": 0,
  "contradictions": [],
  "verdict": "pass|degraded|fail"
}
```

#### 2.5.3 流程

```text
DSH ExpertCore
  → CanonicalFactBundle（冻结）
  → PresentationRequest
  → Hermes 渲染（Word/PPT/图表）
  → FactConsistencyGate
      pass → A 层验收 → 交付
      degraded → 标注/补证/人工
      fail → 打回重做
```

#### 2.5.4 硬约束

1. Hermes 不得修改 Core Facts 的数值、单位、日期、结论、置信度、风险表述；
2. 派生数字必须给公式和输入 `fact_id`，可复算；
3. 补充信息必须标注来源，且不能与 Core Facts 矛盾；
4. 图表数据只能来自 FactBundle；坐标轴/刻度不得误导；
5. 成品必须带 provenance：`facts: DSH / render: Hermes / verified: yes|no`；
6. 未通过 Fact Gate 的成品只能标 `DRAFT`，不得对外；
7. 文档生成在沙箱内；敏感数据不外传，外部调研走白名单；
8. 对外发布需人工授权；内部交付仅通知。

#### 2.5.5 渲染器

渲染器可插拔：Hermes 自带工具、现有 office-plugin（docx/pptx/xlsx/pdf）均可，**契约不变**。选择标准是格式支持、模板兼容、渲染质量与成本，不是身份。

#### 2.5.6 何时使用

- 用户需要 Word/PDF/PPT/Excel/图表/可视化报告；
- DSH 简单文本可直接渲染；复杂版式、图表、模板化研报走 `Presentation Assist`；
- 对外发布走审批；内部交付只通知。

---

## §3 Hermes 提案：ProposalBundle

### 3.1 必填内容

```json
{
  "ticket_id": "BT-1",
  "trace_id": "rp-xxx",
  "options": [
    {
      "option_id": "A",
      "summary": "方案摘要",
      "tasks": [
        {"title": "任务", "owner_domain": "34", "capability_ids": ["..."], "acceptance": "..."}
      ],
      "assumptions": ["假设"],
      "risks": ["风险"],
      "falsification": ["什么情况下此方案失败"],
      "expected_evidence": ["需要哪些证据"]
    }
  ],
  "dissent": ["反对意见/最强反例"],
  "recommended": "A",
  "confidence": 0.0,
  "evidence_refs": ["..."],
  "model_version": "...",
  "prompt_hash": "..."
}
```

### 3.2 约束

1. 至少 1 个方案；T1 以上至少 2 个；
2. 每个方案必须有 `falsification`，否则不得进入辩论；
3. `dissent` 必须保留，不允许被摘要删除；
4. `tasks` 只是建议，不是派工单；不得直接进入 DSH；
5. 无证据引用的结论标记 `unsupported`，不得作为推荐方案。

---

## §4 脑暴 Council

### 4.1 组成

| 席位 | 来源 | 职责 |
|---|---|---|
| 主席 | 规则/人工 | 控时、裁决流程、保留否决权 |
| 提案人 | Hermes | 陈述方案与证据 |
| 反方 | 32 对抗性辩论 Bot | 最强反驳、找反例 |
| 领域评审 | DSH 子 Agent / 领域 Agent | 评估可行性与责任域 |
| 实验执行 | 45 评测 / 48 沙箱与回测 | 跑对照实验、统计检验 |
| 记录员 | Hermes 秘书 | 语义汇总，不计票 |

> Hermes 只有一票（作为提案人）；不得兼任主席、反方、实验执行或终审。

### 4.2 流程与时间盒

| 阶段 | 产出 | 时间盒（T2） |
|---|---|---|
| 提案陈述 | ProposalBundle | 30 min |
| 反方质疑 | DissentRecord | 30 min |
| 领域评审 | FeasibilityNote | 30 min |
| 对照实验 | ExperimentResult | 按实验 SLA |
| 决策 | DecisionRecord | 30 min |

- 最多 2 轮辩论；第 3 轮强制升级人工；
- 无新证据不得重复辩论（防死循环）；
- 实验未完成不得进入 `decided`（T2/T3）。

---

## §5 证据与实验：可信度四道门

### 5.1 EvidenceBundle（真实性）

```json
{
  "evidence_id": "EV-1",
  "source_type": "data|code|log|doc|backtest|sandbox",
  "source_uri": "...",
  "content_hash": "sha256:...",
  "collected_at": 1795000000,
  "collector": "hermes|dsh|45|48",
  "replay_cmd": "...",
  "trace_id": "rp-xxx"
}
```

规则：

- 无 `content_hash` 或 hash 不匹配 → 不得作为决策依据；
- 无 `replay_cmd` 的关键证据 → 标记 `non_replayable`；
- 证据原文不含密钥；敏感字段脱敏。

### 5.2 四道门

| 门 | 判据 | 不通过处理 |
|---|---|---|
| 真实性 | 来源可追溯、hash 匹配、可重放 | 退回补证 |
| 可证伪 | 每个方案有失败条件与反例 | 退回重写 |
| 对照实验 | 有对照组、样本量、指标、阈值 | 不得 `decided` |
| 统计门 | 效应量、置信区间、多重比较校正 | 标记不显著，禁止称“有效” |

无法实验的问题必须标记 `judgment`，并强制人工确认。

### 5.3 实验落点

- 沙箱：`48-涌现架构/experiments/d2b_engineering/sandbox.py`
- 假设实验：`48-涌现架构/experiments/e2_hypothesis/run_e2.py`
- 耦合/反事实：`48-涌现架构/experiments/e3_coupling/`
- 统计与评测：45 评测系统
- 反思度量：`48-涌现架构/metrics/e4b_reflection.py`

---

## §6 DecisionRecord（决策）

### 6.1 结构

```json
{
  "decision_id": "DR-1",
  "ticket_id": "BT-1",
  "chosen_option": "A",
  "rationale": "为什么选 A",
  "evidence_refs": ["EV-1", "EXP-1"],
  "dissent": ["反方意见"],
  "confidence": 0.0,
  "conditions": ["生效条件"],
  "owner": "human|rule",
  "status": "draft|reviewed|adopted|rejected|superseded",
  "expires_at": 0,
  "trace_id": "rp-xxx"
}
```

### 6.2 采纳门禁（Adoption Gate）

**决策是否采纳，以“能否过回测或正常推进”为准，不以 Council 投票为准。**

| 决策类型 | 采纳门禁 | 不通过处理 |
|---|---|---|
| 量化/策略/参数 | 45 回测门 + 统计门（效应量/CI/多重比较） | 不得 adopted |
| 工程/代码变更 | 测试/CI + 回归门 | 不得 adopted |
| 研报/图表/文档（Presentation） | FactLock + Fact Gate + A 层 | 不得交付 |
| 只读/非代码/常规运维 | A 层硬门禁 + 正常推进 | 退回或转人工 |
| 无适用门禁 | 人工确认 | 不得自动 adopted |
| T3 高风险/live/不可逆 | 人工终审（Council 仅建议） | 不得自动 adopted |

- Council 结论是**建议**，不是采纳票；
- Hermes 永远不是终审人；
- `dissent` 必须原样保留；
- 采纳后仍需 A 层对最终结果做硬门禁校验。

### 6.3 采纳与失效

- 只有 `adopted` 的 DecisionRecord 可被 DSH 消费；
- 超过 `expires_at` 或上游证据失效 → `superseded`，DSH 不得继续使用；
- 决策被推翻必须产生新 DecisionRecord，不允许原地改写。

### 6.4 FactLock Gate（表达层事实门）

| verdict | 条件 | 动作 |
|---|---|---|
| **pass** | Core Facts 全部匹配；`changed=0`；无矛盾；关键引用齐全 | 允许交付 |
| **degraded** | 补充信息未标注 / 次要 caveat 缺失 / 格式问题 | 标注 `DRAFT` / 补证 / 人工 |
| **fail** | 核心数字/结论/风险被改；与 Core 矛盾；伪造引用；删除重大风险 | 打回重做 |

规则：

- 核心数字、单位、日期、结论、置信度、风险表述不可变；
- 派生数字必须可复算，并标注输入 `fact_id`；
- 图表数据只能来自 FactBundle；
- 未过门禁只能标 `DRAFT`；
- provenance 必须包含 `facts: DSH / render: Hermes / verified: yes|no`。

---

## §7 飞书授权桥（Feishu Authorization Bridge）

### 7.1 定位

飞书是**人类授权通道**，不是第二套审批真相。GateFlow 仍是唯一审批状态机。

```text
GateFlow 需要人工授权
  → Hermes 发起真实飞书审批（消息/审批单）
  → 人批准/否决
  → 签名 ApprovalGrant 回写 GateFlow
  → GateFlow 推进
```

### 7.2 ApprovalRequest / ApprovalGrant

```json
{
  "request_id": "AR-1",
  "ticket_id": "BT-1",
  "gate_run_id": "GF-1",
  "node_id": "acceptance",
  "action_scope": ["rework.dispatch"],
  "risk": "high",
  "requested_by": "hermes-secretary",
  "approvers": ["human:owner"],
  "deadline": 1795003600,
  "fallback_policy": "escalate|block"
}
```

```json
{
  "grant_id": "AG-2",
  "request_id": "AR-1",
  "approver": "human:owner",
  "scope": ["rework.dispatch"],
  "ttl_s": 3600,
  "signature": "...",
  "issued_at": 1795000000
}
```

### 7.3 超时规则

| 类型 | 超时行为 |
|---|---|
| Gate 验收 / 高风险门 | `remind / escalate / block`，**永不自动通过** |
| 非 Gate 的紧急运维任务（可逆、低/中风险） | 可预授权自动审批，但必须有策略、预算、TTL、审计 |
| live / 不可逆 / 安全事件 | 永不自动审批 |

> 现有 `approval_agent.py` 的“AI 代决”属于交易审批例外路径，不得扩展到治理 Gate。

### 7.4 授权后执行

人工批准后：

1. 生成 `ApprovalGrant`；
2. 与 D3C 的 `AutonomyGrant` 绑定；
3. Hermes 只能在 `scope + ttl` 内执行后续；
4. 每个动作带 `grant_id + trace_id` 审计；
5. 超范围立即拒绝并升级。

### 7.5 通知/授权分级（避免审批疲劳）

| 场景 | 飞书动作 | 是否需要审批 |
|---|---|---|
| 常规只读类 | 可选通知 | ❌ 不需要 |
| 非代码变更（文档/配置说明/报告） | 通知 | ❌ 不需要 |
| 重要决策/紧急事务（非高风险、可逆） | 通知 + 事后审计 | ❌ 不需要 |
| 参与脑暴 | 仅消息告知（会议纪要抄送） | ❌ 不需要 |
| 内部研报/图表交付 | 通知 | ❌ 不需要 |
| 对外发布研报/图表/文档 | 真实飞书审批 | ✅ 必须 |
| 重要告警 | 告警消息 | ❌ 不需要（但需响应） |
| 重要授权（高风险/不可逆/live/安全/策略上线/生产写） | 真实飞书审批 | ✅ 必须 |
| Gate 验收 / 高风险门 | 真实飞书审批 + 回写 GateFlow | ✅ 必须 |
| 紧急运维超时（可逆、低/中风险） | 预授权自动审批单 + 消息 | ⚠️ 预授权范围内可自动 |

**硬边界**：live、不可逆、安全事件、策略上线、生产库写，永远需要人工授权，不适用“正常推进”。

---

## §8 DSH 消费：唯一入口

### 8.1 禁止直连

- Hermes 不持有 DSH task/worker 的写凭证；
- DSH Router 不接受 `source=hermes` 的直接任务；
- 所有重做必须带 `decision_id`，且 `DecisionRecord.status == adopted`。

### 8.2 派发流程

```text
DecisionRecord.adopted
  → BrainstormDispatcher 生成 ReworkPackage
  → DSH Router 创建 Ticket（source=brainstorm, decision_id=...）
  → Worker 执行
  → A 层再验收
```

`ReworkPackage` 包含：任务、责任域、能力 ID、验收判据、截止时间、依赖、证据要求。

### 8.3 幂等与回放

- 幂等键：`(decision_id, task_index)`；
- 重复派发不产生重复 Ticket；
- 每个 Ticket 可回放到 `decision_id` 与 `evidence_refs`。

---

## §9 效率设计

| 机制 | 规则 |
|---|---|
| 分级 | T0/T1/T2/T3，避免所有缺口都开 Council |
| 外援轻量 | DSH 能力不足优先 `AssistRequest`，不立案 |
| 表达优先 | Word/PPT/图表走 `Presentation Assist`，不立案 |
| 默认通知 | 常规只读/非代码/脑暴参与只发消息，不发起审批 |
| 批量 | 相似 `gap_key` 合并立案 |
| 缓存 | 证据、实验、DecisionRecord 可复用，需校验有效期 |
| 异步 | 飞书审批、实验跑批异步；不阻塞主链路 |
| 时间盒 | 每阶段有 SLA；超时升级，不无限讨论 |
| 摘要 | 一页纸 `SecretaryDigest` + 结构化 JSON，不拉长对话 |
| 复用 | 历史相似决策优先，避免重复脑暴 |

---

## §10 与 46/53/3+3/47/49 的对齐

| 约束 | 落地 |
|---|---|
| 46 ADR-6：Worker 不自证 | A 层 + Council + 人工共同判定 |
| 46 A 层不拥有执行 | A 层只立案，不派工 |
| 46 Watchdog 不改任务 | 巡查只产 finding，立案走 D3D |
| 53：外部运行时治理 | Hermes 按 `external_runtimes` 登记，deny-by-default |
| 53 ADR-2：不替代 MCP | Hermes 只经 47 壳访问能力 |
| 3+3：L2 对 L1 只读 | 禁止交易/实盘工具 |
| 3+3：主链路强规则 | DSH 只消费 adopted DecisionRecord |
| 47：工具面 SSoT | 能力 ID 只在 47，53 不复制 |
| 49：实盘永不 MCP | T3 人工终审，Hermes 无 live 权限 |

---

## §11 数据契约（落地模块建议）

| 模块 | 路径 | 职责 |
|---|---|---|
| 外援请求 | `34-.../core/assist_request.py` | AssistRequest/AssistResult、只读与预算约束 |
| 表达契约 | `34-.../core/presentation_contract.py` | PresentationRequest / PresentationArtifact |
| 事实锁 | `34-.../core/fact_lock.py` | CanonicalFactBundle / FactManifest |
| 事实门 | `34-.../core/presentation_gate.py` | FactConsistencyReport / verdict |
| 立案与状态机 | `34-.../core/brainstorm_ticket.py` | Ticket 创建、分级、幂等、状态迁移 |
| 提案 | `34-.../core/proposal_bundle.py` | ProposalBundle 校验、dissent 保留 |
| 证据 | `34-.../core/evidence_bundle.py` | hash/replay 校验、脱敏 |
| 实验 | `34-.../core/experiment_result.py` | 对照组、指标、统计门 |
| 决策 | `34-.../core/decision_record.py` | DecisionRecord 生命周期与终审 |
| 飞书桥 | `34-.../core/feishu_authorization_bridge.py` | ApprovalRequest/Grant、回写 GateFlow |
| 派发 | `34-.../core/brainstorm_dispatcher.py` | 只消费 adopted，生成 ReworkPackage |

所有模块要求：标准库优先、FAIL-OPEN、线程安全、不直接写 Ticket/GateRun。

---

## §12 验收标准

| ID | 门禁 | 通过标准 |
|---|---|---|
| G0 | 契约 | 11 个模块单测全绿；非法输入 FAIL-OPEN |
| G1 | 指挥权 | Hermes 直连 DSH 100% 被拒 |
| G2 | 决策引用 | 所有重做 Ticket 100% 带 adopted decision_id |
| G3 | 证据 | 无 hash/不可重放证据不得进入 DecisionRecord |
| G4 | 实验 | T2/T3 无 ExperimentResult 不得 decided |
| G5 | 异议 | dissent 在 DecisionRecord 中 100% 保留 |
| G6 | 飞书 | 审批结果只回写 GateFlow，无双账本 |
| G7 | 超时 | Gate 超时 100% 不自动通过 |
| G8 | 授权 | 超 scope/TTL 动作 100% 拒绝 |
| G9 | 效率 | T0 不进入 Council；T2 有时间盒与升级 |
| G10 | 可观测 | 全链路 trace_id + decision_id + evidence_refs |
| G11 | 外援方向 | `AssistRequest` 只能 DSH→Hermes；Hermes 反向派工 100% 拒绝 |
| G12 | 通知分级 | 常规只读/非代码/脑暴参与 100% 不触发审批；高风险 100% 触发 |
| G13 | 事实保真 | Core Facts 未授权改动 0；矛盾 0 |
| G14 | 表达溯源 | 成品 100% 带 `fact_bundle_hash` + provenance + `DRAFT/verified` 标识 |

---

## §13 落地阶段

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | 7 个核心契约 + 单测 | 待评审后启动 |
| Phase 2 | GateFlow `node.rejected` → 立案 → 派发闭环 | 待 Phase 1 |
| Phase 3 | 飞书审批桥 + 超时策略 | 待 Phase 2 |
| Phase 4 | Hermes 真实运行时接入（Phase 0 spike 后） | 待 D3C Phase 3 |

---

## §14 风险与开放问题

| ID | 风险/问题 | 处理 |
|---|---|---|
| R1 | 脑暴变成拖延 | 分级 + 时间盒 + 最多 2 轮 |
| R2 | Hermes 影响力过大 | 一票 + 无终审 + dissent 保留 |
| R3 | 实验成本高 | T0/T1 免实验；T2 只跑关键假设 |
| R4 | 飞书与 GateFlow 双账本 | 只允许签名 Grant 回写 |
| R5 | 超时自动审批被滥用 | 仅紧急运维类 + 预授权 + 审计 |
| R6 | 证据造假/幻觉 | hash + replay + 抽样复核 |
| R7 | DSH 借 AssistRequest 绕过决策 | 仅只读/小预算；A 层硬门禁不豁免；超限转 BrainstormTicket |
| R8 | 通知过多导致漏审 | 分级 + 聚合 + 去重；高风险强制审批 |
| R9 | 渲染过程改数字/删风险 | FactLock + Fact Gate + 抽样复核 |
| R10 | 外部调研泄露敏感数据 | 沙箱 + 白名单 + 脱敏 |
| Q1 | T1 是否允许全自动采纳 | 待定：建议仅低风险 |
| Q2 | Council 是否常设 | 建议按需组建 |
| Q3 | 实验 SLA 与算力预算 | 待 45/48 评估 |
