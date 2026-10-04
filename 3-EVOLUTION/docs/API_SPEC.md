# API 规范 — 3-EVOLUTION 进化引擎

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 模块接口规范，对齐 DOC_STANDARD §3.3

---

## 1. 接口概览

本模块为 TypeScript 库，不对外暴露 HTTP/RPC/CLI 接口，全部通过类方法调用。共 5 个核心类：

| 类 | 文件 | 职责 | 方法数 |
|----|------|------|--------|
| `EvolutionEngine` | `evolution-engine.ts` | 进化记录生命周期管理 | 13 |
| `EvolutionOrchestrator` | `evolution-orchestrator.ts` | 进化流水线编排 | 9 |
| `DZEBridge` | `dze-bridge.ts` | DZE 链状态管理 | 9 |
| `DreamAgentBridge` | `dream-agent-bridge.ts` | Dream Agent 任务与账本 | 12 |
| `ApprovalBridge` | `approval-bridge.ts` | 审批工单与超时处理 | 12 |

### 1.1 接口列表

| 模块 | 接口 | 类型 |
|------|------|------|
| 引擎层 | `EvolutionEngine` | 类 |
| 编排层 | `EvolutionOrchestrator` | 类 |
| DZE 桥接 | `DZEBridge` | 类 |
| Dream Agent 桥接 | `DreamAgentBridge` | 类 |
| 审批桥接 | `ApprovalBridge` | 类 |
| 类型层 | `EvolutionTriggerSource` / `EvolutionPhase` / `EvolutionStatus` / `UpdateLayer` | 类型别名 |
| 类型层 | `EvolutionFinding` / `EvolutionLesson` / `EvolutionProposal` / `EvolutionRecord` | 接口 |
| 类型层 | `DZEChainTrigger` / `DreamAgentTask` / `ApprovalRequest` / `EvolutionEngineConfig` | 接口 |

---

## 2. 认证方式

本模块为内部 TypeScript 库，无认证机制。`ApprovalBridge` 预留飞书审批对接字段（`feishu_approval_code` / `feishu_instance_code`），但当前未实际调用飞书 OpenAPI。

---

## 3. 接口详情

### 3.1 `EvolutionEngine`（evolution-engine.ts）

**构造函数**

```typescript
constructor(config?: Partial<EvolutionEngineConfig>)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config` | `Partial<EvolutionEngineConfig>` | `{}` | 进化引擎配置 |

**`EvolutionEngineConfig` 字段**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `data_dir` | `string` | `'./evolution_data'` | 进化数据目录 |
| `auto_trigger_dze` | `boolean` | `true` | 自动触发 DZE 链 |
| `auto_trigger_dream_agent` | `boolean` | `true` | 自动触发 Dream Agent |
| `auto_create_approvals` | `boolean` | `true` | 自动创建审批 |
| `approval_timeout_minutes` | `number` | `30` | 审批超时（分钟） |
| `min_severity_for_code_change` | `'low' \| 'medium' \| 'high'` | `'medium'` | 代码变更最低严重度 |

**方法**

| 方法 | 签名 | 说明 |
|------|------|------|
| `createEvolution` | `(triggerSource: EvolutionTriggerSource, findings?: EvolutionFinding[]) => EvolutionRecord` | 创建进化记录，阶段=discovery，状态=in_progress |
| `addFinding` | `(evolutionId: string, finding: EvolutionFinding) => void` | 追加发现项 |
| `addLessons` | `(evolutionId: string, lessons: EvolutionLesson[]) => void` | 追加经验教训，若当前为 discovery 则流转到 learning |
| `generateProposals` | `(evolutionId: string) => EvolutionProposal[]` | 为每个 finding 生成提案，若当前为 learning 则流转到 deep_analysis |
| `applyKnowledgeUpdate` | `(evolutionId: string, proposalId: string) => boolean` | 应用知识更新（仅 requires_code=false 的提案），流转到 capability_update |
| `triggerCodeDevelopment` | `(evolutionId: string, proposalId: string) => boolean` | 触发代码开发（仅 requires_code=true 的提案），标记 code_changed/dze_chain_triggered |
| `transitionPhase` | `(evolutionId: string, newPhase: EvolutionPhase) => void` | 阶段流转 |
| `setStatus` | `(evolutionId: string, status: EvolutionStatus) => void` | 设置状态，completed 时记录 completed_at |
| `getRecord` | `(evolutionId: string) => EvolutionRecord` | 获取单条记录（深拷贝） |
| `getAllRecords` | `() => EvolutionRecord[]` | 获取全部记录 |
| `getRecordsByPhase` | `(phase: EvolutionPhase) => EvolutionRecord[]` | 按阶段筛选 |
| `getRecordsByStatus` | `(status: EvolutionStatus) => EvolutionRecord[]` | 按状态筛选 |

