# Product Hub Docs Hard Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-clean `7-产物中台/docs` so the main area keeps only the current product-hub mainline documents and governance docs aligned to that mainline.

**Architecture:** This is a docs-governance cleanup, not a feature refactor. The execution first removes obsolete specs and plans, then deletes the outdated top-level project plan, refreshes the governance docs so they point to the new product-hub structure, adds one minimal archive pointer, and finally verifies that the docs tree matches the approved target state.

**Tech Stack:** Markdown, macOS filesystem operations, git, shell verification commands

---

## File Structure

### Create

- `7-产物中台/docs/archive/README.md`
  - Minimal archive note that redirects historical lookup to `git` history.

### Modify

- `7-产物中台/docs/ENGINEERING_INDEX.md`
  - Rewritten to point only at the current product-hub mainline and retained docs.
- `7-产物中台/docs/FAQ.md`
  - Rewritten to explain the new docs boundary and why old planning docs were removed from the main area.

### Delete

- `7-产物中台/docs/PROJECT_PLAN.md`
  - Remove because its content still points to the old `7-ARTIFACT_HUB` mainline and old legacy priorities.
- `7-产物中台/docs/superpowers/specs/2026-05-21-development-demo-user-fallback-design.md`
- `7-产物中台/docs/superpowers/specs/2026-05-21-frontend-driven-strategy-task-order-design.md`
- `7-产物中台/docs/superpowers/specs/2026-05-21-legacy-hub-data-foundation-design.md`
- `7-产物中台/docs/superpowers/specs/2026-05-21-legacy-hub-feed-chain-relation-design.md`
- `7-产物中台/docs/superpowers/specs/2026-05-22-artifact-hub-main-chain-acceptance-design.md`
- `7-产物中台/docs/superpowers/plans/2026-05-21-development-demo-user-fallback-implementation.md`
- `7-产物中台/docs/superpowers/plans/2026-05-21-frontend-driven-strategy-task-order-implementation.md`
- `7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-data-foundation-implementation.md`
- `7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-feed-chain-relation-implementation.md`
- `7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-realtime-skeleton-implementation.md`
- `7-产物中台/docs/superpowers/plans/2026-05-22-dashboard-main-panel-prototype-implementation.md`

### Keep

- `7-产物中台/docs/ENGINEERING_INDEX.md`
- `7-产物中台/docs/FAQ.md`
- `7-产物中台/docs/archive/README.md`
- `7-产物中台/docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md`
- `7-产物中台/docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md`
- `7-产物中台/docs/superpowers/plans/2026-05-22-ui-map-independent-hub-main-map-implementation.md`
- `7-产物中台/docs/superpowers/plans/2026-05-22-product-hub-directory-migration-implementation.md`

## Task 1: Remove Obsolete Spec Documents

**Files:**
- Delete: `7-产物中台/docs/superpowers/specs/2026-05-21-development-demo-user-fallback-design.md`
- Delete: `7-产物中台/docs/superpowers/specs/2026-05-21-frontend-driven-strategy-task-order-design.md`
- Delete: `7-产物中台/docs/superpowers/specs/2026-05-21-legacy-hub-data-foundation-design.md`
- Delete: `7-产物中台/docs/superpowers/specs/2026-05-21-legacy-hub-feed-chain-relation-design.md`
- Delete: `7-产物中台/docs/superpowers/specs/2026-05-22-artifact-hub-main-chain-acceptance-design.md`

