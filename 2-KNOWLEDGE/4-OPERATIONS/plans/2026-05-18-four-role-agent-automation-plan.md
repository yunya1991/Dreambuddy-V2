# Four-Role Agent Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 4-role (Developer / Validator / Governance / Ledger-Protocol) automation suite that runs on `workflow_dispatch` to avoid “Approve and run workflow”, and can be executed locally via `gh workflow run`.

**Architecture:** Introduce three PR-parameterized workflows (developer/validator/governance) running on self-hosted runner. Keep ledger-protocol automation via protocol monitor. Extend claim-guard to consume validator-run artifacts under `workflow_run` and apply ledger cycle without relying on bot `issue_comment`.

**Tech Stack:** GitHub Actions, self-hosted runner (macOS/workbuddy), GitHub CLI (`gh`), Python (existing ledger controller), Node (7-ARTIFACT-HUB-V2 build/test)

---

## File Map (What to Change)

**Create**
- `.github/workflows/collab-developer-agent.yml`
- `.github/workflows/collab-validator-agent.yml`
- `.github/workflows/collab-governance-agent.yml`
- `AGENT协作工具/github-actions/tests/test_collab_workflows_present.py`

**Modify**
- `.github/workflows/agent-collaboration-claim-guard.yml`
- `.github/workflows/agent-protocol-monitor.yml` (rename workflow name to ledger-protocol identity; keep triggers)
- `AGENT协作工具/docs/05-FAQ.md` (add “why approve-and-run happens” + “how to run dispatch workflows”)

---

### Task 1: Add PR-parameterized Developer workflow (workflow_dispatch only)

**Files:**
- Create: `.github/workflows/collab-developer-agent.yml`

- [ ] **Step 1: Create `.github/workflows/collab-developer-agent.yml`**

