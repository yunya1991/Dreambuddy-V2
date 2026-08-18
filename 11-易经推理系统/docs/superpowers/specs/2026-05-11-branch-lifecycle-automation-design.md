# Branch Lifecycle Automation Design

Date: 2026-05-11  
Status: Approved (Design)  
Scope: `dream-multiskill-v2` repository branch/PR lifecycle governance

## 1. Problem Statement

The repository has recurring branch and PR backlog risks:

- stale branches remain after PRs are merged or abandoned;
- old-history branches can fail CI gating due to no merge-base;
- empty-diff PRs still consume review and CI capacity;
- manual cleanup is inconsistent and delayed.

The goal is to add a safe automation layer that continuously marks status and handles low-risk cleanup, while preserving manual merge as the primary path for code integration.

## 2. Goals and Non-Goals

### Goals

- Continuously classify branch and PR states.
- Auto-process low-risk cleanup actions.
- Escalate medium/high-risk items with explicit labels and audit trails.
- Keep existing manual merge flows fully available.
- Provide deterministic artifacts for every automation run.

### Non-Goals

- Replacing `safe-main-merge-gate` or PR review policy.
- Direct pushes to `main`.
- Automatic force-alignment of legacy branches to `main`.
- Any destructive action on protected branches.

## 3. Operating Model

The solution uses a layered governance model:

- `L1` (low risk): automatic execution allowed.
- `L2` (medium risk): no automatic destructive action; label + comment + issue.
- `L3` (high risk): explicitly blocked from automation; manual workflow only.

This design is compatible with both scheduled operation and manual triggering via GitHub Actions.

## 4. Label Taxonomy

All automation labels use `branch-bot/*` prefix:

- `branch-bot/stale`
- `branch-bot/no-merge-base`
- `branch-bot/empty-diff`
- `branch-bot/merged-cleanup-candidate`
- `branch-bot/manual-review-required`
- `branch-bot/auto-closed`
- `branch-bot/auto-deleted`

Labeling is idempotent: applying the same label repeatedly has no side effects.

## 5. Classification Rules

### PR rules

- `empty-diff`: PR diff against `main` has no changed files.
  - Action: auto-close PR with explanation comment (`L1`).
- `stale`: no updates for `stale_days` and no active check progress.
  - Action: label + reminder comment (`L1`).
- `no-merge-base`: cannot compute merge-base with `main`.
  - Action: label + open/append audit issue (`L2`).
- `merged-cleanup-candidate`: PR already merged and head branch is non-protected.
  - Action: branch cleanup queue evaluation (`L1`).

### Branch rules

- Protected branch (`main` + configured protected set): never modified.
- Non-protected, merged, no open PR, older than `retention_days`:
  - Action: auto-delete branch (`L1`).
- Branch history anomaly (ahead/behind mismatch patterns, no-merge-base, or uncertain status):
  - Action: `manual-review-required` and audit issue (`L2/L3`).

## 6. State Machine

Core state progression:

1. `scan`
2. `classify`
3. `apply-low-risk-actions`
4. `write-audit`

Escalation path:

1. `scan`
2. `classify`
3. `label-and-escalate`
4. `await-human-decision`

Execution modes:

- `dry-run=true`: classify and emit plan only; no mutations.
- `dry-run=false`: execute allowed `L1` actions and emit full result.

## 7. Repository Changes

## 7.1 New Skill

Path:

- `skills/0-CORE/branch-lifecycle-automation/SKILL.md`

Content requirements:

- trigger intents (branch cleanup, PR backlog governance, status marking);
- policy boundaries (`L1/L2/L3`);
- manual merge priority statement;
- runbook for scheduled and manual action modes;
- failure handling and reporting format.

## 7.2 New Automation Script

Path:

- `scripts/ci/branch_lifecycle_bot.py`

Inputs:

- `--repo`
- `--dry-run`
- `--stale-days`
- `--retention-days`
- `--protected-branches`

Outputs:

- `artifacts/branch_lifecycle/scan-<timestamp>.json`
- `artifacts/branch_lifecycle/actions-<timestamp>.json`
- `artifacts/branch_lifecycle/summary-<timestamp>.json`

Script responsibilities:

- discover branch + PR state;
- evaluate rules;
- execute L1 actions when allowed;
- emit structured audit artifacts;
- produce stable exit code semantics.

## 7.3 New GitHub Workflow

Path:

- `.github/workflows/branch-lifecycle-automation.yml`

Triggers:

- `schedule` (periodic governance pass)
- `workflow_dispatch` (manual run with parameters)

Permissions (minimum practical):

- `contents: write`
- `pull-requests: write`
- `issues: write`

Workflow jobs:

- checkout + setup;
- run bot script;
- upload artifacts;
- optionally comment summary into a governance issue.

## 8. Audit, Recovery, and Safety

Audit guarantees:

- every run generates machine-readable artifacts;
- every automatic close/delete action includes rule and run ID;
- escalation cases are visible via labels and issues.

Recovery rules:

- closed PR can be reopened manually;
- deleted branch can be restored from logged head SHA;
- no automatic force-push or force-align operation.

Safety controls:

- default deny for unknown states;
- protected branches immutable by automation;
- L2/L3 paths require human action.

## 9. Integration With Existing Flows

The design must not interfere with:

- existing `safe-main-merge-gate` checks;
- existing human PR review and approval policy;
- existing manual merge tooling (`quick_merge.sh` and GitHub UI/CLI).

Automation is repository hygiene, not merge authorization.

## 10. Rollout Plan

Week 1:

- enable workflow in `dry-run=true` to collect baseline metrics.

Week 2:

- enable `L1` automatic actions with conservative thresholds.

Week 3:

- tune stale/retention thresholds and lock policy defaults.

## 11. Testing Strategy

Unit tests (script level):

- classifier coverage for each rule branch;
- idempotent label/action behavior;
- protected-branch guard checks;
- dry-run no-mutation guarantee.

Workflow-level tests:

- schedule trigger smoke run in dry-run;
- artifact upload verification;
- permission failure diagnostics.

Regression checks:

- verify no overlap/regression with `safe_main_merge_gate.py` behavior;
- verify manual merge path remains unchanged.

## 12. Success Metrics

- reduced count of stale branches and stale PRs over 14/30-day windows;
- reduced manual cleanup interventions per week;
- zero incidents on protected branches;
- zero unauthorized direct writes to `main`.

## 13. Open Decisions (Resolved)

- Automation mode: scheduled + manual dispatch both enabled.
- Manual merge policy: explicitly preserved and prioritized.
- Legacy no-merge-base handling: escalate only, no auto force-alignment.
