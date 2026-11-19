# DSH + Hermes 端到端架构（正式设计基线）

- **版本**: v1.0 ｜ **日期**: 2026-11-19 ｜ **状态**: 设计基线（部分落地）
- **归属**: 46-DSH架构 / L2 执行与决策编排
- **定位**: 本文是 DSH 主链路、D3C 外援、D3D 决策闭环、Presentation 表达层的**统一架构地图**；具体契约以各 SPEC 为准
- **上游 SSoT**:
  - [3+3 架构模块映射](../../../1-ARCHITECTURE/3+3架构模块映射.md)
  - [DESIGN-DSH-ARCH-UPGRADE-v0.2](DESIGN-DSH-ARCH-UPGRADE-v0.2.md)
  - [SPEC-P0-D3C 场外助手](SPEC-P0-D3C-HERMES-FIELD-ASSISTANT-v0.1.md)
  - [SPEC-P0-D3D v0.2 脑暴决策闭环](SPEC-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.2.md)
- **评审记录**:
  - [REVIEW-ARCH-P0-D3D](REVIEW-ARCH-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.1.md)
  - [REVIEW-CLOSURE-P0-D3D-v0.2](REVIEW-CLOSURE-P0-D3D-v0.2.md)
- **适用范围**: 架构、开发、运维、治理、安全评审
- **非范围**: 交易策略细节、模型训练算法、前端视觉设计

---

## 1. 文档目的

回答四个问题：

1. 一个用户请求从进入到交付，经过哪些层、哪些组件？
2. DSH、Hermes、A 层、Council、GateFlow、人工各自拥有什么权力？
3. 失败、驳回、能力不足、超时、表达交付分别走哪条旁路？
4. 哪些门禁保证“强规则不被破坏、事实不被污染、审批不被旁路”？

本文是**导航与边界文档**，不重复 D3C/D3D 的字段级契约。

---

## 2. 设计原则

| 原则 | 含义 |
|---|---|
| 主链路强规则 | DSH 执行、GateFlow 审批、A 层验收保持确定性与可审计 |
| 执行与决策分离 | DSH 执行，Hermes 提案，Council 建议，A 层/门禁采纳 |
| 执行与表达分离 | DSH 出事实，Hermes 出 Word/PPT/图表 |
| 审批单一真相 | GateFlow 是唯一审批状态机，飞书只是授权通道 |
| 事实不可变 | Core Facts 冻结，表达层只能引用、排版、可视化 |
| 证据优先 | 决策必须可追溯到数据/代码/日志/实验 |
| 有界自主 | Hermes 的自主权有范围、预算、TTL、可撤销 |
| 高风险 fail-closed | live、不可逆、安全、策略上线必须人工 |

---

## 3. 架构总览

### 3.1 分层视图

```text
┌──────────────────────────────────────────────────────────────┐
│ 对外能力：DreamOS(SACG) → DSH → L0 + 交易链（只读观察）        │
├──────────────────────────────────────────────────────────────┤
│ L2 大模型驱动层                                               │
│   L2-K 内核编排：S 规划 / A 验收 / C 执行 / G 沉淀             │
│   L2-E 执行编排：DSH Router + Worker 角色池                    │
│   L2-G 生成式能力：32 辩论 / 34 训练 / 48 涌现 / 25 策略生成   │
│   L2-P 协议接入：46 DSH Harness / 52 LobeHub / 53 Cordis      │
├──────────────────────────────────────────────────────────────┤
│ L1 基础智能层：零 token 确定性金融能力（交易链、意图路由）     │
├──────────────────────────────────────────────────────────────┤
│ L0 基础能力层：数据/认知/记忆/检索/评测/MCP 能力面             │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 组件视图

```text
用户 / 飞书
   │
   ▼
L1 意图路由（命中即回）
   │ 未命中
   ▼
SACG-S 规划/定标准
   │
   ▼