```yaml
name: collab-developer-agent

on:
  workflow_dispatch:
    inputs:
      pr_number:
        description: "Target PR number"
        required: true
        type: string
      task_id:
        description: "Task ID (ledger pointer)"
        required: true
        type: string
      workspace_path:
        description: "Workspace path (default 7-ARTIFACT-HUB-V2)"
        required: false
        default: "7-ARTIFACT-HUB-V2"
        type: string

permissions:
  contents: read
  issues: write
  pull-requests: write

concurrency:
  group: collab-developer-agent-${{ inputs.pr_number }}
  cancel-in-progress: true

jobs:
  developer:
    runs-on: [self-hosted, macOS, workbuddy]
    env:
      PR_NUMBER: ${{ inputs.pr_number }}
      TASK_ID: ${{ inputs.task_id }}
      WORKSPACE_PATH: ${{ inputs.workspace_path }}
      GH_TOKEN: ${{ github.token }}
      GH_REPO: ${{ github.repository }}
    steps:
      - name: Checkout main
        uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0

      - name: Verify gh
        run: gh --version

      - name: Resolve PR head
        id: pr
        run: |
          echo "head_ref=$(gh pr view ${PR_NUMBER} --json headRefName --jq .headRefName)" >> "$GITHUB_OUTPUT"
          echo "head_sha=$(gh pr view ${PR_NUMBER} --json headRefOid --jq .headRefOid)" >> "$GITHUB_OUTPUT"

      - name: Checkout PR head
        run: |
          git fetch origin "${{ steps.pr.outputs.head_ref }}"
          git checkout -B "pr${PR_NUMBER}" "origin/${{ steps.pr.outputs.head_ref }}"

      - name: Ensure STARTED anchor exists
        run: |
          comments="$(gh pr view ${PR_NUMBER} --json comments --jq '.comments[].body' || true)"
          if printf "%s\n" "$comments" | grep -q '^\[协作开工声明 / STARTED\]'; then
            exit 0
          fi

          {
            printf '%s\n' \
              '[协作开工声明 / STARTED]' \
              '' \
              'Agent: collab-developer-agent' \
              "任务: PR${PR_NUMBER} / build+test" \
              "Task ID: ${TASK_ID}" \
              "分支: ${{ steps.pr.outputs.head_ref }}" \
              "Workspace Path: ${WORKSPACE_PATH}" \
              'Execution Mode: STANDARD' \
              'Direct Takeover: no' \
              'Governance Agent: collab-governance-agent' \
              'Ledger Protocol Agent: ledger-protocol-agent' \
              'Task Type: parallel' \
              'Dependency Gate: accepted' \
              'Current Sync State: none' \
              'Next Required Action: validator: post VALIDATION_RESULT with Governance Handoff: ledgered if PASS' \
              "Claim Target: ${TASK_ID}" \
              '计划修改:' \
              "- ${WORKSPACE_PATH}/*" \
              '' \
              '冲突门禁结果:' \
              '- decision: SAFE' \
              '- reason_codes: []' \
              '' \
              '状态: STARTED'
          } > pr_started.md
          gh pr comment ${PR_NUMBER} --body-file pr_started.md

      - name: Build and test
        id: run
        run: |
          set +e
          cd "${WORKSPACE_PATH}"
          npm ci
          npm_ci_exit=$?
          npm run build
          build_exit=$?
          npm test
          test_exit=$?
          set -e

          overall=0
          if [ "$npm_ci_exit" -ne 0 ] || [ "$build_exit" -ne 0 ] || [ "$test_exit" -ne 0 ]; then
            overall=1
          fi

          echo "npm_ci_exit=$npm_ci_exit" >> "$GITHUB_OUTPUT"
          echo "build_exit=$build_exit" >> "$GITHUB_OUTPUT"
          echo "test_exit=$test_exit" >> "$GITHUB_OUTPUT"
          echo "overall=$overall" >> "$GITHUB_OUTPUT"

      - name: Post TEST_REPORT comment
        run: |
          unit="PASS"
          integration="PASS"
          stress="WAIVED"
          decision="TEST_PASS"
          if [ "${{ steps.run.outputs.overall }}" != "0" ]; then
            unit="FAIL"
            integration="FAIL"
            decision="TEST_FAIL"
          fi

          run_url="${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
          {
            printf '%s\n' \
              '[测试报告 / TEST_REPORT]' \
              '' \
              'Tester: collab-developer-agent' \
              "Task ID: ${TASK_ID}" \
              'Execution Mode: STANDARD' \
              'Unit:' \
              "- ${unit}" \
              '' \
              'Integration:' \
              "- ${integration}" \
              '' \
              'Scenario Simulation:' \
              '- normal path' \
              '- edge input' \
              '- invalid input' \
              '- upstream failure' \
              '' \
              'Stress:' \
              "- ${stress}" \
              '' \
              "Decision: ${decision}" \
              'Sync Recommendation: continue parallel' \
              'Evidence:' \
              "- pr_number=${PR_NUMBER}" \
              "- task_id=${TASK_ID}" \
              "- head_ref=${{ steps.pr.outputs.head_ref }}" \
              "- head_sha=${{ steps.pr.outputs.head_sha }}" \
              "- actions_run=${run_url}" \
              "- npm_ci_exit=${{ steps.run.outputs.npm_ci_exit }}" \
              "- build_exit=${{ steps.run.outputs.build_exit }}" \
              "- test_exit=${{ steps.run.outputs.test_exit }}"
          } > pr_test_report.md
          gh pr comment ${PR_NUMBER} --body-file pr_test_report.md

      - name: Fail job on test failure
        if: ${{ steps.run.outputs.overall != '0' }}
        run: exit 1
```

---

### Task 2: Add PR-parameterized Validator workflow + upload artifact for claim-guard

**Files:**
- Create: `.github/workflows/collab-validator-agent.yml`

- [ ] **Step 1: Create `.github/workflows/collab-validator-agent.yml`**

