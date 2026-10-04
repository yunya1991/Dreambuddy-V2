# 技术设计 — 3-EVOLUTION 进化引擎

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 子系统技术架构设计，对齐 DOC_STANDARD §3.2

---

## 1. 概述

### 1.1 系统定位

3-EVOLUTION 是 DreamBuddy-V2 的自我进化能力实验模块，基于 TypeScript 实现。当前处于实验状态，未集成到主交易系统。其核心职责是接收 10 类系统内/外部触发源，按 9 阶段流水线编排进化记录（`EvolutionRecord`），协调 DZE 开发链、Dream Agent 协作网络、审批门禁三桥接器，将进化产物落到 6 个更新层（knowledge/memory/index/skill/code/architecture）。

### 1.2 设计目标

- **闭环编排**：从发现问题到能力更新的完整流水线，覆盖知识更新与代码变更两条路径。
- **三桥接联动**：通过 `DZEBridge` / `DreamAgentBridge` / `ApprovalBridge` 将进化流程与外部开发链、协作网络、审批系统解耦。
- **门禁控制**：代码变更路径设置 Gate1（方案审批）与 Gate2（开工审批）双门禁，支持超时自动批准。
- **激励机制**：Dream Agent 协作网络引入 DREAM 代币奖励分账（developer 60% / validator 20% / governance 20%）。

### 1.3 业务边界

| 职责 | 归属 |
|------|------|
| 接收触发源与 Finding | 本模块（`EvolutionEngine`） |
| 阶段流转与 Proposal 生成 | 本模块（`EvolutionEngine`） |
| DZE 链状态管理 | 本模块（`DZEBridge`） |
| Dream Agent 任务与账本 | 本模块（`DreamAgentBridge`） |
| 审批工单与超时自动批准 | 本模块（`ApprovalBridge`） |
| 真实 DZE 执行 | 外部 DZE 链（未接入） |
| 真实飞书审批 | 飞书 OpenAPI（未接入） |
| 真实交易决策 | 各交易子系统（本模块不参与） |

---

## 2. 架构设计

### 2.1 分层架构

```
+-----------------------------------------------------------------------+
|                     编排层 (evolution-orchestrator.ts)                 |
|   EvolutionOrchestrator                                               |
|   - startEvolution()    启动进化流水线                                 |
|   - advanceDZEPhase()   推进 DZE 阶段                                 |
|   - passGate1/2()       门禁通过                                      |
|   - completeDreamAgentTask()  完成协作任务                             |
|   - processApprovalTimeout()  审批超时处理                             |
|   - getFullStatus()     全链路状态查询                                 |
+------------------+----------------------+------------------+---------+
                   |                      |                  |
+------------------v---------+  +----------v---------+  +-----v---------+
|     引擎层                 |  |   DZE 桥接层        |  |  Dream Agent  |
|  (evolution-engine.ts)     |  |  (dze-bridge.ts)   |  |  桥接层        |
|  EvolutionEngine           |  |  DZEBridge         |  |(dream-agent-  |
|  - createEvolution()       |  |  - createChain-    |  | bridge.ts)    |
|  - addFinding/Lesson()     |  |    FromEvolution() |  |  DreamAgent-  |
|  - generateProposals()     |  |  - advancePhase()  |  |  Bridge       |
|  - applyKnowledgeUpdate()  |  |  - passGate1/2()   |  |  - register-  |
|  - triggerCodeDevelopment()|  |  - completeChain() |  |    TaskFromDZE()|
|  - transitionPhase()       |  +-------------------+  |  - validate-   |
+------------------+---------+                          |    Task()      |
                   |                                    |  - finalize-   |
+------------------v---------+                          |    Task()      |
|     类型层 (types.ts)       |                          +---------------+
|  EvolutionFinding/Lesson/   |
|  Proposal/Record/Config     |  +-------------------+
+----------------------------+  |   审批桥接层       |
                                | (approval-bridge.ts)|
                                |  ApprovalBridge    |
                                |  - createApproval-  |
                                |    ForGate1/2/     |
                                |    Merge/Deployment|
                                |  - approve/reject()|
                                |  - autoApproveIf-  |
                                |    Eligible()      |
                                +-------------------+
```