SACG-A 验收门 ◄────────────── GateFlow（审批真相）
   │                              ▲
   │                              │ ApprovalBridge
   ▼                              │
DSH Router / Worker ──────────────┘
   │        │
   │        ├─ D3C 外援：AssistRequest → Hermes → AssistResult
   │        │
   │        └─ D3D 决策：BrainstormTicket → Hermes 提案 → Council/实验
   │                              → DecisionRecord → DSH 重做
   ▼
DSH CanonicalFactBundle
   │
   ▼
Hermes Presentation（Word/PPT/图表）
   │
   ▼
FactGate → A 层 → 交付
   │
   ▼
G 层沉淀：45 评测 / 48 实验 / 4-MEMORY 认知 / 35 协作
```

### 3.3 一条主链路 + 三条旁路

| 通道 | 触发 | 方向 | 目的 |
|---|---|---|---|
| **主链路** | 正常请求 | 用户 → SACG → DSH | 确定性执行与验收 |
| **D3C 外援** | DSH 能力不足 | DSH → Hermes | 补齐执行能力 |
| **D3D 决策** | A 层缺口/驳回 | A → Brainstorm → DSH | 方案选择与重做 |
| **Presentation** | 需要 Word/PPT/图表 | DSH → Hermes | 事实锁定的表达交付 |

---

## 4. 端到端主链路

| # | 步骤 | 负责 | 关键产物 | 门禁 |
|---|---|---|---|---|
| 1 | 用户请求 | 前端/飞书 | 原始意图 | — |
| 2 | L1 意图识别 | L1 路由 | 意图/参数 | 命中即回 |
| 3 | S 层规划 | SACG-S | 目标、OKR 节点、验收标准（冻结） | 标准冻结 |
| 4 | DSH 派工 | DSH Router | Ticket、Mandate、预算、trace_id | 角色白名单 |
| 5 | DSH 执行 | Worker | 结果、证据、`CanonicalFactBundle` | A 层硬门禁 |
| 6 | 能力不足 | DSH → Hermes | `AssistRequest` / `AssistResult` | 只读、预算、TTL |
| 7 | A 层验收 | A 层 | 规则 verdict + 语义 verdict | G1–G20 |
| 8 | 缺口/驳回 | A 层/GateFlow | `BrainstormTicket` | TierPolicy |
| 9 | 调研与提案 | Hermes | `ProposalBundle`、反例、异议 | 证据门 |
| 10 | 脑暴与实验 | Council + 32/45/48 | `ExperimentResult` | 对照实验/统计门 |
| 11 | 决策 | Council + 门禁 | `DecisionRecord` | Adoption Gate |
| 12 | 重新执行 | DSH Router | 新 Ticket（带 `decision_id`） | B2 校验 |
| 13 | 表达交付 | DSH + Hermes | `PresentationArtifact` | FactGate |
| 14 | 沉淀 | G 层/45/48/4/35 | 指标、认知、能力缺口 | 反思闭环 |

### 4.1 正常请求时序

```text
User → L1 → SACG-S → DSH Router → Worker
  → A 层（规则 + 语义）
  → 通过 → 交付
  → G 层沉淀
```

### 4.2 缺口请求时序

```text
User → ... → DSH → A 层 fail/degraded
  → BrainstormTicket → Hermes Proposal
  → Council + 实验 → DecisionRecord
  → Adoption Gate → DSH 重做
  → A 层复验 → 交付
```

---

## 5. D3C 外援通道

### 5.1 触发

- DSH 执行中发现能力不足；
- 需要补充数据、工具、调研；
- 不需要方案选择。

### 5.2 流程

```text
DSH
  → AssistRequest（默认 blocking=false，只读，预算/TTL）
  → Hermes 执行
  → AssistResult（resolved/partial/needs_brainstorm/rejected）
  → DSH 继续或转 BrainstormTicket
  → A 层最终验收