- [ ] **Step 1: Verify all obsolete spec files still exist before deletion**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
test -f "7-产物中台/docs/superpowers/specs/2026-05-21-development-demo-user-fallback-design.md"
test -f "7-产物中台/docs/superpowers/specs/2026-05-21-frontend-driven-strategy-task-order-design.md"
test -f "7-产物中台/docs/superpowers/specs/2026-05-21-legacy-hub-data-foundation-design.md"
test -f "7-产物中台/docs/superpowers/specs/2026-05-21-legacy-hub-feed-chain-relation-design.md"
test -f "7-产物中台/docs/superpowers/specs/2026-05-22-artifact-hub-main-chain-acceptance-design.md"
```

Expected: all commands exit `0`.

- [ ] **Step 2: Delete the obsolete spec files**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
rm \
  "7-产物中台/docs/superpowers/specs/2026-05-21-development-demo-user-fallback-design.md" \
  "7-产物中台/docs/superpowers/specs/2026-05-21-frontend-driven-strategy-task-order-design.md" \
  "7-产物中台/docs/superpowers/specs/2026-05-21-legacy-hub-data-foundation-design.md" \
  "7-产物中台/docs/superpowers/specs/2026-05-21-legacy-hub-feed-chain-relation-design.md" \
  "7-产物中台/docs/superpowers/specs/2026-05-22-artifact-hub-main-chain-acceptance-design.md"
```

- [ ] **Step 3: Verify only the retained spec files remain**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
find "7-产物中台/docs/superpowers/specs" -maxdepth 1 -type f -name "*.md" | sort
```

Expected:

```text
7-产物中台/docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md
7-产物中台/docs/superpowers/specs/2026-05-22-product-hub-docs-hard-cleanup-design.md
7-产物中台/docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: remove obsolete product hub specs"
```

## Task 2: Remove Obsolete Plan Documents

**Files:**
- Delete: `7-产物中台/docs/superpowers/plans/2026-05-21-development-demo-user-fallback-implementation.md`
- Delete: `7-产物中台/docs/superpowers/plans/2026-05-21-frontend-driven-strategy-task-order-implementation.md`
- Delete: `7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-data-foundation-implementation.md`
- Delete: `7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-feed-chain-relation-implementation.md`
- Delete: `7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-realtime-skeleton-implementation.md`
- Delete: `7-产物中台/docs/superpowers/plans/2026-05-22-dashboard-main-panel-prototype-implementation.md`

- [ ] **Step 1: Verify all obsolete plan files still exist before deletion**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
test -f "7-产物中台/docs/superpowers/plans/2026-05-21-development-demo-user-fallback-implementation.md"
test -f "7-产物中台/docs/superpowers/plans/2026-05-21-frontend-driven-strategy-task-order-implementation.md"
test -f "7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-data-foundation-implementation.md"
test -f "7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-feed-chain-relation-implementation.md"
test -f "7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-realtime-skeleton-implementation.md"
test -f "7-产物中台/docs/superpowers/plans/2026-05-22-dashboard-main-panel-prototype-implementation.md"
```

Expected: all commands exit `0`.

- [ ] **Step 2: Delete the obsolete plan files**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
rm \
  "7-产物中台/docs/superpowers/plans/2026-05-21-development-demo-user-fallback-implementation.md" \
  "7-产物中台/docs/superpowers/plans/2026-05-21-frontend-driven-strategy-task-order-implementation.md" \
  "7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-data-foundation-implementation.md" \
  "7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-feed-chain-relation-implementation.md" \
  "7-产物中台/docs/superpowers/plans/2026-05-21-legacy-hub-realtime-skeleton-implementation.md" \
  "7-产物中台/docs/superpowers/plans/2026-05-22-dashboard-main-panel-prototype-implementation.md"
```

- [ ] **Step 3: Verify only the retained plan files remain**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
find "7-产物中台/docs/superpowers/plans" -maxdepth 1 -type f -name "*.md" | sort
```

Expected:

```text
7-产物中台/docs/superpowers/plans/2026-05-22-product-hub-directory-migration-implementation.md
7-产物中台/docs/superpowers/plans/2026-05-22-product-hub-docs-hard-cleanup-implementation.md
7-产物中台/docs/superpowers/plans/2026-05-22-ui-map-independent-hub-main-map-implementation.md
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: remove obsolete product hub plans"
```

## Task 3: Remove The Outdated Top-Level Project Plan And Add Minimal Archive Guidance