### 2.2 模块关系

| 层 | 模块 | 职责 | 关键依赖 |
|----|------|------|----------|
| 编排层 | `EvolutionOrchestrator` | 驱动 9 阶段流水线，协调三桥接器 | `EvolutionEngine`, `DZEBridge`, `DreamAgentBridge`, `ApprovalBridge` |
| 引擎层 | `EvolutionEngine` | `EvolutionRecord` 生命周期、阶段流转、Proposal 生成、代码变更判定 | `types.ts` |
| DZE 桥接层 | `DZEBridge` | DZE 链状态机（d1-e3）、Gate1/Gate2 门禁、产物登记 | `types.ts`, `EvolutionRecord`, `EvolutionProposal` |
| Dream Agent 桥接层 | `DreamAgentBridge` | 任务注册、领取/提交/校验/入账、奖励分账、账本 | `types.ts`, `DZEChainState` |
| 审批桥接层 | `ApprovalBridge` | 五类审批工单、超时自动批准规则 | `types.ts`, `DZEChainState`, `DreamAgentTask` |
| 类型层 | `types.ts` | 全部数据结构与配置接口定义 | — |

---

## 3. 核心算法

### 3.1 代码变更判定（`EvolutionEngine.requiresCodeChange`）

```
requiresCodeChange(finding):
    severityRank = { low:0, medium:1, high:2, critical:3 }
    if severityRank[finding.severity] < severityRank[config.min_severity_for_code_change]:
        return false
    codeAreas = ['code', 'skill', 'engine', 'module', 'component', 'api']
    return finding.affected_areas.some(area =>
        codeAreas.some(ca => area.toLowerCase().includes(ca))
    )
```

**判定逻辑**：严重度达到 `min_severity_for_code_change`（默认 medium）且受影响区域包含代码类关键字时，判定为需要代码变更。

### 3.2 变更类型分派

```
determineChangeType(finding):
    if requiresCodeChange(finding):
        if affected_areas 含 'architect' → architecture_change
        elif affected_areas 含 'skill'    → skill_update
        else                              → code_change
    else:
        if source in ('lesson_distilled', 'a8_reflection') → knowledge_update
        else                                               → memory_update
```

### 3.3 DZE 阶段推进（`DZEBridge.advancePhase`）

```
phaseOrder = [d1,d2,d3,d4,z1,z2,z3,z4,e1,e2,e3]
advancePhase(triggerId, nextPhase):
    currentIdx = indexOf(state.current_phase)
    nextIdx = indexOf(nextPhase)
    if nextIdx <= currentIdx: throw Error('Cannot go backwards')
    for i in [currentIdx .. nextIdx]:
        state.phases_completed.push(phaseOrder[i])  // 去重
    state.current_phase = nextPhase
    state.phases_pending = phaseOrder[nextIdx+1 ..]
```

### 3.4 Gate 门禁校验

```
passGate1(triggerId, approved, approver='system'):
    assert state.current_phase == 'd4'   // Gate1 仅可在 d4 通过
    if approved:
        state.gate1_passed = true
        return true
    return false

passGate2(triggerId, approved, approver='system'):
    assert state.current_phase == 'z4'   // Gate2 仅可在 z4 通过
    if approved:
        state.gate2_passed = true
        return true
    return false
```

### 3.5 Dream Agent 奖励分账（`DreamAgentBridge.validateTask` / `finalizeTask`）

