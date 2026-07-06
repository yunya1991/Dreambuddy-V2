# Evolution P2 Approval Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将进化发布从“仅技术门禁通过”升级为“技术门禁 + 审批票据通过”双门禁，默认 fail-closed。

**Architecture:** 在 `evolution_decision_gate.py` 中引入审批票据校验逻辑，并输出审批审计产物；同时扩展 `evolution-decision-gate.yml` 传入审批参数。审批不通过时阻断 promotion 与 rollback pointer 生成。

**Tech Stack:** Python 3.11, pytest, GitHub Actions

---

### Task 1: Add failing tests for approval gating

**Files:**
- Modify: `tests/test_ci_evolution_decision_gate.py`
- Test: `tests/test_ci_evolution_decision_gate.py`

- [ ] **Step 1: Write failing tests**

```python
def test_decision_gate_rejects_when_approval_required_but_ticket_missing(tmp_path):
    ...
    rc = mod.main([...,"--require-approval-ticket"])
    assert rc == 1
    assert "APPROVAL_TICKET_REQUIRED" in payload["reason_codes"]

def test_decision_gate_approves_when_ticket_is_valid(tmp_path):
    ...
    rc = mod.main([...,"--require-approval-ticket","--approval-ticket-json", str(ticket_path)])
    assert rc == 0
    assert payload["approval"]["decision"] == "approve"
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `pytest tests/test_ci_evolution_decision_gate.py -q`
Expected: FAIL with missing CLI args/approval fields assertions.

### Task 2: Implement approval gate in decision script

**Files:**
- Modify: `scripts/ci/evolution_decision_gate.py`
- Test: `tests/test_ci_evolution_decision_gate.py`

- [ ] **Step 1: Add CLI args and approval validator**

```python
parser.add_argument("--approval-ticket-json", default="")
parser.add_argument("--require-approval-ticket", action="store_true")
parser.add_argument("--approval-artifacts-dir", default="artifacts/evolution/approval")
```

```python
def evaluate_approval_ticket(...):
    # 校验 candidate/trace/policy_version/scope/有效期
    return {"decision": "...", "reason_codes": [...]}
```

- [ ] **Step 2: Wire validator into main flow**

```python
if gate_result["decision"] == "approve":
    approval = evaluate_approval_ticket(...)
    if approval["decision"] == "reject":
        gate_result["decision"] = "reject"
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_ci_evolution_decision_gate.py -q`
Expected: PASS.

### Task 3: Wire workflow and required CI coverage

**Files:**
- Modify: `.github/workflows/evolution-decision-gate.yml`
- Modify: `.github/workflows/safe-main-merge-gate.yml`
- Create: `artifacts/evolution/approval/approval_ticket_positive_20260511.json`

- [ ] **Step 1: Add workflow inputs and script args**

```yaml
approval_ticket_json:
  default: ""
require_approval_ticket:
  default: "true"
```

- [ ] **Step 2: Add sample ticket artifact**

```json
{
  "ticket_id": "appr-20260512-pos-001",
  "candidate_id": "cand-20260511-pos-001",
  "trace_id": "trace-p0-pos-001",
  "policy_version": "embedded.v0",
  "scope": {"to_versions": ["v0.1.1"]},
  "approved_at": "2026-05-12T00:00:00Z",
  "expires_at": "2027-05-12T00:00:00Z",
  "approver": "risk-committee"
}
```

- [ ] **Step 3: Run focused tests**

Run: `pytest tests/test_ci_evolution_decision_gate.py tests/test_ci_evolution_policy_regression_matrix.py -q`
Expected: PASS.

### Task 4: Update constraints spec and verify lint/diagnostics

**Files:**
- Create: `constraints/workflows-spec/evolution-p2-approval-gate-spec-v0.1.md`
- Modify: `constraints/workflows-spec/evolution.md`
- Modify: `constraints/workflows-spec/README.md`

- [ ] **Step 1: Add P2 approval gate spec**

```markdown
定义审批票据字段、reason_codes、失效策略（fail-closed）和审计产物路径。
```

- [ ] **Step 2: Run checks**

Run: `pytest tests/test_ci_evolution_decision_gate.py -q`
Expected: PASS.

- [ ] **Step 3: Validate diagnostics**

Run diagnostics on edited files and fix issues if present.