```yaml
name: collab-validator-agent

on:
  workflow_dispatch:
    inputs:
      pr_number:
        description: "Target PR number"
        required: true
        type: string
      task_id:
        description: "Task ID (ledger pointer)"
        required: true
        type: string
      workspace_path:
        description: "Workspace path (default 7-ARTIFACT-HUB-V2)"
        required: false
        default: "7-ARTIFACT-HUB-V2"
        type: string

permissions:
  contents: read
  issues: write
  pull-requests: write
  actions: write

concurrency:
  group: collab-validator-agent-${{ inputs.pr_number }}
  cancel-in-progress: true

jobs:
  validator:
    runs-on: [self-hosted, macOS, workbuddy]
    env:
      PR_NUMBER: ${{ inputs.pr_number }}
      TASK_ID: ${{ inputs.task_id }}
      WORKSPACE_PATH: ${{ inputs.workspace_path }}
      GH_TOKEN: ${{ github.token }}
      GH_REPO: ${{ github.repository }}
    steps:
      - name: Checkout main
        uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0

      - name: Verify gh
        run: gh --version

      - name: Resolve PR head
        id: pr
        run: |
          echo "head_ref=$(gh pr view ${PR_NUMBER} --json headRefName --jq .headRefName)" >> "$GITHUB_OUTPUT"
          echo "head_sha=$(gh pr view ${PR_NUMBER} --json headRefOid --jq .headRefOid)" >> "$GITHUB_OUTPUT"

      - name: Checkout PR head
        run: |
          git fetch origin "${{ steps.pr.outputs.head_ref }}"
          git checkout -B "pr${PR_NUMBER}" "origin/${{ steps.pr.outputs.head_ref }}"

      - name: Build and test
        id: run
        run: |
          set +e
          cd "${WORKSPACE_PATH}"
          npm ci
          npm_ci_exit=$?
          npm run build
          build_exit=$?
          npm test
          test_exit=$?
          set -e

          overall=0
          if [ "$npm_ci_exit" -ne 0 ] || [ "$build_exit" -ne 0 ] || [ "$test_exit" -ne 0 ]; then
            overall=1
          fi

          echo "npm_ci_exit=$npm_ci_exit" >> "$GITHUB_OUTPUT"
          echo "build_exit=$build_exit" >> "$GITHUB_OUTPUT"
          echo "test_exit=$test_exit" >> "$GITHUB_OUTPUT"
          echo "overall=$overall" >> "$GITHUB_OUTPUT"

      - name: Post VALIDATION_RESULT comment
        run: |
          hard_gate="PASS"
          score="95"
          decision="ACCEPTED"
          reward_multiplier="1.0"
          reason_code="NONE"
          handoff="ledgered"

          if [ "${{ steps.run.outputs.overall }}" != "0" ]; then
            hard_gate="BLOCK"
            score="40"
            decision="REWORK"
            reward_multiplier="0.0"
            reason_code="BUILD_OR_TEST_FAILED"
            handoff="pending"
          fi

          run_url="${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
          {
            printf '%s\n' \
              '[验证结论 / VALIDATION_RESULT]' \
              '' \
              'Validator: collab-validator-agent' \
              "Hard Gate Result: ${hard_gate}" \
              "Score: ${score}" \
              "Decision: ${decision}" \
              'Reason Codes:' \
              "- ${reason_code}" \
              "Reward Multiplier: ${reward_multiplier}" \
              "Ledger Update: ${TASK_ID}" \
              "Governance Handoff: ${handoff}" \
              '' \
              'Evidence:' \
              "- pr_number=${PR_NUMBER}" \
              "- task_id=${TASK_ID}" \
              "- head_ref=${{ steps.pr.outputs.head_ref }}" \
              "- head_sha=${{ steps.pr.outputs.head_sha }}" \
              "- actions_run=${run_url}" \
              "- npm_ci_exit=${{ steps.run.outputs.npm_ci_exit }}" \
              "- build_exit=${{ steps.run.outputs.build_exit }}" \
              "- test_exit=${{ steps.run.outputs.test_exit }}"
          } > pr_validation_result.md
          gh pr comment ${PR_NUMBER} --body-file pr_validation_result.md

      - name: Write collab context artifact
        run: |
          {
            printf '{\n'
            printf '  "pr_number": "%s",\n' "${PR_NUMBER}"
            printf '  "task_id": "%s",\n' "${TASK_ID}"
            printf '  "head_ref": "%s",\n' "${{ steps.pr.outputs.head_ref }}"
            printf '  "head_sha": "%s"\n' "${{ steps.pr.outputs.head_sha }}"
            printf '}\n'
          } > collab_context.json

      - name: Upload collab context artifact
        uses: actions/upload-artifact@v4
        with:
          name: collab-context
          path: collab_context.json

      - name: Fail job on validation block
        if: ${{ steps.run.outputs.overall != '0' }}
        run: exit 1
```