```
validateTask(passed):
    if passed:
        baseReward  = reward_estimate * 0.6    // developer
        validatorReward = reward_estimate * 0.2 // validator
        total_dream_rewarded += baseReward + validatorReward
    else:
        status = 'claimed'   // 退回待领取

finalizeTask(taskId, governanceId):
    assert status == 'validated'
    governanceReward = reward_estimate * 0.2   // governance
    total_dream_rewarded += governanceReward
    block_height += 1
    ledger_ref = 'block_' + block_height
```

### 3.6 审批超时自动批准（`ApprovalBridge.autoApproveIfEligible`）

```
autoApproveIfEligible(approvalId):
    approval = getApproval(approvalId)
    if approval.status != 'pending': return {approved: false, reason: ...}
    rule = autoApprovalRules.find(r => r.approval_type == approval.approval_type)
    if !rule or !rule.auto_approve: return {approved: false, reason: ...}
    elapsed = (now - approval.created_at) / 60000
    if elapsed < rule.timeout_minutes: return {approved: false, reason: ...}
    approval.status = 'timeout_auto_approved'
    approval.decided_by = 'auto-approval-bot'
    return {approved: true, reason: ...}
```

---

## 4. 数据流

### 4.1 进化主流程数据流

```
触发源 + Finding[]
    │
    ▼
EvolutionOrchestrator.startEvolution()
    │
    ├─→ EvolutionEngine.createEvolution()  → EvolutionRecord (phase=discovery)
    ├─→ transitionPhase('learning')
    ├─→ extractLessons(findings) → EvolutionLesson[]
    ├─→ addLessons()  → EvolutionRecord.lessons
    ├─→ generateProposals()
    │     └─→ for each finding:
    │           requiresCode = requiresCodeChange(finding)
    │           changeType = requiresCode ? determineCodeChangeType() : determineKnowledgeChangeType()
    │           → EvolutionProposal { change_type, requires_code, status:'pending_review' }
    └─→ processProposals()
          ├─ proposal.requires_code == true:
          │     ├─ DZEBridge.createChainFromEvolution() → DZEChainTrigger
          │     ├─ EvolutionEngine.triggerCodeDevelopment() → phase=code_development
          │     └─ ApprovalBridge.createApprovalForGate1() → ApprovalRequest(design)
          └─ proposal.requires_code == false:
                ├─ EvolutionEngine.applyKnowledgeUpdate() → phase=capability_update
                └─ if allProposalsImplemented → phase=completed, status=completed
```

### 4.2 数据结构

| 结构 | 字段 | 说明 |
|------|------|------|
| `EvolutionFinding` | id, source, severity, title, description, affected_areas, detected_at, raw_data? | 进化发现项 |
| `EvolutionLesson` | id, pattern, type(success/failure), frequency, severity, description, evidence_refs, first_seen, last_seen | 经验教训 |
| `EvolutionProposal` | id, finding_id, title, description, change_type, requires_code, rollback_plan_id, evidence_refs, status, created_at, approved_at? | 进化提案 |
| `EvolutionRecord` | id, phase, status, findings, lessons, proposals, current_phase, trigger_source, started_at, updated_at, completed_at?, metadata | 进化记录（核心聚合根） |
| `EvolutionRecord.metadata` | knowledge_updated, memory_updated, index_updated, code_changed, dze_chain_triggered, dream_agent_triggered, approval_required, approval_completed | 进化元数据标记 |
| `DZEChainState` | trigger_id, evolution_id, proposal_id, current_phase, task_scope, complexity, estimated_lines, affected_modules, phases_completed, phases_pending, gate1_passed, gate2_passed, started_at, updated_at, completed_at?, artifacts | DZE 链状态 |
| `DreamAgentTask` | evolution_id, dze_task_id?, task_id, title, description, assigned_roles, priority, reward_estimate, status, created_at, ledger_ref? | Dream Agent 任务 |
| `LedgerEntry` | id, task_id, evolution_id, agent_id, agent_role, action, reward_amount, timestamp, description, block_height? | 账本条目 |
| `ApprovalRequest` | id, evolution_id, proposal_id?, task_id?, approval_type, title, description, requester, approvers, status, created_at, decided_at?, decided_by?, feishu_approval_code?, feishu_instance_code? | 审批请求 |