**示例**

```typescript
import { EvolutionEngine } from './evolution-engine';

const engine = new EvolutionEngine({ min_severity_for_code_change: 'high' });
const record = engine.createEvolution('execution_failure', [
  { id: 'f1', source: 'execution_failure', severity: 'high',
    title: '测试失败', description: '...', affected_areas: ['code'],
    detected_at: new Date().toISOString() },
]);
console.log(record.id);  // evo_xxx_xxx
```

### 3.2 `EvolutionOrchestrator`（evolution-orchestrator.ts）

**构造函数**

```typescript
constructor()
```

无参数，内部实例化 `EvolutionEngine` + 三个桥接器。

**`OrchestratorResult` 接口**

| 字段 | 类型 | 说明 |
|------|------|------|
| `evolutionId` | `string` | 进化记录 ID |
| `currentPhase` | `EvolutionPhase` | 当前阶段 |
| `dzeTriggered` | `boolean` | 是否已触发 DZE 链 |
| `dreamAgentTriggered` | `boolean` | 是否已触发 Dream Agent |
| `approvalsCreated` | `number` | 已创建审批数 |
| `status` | `string` | 进化状态 |

**方法**

| 方法 | 签名 | 说明 |
|------|------|------|
| `startEvolution` | `(triggerSource: EvolutionTriggerSource, findings: EvolutionFinding[]) => OrchestratorResult` | 启动进化全流程：创建→学习→提案→按 requires_code 分流 |
| `advanceDZEPhase` | `(evolutionId: string, phase: DZEPhase) => void` | 推进 DZE 阶段；e3→deployment，e*→code_development |
| `passGate1` | `(evolutionId: string, approved: boolean, approver?: string) => boolean` | 通过 Gate1，成功则 z1 + approval_completed + code_development |
| `passGate2` | `(evolutionId: string, approved: boolean, approver?: string) => boolean` | 通过 Gate2，成功则 e1 + 注册 Dream Agent 任务 |
| `completeDreamAgentTask` | `(evolutionId: string, taskId: string) => void` | 完成协作任务：finalizeTask + completeChain + completed |
| `processApprovalTimeout` | `(evolutionId: string) => number` | 处理审批超时，design→passGate1，kickoff→passGate2，返回自动批准数 |
| `getFullStatus` | `(evolutionId: string) => {evolution, dzeChains, dreamAgentTasks, approvals}` | 全链路状态查询 |
| `getEngine` | `() => EvolutionEngine` | 获取引擎实例 |
| `getDZEBridge` / `getDreamAgentBridge` / `getApprovalBridge` | `() => 对应实例` | 获取桥接器实例 |

**示例**

```typescript
import { EvolutionOrchestrator } from './evolution-orchestrator';

const orch = new EvolutionOrchestrator();
const result = orch.startEvolution('execution_failure', findings);
console.log(result.dzeTriggered);  // true（若为代码变更）
```

### 3.3 `DZEBridge`（dze-bridge.ts）

**`DZEPhase` 类型**：`'d1' \| 'd2' \| 'd3' \| 'd4' \| 'z1' \| 'z2' \| 'z3' \| 'z4' \| 'e1' \| 'e2' \| 'e3'`

**`DZEChainState` 关键字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `trigger_id` | `string` | 链触发 ID |
| `current_phase` | `DZEPhase` | 当前阶段 |
| `phases_completed` | `DZEPhase[]` | 已完成阶段 |
| `phases_pending` | `DZEPhase[]` | 待执行阶段 |
| `gate1_passed` / `gate2_passed` | `boolean` | 门禁状态 |
| `artifacts` | `{d4_spec_path?, z4_plan_path?, e3_deployment_ref?, e2_test_report?}` | 产物路径 |

**方法**