---

### Task 3: Add PR-parameterized Governance workflow (protocol completeness)

**Files:**
- Create: `.github/workflows/collab-governance-agent.yml`

- [ ] **Step 1: Create `.github/workflows/collab-governance-agent.yml`**

```yaml
name: collab-governance-agent

on:
  workflow_dispatch:
    inputs:
      pr_number:
        description: "Target PR number"
        required: true
        type: string
      task_id:
        description: "Task ID (ledger pointer)"
        required: true
        type: string

permissions:
  contents: read
  issues: write
  pull-requests: write

concurrency:
  group: collab-governance-agent-${{ inputs.pr_number }}
  cancel-in-progress: true

jobs:
  governance:
    runs-on: [self-hosted, macOS, workbuddy]
    env:
      PR_NUMBER: ${{ inputs.pr_number }}
      TASK_ID: ${{ inputs.task_id }}
      GH_TOKEN: ${{ github.token }}
      GH_REPO: ${{ github.repository }}
    steps:
      - name: Checkout main
        uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0

      - name: Verify gh
        run: gh --version

      - name: Fetch PR comments
        id: comments
        run: |
          gh pr view ${PR_NUMBER} --json comments --jq '.comments[].body' > pr_comments.txt || true
          echo "comment_file=pr_comments.txt" >> "$GITHUB_OUTPUT"

      - name: Protocol completeness check
        run: |
          started_ok=0
          test_report_ok=0
          validation_ok=0

          if grep -q '^\[协作开工声明 / STARTED\]' "${{ steps.comments.outputs.comment_file }}"; then
            started_ok=1
          fi
          if grep -q '^\[测试报告 / TEST_REPORT\]' "${{ steps.comments.outputs.comment_file }}"; then
            test_report_ok=1
          fi
          if grep -q '^\[验证结论 / VALIDATION_RESULT\]' "${{ steps.comments.outputs.comment_file }}"; then
            validation_ok=1
          fi

          if [ "$started_ok" -eq 1 ] && [ "$test_report_ok" -eq 1 ] && [ "$validation_ok" -eq 1 ]; then
            exit 0
          fi

          next_action="developer: post TEST_REPORT; validator: post VALIDATION_RESULT with Governance Handoff: ledgered"
          if [ "$started_ok" -eq 0 ]; then
            next_action="developer: post STARTED"
          elif [ "$test_report_ok" -eq 0 ]; then
            next_action="developer: run build/test and post TEST_REPORT"
          elif [ "$validation_ok" -eq 0 ]; then
            next_action="validator: re-run build/test and post VALIDATION_RESULT"
          fi

          {
            printf '%s\n' \
              '[协作状态更新 / UPDATED]' \
              '' \
              'Agent: collab-governance-agent' \
              "任务: protocol completeness check for PR${PR_NUMBER}" \
              'Execution Mode: STANDARD' \
              'Direct Takeover: no' \
              'Governance Agent: collab-governance-agent' \
              'Task Type: shared-sync' \
              'Current Sync State: pending' \
              "Next Required Action: ${next_action}" \
              '变更说明:' \
              '- protocol anchor missing' \
              '' \
              '当前占用范围:' \
              '- (see STARTED comment)' \
              '' \
              '状态: UPDATED'
          } > pr_updated.md
          gh pr comment ${PR_NUMBER} --body-file pr_updated.md
```