---

## 5. 接口设计

### 5.1 `EvolutionEngine`（evolution-engine.ts）

| 方法 | 签名 | 说明 |
|------|------|------|
| `constructor` | `(config: Partial<EvolutionEngineConfig> = {})` | 初始化，合并默认配置 |
| `createEvolution` | `(triggerSource, findings?) => EvolutionRecord` | 创建进化记录，阶段=discovery |
| `addFinding` | `(evolutionId, finding) => void` | 追加发现项 |
| `addLessons` | `(evolutionId, lessons) => void` | 追加经验教训，discovery→learning |
| `generateProposals` | `(evolutionId) => EvolutionProposal[]` | 为每个 finding 生成提案，learning→deep_analysis |
| `applyKnowledgeUpdate` | `(evolutionId, proposalId) => boolean` | 应用知识更新，requires_code=false 才生效 |
| `triggerCodeDevelopment` | `(evolutionId, proposalId) => boolean` | 触发代码开发，requires_code=true 才生效 |
| `transitionPhase` | `(evolutionId, newPhase) => void` | 阶段流转 |
| `setStatus` | `(evolutionId, status) => void` | 设置状态，completed 时记录 completed_at |
| `getRecord` | `(evolutionId) => EvolutionRecord` | 获取单条记录 |
| `getAllRecords` | `() => EvolutionRecord[]` | 获取全部记录 |
| `getRecordsByPhase` | `(phase) => EvolutionRecord[]` | 按阶段筛选 |
| `getRecordsByStatus` | `(status) => EvolutionRecord[]` | 按状态筛选 |

### 5.2 `EvolutionOrchestrator`（evolution-orchestrator.ts）

| 方法 | 签名 | 说明 |
|------|------|------|
| `startEvolution` | `(triggerSource, findings) => OrchestratorResult` | 启动进化全流程 |
| `advanceDZEPhase` | `(evolutionId, phase: DZEPhase) => void` | 推进 DZE 阶段，e3→deployment，e*→code_development |
| `passGate1` | `(evolutionId, approved, approver='system') => boolean` | 通过 Gate1，成功则 z1 + code_development |
| `passGate2` | `(evolutionId, approved, approver='system') => boolean` | 通过 Gate2，成功则 e1 + 注册 Dream Agent 任务 |
| `completeDreamAgentTask` | `(evolutionId, taskId) => void` | 完成协作任务，DZE 链 complete，进化 completed |
| `processApprovalTimeout` | `(evolutionId) => number` | 处理审批超时，返回自动批准数 |
| `getFullStatus` | `(evolutionId) => {evolution, dzeChains, dreamAgentTasks, approvals}` | 全链路状态查询 |
| `getEngine` / `getDZEBridge` / `getDreamAgentBridge` / `getApprovalBridge` | `() => 对应实例` | 获取内部组件引用 |

### 5.3 `DZEBridge`（dze-bridge.ts）

| 方法 | 签名 | 说明 |
|------|------|------|
| `createChainFromEvolution` | `(evolutionRecord, proposal) => DZEChainTrigger` | 从进化记录创建 DZE 链 |
| `advancePhase` | `(triggerId, nextPhase) => DZEChainState` | 推进阶段（不可倒退） |
| `passGate1` | `(triggerId, approved, approver='system') => boolean` | Gate1 门禁（须在 d4） |
| `passGate2` | `(triggerId, approved, approver='system') => boolean` | Gate2 门禁（须在 z4） |
| `completeChain` | `(triggerId, deploymentRef) => DZEChainState` | 完成链（e3 + 全部阶段） |
| `addArtifact` | `(triggerId, artifactKey, value) => void` | 登记产物（d4_spec/z4_plan/e2_test/e3_deployment） |
| `getState` / `getAllChains` / `getChainsByEvolution` / `getChainsByPhase` | 查询方法 | 状态查询 |

