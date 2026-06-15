import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import fs from "node:fs";
import { MetaStore } from "./meta-store.js";
import { MinisterAgent } from "./types.js";
import type { BoardProposal, ApprovalGate, ExecutionReview } from "./types.js";

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "meta-store-test-"));
}

describe("MetaStore Phase 3: BoardProposal", () => {
  let store: MetaStore;
  let dir: string;

  before(() => {
    dir = tmpDir();
    store = new MetaStore(dir);
  });

  after(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("addBoardProposal stores without error", () => {
    const proposal: BoardProposal = {
      proposal_id: "prop-001",
      trace_id: "trace-abc",
      department: "finance",
      decision_level: "L2",
      title: "Q3 Budget Approval",
      summary: "Approve Q3 operational budget for department",
      proposer_agent: MinisterAgent.GOVERNANCE,
      status: "submitted",
      created_at: "2026-05-18T00:00:00Z",
    };
    assert.doesNotThrow(() => store.addBoardProposal(proposal));
  });

  it("addBoardProposal rejects duplicate proposal_id", () => {
    const proposal: BoardProposal = {
      proposal_id: "prop-001",
      trace_id: "trace-dup",
      department: "ops",
      decision_level: "L1",
      title: "Duplicate",
      summary: "Should fail",
      proposer_agent: MinisterAgent.OPERATIONS,
      status: "draft",
      created_at: "2026-05-18T01:00:00Z",
    };
    assert.throws(() => store.addBoardProposal(proposal));
  });
});

describe("MetaStore Phase 3: ApprovalGate", () => {
  let store: MetaStore;
  let dir: string;

  before(() => {
    dir = tmpDir();
    store = new MetaStore(dir);
    const proposal: BoardProposal = {
      proposal_id: "prop-gate-001",
      trace_id: "trace-gate",
      department: "legal",
      decision_level: "L3",
      title: "Policy Change",
      summary: "Update internal policy",
      proposer_agent: MinisterAgent.GOVERNANCE,
      status: "under_review",
      created_at: "2026-05-18T00:00:00Z",
    };
    store.addBoardProposal(proposal);
  });

  after(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("addApprovalGate stores gate with JSON arrays", () => {
    const gate: ApprovalGate = {
      gate_id: "gate-001",
      proposal_id: "prop-gate-001",
      required_approvers: [MinisterAgent.GOVERNANCE, MinisterAgent.RESEARCH],
      received_approvals: [],
      status: "pending",
    };
    assert.doesNotThrow(() => store.addApprovalGate(gate));
  });

  it("addApprovalGate with decided_at and received approvals", () => {
    const gate: ApprovalGate = {
      gate_id: "gate-002",
      proposal_id: "prop-gate-001",
      required_approvers: [MinisterAgent.GOVERNANCE],
      received_approvals: [MinisterAgent.GOVERNANCE],
      status: "approved",
      decided_at: "2026-05-18T06:00:00Z",
    };
    assert.doesNotThrow(() => store.addApprovalGate(gate));
  });
});

describe("MetaStore Phase 3: ExecutionReview", () => {
  let store: MetaStore;
  let dir: string;

  before(() => {
    dir = tmpDir();
    store = new MetaStore(dir);
  });

  after(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("addExecutionReview and listExecutionReviews returns all when no traceId", () => {
    const review1: ExecutionReview = {
      review_id: "rev-001",
      trace_id: "trace-x",
      execution_id: "exec-001",
      reviewer_agent: MinisterAgent.GOVERNANCE,
      verdict: "pass",
      findings: "All steps completed correctly",
      recommendations: "None",
      reviewed_at: "2026-05-18T08:00:00Z",
    };
    const review2: ExecutionReview = {
      review_id: "rev-002",
      trace_id: "trace-y",
      execution_id: "exec-002",
      reviewer_agent: MinisterAgent.OPERATIONS,
      verdict: "pass_with_notes",
      findings: "Minor deviation in step 3",
      recommendations: "Update workflow template",
      reviewed_at: "2026-05-18T09:00:00Z",
    };
    store.addExecutionReview(review1);
    store.addExecutionReview(review2);

    const all = store.listExecutionReviews();
    assert.equal(all.length, 2);
  });

  it("listExecutionReviews filters by traceId", () => {
    const filtered = store.listExecutionReviews("trace-x");
    assert.equal(filtered.length, 1);
    assert.equal(filtered[0].review_id, "rev-001");
    assert.equal(filtered[0].verdict, "pass");
  });

  it("listExecutionReviews returns empty array for unknown traceId", () => {
    const result = store.listExecutionReviews("trace-nonexistent");
    assert.deepEqual(result, []);
  });

  it("addExecutionReview preserves all fields", () => {
    const review: ExecutionReview = {
      review_id: "rev-003",
      trace_id: "trace-z",
      execution_id: "exec-003",
      reviewer_agent: MinisterAgent.RESEARCH,
      verdict: "escalate",
      findings: "Critical anomaly detected",
      recommendations: "Escalate to board immediately",
      reviewed_at: "2026-05-18T10:00:00Z",
    };
    store.addExecutionReview(review);
    const results = store.listExecutionReviews("trace-z");
    assert.equal(results.length, 1);
    assert.equal(results[0].verdict, "escalate");
    assert.equal(results[0].findings, "Critical anomaly detected");
    assert.equal(results[0].reviewer_agent, MinisterAgent.RESEARCH);
  });
});
