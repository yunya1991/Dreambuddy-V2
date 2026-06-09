# 董事会总览台设计

> 版本：v1.1  
> 更新日期：2026-05-16  
> 状态：规划中  
> 作用：定义“六人董事会（治理委员会）”的总览台定位、页面结构、决策分级标记和与人工审批的关系。

## 0. 当前实现状态

董事会总览台当前是规划页面，不是主仓现状。

| 项目 | 状态 | 说明 |
|---|---|---|
| 董事会总览台页面 | 规划中 | 当前主仓尚无该页面 |
| 待审批区 | 规划中 | 当前尚无现成审批 UI |
| L1/L2/L3 展示 | 规划中 | 当前仅定义治理标记模型 |

## 1. 定位

董事会总览台不是普通 dashboard，而是：

- 六位部长 Agent 的联合管理视图；
- 公司中枢的监督与协同页面；
- 重大事项升级前的治理收敛点；
- 人工审批前的提案整合入口。

它的上位定位是：

> 公司中枢中的管理大脑页面。

## 2. 目标

董事会总览台要解决的问题是：

- 六个部门各自有页面，但缺少统一管理视图；
- 跨部门问题容易散落在多个中台；
- 小问题、中问题、重大事项缺少统一分级入口；
- 人工审批前缺少结构化议案汇总。

因此董事会总览台的目标是：

- 汇总六部门状态；
- 聚合跨部门问题；
- 跟踪已自主处理事项；
- 管理中问题会签；
- 将重大事项整理为人工审批议案。

## 3. 六人董事会模型

### 3.1 成员

- 研究部长 Agent
- 交易部长 Agent
- 治理部长 Agent
- 运营部长 Agent
- HR 部长 Agent
- 市场部长 Agent

### 3.2 角色

每位部长 Agent 不直接替代部门业务，而是：

- 监督部门目标；
- 检查异常；
- 推动优化；
- 对小问题做快速决策；
- 对中问题参与联席讨论；
- 对重大事项形成议案。

### 3.3 与人工审批的关系

董事会总览台不是最终裁决者。

重大事项必须：

- 经董事会整理；
- 形成结构化 proposal；
- 提交人工审批。

## 4. 页面结构

### 4.1 顶部总览区

展示：

- 六部门健康度；
- 今日关键异常；
- 今日已自主处理事项数；
- 待会签中问题数；
- 待人工审批重大事项数。

### 4.2 六部长状态区

以六卡片形式展示：

- 研究部长 Agent
- 交易部长 Agent
- 治理部长 Agent
- 运营部长 Agent
- HR 部长 Agent
- 市场部长 Agent

每张卡片显示：

- 部门健康度；
- 当前关键任务；
- 最近异常；
- 最近建议动作；
- 决策等级分布。

### 4.3 跨部门问题区

用于展示跨部门问题，例如：

- 研究产物未能支撑交易决策；
- `/chain` 双工作流状态冲突；
- 市场部情报未被研究部及时吸收；
- 运营部分发与治理红线冲突；
- HR 绩效预警与实际执行矛盾。

### 4.4 董事会议案区

汇总：

- 待讨论议案；
- 已通过议案；
- 已驳回议案；
- 待补充证据议案。

### 4.5 人工审批待办区

用于展示：

- 已升级为 L3 的重大事项；
- 建议动作；
- 风险说明；
- 回滚方案；
- 当前审批状态。

## 5. 决策分级

本页中的 `L1 / L2 / L3` 与 `GOVERNANCE_SPEC.md` 保持一致，当前统一视为治理标记字段，而不是已实现的自动化执行流程。

### 5.1 L1 小问题

`L1` 表示部门内可收敛的低风险事项。

董事会总览台当前只要求能记录与展示。

### 5.2 L2 中问题

`L2` 表示需要跨部门协同的事项，会在总览台里进入：

- 议题池；
- 会签区；
- 联合建议区。

### 5.3 L3 重大事项

`L3` 表示必须上报人工审批的重大事项，需要进入：

- 重大事项区；
- 人工审批待办区；
- 审批结果回写区。

## 6. 关键模块

### 6.1 六部门健康图

用于统一展示：

- 研究部状态；
- 交易部状态；
- 治理部状态；
- 运营部状态；
- HR 状态；
- 市场部状态。

### 6.2 风险与异常图

用于统一展示：

