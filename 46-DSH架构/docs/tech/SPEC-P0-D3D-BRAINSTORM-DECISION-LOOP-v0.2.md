# SPEC-P0-D3D: 脑暴决策闭环（Brainstorm Decision Loop）

- **版本**: v0.2 ｜ **日期**: 2026-11-19 ｜ **状态**: 🟡 草案（按架构评审修订；Phase 1 契约已落地）
- **归属**: 46-DSH架构 / L2-K 决策编排
- **整体架构**: [ARCHITECTURE-DSH-HERMES-END-TO-END-v1.0](ARCHITECTURE-DSH-HERMES-END-TO-END-v1.0.md)
- **关系**: 本文是 [P0-D3C 场外助手](SPEC-P0-D3C-HERMES-FIELD-ASSISTANT-v0.1.md) 的决策层扩展；D3C 负责“谁去补”，D3D 负责“补什么、为什么、是否采纳”
- **评审清单**: [REVIEW-CHECKLIST-P0-D3D](REVIEW-CHECKLIST-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.1.md)
- **架构评审意见**: [REVIEW-ARCH-P0-D3D](REVIEW-ARCH-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.1.md)
- **修订依据**: 架构评审 54 项 Blocker 结论（30 通过 / 23 有条件 / 1 不通过）
- **v0.1 归档**: [SPEC-P0-D3D v0.1](SPEC-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.1.md)（被本文取代）
- **复审报告**: [REVIEW-CLOSURE-P0-D3D-v0.2](REVIEW-CLOSURE-P0-D3D-v0.2.md)（3 关闭 / 5 有条件 / 0 不通过）
- **上游约束**: [DESIGN-DSH-ARCH-UPGRADE-v0.2](DESIGN-DSH-ARCH-UPGRADE-v0.2.md)、[GateFlow](../../../3.1-FRONTEND/src/lib/task-board/gate-flow.ts)、[GateGovernance](../../../3.1-FRONTEND/src/lib/task-board/gate-governance.ts)、[3+3 映射](../../../1-ARCHITECTURE/3+3架构模块映射.md)、[47 registry](../../../47-MCP管理系统/registry/mcp_capabilities.yaml)、[49 交易协议](../../../49-交易框架协议/SPEC.md)
- **一句话**: **执行归 DSH，提案归 Hermes，决策归脑暴 Council，授权归人；Hermes 永远不直接指挥 DSH。**

---

## §0 结论与七条不变式

### 0.1 为什么需要 D3D

D3C 解决了“DSH 断路后谁来补”，但留下一个结构性风险：如果 Hermes 补完直接给 DSH 派活，它就变成了事实上的指挥官。D3D 在两者之间插入**脑暴决策层**，把“提案”和“执行”彻底分开。

### 0.2 七条不变式（Hard Invariants）

| ID | 不变式 | 违反后果 |
|---|---|---|
| **HI-1** | Hermes 不得向 DSH 下发任务；DSH 可在执行中向 Hermes 发起 `AssistRequest` | 指挥权旁落，审计链断裂 |
| **HI-2** | 任何 DSH 重做必须引用 `DecisionRecord.adopted` | 无法回溯“为什么做” |
| **HI-3** | 飞书是授权/告警通道，GateFlow 是唯一审批真相 | 双账本、审批失效 |
| **HI-4** | 决策采纳以回测/正常推进门禁为准，不以 Council 投票为准 | 脑暴空转、决策不可验证 |
| **HI-5** | Presentation 层不得修改 Core Facts；成品必须过 Fact Gate | 外表污染内在 |
| **HI-6** | 所有表达成品必须带 `FactUsageManifest`；无 manifest 不得交付 | 事实无法追溯 |
| **HI-7** | `ApprovalBridge` 是 GateFlow 的唯一写入者 | 审批被旁路或双写 |

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

### 0.4 v0.2 修订摘要（评审关闭项）

