# Architecture Archive Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在继续 `/feed`、`/ops`、`/trace` 等功能开发前，先为 `7-ARTIFACT-HUB-V2` 建立完整的架构归档治理骨架，明确中游定位、上下游边界、单一真相源、文档分类与运行态治理规则。

**Architecture:** 本计划只做“认知架构”和“治理架构”的收口，不先做大规模代码迁移。实现方式是先补齐文档骨架、来源真相源说明、跨系统边界矩阵、运行态资产治理规则和归档账本，再用这些文档反向约束后续 `/feed`、`/chain`、`/ops`、`board` 的实现与提交边界。

**Tech Stack:** Markdown, HTML docs, TypeScript repo structure, git working tree conventions

---

## File Structure

- Create: `docs/architecture/SYSTEM_BOUNDARIES.md`
- Create: `docs/architecture/SOURCE_OF_TRUTH.md`
- Create: `docs/architecture/ARCHIVE_INFORMATION_MODEL.md`
- Create: `docs/integration/UPSTREAM_DOWNSTREAM_MATRIX.md`
- Create: `docs/governance/CHANGE_CLASSIFICATION_POLICY.md`
- Create: `docs/governance/RUNTIME_ASSET_GOVERNANCE.md`
- Create: `docs/recovery/ARCHIVE_LEDGER.md`
- Create: `docs/recovery/EXECUTION_ORDER.md`
- Modify: `docs/README.md`
- Modify: `docs/architecture/README.md`
- Modify: `docs/integration/README.md`
- Modify: `docs/governance/README.md`
- Modify: `docs/recovery/README.md`
- Modify: `README.md`

### Responsibilities

- `SYSTEM_BOUNDARIES.md`: 定义 `3-FRONTEND`、`7-ARTIFACT-HUB-V2`、`6-TRADING`、`dreambuddy/config`、`dreambuddy/artifacts` 的职责边界。
- `SOURCE_OF_TRUTH.md`: 固化 artifacts、meta、config、runtime docs 的单一真相源和禁止扩散规则。
- `ARCHIVE_INFORMATION_MODEL.md`: 定义文档分类法和归档信息模型，回答“什么文档应该放在哪一层”。
- `UPSTREAM_DOWNSTREAM_MATRIX.md`: 把上下游承接关系写成矩阵，回答“谁产出、谁承接、谁消费、谁审计”。
- `CHANGE_CLASSIFICATION_POLICY.md`: 定义未提交改动的分类规则，回答“哪些改动可以一起提交、哪些必须分离”。
- `RUNTIME_ASSET_GOVERNANCE.md`: 定义 `dreambuddy/artifacts`、`dreambuddy/config`、本地 backup 的治理约束。
- `ARCHIVE_LEDGER.md`: 记录“原路径 -> 归档副本路径 -> 当前状态 -> 后续动作”的账本。
- `EXECUTION_ORDER.md`: 固定完整架构归档梳理的执行顺序和停止条件。

### Task 1: Freeze System Boundaries

**Files:**
- Create: `docs/architecture/SYSTEM_BOUNDARIES.md`
- Create: `docs/architecture/SOURCE_OF_TRUTH.md`
- Modify: `docs/architecture/README.md`
- Modify: `README.md`

- [ ] **Step 1: Create the boundary document skeleton**

```md
# System Boundaries

## 1. Scope

This document freezes the role boundaries among:

- `3-FRONTEND`
- `7-ARTIFACT-HUB-V2`
- `6-TRADING`
- `dreambuddy/config`
- `dreambuddy/artifacts`

## 2. Boundary Table

| System | Role | Produces | Consumes | Must Not Own |
|---|---|---|---|---|
| `3-FRONTEND` | Consumer entry | user actions | hub/query results | governance source of truth |
| `7-ARTIFACT-HUB-V2` | Middle governance layer | route/trace/task/result/feed/ops | trading outputs, config, artifacts | end-user heavy UI ownership |
| `6-TRADING` | Upstream production layer | research/trading execution artifacts | market signals, skills | governance UX |
```
```

- [ ] **Step 2: Fill the single-source-of-truth document**

```md
# Source Of Truth

## 1. Repo-Local Truth Sources

- Artifacts root: `../dreambuddy/artifacts`
- Meta root: `../dreambuddy/meta`
- Config root: `../dreambuddy/config`