```

### 5.3 硬约束

| 约束 | 规则 |
|---|---|
| 方向 | 只能 DSH → Hermes |
| 产出 | Hermes 不创建 Ticket、不调 Worker |
| 权限 | 默认只读；写操作必须带 Grant |
| 防乒乓 | 每 Ticket ≤2 次；同 `need_hash` 不重复 |
| 验收 | A 层硬门禁不豁免 |
| 超限 | 转 BrainstormTicket |

---

## 6. D3D 决策闭环

### 6.1 触发与分级

| 触发 | 是否立案 |
|---|---|
| A 层 `fail/degraded` 且缺口非平凡 | ✅ |
| GateFlow `node.rejected` 且需要重做 | ✅ |
| Hermes 返回 `capability_gap` / `needs_human` | ✅ |
| 用户显式要求“讨论/脑暴/给方案” | ✅ |
| DSH 能力不足 | ❌ 走 AssistRequest |
| 瞬时错误/标准明确的小修复 | ❌ 直接重试/重做 |

**TierPolicy**：T3（critical/live/不可逆）→ T2（跨域/证据冲突）→ T1（多方案/中不确定）→ T0（低风险单方案）。

### 6.2 流程

```text
A 层 fail/degraded
  → BrainstormTicket
  → Hermes 调研/提案/异议
  → Council（32 辩论 + 45 评测 + 48 实验）
  → DecisionRecord
  → Adoption Gate（回测/CI/正常推进）
  → 人工/飞书授权（高风险）
  → DSH 重做
```

### 6.3 硬边界

- Council 只给建议，不是采纳票；
- Hermes 不是终审；
- 无适用门禁 → 人工；
- T3 → 人工终审；
- `dissent` 必须保留。

---

## 7. Presentation 表达通道

### 7.1 流程

```text
DSH ExpertCore
  → CanonicalFactBundle（冻结）
  → PresentationRequest
  → Hermes 渲染
  → FactUsageManifest + ChartSpec + CaveatManifest
  → FactGate
  → DRAFT/VERIFIED → 交付
```

### 7.2 三类信息

| 类型 | 来源 | 规则 |
|---|---|---|
| Core Facts | DSH | 不可改值/结论 |
| Derived Facts | Hermes | 必须给公式与 `fact_id` |
| Supplementary Context | Hermes 调研 | 必须标注来源，不得矛盾 |

### 7.3 FactGate

| verdict | 条件 | 动作 |
|---|---|---|
| pass | 核心事实匹配、manifest 完整、无未映射、图表一致、caveat 覆盖 | 交付 |
| degraded | 补充信息未标注、次要 caveat 缺失、格式问题 | DRAFT/补证/人工 |
| fail | 改核心事实、矛盾、伪造引用、删重大风险、manifest 缺失 | 打回 |

### 7.4 逐格式提取

| 格式 | 方案 | 拒绝 |
|---|---|---|
| docx | `word/document.xml` + manifest | 无法映射 |
| pptx | slide XML + chart XML + workbook | 纯图片 |
| xlsx | 单元格/公式 + 命名区域 | 公式不可复算 |
| pdf | 仅文本层 | 扫描件 |

### 7.5 Hermes 反思门禁 → 广义认知注入（v1.1 增补）

定位：Hermes 反思只是**候选证据**，不是认知真相。认知系统升级期间，Hermes 不得直写记忆 / 图谱 / 向量库。

**当前默认关闭**：`enable_hermes_reflection_gate` 未显式置 `1` 时，门禁不评估、不落盘，广义认知系统（含残差记忆器等）继续走原路径；`ReflectionInbox` 关闭状态下 `evaluate_and_enqueue` 返回 `gate_disabled`。

```text
Hermes 反思
  → ReflectionProposal（trace_id / task_id / evidence_refs / insights / confidence）
  → ReflectionGate（真实性 / 证据 / 写动作 / 密钥 / 思维链 / 限长 / 去重 / 置信度）
  → ReflectionInbox（append-only，candidate_only）
  → 广义认知系统消费与复核
  → 复核通过后才可升级为记忆