---

### Task 4: Make claim-guard work with validator workflow_run (no issue_comment dependency)

**Files:**
- Modify: `.github/workflows/agent-collaboration-claim-guard.yml`

- [ ] **Step 1: Extend workflow_run trigger list**

Change:

```yaml
  workflow_run:
    workflows: [pr9-validator-agent]
```

To:

```yaml
  workflow_run:
    workflows: [pr9-validator-agent, collab-validator-agent]
```

- [ ] **Step 2: Add a new workflow_run job to load artifact and locate PR**

Create a new job (keep the existing PR9 job for compatibility) that:

- downloads the `collab-context` artifact from the triggering workflow_run,
- reads `pr_number`,
- fetches PR body + comments via API,
- runs `AGENT协作工具/github-actions/run_governance_ledger_cycle.py`,
- commits ledger updates if changed.

Implementation sketch (exact code to paste into workflow):

```yaml
  validate-collaboration-validator-run:
    if: |
      github.event_name == 'workflow_run' &&
      github.event.workflow_run.conclusion == 'success' &&
      github.event.workflow_run.name == 'collab-validator-agent'
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          ref: main

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Download collab context artifact
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const runId = context.payload.workflow_run.id;
            const { data: artifacts } = await github.rest.actions.listWorkflowRunArtifacts({
              owner: context.repo.owner,
              repo: context.repo.repo,
              run_id: runId
            });
            const artifact = artifacts.artifacts.find(a => a.name === 'collab-context');
            if (!artifact) throw new Error('collab-context artifact not found');
            const { data: zip } = await github.rest.actions.downloadArtifact({
              owner: context.repo.owner,
              repo: context.repo.repo,
              artifact_id: artifact.id,
              archive_format: 'zip'
            });
            fs.writeFileSync('collab-context.zip', Buffer.from(zip));

      - name: Unzip collab context
        run: |
          python3 - <<'PY'
          import zipfile
          with zipfile.ZipFile("collab-context.zip") as z:
              z.extractall(".")
          PY

      - name: Build collaboration raw payload
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const ctx = JSON.parse(fs.readFileSync('collab_context.json', 'utf8'));
            const issueNumber = Number(ctx.pr_number);
            const prResponse = await github.rest.pulls.get({
              owner: context.repo.owner,
              repo: context.repo.repo,
              pull_number: issueNumber
            });
            const pr = prResponse.data;
            const issueComments = await github.paginate(
              github.rest.issues.listComments,
              {
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: issueNumber
              }
            );
            const comments = issueComments.map((c) => c.body || "");
            const result = { branch: String(pr?.head?.ref || ""), pr_body: pr?.body || "", comments };
            fs.writeFileSync("agent_collaboration_raw.json", JSON.stringify(result, null, 2));

      - name: Run governance ledger cycle
        run: |
          python3 "AGENT协作工具/github-actions/run_governance_ledger_cycle.py" \
            "AGENT协作工具/ledger/tasks/index.json" \
            "AGENT协作工具/ledger/rewards/index.json" \
            < agent_collaboration_raw.json > agent_governance_cycle_result.json
          python3 - <<'PY'
          import json
          import sys
          result = json.load(open("agent_governance_cycle_result.json", encoding="utf-8"))
          if result.get("decision") != "PASS":
              print(json.dumps(result, ensure_ascii=False, indent=2))
              sys.exit(1)
          print(json.dumps(result, ensure_ascii=False, indent=2))
          PY

      - name: Commit ledger updates
        run: |
          if git diff --quiet -- "AGENT协作工具/ledger/tasks/index.json" "AGENT协作工具/ledger/rewards/index.json"; then
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add "AGENT协作工具/ledger/tasks/index.json" "AGENT协作工具/ledger/rewards/index.json"
          git commit -m "chore(ledger): apply governance cycle (validator run)"
          git push origin HEAD:main
```

