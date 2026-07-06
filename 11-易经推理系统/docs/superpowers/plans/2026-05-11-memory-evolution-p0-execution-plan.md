# Memory-Evolution-Constraint P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 `memory -> evolution -> constraints` 最小闭环的 P0 可执行骨架（文档与流程基线），可直接进入后续代码实施。  
**Architecture:** 以“候选契约 + 验证报告契约 + 状态机 + 门禁矩阵 + 回滚指针”作为 P0 交付核心，先固化约束层规范，再将其映射到 GitHub 工作流执行路径。  
**Tech Stack:** Markdown 规范文档、GitHub PR Gate、pytest（门禁回归）

---

## 文件结构与职责

- `constraints/workflows-spec/evolution-p0-scope-freeze-2026-05-11.md`：P0 范围冻结与不做项。
- `constraints/workflows-spec/evolution-p0-contracts-v0.1.md`：Candidate/ValidationReport/PromotionRecord 契约。
- `constraints/workflows-spec/evolution-p0-state-machine-errors.md`：状态机与错误码字典。
- `constraints/workflows-spec/evolution-p0-acceptance-checklist.md`：P0 DoD 与验收表。
- `constraints/workflows-spec/evolution.md`：进化工程规范主文档（引用 P0 配套文档）。
- `constraints/workflows-spec/README.md`：索引更新。

### Task 1: 冻结 P0 范围

**Files:**
- Create: `constraints/workflows-spec/evolution-p0-scope-freeze-2026-05-11.md`

- [ ] **Step 1: 新建范围冻结文档**

```md
# Evolution P0 Scope Freeze (2026-05-11)

## In Scope
- candidate ingest
- audit gate
- sandbox gate
- decision gate
- rollback pointer

## Out of Scope
- stress gate
- scenario gate
- backtest gate
- auto rollback executor
- UI dashboard
```

- [ ] **Step 2: 验证文档可读与范围清晰**

Run: `test -f constraints/workflows-spec/evolution-p0-scope-freeze-2026-05-11.md && echo ok`  
Expected: 输出 `ok`。

- [ ] **Step 3: 提交**

```bash
git add constraints/workflows-spec/evolution-p0-scope-freeze-2026-05-11.md
git commit -m "docs(evolution): add P0 scope freeze"
```

### Task 2: 固化 P0 契约

**Files:**
- Create: `constraints/workflows-spec/evolution-p0-contracts-v0.1.md`

- [ ] **Step 1: 写契约文档**

```md
# Evolution P0 Contracts v0.1

## Candidate
- candidate_id
- trace_id
- constraint_version_base
- source_type
- source_refs[]
- hypothesis
- expected_effect
- risk_assessment
- evidence_refs[]
- schema_version

## ValidationReport
- candidate_id
- stage
- pass
- metrics
- violations[]
- artifacts[]
- timestamp

## PromotionRecord
- candidate_id
- from_version
- to_version
- decision
- rollback_pointer
- evidence_refs[]
- timestamp
```

- [ ] **Step 2: 验证字段与通信契约一致**

Run: `grep -n "trace_id\\|evidence_refs\\|schema_version" constraints/workflows-spec/evolution-p0-contracts-v0.1.md`  
Expected: 三项均命中。

- [ ] **Step 3: 提交**

```bash
git add constraints/workflows-spec/evolution-p0-contracts-v0.1.md
git commit -m "docs(evolution): define P0 contracts v0.1"
```

### Task 3: 状态机与错误码

**Files:**
- Create: `constraints/workflows-spec/evolution-p0-state-machine-errors.md`

- [ ] **Step 1: 写状态机与错误码文档**

```md
# Evolution P0 State Machine and Error Codes

## States
- C0_COLLECTED
- C1_AUDIT_PASSED
- C2_SANDBOX_PASSED
- C6_APPROVED
- C7_PROMOTED
- C_FAIL

## Error Codes
- CANDIDATE_INVALID
- AUDIT_FAILED
- SANDBOX_REGRESSION
- PROMOTION_BLOCKED
```