| 方法 | 签名 | 说明 |
|------|------|------|
| `createChainFromEvolution` | `(evolutionRecord: EvolutionRecord, proposal: EvolutionProposal) => DZEChainTrigger` | 从进化记录创建 DZE 链，starting_phase=d1 |
| `advancePhase` | `(triggerId: string, nextPhase: DZEPhase) => DZEChainState` | 推进阶段（不可倒退），更新 completed/pending |
| `passGate1` | `(triggerId: string, approved: boolean, approver?: string) => boolean` | Gate1 门禁，须在 d4 阶段 |
| `passGate2` | `(triggerId: string, approved: boolean, approver?: string) => boolean` | Gate2 门禁，须在 z4 阶段 |
| `completeChain` | `(triggerId: string, deploymentRef: string) => DZEChainState` | 完成链：e3 + 全部阶段 completed + e3_deployment_ref |
| `addArtifact` | `(triggerId: string, artifactKey: keyof DZEChainState['artifacts'], value: string) => void` | 登记产物路径 |
| `getState` | `(triggerId: string) => DZEChainState` | 获取链状态（深拷贝） |
| `getAllChains` | `() => DZEChainState[]` | 全部链 |
| `getChainsByEvolution` | `(evolutionId: string) => DZEChainState[]` | 按进化 ID 筛选 |
| `getChainsByPhase` | `(phase: DZEPhase) => DZEChainState[]` | 按阶段筛选 |

### 3.4 `DreamAgentBridge`（dream-agent-bridge.ts）

**`AgentRole` 类型**：`'developer' \| 'validator' \| 'governance'`

**`DreamAgentTask` 关键字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | `string` | 任务 ID |
| `assigned_roles` | `AgentRole[]` | 分配角色（默认 developer/validator/governance） |
| `priority` | `'low' \| 'medium' \| 'high'` | 优先级（由 complexity 决定） |
| `reward_estimate` | `number` | 奖励估算（small=100/medium=500/large=2000） |
| `status` | `'registered' \| 'claimed' \| 'in_progress' \| 'validated' \| 'ledgered'` | 任务状态 |
| `ledger_ref` | `string?` | 账本引用（block_N） |

**方法**

| 方法 | 签名 | 说明 |
|------|------|------|
| `registerTaskFromDZE` | `(evolutionRecord: EvolutionRecord, dzeState: DZEChainState) => DreamAgentTask` | 从 DZE 链注册任务 |
| `assignDeveloper` | `(taskId: string, developerId: string) => DreamAgentTask` | 开发者领取，status=claimed |
| `submitForValidation` | `(taskId: string, developerId: string) => DreamAgentTask` | 提交校验，status=in_progress |
| `validateTask` | `(taskId: string, validatorId: string, passed: boolean, score?: number) => DreamAgentTask` | 校验：passed→validated（奖励 developer 60%+validator 20%），否则 claimed |
| `finalizeTask` | `(taskId: string, governanceId: string) => DreamAgentTask` | 治理入账：须 validated，status=ledgered，奖励 governance 20%，block_height++ |
| `getTask` | `(taskId: string) => DreamAgentTask` | 获取任务（深拷贝） |
| `getAllTasks` | `() => DreamAgentTask[]` | 全部任务 |
| `getTasksByEvolution` | `(evolutionId: string) => DreamAgentTask[]` | 按进化 ID 筛选 |
| `getTasksByStatus` | `(status: DreamAgentTask['status']) => DreamAgentTask[]` | 按状态筛选 |
| `getLedger` | `() => LedgerEntry[]` | 全部账本 |
| `getLedgerByTask` | `(taskId: string) => LedgerEntry[]` | 按任务筛选账本 |
| `getTotalRewards` | `() => number` | 累计奖励 |
| `getBlockHeight` | `() => number` | 区块高度 |

### 3.5 `ApprovalBridge`（approval-bridge.ts）

**`ApprovalRequest.approval_type` 类型**：`'design' \| 'kickoff' \| 'risk' \| 'merge' \| 'deployment'`

**`ApprovalRequest.status` 类型**：`'pending' \| 'approved' \| 'rejected' \| 'timeout_auto_approved'`

**构造函数**

```typescript
constructor(config?: { defaultTimeoutMinutes?: number })
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config.defaultTimeoutMinutes` | `number` | `30` | 默认审批超时（分钟） |

**方法**