## 2. Rules

- New runtime artifacts must converge into repo-local roots.
- New docs must not redefine source-of-truth paths ad hoc.
- `~/.workbuddy` is compatibility context, not the long-term primary source.
```
```

- [ ] **Step 3: Update architecture entry points**

```md
## Primary Boundary Docs

- [SYSTEM_BOUNDARIES.md](./SYSTEM_BOUNDARIES.md)
- [SOURCE_OF_TRUTH.md](./SOURCE_OF_TRUTH.md)
```
```

- [ ] **Step 4: Update root README references**

```md
详细治理与归档边界见：

- [架构边界](./docs/architecture/SYSTEM_BOUNDARIES.md)
- [单一真相源](./docs/architecture/SOURCE_OF_TRUTH.md)
```
```

- [ ] **Step 5: Verify references**

Run: `python3 - <<'PY'\nfrom pathlib import Path\nroot = Path('/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2')\nfor rel in [\n 'docs/architecture/SYSTEM_BOUNDARIES.md',\n 'docs/architecture/SOURCE_OF_TRUTH.md',\n 'docs/architecture/README.md',\n 'README.md',\n]:\n    p = root / rel\n    assert p.exists(), rel\nprint('ok')\nPY`
Expected: prints `ok`

### Task 2: Freeze Archive Information Model

**Files:**
- Create: `docs/architecture/ARCHIVE_INFORMATION_MODEL.md`
- Modify: `docs/README.md`
- Modify: `docs/architecture/README.md`

- [ ] **Step 1: Create the archive information model document**

```md
# Archive Information Model

## 1. Document Classes

| Class | Directory | Examples |
|---|---|---|
| Architecture | `docs/architecture/` | system map, boundaries, diagrams |
| Integration | `docs/integration/` | frontend-hub-trading linkage |
| Governance | `docs/governance/` | policy, console, board, market console |
| Recovery | `docs/recovery/` | migration, recovery, archive ledger |
| Execution Plans | `docs/superpowers/plans/` | step-by-step implementation plans |

## 2. Placement Rules

- A doc describing runtime ownership goes to `architecture/`.
- A doc describing system coupling goes to `integration/`.
- A doc describing control, audit, approval, policy goes to `governance/`.
- A doc describing migration, restore, rollback, archive execution goes to `recovery/`.
```
```

- [ ] **Step 2: Add the model to docs indexes**

```md
## Core Model

- [ARCHIVE_INFORMATION_MODEL.md](./ARCHIVE_INFORMATION_MODEL.md)
```
```

- [ ] **Step 3: Add the model to top-level docs index**

```md
## 核心约束

- [Archive Information Model](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/architecture/ARCHIVE_INFORMATION_MODEL.md)
```
```

- [ ] **Step 4: Verify directory completeness**

Run: `python3 - <<'PY'\nfrom pathlib import Path\nroot = Path('/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs')\nrequired = ['architecture', 'integration', 'governance', 'recovery', 'superpowers']\nmissing = [name for name in required if not (root / name).exists()]\nassert not missing, missing\nprint('ok')\nPY`
Expected: prints `ok`

### Task 3: Freeze Upstream / Middle / Downstream Ownership

**Files:**
- Create: `docs/integration/UPSTREAM_DOWNSTREAM_MATRIX.md`
- Modify: `docs/integration/README.md`

- [ ] **Step 1: Create the ownership matrix**

```md
# Upstream Downstream Matrix

## 1. Systems

| Layer | Path | Owns |
|---|---|---|
| Upstream | `6-TRADING` | research/trading production |
| Middle | `7-ARTIFACT-HUB-V2` | route/trace/task/result/feed/ops governance |
| Downstream | `3-FRONTEND` | user entry and lightweight consumption |

## 2. Handoffs

| Producer | Artifact | Middle Layer Role | Consumer |
|---|---|---|---|
| `6-TRADING` | research/trading outputs | ingest, classify, route, audit | `3-FRONTEND` or governance views |
| `3-FRONTEND` | user intent/task requests | route and persistence | Hub / Trading |
| `7-ARTIFACT-HUB-V2` | trace/task/result/feed projections | expose governance evidence | both governance and user views |
```
```

