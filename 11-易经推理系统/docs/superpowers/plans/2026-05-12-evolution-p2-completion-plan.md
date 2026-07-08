# Evolution P2 Completion Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全 P2 未完成子项：候选评分、版本对比看板、自动回滚执行器、周期治理报表，并形成可实跑闭环。

**Architecture:** 使用独立 CI 脚本实现四个能力点，脚本产物统一落到 `artifacts/evolution/*`，通过 GitHub Actions 提供手动和定时触发入口。沿用现有 `decision/promotion/rollback` artifact 作为输入，确保 fail-closed 与可追溯。

**Tech Stack:** Python 3.11, pytest, GitHub Actions, JSON artifacts

---

### Task 1: PR1-候选评分与版本对比看板

**Files:**
- Create: `scripts/ci/evolution_candidate_priority_score.py`
- Create: `scripts/ci/evolution_version_compare_dashboard.py`
- Create: `tests/test_ci_evolution_candidate_priority_score.py`
- Create: `tests/test_ci_evolution_version_compare_dashboard.py`
- Modify: `.github/workflows/evolution-decision-gate.yml`

- [ ] **Step 1: 先写两组失败测试（评分脚本+看板脚本）**
- [ ] **Step 2: 实现最小脚本逻辑并通过测试**
- [ ] **Step 3: 接入 workflow 可选开关运行并上传产物**
- [ ] **Step 4: 运行 `pytest tests/test_ci_evolution_candidate_priority_score.py tests/test_ci_evolution_version_compare_dashboard.py -q`**

### Task 2: PR2-自动回滚执行器与周期报表

**Files:**
- Create: `scripts/ci/constraint_rollback.py`
- Create: `scripts/ci/evolution_governance_report.py`
- Create: `tests/test_ci_constraint_rollback.py`
- Create: `tests/test_ci_evolution_governance_report.py`
- Create: `.github/workflows/constraint-rollback.yml`
- Create: `.github/workflows/evolution-governance-report.yml`

- [ ] **Step 1: 先写失败测试（dry-run/real-run + 周期汇总）**
- [ ] **Step 2: 实现回滚执行器（默认 dry-run，真实执行需显式参数）**
- [ ] **Step 3: 实现周/月报表聚合（通过率、拒绝原因、回滚次数、RTO）**
- [ ] **Step 4: 接入 workflow（手动触发 + cron）**
- [ ] **Step 5: 运行 `pytest tests/test_ci_constraint_rollback.py tests/test_ci_evolution_governance_report.py -q`**

### Task 3: 规范同步与主门禁覆盖

**Files:**
- Modify: `constraints/workflows-spec/evolution.md`
- Modify: `constraints/workflows-spec/README.md`
- Create: `constraints/workflows-spec/evolution-p2-ops-automation-spec-v0.1.md`
- Modify: `.github/workflows/safe-main-merge-gate.yml`

- [ ] **Step 1: 补充 P2 完整规范与索引**
- [ ] **Step 2: 将新增 4 个测试接入 safe-main-merge-gate**
- [ ] **Step 3: 运行全量相关测试并检查无回归**
- [ ] **Step 4: 手动触发回滚与报表 workflow 各 1 次并记录结果**