```

| 规则 | 处置 |
|---|---|
| 开关未打开（默认） | 返回 `gate_disabled`，不影响认知原路径 |
| 缺 `trace_id` / `task_id` / `reflection_id` | 拒绝 |
| 任一 insight 无 `evidence_refs` | 拒绝 |
| 出现写动作（`memory_write` / `record` / `place_order` 等） | 拒绝 |
| 出现密钥、token、私钥 | 拒绝 |
| metadata 携带 `reasoning` / `chain_of_thought` | 拒绝 |
| artifact > 16KB 或 confidence < 0.5 | 拒绝 |
| 重复 `reflection_id` / `content_hash` | 幂等丢弃 |
| 通过 | 写入 inbox，`mode=candidate_only`、`requires_review=true`、TTL 7 天 |

实现：`34-前端应用训练系统/core/hermes_reflection_gate.py`（12 项契约测试，含默认关闭/显式开启）。
边界：本门禁不替代认知系统的写入策略；它只保证“进入认知系统之前”的反思是干净、可审计、可回滚的候选证据。

---

## 8. 审批与授权

### 8.1 单一真相

```text
GateFlow（唯一审批状态机）
  ← ApprovalBridge（唯一写入者）
  ← Hermes（只能调用 Bridge）
  ← 飞书（只做消息/授权通道）
