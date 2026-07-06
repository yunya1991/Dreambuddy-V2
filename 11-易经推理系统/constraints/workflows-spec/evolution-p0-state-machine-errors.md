# Evolution P0 State Machine and Error Codes

## 1. State Machine

### Normal Path

- `C0_COLLECTED`：Candidate 入队完成
- `C1_AUDIT_PASSED`：Audit Gate 通过
- `C2_SANDBOX_PASSED`：Sandbox Gate 通过
- `C6_APPROVED`：Decision Gate 审批通过
- `C7_PROMOTED`：约束升级 PR 合并完成

### Failure Path

- `C_FAIL`：任一步失败，必须阻断自动发布

## 2. Transition Rules

- `C0_COLLECTED -> C1_AUDIT_PASSED`：字段、来源、证据链检查通过
- `C1_AUDIT_PASSED -> C2_SANDBOX_PASSED`：沙箱回放无回归
- `C2_SANDBOX_PASSED -> C6_APPROVED`：Decision 规则满足全绿条件
- `C6_APPROVED -> C7_PROMOTED`：存在 rollback pointer 且发布门禁通过

失败转移：

- 任一状态失败 -> `C_FAIL`
- `C_FAIL` 后仅允许人工复核重试，不允许自动跳步

## 3. Error Codes

- `CANDIDATE_INVALID`：候选契约不完整或字段非法
- `AUDIT_FAILED`：审计检查失败
- `SANDBOX_REGRESSION`：沙箱回放检测到风险回归
- `PROMOTION_BLOCKED`：发布前置条件不满足

## 4. Error Handling Policy

- 出错后写入 `ValidationReport.violations[]`
- 同步写审计 artifact 到 `artifacts/evolution/*`
- 报告中必须包含 `candidate_id`、`trace_id`、`reason_code`