| 评审项 | v0.2 处理 | 章节 |
|---|---|---|
| E8 事实提取 | 新增 `FactUsageManifest` + 逐格式提取 + 以 manifest 为主 | §2.5.3、§6.4 |
| B1 Hermes 技术隔离 | 独立 OS 用户、无 DSH 凭证、网络隔离、Router 拒绝 `source=hermes` | §8.1、§10.1 |
| B2 强制 decision_id | Router 必填 `decision_id + adopted + expires_at` | §8.1 |
| H1 审批唯一写入 | 新增 `ApprovalBridge`，唯一写 GateFlow | §7.4 |
| H6 超时自动审批 | 新增 `UrgentPolicy` 白名单与硬排除 | §7.3 |
| A6 外援阻塞 | `AssistRequest.blocking=false` 默认，超时返回 partial | §2.4 |
| A7 状态双真相 | 新增“状态所有权矩阵” | §2.6 |
| C1 分级不可判定 | 新增 `TierPolicy`，机器可判定 | §2.2.1 |
| B5 Hermes 投票 | 新增 `hermes_secretary` 非投票角色 | §1.2 |
| E2/E5/E7 | 未映射数字 fail、`ChartSpec`、`CaveatManifest` | §2.5、§6.4 |
| I1/I6/I7 | 运行时隔离、脱敏、撤销/kill switch | §10.1–§10.4 |
| L2 53 登记 | 新增 `external_runtimes` 登记清单与 Phase 2 门禁 | §10.5 |
| K4 幂等 | 统一幂等键表 | §10.2 |

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

### 1.2 Hermes 的非投票角色

Hermes 在治理/脑暴中的身份固定为 `hermes_secretary`：

| 属性 | 规定 |
|---|---|
| `can_vote` | `false` |
| `can_approve` | `false` |
| `can_propose` | `true` |
| `can_dissent` | `true` |
| `seat_type` | `secretary`（仅记录、汇总、催办） |
| 高风险 Gate | 禁止任何 Agent 席位，Hermes 连列席都只能只读 |

`gate-governance` 必须在编译/运行期拒绝：
- `hermes_secretary` 出现在审批票中；
- Agent 席位审批 high/critical gate；
- Hermes 审批自己发起的 `ApprovalRequest`。

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

### 2.2.1 TierPolicy（机器可判定）

```json
{
  "risk_level": "low|medium|high|critical",
  "reversible": true,
  "blast_radius": "single_task|module|cross_domain|system",
  "evidence_gap_count": 0,
  "option_count": 2,
  "uncertainty_score": 0.35,
  "tier": "T0|T1|T2|T3",
  "tier_reason": "risk=low, reversible=true, options=1",
  "policy_version": "tier-policy-v1"
}
```

判定顺序（命中即停）：

| 顺序 | 条件 | 级别 |
|---|---|---|
| 1 | `risk_level=critical` 或 `reversible=false` 或 live/安全/策略上线 | T3 |
| 2 | `blast_radius=cross_domain` 或 `evidence_gap_count≥2` 或 `uncertainty_score≥0.7` | T2 |
| 3 | `option_count≥2` 或 `uncertainty_score≥0.4` | T1 |
| 4 | 其余 | T0 |

没有 `tier_reason` 或 `policy_version` 的 Ticket 不得立案。

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
  "blocking": false,
  "deadline_s": 300,
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
| 执行模式 | 默认异步非阻塞；DSH 可继续执行；超时返回 `partial`，不拖死主链路 |
| 防乒乓 | 每 Ticket `assist_count ≤ 2`；同 `need_hash` 不得重复；无新信息不得重试 |
| 审计 | 带 `assist_id + trace_id`，可回放 |

返回契约：

```json
{
  "assist_id": "AS-1",
  "status": "resolved|partial|needs_brainstorm|rejected",
  "output": "可被 DSH 消费的结果/证据",
  "evidence_refs": ["EV-1"],
  "capability_gap": null,
  "partial_reason": null,
  "cost_usd": 0.0,
  "elapsed_ms": 1200,
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
  "fact_usage_manifest": "outputs/report.fact-usage.json",
  "status": "DRAFT|VERIFIED",
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
  "unmapped_claims": 0,
  "manifest_missing": false,
  "chart_mismatch": 0,
  "caveat_missing": 0,
  "verdict": "pass|degraded|fail"
}
```

**FactUsageManifest（强制）**