```

### 8.2 ApprovalGrant

- 必须有 `scope + ttl + signature + nonce + grant_hash`；
- `request_id` 幂等；
- 签名失败 → 拒绝；
- 超范围 → 拒绝并升级。

### 8.3 超时规则

| 类型 | 超时行为 |
|---|---|
| Gate/高风险 | remind/escalate/block，永不自动通过 |
| 紧急运维（UrgentPolicy 白名单） | 可预授权自动审批，必须有预算/TTL/审计 |
| live/不可逆/安全 | 永不自动 |

### 8.4 通知分级

| 场景 | 飞书动作 | 审批 |
|---|---|---|
| 常规只读 | 可选通知 | 否 |
| 非代码变更 | 通知 | 否 |
| 重要决策/紧急事务（非高风险、可逆） | 通知 + 事后审计 | 否 |
| 参与脑暴 | 会议纪要抄送 | 否 |
| 内部研报/图表 | 通知 | 否 |
| 对外发布 | 飞书审批 | 是 |
| 高风险/live/不可逆 | 飞书审批 | 是 |

---

## 9. 状态与数据契约

### 9.1 状态所有权

| 状态 | 唯一所有者 | 其他模块权限 |
|---|---|---|
| DSH Ticket 执行 | DSH Router/Worker | 只读 |
| GateFlow 审批 | GateFlow | 只读；ApprovalBridge 唯一写 |
| BrainstormTicket | D3D Orchestrator | 只读 |
| DecisionRecord | DecisionRecord | 只读；只消费 adopted |
| AssistRequest/Result | D3C | 只读 |
| PresentationArtifact | Presentation | 只读 |
| 飞书消息/审批单 | ApprovalBridge | 只存 external_ref |
| approval.granted outbox | GateFlow consumer | 只消费；幂等推进 `gate.updated` |

### 9.2 核心产物

| 产物 | 作用 |
|---|---|
| Ticket | DSH 执行单元 |
| Mandate | 工具/预算/边界 |
| AssistRequest/Result | 外援请求与结果 |
| BrainstormTicket | 决策过程 |
| ProposalBundle | 方案、假设、风险、异议 |
| EvidenceBundle | 证据、hash、replay |
| ExperimentPlan/Result | 对照实验 |
| DecisionRecord | 决策结果 |
| ApprovalGrant | 人工授权 |
| CanonicalFactBundle | 事实源 |
| PresentationArtifact | 表达成品 |
| FactUsageManifest | 事实使用清单 |
| FactConsistencyReport | FactGate 结果 |

### 9.3 幂等键

| 场景 | 键 |
|---|---|
| GateFlow 事件 | `(gate_run_id, event_id)` |
| 审批回写 | `request_id` |
| 决策派发 | `(decision_id, task_index)` |
| 外援 | `assist_id` |
| 表达 | `(request_id, artifact_version)` |
| 立案 | `(gap_key, active)` |
| 实验 | `(decision_id, experiment_id)` |

---

## 10. 门禁与验收

| 门禁 | 作用 |
|---|---|
| G0 | D3D 14 个契约 + 1 隔离策略模块单测 |
| G1/G2 | Hermes 不直连；重做带 adopted decision_id |
| G3/G4 | 证据可重放；T2/T3 有实验 |
| G5 | dissent 保留 |
| G6/G7 | 审批无双账本；Gate 超时不自动通过 |
| G8 | 超 scope/TTL 拒绝 |
| G9/G10 | 分级与可观测 |
| G11 | 外援方向 |
| G12 | 通知分级 |
| G13/G14 | 事实保真与表达溯源 |
| G15 | FactUsageManifest 覆盖 |
| G16 | ApprovalBridge 唯一写入 |
| G17 | TierPolicy 可判定 |
| G18 | 运行时隔离 |
| G19 | UrgentPolicy 白名单 |
| G20 | 幂等 |

**Adoption Gate**：量化/策略 → 45 回测 + 统计；工程 → 测试/CI + 回归；Presentation → FactGate；无门禁 → 人工。

---

## 11. 安全、隔离与审计

| 项 | 要求 |
|---|---|
| OS 用户 | 独立 `hermes-runtime` |
| systemd | `NoNewPrivileges`、`ProtectSystem=strict`、`PrivateTmp`、`ProtectHome` |
| 文件系统 | 仅 workspace/tmp 可写 |
| 凭证 | 无 DSH/生产凭证；仅 ApprovalBridge 短期 token |
| 网络 | 出站白名单；不可达 DSH 内部端口 |
| 资源 | `MemoryMax`、`CPUQuota`、并发上限 |
| 沙箱 | 文档生成、实验运行独立沙箱 |
| 脱敏 | PII/secret 字段级规则；原始 FactBundle 不外发 |
| 撤销 | `revoke_grant`、`revoke_autonomy`、kill switch |
| 审计 | 全链路 trace_id + grant_id + decision_id |

**53 外部运行时登记**：`runtime_id=hermes`、`allowed_roles`、`deny_by_default=true`、`sandbox_profile`、`network_policy`、`max_concurrency`、`audit_sink`。

---

## 12. 可观测性与指标

| 指标 | 目标 |
|---|---|
| DSH 任务成功率 | 持续提升 |
| A 层误判率 | 持续下降 |
| Hermes 外援介入率 | 长期下降 |
| 重复外援率 | 下降 |
| 决策到修复 join 率 | 提升 |
| Fact 保真率 | 100% |
| 未映射事实数 | 0 |
| 审批回写双账本 | 0 |
| Gate 超时自动通过 | 0 |
| 单任务成本/时延 | 在 SLA 内 |

**告警**：`source=hermes` 直连、ApprovalBridge 直写、FactGate fail、Gate 超时、Hermes 越权、53 未登记运行时。

---

## 13. 失败模式与降级

| 失败 | 处理 |
|---|---|
| DSH 瞬时错误 | Worker retry |
| DSH 能力不足 | AssistRequest |
| Hermes 失败 | partial/needs_brainstorm，不拖死 DSH |
| A 层缺口 | BrainstormTicket |
| 实验失败 | 不得 adopted；转人工 |
| 飞书不可用 | ApprovalBridge block；不自动通过 |
| FactGate fail | 打回/标 DRAFT |
| Hermes 越权 | 拒绝 + 告警 + 撤销 Grant |
| 53 未登记 | 禁止接入真实 Hermes |

**降级顺序**：DSH 主链路 → D3C 外援 → D3D 决策 → 人工。

---

## 14. 部署与落地阶段

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 0 | Hermes headless/MCP 可行性 | ✅ 云端 0.19 `-z` headless 已验证；本地 venv 损坏 |
| Phase 1 | D3C 5 模块 | ✅ 已落地 |
| Phase 1' | D3D 14 契约 + 1 隔离策略 + E8/B1/H6/A6/C1 关闭 | ✅ 契约层已落地（38 单测），待接线 |
| Phase 2 | GateFlow 事件导出/消费 + 立案派发 + Approval outbox + 53 登记（disabled）+ 真实飞书审批 + outbox→GateFlow 消费 | ✅ 前端导出器 + Python 消费器 + 真实飞书审批 + `approval.granted` 推进已接；Hermes 待接 |
| Phase 3 | Hermes 真实运行时接入 | 🟡 执行器/路由/53 校验/部署模板已落地；云端 H0–H8 全过，canary 0/10/50/100 机制验证通过；云端代码未部署，`enabled=false` |
| Phase 3.5 | Hermes 反思门禁 → 广义认知注入 | ✅ 门禁 + 收件箱契约已落地（10 单测），candidate_only |
| Phase 4 | Presentation Assist 生产化 | 待 Phase 3 |

**上线策略**：feature flag → shadow → canary → 全量；每阶段保留回退开关。

---

## 15. 模块与代码映射

| 能力 | 现有/计划 | 路径 |
|---|---|---|
| DSH Worker | 现有 | `34-.../core/worker_launcher.py` |
| 角色定义 | 现有 | `34-.../core/worker_roles.py` |
| A 层验收 | 现有 | `34-.../core/okr_acceptance.py` |
| 双层验收 | 已落地 | `34-.../core/dual_acceptance.py` |
| 场外助手 | 已落地 | `34-.../core/hermes_field_assistant.py` |
| 断路交接 | 已落地 | `34-.../core/hermes_handoff.py` |
| 有界自主 | 已落地 | `34-.../core/bounded_autonomy.py` |
| 死信队列 | 已落地 | `34-.../core/dsh_deadletter.py` |
| GateFlow 事件导出 | 已落地 | `3.1-FRONTEND/src/lib/task-board/gateflow-event-export.ts` |
| GateFlow 立案桥 | 已落地 | `34-.../core/gateflow_brainstorm_bridge.py` |
| 立案/提案/决策 | 契约已落地 | `34-.../core/brainstorm_*.py` |
| 决策派发 inbox | 已落地 | `34-.../core/brainstorm_dispatcher.py` |
| 反思门禁 / 认知注入 | 已落地 | `34-.../core/hermes_reflection_gate.py` |
| Hermes 执行器 | Phase 3 | `34-.../core/hermes_executor.py` |
| 审批 JSONL 落盘 | 已落地 | `34-.../core/approval_bridge.py`（`JsonlGateFlowSink`） |
| D3D 证据包 | 契约已落地 | `34-.../core/d3d_evidence_bundle.py` |
| 事实锁/事实门 | 契约已落地 | `34-.../core/fact_lock.py` / `presentation_gate.py` |
| 审批桥 | 契约已落地 | `34-.../core/approval_bridge.py` |
| 紧急策略 | 契约已落地 | `34-.../core/urgent_policy.py` |
| 分级策略 | 已落地 | `34-.../core/tier_policy.py` |
| 运行时隔离 | 已落地 | `34-.../core/runtime_isolation.py` |
| GateFlow | 现有 | `3.1-FRONTEND/src/lib/task-board/gate-flow.ts` |
| GateGovernance | 现有 | `3.1-FRONTEND/src/lib/task-board/gate-governance.ts` |
| 45 评测 | 现有 | `45-评测系统` |
| 48 实验 | 现有 | `48-涌现架构/experiments` |
| 认知写回 | 现有 | `48-涌现架构/asil/cognitive_writeback.py` |
| 记忆反思 | 现有 | `4-MEMORY/9-工具与接口/reflection_node.py` |
| 47 能力面 | 现有 | `47-MCP管理系统/registry` |
| 53 外部运行时 | 已登记（disabled） | `53-DSH插件模块/external_runtimes.yaml` |

---

## 16. 关键决策与开放问题

### 16.1 已定决策

| ID | 决策 |
|---|---|
| ADR-6 | Worker 不自证，A 层 + 门禁 + 人工判定 |
| ADR-9 | Worker 只读；写操作走编排侧 |
| HI-1 | Hermes 不得向 DSH 派活 |
| HI-2 | DSH 重做必须引用 adopted DecisionRecord |
| HI-3 | GateFlow 唯一审批真相 |
| HI-4 | 采纳以门禁为准，不以 Council 投票为准 |
| HI-5 | Presentation 不改 Core Facts |
| HI-6 | 表达成品必须带 FactUsageManifest |
| HI-7 | ApprovalBridge 唯一写 GateFlow |

### 16.2 开放问题

| ID | 问题 | 当前建议 |
|---|---|---|
| Q1 | T1 是否允许全自动采纳 | 仅低风险、可逆、有门禁 |
| Q2 | Council 是否常设 | 按需组建 |
| Q3 | 实验 SLA 与算力预算 | 45/48 分级 |
| Q4 | “重要决策可正常推进”边界 | 非高风险、可逆；高风险仍审批 |
| Q5 | 四类成品提取方案 | manifest 为主 + 逐格式 fallback；扫描 PDF 不接受 |

---

## 17. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-11-19 | 首版：整合 DSH 主链路、D3C 外援、D3D 决策、Presentation、审批、状态、门禁与落地阶段 |

---

## 附录 A：术语

| 术语 | 含义 |
|---|---|
| DSH | DeepSeek Harness，执行编排层 |
| D3C | 场外助手：断路救援、双层验收、有界自主、死信接管 |
| D3D | 脑暴决策闭环：立案、提案、Council、实验、DecisionRecord |
| A 层 | 规则验收 + 语义验收 + GateFlow 审批 |
| Core Facts | DSH 产出的不可变事实 |
| FactGate | 表达成品事实一致性门 |
| Adoption Gate | 决策采纳门禁 |
| UrgentPolicy | 紧急运维预授权策略 |
| ApprovalBridge | GateFlow 唯一写入桥 |

## 附录 B：参考文档

- [3+3 架构模块映射](../../../1-ARCHITECTURE/3+3架构模块映射.md)
- [DESIGN-DSH-ARCH-UPGRADE-v0.2](DESIGN-DSH-ARCH-UPGRADE-v0.2.md)
- [SPEC-P0-D3C](SPEC-P0-D3C-HERMES-FIELD-ASSISTANT-v0.1.md)
- [SPEC-P0-D3D v0.2](SPEC-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.2.md)
- [REVIEW-ARCH-P0-D3D](REVIEW-ARCH-P0-D3D-BRAINSTORM-DECISION-LOOP-v0.1.md)
- [REVIEW-CLOSURE-P0-D3D-v0.2](REVIEW-CLOSURE-P0-D3D-v0.2.md)
- [GateFlow](../../../3.1-FRONTEND/src/lib/task-board/gate-flow.ts)
- [GateGovernance](../../../3.1-FRONTEND/src/lib/task-board/gate-governance.ts)
- [47 MCP registry](../../../47-MCP管理系统/registry/mcp_capabilities.yaml)
- [49 交易协议](../../../49-交易框架协议/SPEC.md)