**Files:**
- Delete: `7-产物中台/docs/PROJECT_PLAN.md`
- Create: `7-产物中台/docs/archive/README.md`

- [ ] **Step 1: Prove `PROJECT_PLAN.md` still points to the old mainline**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
grep -n "7-ARTIFACT_HUB\|legacy-hub\|数据底座" "7-产物中台/docs/PROJECT_PLAN.md"
```

Expected: output contains old-mainline markers such as `7-ARTIFACT_HUB` and `legacy-hub`.

- [ ] **Step 2: Delete the outdated top-level plan**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
rm "7-产物中台/docs/PROJECT_PLAN.md"
```

- [ ] **Step 3: Create the minimal archive note**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
mkdir -p "7-产物中台/docs/archive"
cat > "7-产物中台/docs/archive/README.md" <<'EOF'
# Archive

- 旧规划文档、旧实施计划和已被替代的中台方案，已从 `7-产物中台/docs` 主区清除。
- 当前主区只保留正在使用的中台主线文档与治理文档。
- 如需追溯旧文档，请通过 `git log -- 7-产物中台/docs` 或仓库历史版本查看。
EOF
```

- [ ] **Step 4: Verify the top-level docs boundary**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
find "7-产物中台/docs" -maxdepth 2 -type f \( -name "*.md" -o -name "*.canvas" \) | sort
```

Expected: top-level output no longer contains `PROJECT_PLAN.md` and now includes `archive/README.md`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: trim top-level product hub docs"
```

## Task 4: Refresh Governance Docs For The Current Mainline

**Files:**
- Modify: `7-产物中台/docs/ENGINEERING_INDEX.md`
- Modify: `7-产物中台/docs/FAQ.md`

- [ ] **Step 1: Rewrite `ENGINEERING_INDEX.md` to the current mainline**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
cat > "7-产物中台/docs/ENGINEERING_INDEX.md" <<'EOF'
# 工程索引

## 项目定位

- `7-产物中台` 是当前产物中台总容器。
- `系统研究索引体系` 是已经归位的现有实现工程。
- `ui-map`、`用户上下文索引系统`、`策略主线`、`系统研究链路`、`系统运营链路` 是后续按模块推进的目标目录。

## 当前文档主线

- 当前保留的设计文档：
- [ui-map-independent-hub-main-map-design.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md)
- [product-hub-directory-migration-design.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md)
- 当前保留的实施计划：
- [ui-map-independent-hub-main-map-implementation.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/docs/superpowers/plans/2026-05-22-ui-map-independent-hub-main-map-implementation.md)
- [product-hub-directory-migration-implementation.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/docs/superpowers/plans/2026-05-22-product-hub-directory-migration-implementation.md)

## 目录地图

- `docs/`
- 当前治理文档与正式 spec / plan 沉淀区。
- `系统研究索引体系/`
- 已归位的老中台实现工程，当前可运行并负责系统研究索引能力。
- `ui-map/`
- 独立中台首页模块预留目录。
- `用户上下文索引系统/`
- 用户配置、记忆、执行上下文承载模块预留目录。
- `策略主线/`
- 策略统一收口与主链承接模块预留目录。
- `系统研究链路/`
- 系统研究链路透视模块预留目录。
- `系统运营链路/`
- 系统运营链路透视模块预留目录。

## 协作者先看

- 先看 `docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md`。
- 再看 `docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md`。
- 若要追溯旧文档，请查看 `docs/archive/README.md` 提示并通过 `git` 历史查询。
EOF
```

- [ ] **Step 2: Rewrite `FAQ.md` to explain the cleaned boundary**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
cat > "7-产物中台/docs/FAQ.md" <<'EOF'
# FAQ

## 为什么现在要做文档强力清理

- 因为 `7-产物中台` 已经完成目录归位，主线和模块边界已经明确。
- 如果继续在主区保留大量旧规划文档，会再次把 `docs` 变成历史堆积区。
- 当前目标是让协作者进入 `docs` 后，第一眼只能看到仍然有效的主线文档。