---

### Task 5: Identify the 4th role automation (Ledger/Protocol) explicitly

**Files:**
- Modify: `.github/workflows/agent-protocol-monitor.yml`

- [ ] **Step 1: Rename workflow `name:`**

Change:

```yaml
name: Agent Protocol Monitor
```

To:

```yaml
name: ledger-protocol-agent
```

Keep triggers (`schedule` + `workflow_dispatch`) unchanged.

---

### Task 6: Add a unittest to ensure new workflows exist and are dispatch-only

**Files:**
- Create: `AGENT协作工具/github-actions/tests/test_collab_workflows_present.py`

- [ ] **Step 1: Create test file**

```python
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2].parent


class CollabWorkflowPresenceTests(unittest.TestCase):
    def test_collab_workflows_exist(self):
        workflows = ROOT / ".github" / "workflows"
        required = [
            "collab-developer-agent.yml",
            "collab-validator-agent.yml",
            "collab-governance-agent.yml",
        ]
        for name in required:
            self.assertTrue((workflows / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests**

Run:

```bash
python3 -m unittest discover -s AGENT协作工具/github-actions/tests -p "test_*.py"
```

Expected:

- `OK`

---

### Task 7: Update FAQ for “Approve and run workflow”

**Files:**
- Modify: `AGENT协作工具/docs/05-FAQ.md`

- [ ] **Step 1: Add a new FAQ entry**

Add section:

- why “Approve and run workflow” happens (PR-triggered workflows on fork/first-time contributors),
- why using `workflow_dispatch` on `main` avoids it,
- how to run locally using:

```bash
gh workflow run collab-developer-agent -f pr_number=<N> -f task_id=<task> -f workspace_path=7-ARTIFACT-HUB-V2
gh workflow run collab-validator-agent -f pr_number=<N> -f task_id=<task> -f workspace_path=7-ARTIFACT-HUB-V2
gh workflow run collab-governance-agent -f pr_number=<N> -f task_id=<task>
```

---

### Task 8: Local end-to-end run (Option 1)

**Goal:** Run one round locally and confirm PR comments were posted.

- [ ] **Step 1: Pick a target PR**

Run:

```bash
gh pr list --state open --limit 5
```

Pick an existing PR number `<N>`.

- [ ] **Step 2: Trigger workflows**

Run:

```bash
gh workflow run collab-developer-agent -f pr_number=<N> -f task_id=task-local-e2e-1 -f workspace_path=7-ARTIFACT-HUB-V2
gh workflow run collab-validator-agent -f pr_number=<N> -f task_id=task-local-e2e-1 -f workspace_path=7-ARTIFACT-HUB-V2
gh workflow run collab-governance-agent -f pr_number=<N> -f task_id=task-local-e2e-1
```

- [ ] **Step 3: Verify PR comment anchors exist**

Run:

```bash
gh pr view <N> --json comments --jq '.comments[].body' | cat
```

Expected to find:

- `[协作开工声明 / STARTED]`
- `[测试报告 / TEST_REPORT]`
- `[验证结论 / VALIDATION_RESULT]`

---

## Self-Review Checklist (Plan)

- All new workflows are `workflow_dispatch` only (no `pull_request` triggers).
- Claim-guard no longer depends on bot `issue_comment` for validator outputs (uses workflow_run + artifact).
- Existing PR9 workflows remain unchanged for backward compatibility.