```json
{
  "artifact_id": "PA-1",
  "fact_usages": [
    {
      "claim_id": "C-1",
      "fact_id": "F-1",
      "location": "docx:paragraph:12",
      "rendered_value": "12.3%",
      "transform": "identity|rounded|unit_converted|derived",
      "formula": null
    }
  ],
  "unmapped_claims": [],
  "chart_specs": [
    {
      "chart_id": "CH-1",
      "chart_type": "bar",
      "source_fact_ids": ["F-1"],
      "x": "date",
      "y": "value",
      "unit": "%",
      "axis": {"y_min": 0, "y_max": 20}
    }
  ],
  "caveats": [
    {
      "caveat_id": "CV-1",
      "location": "docx:paragraph:30",
      "text": "样本外未验证",
      "source": "CanonicalFactBundle.risks[0]"
    }
  ]
}
```

规则：

- `unmapped_claims` 非空 → **fail**；
- `chart_specs` 必须与 `chart_data.json` 一致；
- `caveats` 必须覆盖 DSH 的 material risks；
- 无 manifest → 不得交付（HI-6）。

> `ChartSpec` 指 `chart_specs[]` 的元素；`CaveatManifest` 是 `caveats[]` 的完整视图，两者都必须随成品提供。

#### 2.5.3 逐格式事实提取

FactGate 以 **manifest 为主、抽取为辅**，避免从成品反推事实时引入新的幻觉。

| 格式 | 主方案 | 辅方案 | 拒绝条件 |
|---|---|---|---|
| docx | `word/document.xml` 段落/表格 + manifest 定位 | 文本抽取抽查 | manifest 缺失或数字无法映射 |
| pptx | slide XML + chart XML + 内嵌 workbook | 文本抽取抽查 | 只有图片、无 chart_data |
| xlsx | 单元格值/公式 + 命名区域 | 公式复算 | 公式不可复算 |
| pdf | **仅文本层 PDF**，PyMuPDF/pdftotext | 要求同时提供 docx/pptx 源文件 | 扫描件、纯图片 PDF |

#### 2.5.4 流程

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

#### 2.5.5 硬约束

1. Hermes 不得修改 Core Facts 的数值、单位、日期、结论、置信度、风险表述；
2. 派生数字必须给公式和输入 `fact_id`，可复算；
3. 补充信息必须标注来源，且不能与 Core Facts 矛盾；
4. 图表数据只能来自 FactBundle；坐标轴/刻度不得误导；
5. 成品必须带 provenance：`facts: DSH / render: Hermes / verified: yes|no`；
6. 未通过 Fact Gate 的成品只能标 `DRAFT`，不得对外；
7. 文档生成在沙箱内；敏感数据不外传，外部调研走白名单；
8. 对外发布需人工授权；内部交付仅通知；
9. 成品必须随附 `FactUsageManifest`；缺失 → fail；
10. `unmapped_claims` 非空 → fail；
11. 图表必须有 `ChartSpec + chart_data.json`；纯图片图表 → fail；
12. `CaveatManifest` 必须覆盖 DSH 的 material risks；缺失 → fail；
13. 成品状态只能是 `DRAFT|VERIFIED`；交付 API 只服务 `VERIFIED`。

#### 2.5.6 渲染器

渲染器可插拔：Hermes 自带工具、现有 office-plugin（docx/pptx/xlsx/pdf）均可，**契约不变**。选择标准是格式支持、模板兼容、渲染质量与成本，不是身份。

#### 2.5.7 何时使用

- 用户需要 Word/PDF/PPT/Excel/图表/可视化报告；
- DSH 简单文本可直接渲染；复杂版式、图表、模板化研报走 `Presentation Assist`；
- 对外发布走审批；内部交付只通知。

### 2.6 状态所有权矩阵（防止双真相）

| 状态 | 唯一所有者 | 其他模块权限 |
|---|---|---|
| GateFlow 审批状态 | `gate-flow.ts` | 只读；仅 `ApprovalBridge` 可写 |
| BrainstormTicket 过程状态 | `brainstorm_ticket.py` | 只读；仅 Orchestrator 推进 |
| DecisionRecord 结果 | `decision_record.py` | 只读；Dispatcher 只读 `adopted` |
| AssistRequest/Result | `assist_request.py` | 只读；DSH 消费结果 |
| 飞书消息/审批单 | `feishu_authorization_bridge.py` | 只存 `external_ref`，不复制审批状态 |
| DSH Ticket 执行状态 | DSH Router/Worker | 只读；Brainstorm 不得直接写 |

