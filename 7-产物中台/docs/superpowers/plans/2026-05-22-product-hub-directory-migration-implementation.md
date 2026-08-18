# Product Hub Directory Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-home the current `7-ARTIFACT_HUB` into the new `7-产物中台` container, rename it as `系统研究索引体系`, split research documents into `docs`, and create empty directories for the new hub modules.

**Architecture:** This is a directory-governance migration, not a feature refactor. The implementation first creates the new product-hub container, then moves the existing independent hub into the `系统研究索引体系` module, separates documentation from implementation, and finally creates empty shell directories for the remaining modules. Compatibility fixes for imports, scripts, build paths, and navigation are intentionally deferred to later feature work.

**Tech Stack:** macOS filesystem operations, git, shell verification commands, markdown documentation

---

## File Structure

### New Files

- `7-产物中台/`
  - New top-level product-hub container.
- `7-产物中台/docs/`
  - Centralized documentation directory after the split.
- `7-产物中台/ui-map/`
  - Empty shell directory for the independent hub homepage module.
- `7-产物中台/用户上下文索引系统/`
  - Empty shell directory for the user-context index module.
- `7-产物中台/策略主线/`
  - Empty shell directory for the strategy mainline module.
- `7-产物中台/系统研究链路/`
  - Empty shell directory for the system-research chain module.
- `7-产物中台/系统运营链路/`
  - Empty shell directory for the system-operations chain module.
- `7-产物中台/docs/ENGINEERING_INDEX.md`
  - Placeholder engineering index document for later module work.
- `7-产物中台/docs/FAQ.md`
  - Placeholder FAQ document for later maintenance work.

### Moved / Renamed Paths

- Move: `7-ARTIFACT_HUB/` → `7-产物中台/系统研究索引体系/`
  - Entire current implementation is re-homed as the `系统研究索引体系` module.

### Modified Files

- `7-产物中台/docs/PROJECT_PLAN.md` if it currently exists inside the moved directory and must remain documentation.
- `7-产物中台/docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md`
  - Add implementation notes after migration verification.

## Task 1: Create The Product Hub Container

**Files:**
- Create: `7-产物中台/`
- Create: `7-产物中台/docs/`

- [ ] **Step 1: Write the failing directory check**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
test -d "7-产物中台"
```

Expected: FAIL with exit code `1` because the directory does not exist yet.

- [ ] **Step 2: Create the container directories**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
mkdir -p "7-产物中台/docs"
```

- [ ] **Step 3: Verify the directories now exist**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
test -d "7-产物中台"
test -d "7-产物中台/docs"
```

Expected: both commands exit `0`.

- [ ] **Step 4: Commit**

```bash
git add "7-产物中台"
git commit -m "chore: create product hub container"
```

## Task 2: Re-Home `7-ARTIFACT_HUB` As `系统研究索引体系`

**Files:**
- Move: `7-ARTIFACT_HUB/` → `7-产物中台/系统研究索引体系/`

- [ ] **Step 1: Write the failing path check**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
test -d "7-产物中台/系统研究索引体系"
```

Expected: FAIL with exit code `1` because the renamed directory does not exist yet.

- [ ] **Step 2: Move and rename the directory**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
mv "7-ARTIFACT_HUB" "7-产物中台/系统研究索引体系"
```

- [ ] **Step 3: Verify old path is gone and new path exists**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
test ! -e "7-ARTIFACT_HUB"
test -d "7-产物中台/系统研究索引体系"
```

Expected: both commands exit `0`.

- [ ] **Step 4: Capture the top-level tree after re-home**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
find "7-产物中台" -maxdepth 2 -mindepth 1 | sort
```

Expected: output includes `7-产物中台/docs` and `7-产物中台/系统研究索引体系`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: rehome artifact hub as system research index"
```

## Task 3: Split Research Documents Into `docs`

**Files:**
- Move documentation files from `7-产物中台/系统研究索引体系/` into `7-产物中台/docs/`
- Create: `7-产物中台/docs/ENGINEERING_INDEX.md`
- Create: `7-产物中台/docs/FAQ.md`

- [ ] **Step 1: Identify documentation candidates**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
find "7-产物中台/系统研究索引体系" -maxdepth 2 \( -name "*.md" -o -name "*.canvas" \) | sort
```

Expected: list of markdown and canvas files currently mixed into the implementation directory.

- [ ] **Step 2: Move the top-level research documents into `docs`**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
mkdir -p "7-产物中台/docs"
for file in "7-产物中台/系统研究索引体系"/*.md; do
  [ -e "$file" ] || continue
  mv "$file" "7-产物中台/docs/"
done
```

