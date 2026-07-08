# Evolution P1 Acceptance Report (2026-05-12)

## 1. 验收范围

本次执行 P1 多门禁聚合验收，覆盖：

- `required_stages` 扩展为 `audit,sandbox,stress,scenario,backtest`
- `stage_policy` 阶段级策略（含 `allow_warnings`）
- 多门禁聚合判定与 fail-closed 阻断路径

## 2. 验收输入

### 正样本（策略放宽）

- Candidate：`artifacts/evolution/feedback/candidate_positive_20260511.json`
- Reports：
  - `artifacts/evolution/audit/audit_positive_20260511.json`
  - `artifacts/evolution/sandbox/sandbox_positive_20260511.json`
  - `artifacts/evolution/stress/stress_positive_20260512.json`
  - `artifacts/evolution/scenario/scenario_positive_20260512.json`
  - `artifacts/evolution/backtest/backtest_positive_20260512.json`
- Stage policy：
  - `artifacts/evolution/policy/stage_policy_p1_relaxed_scenario.json`

### 反样本（默认严格策略）

- Candidate：`artifacts/evolution/feedback/candidate_positive_20260511.json`
- Reports：
  - `artifacts/evolution/audit/audit_positive_20260511.json`
  - `artifacts/evolution/sandbox/sandbox_positive_20260511.json`
  - `artifacts/evolution/stress/stress_positive_20260512.json`
  - `artifacts/evolution/scenario/scenario_positive_20260512.json`
  - `artifacts/evolution/backtest/backtest_negative_20260512.json`

## 3. 验收结果

### 正样本（通过）

- Decision：`artifacts/evolution/decision/decision-20260512T103000Z.json`
  - `decision=approve`
  - `required_stages` 为五门禁
  - `stage_policy_snapshot.scenario.allow_warnings=true`
- Promotion：`artifacts/evolution/decision/promotion-20260512T103000Z.json`
- Rollback Pointer：`artifacts/evolution/rollback/rollback-pointer-20260512T103000Z.json`

### 反样本（阻断）

- Decision：`artifacts/evolution/decision/decision-20260512T103500Z.json`
  - `decision=reject`
  - `reason_codes` 包含：
    - `REPORT_VIOLATION_COUNT_EXCEEDED`
    - `REPORT_VIOLATION_FOUND`
    - `REPORT_SEVERITY_BLOCKED`
- 未生成 Promotion 与 Rollback Pointer

## 4. 结论（Go/No-Go）

结论：`GO (P1 多门禁 + stage_policy 聚合判定通过)`

说明：

- 阶段级策略已可通过 JSON 外置配置；
- 默认仍为严格 fail-closed；
- 下一步可进入 P1.5：引入阶段权重和策略模板版本化。