规则：

- 禁止跨模块写状态；
- 跨状态只引用 ID，不复制状态字段；
- 任何双写路径必须被测试判定为失败。

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

**ExperimentPlan（T2/T3 必填）**

```json
{
  "experiment_id": "EXP-1",
  "decision_id": "DR-1",
  "hypothesis": "方案 A 优于 B",
  "control": "baseline",
  "treatment": "A",
  "sample_size": 100,
  "metrics": ["sharpe", "max_drawdown"],
  "thresholds": {"sharpe_delta": 0.2},
  "run_id": "run-123",
  "judgment": false,
  "human_signoff": null
}
```

规则：

- T2/T3 无 `ExperimentResult` 不得 `decided`；
- 无法实验时 `judgment=true`，必须有 `human_signoff`；
- 实验必须可在 48/45 复跑，`run_id` 可追溯。

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
  "decision_hash": "sha256:...",
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
| **pass** | Core Facts 全部匹配；`changed=0`；无矛盾；关键引用齐全；manifest 完整；`unmapped_claims=0` | 允许交付 |
| **degraded** | 补充信息未标注 / 次要 caveat 缺失 / 格式问题 | 标注 `DRAFT` / 补证 / 人工 |
| **fail** | 核心数字/结论/风险被改；与 Core 矛盾；伪造引用；删除重大风险；manifest 缺失；`unmapped_claims>0`；chart_mismatch>0；caveat_missing>0 | 打回重做 |

规则：

- 输入必须是 `PresentationArtifact + FactUsageManifest + ChartSpec/CaveatManifest`；
- 核心数字、单位、日期、结论、置信度、风险表述不可变；
- `unmapped_claims` 非空 → **fail**；
- 派生数字必须可复算，并标注输入 `fact_id`；
- 图表 `chart_data.json` 必须与 `ChartSpec` 和 FactBundle 一致；
- `CaveatManifest` 必须覆盖 material risks；缺失 → **fail**；
- 未过门禁只能标 `DRAFT`；交付 API 只服务 `VERIFIED`；
- provenance 必须包含 `facts: DSH / render: Hermes / verified: yes|no`。

---

## §7 飞书授权桥（Feishu Authorization Bridge）

### 7.1 定位

飞书是**人类授权通道**，不是第二套审批真相。GateFlow 仍是唯一审批状态机。

`ApprovalBridge` 是 GateFlow 的**唯一写入者**；Hermes 不得直接调用 GateFlow 写接口。

```text
GateFlow 需要人工授权
  → Hermes → ApprovalBridge 发起真实飞书审批
  → 人批准/否决
  → 签名 ApprovalGrant 经 ApprovalBridge 回写 GateFlow
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
  "signature_alg": "ed25519|hmac-sha256",
  "key_id": "approval-key-2026-11",
  "nonce": "n-1",
  "grant_hash": "sha256:...",
  "issued_at": 1795000000
}
```

回写要求：

- `request_id` 唯一约束，重复 webhook 返回同一结果；
- 签名校验失败 → 拒绝，不得降级；
- `nonce` 防重放；
- `grant_hash` 进入审计，支持事后核验。

### 7.3 超时规则

| 类型 | 超时行为 |
|---|---|
| Gate 验收 / 高风险门 | `remind / escalate / block`，**永不自动通过** |
| 非 Gate 的紧急运维任务（可逆、低/中风险） | 仅限 `UrgentPolicy` 白名单类，可预授权自动审批，必须有预算、TTL、审计 |
| live / 不可逆 / 安全事件 | 永不自动审批 |

#### UrgentPolicy 预授权登记

| 字段 | 要求 |
|---|---|
| `policy_id` | 唯一策略 ID |
| `task_class` | 仅限白名单运维类 |
| `risk` | `low|medium` |
| `reversible` | 必须 `true` |
| `max_scope` | 单次最大影响范围 |
| `max_budget` | 金额/资源上限 |
| `ttl_s` | 授权有效期 |
| `audit` | 必须写审计与告警 |