### 5.4 `DreamAgentBridge`（dream-agent-bridge.ts）

| 方法 | 签名 | 说明 |
|------|------|------|
| `registerTaskFromDZE` | `(evolutionRecord, dzeState) => DreamAgentTask` | 从 DZE 链注册任务 |
| `assignDeveloper` | `(taskId, developerId) => DreamAgentTask` | 开发者领取（claimed） |
| `submitForValidation` | `(taskId, developerId) => DreamAgentTask` | 提交校验（in_progress） |
| `validateTask` | `(taskId, validatorId, passed, score=0) => DreamAgentTask` | 校验（validated/claimed） |
| `finalizeTask` | `(taskId, governanceId) => DreamAgentTask` | 治理入账（ledgered），须先 validated |
| `getTask` / `getAllTasks` / `getTasksByEvolution` / `getTasksByStatus` | 查询方法 | 任务查询 |
| `getLedger` / `getLedgerByTask` | `() => LedgerEntry[]` | 账本查询 |
| `getTotalRewards` / `getBlockHeight` | 统计方法 | 奖励/区块高度 |

### 5.5 `ApprovalBridge`（approval-bridge.ts）

| 方法 | 签名 | 说明 |
|------|------|------|
| `createApprovalForGate1` | `(evolutionRecord, dzeState, proposal) => ApprovalRequest` | 方案审批（design） |
| `createApprovalForGate2` | `(evolutionRecord, dzeState) => ApprovalRequest` | 开工审批（kickoff） |
| `createApprovalForMerge` | `(evolutionRecord, task) => ApprovalRequest` | 合入审批（merge） |
| `createApprovalForDeployment` | `(evolutionRecord, dzeState) => ApprovalRequest` | 部署审批（deployment） |
| `approve` / `reject` | `(approvalId, approver, reason?) => ApprovalRequest` | 人工审批 |
| `autoApproveIfEligible` | `(approvalId) => {approved, reason}` | 超时自动批准 |
| `checkTimeouts` | `() => ApprovalRequest[]` | 批量检查超时 |
| `setAutoApprovalRule` | `(rule) => void` | 设置自动批准规则 |
| `getApproval` / `getAllApprovals` / `getApprovalsByEvolution` / `getPendingApprovals` / `getApprovalsByType` | 查询方法 | 审批查询 |

---

## 6. 状态管理

### 6.1 存储位置

| 状态 | 存储位置 | 说明 |
|------|----------|------|
| 进化记录 | `EvolutionEngine.records: Map<string, EvolutionRecord>` | 内存，进程重启丢失 |
| DZE 链状态 | `DZEBridge.chainStates: Map<string, DZEChainState>` | 内存 |
| Dream Agent 状态 | `DreamAgentBridge.state.tasks: Map<string, DreamAgentTask>` | 内存 |
| 账本 | `DreamAgentBridge.state.ledger: LedgerEntry[]` | 内存 |
| 审批工单 | `ApprovalBridge.approvals: Map<string, ApprovalRequest>` | 内存 |
| 自动批准规则 | `ApprovalBridge.autoApprovalRules: AutoApprovalRule[]` | 内存，默认 5 条 |

### 6.2 状态机（进化阶段流转）

```
discovery ──addLessons──► learning ──generateProposals──► deep_analysis
                                                              │
                                    ┌─────────────────────────┤
                                    │                         │
                          requires_code=true          requires_code=false
                                    │                         │
                                    ▼                         ▼
                          code_development            capability_update
                                    │                         │
                          (DZE 链 d1→e3)            (all proposals
                                    │                    implemented)
                          Gate1(design)                  │
                          Gate2(kickoff)                 │
                          Dream Agent 协作               │
                                    │                     │
                                    ▼                     ▼
                              deployment ────────────► completed
```