- [ ] **Step 3: Seed the engineering index and FAQ**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
cat > "7-产物中台/docs/ENGINEERING_INDEX.md" <<'EOF'
# 工程索引

- 模块总容器：`7-产物中台`
- 已归位模块：`系统研究索引体系`
- 预留模块：`ui-map`、`用户上下文索引系统`、`策略主线`、`系统研究链路`、`系统运营链路`
EOF

cat > "7-产物中台/docs/FAQ.md" <<'EOF'
# FAQ

## 当前为什么先做目录归位？

- 为了先完成中台总容器、模块归位、文档分层和新模块落位，降低后续治理成本。
EOF
```

- [ ] **Step 4: Verify docs are separated from implementation root**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
find "7-产物中台/docs" -maxdepth 1 -name "*.md" | sort
find "7-产物中台/系统研究索引体系" -maxdepth 1 -name "*.md" | sort
```

Expected:

```text
The first command lists moved docs and the two new docs.
The second command is empty or only retains implementation-adjacent markdown intentionally left behind.
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: split product hub docs from implementation"
```

## Task 4: Create Empty Module Directories / Shell Directories

**Files:**
- Create: `7-产物中台/ui-map/`
- Create: `7-产物中台/用户上下文索引系统/`
- Create: `7-产物中台/策略主线/`
- Create: `7-产物中台/系统研究链路/`
- Create: `7-产物中台/系统运营链路/`

- [ ] **Step 1: Write the failing directory checks**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
test -d "7-产物中台/ui-map"
test -d "7-产物中台/用户上下文索引系统"
test -d "7-产物中台/策略主线"
test -d "7-产物中台/系统研究链路"
test -d "7-产物中台/系统运营链路"
```

Expected: all checks fail before the directories are created.

- [ ] **Step 2: Create the module directories**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
mkdir -p \
  "7-产物中台/ui-map" \
  "7-产物中台/用户上下文索引系统" \
  "7-产物中台/策略主线" \
  "7-产物中台/系统研究链路" \
  "7-产物中台/系统运营链路"
```

- [ ] **Step 3: Add keep files so the empty directories are tracked**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
touch \
  "7-产物中台/ui-map/.gitkeep" \
  "7-产物中台/用户上下文索引系统/.gitkeep" \
  "7-产物中台/策略主线/.gitkeep" \
  "7-产物中台/系统研究链路/.gitkeep" \
  "7-产物中台/系统运营链路/.gitkeep"
```

- [ ] **Step 4: Verify the final module skeleton**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
find "7-产物中台" -maxdepth 2 -mindepth 1 | sort
```

Expected: output includes `docs`, `系统研究索引体系`, and all five new module directories.

- [ ] **Step 5: Commit**

```bash
git add "7-产物中台"
git commit -m "chore: add product hub module skeleton"
```

## Task 5: Final Verification And Spec Backfill

**Files:**
- Modify: `7-产物中台/docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md`

- [ ] **Step 1: Verify the final directory map**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
find "7-产物中台" -maxdepth 2 -mindepth 1 | sort
```

Expected: output reflects the target structure from the spec.

- [ ] **Step 2: Verify there is no top-level `7-ARTIFACT_HUB` left**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
test ! -e "7-ARTIFACT_HUB"
```

Expected: exit code `0`.

- [ ] **Step 3: Backfill implementation notes into the spec**

```md
## Implementation Notes

- Created `7-产物中台` as the new top-level container
- Re-homed `7-ARTIFACT_HUB` into `7-产物中台/系统研究索引体系`
- Split research documentation into `7-产物中台/docs`
- Added empty shell directories for `ui-map` and the remaining new modules
```

- [ ] **Step 4: Commit**

```bash
git add "7-产物中台/docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md"
git commit -m "docs: finalize product hub migration handoff"
```

## Self-Review

- Spec coverage:
  - 创建 `7-产物中台`: Task 1
  - 归位并重命名 `7-ARTIFACT_HUB`: Task 2
  - 文档剥离到 `docs`: Task 3
  - 新模块空目录/壳目录: Task 4
  - 迁移后结构验证与文档回填: Task 5
- Placeholder scan:
  - No `TODO`/`TBD` placeholders remain.
  - Every task includes exact commands and expected outcomes.
- Type consistency:
  - Migration paths and target directory names remain consistent across all tasks.

Plan complete and saved to `7-ARTIFACT_HUB/docs/superpowers/plans/2026-05-22-product-hub-directory-migration-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