| 方法 | 签名 | 说明 |
|------|------|------|
| `createApprovalForGate1` | `(evolutionRecord, dzeState, proposal) => ApprovalRequest` | 方案审批（design），approvers=[human-approver, governance-agent] |
| `createApprovalForGate2` | `(evolutionRecord, dzeState) => ApprovalRequest` | 开工审批（kickoff） |
| `createApprovalForMerge` | `(evolutionRecord, task) => ApprovalRequest` | 合入审批（merge） |
| `createApprovalForDeployment` | `(evolutionRecord, dzeState) => ApprovalRequest` | 部署审批（deployment），approvers=[human-approver] |
| `approve` | `(approvalId: string, approver: string) => ApprovalRequest` | 批准 |
| `reject` | `(approvalId: string, approver: string, reason: string) => ApprovalRequest` | 拒绝（reason 追加到 description） |
| `autoApproveIfEligible` | `(approvalId: string) => {approved: boolean, reason: string}` | 超时自动批准 |
| `checkTimeouts` | `() => ApprovalRequest[]` | 批量检查并自动批准超时审批 |
| `setAutoApprovalRule` | `(rule: AutoApprovalRule) => void` | 设置/覆盖自动批准规则 |
| `getApproval` | `(approvalId: string) => ApprovalRequest` | 获取审批（深拷贝） |
| `getAllApprovals` | `() => ApprovalRequest[]` | 全部审批 |
| `getApprovalsByEvolution` | `(evolutionId: string) => ApprovalRequest[]` | 按进化 ID 筛选 |
| `getPendingApprovals` | `() => ApprovalRequest[]` | 待审批列表 |
| `getApprovalsByType` | `(type: ApprovalRequest['approval_type']) => ApprovalRequest[]` | 按类型筛选 |

**示例**

```typescript
import { ApprovalBridge } from './approval-bridge';

const bridge = new ApprovalBridge({ defaultTimeoutMinutes: 60 });
const approval = bridge.createApprovalForGate1(record, dzeState, proposal);
const result = bridge.autoApproveIfEligible(approval.id);
console.log(result.approved);  // false（未超时）
```

### 3.6 类型定义（types.ts）

**`EvolutionTriggerSource`**（10 类）
```typescript
type EvolutionTriggerSource =
  | 'execution_failure' | 'low_confidence' | 'chain_disagreement'
  | 'user_feedback' | 'governance_alert' | 'scheduled_audit'
  | 'lesson_distilled' | 'a8_reflection' | 'dream_oneirology'
  | 'orchestration_optimization';
```

**`EvolutionPhase`**（9 阶段）
```typescript
type EvolutionPhase =
  | 'discovery' | 'learning' | 'deep_analysis' | 'capability_update'
  | 'code_development' | 'collaboration' | 'approval' | 'deployment'
  | 'completed';
```

**`EvolutionStatus`**（6 状态）
```typescript
type EvolutionStatus = 'pending' | 'in_progress' | 'blocked' | 'completed' | 'failed' | 'skipped';
```

**`UpdateLayer`**（6 层）
```typescript
type UpdateLayer = 'knowledge' | 'memory' | 'index' | 'skill' | 'code' | 'architecture';
```

---

## 4. 错误码

本模块为纯 TypeScript 库，错误以 `Error` 异常抛出，无数字错误码。错误消息约定：

| 错误场景 | 错误消息 | 抛出位置 |
|----------|----------|----------|
| 进化记录不存在 | `Evolution record ${id} not found` | `EvolutionEngine.getRecord` |
| Proposal 不存在 | `Proposal ${id} not found` | `applyKnowledgeUpdate` / `triggerCodeDevelopment` |
| DZE 阶段倒退 | `Cannot go backwards from ${current} to ${next}` | `DZEBridge.advancePhase` |
| Gate1 阶段不符 | `Gate 1 can only be passed at phase d4, currently at ${phase}` | `DZEBridge.passGate1` |
| Gate2 阶段不符 | `Gate 2 can only be passed at phase z4, currently at ${phase}` | `DZEBridge.passGate2` |
| DZE 链不存在 | `DZE chain state ${id} not found` | `DZEBridge.getState` |
| 进化无 DZE 链 | `No DZE chain found for evolution ${id}` | `EvolutionOrchestrator.advanceDZEPhase` 等 |
| Task 不存在 | `Task ${id} not found` | `DreamAgentBridge.getTask` |
| Task 未 validated | `Task must be validated before finalizing, current: ${status}` | `DreamAgentBridge.finalizeTask` |
| 审批不存在 | `Approval ${id} not found` | `ApprovalBridge.getApproval` |

---

## 5. 版本管理

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-30 | 初始 API 规范版本，覆盖 EvolutionEngine / EvolutionOrchestrator / DZEBridge / DreamAgentBridge / ApprovalBridge 全部公开方法 |

> 当前模块为实验状态，API 可能随主线集成而调整。变更以 `CHANGELOG.md` 为准。

---

**文档版本**: v1.0
**最后更新**: 2026-09-30