## 为什么删除旧文档而不是建复杂归档

- 因为这次采用的是强力清理，不是历史文档再整理。
- 旧方案如果仍长期保留在可见主区，会继续干扰当前工程判断。
- 真正需要追溯时，直接依赖 `git` 历史更清晰，也更符合这次治理目标。

## 现在保留哪些正式文档

- `ui-map` 独立中台首页设计与实施计划。
- 中台目录归位迁移设计与实施计划。
- 顶层治理文档 `ENGINEERING_INDEX.md`、`FAQ.md`。

## `PROJECT_PLAN.md` 为什么被删除

- 因为它仍然基于旧的 `7-ARTIFACT_HUB` 主线叙事。
- 其中的优先级、路径引用和 legacy 文档引用都不再代表当前中台总容器结构。
- 在没有改写为当前主线之前，删除比继续保留更安全。
EOF
```

- [ ] **Step 3: Verify both governance docs no longer reference the old mainline**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
grep -n "7-ARTIFACT_HUB\|legacy-hub" "7-产物中台/docs/ENGINEERING_INDEX.md" "7-产物中台/docs/FAQ.md"
```

Expected: no output and exit code `1`.

- [ ] **Step 4: Commit**

```bash
git add "7-产物中台/docs/ENGINEERING_INDEX.md" "7-产物中台/docs/FAQ.md"
git commit -m "docs: align product hub governance docs"
```

## Task 5: Final Verification

**Files:**
- Verify: `7-产物中台/docs/`

- [ ] **Step 1: Verify the final retained top-level docs**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
find "7-产物中台/docs" -maxdepth 1 -type f -name "*.md" | sort
```

Expected:

```text
7-产物中台/docs/ENGINEERING_INDEX.md
7-产物中台/docs/FAQ.md
```

- [ ] **Step 2: Verify the final retained spec docs**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
find "7-产物中台/docs/superpowers/specs" -maxdepth 1 -type f -name "*.md" | sort
```

Expected:

```text
7-产物中台/docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md
7-产物中台/docs/superpowers/specs/2026-05-22-product-hub-docs-hard-cleanup-design.md
7-产物中台/docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md
```

- [ ] **Step 3: Verify the final retained plan docs**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
find "7-产物中台/docs/superpowers/plans" -maxdepth 1 -type f -name "*.md" | sort
```

Expected:

```text
7-产物中台/docs/superpowers/plans/2026-05-22-product-hub-directory-migration-implementation.md
7-产物中台/docs/superpowers/plans/2026-05-22-product-hub-docs-hard-cleanup-implementation.md
7-产物中台/docs/superpowers/plans/2026-05-22-ui-map-independent-hub-main-map-implementation.md
```

- [ ] **Step 4: Verify archive note exists**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
test -f "7-产物中台/docs/archive/README.md"
```

Expected: exit code `0`.

- [ ] **Step 5: Verify git status only shows intended docs changes**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git status --short -- "7-产物中台/docs"
```

Expected: output only references the deleted obsolete docs, the deleted `PROJECT_PLAN.md`, the new `archive/README.md`, and the rewritten governance docs.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: finalize product hub docs hard cleanup"
```

## Self-Review

- Spec coverage:
  - 删除被替代 spec: Task 1
  - 删除被替代 plan: Task 2
  - 判定并删除旧 `PROJECT_PLAN.md`: Task 3
  - 极简归档 `archive/README.md`: Task 3
  - 保留并收口治理文档: Task 4
  - 最终结构校验: Task 5
- Placeholder scan:
  - No `TODO`/`TBD` placeholders remain.
  - Every task uses exact paths, commands, and expected results.
- Type consistency:
  - The kept files, removed files, and top-level docs boundary remain consistent across all tasks.

Plan complete and saved to `7-产物中台/docs/superpowers/plans/2026-05-22-product-hub-docs-hard-cleanup-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
