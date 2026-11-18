import assert from "assert";
import type { EvolutionProposal } from "./types";
import { freezePrereg, type ExperimentPrereg } from "./experiment-prereg";
import { buildProposalTicket, isDirectProductionChange } from "./proposal-ticket-bridge";

let passed = 0;
let failed = 0;

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`  ok ${name}`);
    passed += 1;
  } catch (e) {
    console.error(`  FAIL ${name}: ${(e as Error).message}`);
    failed += 1;
  }
}

function prereg(): ExperimentPrereg {
  return freezePrereg({
    prereg_id: "PR-1",
    proposal_id: "PROP-1",
    hypothesis: "修复后失败率下降",
    metric: "failure_rate",
    direction: "lower_is_better",
    baseline_value: 0.2,
    success_threshold: 0.15,
    failure_threshold: 0.25,
    sample: {
      unit: "trade",
      min_size: 100,
      period_start: "2024-01-01",
      period_end: "2025-12-31",
      out_of_sample_ratio: 0.3,
    },
    stopping_rule: "达到样本量即停止",
    registered_at: "2026-01-01T00:00:00Z",
    locked: false,
  });
}

function proposal(over: Partial<EvolutionProposal> = {}): EvolutionProposal {
  return {
    id: "PROP-1",
    finding_id: "F-1",
    title: "修复执行失败",
    description: "降低失败率",
    change_type: "code_change",
    requires_code: true,
    rollback_plan_id: "rb-1",
    evidence_refs: ["F-1"],
    prereg_id: "PR-1",
    status: "pending_review",
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

test("合法提案生成 Ticket 且禁止直写", () => {
  const out = buildProposalTicket(proposal(), prereg());
  assert.ok(out.ok);
  if (out.ok) {
    assert.strictEqual(out.ticket.ticket_id, "TK-EVO-PROP-1");
    assert.strictEqual(out.ticket.required_verdict_level, "U2");
    assert.strictEqual(out.ticket.risk_level, "high");
    assert.strictEqual(out.ticket.direct_write, false);
    assert.ok(out.ticket.gates.includes("acceptance"));
    assert.strictEqual(out.ticket.prereg_id, "PR-1");
  }
});

function blockers(out: ReturnType<typeof buildProposalTicket>): string[] {
  assert.strictEqual(out.ok, false);
  return out.ok ? [] : out.blockers;
}

test("缺预注册被拒", () => {
  const out = buildProposalTicket(proposal({ prereg_id: undefined }), prereg());
  assert.ok(blockers(out).includes("missing_prereg"));
});

test("预注册对象缺失被拒", () => {
  const out = buildProposalTicket(proposal(), null);
  assert.ok(blockers(out).includes("missing_prereg"));
});

test("预注册未冻结被拒", () => {
  const p = { ...prereg(), locked: false };
  const out = buildProposalTicket(proposal(), p);
  assert.ok(blockers(out).includes("prereg_not_locked"));
});

test("预注册被篡改被拒", () => {
  const tampered = { ...prereg(), success_threshold: 0.2 };
  const out = buildProposalTicket(proposal(), tampered);
  assert.ok(blockers(out).includes("prereg_tampered"));
});

test("缺回滚计划被拒", () => {
  const out = buildProposalTicket(proposal({ rollback_plan_id: "" }), prereg());
  assert.ok(blockers(out).includes("missing_rollback"));
});

test("缺证据被拒", () => {
  const out = buildProposalTicket(proposal({ evidence_refs: [] }), prereg());
  assert.ok(blockers(out).includes("missing_evidence"));
});

test("已实施提案被拒", () => {
  const out = buildProposalTicket(proposal({ status: "implemented" }), prereg());
  assert.ok(blockers(out).includes("already_implemented"));
});

test("直改生产标记被拒", () => {
  const p = { ...proposal(), direct_production: true } as EvolutionProposal;
  assert.strictEqual(isDirectProductionChange(p), true);
  const out = buildProposalTicket(p, prereg());
  assert.ok(blockers(out).includes("direct_production_forbidden"));
});

test("纯知识变更不生成 Ticket", () => {
  const p = proposal({
    requires_code: false,
    change_type: "knowledge_update",
  });
  const out = buildProposalTicket(p, prereg());
  assert.ok(blockers(out).includes("not_code_change"));
});

test("多阻断项一次返回", () => {
  const out = buildProposalTicket(
    proposal({ rollback_plan_id: "", evidence_refs: [] }),
    null,
  );
  const codes = blockers(out);
  assert.ok(codes.includes("missing_rollback"));
  assert.ok(codes.includes("missing_evidence"));
  assert.ok(codes.includes("missing_prereg"));
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