- [ ] **Step 2: Add feed and ops ownership notes**

```md
## 3. Route Ownership

- `/feed`: middle-layer product surface in `7-ARTIFACT-HUB-V2`
- `/ops`: governance console in `7-ARTIFACT-HUB-V2`
- `/dashboard`: downstream user surface in `3-FRONTEND`
```
```

- [ ] **Step 3: Link the matrix from integration index**

```md
## Core Ownership

- [UPSTREAM_DOWNSTREAM_MATRIX.md](./UPSTREAM_DOWNSTREAM_MATRIX.md)
```
```

- [ ] **Step 4: Verify no category is unowned**

Run: `python3 - <<'PY'\nfrom pathlib import Path\np = Path('/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/integration/UPSTREAM_DOWNSTREAM_MATRIX.md')\ntext = p.read_text()\nfor token in ['Upstream', 'Middle', 'Downstream', '/feed', '/ops']:\n    assert token in text, token\nprint('ok')\nPY`
Expected: prints `ok`

### Task 4: Freeze Runtime Asset Governance

**Files:**
- Create: `docs/governance/CHANGE_CLASSIFICATION_POLICY.md`
- Create: `docs/governance/RUNTIME_ASSET_GOVERNANCE.md`
- Modify: `docs/governance/README.md`

- [ ] **Step 1: Create the change classification policy**

