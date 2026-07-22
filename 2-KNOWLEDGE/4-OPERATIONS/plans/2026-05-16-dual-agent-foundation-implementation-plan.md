# Dual-Agent Collaboration Foundation Implementation Plan

> 注意：本文件为历史计划文档。当前协作主干以 `AGENT协作工具/docs/` 为准；默认工作区以 `7-ARTIFACT-HUB-V2/**` 为准；分支策略以 `agent/*` 独立 PR 为准。

主入口：

- `AGENT协作工具/docs/README.md`
- `AGENT协作工具/docs/agent-efficient-collaboration-mode.md`
- `AGENT协作工具/docs/agent-ledger-protocol-vs-governance-short-spec.md`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `7-ARTIFACT-HUB-V2` 建立可落地的双代理协作底座，产出可直接复用的 checklist、任务卡模板、最小协作契约包、首批任务板与里程碑分支。

**Architecture:** 先把协作机制实现为文档化、可验证的运行资产，再基于这些资产启动双代理并行开发。SOLO 主责规则、契约与集成边界；Claude Code 后续基于冻结契约推进页面壳与交互层，双方通过 `milestone/*` 分支收口。

**Tech Stack:** Markdown, JSON, Git branches, GitHub PR workflow, existing `docs/superpowers/{specs,plans}` layout.

---

## Execution Protocol

Before any task work begins, the assigned agent must:

1. Run `AGENT协作工具/SKILLS/dual-agent-conflict-gate/conflict_gate.py`
2. If the result is `SAFE` or `WARNING`, post a `STARTED` PR comment before editing files
3. If scope changes, post an `UPDATED` comment
4. If the task is blocked, post a `BLOCKED` comment
5. After commit/push, post a `DONE` comment with commit SHA

Required status tags:

- `STARTED`
- `UPDATED`
- `BLOCKED`
- `DONE`

This protocol is mandatory for both SOLO and Claude Code whenever they touch shared contracts, shared docs, shared entry files, or milestone-scoped work.

---

## Repository Layout Changes

**Create**
- `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/checklists/2026-05-16-m1-dual-agent-foundation-checklist.md`
- `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/templates/agent-task-card.md`
- `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/README.md`
- `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/health-summary.v1.json`
- `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/trace-summary.v1.json`
- `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/route-decision-summary.v1.json`
- `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/workflow-summary.v1.json`
- `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/plans/2026-05-16-m1-dual-agent-foundation-task-board.md`

**Modify**
- `docs/superpowers/specs/2026-05-16-dual-agent-collaboration-foundation-design.md`

---

### Task 1: Create the M1 milestone checklist

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/checklists/2026-05-16-m1-dual-agent-foundation-checklist.md`

- [ ] **Step 1: Create the checklist document**

```md
# M1 Dual-Agent Foundation Checklist

**Milestone:** `M1 dual-agent-collaboration-foundation`

**Purpose:** 用 checklist 跟踪双代理协作底座是否已具备启动条件。

## K1 协作底座已写完
- [ ] 协作 spec 已存在
- [ ] 实施计划已存在
- [ ] 用户确认协作模式为“双代理分域自治”

## K2 最小契约已冻结
- [ ] `health-summary.v1.json` 已创建
- [ ] `trace-summary.v1.json` 已创建
- [ ] `route-decision-summary.v1.json` 已创建
- [ ] `workflow-summary.v1.json` 已创建
- [ ] 契约状态达到 `L1 协作接口`

## K3 双代理已完成第一次并行且无覆盖冲突
- [ ] SOLO 首批任务已明确
- [ ] Claude Code 首批任务已明确
- [ ] 共享文件占用规则已写入任务板
- [ ] 至少完成一次 mock 联调准备