**硬排除**：Gate/高风险门、live、不可逆、安全事件、策略上线、生产库写、权限变更。

> 现有 `approval_agent.py` 的“AI 代决”属于交易审批例外路径，不得扩展到治理 Gate。

### 7.4 ApprovalBridge 唯一写入

- Hermes 只能调用 `ApprovalBridge`，不得直写 GateFlow；
- Bridge 校验签名、`request_id`、`scope`、`nonce`；
- Bridge 写入 GateFlow 事件与 Grant，必须幂等；
- Bridge 失败 → `block`，不允许 Hermes 自行推进；
- 任何“Hermes 直写 GateFlow”的路径必须被拒绝并告警。

**Outbox 消费（Phase 2 接线）**：

- `approval.granted` 事件必须携带 `task_id / gate_id / gate_kind / grant`；
- 消费者只接受 `approval.granted`，按 `request_id|grant_id` 幂等；
- 游标失败不前进，坏行跳过；重复事件不重复推进；
- 验收门即使拿到授权 Grant，仍必须通过 L0 verdict 硬门，不得绕过；
- 审批轮询器在产生新 Grant 后可经 `GATEFLOW_APPLY_URL` 立即触发消费（FAIL-OPEN）。

### 7.5 授权后执行

人工批准后：

1. 生成 `ApprovalGrant`；
2. 与 D3C 的 `AutonomyGrant` 绑定；
3. Hermes 只能在 `scope + ttl` 内执行后续；
4. 每个动作带 `grant_id + trace_id` 审计；
5. 超范围立即拒绝并升级。

### 7.6 通知/授权分级（避免审批疲劳）

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

### 7.7 Hermes 反思门禁 → 广义认知注入

认知系统升级期间，Hermes 反思不得直写记忆/图谱/向量库；必须先过门禁，再作为候选证据注入。

```text
Hermes 反思 → ReflectionProposal
  → ReflectionGate（trace/证据/写动作/密钥/CoT/限长/去重/置信度）
  → ReflectionInbox（append-only, candidate_only）
  → 广义认知系统消费/复核 → 才可升级为记忆
```

| 规则 | 处置 |
|---|---|
| 缺 `trace_id` / `task_id` / `reflection_id` | 拒绝 |
| 任一 insight 无 `evidence_refs` | 拒绝 |
| 写动作（`memory_write` / `record` / `place_order` 等） | 拒绝 |
| 密钥 / token / 私钥 | 拒绝 |
| `reasoning` / `chain_of_thought` | 拒绝 |
| artifact > 16KB / confidence < 0.5 | 拒绝 |
| 重复 `reflection_id` / `content_hash` | 幂等丢弃 |
| 通过 | inbox，`candidate_only` + `requires_review=true` + TTL 7 天 |

实现：`34-前端应用训练系统/core/hermes_reflection_gate.py`。

---

## §8 DSH 消费：唯一入口

### 8.1 禁止直连与强制校验

- Hermes 不持有 DSH task/worker 的写凭证；
- Hermes 无法访问 DSH 内部端口（网络隔离，见 §10.1）；
- DSH Router 不接受 `source=hermes` 的直接任务；
- 所有重做必须带 `decision_id`，且 `DecisionRecord.status == adopted`。

Router 校验表：

| 校验 | 失败结果 |
|---|---|
| `source` 必须为 `brainstorm` | `403 source_forbidden` |
| `decision_id` 必填 | `400 decision_required` |
| `DecisionRecord.status == adopted` | `409 decision_not_adopted` |
| `expires_at > now` | `409 decision_expired` |
| `decision_hash` 与记录一致 | `409 decision_tampered` |
| `task_index` 在 ReworkPackage 范围内 | `400 task_out_of_scope` |

Router 对 `source=hermes` 的请求必须记录安全告警；重复出现升级到人工。

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

## §10 与 46/53/3+3/47/49 的对齐及安全隔离

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

### 10.1 Hermes 运行时隔离