```md
# Change Classification Policy

## 1. Change Classes

| Class | Includes | Commit Policy |
|---|---|---|
| Product implementation | `src/feed`, `src/ops-ui`, feature-specific docs | can ship together when same feature |
| Hub core evolution | `artifact-store`, `meta-store`, `router-engine`, `work-order` | separate review line |
| Upstream trading | `6-TRADING/*` | never mix with middle-layer feature commits |
| Downstream frontend | `3-FRONTEND/*` | never mix with middle-layer feature commits |
| Runtime assets | `dreambuddy/artifacts/*` | treat as data, not normal code diff |
| Shared config | `dreambuddy/config/*` | separate review line |
```
```

- [ ] **Step 2: Create runtime asset governance rules**

```md
# Runtime Asset Governance

## 1. Runtime Categories

- `dreambuddy/artifacts`
- `dreambuddy/meta`
- `dreambuddy/config`
- local backup directories

## 2. Rules

- Runtime artifacts are evidence or state, not ordinary feature files.
- Local backup directories must not be swept into feature commits.
- Shared config changes require explicit review because they affect multiple systems.
```
```

- [ ] **Step 3: Link both docs from governance index**

```md
## Core Governance Rules

- [CHANGE_CLASSIFICATION_POLICY.md](./CHANGE_CLASSIFICATION_POLICY.md)
- [RUNTIME_ASSET_GOVERNANCE.md](./RUNTIME_ASSET_GOVERNANCE.md)
```
```

- [ ] **Step 4: Verify policy covers current worktree classes**

Run: `python3 - <<'PY'\nfrom pathlib import Path\ntext = (Path('/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/governance/CHANGE_CLASSIFICATION_POLICY.md').read_text() +\n        Path('/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/governance/RUNTIME_ASSET_GOVERNANCE.md').read_text())\nfor token in ['3-FRONTEND', '6-TRADING', 'dreambuddy/artifacts', 'dreambuddy/config']:\n    assert token in text, token\nprint('ok')\nPY`
Expected: prints `ok`

### Task 5: Build Archive Ledger And Execution Order

**Files:**
- Create: `docs/recovery/ARCHIVE_LEDGER.md`
- Create: `docs/recovery/EXECUTION_ORDER.md`
- Modify: `docs/recovery/README.md`

- [ ] **Step 1: Create the archive ledger**

```md
# Archive Ledger

| Original Path | Archive Copy | Status | Next Action |
|---|---|---|---|
| `FRONTEND_INTEGRATION_DESIGN.md` | `docs/integration/FRONTEND_INTEGRATION_DESIGN.md` | copied | keep both until links are stable |
| `frontend-hub-trading三端联通.md` | `docs/integration/frontend-hub-trading三端联通.md` | copied | keep both until links are stable |
| `docs/architecture-diagram-01-overview.html` | `docs/architecture/diagrams/architecture-diagram-01-overview.html` | copied | keep both until links are stable |
```
```

- [ ] **Step 2: Create execution order document**

```md
# Execution Order

## Phase 1

- freeze boundaries
- freeze source of truth
- freeze archive model

## Phase 2

- freeze upstream/middle/downstream ownership
- freeze runtime governance
- freeze archive ledger

## Phase 3

- resume `/feed` implementation only after architecture governance skeleton is readable and linked
```
```

- [ ] **Step 3: Link both docs from recovery index**

```md
## Governance Execution

- [ARCHIVE_LEDGER.md](./ARCHIVE_LEDGER.md)
- [EXECUTION_ORDER.md](./EXECUTION_ORDER.md)
```
```

- [ ] **Step 4: Verify copied archive files are all recorded**

Run: `python3 - <<'PY'\nfrom pathlib import Path\nroot = Path('/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2')\nledger = (root / 'docs/recovery/ARCHIVE_LEDGER.md').read_text()\nfor token in [\n 'FRONTEND_INTEGRATION_DESIGN.md',\n 'frontend-hub-trading三端联通.md',\n 'architecture-diagram-01-overview.html',\n 'architecture-diagram-02-dataflow.html',\n 'OBJECT_MODEL.md',\n 'CHAIN_WORKFLOWS.md',\n 'GOVERNANCE_SPEC.md',\n 'BOARD_CONSOLE_DESIGN.md',\n 'MARKET_CONSOLE_DESIGN.md',\n 'OPS_UI_README.md',\n]:\n    assert token in ledger, token\nprint('ok')\nPY`
Expected: prints `ok`

### Task 6: Publish A Single Governance Entry Point

**Files:**
- Modify: `docs/README.md`
- Modify: `README.md`

- [ ] **Step 1: Add a “Start Here” sequence to docs index**

```md
## Start Here

1. Read `docs/architecture/SYSTEM_BOUNDARIES.md`
2. Read `docs/architecture/SOURCE_OF_TRUTH.md`
3. Read `docs/integration/UPSTREAM_DOWNSTREAM_MATRIX.md`
4. Read `docs/governance/CHANGE_CLASSIFICATION_POLICY.md`
5. Read `docs/recovery/EXECUTION_ORDER.md`
```
```

- [ ] **Step 2: Add the same sequence to the root README**

```md
## 架构治理入口

建议先阅读：

1. `docs/architecture/SYSTEM_BOUNDARIES.md`
2. `docs/architecture/SOURCE_OF_TRUTH.md`
3. `docs/integration/UPSTREAM_DOWNSTREAM_MATRIX.md`
4. `docs/governance/CHANGE_CLASSIFICATION_POLICY.md`
5. `docs/recovery/EXECUTION_ORDER.md`
```
```

- [ ] **Step 3: Verify the entry path is complete**

Run: `python3 - <<'PY'\nfrom pathlib import Path\npaths = [\n '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/architecture/SYSTEM_BOUNDARIES.md',\n '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/architecture/SOURCE_OF_TRUTH.md',\n '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/integration/UPSTREAM_DOWNSTREAM_MATRIX.md',\n '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/governance/CHANGE_CLASSIFICATION_POLICY.md',\n '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/docs/recovery/EXECUTION_ORDER.md',\n]\nfor p in paths:\n    assert Path(p).exists(), p\nprint('ok')\nPY`
Expected: prints `ok`

## Self-Review

### Spec coverage

- 已覆盖系统分层与边界冻结：Task 1
- 已覆盖单一真相源：Task 1
- 已覆盖文档分类法：Task 2
- 已覆盖上下游承接关系：Task 3
- 已覆盖运行态与提交治理：Task 4
- 已覆盖归档账本与执行顺序：Task 5
- 已覆盖统一阅读入口：Task 6

### Placeholder scan

- 本计划没有使用 `TODO`、`TBD`、`implement later`
- 每个任务都给出明确文件、文档骨架、命令和预期结果

### Type consistency

- 统一使用 `SYSTEM_BOUNDARIES`、`SOURCE_OF_TRUTH`、`UPSTREAM_DOWNSTREAM_MATRIX`
- 统一使用“上游 / 中间 / 下游 / 共享底座 / 运行态资产”分类口径

Plan complete and saved to `docs/superpowers/plans/2026-05-20-architecture-archive-governance.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