- 关键风险；
- 审计异常；
- 工作流阻塞；
- 绩效异常；
- 分发异常。

### 6.3 已自主处理事项

若后续开放 Agent 自主闭环，本区应显式展示获准自主闭环的事项。

这样可以回答：

- 系统未来可自主处理哪些事项；
- 为什么这些事项可以自主处理；
- 是否可能产生副作用；
- 后续是否仍需要追审。

### 6.4 重大议案

重大议案必须至少显示：

- 来源部门；
- 发起部长 Agent；
- 问题摘要；
- 建议动作；
- 证据链；
- 风险说明；
- 回滚方案；
- 审批状态。

## 7. 与其他页面的关系

### 7.1 与研究中台

- 在目标关系中，研究中台将提供研究产物与研究链路状态；
- 董事会总览台将主要关注其对全局的影响与问题。

### 7.2 与 `/chain`

- 在目标关系中，`/chain` 将提供两套交易工作流的可视化与健康状态；
- 董事会总览台将从管理层视角查看它们是否影响公司运行。

### 7.3 与治理控制台

- 在目标关系中，治理控制台将承接 route / trace / audit 的细节；
- 董事会总览台将把这些细节汇总成管理议题。

### 7.4 与市场化中台

- 在目标关系中，市场化中台将负责具体分发动作；
- 董事会总览台将主要关注分发对全局运营、风险和绩效的影响。

### 7.5 与 HR / 市场部

- 在目标关系中，HR 将提供绩效与组织优化信号；
- 市场部将提供外部竞争与机会信号；
- 董事会总览台将把这两类信号纳入跨部门判断。

## 8. 对象模型映射

董事会总览台主要依赖：

- `Department`
- `MinisterAgent`
- `BoardProposal`
- `ApprovalGate`
- `Audit`
- `Performance`
- `MarketIntel`

其中 `MinisterAgent`、`BoardProposal`、`ApprovalGate`、`Performance`、`MarketIntel` 当前均属于后续阶段对象，不代表主仓已有实现。

## 8.1 Phase 3 已实现 API 路由

> 更新日期：2026-05-18
> 实现状态：**已交付（Phase 3, PR #45 + PR #47）**

以下路由已在 `7-ARTIFACT-HUB-V2/src/` 中完整实现，MetaStore 持久化至 SQLite（`artifact_hub.sqlite`）。

### 8.1.1 BoardProposal — 议案管理

**类型定义（`src/types.ts`）：**

```typescript
type BoardProposalStatus = 'draft' | 'submitted' | 'under_review' | 'approved' | 'rejected' | 'withdrawn';

interface BoardProposal {
  proposal_id: string;
  trace_id: string;
  department: string;
  decision_level: DecisionLevel;    // "L1" | "L2" | "L3"
  title: string;
  summary: string;
  proposer_agent: MinisterAgent;    // enum: "governance_minister_agent" 等
  status: BoardProposalStatus;
  created_at: ISODateString;
  resolved_at?: ISODateString;
}
```

**MetaStore 持久化方法（`src/meta-store.ts`）：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `addBoardProposal` | `(proposal: BoardProposal): void` | 插入议案记录 |

**SQLite 表结构（`board_proposals`）：**

```sql
CREATE TABLE IF NOT EXISTS board_proposals (
  proposal_id   TEXT PRIMARY KEY,
  trace_id      TEXT NOT NULL,
  department    TEXT NOT NULL,
  decision_level TEXT NOT NULL,
  title         TEXT NOT NULL,
  summary       TEXT NOT NULL,
  proposer_agent TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'draft',
  created_at    TEXT NOT NULL,
  resolved_at   TEXT
);
```

### 8.1.2 ApprovalGate — 审批门控

**类型定义（`src/types.ts`）：**

```typescript
interface ApprovalGate {
  gate_id: string;
  proposal_id: string;
  required_approvers: MinisterAgent[];
  received_approvals: MinisterAgent[];
  status: ApprovalStatus;    // "pending" | "approved" | "rejected" | "needs_more_evidence"
  decided_at?: ISODateString;
}
```

**MetaStore 持久化方法：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `addApprovalGate` | `(gate: ApprovalGate): void` | 插入审批门控记录，数组字段 JSON 序列化 |

**SQLite 表结构（`approval_gates`）：**