- [ ] **Step 2: 验证状态流可执行**

Run: `grep -n "C0_COLLECTED\\|C1_AUDIT_PASSED\\|C2_SANDBOX_PASSED\\|C6_APPROVED\\|C7_PROMOTED\\|C_FAIL" constraints/workflows-spec/evolution-p0-state-machine-errors.md`  
Expected: 所有状态都存在。

- [ ] **Step 3: 提交**

```bash
git add constraints/workflows-spec/evolution-p0-state-machine-errors.md
git commit -m "docs(evolution): add P0 state machine and error codes"
```

### Task 4: 验收清单与主规范索引

**Files:**
- Create: `constraints/workflows-spec/evolution-p0-acceptance-checklist.md`
- Modify: `constraints/workflows-spec/evolution.md`
- Modify: `constraints/workflows-spec/README.md`

- [ ] **Step 1: 写 P0 验收清单**

```md
# Evolution P0 Acceptance Checklist

- [ ] candidate ingest 可入队
- [ ] audit gate 可阻断失败候选
- [ ] sandbox gate 可阻断回归候选
- [ ] decision gate 仅全绿候选可批准
- [ ] rollback pointer 生成并可执行
- [ ] artifacts 全量可追溯
```

- [ ] **Step 2: 在 evolution.md 引用 4 份 P0 配套文档**

```md
## P0 执行文档
- evolution-p0-scope-freeze-2026-05-11.md
- evolution-p0-contracts-v0.1.md
- evolution-p0-state-machine-errors.md
- evolution-p0-acceptance-checklist.md
```

- [ ] **Step 3: 更新 workflows-spec README 索引**

```md
- `evolution-p0-scope-freeze-2026-05-11.md`：P0 范围冻结
- `evolution-p0-contracts-v0.1.md`：P0 契约定义
- `evolution-p0-state-machine-errors.md`：P0 状态机与错误码
- `evolution-p0-acceptance-checklist.md`：P0 验收清单
```

- [ ] **Step 4: 运行门禁回归**

Run: `pytest tests/test_ci_architecture_sync_guard.py tests/test_ci_safe_main_merge_gate.py -q`  
Expected: 全绿通过。

- [ ] **Step 5: 提交**

```bash
git add constraints/workflows-spec/evolution-p0-acceptance-checklist.md \
  constraints/workflows-spec/evolution.md \
  constraints/workflows-spec/README.md
git commit -m "docs(evolution): add P0 execution checklist and spec index links"
```

### Task 5: PR 与合并

**Files:**
- Modify: `constraints/workflows-spec/*`（前述文档）

- [ ] **Step 1: 推送分支**

Run: `git push -u origin feature/p0-closed-loop-execution-kit`  
Expected: 远端分支创建成功。

- [ ] **Step 2: 创建 PR**

Run:

```bash
gh pr create --base main --head feature/p0-closed-loop-execution-kit \
  --title "docs(evolution): add executable P0 closed-loop kit" \
  --body "Add P0 execution kit docs for memory-evolution-constraint closed loop."
```

Expected: 返回 PR URL。

- [ ] **Step 3: 等待 CI 并合并**

Run: `gh pr checks --watch`  
Expected: `PR Gate Checks` 通过。

Run: `gh pr merge --squash --delete-branch`  
Expected: 合并成功。

- [ ] **Step 4: 合并后验证**

Run:

```bash
git checkout main
git fetch origin
git rev-list --left-right --count main...origin/main
```

Expected: `0 0`。

## 自检清单（已完成）

- Spec 覆盖：P0 范围、契约、状态机、验收、索引同步均包含。  
- 占位符扫描：无 `TODO/TBD`。  
- 一致性检查：字段命名与现有 `communication-contract-v0.1.md` 对齐。