## K4 第一个功能里程碑准备启动
- [ ] 已建立 `milestone/dual-agent-foundation`
- [ ] 已确定下一功能优先级
- [ ] 已确认是否进入 `ops-ui` / `/feed` / `/chain`
```

- [ ] **Step 2: Verify the checklist has all K1-K4 sections**

Run:

```bash
grep -n "^## K[1-4]" /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/checklists/2026-05-16-m1-dual-agent-foundation-checklist.md
```

Expected:

```text
## K1 协作底座已写完
## K2 最小契约已冻结
## K3 双代理已完成第一次并行且无覆盖冲突
## K4 第一个功能里程碑准备启动
```

- [ ] **Step 3: Commit the checklist**

```bash
git add docs/superpowers/checklists/2026-05-16-m1-dual-agent-foundation-checklist.md
git commit -m "docs(collaboration): add M1 foundation checklist"
```

---

### Task 2: Create the reusable agent task card template

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/templates/agent-task-card.md`

- [ ] **Step 1: Create the task card template**

```md
# Agent Task Card Template

## Basic Info
- Task Name:
- Owner:
- Milestone:
- Priority:

## Goal
- What this task must achieve:

## Input Dependencies
- Required files:
- Required contracts:
- Required branches:

## Output Artifacts
- Files to create:
- Files to modify:
- Evidence to attach:

## Protected Boundaries
- Files not to modify:
- Contracts not to change:
- Shared files requiring approval:

## Definition of Done
- [ ] Local change complete
- [ ] Contract still matches
- [ ] No shared-file conflict introduced
- [ ] Ready for milestone merge
```

- [ ] **Step 2: Verify the template contains all required sections**

Run:

```bash
grep -n "^## " /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/templates/agent-task-card.md
```

Expected:

```text
## Basic Info
## Goal
## Input Dependencies
## Output Artifacts
## Protected Boundaries
## Definition of Done
```

- [ ] **Step 3: Commit the template**

```bash
git add docs/superpowers/templates/agent-task-card.md
git commit -m "docs(collaboration): add agent task card template"
```

---

### Task 3: Create the minimal collaboration contract pack

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/README.md`
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/health-summary.v1.json`
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/trace-summary.v1.json`
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/route-decision-summary.v1.json`
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/workflow-summary.v1.json`

- [ ] **Step 1: Create the contract pack README**

```md
# 7-ARTIFACT-HUB-V2 Foundation Contracts

**Status:** `L1 协作接口`

**Purpose:** 为双代理第一轮并行开发提供最小冻结读接口样例。

## Included Contracts
- `health-summary.v1.json`
- `trace-summary.v1.json`
- `route-decision-summary.v1.json`
- `workflow-summary.v1.json`

## Rules
- 当前只冻结最小读接口 shape
- 未写入本目录的字段，不默认开放给页面依赖
- 若需改动字段，先更新 spec 与任务板，再修改样例
```

- [ ] **Step 2: Create `health-summary.v1.json`**

```json
{
  "service": "artifact-hub-v2",
  "status": "ok",
  "timestamp": "2026-05-16T00:00:00Z",
  "dependencies": {
    "artifact_hub": "ok",
    "gateway": "unknown",
    "meta_db": "ok"
  }
}
```

- [ ] **Step 3: Create `trace-summary.v1.json`**

```json
{
  "trace_id": "trace_demo_001",
  "status": "completed",
  "workflow_id": "wf_demo_001",
  "workflow_type": "legacy_chain",
  "department": "governance",
  "started_at": "2026-05-16T00:00:00Z",
  "finished_at": "2026-05-16T00:02:30Z"
}
```

- [ ] **Step 4: Create `route-decision-summary.v1.json`**

```json
{
  "trace_id": "trace_demo_001",
  "decision_id": "decision_demo_001",
  "selected_route": "RUN_CHAIN",
  "decision_level": "L1",
  "policy_version": "v1",
  "reason": "mock decision for collaboration foundation"
}
```

- [ ] **Step 5: Create `workflow-summary.v1.json`**

```json
{
  "workflow_id": "wf_demo_001",
  "workflow_type": "legacy_chain",
  "chain_phase": "A3",
  "status": "running",
  "latest_trace_id": "trace_demo_001"
}
```

- [ ] **Step 6: Validate all JSON files**

Run:

```bash
python -m json.tool /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/health-summary.v1.json >/dev/null
python -m json.tool /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/trace-summary.v1.json >/dev/null
python -m json.tool /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/route-decision-summary.v1.json >/dev/null
python -m json.tool /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/contracts/7-artifact-hub-v2-foundation/workflow-summary.v1.json >/dev/null
```

Expected: no output and exit code `0`.

- [ ] **Step 7: Commit the contract pack**

```bash
git add docs/superpowers/contracts/7-artifact-hub-v2-foundation
git commit -m "docs(collaboration): add foundation contract pack"
```

---

### Task 4: Create the M1 task board with first-batch assignments

**Files:**
- Create: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/plans/2026-05-16-m1-dual-agent-foundation-task-board.md`

