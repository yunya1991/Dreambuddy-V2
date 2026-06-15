# 7-ARTIFACT-HUB-V2 治理对象模型

> 版本：v1.1  
> 更新日期：2026-05-16  
> 作用：统一 `7-ARTIFACT-HUB-V2` 的核心对象命名与最小字段语义，作为双中台、双交易工作流、董事会与审计体系的共同语言。

## 1. 当前范围

本文件不再把 12 个对象全部展开到完整字段级别。

当前阶段只做两件事：

- 明确哪些对象已与现有代码有映射；
- 为 Phase 1 的核心对象定义最小字段；
- 对 Phase 2 / Phase 3 对象只保留名称、职责和落地方向。

## 2. 当前代码映射

当前代码中已有较强映射的对象如下：

| 治理对象 | 当前代码 / 数据载体 | 说明 |
|---|---|---|
| `Artifact` | `artifact-store.ts`、artifact index | 已有明确落点 |
| `Audit` | trace / event 系统 | 已有追踪与事件记录基础 |
| `Decision` | route decision 记录 | 已有近似实现，但字段仍需统一 |
| `Execution` | task / result 文件、工作流运行记录 | 已有近似实现，但对象尚未收口 |

当前尚未正式落地为独立类型的对象包括：

- `Department`
- `Intent`
- `Distribution`
- `Performance`
- `MarketIntel`
- `MinisterAgent`
- `BoardProposal`
- `ApprovalGate`
- `ExecutionReview`

## 3. 顶层关系

治理对象不是严格线性链路，而是一个可回环系统。

```text
MarketIntel -> Intent -> Decision -> Execution -> Artifact -> Distribution -> Audit
Audit -> Intent
Performance -> Decision
BoardProposal -> ApprovalGate -> ExecutionReview
Department -> all
```

关键回环包括：

- `Audit -> Intent`：审计发现异常后，重新生成新任务或新治理动作；
- `Performance -> Decision`：绩效信号推动策略调整或部门优化；
- `MarketIntel -> Intent`：外部情报进入研究、交易或运营链路；
- `BoardProposal -> ApprovalGate -> ExecutionReview`：重大事项从议案到审批再回到复盘。

## 4. Phase 1 核心对象

### 4.1 Department

表示系统中的正式部门，是所有记录的组织归属。

第一版固定为：

- `research`
- `trading`
- `governance`
- `operations`
- `hr`
- `market`

最小字段建议：

- `department_id`
- `name`
- `responsibility_scope`
- `status`

### 4.2 Intent

表示输入目标，是治理链路的起点。

最小字段建议：

- `intent_id`
- `source_type`
- `source_ref`
- `department`
- `payload`
- `priority`
- `created_at`

### 4.3 Decision

表示 AI 或系统做出的判断、推荐和路由决策，用于回答“为什么这样做”。

最小字段建议：

- `decision_id`
- `trace_id`
- `intent_id`
- `department`
- `policy_version`
- `selected_route`
- `reason`
- `evidence_refs`
- `decision_level`
- `created_at`

### 4.4 Execution

表示实际执行了什么，用于回答“系统到底做了什么”。

最小字段建议：

- `execution_id`
- `trace_id`
- `intent_id`
- `decision_id`
- `workflow_id`
- `workflow_type`
- `department`
- `status`
- `started_at`
- `finished_at`

### 4.5 Artifact

表示系统产出或消费的正式产物，是当前最明确的落地对象之一。

最小字段建议：

- `artifact_id`
- `title`
- `department`
- `category`
- `type`
- `chain_phase`
- `workflow_id`
- `workflow_type`
- `trace_id`
- `status`
- `relative_path`
- `created_at`

### 4.6 Audit

表示一条治理链路的可回放视图，用于回答“事后如何追溯”。

最小字段建议：

- `audit_id`
- `trace_id`
- `department`
- `decision_snapshot`
- `execution_snapshot`
- `events`
- `risk_flags`
- `review_notes`
- `created_at`

## 5. Phase 2 对象

Phase 2 对象先只定义职责，不展开完整字段。

### 5.1 Distribution

表示内容或策略如何被分发到目标人群与渠道，用于治理分发黑箱。

### 5.2 Performance

表示部门或链路的绩效结果，用于支撑 HR 评估与组织优化。

### 5.3 MarketIntel

表示外部市场与竞争情报，用于把外部变化输入研究、交易与运营链路。

## 6. Phase 3 对象

Phase 3 对象属于更强治理与审批能力，当前只保留名字和职责。

### 6.1 MinisterAgent

表示部门治理责任的角色标识，不等于当前已经存在独立 LLM agent 实现。

### 6.2 BoardProposal

表示跨部门或重大事项的结构化议案。

### 6.3 ApprovalGate

表示重大事项的审批门与审批结果。

### 6.4 ExecutionReview

表示重大动作执行后的复盘记录。

## 7. 最小落地顺序

### Phase 1

先统一以下对象字段与命名：

- `Department`
- `Intent`
- `Decision`
- `Execution`
- `Artifact`
- `Audit`

### Phase 2

在前六个对象稳定后，再接入：

- `Distribution`
- `Performance`
- `MarketIntel`

### Phase 3

最后接入更强治理对象：

- `MinisterAgent`
- `BoardProposal`
- `ApprovalGate`
- `ExecutionReview`

## 8. 一句话结论

这份对象模型的目标不是把所有未来对象一次性设计完，而是：

> 先用最小可落地的一组对象，把当前 Hub、路由、追踪、产物与审计语言统一起来，再逐步扩展到分发、绩效、董事会与审批体系。