```sql
CREATE TABLE IF NOT EXISTS approval_gates (
  gate_id                TEXT PRIMARY KEY,
  proposal_id            TEXT NOT NULL,
  required_approvers_json TEXT NOT NULL,
  received_approvals_json TEXT NOT NULL DEFAULT '[]',
  status                 TEXT NOT NULL DEFAULT 'pending',
  decided_at             TEXT
);
```

### 8.1.3 ExecutionReview — 执行复审

**类型定义（`src/types.ts`）：**

```typescript
interface ExecutionReview {
  review_id: string;
  trace_id: string;
  execution_id: string;
  reviewer_agent: MinisterAgent;
  verdict: 'pass' | 'pass_with_notes' | 'fail' | 'escalate';
  findings: string;
  recommendations: string;
  reviewed_at: ISODateString;
}
```

**MetaStore 持久化方法：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `addExecutionReview` | `(review: ExecutionReview): void` | 插入复审记录 |
| `listExecutionReviews` | `(traceId?: string): ExecutionReview[]` | 查询复审列表，支持 trace_id 过滤 |

**SQLite 表结构（`execution_reviews`）：**

```sql
CREATE TABLE IF NOT EXISTS execution_reviews (
  review_id      TEXT PRIMARY KEY,
  trace_id       TEXT NOT NULL,
  execution_id   TEXT NOT NULL,
  reviewer_agent TEXT NOT NULL,
  verdict        TEXT NOT NULL,
  findings       TEXT NOT NULL,
  recommendations TEXT NOT NULL,
  reviewed_at    TEXT NOT NULL
);
```

### 8.1.4 HTTP 路由 — GET /chain/reviews

**实现位置：** `src/index.ts`

```
GET /chain/reviews
GET /chain/reviews?trace_id=<trace_id>
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `trace_id` | query string | 否 | 按 trace_id 过滤结果 |

**响应结构：**

```json
{
  "reviews": [
    {
      "review_id": "rev-001",
      "trace_id": "trace-abc",
      "execution_id": "exec-001",
      "reviewer_agent": "governance_minister_agent",
      "verdict": "pass",
      "findings": "...",
      "recommendations": "...",
      "reviewed_at": "2026-05-18T10:00:00Z"
    }
  ],
  "total": 1
}
```

**错误响应：**

| 状态码 | 场景 |
|--------|------|
| `405 Method Not Allowed` | 非 GET 请求 |

### 8.1.5 Phase 3 对象关系图

```
BoardProposal (board_proposals)
    ├── proposal_id (PK)
    ├── trace_id → links to executions.trace_id
    ├── decision_level: L1 / L2 / L3
    ├── proposer_agent: MinisterAgent enum
    └── status: draft → submitted → under_review → approved/rejected/withdrawn

ApprovalGate (approval_gates)
    ├── gate_id (PK)
    ├── proposal_id → BoardProposal.proposal_id
    ├── required_approvers: MinisterAgent[]  (JSON)
    ├── received_approvals: MinisterAgent[]  (JSON)
    └── status: pending → approved/rejected/needs_more_evidence

ExecutionReview (execution_reviews)
    ├── review_id (PK)
    ├── trace_id → links to executions.trace_id
    ├── execution_id → executions.execution_id
    ├── reviewer_agent: MinisterAgent enum
    └── verdict: pass / pass_with_notes / fail / escalate

HTTP Route:
    GET /chain/reviews[?trace_id=X] → MetaStore.listExecutionReviews(traceId?)
```


## 9. 页面风格建议

董事会总览台不应做成“花哨大屏”，而应更像：

- 管理驾驶舱；
- 结构化议题台；
- 决策收敛台。

页面风格重点：

- 强结构；
- 强分级；
- 强风险提示；
- 强待办与升级路径；
- 强跨部门关系，而不是单部门细节。

## 10. 演进方向

### Phase 1

先完成页面定义与最小数据映射：

- 六部门状态总览；
- 董事会议题区；
- 待审批区；
- 已自主处理事项区。

### Phase 2

再接入：

- 跨部门问题识别；
- 自动议案生成；
- L2 会签流程；
- 审批回写与复盘。

### Phase 3

最终接入：

- 更强的 Agent 自主治理；
- 更高层次的组织优化建议；
- 更自动化的人机协同审批。

## 11. 一句话结论

董事会总览台的本质不是“看六个部门状态”，而是：

> 把六位部长 Agent 的监督、协同、议案和升级路径收敛到一个可管理、可审批、可审计的公司管理大脑页面。
