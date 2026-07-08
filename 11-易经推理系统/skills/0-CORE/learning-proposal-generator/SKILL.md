---
name: learning-proposal-generator
description: 将反思与蒸馏结果转为可治理的变更提案（proposal），只产出提案不自动应用，必须携带 rollback_plan_id 与 evidence_refs。
license: Internal
---

# Learning Proposal Generator

## 目标

- 把“想法/反思”变成可审核、可验证、可回滚的提案
- 将变更收敛为少数类型：policy_patch / config_update / scoring_spec_update

## 何时使用

- Step 6 盘后进化（尤其止损后）
- 定时优化（例如每日一次参数寻优后的落盘）

## 输入（建议字段）

- `analysis`
  - `pattern`
  - `root_causes[]`
  - `recommendations[]`
- `artifacts`
  - `episode_path`
  - `evidence_refs[]`
  - `lessons_delta`（可选）
- `proposal_policy`
  - `allowed_types[]`
  - `require_shadow_verification`: `true|false`

## 输出

- `proposal`
  - `type`: `policy_patch|config_update|scoring_spec_update`
  - `target_file`
  - `patch_content` 或 `updates`
  - `reason`
  - `reason_codes[]`
  - `rollback_plan_id`
  - `evidence_refs[]`
- `proposal_path`

## 过程

1. 将反思归类到允许的提案类型
2. 生成最小变更（避免一次提案包含多个独立改动）
3. 生成 rollback_plan_id，并绑定 evidence_refs
4. 落盘到 mailbox/proposals（由上层执行落盘）

## 验证

- 每个提案必须包含 `rollback_plan_id` 与 `evidence_refs`
- 任何涉及交易风险参数的提案必须标记为 require_shadow_verification

## Contract v0.1（最小审计契约）
- 输入建议包含：`trace_id`、`ts`、`inst_id`（与 episode 对齐）
- 输出必须包含：`proposal.rollback_plan_id`、`proposal.evidence_refs[]`、`proposal.reason_codes[]`

## Integration
- 上游：`learning-lesson-distiller`（lessons_delta，可选）+ `dream-posttrade-mrm-audit`（归因与建议）+ `learning-episode-writer`（episode_path）
- 下游：`hermes-shadow-verification-gate`（影子验证）、`hermes-rollback-actuator`（回滚计划落地）
- 约定：本技能输出为“发布层正式提案”，可进入 shadow verification；仍不自动应用

## Fail-Closed
- 缺少 evidence_refs 或 rollback_plan_id：不得生成可发布提案