| 项 | 要求 |
|---|---|
| OS 用户 | 独立 `hermes-runtime`，不得与 DSH/生产服务共用 |
| systemd | `NoNewPrivileges=yes`、`ProtectSystem=strict`、`PrivateTmp=yes`、`ProtectHome=yes` |
| 文件系统 | 仅 workspace/tmp 可写；DSH 代码与数据只读 |
| 凭证 | 不注入 DSH/生产凭证；只持有 `ApprovalBridge` 的短期 token |
| 网络 | 出站白名单；不可达 DSH 内部端口；外部调研走代理 |
| 资源 | `MemoryMax`、`CPUQuota`、并发上限 |
| 沙箱 | 文档生成、实验运行在独立沙箱 |

关闭标准：Hermes 尝试访问 DSH 内部 API 必须连接失败/403，并产生告警。

### 10.2 统一幂等键

| 场景 | 幂等键 |
|---|---|
| GateFlow 事件 | `(gate_run_id, event_id)` |
| 审批回写 | `request_id` |
| 决策派发 | `(decision_id, task_index)` |
| 外援请求/结果 | `assist_id` |
| 表达成品 | `(request_id, artifact_version)` |
| 立案 | `(gap_key, active)` |
| 实验 | `(decision_id, experiment_id)` |

要求：统一去重表；重复请求返回同一结果；TTL 不短于业务有效期。

### 10.3 撤销与 kill switch

- `revoke_grant(grant_id)`：立即失效；
- `revoke_autonomy(grant_id)`：停止后续自主动作；
- 运行时 kill switch：停止 Hermes worker，不影响 DSH 主链路；
- 异常成本/越权/连续失败 → 自动撤销并告警；
- 撤销事件必须审计。

### 10.4 脱敏与 egress

- PII/secret 字段级规则；
- 原始 `CanonicalFactBundle` 不得外发；
- 外部调研只使用公开信息，不带入机密事实；
- 产物/日志/证据统一脱敏扫描；
- 对外发布前做 DLP 检查。

### 10.5 53 外部运行时登记（Phase 2 门禁）

```yaml
runtime_id: hermes
allowed_roles: [research, engineer, presentation]
allowed_shells: []
deny_by_default: true
sandbox_profile: hermes-sandbox
network_policy: egress-allowlist
max_concurrency: 3
audit_sink: dsh_audit
```

登记要求：

- 先登记再接入，不允许空登记；
- `check_whitelist.py --runtime hermes --role <role>` 接入 systemd `ExecStartPre` 或 CI；
- 未登记时 Phase 1 只能用 fake runtime，不得连真实 Hermes。

---

## §11 数据契约（落地模块建议）

| 模块 | 路径 | 职责 |
|---|---|---|
| 外援请求 | `34-.../core/assist_request.py` | AssistRequest/AssistResult、只读与预算约束 |
| 表达契约 | `34-.../core/presentation_contract.py` | PresentationRequest / PresentationArtifact |
| 事实锁 | `34-.../core/fact_lock.py` | CanonicalFactBundle / FactUsageManifest / ChartSpec / CaveatManifest |
| 事实门 | `34-.../core/presentation_gate.py` | FactConsistencyReport / 逐格式提取 / verdict |
| 立案与状态机 | `34-.../core/brainstorm_ticket.py` | Ticket 创建、分级、幂等、状态迁移 |
| 提案 | `34-.../core/proposal_bundle.py` | ProposalBundle 校验、dissent 保留 |
| 证据 | `34-.../core/d3d_evidence_bundle.py` | hash/replay 校验、脱敏（避免与既有 `evidence_bundle.py` 冲突） |
| 实验 | `34-.../core/experiment_result.py` | 对照组、指标、统计门 |
| 决策 | `34-.../core/decision_record.py` | DecisionRecord 生命周期与终审 |
| 飞书桥 | `34-.../core/feishu_authorization_bridge.py` | ApprovalRequest/Grant、飞书消息 |
| 飞书审批客户端 | `34-.../core/feishu_approval_client.py` | REST：token/实例/状态/审批/IM，凭据仅 env，可注入 transport |
| 飞书审批服务 | `34-.../core/feishu_approval_service.py` | 建单 → 轮询 → 签名 Grant → ApprovalBridge；预授权仅 UrgentPolicy |
| 审批桥 | `34-.../core/approval_bridge.py` | **唯一写 GateFlow outbox**、签名/幂等/重放校验、写入 task/gate 定位与完整 Grant |
| Outbox 消费 | `3.1-FRONTEND/src/lib/task-board/approval-outbox.ts` | `approval.granted` → `gate.updated`（游标/幂等/验收 verdict 硬门） |
| Outbox API | `3.1-FRONTEND/src/app/api/approvals/outbox/route.ts` | POST 触发消费、GET 查看游标与已应用数 |
| 紧急策略 | `34-.../core/urgent_policy.py` | UrgentPolicy 白名单、预算、TTL |
| 分级策略 | `34-.../core/tier_policy.py` | T0–T3 机器判定、`tier_reason` |
| GateFlow 事件导出 | `3.1-FRONTEND/src/lib/task-board/gateflow-event-export.ts` | 驳回 → `.data/gateflow/*.jsonl` |
| GateFlow 立案桥 | `34-.../core/gateflow_brainstorm_bridge.py` | `node.rejected` → 幂等立案 |
| 运行时隔离 | `34-.../core/runtime_isolation.py` | B1：systemd/网络/凭证/路径校验 |
| 53 外部运行时 | `53-DSH插件模块/external_runtimes.yaml` | hermes 当前 disabled / sandbox only |
| 派发 | `34-.../core/brainstorm_dispatcher.py` | 只消费 adopted，生成 ReworkPackage |

