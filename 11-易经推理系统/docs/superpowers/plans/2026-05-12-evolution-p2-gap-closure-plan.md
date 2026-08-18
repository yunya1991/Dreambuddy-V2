# Evolution P2 Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 P2 剩余工程缺口：月报调度、release 基线快照、workflow 拆分对齐、默认 smoke 验证。

**Architecture:** 通过新增轻量 workflow 与 release snapshot 脚本补足编排层能力，保持现有 Decision Gate 为核心执行器。修复报表 workflow 的 period 路由，保证周/月定时触发与手动触发行为一致。

**Tech Stack:** Python 3.11, GitHub Actions, pytest, JSON artifacts

---

### Task 1: 补月报调度路由

**Files:**
- Modify: `.github/workflows/evolution-governance-report.yml`

- [ ] **Step 1: 让 schedule 事件根据 cron 自动推断 week/month**
- [ ] **Step 2: 保持 workflow_dispatch 输入优先级高于 cron 推断**

### Task 2: 建立 release 基线与快照脚本

**Files:**
- Create: `scripts/ci/constraint_release_snapshot.py`
- Create: `tests/test_ci_constraint_release_snapshot.py`
- Create: `constraints/releases/v0.1.json`
- Create: `constraints/releases/v0.1.1.json`
- Create: `constraints/releases/v0.1.2.json`

- [ ] **Step 1: 先写测试（输入 source json -> 输出 release snapshot）**
- [ ] **Step 2: 实现脚本并通过测试**
- [ ] **Step 3: 补齐已有版本基线文件**

### Task 3: workflow 拆分对齐

**Files:**
- Create: `.github/workflows/memory-candidate-ingest.yml`
- Create: `.github/workflows/evolution-validation-gate.yml`
- Create: `.github/workflows/constraint-promotion.yml`
- Create: `.github/workflows/post-promotion-watch.yml`

- [ ] **Step 1: 新增 ingest workflow（候选契约校验+落盘 artifact）**
- [ ] **Step 2: 新增 validation workflow（调用 decision gate）**
- [ ] **Step 3: 新增 promotion workflow（生成 release snapshot artifact）**
- [ ] **Step 4: 新增 post-promotion-watch workflow（看板+治理报表）**

### Task 4: 默认 smoke 验证与规范同步

**Files:**
- Create: `.github/workflows/evolution-default-smoke.yml`
- Modify: `constraints/workflows-spec/evolution.md`
- Modify: `constraints/workflows-spec/README.md`
- Modify: `constraints/workflows-spec/evolution-p2-ops-automation-spec-v0.1.md`
- Modify: `.github/workflows/safe-main-merge-gate.yml`

- [ ] **Step 1: 新增默认绿路 smoke workflow**
- [ ] **Step 2: 新增 smoke + release snapshot 测试到主门禁**
- [ ] **Step 3: 同步规范与索引**
