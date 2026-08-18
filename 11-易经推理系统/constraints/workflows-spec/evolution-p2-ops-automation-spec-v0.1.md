# Evolution P2 Ops Automation Spec v0.1

## 1. 目标

补全 P2 剩余子项，形成运营级自动化闭环：

- 候选优先级评分
- 版本对比看板（JSON）
- 自动回滚执行器（dry-run/apply）
- 周/月治理报表

## 2. 脚本与产物

评分：

- `scripts/ci/evolution_candidate_priority_score.py`
- 输出：`artifacts/evolution/scoring/priority-score-*.json`

版本对比看板：

- `scripts/ci/evolution_version_compare_dashboard.py`
- 输出：`artifacts/evolution/dashboard/version-compare-*.json`

自动回滚执行器：

- `scripts/ci/constraint_rollback.py`
- 输出：`artifacts/evolution/rollback/executions/rollback-execution-*.json`

治理报表：

- `scripts/ci/evolution_governance_report.py`
- 输出：`artifacts/evolution/reports/{week|month}/governance-report-*.json`

## 3. 工作流

- `evolution-decision-gate.yml`
  - 新增：
    - `run_priority_score`
    - `run_version_dashboard`
- `constraint-rollback.yml`
  - 手动触发 rollback pointer 执行
- `evolution-governance-report.yml`
  - 定时 + 手动触发周/月报表
- `memory-candidate-ingest.yml`
  - 候选契约校验与 ingest artifact
- `evolution-validation-gate.yml`
  - 独立验证门禁执行入口
- `constraint-promotion.yml`
  - release snapshot 产物入口
- `post-promotion-watch.yml`
  - 发布后看板与治理报表聚合
- `evolution-default-smoke.yml`
  - 默认绿路 smoke 校验

## 4. 核心指标

评分结果：

- `priority_score`（0-100）
- `priority_tier`（`P0/P1/P2/P3`）

治理报告摘要：

- `total_decisions / approve_count / reject_count`
- `approval_reject_count`
- `rollback_execution_count / rollback_applied_count`
- `avg_rto_seconds`

## 5. Fail-Closed 约束

- `constraint_rollback.py` 在 `apply` 模式未显式 `--allow-apply` 时必须失败。
- `restore_ref` 缺失或不存在时必须失败。
- 任一失败必须写出 `reason_codes` 并返回非 0。

## 6. Release Baseline

- `constraints/releases/*.json` 作为 rollback `restore_ref` 的基础快照。
- 新增 `scripts/ci/constraint_release_snapshot.py` 用于生成新版本 release snapshot。