- [ ] **Step 1: Create the task board**

```md
# M1 Dual-Agent Foundation Task Board

## Milestone
- `M1 dual-agent-collaboration-foundation`

## SOLO First Batch
- `A1` 固化 checklist、模板、contracts 目录
- `A2` 冻结 `health-summary.v1.json`
- `A3` 冻结 `trace-summary.v1.json`
- `A4` 冻结 `route-decision-summary.v1.json`
- `A5` 冻结 `workflow-summary.v1.json`
- `A6` 建立里程碑分支并准备收口

## Claude Code First Batch
- `C1` 按冻结 contracts 设计页面数据 adapter 结构
- `C2` 先用 mock data 准备 `ops-ui` 页面壳模式
- `C3` 准备 trace / health / workflow 三类卡片的数据消费边界
- `C4` 不改共享 contracts，只围绕页面层推进

## Shared Freeze Items
- `health-summary.v1.json`
- `trace-summary.v1.json`
- `route-decision-summary.v1.json`
- `workflow-summary.v1.json`
- 顶层 `README`
- 顶层 spec 索引

## Do Not Touch Without Re-Assignment
- `7-ARTIFACT-HUB-V2/src/**`（SOLO 主责，`7-ARTIFACT-HUB-V2/src/ops-ui/**` 页面层目录除外）
- `7-ARTIFACT-HUB-V2/src/ops-ui/**`（Claude Code 主责，用于 C1/C2/C3 页面层任务）
- `dreambuddy/meta/**`
- `dreambuddy/config/**`

## Exit Criteria
- SOLO 与 Claude Code 的首批任务均已明确
- 共享冻结项已列出
- `milestone/dual-agent-foundation` 已建立并可收口
- 下一里程碑进入 `ops-ui` 骨架阶段，Claude Code 可在 `7-ARTIFACT-HUB-V2/src/ops-ui/**` 内推进页面层任务
```

- [ ] **Step 2: Verify the board includes SOLO and Claude Code sections**

Run:

```bash
grep -n "^## SOLO First Batch\\|^## Claude Code First Batch\\|^## Shared Freeze Items" /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/plans/2026-05-16-m1-dual-agent-foundation-task-board.md
```

Expected:

```text
## SOLO First Batch
## Claude Code First Batch
## Shared Freeze Items
```

- [ ] **Step 3: Commit the task board**

```bash
git add docs/superpowers/plans/2026-05-16-m1-dual-agent-foundation-task-board.md
git commit -m "docs(collaboration): add M1 task board"
```

---

### Task 5: Link the implementation artifacts back to the design spec

**Files:**
- Modify: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/specs/2026-05-16-dual-agent-collaboration-foundation-design.md`

- [ ] **Step 1: Add an implementation artifacts section near the end of the spec**

```md
## 16. 实施产物索引

当前协作底座的实施产物包括：

- `docs/superpowers/plans/2026-05-16-dual-agent-foundation-implementation-plan.md`
- `docs/superpowers/checklists/2026-05-16-m1-dual-agent-foundation-checklist.md`
- `docs/superpowers/plans/2026-05-16-m1-dual-agent-foundation-task-board.md`
- `docs/superpowers/contracts/7-artifact-hub-v2-foundation/`
```

- [ ] **Step 2: Verify the spec now references the implementation artifacts**

Run:

```bash
grep -n "实施产物索引" /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/specs/2026-05-16-dual-agent-collaboration-foundation-design.md
```

Expected: one match containing `## 16. 实施产物索引`.

- [ ] **Step 3: Commit the spec update**

```bash
git add docs/superpowers/specs/2026-05-16-dual-agent-collaboration-foundation-design.md
git commit -m "docs(collaboration): link foundation implementation artifacts"
```

---

### Task 6: Create and publish the milestone branch

**Files:**
- Modify: None

- [ ] **Step 1: Create the milestone branch**

Run:

```bash
git checkout -b milestone/dual-agent-foundation
```

Expected: switched to new branch `milestone/dual-agent-foundation`.

- [ ] **Step 2: Push the milestone branch**

Run:

```bash
git push -u origin milestone/dual-agent-foundation
```

Expected: upstream is set for `milestone/dual-agent-foundation`.

- [ ] **Step 3: Record the active milestone branch in the task board**

Add the following line under `## Milestone` in `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/docs/superpowers/plans/2026-05-16-m1-dual-agent-foundation-task-board.md`:

```md
- Active branch: `milestone/dual-agent-foundation`
```

- [ ] **Step 4: Commit the branch note**

```bash
git add docs/superpowers/plans/2026-05-16-m1-dual-agent-foundation-task-board.md
git commit -m "docs(collaboration): record active milestone branch"
```

---

## First Batch Assignment Summary

### SOLO
- 建立 checklist、模板、contracts 目录与 task board
- 冻结 `health` / `trace` / `route decision` / `workflow` 四个最小协作接口
- 建立并维护 `milestone/dual-agent-foundation`
- 收口共享文件与共享契约

### Claude Code
- 基于冻结 contracts 设计页面 adapter
- 用 mock 数据先起 `ops-ui` 页面壳
- 保持在页面层与交互层推进
- 不直接修改共享 contracts 与后端主责文件

### User
- 只在 `K1-K4` 四个关键里程碑介入
- 不参与日常裁决
- 在是否进入下一功能里程碑时拍板

## PR Comment Templates

### STARTED

```md
[协作开工声明 / STARTED]

Agent: SOLO | Claude Code
任务: <任务名称>
分支: <agent/* 分支>
计划修改:
- <文件或目录 1>
- <文件或目录 2>

预期产出:
- <产出 1>
- <产出 2>

占用范围:
- <当前请勿并行修改的文件或目录>

冲突门禁结果:
- decision: SAFE | WARNING
- reason_codes: <如无可写 []>

状态: STARTED
说明: 在我发 DONE 评论前，请不要并行修改上述范围。
```

### UPDATED

```md
[协作状态更新 / UPDATED]

Agent: <SOLO | Claude Code>
任务: <任务名称>
变更说明:
- <新增范围或缩减范围>
当前占用范围:
- <更新后的文件或目录>
状态: UPDATED
```

### BLOCKED

```md
[协作阻塞通知 / BLOCKED]

Agent: <SOLO | Claude Code>
任务: <任务名称>
阻塞原因:
- <门禁 BLOCK 或中途发现的冲突>
需要对方配合:
- <需要谁先完成什么>
状态: BLOCKED
```

### DONE

```md
[协作完成回报 / DONE]

Agent: <SOLO | Claude Code>
任务: <任务名称>
提交: <commit sha>
已完成:
- <完成项 1>
- <完成项 2>
状态: DONE
说明: 另一代理可以基于最新 PR head 继续。
```
