# PR9 Self-Hosted Runner Agent Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace “needs manual click to run” local automations with GitHub Actions schedules running on a self-hosted macOS runner, while keeping the collaboration protocol landing points (PR comments + ledger) unchanged.

**Architecture:** Add three scheduled GitHub Actions workflows (developer/validator/governance) that run on `self-hosted` runner. Workflows use `gh` with `${{ github.token }}` (no interactive auth) to read PR9 state, run local build/test for `7-ARTIFACT-HUB-V2`, and post structured comment bodies that match existing templates. Ledger advancement remains triggered by `[验证结论 / VALIDATION_RESULT]` → claim guard controller.

**Tech Stack:** GitHub Actions, self-hosted runner (macOS), GitHub CLI (`gh`), Python 3.11, Node.js (project-defined), existing `AGENT协作工具/templates/*` and `AGENT协作工具/github-actions/run_governance_ledger_cycle.py`.

---

## Scope & Non-Goals

- In scope:
  - Self-hosted runner setup guide (one-time manual steps).
  - Three scheduled workflows that run without human clicking.
  - Protocol-aligned outputs: STARTED/UPDATED/TEST_REPORT/DONE/VALIDATION_RESULT as PR comments (or comment drafts).
  - Validator handoff to drive ledger transition to `ledgered` (and reward write) via existing claim guard controller.
- Out of scope (for this plan):
  - LLM-based “reasoning” inside workflows.
  - Auto code changes/auto PR commits by workflows.
  - Archiving/knowledge_sync automation beyond v1 minimal chain.

---

## File Structure (new/modified)

**Create (workflows):**
- `.github/workflows/pr9-developer-agent.yml`
- `.github/workflows/pr9-validator-agent.yml`
- `.github/workflows/pr9-governance-agent.yml`

**Modify (docs):**
- `AGENT协作工具/docs/agent-collaboration-system-v1-design.md` (add “self-hosted runner automation” section)
- `AGENT协作工具/docs/README.md` (link automation section)

**Create (docs):**
- `AGENT协作工具/docs/self-hosted-runner.md` (setup + ops)

---

### Task 1: Document Self-Hosted Runner Setup

**Files:**
- Create: `AGENT协作工具/docs/self-hosted-runner.md`

- [ ] **Step 1: Write setup doc**
  - Include:
    - Runner labels to use: `self-hosted`, `macOS`, `workbuddy`
    - Required tools: `gh`, `node`, `python3`
    - Required GitHub permissions: Actions enabled; runner registered to repo
    - How to keep runner running (service / login item guidance)
    - How to rotate/remove runner

- [ ] **Step 2: Commit**

```bash
git add AGENT协作工具/docs/self-hosted-runner.md
git commit -m "docs(automation): add self-hosted runner setup guide"
```

---

### Task 2: PR9 Developer Agent Workflow (build/test + TEST_REPORT)

**Files:**
- Create: `.github/workflows/pr9-developer-agent.yml`

- [ ] **Step 1: Write workflow**
  - Trigger:
    - `schedule: "20 * * * *"` (hourly)
    - `workflow_dispatch`
  - Runner:
    - `runs-on: [self-hosted, macOS, workbuddy]`
  - Permissions:
    - `contents: read`
    - `pull-requests: write` (or `issues: write`) for commenting
  - Steps:
    - Checkout `main`
    - Ensure `gh` is available (`gh --version`)
    - Set `GH_TOKEN: ${{ github.token }}`
    - Get PR9 head branch + head sha via `gh pr view 9 --json headRefName,headRefOid`
    - Fetch and checkout that branch in the workflow workspace
    - Run (within `7-ARTIFACT-HUB-V2`):
      - `npm ci`
      - `npm run build`
      - `npm test`
    - Create a TEST_REPORT comment body matching `AGENT协作工具/templates/test-report-comment.md` fields (include task_id, commands, pass/fail summary, head sha)
    - Post comment with `gh pr comment 9 --body-file <file>`
    - If build/test fails: still post TEST_REPORT, and exit non-zero to keep it visible in Actions