所有模块要求：标准库优先、FAIL-OPEN、线程安全；除 `approval_bridge` 按批准路径写 GateFlow 外，不直接写 Ticket/GateRun。

---

## §12 验收标准

| ID | 门禁 | 通过标准 |
|---|---|---|
| G0 | 契约 | 15 个模块单测全绿；非法输入 FAIL-OPEN |
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
| G15 | 事实清单 | `FactUsageManifest` 覆盖 100%；`unmapped_claims` 0 |
| G16 | 审批单写 | `ApprovalBridge` 是唯一写入；直写/双写 0 |
| G17 | 分级 | `TierPolicy` 稳定输出 T0–T3；无 `tier_reason` 不得立案 |
| G18 | 隔离 | Hermes 无 DSH 凭证；访问 DSH 内部端口 100% 失败 |
| G19 | 紧急审批 | 仅 `UrgentPolicy` 白名单；Gate/live/不可逆 0 自动 |
| G20 | 幂等 | 重复事件/派发/回写/外援 0 副作用 |

---

## §13 落地阶段

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | 14 个核心契约 + 1 隔离策略 + 单测；关闭 E8/B1/B2/H1/H6/A6/A7/C1 | ✅ 契约层已落地（38 单测） |
| Phase 2 | GateFlow `node.rejected` → 立案 → 派发闭环；ApprovalBridge + UrgentPolicy + 53 登记；真实飞书审批；outbox → GateFlow 消费 | ✅ 前端导出器 + Python 消费器 + 真实飞书审批 + `approval.granted` 消费者（9 单测）已接；Hermes 待接 |
| Phase 3 | Hermes 真实运行时接入（Phase 0 spike 后） | 待 Phase 2 |
| Phase 4 | Presentation Assist / FactLock 生产化 | 待 Phase 3 |

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
| R11 | Hermes 运行时隔离不足 | 独立用户 + systemd 加固 + 网络白名单（§10.1） |
| R12 | 事实提取误报/漏报 | manifest 为主 + 逐格式 fallback + 抽样 |
| R13 | 审批回写重放 | nonce + 幂等表 + 签名校验 |
| R14 | 53 登记滞后 | Phase 2 门禁，未登记不得接真实 Hermes |
| Q1 | T1 是否允许全自动采纳 | 待定：建议仅低风险、可逆、有门禁 |
| Q2 | Council 是否常设 | 建议按需组建 |
| Q3 | 实验 SLA 与算力预算 | 待 45/48 评估 |
| Q4 | “重要决策可正常推进”的边界 | **已定**：非高风险、可逆；高风险/live/不可逆仍需审批 |
| Q5 | 四类成品事实提取方案 | **已定**：manifest 为主 + 逐格式 fallback；扫描 PDF 不接受 |
