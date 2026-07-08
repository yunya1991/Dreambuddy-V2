# Evolution P2 Approval Gate Spec v0.1

## 1. 目标

在 P1.5 `policy_version` 能力基础上，增加审批票据门禁，形成发布双门禁：

- 技术门禁：`decision_gate=approve`
- 审批门禁：`approval_gate=approve`

任一不满足，必须 fail-closed。

## 2. 审批票据契约

路径建议：

- `artifacts/evolution/approval/approval_ticket_*.json`

字段：

- `ticket_id`：审批票据唯一标识
- `candidate_id`：候选标识，必须与 Candidate 一致
- `trace_id`：链路标识，必须与 Candidate 一致
- `policy_version`：审批针对的策略版本，必须与 Decision Record 一致
- `decision_ref`：关联的 Decision Record 路径（审计用途）
- `approver`：审批主体
- `approved_at`：生效时间（UTC）
- `expires_at`：过期时间（UTC）
- `scope`：作用域，当前定义 `scope.to_versions[]`
- `schema_version`：`evolution-p2-approval-ticket-v0.1`

## 3. 判定规则

审批校验入口：

- `scripts/ci/evolution_decision_gate.py`
  - `--require-approval-ticket`
  - `--approval-ticket-json`
  - `--approval-artifacts-dir`

规则：

1. `require_approval_ticket=true` 且无票据 -> 拒绝
2. `candidate_id / trace_id / policy_version` 任一不一致 -> 拒绝
3. `to_version` 不在 `scope.to_versions` -> 拒绝
4. `approved_at <= now <= expires_at` 不成立 -> 拒绝
5. 票据 JSON 非法或关键时间不可解析 -> 拒绝

## 4. Reason Codes

- `APPROVAL_TICKET_REQUIRED`
- `APPROVAL_TICKET_INVALID`
- `APPROVAL_CANDIDATE_MISMATCH`
- `APPROVAL_TRACE_MISMATCH`
- `APPROVAL_POLICY_VERSION_MISMATCH`
- `APPROVAL_SCOPE_MISMATCH`
- `APPROVAL_NOT_YET_EFFECTIVE`
- `APPROVAL_EXPIRED`

## 5. 产物与行为

Decision Record 增加：

- `approval.required`
- `approval.decision`（`approve/reject/skip`）
- `approval.reason_codes`
- `approval.ticket_id`
- `approval.source`

新增产物：

- `artifacts/evolution/approval/approval-result-*.json`

行为约束：

- 审批拒绝时不得生成 `promotion-*.json` 与 `rollback-pointer-*.json`
- 仅当技术门禁 + 审批门禁均通过，才允许 promotion