- [ ] **Step 2: Run smoke check locally**

```bash
python3 -c "import yaml" 2>/dev/null || true
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/pr9-developer-agent.yml
git commit -m "ci(pr9): add developer agent workflow on self-hosted runner"
```

---

### Task 3: PR9 Validator Agent Workflow (re-run build/test + VALIDATION_RESULT)

**Files:**
- Create: `.github/workflows/pr9-validator-agent.yml`

- [ ] **Step 1: Write workflow**
  - Trigger:
    - `schedule: "0 */2 * * *"` (every 2 hours)
    - `workflow_dispatch`
  - Runner:
    - `runs-on: [self-hosted, macOS, workbuddy]`
  - Permissions:
    - `contents: read`
    - `pull-requests: write` (or `issues: write`) for commenting
  - Steps:
    - Same “get PR9 head branch + checkout” as developer workflow
    - Re-run `npm ci && npm run build && npm test`
    - If PASS:
      - Post `[验证结论 / VALIDATION_RESULT]` comment matching `AGENT协作工具/templates/pr-comment-validation-result.md`
      - Must include:
        - `Hard Gate Result: PASS`
        - `Decision: ACCEPTED`
        - `Governance Handoff: ledgered`
        - (Recommended) `Task ID: task-pr9-artifact-hub-v2-build-1`
    - If FAIL:
      - Post VALIDATION_RESULT with `Hard Gate Result: BLOCK`, `Decision: REWORK`, and command-like `recommended_next_action`

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/pr9-validator-agent.yml
git commit -m "ci(pr9): add validator agent workflow on self-hosted runner"
```

---

### Task 4: PR9 Governance Agent Workflow (protocol completeness + reminders)

**Files:**
- Create: `.github/workflows/pr9-governance-agent.yml`

- [ ] **Step 1: Write workflow**
  - Trigger:
    - `schedule: "10 */4 * * *"` (every 4 hours)
    - `workflow_dispatch`
  - Runner:
    - `runs-on: [self-hosted, macOS, workbuddy]`
  - Permissions:
    - `contents: read`
    - `pull-requests: write` (or `issues: write`) for commenting
  - Steps:
    - Fetch PR9 comments (`gh pr view 9 --comments`)
    - Check for required protocol anchors (minimal):
      - STARTED exists with Task ID
      - TEST_REPORT exists (recent)
      - VALIDATION_RESULT exists (if tests pass)
    - If missing:
      - Post an UPDATED or BLOCKED comment draft that tells exactly what to post next (do not edit ledger; only instructions)

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/pr9-governance-agent.yml
git commit -m "ci(pr9): add governance agent workflow on self-hosted runner"
```

---

### Task 5: Docs Update & Broadcast

**Files:**
- Modify: `AGENT协作工具/docs/agent-collaboration-system-v1-design.md`
- Modify: `AGENT协作工具/docs/README.md`

- [ ] **Step 1: Update design doc**
  - Add a section describing:
    - Why self-hosted runner is used (avoid interactive auth; use local toolchain)
    - How it preserves protocol landing points
    - Security boundaries (minimal permissions; no secrets logged)

- [ ] **Step 2: Update docs README link**

- [ ] **Step 3: Commit**

```bash
git add AGENT协作工具/docs/agent-collaboration-system-v1-design.md AGENT协作工具/docs/README.md
git commit -m "docs(collaboration): document self-hosted runner automation"
```

---

### Task 6: Verification & Rollout Checklist

- [ ] **Step 1: Verify existing tests still pass**

```bash
python3 -m unittest discover -s "AGENT协作工具/github-actions/tests" -p "test_*.py"
```

- [ ] **Step 2: Validate workflows exist**

```bash
ls -1 .github/workflows | cat
```

- [ ] **Step 3: Manual runner verification checklist (doc-only)**
  - Confirm runner labels match workflow `runs-on`
  - Trigger workflows with `workflow_dispatch`
  - Confirm PR9 receives comments
  - Confirm claim guard advances ledger after validator posts ACCEPTED+handoff