---

## 7. 配置管理

配置通过 `EvolutionEngine` 构造函数传入 `Partial<EvolutionEngineConfig>`，未提供的字段使用默认值：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `data_dir` | `./evolution_data` | 进化数据目录 |
| `auto_trigger_dze` | `true` | 自动触发 DZE 链 |
| `auto_trigger_dream_agent` | `true` | 自动触发 Dream Agent |
| `auto_create_approvals` | `true` | 自动创建审批 |
| `approval_timeout_minutes` | `30` | 审批超时（分钟） |
| `min_severity_for_code_change` | `medium` | 代码变更最低严重度 |

`ApprovalBridge` 构造函数接受 `{ defaultTimeoutMinutes?: number }`，默认 30 分钟。自动批准规则通过 `initDefaultRules()` 初始化 5 条默认规则，可通过 `setAutoApprovalRule()` 覆盖。

---

## 8. 错误处理

| 场景 | 处理策略 | 实现位置 |
|------|----------|----------|
| 进化记录不存在 | `getRecord()` 抛 `Error('Evolution record ${id} not found')` | `evolution-engine.ts` |
| Proposal 不存在 | `applyKnowledgeUpdate()` / `triggerCodeDevelopment()` 抛 `Error('Proposal ${id} not found')` | `evolution-engine.ts` |
| DZE 阶段倒退 | `advancePhase()` 抛 `Error('Cannot go backwards from X to Y')` | `dze-bridge.ts` |
| Gate1 不在 d4 | `passGate1()` 抛 `Error('Gate 1 can only be passed at phase d4')` | `dze-bridge.ts` |
| Gate2 不在 z4 | `passGate2()` 抛 `Error('Gate 2 can only be passed at phase z4')` | `dze-bridge.ts` |
| DZE 链不存在 | `advancePhase()` / `passGate1/2()` 抛 `Error('DZE chain state ${id} not found')` | `dze-bridge.ts` |
| Task 未 validated 就 finalize | `finalizeTask()` 抛 `Error('Task must be validated before finalizing')` | `dream-agent-bridge.ts` |
| Task 不存在 | `getTask()` 抛 `Error('Task ${id} not found')` | `dream-agent-bridge.ts` |
| 审批不存在 | `getApproval()` 抛 `Error('Approval ${id} not found')` | `approval-bridge.ts` |

> 系统为纯内存态实验实现，无外部 I/O，错误主要为状态机校验异常。

---

## 9. 扩展性设计

### 9.1 新增触发源

在 `types.ts` 的 `EvolutionTriggerSource` 联合类型中新增取值，`EvolutionEngine.createEvolution()` 即可接收。

### 9.2 新增更新层

在 `types.ts` 的 `UpdateLayer` 联合类型中新增取值，并在 `EvolutionRecord.metadata` 中增加对应布尔标记。

### 9.3 新增审批类型

1. 在 `ApprovalRequest.approval_type` 联合类型中新增取值。
2. 在 `ApprovalBridge` 中新增 `createApprovalForXxx()` 方法。
3. 在 `initDefaultRules()` 中新增对应 `AutoApprovalRule`。

### 9.4 接入真实飞书审批

`ApprovalRequest` 已预留 `feishu_approval_code` / `feishu_instance_code` 字段，可在 `createApprovalFor*()` 中调用飞书审批 OpenAPI 填充。

### 9.5 持久化

当前全部状态存于内存 `Map`，可扩展为写入 `data_dir` 下的 JSON 文件或数据库，在 `EvolutionEngine` / 各 Bridge 构造时加载。

---

## 10. 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-09-30 | 初始版本：补建技术设计文档，覆盖概述/架构/算法/数据流/接口/状态/配置/错误处理/扩展性 9 章节 |

---

**文档版本**: v1.0
**最后更新**: 2026-09-30
